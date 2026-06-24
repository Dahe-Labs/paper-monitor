import tempfile
import unittest
from pathlib import Path

from paper_monitor.filtering import FilterConfig
from paper_monitor.models import Article
from paper_monitor.monitor import MonitorConfig, run_once
from paper_monitor.storage import ArticleStore


class MonitorPipelineTests(unittest.TestCase):
    def test_run_once_notifies_only_new_matching_articles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ArticleStore(Path(temp_dir) / "articles.sqlite3")
            matching = Article(
                title="Solid electrolyte design for all-solid-state batteries",
                journal="Nature Energy",
                url="https://example.org/matching",
                doi="10.1000/matching",
                published="2026-06-20",
                abstract="Argyrodite solid electrolyte.",
                source="fixture",
            )
            unrelated = Article(
                title="Solid-state laser design",
                journal="Nature Energy",
                url="https://example.org/unrelated",
                doi="10.1000/unrelated",
                published="2026-06-20",
                abstract="Photonics.",
                source="fixture",
            )
            notified = []
            config = MonitorConfig(
                filter_config=FilterConfig(
                    include_terms=["solid electrolyte", "all-solid-state batteries"],
                    exclude_terms=["solid-state laser"],
                    journals=["Nature Energy"],
                ),
                max_notifications=5,
            )

            first = run_once(
                config=config,
                store=store,
                fetch_articles=lambda: [matching, unrelated],
                notify=lambda article, match: notified.append((article, match)),
            )
            second = run_once(
                config=config,
                store=store,
                fetch_articles=lambda: [matching],
                notify=lambda article, match: notified.append((article, match)),
            )

            self.assertEqual(first.new_matches, 1)
            self.assertEqual(first.skipped, 1)
            self.assertEqual(second.new_matches, 0)
            self.assertEqual(len(notified), 1)
            self.assertEqual(notified[0][0].doi, "10.1000/matching")
            self.assertIsNotNone(first.run_id)
            self.assertEqual(len(store.candidates_for_run(first.run_id)), 2)
            self.assertEqual(store.latest_run()["fetched"], 1)

    def test_run_once_deduplicates_fetched_articles_by_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ArticleStore(Path(temp_dir) / "articles.sqlite3")
            matching = Article(
                title="Solid electrolyte design for all-solid-state batteries",
                journal="Nature Energy",
                url="https://example.org/matching",
                doi="10.1000/matching",
                published="2026-06-20",
                abstract="Argyrodite solid electrolyte.",
                source="Crossref",
            )
            duplicate = Article(
                title="Solid electrolyte design for all-solid-state batteries",
                journal="Nature Energy",
                url="https://doi.org/10.1000/matching",
                doi="10.1000/matching",
                published="2026-06-20",
                abstract="Argyrodite solid electrolyte.",
                source="Crossref",
            )
            unrelated = Article(
                title="Solid-state laser design",
                journal="Nature Energy",
                url="https://example.org/unrelated",
                doi="10.1000/unrelated",
                published="2026-06-20",
                abstract="Photonics.",
                source="Crossref",
            )
            notified = []
            config = MonitorConfig(
                filter_config=FilterConfig(
                    include_terms=["solid electrolyte", "all-solid-state batteries"],
                    exclude_terms=["solid-state laser"],
                    journals=["Nature Energy"],
                ),
                max_notifications=5,
            )

            summary = run_once(
                config=config,
                store=store,
                fetch_articles=lambda: [matching, duplicate, unrelated],
                notify=lambda article, match: notified.append((article, match)),
            )

            self.assertEqual(summary.fetched, 3)
            self.assertEqual(summary.matched, 1)
            self.assertEqual(summary.skipped, 2)
            self.assertEqual(summary.new_matches, 1)
            self.assertEqual(len(notified), 1)
            self.assertEqual(len(store.candidates_for_run(summary.run_id)), 2)


if __name__ == "__main__":
    unittest.main()
