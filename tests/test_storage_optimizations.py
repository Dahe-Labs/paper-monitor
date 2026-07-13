import sqlite3
import tempfile
import unittest
from pathlib import Path

from paper_monitor.filtering import FilterConfig
from paper_monitor.models import Article
from paper_monitor.monitor import MonitorConfig, run_once
from paper_monitor.sources import SourceFetchError, SourceFetchResult
from paper_monitor.storage import ArticleStore, CandidateRecord


def _article(suffix: str, *, source: str = "fixture") -> Article:
    return Article(
        title="Solid electrolyte paper %s" % suffix,
        journal="Nature Energy",
        url="https://example.org/%s" % suffix,
        doi="10.1000/%s" % suffix,
        published="2026-06-20",
        abstract="A solid electrolyte study.",
        source=source,
    )


def _candidate(article: Article) -> CandidateRecord:
    return CandidateRecord(
        article=article,
        matched=True,
        reason="matched",
        matched_terms=["solid electrolyte"],
        journal_match="Nature Energy",
    )


class StorageOptimizationTests(unittest.TestCase):
    def test_candidate_batch_rolls_back_every_row_when_one_insert_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ArticleStore(Path(temp_dir) / "articles.sqlite3")
            run_id = store.start_run()
            invalid_article = _article("invalid", source=None)  # type: ignore[arg-type]

            with self.assertRaises(sqlite3.IntegrityError):
                store.record_candidates(run_id, [_candidate(_article("valid")), _candidate(invalid_article)])

            self.assertEqual(store.candidates_for_run(run_id), [])

    def test_monitor_uses_one_candidate_batch_and_preserves_source_diagnostics(self):
        class TrackingStore(ArticleStore):
            def __init__(self, path: Path):
                super().__init__(path)
                self.batch_calls = 0

            def record_candidate(self, *args, **kwargs):
                raise AssertionError("run_once should use the batch API")

            def record_candidates(self, run_id, candidates):
                self.batch_calls += 1
                return super().record_candidates(run_id, candidates)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = TrackingStore(Path(temp_dir) / "articles.sqlite3")
            statuses = [
                {"source": "Crossref", "target": "", "status": "partial", "count": 2, "error": "timeout"}
            ]
            fetched = SourceFetchResult([_article("one"), _article("two")], statuses)
            summary = run_once(
                MonitorConfig(
                    filter_config=FilterConfig(
                        include_terms=["solid electrolyte"],
                        exclude_terms=[],
                        journals=[],
                    ),
                    max_notifications=0,
                ),
                store,
                lambda: fetched,
                lambda _article, _match: None,
            )

            self.assertEqual(store.batch_calls, 1)
            self.assertEqual(len(store.candidates_for_run(summary.run_id)), 2)
            self.assertEqual(summary.source_statuses, statuses)

    def test_monitor_bounds_candidate_batches_for_large_searches(self):
        class TrackingStore(ArticleStore):
            def __init__(self, path: Path):
                super().__init__(path)
                self.batch_sizes = []

            def record_candidates(self, run_id, candidates):
                materialized = list(candidates)
                self.batch_sizes.append(len(materialized))
                return super().record_candidates(run_id, materialized)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = TrackingStore(Path(temp_dir) / "articles.sqlite3")
            fetched = [_article(str(index)) for index in range(601)]
            summary = run_once(
                MonitorConfig(
                    filter_config=FilterConfig(
                        include_terms=["solid electrolyte"],
                        exclude_terms=[],
                        journals=[],
                    ),
                    max_notifications=0,
                ),
                store,
                lambda: fetched,
                lambda _article, _match: None,
            )

            self.assertEqual(summary.fetched, 601)
            self.assertEqual(store.batch_sizes, [250, 250, 101])

    def test_all_failed_source_result_marks_run_failed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ArticleStore(Path(temp_dir) / "articles.sqlite3")
            fetched = SourceFetchResult(
                [],
                [{"source": "Crossref", "target": "", "status": "failed", "count": 0, "error": "offline"}],
            )

            with self.assertRaisesRegex(SourceFetchError, "offline") as raised:
                run_once(
                    MonitorConfig(
                        filter_config=FilterConfig(include_terms=[], exclude_terms=[], journals=[]),
                        max_notifications=0,
                    ),
                    store,
                    lambda: fetched,
                    lambda _article, _match: None,
                )

            self.assertEqual(store.latest_run()["status"], "failed")
            self.assertEqual(raised.exception.source_statuses, fetched.source_statuses)

    def test_schema_migration_backfill_runs_once_and_creates_query_indexes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "articles.sqlite3"
            ArticleStore(db_path)
            connection = sqlite3.connect(str(db_path))
            try:
                connection.execute(
                    """
                    INSERT INTO articles (
                        identity, doi, title, journal, url, published, detected, abstract, source, first_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, datetime('now'))
                    """,
                    (
                        "doi:10.1000/manual",
                        "10.1000/manual",
                        "Manual row",
                        "Nature Energy",
                        "https://example.org/manual",
                        "2026-06-20",
                        "",
                        "fixture",
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            ArticleStore(db_path)
            connection = sqlite3.connect(str(db_path))
            try:
                detected = connection.execute(
                    "SELECT detected FROM articles WHERE identity = 'doi:10.1000/manual'"
                ).fetchone()[0]
                schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
                candidate_indexes = {
                    row[1] for row in connection.execute("PRAGMA index_list(candidates)").fetchall()
                }
            finally:
                connection.close()

            self.assertEqual(detected, "")
            self.assertEqual(schema_version, 3)
            self.assertIn("idx_candidates_run_id_id", candidate_indexes)

    def test_connections_use_wal_busy_timeout_and_support_memory_databases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "articles.sqlite3"
            store = ArticleStore(db_path)
            with store._connect() as connection:
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
                self.assertEqual(connection.execute("PRAGMA busy_timeout").fetchone()[0], 5_000)

        memory_store = ArticleStore(Path(":memory:"))
        run_id = memory_store.start_run()
        memory_store.finish_run(run_id, fetched=0, matched=0, new_matches=0, skipped=0)
        self.assertEqual(memory_store.latest_run()["id"], run_id)

    def test_starting_a_run_recovers_only_preexisting_running_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "articles.sqlite3"
            first_store = ArticleStore(db_path)
            abandoned_run_id = first_store.start_run()

            second_store = ArticleStore(db_path)
            self.assertEqual(second_store.latest_run()["status"], "running")
            current_run_id = second_store.start_run()

            connection = sqlite3.connect(str(db_path))
            try:
                statuses = dict(connection.execute("SELECT id, status FROM runs ORDER BY id").fetchall())
            finally:
                connection.close()

            self.assertEqual(statuses[abandoned_run_id], "aborted")
            self.assertEqual(statuses[current_run_id], "running")

    def test_history_cleanup_is_explicit_and_keeps_current_and_latest_terminal_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "articles.sqlite3"
            store = ArticleStore(db_path)
            terminal_run_ids = []
            for suffix in ("one", "two", "three"):
                run_id = store.start_run()
                terminal_run_ids.append(run_id)
                store.record_candidates(run_id, [_candidate(_article(suffix))])
                store.finish_run(run_id, fetched=1, matched=1, new_matches=1, skipped=0)
            current_run_id = store.start_run()

            self.assertEqual(
                store.cleanup_history(),
                {"runs_deleted": 0, "candidates_deleted": 0},
            )
            result = store.cleanup_history(keep_latest_runs=1)

            connection = sqlite3.connect(str(db_path))
            try:
                remaining_run_ids = {
                    row[0] for row in connection.execute("SELECT id FROM runs").fetchall()
                }
            finally:
                connection.close()

            self.assertEqual(result, {"runs_deleted": 2, "candidates_deleted": 2})
            self.assertEqual(remaining_run_ids, {terminal_run_ids[-1], current_run_id})

    def test_latest_successful_run_ignores_newer_failed_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ArticleStore(Path(temp_dir) / "articles.sqlite3")
            successful_run_id = store.start_run()
            store.finish_run(
                successful_run_id,
                fetched=1,
                matched=1,
                new_matches=1,
                skipped=0,
                status="partial",
            )
            failed_run_id = store.start_run()
            store.fail_run(failed_run_id, "offline")

            self.assertEqual(store.latest_successful_run()["id"], successful_run_id)


if __name__ == "__main__":
    unittest.main()
