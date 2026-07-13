import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor.models import Article
from paper_monitor.sources import (
    SourceFetchResult,
    _crossref_cache_path,
    _prune_crossref_cache,
    _read_cached_url_response,
    fetch_all_sources,
    fetch_crossref,
)


class SourceDiagnosticsTests(unittest.TestCase):
    def test_all_failed_sources_are_exposed_without_breaking_list_callers(self):
        config = {
            "rss": [{"name": "Broken", "url": "https://example.org/broken.xml"}],
            "crossref": {"enabled": False},
            "openalex": {"enabled": False},
            "arxiv": {"enabled": False},
        }

        with patch("paper_monitor.sources.fetch_url", side_effect=OSError("offline")):
            result = fetch_all_sources(config)

        self.assertEqual(result, [])
        self.assertTrue(result.all_failed)
        self.assertIn("offline", str(result.all_failed_error))
        self.assertEqual(result.source_statuses[0]["status"], "failed")

    def test_partial_source_results_keep_articles_and_diagnostics(self):
        article = Article(
            title="Paper",
            journal="Journal",
            url="https://example.org/paper",
            doi="",
            published="2026-07-12",
            abstract="",
            source="Crossref",
        )
        crossref = SourceFetchResult(
            [article],
            [
                {"source": "Crossref request", "status": "succeeded", "count": 1, "error": ""},
                {"source": "Crossref request", "status": "failed", "count": 0, "error": "timeout"},
            ],
        )
        config = {
            "rss": [],
            "crossref": {"enabled": True},
            "openalex": {"enabled": False},
            "arxiv": {"enabled": False},
        }

        with patch("paper_monitor.sources.fetch_crossref", return_value=crossref):
            result = fetch_all_sources(config)

        self.assertEqual(result, [article])
        self.assertTrue(result.partial)
        self.assertEqual(result.source_statuses[0]["status"], "partial")

    def test_crossref_marks_all_request_failures(self):
        result = fetch_crossref(
            {
                "journal_titles": ["Journal A", "Journal B"],
                "query": "solid electrolyte",
                "retry_count": 0,
                "min_request_interval_seconds": 0,
            },
            fetch=lambda _url: (_ for _ in ()).throw(OSError("network down")),
        )

        self.assertEqual(result, [])
        self.assertTrue(result.all_failed)
        self.assertEqual([item["status"] for item in result.source_statuses], ["failed", "failed"])

    def test_expired_cache_entry_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_dir = Path(directory)
            url = "https://api.crossref.org/works?query=test"
            path = _crossref_cache_path(url, cache_dir)
            path.write_bytes(b"{}")
            old = time.time() - 120
            os.utime(path, (old, old))

            self.assertIsNone(_read_cached_url_response(url, cache_dir, ttl_seconds=60))
            self.assertFalse(path.exists())

    def test_cache_pruning_enforces_file_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            cache_dir = Path(directory)
            for index in range(3):
                path = cache_dir / f"{index}.json"
                path.write_bytes(str(index).encode("ascii"))
                modified = time.time() - (10 - index)
                os.utime(path, (modified, modified))

            with patch("paper_monitor.sources.CROSSREF_CACHE_MAX_FILES", 2):
                _prune_crossref_cache(cache_dir, ttl_seconds=3600)

            self.assertEqual(len(list(cache_dir.glob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
