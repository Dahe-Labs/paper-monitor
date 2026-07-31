import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor.article_lifecycle import (
    ArticleDetection,
    ArticleLifecycle,
    RefreshCommit,
    RefreshRunStatus,
)
from paper_monitor.cli import _open_dashboard, build_arg_parser
from paper_monitor.config import DEFAULT_CONFIG, load_app_config, write_default_config


def _contains_han(value: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in value)


class ConfigAndCliTests(unittest.TestCase):
    def test_writes_and_loads_default_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            write_default_config(config_path)
            config = load_app_config(config_path)

            self.assertTrue(config.source_config["crossref"]["enabled"])
            self.assertEqual(config.source_config["crossref"]["days_back"], 15)
            self.assertEqual(config.source_config["crossref"]["timeout_seconds"], 20)
            self.assertEqual(config.source_config["crossref"]["max_workers"], 3)
            self.assertEqual(config.source_config["openalex"]["days_back"], 15)
            self.assertIn("Nature Energy", config.source_config["crossref"]["journal_titles"])
            self.assertEqual(config.dashboard_path.name, "latest.html")
            self.assertEqual(config.journal_metrics_path.name, "journal_metrics.json")
            self.assertIn("solid electrolyte", config.monitor_config.filter_config.include_terms)
            self.assertIn("Nature Energy", config.monitor_config.filter_config.journals)
            self.assertEqual(config.interval_seconds, 86400)
            self.assertEqual(config.refresh_start_time, "09:00")

    def test_legacy_notification_limit_is_clamped_to_shared_ui_runtime_maximum(self):
        from paper_monitor.windows_settings import settings_payload

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            payload = json.loads(json.dumps(DEFAULT_CONFIG))
            payload["max_notifications"] = 100
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            app_config = load_app_config(config_path)
            editable = settings_payload(config_path)

        self.assertEqual(app_config.monitor_config.max_notifications, 20)
        self.assertEqual(editable["max_notifications"], 20)

    def test_test_notification_defaults_to_paper_monitor_title(self):
        args = build_arg_parser().parse_args(["test-notification"])

        self.assertEqual(args.title, "Paper Monitor test")

    def test_default_config_uses_english_only_material_keywords(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"

            write_default_config(config_path)
            config = load_app_config(config_path)

            include_terms = config.monitor_config.filter_config.include_terms
            for term in ["electrolyte", "electrode", "LLZTO", "LLZO", "silicon anode", "Si anode", "NCM"]:
                self.assertIn(term, include_terms)
            self.assertFalse(any(_contains_han(term) for term in include_terms))

            crossref_query = config.source_config["crossref"]["query"]
            openalex_query = config.source_config["openalex"]["query"]
            self.assertIn("silicon anode", crossref_query)
            self.assertIn("NCM", crossref_query)
            self.assertIn("silicon anode", openalex_query)
            self.assertIn("NCM", openalex_query)
            self.assertFalse(_contains_han(crossref_query))
            self.assertFalse(_contains_han(openalex_query))

    def test_default_config_has_one_explicit_journal_selection(self):
        journals = DEFAULT_CONFIG["journal_scope"]["selected_journals"]

        self.assertEqual(len(journals), 15)
        self.assertEqual(len(journals), len(set(journals)))
        for journal in [
            "Advanced Functional Materials",
            "Advanced Energy Materials",
            "Energy & Environmental Science",
            "ACS Energy Letters",
            "Joule",
        ]:
            self.assertIn(journal, journals)

    def test_checked_in_configs_and_metrics_match_default_selected_journals(self):
        project_root = Path(__file__).resolve().parents[1]
        expected = DEFAULT_CONFIG["journal_scope"]["selected_journals"]
        example = json.loads((project_root / "config.example.json").read_text(encoding="utf-8"))
        metrics = json.loads((project_root / "journal_metrics.json").read_text(encoding="utf-8"))

        self.assertNotIn("journals", example)
        metric_names = [item["journal"] for item in metrics["journals"]]
        self.assertTrue(set(expected).issubset(metric_names))
        formal_metrics = [item for item in metrics["journals"] if item["default_selected"]]
        self.assertEqual(len(formal_metrics), 300)
        self.assertEqual(len(metric_names), 301)
        self.assertTrue(all(item["impact_factor"] > 0 for item in formal_metrics))
        self.assertTrue(all(item["category"] for item in formal_metrics))
        self.assertGreaterEqual(len({item["category"] for item in formal_metrics}), 10)
        self.assertEqual(metrics["metric"]["name"], "OpenAlex 2-year mean citedness")
        self.assertIn("arXiv", metric_names)
        arxiv_metric = next(item for item in metrics["journals"] if item["journal"] == "arXiv")
        self.assertIsNone(arxiv_metric["impact_factor"])
        self.assertFalse(arxiv_metric["default_selected"])
        self.assertNotIn("arXiv", example["journal_scope"]["selected_journals"])
        self.assertEqual([item["rank"] for item in metrics["journals"]], list(range(1, 302)))
        self.assertNotIn("top_n", example["journal_scope"])
        self.assertEqual(example["journal_scope"]["selected_journals"], expected)

    def test_explicit_empty_journal_selection_does_not_fall_back_to_legacy_journals(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            payload = json.loads(json.dumps(DEFAULT_CONFIG))
            payload["journals"] = ["Nature Energy"]
            payload["journal_scope"]["selected_journals"] = []
            payload["sources"]["arxiv"]["enabled"] = False
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            config = load_app_config(config_path)

        self.assertEqual(config.monitor_config.filter_config.journals, [])
        self.assertEqual(config.source_config["crossref"]["journal_titles"], [])
        self.assertFalse(config.source_config["crossref"]["enabled"])
        self.assertFalse(config.source_config["openalex"]["enabled"])
        self.assertEqual(config.source_config["rss"], [])

    def test_loads_user_overrides_from_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            payload = {
                "database_path": str(Path(temp_dir) / "custom.sqlite3"),
                "interval_seconds": 3600,
                "max_notifications": 2,
                "include_terms": ["solid electrolyte"],
                "exclude_terms": ["solid-state laser"],
                "journals": ["Nature Energy"],
                "sources": {"crossref": {"enabled": False}, "rss": []},
            }
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            config = load_app_config(config_path)

            self.assertEqual(config.database_path, Path(temp_dir) / "custom.sqlite3")
            self.assertEqual(config.interval_seconds, 3600)
            self.assertFalse(config.source_config["crossref"]["enabled"])

    def test_loads_settings_schema_and_syncs_selected_journals_to_crossref(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            payload = {
                "database_path": "work/paper-monitor/articles.sqlite3",
                "dashboard_path": "work/paper-monitor/dashboard/latest.html",
                "journal_metrics_path": "journal_metrics.json",
                "settings_schema_version": 1,
                "journal_scope": {
                    "top_n": 2,
                    "selected_journals": ["Nature Energy", "Advanced Materials", "arXiv"],
                },
                "interval_seconds": 3600,
                "refresh_start_time": "09:00",
                "include_terms": ["solid electrolyte", "", "solid electrolyte", "LLZO"],
                "exclude_terms": ["solid-state laser", "", "solid-state laser"],
                "search_direction": {
                    "preset": "solid_electrolyte",
                    "label": "Solid electrolyte",
                    "keywords": ["solid electrolyte", "", "LLZO", "LLZO"],
                    "crossref_query": "solid electrolyte OR LLZO",
                    "openalex_query": "solid electrolyte LLZO",
                    "query_manually_edited": True,
                },
                "sources": {
                    "rss": [],
                    "crossref": {"enabled": True, "journal_titles": ["Stale Journal"], "query": ""},
                    "openalex": {"enabled": False, "query": ""},
                },
            }
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            config = load_app_config(config_path)

            filter_config = config.monitor_config.filter_config
            self.assertEqual(filter_config.journals, ["Nature Energy", "Advanced Materials", "arXiv"])
            self.assertEqual(config.refresh_start_time, "09:00")
            self.assertEqual(filter_config.include_terms, ["solid electrolyte", "LLZO"])
            self.assertEqual(filter_config.exclude_terms, ["solid-state laser"])
            self.assertEqual(
                config.source_config["crossref"]["journal_titles"],
                ["Nature Energy", "Advanced Materials"],
            )
            self.assertTrue(config.source_config["arxiv"]["enabled"])
            self.assertEqual(config.source_config["crossref"]["query"], "solid electrolyte OR LLZO")
            self.assertEqual(config.source_config["openalex"]["query"], "solid electrolyte LLZO")

    def test_custom_search_direction_queries_do_not_replace_filter_terms(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            payload = {
                "journals": ["Nature Energy"],
                "include_terms": ["old term"],
                "exclude_terms": [],
                "search_direction": {
                    "preset": "custom",
                    "label": "Cathode interface",
                    "crossref_query": "cathode OR space charge",
                    "openalex_query": "cathode space charge",
                    "query_manually_edited": False,
                },
                "sources": {
                    "rss": [],
                    "crossref": {"enabled": True, "journal_titles": [], "query": ""},
                    "openalex": {"enabled": False, "query": ""},
                },
            }
            config_path.write_text(json.dumps(payload), encoding="utf-8")

            config = load_app_config(config_path)

            self.assertEqual(config.monitor_config.filter_config.include_terms, ["old term"])
            self.assertEqual(config.source_config["crossref"]["query"], "cathode OR space charge")
            self.assertEqual(config.source_config["openalex"]["query"], "cathode space charge")

    def test_settings_schema_falls_back_to_journals_when_selected_journals_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            payloads = [
                {
                    "journal_scope": {"top_n": 10},
                    "journals": ["Nature", "Science"],
                    "include_terms": ["solid electrolyte"],
                    "exclude_terms": [],
                    "sources": {"rss": [], "crossref": {"enabled": True, "journal_titles": []}},
                },
            ]

            for payload in payloads:
                with self.subTest(journal_scope=payload["journal_scope"]):
                    config_path.write_text(json.dumps(payload), encoding="utf-8")

                    config = load_app_config(config_path)

                    self.assertEqual(config.monitor_config.filter_config.journals, ["Nature", "Science"])
                    self.assertEqual(config.source_config["crossref"]["journal_titles"], ["Nature", "Science"])

    def test_cli_parser_supports_windows_developer_commands(self):
        parser = build_arg_parser()

        init_args = parser.parse_args(["init", "--config", "config.json"])
        run_args = parser.parse_args(["run", "--config", "config.json", "--dry-run"])
        analyze_args = parser.parse_args(
            [
                "analyze-keywords",
                "--config",
                "config.json",
                "--date-from",
                "2026-06-01",
                "--date-to",
                "2026-06-24",
                "--sort-mode",
                "impact_factor",
                "--analysis-depth",
                "exhaustive",
                "--journal",
                "Nature Energy",
            ]
        )
        dashboard_args = parser.parse_args(["open-dashboard", "--config", "config.json"])

        self.assertEqual(init_args.command, "init")
        self.assertEqual(run_args.command, "run")
        self.assertTrue(run_args.dry_run)
        self.assertEqual(analyze_args.command, "analyze-keywords")
        self.assertEqual(analyze_args.date_from, "2026-06-01")
        self.assertEqual(analyze_args.date_to, "2026-06-24")
        self.assertEqual(analyze_args.sort_mode, "impact_factor")
        self.assertEqual(analyze_args.analysis_depth, "exhaustive")
        self.assertEqual(analyze_args.journal, ["Nature Energy"])
        self.assertEqual(dashboard_args.command, "open-dashboard")

    def test_open_dashboard_rewrites_existing_dashboard_with_current_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            write_default_config(config_path)
            config = load_app_config(config_path)
            ArticleLifecycle(config.database_path).commit_refresh(
                RefreshCommit(
                    run_id="dashboard-test",
                    status=RefreshRunStatus.SUCCEEDED,
                    detections=(
                        ArticleDetection(
                            title="Solid electrolyte dashboard article",
                            authors=("Ada Lovelace",),
                            journal="Nature Energy",
                            impact_reference=21.1,
                            url="https://example.org/dashboard-article",
                            doi="10.1000/dashboard",
                            published="2026-06-24",
                            source="fixture",
                        ),
                    ),
                    fetched=1,
                    matched=1,
                )
            )
            config.dashboard_path.parent.mkdir(parents=True, exist_ok=True)
            config.dashboard_path.write_text("<html>old dashboard</html>", encoding="utf-8")

            with patch("paper_monitor.cli.webbrowser.open") as open_dashboard:
                result = _open_dashboard(config_path)

            html = config.dashboard_path.read_text(encoding="utf-8")
            self.assertEqual(result, 0)
            open_dashboard.assert_called_once_with(config.dashboard_path.resolve().as_uri())
            self.assertNotIn("old dashboard", html)
            self.assertIn('id="keyword-analysis-nav"', html)
            self.assertIn(">Keyword Analysis</button>", html)
            self.assertIn("Solid electrolyte dashboard article", html)

if __name__ == "__main__":
    unittest.main()
