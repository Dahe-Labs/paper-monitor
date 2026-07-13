import datetime as dt
import tempfile
import unittest
from pathlib import Path

from paper_monitor.article_lifecycle import (
    ArticleDetection,
    ArticleLifecycle,
    NotificationDelivery,
    RefreshCommit,
    RefreshRunStatus,
    UnknownPresentationToken,
)
from paper_monitor.models import Article
from paper_monitor.storage import ArticleStore


class MutableClock:
    def __init__(self, value: dt.datetime):
        self.value = value

    def __call__(self) -> dt.datetime:
        return self.value

    def advance(self, *, days: int) -> None:
        self.value += dt.timedelta(days=days)


class FakeNotifier:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.notifications = []

    def deliver(self, notification):
        self.notifications.append(notification)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def detection(
    suffix: str = "1",
    *,
    doi: str = "",
    url: str = "",
    title: str = "Solid electrolyte interface",
    source_id: str = "",
) -> ArticleDetection:
    return ArticleDetection(
        title=title,
        authors=("Ada Lovelace", "Grace Hopper"),
        journal="Journal of Batteries",
        impact_reference=9.25,
        url=url or f"https://example.org/articles/{suffix}",
        doi=doi,
        source="Crossref",
        source_id=source_id,
        published="2026-07-01",
    )


class ArticleLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.clock = MutableClock(dt.datetime(2026, 7, 13, 12, tzinfo=dt.timezone.utc))
        self.lifecycle = ArticleLifecycle(
            Path(self.temp_dir.name) / "articles.sqlite3",
            _clock=self.clock,
        )

    def commit(self, run_id: str, *detections: ArticleDetection, status=RefreshRunStatus.SUCCEEDED):
        return self.lifecycle.commit_refresh(
            RefreshCommit(
                run_id=run_id,
                status=status,
                detections=tuple(detections),
                fetched=len(detections),
                matched=len(detections),
            )
        )

    def test_commit_is_idempotent_and_exact_aliases_merge_metadata(self):
        first = detection(doi="https://doi.org/10.1000/ABC", url="https://example.org/a?utm_source=test")
        corrected = detection(
            doi="doi:10.1000/abc",
            url="https://publisher.example/new-location",
            title="Corrected solid electrolyte interface",
        )

        first_outcome = self.commit("run-1", first)
        second_outcome = self.commit("run-2", corrected)
        repeated_outcome = self.commit("run-2", first)
        snapshot = self.lifecycle.dashboard_snapshot()

        self.assertEqual(first_outcome.new_count, 1)
        self.assertEqual(second_outcome.new_count, 0)
        self.assertEqual(repeated_outcome, second_outcome)
        self.assertEqual(len(snapshot.articles), 1)
        self.assertEqual(snapshot.articles[0].title, corrected.title)
        self.assertEqual(snapshot.articles[0].impact_reference, 9.25)
        self.assertFalse(hasattr(snapshot.articles[0], "abstract"))

    def test_source_id_and_exact_title_author_year_are_strict_aliases(self):
        first = detection(source_id="work-42", url="https://example.org/old")
        moved = detection(source_id="work-42", url="https://example.org/new")
        same_bibliography = detection(
            source_id="",
            url="https://third.example/article",
            title=first.title,
        )
        different_title = detection(
            suffix="different",
            source_id="",
            title=first.title + " review",
        )

        self.commit("run-source", first)
        self.assertEqual(self.commit("run-moved", moved).new_count, 0)
        self.assertEqual(self.commit("run-bibliography", same_bibliography).new_count, 0)
        self.assertEqual(self.commit("run-different", different_title).new_count, 1)
        self.assertEqual(len(self.lifecycle.dashboard_snapshot().articles), 2)

    def test_confirmed_presentation_permanently_suppresses_notification(self):
        self.commit("run-presented", detection())
        snapshot = self.lifecycle.dashboard_snapshot()

        self.assertEqual(self.lifecycle.confirm_presentation(snapshot.presentation_token), 1)
        self.assertEqual(self.lifecycle.confirm_presentation(snapshot.presentation_token), 0)
        notifier = FakeNotifier(NotificationDelivery.ACCEPTED)
        outcome = self.lifecycle.deliver_notification("run-presented", notifier)

        self.assertEqual(outcome.state, "not_needed")
        self.assertFalse(outcome.attempted)
        self.assertEqual(notifier.notifications, [])
        with self.assertRaises(UnknownPresentationToken):
            self.lifecycle.confirm_presentation("unknown")

    def test_one_notification_summarizes_run_and_is_never_repeated_after_acceptance(self):
        self.commit("run-many", *(detection(str(index), title=f"Article {index}") for index in range(4)))
        notifier = FakeNotifier(NotificationDelivery.ACCEPTED)

        first = self.lifecycle.deliver_notification("run-many", notifier)
        second = self.lifecycle.deliver_notification("run-many", notifier)

        self.assertTrue(first.attempted)
        self.assertEqual(first.delivery, NotificationDelivery.ACCEPTED)
        self.assertEqual(first.article_count, 4)
        self.assertEqual(first.notification.heading, "4 new articles detected")
        self.assertEqual(len(first.notification.preview_titles), 3)
        self.assertFalse(second.attempted)
        self.assertEqual(second.state, "accepted")
        self.assertEqual(len(notifier.notifications), 1)

    def test_only_clear_rejection_retries_and_ambiguous_failure_is_consumed(self):
        self.commit("run-retry", detection("retry", title="Retryable article"))
        retrying = FakeNotifier(NotificationDelivery.REJECTED, NotificationDelivery.ACCEPTED)

        rejected = self.lifecycle.deliver_notification("run-retry", retrying)
        accepted = self.lifecycle.deliver_notification("run-retry", retrying)
        repeated = self.lifecycle.deliver_notification("run-retry", retrying)

        self.assertEqual(rejected.delivery, NotificationDelivery.REJECTED)
        self.assertEqual(accepted.delivery, NotificationDelivery.ACCEPTED)
        self.assertFalse(repeated.attempted)
        self.assertEqual(len(retrying.notifications), 2)

        self.commit("run-ambiguous", detection("ambiguous", title="Ambiguous article"))
        ambiguous_notifier = FakeNotifier(RuntimeError("delivery state unknown"))
        ambiguous = self.lifecycle.deliver_notification("run-ambiguous", ambiguous_notifier)
        ambiguous_repeat = self.lifecycle.deliver_notification("run-ambiguous", ambiguous_notifier)

        self.assertEqual(ambiguous.delivery, NotificationDelivery.AMBIGUOUS)
        self.assertIn("delivery state unknown", ambiguous.error)
        self.assertFalse(ambiguous_repeat.attempted)
        self.assertEqual(len(ambiguous_notifier.notifications), 1)

    def test_expired_listing_is_deleted_and_retired_fingerprint_blocks_redetection(self):
        article = detection(doi="10.1000/expired")
        self.commit("run-original", article)

        self.clock.advance(days=31)
        self.assertEqual(self.lifecycle.dashboard_snapshot().articles, ())
        redetected = self.commit("run-redetected", article)

        self.assertEqual(redetected.new_count, 0)
        self.assertEqual(redetected.active_count, 0)
        self.assertEqual(self.lifecycle.dashboard_snapshot().articles, ())

    def test_failed_run_preserves_existing_listing(self):
        self.commit("run-success", detection())
        failure = self.lifecycle.commit_refresh(
            RefreshCommit(
                run_id="run-failed",
                status=RefreshRunStatus.FAILED,
                source_statuses=({"source": "Crossref", "status": "failed"},),
                error="network unavailable",
            )
        )

        self.assertEqual(failure.status, RefreshRunStatus.FAILED)
        self.assertEqual(failure.active_count, 0)
        self.assertEqual(len(self.lifecycle.dashboard_snapshot().articles), 1)

    def test_additive_tables_coexist_with_legacy_article_store_during_migration(self):
        database_path = Path(self.temp_dir.name) / "coexistence.sqlite3"
        legacy_store = ArticleStore(database_path)
        legacy_store.add_new_articles(
            [
                Article(
                    title="Legacy article",
                    journal="Legacy Journal",
                    url="https://legacy.example/article",
                    doi="10.1000/legacy",
                    published="2026-06-01",
                    abstract="legacy abstract",
                    source="Legacy",
                )
            ]
        )
        lifecycle = ArticleLifecycle(database_path, _clock=self.clock)
        lifecycle.commit_refresh(
            RefreshCommit(
                run_id="new-lifecycle-run",
                status=RefreshRunStatus.SUCCEEDED,
                detections=(detection(doi="10.1000/new-lifecycle"),),
                fetched=1,
                matched=1,
            )
        )

        self.assertEqual(len(legacy_store.recent_articles()), 1)
        self.assertEqual(len(lifecycle.dashboard_snapshot().articles), 1)


if __name__ == "__main__":
    unittest.main()
