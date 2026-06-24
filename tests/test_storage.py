import tempfile
import unittest
import sqlite3
from pathlib import Path

from paper_monitor.models import Article
from paper_monitor.storage import ArticleStore


class StorageTests(unittest.TestCase):
    def test_add_new_articles_returns_only_unseen_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ArticleStore(Path(temp_dir) / "articles.sqlite3")
            article = Article(
                title="Solid electrolyte paper",
                journal="Nature Energy",
                url="https://example.org/article",
                doi="10.1000/example",
                published="2026-06-20",
                abstract="",
                source="fixture",
            )

            first = store.add_new_articles([article])
            second = store.add_new_articles([article])

            self.assertEqual(first, [article])
            self.assertEqual(second, [])

    def test_duplicate_articles_refresh_stored_metadata_without_counting_as_new(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ArticleStore(Path(temp_dir) / "articles.sqlite3")
            original = Article(
                title="Solid electrolyte paper",
                journal="Journal of Power Sources",
                url="https://doi.org/10.1016/example",
                doi="10.1016/example",
                published="2026-10",
                detected="2026-06-17",
                abstract="Original metadata.",
                source="Crossref",
            )
            corrected = Article(
                title="Solid electrolyte paper",
                journal="Journal of Power Sources",
                url="https://doi.org/10.1016/example",
                doi="10.1016/example",
                published="2026-10-15",
                detected="2026-06-21",
                abstract="Corrected metadata.",
                source="Crossref",
            )

            first = store.add_new_articles([original])
            second = store.add_new_articles([corrected])
            recent = store.recent_articles(1)

            self.assertEqual(first, [original])
            self.assertEqual(second, [])
            self.assertEqual(recent[0].published, "2026-10-15")
            self.assertEqual(recent[0].detected, "2026-06-21")
            self.assertEqual(recent[0].abstract, "Corrected metadata.")

    def test_migrates_existing_database_and_backfills_detected_dates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "articles.sqlite3"
            connection = sqlite3.connect(str(db_path))
            try:
                connection.execute(
                    """
                    CREATE TABLE articles (
                        identity TEXT PRIMARY KEY,
                        doi TEXT,
                        title TEXT NOT NULL,
                        journal TEXT NOT NULL,
                        url TEXT NOT NULL,
                        published TEXT,
                        abstract TEXT,
                        source TEXT NOT NULL,
                        first_seen_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO articles (
                        identity, doi, title, journal, url, published, abstract, source, first_seen_at
                    )
                    VALUES (
                        'doi:10.1000/old', '10.1000/old', 'Old paper', 'Nature Energy',
                        'https://example.org/old', '2026-06-20', '', 'fixture', datetime('now')
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        started_at TEXT NOT NULL,
                        finished_at TEXT,
                        status TEXT NOT NULL,
                        fetched INTEGER NOT NULL,
                        matched INTEGER NOT NULL,
                        new_matches INTEGER NOT NULL,
                        skipped INTEGER NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE candidates (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id INTEGER NOT NULL,
                        identity TEXT NOT NULL,
                        doi TEXT,
                        title TEXT NOT NULL,
                        journal TEXT NOT NULL,
                        url TEXT NOT NULL,
                        published TEXT,
                        abstract TEXT,
                        source TEXT NOT NULL,
                        matched INTEGER NOT NULL,
                        reason TEXT NOT NULL,
                        matched_terms TEXT NOT NULL,
                        journal_match TEXT
                    )
                    """
                )
                connection.commit()
            finally:
                connection.close()

            store = ArticleStore(db_path)
            recent = store.recent_articles(1)

            self.assertEqual(recent[0].published, "2026-06-20")
            self.assertEqual(recent[0].detected, "2026-06-20")

    def test_uses_title_and_url_identity_when_doi_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ArticleStore(Path(temp_dir) / "articles.sqlite3")
            article = Article(
                title="New solid-state battery article",
                journal="Science",
                url="https://example.org/no-doi",
                doi="",
                published="2026-06-20",
                abstract="",
                source="fixture",
            )

            first = store.add_new_articles([article])
            second = store.add_new_articles([article])

            self.assertEqual(len(first), 1)
            self.assertEqual(second, [])

    def test_records_runs_and_candidate_decisions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ArticleStore(Path(temp_dir) / "articles.sqlite3")
            run_id = store.start_run()
            article = Article(
                title="Solid electrolyte paper",
                journal="Nature Energy",
                url="https://example.org/article",
                doi="10.1000/example",
                published="2026-06-20",
                abstract="",
                source="fixture",
            )

            store.record_candidate(
                run_id=run_id,
                article=article,
                matched=True,
                reason="matched",
                matched_terms=["solid electrolyte"],
                journal_match="Nature Energy",
            )
            store.finish_run(run_id, fetched=1, matched=1, new_matches=1, skipped=0)

            latest_run = store.latest_run()
            candidates = store.candidates_for_run(run_id)

            self.assertEqual(latest_run["id"], run_id)
            self.assertEqual(latest_run["fetched"], 1)
            self.assertEqual(len(candidates), 1)
            self.assertTrue(candidates[0]["matched"])
            self.assertEqual(candidates[0]["detected"], "2026-06-20")
            self.assertEqual(candidates[0]["reason"], "matched")
            self.assertEqual(candidates[0]["matched_terms"], ["solid electrolyte"])


if __name__ == "__main__":
    unittest.main()
