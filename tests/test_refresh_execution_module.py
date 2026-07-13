import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlsplit

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

    def test_production_source_adapters_feed_one_refresh_without_duplicate_redetection(self):
        metrics_path = Path(self.temp_dir.name) / "metrics.json"
        metrics_path.write_text(
            json.dumps(
                {
                    "journals": [
                        {
                            "journal": "Nature Energy",
                            "aliases": [],
                            "impact_factor": 12.5,
                            "impact_factor_year": 2026,
                            "five_year_impact_factor": None,
                            "level": "reference",
                            "source_url": "",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.config_path.write_text(
            json.dumps(
                {
                    "database_path": str(self.database_path),
                    "journal_metrics_path": str(metrics_path),
                    "include_terms": ["solid electrolyte"],
                    "exclude_terms": [],
                    "journal_scope": {
                        "top_n": 1,
                        "selected_journals": ["Nature Energy"],
                    },
                    "app_settings": {
                        "startup_enabled": False,
                        "show_tray_icon": True,
                        "notifications_enabled": False,
                    },
                    "sources": {
                        "rss": [{"name": "Nature Energy", "url": "https://feed.example/rss"}],
                        "crossref": {
                            "enabled": True,
                            "days_back": 30,
                            "rows_per_journal": 10,
                            "retry_count": 0,
                            "min_request_interval_seconds": 0,
                        },
                        "openalex": {
                            "enabled": True,
                            "days_back": 30,
                            "per_page": 10,
                            "max_pages": 1,
                            "api_key": "test-key",
                        },
                        "arxiv": {"enabled": False},
                    },
                }
            ),
            encoding="utf-8",
        )
        generation = {"value": 1}
        requested_hosts = []

        def fetch(url, timeout=30):
            del timeout
            host = urlsplit(url).hostname
            requested_hosts.append(host)
            suffix = generation["value"]
            if host == "feed.example":
                return f"""<?xml version="1.0"?>
                <rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
                  <channel><title>Nature Energy</title><item>
                    <guid isPermaLink="false">rss-work-1</guid>
                    <title>RSS solid electrolyte discovery</title>
                    <link>https://publisher.example/rss-{suffix}</link>
                    <description>transient RSS abstract</description>
                    <dc:creator>RSS Author</dc:creator>
                    <pubDate>Mon, 13 Jul 2026 09:00:00 GMT</pubDate>
                  </item></channel>
                </rss>""".encode("utf-8")
            if host == "api.crossref.org":
                return json.dumps(
                    {
                        "message": {
                            "items": [
                                {
                                    "title": ["Crossref solid electrolyte discovery"],
                                    "container-title": ["Nature Energy"],
                                    "DOI": "10.1000/crossref-stable",
                                    "URL": f"https://publisher.example/crossref-{suffix}",
                                    "abstract": "transient Crossref abstract",
                                    "published": {"date-parts": [[2026, 7, 13]]},
                                    "author": [{"given": "Crossref", "family": "Author"}],
                                }
                            ]
                        }
                    }
                ).encode("utf-8")
            if host == "api.openalex.org":
                return json.dumps(
                    {
                        "results": [
                            {
                                "id": "https://openalex.org/W987654321",
                                "display_name": "OpenAlex solid electrolyte discovery",
                                "doi": None,
                                "publication_date": "2026-07-13",
                                "primary_location": {
                                    "landing_page_url": f"https://publisher.example/openalex-{suffix}",
                                    "source": {"display_name": "Nature Energy"},
                                },
                                "abstract_inverted_index": {
                                    "transient": [0],
                                    "OpenAlex": [1],
                                    "abstract": [2],
                                },
                                "authorships": [
                                    {"author": {"display_name": "OpenAlex Author"}},
                                ],
                            }
                        ],
                        "meta": {},
                    }
                ).encode("utf-8")
            raise AssertionError(f"unexpected source URL: {url}")

        with (
            mock.patch("paper_monitor.sources.fetch_url", side_effect=fetch),
            mock.patch("paper_monitor.refresh_execution.acquire_mutex", return_value=object()),
            mock.patch("paper_monitor.refresh_execution.close_handle"),
        ):
            execution = RefreshExecution(self.config_path)
            first = execution.execute(RefreshIntent.VISIBLE)
            generation["value"] = 2
            second = execution.execute(RefreshIntent.VISIBLE)

        self.assertEqual(first.fetched, 3)
        self.assertEqual(first.matched, 3)
        self.assertEqual(first.new_matches, 3)
        self.assertEqual(second.new_matches, 0)
        self.assertEqual(len(second.snapshot.articles), 3)
        self.assertEqual(
            {article.authors for article in second.snapshot.articles},
            {("RSS Author",), ("Crossref Author",), ("OpenAlex Author",)},
        )
        self.assertTrue(all(not hasattr(article, "abstract") for article in second.snapshot.articles))
        self.assertEqual(
            requested_hosts,
            [
                "feed.example",
                "api.crossref.org",
                "api.openalex.org",
                "feed.example",
                "api.crossref.org",
                "api.openalex.org",
            ],
        )


if __name__ == "__main__":
    unittest.main()
