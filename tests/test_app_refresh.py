import json
import re
import tempfile
import unittest
from pathlib import Path

from paper_monitor.app_refresh import run_app_refresh
from paper_monitor.config import write_default_config
from paper_monitor.models import Article
from paper_monitor.storage import ArticleStore


class AppRefreshTests(unittest.TestCase):
    def test_app_refresh_returns_summary_dashboard_and_new_articles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)

            article = Article(
                title="Solid electrolyte breakthrough",
                journal="Nature Energy",
                url="https://example.org/article",
                doi="10.1000/example",
                published="2026-06-22",
                detected="2026-06-21",
                abstract="Solid-state battery interface.",
                source="fixture",
            )

            result = run_app_refresh(config_path, fetch_articles=lambda: [article])

        self.assertEqual(result["fetched"], 1)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["new_matches"], 1)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(len(result["articles"]), 1)
        self.assertEqual(result["articles"][0]["title"], "Solid electrolyte breakthrough")
        self.assertEqual(result["articles"][0]["url"], "https://example.org/article")
        self.assertEqual(result["articles"][0]["doi"], "10.1000/example")
        self.assertEqual(result["articles"][0]["detected"], "2026-06-21")
        self.assertTrue(result["dashboard_path"].endswith("latest.html"))

    def test_app_refresh_does_not_report_duplicate_articles_as_new(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)

            article = Article(
                title="Solid electrolyte breakthrough",
                journal="Nature Energy",
                url="https://example.org/article",
                doi="10.1000/example",
                published="2026-06-22",
                abstract="Solid-state battery interface.",
                source="fixture",
            )

            first = run_app_refresh(config_path, fetch_articles=lambda: [article])
            second = run_app_refresh(config_path, fetch_articles=lambda: [article])

        self.assertEqual(first["new_matches"], 1)
        self.assertEqual(len(first["articles"]), 1)
        self.assertEqual(second["new_matches"], 0)
        self.assertEqual(second["articles"], [])

    def test_app_refresh_writes_configured_journal_scope_to_keyword_analysis_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)

            article = Article(
                title="Solid electrolyte breakthrough",
                journal="Nature Energy",
                url="https://example.org/article",
                doi="10.1000/example",
                published="2026-06-22",
                abstract="Solid-state battery interface.",
                source="fixture",
            )

            result = run_app_refresh(config_path, fetch_articles=lambda: [article])
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

    def test_scheduled_refresh_queues_notifications_and_defers_dashboard_rendering(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)
            config_payload = json.loads(config_path.read_text(encoding="utf-8"))
            config_payload["app_settings"]["notifications_enabled"] = True
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")
            article = Article(
                title="Solid electrolyte scheduled paper",
                journal="Nature Energy",
                url="https://example.org/scheduled",
                doi="10.1000/scheduled",
                published="2026-06-22",
                abstract="Solid electrolyte.",
                source="fixture",
            )

            result = run_app_refresh(
                config_path,
                fetch_articles=lambda: [article],
                reason="scheduled_refresh",
            )
            config = json.loads(config_path.read_text(encoding="utf-8"))
            database_path = config_path.parent / config["database_path"]
            pending = ArticleStore(database_path).pending_notifications()

        self.assertFalse(result["dashboard_updated"])
        self.assertEqual(result["notifications_queued"], 1)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["article"]["title"], "Solid electrolyte scheduled paper")


if __name__ == "__main__":
    unittest.main()
