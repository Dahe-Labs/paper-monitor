import json
import tempfile
import unittest
from pathlib import Path

from paper_monitor.analysis_refresh import run_crossref_keyword_analysis
from paper_monitor.config import write_default_config
from paper_monitor.models import Article


class CrossrefKeywordAnalysisRefreshTests(unittest.TestCase):
    def test_run_crossref_keyword_analysis_returns_payload_without_database_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)
            metrics_path = Path(temp_dir) / "journal_metrics.json"
            metrics_path.write_text(
                json.dumps(
                    {
                        "journals": [
                            {
                                "journal": "Nature Energy",
                                "aliases": [],
                                "impact_factor": 60.1,
                                "impact_factor_year": 2025,
                                "five_year_impact_factor": None,
                                "level": "top journal",
                                "source_url": "",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            fetched = [
                Article(
                    title="Solid electrolyte interface",
                    journal="Nature Energy",
                    url="https://example.org/solid",
                    doi="10.1000/solid",
                    published="2026-10-15",
                    detected="2026-06-21",
                    abstract="Solid electrolyte interface for lithium metal.",
                    source="Crossref",
                    authors=("Ada Lovelace", "Grace Hopper"),
                ),
                Article(
                    title="Solid-state laser",
                    journal="Nature Energy",
                    url="https://example.org/laser",
                    doi="10.1000/laser",
                    published="2026-06-21",
                    detected="2026-06-21",
                    abstract="Laser.",
                    source="Crossref",
                ),
            ]

            result = run_crossref_keyword_analysis(
                config_path,
                date_from="2026-06-01",
                date_to="2026-06-24",
                sort_mode="time",
                top_n=30,
                selected_journals=["Nature Energy"],
                fetch_articles=lambda source_config: fetched,
            )

            self.assertEqual(result["fetched"], 2)
            self.assertEqual(result["matched"], 1)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(result["scope"]["date_from"], "2026-06-01")
            self.assertEqual(result["scope"]["date_to"], "2026-06-24")
            self.assertEqual(result["scope"]["source"], "crossref")
            self.assertEqual(result["papers"][0]["title"], "Solid electrolyte interface")
            self.assertEqual(result["papers"][0]["impact_factor"], 60.1)
            self.assertEqual(result["papers"][0]["authors"], ["Ada Lovelace", "Grace Hopper"])
            self.assertFalse((Path(temp_dir) / "work/paper-monitor/articles.sqlite3").exists())

    def test_run_crossref_keyword_analysis_does_not_fetch_when_all_journals_are_cleared(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)
            metrics_path = Path(temp_dir) / "journal_metrics.json"
            metrics_path.write_text('{"journals":[]}', encoding="utf-8")

            def fail_if_called(_source_config):
                raise AssertionError("Crossref should not be queried when no journals are selected")

            result = run_crossref_keyword_analysis(
                config_path,
                date_from="2026-06-01",
                date_to="2026-06-24",
                selected_journals=[],
                fetch_articles=fail_if_called,
            )

            self.assertEqual(result["fetched"], 0)
            self.assertEqual(result["matched"], 0)
            self.assertEqual(result["skipped"], 0)
            self.assertEqual(result["papers"], [])
            self.assertEqual(result["scope"]["selected_journals"], [])

    def test_run_crossref_keyword_analysis_uses_exhaustive_cursor_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)
            metrics_path = Path(temp_dir) / "journal_metrics.json"
            metrics_path.write_text('{"journals":[]}', encoding="utf-8")
            captured_source_config = {}

            def capture_fetch(source_config):
                captured_source_config.update(source_config)
                return []

            run_crossref_keyword_analysis(
                config_path,
                date_from="2026-06-01",
                date_to="2026-06-24",
                analysis_depth="exhaustive",
                selected_journals=["Nature Energy", "Advanced Energy Materials"],
                fetch_articles=capture_fetch,
            )

            crossref = captured_source_config["crossref"]
            self.assertEqual(crossref["journal_titles"], ["Nature Energy", "Advanced Energy Materials"])
            self.assertEqual(crossref["max_workers"], 3)
            self.assertTrue(crossref["cursor_pagination"])
            self.assertEqual(crossref["rows_per_journal"], 1000)
            self.assertEqual(crossref["date_chunk_days"], 31)
            self.assertEqual(crossref["max_cursor_pages"], 100)
            self.assertEqual(crossref["cache_ttl_seconds"], 3600)
            self.assertEqual(crossref["retry_count"], 2)

    def test_run_crossref_keyword_analysis_defaults_to_fast_title_only_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)
            metrics_path = Path(temp_dir) / "journal_metrics.json"
            metrics_path.write_text('{"journals":[]}', encoding="utf-8")
            captured_source_config = {}

            def capture_fetch(source_config):
                captured_source_config.update(source_config)
                return []

            run_crossref_keyword_analysis(
                config_path,
                date_from="2026-01-01",
                date_to="2026-12-31",
                selected_journals=["Nature Energy"],
                fetch_articles=capture_fetch,
            )

            crossref = captured_source_config["crossref"]
            self.assertEqual(crossref["query_field"], "title")
            self.assertEqual(crossref["rows_per_journal"], 1000)
            self.assertEqual(crossref["max_workers"], 6)
            self.assertEqual(crossref["date_chunk_days"], 0)
            self.assertEqual(crossref["max_cursor_pages"], 1)
            self.assertEqual(crossref["cache_ttl_seconds"], 21600)
            self.assertEqual(crossref["retry_count"], 2)
            self.assertIn("title", crossref["select_fields"])
            self.assertIn("author", crossref["select_fields"])
            self.assertIn("created", crossref["select_fields"])
            self.assertNotIn("abstract", crossref["select_fields"])

    def test_run_crossref_keyword_analysis_keeps_exhaustive_mode_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)
            metrics_path = Path(temp_dir) / "journal_metrics.json"
            metrics_path.write_text('{"journals":[]}', encoding="utf-8")
            captured_source_config = {}

            def capture_fetch(source_config):
                captured_source_config.update(source_config)
                return []

            run_crossref_keyword_analysis(
                config_path,
                date_from="2026-01-01",
                date_to="2026-12-31",
                selected_journals=["Nature Energy"],
                analysis_depth="exhaustive",
                fetch_articles=capture_fetch,
            )

            crossref = captured_source_config["crossref"]
            self.assertEqual(crossref["query_field"], "bibliographic")
            self.assertEqual(crossref["date_chunk_days"], 31)
            self.assertEqual(crossref["max_cursor_pages"], 100)
            self.assertNotIn("select_fields", crossref)
