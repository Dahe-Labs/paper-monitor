import copy
import json
import tempfile
import unittest
from pathlib import Path

from paper_monitor.config import DEFAULT_CONFIG, load_app_config
from paper_monitor.windows_settings import default_settings_payload, save_settings


class SettingsRuntimeContractTests(unittest.TestCase):
    def test_every_persisted_windows_setting_reaches_its_runtime_consumer(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            raw = copy.deepcopy(DEFAULT_CONFIG)
            raw["sources"]["crossref"]["rows"] = 777
            config_path.write_text(
                json.dumps(raw, ensure_ascii=False),
                encoding="utf-8",
            )
            payload = default_settings_payload(config_path)
            payload["interval_seconds"] = 6 * 60 * 60
            payload["refresh_start_time"] = "07:45"
            payload["max_notifications"] = 7
            payload["app_settings"] = {
                "startup_enabled": True,
                "launch_at_login": True,
                "show_tray_icon": True,
                "notifications_enabled": False,
            }
            payload["search_direction"] = {
                "preset": "custom",
                "label": "Runtime contract",
                "crossref_query": "sulfide electrolyte",
                "openalex_query": "halide electrolyte",
                "query_manually_edited": True,
            }
            payload["include_terms"] = ["sulfide", "LLZO"]
            payload["exclude_terms"] = ["laser"]
            payload["journal_scope"]["selected_journals"] = [
                "Nature Energy",
                "arXiv",
            ]
            crossref = payload["sources"]["crossref"]
            crossref.pop("rows")
            crossref.update(
                {
                    "enabled": True,
                    "days_back": 21,
                    "rows_per_journal": 33,
                    "timeout_seconds": 31,
                    "max_workers": 2,
                    "mailto": "researcher@example.edu",
                    "query": "sulfide electrolyte",
                }
            )
            payload["sources"]["openalex"].update(
                {
                    "enabled": True,
                    "days_back": 22,
                    "per_page": 120,
                    "max_pages": 4,
                    "query": "halide electrolyte",
                    "api_key": "test-key",
                }
            )
            payload["sources"]["arxiv"].update(
                {
                    "enabled": True,
                    "days_back": 23,
                    "max_results": 150,
                    "search_field": "all",
                    "timeout_seconds": 32,
                    "query": "sodium battery",
                }
            )

            response = save_settings(config_path, payload)
            runtime = load_app_config(config_path)
            saved = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(response, {"ok": True})
        self.assertEqual(runtime.interval_seconds, 6 * 60 * 60)
        self.assertEqual(runtime.refresh_start_time, "07:45")
        self.assertEqual(runtime.monitor_config.max_notifications, 7)
        self.assertEqual(runtime.monitor_config.filter_config.include_terms, ["sulfide", "LLZO"])
        self.assertEqual(runtime.monitor_config.filter_config.exclude_terms, ["laser"])
        self.assertEqual(
            runtime.monitor_config.filter_config.journals,
            ["Nature Energy", "arxiv"],
        )
        self.assertTrue(runtime.app_settings.startup_enabled)
        self.assertTrue(runtime.app_settings.launch_at_login)
        self.assertTrue(runtime.app_settings.show_tray_icon)
        self.assertFalse(runtime.app_settings.notifications_enabled)

        runtime_crossref = runtime.source_config["crossref"]
        self.assertTrue(runtime_crossref["enabled"])
        self.assertEqual(runtime_crossref["days_back"], 21)
        self.assertEqual(runtime_crossref["rows_per_journal"], 33)
        self.assertEqual(runtime_crossref["timeout_seconds"], 31)
        self.assertEqual(runtime_crossref["max_workers"], 2)
        self.assertEqual(runtime_crossref["mailto"], "researcher@example.edu")
        self.assertEqual(runtime_crossref["query"], "sulfide electrolyte")
        self.assertEqual(runtime_crossref["journal_titles"], ["Nature Energy"])

        runtime_openalex = runtime.source_config["openalex"]
        self.assertTrue(runtime_openalex["enabled"])
        self.assertEqual(runtime_openalex["days_back"], 22)
        self.assertEqual(runtime_openalex["per_page"], 120)
        self.assertEqual(runtime_openalex["max_pages"], 4)
        self.assertEqual(runtime_openalex["query"], "halide electrolyte")
        self.assertEqual(runtime_openalex["api_key"], "test-key")

        runtime_arxiv = runtime.source_config["arxiv"]
        self.assertTrue(runtime_arxiv["enabled"])
        self.assertEqual(runtime_arxiv["days_back"], 23)
        self.assertEqual(runtime_arxiv["max_results"], 150)
        self.assertEqual(runtime_arxiv["search_field"], "all")
        self.assertEqual(runtime_arxiv["timeout_seconds"], 32)
        self.assertEqual(runtime_arxiv["query"], "sodium battery")

        # The obsolete no-journal Crossref row limit is no longer exposed, but
        # an existing value remains untouched for backward-compatible configs.
        self.assertEqual(saved["sources"]["crossref"]["rows"], 777)


if __name__ == "__main__":
    unittest.main()
