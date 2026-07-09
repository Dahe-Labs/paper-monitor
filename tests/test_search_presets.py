import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor.search_presets import (
    DEFAULT_SEARCH_DIRECTION,
    SEARCH_DIRECTION_PRESETS,
    _load_catalog,
    find_preset,
)
from paper_monitor.windows_settings import default_settings_payload, settings_payload


class MissingPresetResource:
    def joinpath(self, *_parts):
        return self

    def read_text(self, encoding="utf-8"):
        raise FileNotFoundError("missing bundled preset catalog")


class SearchPresetTests(unittest.TestCase):
    def test_preset_catalog_contract(self):
        ids = [preset["id"] for preset in SEARCH_DIRECTION_PRESETS]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(DEFAULT_SEARCH_DIRECTION["preset"], ids)
        self.assertIn("custom", ids)
        self.assertEqual(find_preset("interface_impedance")["id"], "interface_interphase")
        self.assertEqual(find_preset("cathode_materials")["id"], "custom")
        for preset in SEARCH_DIRECTION_PRESETS:
            self.assertTrue(preset["id"])
            self.assertTrue(preset["label"])
            self.assertIsInstance(preset["aliases"], list)
            self.assertIsInstance(preset["is_custom"], bool)
            if preset["id"] != "custom":
                self.assertTrue(preset["crossref_query"])
                self.assertTrue(preset["openalex_query"])

    def test_default_settings_payload_returns_preset_copy(self):
        first = default_settings_payload()
        first["search_direction"]["presets"][0]["label"] = "Mutated"
        second = default_settings_payload()

        self.assertNotEqual(second["search_direction"]["presets"][0]["label"], "Mutated")

    def test_missing_bundled_preset_catalog_falls_back_to_embedded_defaults(self):
        with patch("paper_monitor.search_presets.resources.files", return_value=MissingPresetResource()):
            catalog = _load_catalog()

        self.assertEqual(catalog["default_preset"], "solid_state_battery_general")
        preset_ids = [preset["id"] for preset in catalog["presets"]]
        self.assertIn("solid_state_battery_general", preset_ids)
        self.assertIn("custom", preset_ids)

    def test_windows_settings_payload_canonicalizes_legacy_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "search_direction": {
                            "preset": "interface_impedance",
                            "label": "Interface / impedance",
                            "crossref_query": "old interface query",
                            "openalex_query": "old interface query",
                            "query_manually_edited": False,
                        },
                    },
                ),
                encoding="utf-8",
            )

            payload = settings_payload(config_path)

        self.assertEqual(payload["search_direction"]["preset"], "interface_interphase")
        self.assertEqual(payload["search_direction"]["label"], "Interface / interphase")
        self.assertIn("solid electrolyte interface", payload["search_direction"]["crossref_query"])
        self.assertFalse(payload["search_direction"]["query_manually_edited"])

    def test_windows_settings_payload_treats_removed_legacy_alias_as_custom(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "search_direction": {
                            "preset": "cathode_materials",
                            "label": "Cathode materials",
                            "crossref_query": "cathode query",
                            "openalex_query": "cathode query",
                            "query_manually_edited": False,
                        },
                    },
                ),
                encoding="utf-8",
            )

            payload = settings_payload(config_path)

        self.assertEqual(payload["search_direction"]["preset"], "custom")
        self.assertEqual(payload["search_direction"]["label"], "Cathode materials")
        self.assertEqual(payload["search_direction"]["crossref_query"], "cathode query")
        self.assertTrue(payload["search_direction"]["query_manually_edited"])


if __name__ == "__main__":
    unittest.main()
