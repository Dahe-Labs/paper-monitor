import json
import unittest
from pathlib import Path

from paper_monitor.config import DEFAULT_CONFIG
from paper_monitor.search_presets import (
    DEFAULT_SEARCH_DIRECTION,
    SEARCH_DIRECTION_PRESETS,
)


class ConfigContractTests(unittest.TestCase):
    def test_example_config_matches_default_config(self):
        example = json.loads(Path("config.example.json").read_text(encoding="utf-8"))

        self.assertEqual(example, DEFAULT_CONFIG)

    def test_schema_covers_default_config_fields(self):
        schema = json.loads(Path("docs/config.schema.json").read_text(encoding="utf-8"))

        self._assert_schema_covers(schema, DEFAULT_CONFIG, "config")

    def test_default_search_direction_matches_first_preset(self):
        first_preset = SEARCH_DIRECTION_PRESETS[0]

        self.assertEqual(DEFAULT_CONFIG["search_direction"], DEFAULT_SEARCH_DIRECTION)
        self.assertEqual(DEFAULT_SEARCH_DIRECTION["preset"], first_preset["id"])
        self.assertEqual(DEFAULT_SEARCH_DIRECTION["label"], first_preset["label"])
        self.assertEqual(DEFAULT_SEARCH_DIRECTION["crossref_query"], first_preset["crossref_query"])
        self.assertEqual(DEFAULT_SEARCH_DIRECTION["openalex_query"], first_preset["openalex_query"])

    def _assert_schema_covers(self, schema_node, value, path):
        if isinstance(value, dict):
            properties = schema_node.get("properties", {})
            for key, child in value.items():
                child_path = f"{path}.{key}"
                self.assertIn(key, properties, child_path)
                self._assert_schema_covers(properties[key], child, child_path)
            return

        if isinstance(value, list) and value:
            item_schema = schema_node.get("items")
            if isinstance(value[0], dict):
                self.assertIsInstance(item_schema, dict, path)
                self._assert_schema_covers(item_schema, value[0], f"{path}[]")


if __name__ == "__main__":
    unittest.main()
