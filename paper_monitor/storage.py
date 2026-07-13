import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

from .models import Article

_SCHEMA_VERSION = 3
_BUSY_TIMEOUT_MS = 5_000
_INTERRUPTED_RUN_MESSAGE = "The previous refresh ended before it could record a result."


@dataclass(frozen=True)
class CandidateRecord:
    article: Article
    matched: bool
    reason: str
    matched_terms: Sequence[str]
    journal_match: Optional[str]


class ArticleStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._is_memory_database = str(path) == ":memory:"
        self._memory_connection: Optional[sqlite3.Connection] = None
        self._memory_connection_lock = threading.RLock()
        if not self._is_memory_database:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        else:
            # A new connection would create a different in-memory database, so
            # retain one connection for the lifetime of this store.
            self._memory_connection = self._open_connection()
        self._initialize()

    def add_new_articles(self, articles: Iterable[Article]) -> List[Article]:
        new_articles: List[Article] = []
        with self._connect() as connection:
            for article in articles:
                try:
                    connection.execute(
                        """
                        INSERT INTO articles (
                            identity, doi, title, journal, url, published, detected, abstract, source, first_seen_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                        """,
                        (
                            article.identity,
                            article.doi,
                            article.title,
                            article.journal,
                            article.url,
                            article.published,
                            article.detected or article.published,
                            article.abstract,
                            article.source,
                        ),
                    )
                except sqlite3.IntegrityError:
                    self._update_article_metadata(connection, article)
                    continue
                new_articles.append(article)
        return new_articles

    def _update_article_metadata(self, connection: sqlite3.Connection, article: Article) -> None:
        connection.execute(
            """
            UPDATE articles
            SET doi = ?,
                title = ?,
                journal = ?,
                url = ?,
                published = ?,
                detected = ?,
                abstract = ?,
                source = ?
            WHERE identity = ?
            """,
            (
                article.doi,
                article.title,
                article.journal,
                article.url,
                article.published,
                article.detected or article.published,
                article.abstract,
                article.source,
                article.identity,
            ),
        )

    def start_run(self) -> int:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._recover_interrupted_runs(connection)
            cursor = connection.execute(
                """
                INSERT INTO runs (started_at, status, fetched, matched, new_matches, skipped)
                VALUES (datetime('now'), 'running', 0, 0, 0, 0)
                """
            )
            return int(cursor.lastrowid)

    def recover_interrupted_runs(self) -> int:
        """Mark abandoned runs terminal.

        Callers should own the application's refresh lock. ``start_run`` uses
        this operation in the same transaction immediately before inserting the
        new run, which prevents the new run from being mistaken for an old one.
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return self._recover_interrupted_runs(connection)

    def _recover_interrupted_runs(self, connection: sqlite3.Connection) -> int:
        cursor = connection.execute(
            """
            UPDATE runs
            SET finished_at = COALESCE(finished_at, datetime('now')),
                status = 'aborted',
                error_message = CASE
                    WHEN error_message IS NULL OR error_message = '' THEN ?
                    ELSE error_message
                END
            WHERE status = 'running'
            """,
            (_INTERRUPTED_RUN_MESSAGE,),
        )
        return max(cursor.rowcount, 0)

    def finish_run(
        self,
        run_id: int,
        fetched: int,
        matched: int,
        new_matches: int,
        skipped: int,
        status: str = "finished",
        error_message: str = "",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET finished_at = datetime('now'),
                    status = ?,
                    fetched = ?,
                    matched = ?,
                    new_matches = ?,
                    skipped = ?,
                    error_message = ?
                WHERE id = ?
                """,
                (status, fetched, matched, new_matches, skipped, error_message, run_id),
            )

    def fail_run(self, run_id: int, error_message: str) -> None:
        self.finish_run(
            run_id,
            fetched=0,
            matched=0,
            new_matches=0,
            skipped=0,
            status="failed",
            error_message=_short_error_message(error_message),
        )

    def record_candidate(
        self,
        run_id: int,
        article: Article,
        matched: bool,
        reason: str,
        matched_terms: List[str],
        journal_match: Optional[str],
    ) -> None:
        """Record one candidate while retaining the original public API."""
        self.record_candidates(
            run_id,
            [
                CandidateRecord(
                    article=article,
                    matched=matched,
                    reason=reason,
                    matched_terms=matched_terms,
                    journal_match=journal_match,
                )
            ],
        )

    def record_candidates(self, run_id: int, candidates: Iterable[CandidateRecord]) -> None:
        """Record a candidate batch atomically in one SQLite transaction."""
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO candidates (
                    run_id, identity, doi, title, journal, url, published, detected, abstract, source,
                    matched, reason, matched_terms, journal_match
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (self._candidate_values(run_id, candidate) for candidate in candidates),
            )

    def _candidate_values(self, run_id: int, candidate: CandidateRecord) -> tuple:
        article = candidate.article
        return (
            run_id,
            article.identity,
            article.doi,
            article.title,
            article.journal,
            article.url,
            article.published,
            article.detected or article.published,
            article.abstract,
            article.source,
            1 if candidate.matched else 0,
            candidate.reason,
            json.dumps(list(candidate.matched_terms), ensure_ascii=False),
            candidate.journal_match or "",
        )

    def latest_run(self) -> Optional[Dict[str, object]]:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT id, started_at, finished_at, status, fetched, matched, new_matches, skipped, error_message
                FROM runs
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def latest_successful_run(self) -> Optional[Dict[str, object]]:
        """Return the latest run whose result is usable for incremental work."""
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT id, started_at, finished_at, status, fetched, matched, new_matches, skipped, error_message
                FROM runs
                WHERE status IN ('finished', 'succeeded', 'partial')
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def candidates_for_run(self, run_id: int) -> List[Dict[str, object]]:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT identity, doi, title, journal, url, published, detected, abstract, source,
                       matched, reason, matched_terms, journal_match
                FROM candidates
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        candidates: List[Dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item["detected"] = item.get("detected") or item.get("published") or ""
            item["matched"] = bool(item["matched"])
            item["matched_terms"] = json.loads(item["matched_terms"] or "[]")
            candidates.append(item)
        return candidates

    def recent_articles(self, limit: int = 20) -> List[Article]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT title, journal, url, doi, published, detected, abstract, source
                FROM articles
                ORDER BY first_seen_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            Article(
                title=row[0],
                journal=row[1],
                url=row[2],
                doi=row[3],
                published=row[4],
                detected=row[5] or row[4],
                abstract=row[6],
                source=row[7],
            )
            for row in rows
        ]

    def enqueue_notifications(self, articles: Iterable[Mapping[str, object]]) -> int:
        """Persist notification payloads before attempting desktop delivery."""

        queued = 0
        with self._connect() as connection:
            for article in articles:
                payload = dict(article)
                identity = str(payload.get("identity") or "").strip()
                if not identity:
                    stable = "\n".join(
                        str(payload.get(key) or "") for key in ("doi", "url", "title")
                    )
                    identity = "notification:" + hashlib.sha256(stable.encode("utf-8")).hexdigest()
                serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO notification_outbox (
                        article_identity, payload_json, created_at, attempt_count, last_error
                    )
                    VALUES (?, ?, datetime('now'), 0, '')
                    """,
                    (identity, serialized),
                )
                queued += max(cursor.rowcount, 0)
        return queued

    def pending_notifications(self, limit: int = 100) -> List[Dict[str, object]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 1000:
            raise ValueError("notification limit must be between 1 and 1000")
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT id, payload_json, attempt_count, last_error
                FROM notification_outbox
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        pending: List[Dict[str, object]] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, dict):
                raise RuntimeError("Notification outbox payload is not an object")
            pending.append(
                {
                    "id": int(row["id"]),
                    "article": payload,
                    "attempt_count": int(row["attempt_count"]),
                    "last_error": str(row["last_error"] or ""),
                }
            )
        return pending

    def mark_notification_sent(self, notification_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM notification_outbox WHERE id = ?", (notification_id,))

    def mark_notification_failed(self, notification_id: int, error_message: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE notification_outbox
                SET attempt_count = attempt_count + 1,
                    last_attempt_at = datetime('now'),
                    last_error = ?
                WHERE id = ?
                """,
                (_short_error_message(error_message), notification_id),
            )

    def cleanup_history(
        self,
        *,
        keep_latest_runs: Optional[int] = None,
        max_age_days: Optional[int] = None,
    ) -> Dict[str, int]:
        """Delete eligible terminal run history only when a policy is supplied.

        When both policies are provided, a run must be outside the retained run
        count *and* older than the age limit. Running jobs and the article
        identity table are never deleted. Calling with the defaults is a no-op.
        """
        self._validate_retention_value("keep_latest_runs", keep_latest_runs)
        self._validate_retention_value("max_age_days", max_age_days)
        if keep_latest_runs is None and max_age_days is None:
            return {"runs_deleted": 0, "candidates_deleted": 0}

        conditions = ["status <> 'running'"]
        parameters: List[object] = []
        if keep_latest_runs is not None:
            conditions.append(
                "id NOT IN ("
                "SELECT id FROM runs WHERE status <> 'running' ORDER BY id DESC LIMIT ?"
                ")"
            )
            parameters.append(keep_latest_runs)
        if max_age_days is not None:
            conditions.append("COALESCE(finished_at, started_at) < datetime('now', ?)")
            parameters.append("-%d days" % max_age_days)

        eligible_runs = "SELECT id FROM runs WHERE " + " AND ".join(conditions)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            candidate_cursor = connection.execute(
                "DELETE FROM candidates WHERE run_id IN (%s)" % eligible_runs,
                parameters,
            )
            run_cursor = connection.execute(
                "DELETE FROM runs WHERE id IN (%s)" % eligible_runs,
                parameters,
            )
        return {
            "runs_deleted": max(run_cursor.rowcount, 0),
            "candidates_deleted": max(candidate_cursor.rowcount, 0),
        }

    def prune_history(
        self,
        *,
        keep_latest_runs: Optional[int] = None,
        max_age_days: Optional[int] = None,
    ) -> Dict[str, int]:
        """Alias for :meth:`cleanup_history` for retention-policy callers."""
        return self.cleanup_history(keep_latest_runs=keep_latest_runs, max_age_days=max_age_days)

    @staticmethod
    def _validate_retention_value(name: str, value: Optional[int]) -> None:
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ValueError("%s must be a non-negative integer or None" % name)

    def _initialize(self) -> None:
        with self._connect() as connection:
            # SQLite legitimately keeps ``memory``/``delete`` mode for some
            # in-memory or temporary databases. Do not treat that fallback as
            # an initialization failure.
            connection.execute("PRAGMA journal_mode = WAL").fetchone()
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS articles (
                    identity TEXT PRIMARY KEY,
                    doi TEXT,
                    title TEXT NOT NULL,
                    journal TEXT NOT NULL,
                    url TEXT NOT NULL,
                    published TEXT,
                    detected TEXT,
                    abstract TEXT,
                    source TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    fetched INTEGER NOT NULL,
                    matched INTEGER NOT NULL,
                    new_matches INTEGER NOT NULL,
                    skipped INTEGER NOT NULL,
                    error_message TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    identity TEXT NOT NULL,
                    doi TEXT,
                    title TEXT NOT NULL,
                    journal TEXT NOT NULL,
                    url TEXT NOT NULL,
                    published TEXT,
                    detected TEXT,
                    abstract TEXT,
                    source TEXT NOT NULL,
                    matched INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    matched_terms TEXT NOT NULL,
                    journal_match TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_identity TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_attempt_at TEXT,
                    last_error TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._migrate_schema(connection)

    def _migrate_schema(self, connection: sqlite3.Connection) -> None:
        current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version > _SCHEMA_VERSION:
            raise RuntimeError(
                "Database schema version %d is newer than supported version %d"
                % (current_version, _SCHEMA_VERSION)
            )

        if current_version < 1:
            self._ensure_column(connection, "articles", "detected", "TEXT")
            self._ensure_column(connection, "candidates", "detected", "TEXT")
            self._ensure_column(connection, "runs", "error_message", "TEXT")
            connection.execute("UPDATE articles SET detected = published WHERE detected IS NULL OR detected = ''")
            connection.execute("UPDATE candidates SET detected = published WHERE detected IS NULL OR detected = ''")
            connection.execute("PRAGMA user_version = 1")

        if current_version < 2:
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_candidates_run_id_id ON candidates(run_id, id)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_status_id ON runs(status, id)")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_articles_first_seen_at ON articles(first_seen_at DESC)"
            )
            connection.execute("PRAGMA user_version = 2")

        if current_version < 3:
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_notification_outbox_created "
                "ON notification_outbox(created_at, id)"
            )
            connection.execute("PRAGMA user_version = 3")

    def _ensure_column(self, connection: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        rows = connection.execute("PRAGMA table_info(%s)" % table).fetchall()
        existing = {str(row[1]) for row in rows}
        if column not in existing:
            connection.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, column_type))

    def _open_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            timeout=_BUSY_TIMEOUT_MS / 1_000,
            check_same_thread=not self._is_memory_database,
        )
        connection.execute("PRAGMA busy_timeout = %d" % _BUSY_TIMEOUT_MS)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self._is_memory_database:
            with self._memory_connection_lock:
                connection = self._memory_connection
                if connection is None:
                    raise RuntimeError("The in-memory article store is closed")
                try:
                    yield connection
                except Exception:
                    connection.rollback()
                    raise
                else:
                    connection.commit()
            return

        connection = self._open_connection()
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()


def _short_error_message(value: str, limit: int = 500) -> str:
    compact = " ".join(str(value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."
