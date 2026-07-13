import datetime as dt
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from paper_monitor.article_lifecycle import (
    ArticleDetection,
    ArticleLifecycle,
    NotificationDelivery,
    RefreshCommit,
    RefreshRunStatus,
)
from paper_monitor.models import Article
from paper_monitor.storage import ArticleStore


class FakeNotifier:
    def __init__(self):
        self.notifications = []

    def deliver(self, notification):
        self.notifications.append(notification)
        return NotificationDelivery.ACCEPTED


def legacy_article(suffix: str = "1") -> Article:
    return Article(
        title=f"Legacy battery article {suffix}",
        journal="Journal of Batteries",
        url=f"https://legacy.example/articles/{suffix}",
        doi=f"10.1000/legacy-{suffix}",
        published="2026-07-01",
        detected="2026-07-02",
        abstract=f"legacy abstract {suffix} must not migrate",
        source="Crossref",
    )


def detection(article: Article) -> ArticleDetection:
    return ArticleDetection(
        title=article.title,
        authors=(),
        journal=article.journal,
        impact_reference=None,
        url=article.url,
        doi=article.doi,
        source=article.source,
        published=article.published,
    )


class ArticleLifecycleMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "articles.sqlite3"
        self.clock_value = dt.datetime(2026, 7, 13, 12, tzinfo=dt.timezone.utc)
        self.clock = lambda: self.clock_value

    def legacy_store(self, *articles: Article) -> ArticleStore:
        store = ArticleStore(self.database_path)
        store.add_new_articles(articles)
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            connection.execute(
                "UPDATE articles SET first_seen_at = '2026-07-13 00:00:00'"
            )
            connection.commit()
        return store

    def commit_redetection(self, lifecycle: ArticleLifecycle, run_id: str, article: Article):
        return lifecycle.commit_refresh(
            RefreshCommit(
                run_id=run_id,
                status=RefreshRunStatus.SUCCEEDED,
                detections=(detection(article),),
                fetched=1,
                matched=1,
            )
        )

    def test_active_legacy_articles_migrate_once_without_abstract_or_duplicate_notification(self):
        article = legacy_article()
        self.legacy_store(article)

        lifecycle = ArticleLifecycle(self.database_path, _clock=self.clock)
        first_snapshot = lifecycle.dashboard_snapshot()
        second_lifecycle = ArticleLifecycle(self.database_path, _clock=self.clock)
        second_snapshot = second_lifecycle.dashboard_snapshot()

        self.assertEqual(len(first_snapshot.articles), 1)
        self.assertEqual(len(second_snapshot.articles), 1)
        self.assertEqual(first_snapshot.articles[0].title, article.title)
        self.assertFalse(hasattr(first_snapshot.articles[0], "abstract"))

        outcome = self.commit_redetection(second_lifecycle, "redetected-run", article)
        notifier = FakeNotifier()
        notification = second_lifecycle.deliver_notification("redetected-run", notifier)
        self.assertEqual(outcome.new_count, 0)
        self.assertEqual(notification.state, "not_needed")
        self.assertEqual(notifier.notifications, [])

    def test_unattempted_legacy_outbox_remains_eligible_but_attempted_item_is_suppressed(self):
        pending_article = legacy_article("pending")
        attempted_article = legacy_article("attempted")
        store = self.legacy_store(pending_article, attempted_article)
        store.enqueue_notifications(
            [
                {
                    "identity": pending_article.identity,
                    "title": pending_article.title,
                    "journal": pending_article.journal,
                    "url": pending_article.url,
                    "doi": pending_article.doi,
                    "published": pending_article.published,
                    "source": pending_article.source,
                },
                {
                    "identity": attempted_article.identity,
                    "title": attempted_article.title,
                    "journal": attempted_article.journal,
                    "url": attempted_article.url,
                    "doi": attempted_article.doi,
                    "published": attempted_article.published,
                    "source": attempted_article.source,
                },
            ]
        )
        pending_rows = store.pending_notifications()
        attempted_id = next(
            int(row["id"])
            for row in pending_rows
            if row["article"]["doi"] == attempted_article.doi
        )
        store.mark_notification_failed(attempted_id, "delivery state unknown")

        lifecycle = ArticleLifecycle(self.database_path, _clock=self.clock)
        self.commit_redetection(lifecycle, "pending-run", pending_article)
        self.commit_redetection(lifecycle, "attempted-run", attempted_article)
        notifier = FakeNotifier()

        pending = lifecycle.deliver_notification("pending-run", notifier)
        attempted = lifecycle.deliver_notification("attempted-run", notifier)

        self.assertEqual(pending.delivery, NotificationDelivery.ACCEPTED)
        self.assertEqual(attempted.state, "not_needed")
        self.assertEqual(len(notifier.notifications), 1)

    def test_attempted_outbox_alias_wins_over_pending_alias_for_same_article(self):
        article = legacy_article("same-article")
        store = self.legacy_store(article)
        payload = {
            "title": article.title,
            "journal": article.journal,
            "url": article.url,
            "doi": article.doi,
            "published": article.published,
            "source": article.source,
        }
        store.enqueue_notifications(
            [
                {**payload, "identity": "pending-alias"},
                {**payload, "identity": "attempted-alias"},
            ]
        )
        attempted_id = next(
            int(row["id"])
            for row in store.pending_notifications()
            if row["article"]["identity"] == "attempted-alias"
        )
        store.mark_notification_failed(attempted_id, "delivery state unknown")

        lifecycle = ArticleLifecycle(self.database_path, _clock=self.clock)
        self.commit_redetection(lifecycle, "same-article-run", article)
        notifier = FakeNotifier()
        outcome = lifecycle.deliver_notification("same-article-run", notifier)

        self.assertEqual(outcome.state, "not_needed")
        self.assertEqual(notifier.notifications, [])

    def test_expired_legacy_article_becomes_fingerprint_without_copying_metadata(self):
        article = legacy_article("expired")
        store = self.legacy_store(article)
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            connection.execute(
                "UPDATE articles SET first_seen_at = '2026-05-01 00:00:00'"
            )
            connection.commit()

        lifecycle = ArticleLifecycle(self.database_path, _clock=self.clock)
        self.assertEqual(lifecycle.dashboard_snapshot().articles, ())
        redetected = self.commit_redetection(lifecycle, "expired-redetection", article)

        self.assertEqual(redetected.new_count, 0)
        self.assertEqual(redetected.active_count, 0)
        self.assertEqual(lifecycle.dashboard_snapshot().articles, ())
        self.assertEqual(len(store.recent_articles()), 1)

    def test_migration_failure_rolls_back_all_new_state_and_can_retry(self):
        first = legacy_article("first")
        second = legacy_article("second")
        self.legacy_store(first, second)
        original = ArticleLifecycle._migrate_legacy_article
        calls = 0

        def fail_on_second(instance, connection, row, migrated_at, cutoff, now):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected migration failure")
            return original(instance, connection, row, migrated_at, cutoff, now)

        with mock.patch.object(
            ArticleLifecycle,
            "_migrate_legacy_article",
            new=fail_on_second,
        ):
            with self.assertRaisesRegex(RuntimeError, "injected migration failure"):
                ArticleLifecycle(self.database_path, _clock=self.clock)

        with closing(sqlite3.connect(str(self.database_path))) as connection:
            migrated_count = connection.execute(
                "SELECT COUNT(*) FROM lifecycle_articles"
            ).fetchone()[0]
            marker_count = connection.execute(
                "SELECT COUNT(*) FROM lifecycle_migrations"
            ).fetchone()[0]
            legacy_count = connection.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        self.assertEqual(migrated_count, 0)
        self.assertEqual(marker_count, 0)
        self.assertEqual(legacy_count, 2)

        lifecycle = ArticleLifecycle(self.database_path, _clock=self.clock)
        self.assertEqual(len(lifecycle.dashboard_snapshot().articles), 2)

    def test_canonical_doi_migration_merges_old_query_suffix_duplicates(self):
        article = Article(
            title="Duplicate publisher article",
            journal="Advanced Materials",
            url="https://doi.org/10.1002/adma.74049",
            doi="10.1002/adma.74049",
            published="2026-07-12",
            abstract="",
            source="Crossref",
        )
        lifecycle = ArticleLifecycle(self.database_path, _clock=self.clock)
        self.commit_redetection(lifecycle, "canonical-run", article)

        source_alias = hashlib.sha256(
            b"source:advanced materials:publisher-work-74049"
        ).digest()
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            canonical_id = connection.execute(
                "SELECT article_id FROM lifecycle_articles"
            ).fetchone()[0]
            connection.execute(
                "DELETE FROM lifecycle_migrations WHERE name = 'canonical-doi-query-v1'"
            )
            connection.execute(
                """
                INSERT INTO lifecycle_articles (
                    article_id, title, authors_json, journal, impact_reference, url, doi,
                    source, source_id, published, first_detected_at, last_detected_at,
                    presented_at, notified_at, notification_state
                )
                VALUES (?, ?, '[]', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'consumed')
                """,
                (
                    "old-query-suffix-duplicate",
                    article.title,
                    article.journal,
                    21.2,
                    "https://publisher.example/doi/10.1002/adma.74049?af=R",
                    "10.1002/adma.74049?af=R",
                    "Advanced Materials",
                    "publisher-work-74049",
                    article.published,
                    "2026-07-12T00:00:00Z",
                    "2026-07-13T00:00:00Z",
                    "2026-07-13T00:00:00Z",
                ),
            )
            connection.execute(
                """
                INSERT INTO lifecycle_article_aliases (alias_hash, article_id)
                VALUES (?, 'old-query-suffix-duplicate')
                """,
                (source_alias,),
            )
            connection.commit()

        migrated = ArticleLifecycle(self.database_path, _clock=self.clock)
        snapshot = migrated.dashboard_snapshot()
        with closing(sqlite3.connect(str(self.database_path))) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT article_id, doi, presented_at, notification_state FROM lifecycle_articles"
            ).fetchall()
            alias_owner = connection.execute(
                "SELECT article_id FROM lifecycle_article_aliases WHERE alias_hash = ?",
                (source_alias,),
            ).fetchone()[0]
            details = json.loads(
                connection.execute(
                    "SELECT details_json FROM lifecycle_migrations WHERE name = 'canonical-doi-query-v1'"
                ).fetchone()[0]
            )

        self.assertEqual(len(snapshot.articles), 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["article_id"], canonical_id)
        self.assertEqual(rows[0]["doi"], article.doi)
        self.assertEqual(rows[0]["notification_state"], "consumed")
        self.assertTrue(rows[0]["presented_at"])
        self.assertEqual(alias_owner, canonical_id)
        self.assertEqual(details, {"corrected": 1, "merged": 1})

        repeated = self.commit_redetection(
            migrated,
            "publisher-repeat",
            Article(
                title=article.title,
                journal=article.journal,
                url="https://publisher.example/doi/10.1002/adma.74049?af=R",
                doi="10.1002/adma.74049?af=R",
                published=article.published,
                abstract="",
                source="Advanced Materials",
                source_id="publisher-work-74049",
            ),
        )
        self.assertEqual(repeated.new_count, 0)


if __name__ == "__main__":
    unittest.main()
