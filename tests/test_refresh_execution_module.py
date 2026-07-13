import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from paper_monitor.article_lifecycle import (
    ArticleLifecycle,
    NotificationDelivery,
    RefreshCommit,
    RefreshRunStatus,
)
from paper_monitor.filtering import FilterConfig
from paper_monitor.journal_metrics import JournalMetric, JournalMetrics
from paper_monitor.models import Article
from paper_monitor.monitor import MonitorConfig
from paper_monitor.refresh_errors import RefreshAlreadyRunning
from paper_monitor.refresh_execution import RefreshExecution, RefreshIntent
from paper_monitor.sources import SourceFetchResult


class FakeNotifier:
    def __init__(self, response=NotificationDelivery.ACCEPTED):
        self.response = response
        self.notifications = []

    def deliver(self, notification):
        self.notifications.append(notification)
        return self.response


def article(title="Solid-state battery discovery", *, abstract="secret searchable abstract"):
    return Article(
        title=title,
        journal="Journal of Batteries",
        url="https://example.org/article",
        doi="10.1000/example",
        published="2026-07-01",
        abstract=abstract,
        source="Crossref",
        authors=("Ada Lovelace",),
        source_id="crossref-work-1",
    )


class RefreshExecutionModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "articles.sqlite3"
        self.config_path = Path(self.temp_dir.name) / "config.json"
        self.lifecycle = ArticleLifecycle(self.database_path)
        self.notifier = FakeNotifier()
        self.config = SimpleNamespace(
            database_path=self.database_path,
            journal_metrics_path=Path(self.temp_dir.name) / "journal_metrics.json",
            source_config={"crossref": {"enabled": True}},
            monitor_config=MonitorConfig(
                filter_config=FilterConfig(
                    include_terms=["solid-state battery"],
                    exclude_terms=[],
                    journals=["Journal of Batteries"],
                ),
                max_notifications=5,
            ),
            app_settings=SimpleNamespace(notifications_enabled=True),
        )
        self.metrics = JournalMetrics(
            [
                JournalMetric(
                    journal="Journal of Batteries",
                    aliases=[],
                    impact_factor=9.25,
                    impact_factor_year=2026,
                    five_year_impact_factor=None,
                    level="reference",
                    source_url="",
                )
            ]
        )

    def execution(self, results, *, run_ids=("run-1",), acquire_mutex=lambda: object()):
        result_iterator = iter(results)
        run_id_iterator = iter(run_ids)
        dependencies = SimpleNamespace(
            load_config=lambda _path: self.config,
            fetch_sources=lambda _source_config: next(result_iterator),
            load_metrics=lambda _path: self.metrics,
            lifecycle_factory=lambda _path: self.lifecycle,
            notification_adapter_factory=lambda _config: self.notifier,
            acquire_refresh_mutex=acquire_mutex,
            close_refresh_mutex=lambda _handle: None,
            new_run_id=lambda: next(run_id_iterator),
        )
        with mock.patch(
            "paper_monitor.refresh_execution._production_dependencies",
            return_value=dependencies,
        ):
            return RefreshExecution(self.config_path)

    def test_background_execution_matches_transient_abstract_and_commits_compact_listing(self):
        fetched = SourceFetchResult(
            [article(), article(title="Unrelated catalysis", abstract="nothing relevant")],
            [{"source": "Crossref", "status": "succeeded", "count": 2, "error": ""}],
        )
        execution = self.execution([fetched])

        outcome = execution.execute(RefreshIntent.BACKGROUND)
        snapshot = self.lifecycle.dashboard_snapshot()

        self.assertEqual(outcome.status, RefreshRunStatus.SUCCEEDED)
        self.assertEqual(outcome.fetched, 2)
        self.assertEqual(outcome.matched, 1)
        self.assertEqual(outcome.new_matches, 1)
        self.assertEqual(outcome.skipped, 1)
        self.assertEqual(outcome.notification.delivery, NotificationDelivery.ACCEPTED)
        self.assertEqual(len(self.notifier.notifications), 1)
        self.assertEqual(len(snapshot.articles), 1)
        self.assertEqual(snapshot.articles[0].impact_reference, 9.25)
        self.assertFalse(hasattr(snapshot.articles[0], "abstract"))

    def test_visible_execution_returns_snapshot_and_presentation_suppresses_later_background_notice(self):
        first = SourceFetchResult(
            [article()],
            [{"source": "Crossref", "status": "succeeded", "count": 1, "error": ""}],
        )
        second = SourceFetchResult(
            [article()],
            [{"source": "Crossref", "status": "succeeded", "count": 1, "error": ""}],
        )
        execution = self.execution([first, second], run_ids=("visible-run", "background-run"))

        visible = execution.execute(RefreshIntent.VISIBLE)
        self.assertIsNotNone(visible.snapshot)
        self.assertIsNone(visible.notification)
        self.assertEqual(self.notifier.notifications, [])
        self.assertEqual(self.lifecycle.confirm_presentation(visible.snapshot.presentation_token), 1)

        background = execution.execute(RefreshIntent.BACKGROUND)
        self.assertEqual(background.new_matches, 0)
        self.assertEqual(background.notification.state, "not_needed")
        self.assertEqual(self.notifier.notifications, [])

    def test_partial_execution_keeps_successful_source_articles(self):
        fetched = SourceFetchResult(
            [article()],
            [
                {"source": "Crossref", "status": "succeeded", "count": 1, "error": ""},
                {"source": "RSS", "status": "failed", "count": 0, "error": "timeout"},
            ],
        )
        outcome = self.execution([fetched], run_ids=("partial-run",)).execute(
            RefreshIntent.BACKGROUND
        )

        self.assertEqual(outcome.status, RefreshRunStatus.PARTIAL)
        self.assertEqual(outcome.new_matches, 1)
        self.assertIn("RSS: timeout", outcome.error)
        self.assertEqual(len(self.lifecycle.dashboard_snapshot().articles), 1)
        self.assertEqual(outcome.notification.delivery, NotificationDelivery.ACCEPTED)

    def test_missing_notification_adapter_is_explicit_and_keeps_article_eligible(self):
        fetched = SourceFetchResult(
            [article()],
            [{"source": "Crossref", "status": "succeeded", "count": 1, "error": ""}],
        )
        self.notifier = None
        outcome = self.execution([fetched], run_ids=("deferred-run",)).execute(
            RefreshIntent.BACKGROUND
        )

        self.assertEqual(outcome.notification.state, "deferred")
        self.assertFalse(outcome.notification.attempted)
        self.assertEqual(outcome.commit.notification_eligible_count, 1)

        self.notifier = FakeNotifier()
        repeated = SourceFetchResult(
            [article()],
            [{"source": "Crossref", "status": "succeeded", "count": 1, "error": ""}],
        )
        retry = self.execution([repeated], run_ids=("adapter-ready-run",)).execute(
            RefreshIntent.BACKGROUND
        )
        self.assertEqual(retry.notification.delivery, NotificationDelivery.ACCEPTED)
        self.assertEqual(len(self.notifier.notifications), 1)

    def test_all_sources_failed_records_failure_without_erasing_existing_listing(self):
        self.lifecycle.commit_refresh(
            RefreshCommit(
                run_id="seed-run",
                status=RefreshRunStatus.SUCCEEDED,
                detections=(),
            )
        )
        successful = SourceFetchResult(
            [article()],
            [{"source": "Crossref", "status": "succeeded", "count": 1, "error": ""}],
        )
        failed = SourceFetchResult(
            [],
            [{"source": "Crossref", "status": "failed", "count": 0, "error": "offline"}],
        )
        execution = self.execution(
            [successful, failed],
            run_ids=("successful-run", "failed-run"),
        )
        execution.execute(RefreshIntent.BACKGROUND)

        outcome = execution.execute(RefreshIntent.BACKGROUND)

        self.assertEqual(outcome.status, RefreshRunStatus.FAILED)
        self.assertEqual(outcome.new_matches, 0)
        self.assertIsNone(outcome.notification)
        self.assertIn("offline", outcome.error)
        self.assertEqual(len(self.lifecycle.dashboard_snapshot().articles), 1)

    def test_cross_process_mutex_rejection_uses_shared_already_running_error(self):
        execution = self.execution([], acquire_mutex=lambda: None)

        with self.assertRaises(RefreshAlreadyRunning):
            execution.execute(RefreshIntent.BACKGROUND)


if __name__ == "__main__":
    unittest.main()
