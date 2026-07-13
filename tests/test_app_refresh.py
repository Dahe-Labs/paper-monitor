import json
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from paper_monitor.app_refresh import run_app_refresh
from paper_monitor.article_lifecycle import ArticleLifecycle
from paper_monitor.config import write_default_config
from paper_monitor.models import Article
from paper_monitor.refresh_errors import RefreshSourcesFailed


def fixture_article() -> Article:
    return Article(
        title="Solid electrolyte breakthrough",
        journal="Nature Energy",
        url="https://example.org/article",
        doi="10.1000/example",
        published="2026-06-22",
        detected="2026-06-21",
        abstract="Solid-state battery interface.",
        source="fixture",
        authors=("Ada Lovelace",),
    )


class AppRefreshTests(unittest.TestCase):
    def test_app_refresh_uses_lifecycle_for_dashboard_and_notification_handoff(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)

            result = run_app_refresh(config_path, fetch_articles=lambda: [fixture_article()])
            dashboard = Path(str(result["dashboard_path"])).read_text(encoding="utf-8")
            database_path = config_path.parent / "work/paper-monitor/articles.sqlite3"
            lifecycle = ArticleLifecycle(database_path)
            stored_count = len(lifecycle.list_articles())
            with closing(sqlite3.connect(database_path)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["fetched"], 1)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["new_matches"], 1)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(len(result["articles"]), 1)
        self.assertEqual(result["articles"][0]["title"], fixture_article().title)
        self.assertEqual(result["notification_article_count"], 1)
        self.assertIn(fixture_article().title, dashboard)
        self.assertEqual(stored_count, 1)
        self.assertTrue(
            {"articles", "runs", "candidates", "notification_outbox"}.isdisjoint(tables)
        )

    def test_app_refresh_does_not_offer_duplicate_articles_again(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)
            article = fixture_article()

            first = run_app_refresh(config_path, fetch_articles=lambda: [article])
            second = run_app_refresh(config_path, fetch_articles=lambda: [article])

        self.assertEqual(first["new_matches"], 1)
        self.assertEqual(len(first["articles"]), 1)
        self.assertEqual(second["new_matches"], 0)
        self.assertEqual(second["articles"], [])
        self.assertEqual(second["notification_article_count"], 0)

    def test_app_refresh_writes_configured_journal_scope_to_keyword_analysis_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)

            result = run_app_refresh(
                config_path,
                fetch_articles=lambda: [fixture_article()],
            )
            html = Path(str(result["dashboard_path"])).read_text(encoding="utf-8")
            match = re.search(
                r'<script type="application/json" id="keyword-analysis-data">(.*?)</script>',
                html,
                re.S,
            )

        self.assertIsNotNone(match)
        payload = json.loads(match.group(1))
        selected_journals = payload["scope"]["selected_journals"]
        self.assertEqual(payload["scope"]["top_n"], 15)
        self.assertEqual(len(selected_journals), 15)
        self.assertEqual(selected_journals[0], "Nature")
        self.assertIn("Joule", selected_journals)

    def test_app_refresh_exposes_failed_lifecycle_run_to_the_shell(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)

            def fail_fetch():
                raise RuntimeError("network unavailable")

            with self.assertRaises(RefreshSourcesFailed) as raised:
                run_app_refresh(config_path, fetch_articles=fail_fetch)

        self.assertEqual(raised.exception.result["status"], "failed")
        self.assertEqual(raised.exception.result["articles"], [])
        self.assertIn("network unavailable", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
