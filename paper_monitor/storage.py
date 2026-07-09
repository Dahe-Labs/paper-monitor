import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

from .models import Article


class ArticleStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
            cursor = connection.execute(
                """
                INSERT INTO runs (started_at, status, fetched, matched, new_matches, skipped)
                VALUES (datetime('now'), 'running', 0, 0, 0, 0)
                """
            )
            return int(cursor.lastrowid)

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
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO candidates (
                    run_id, identity, doi, title, journal, url, published, detected, abstract, source,
                    matched, reason, matched_terms, journal_match
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
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
                    1 if matched else 0,
                    reason,
                    json.dumps(matched_terms, ensure_ascii=False),
                    journal_match or "",
                ),
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

    def _initialize(self) -> None:
        with self._connect() as connection:
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
            self._ensure_column(connection, "articles", "detected", "TEXT")
            self._ensure_column(connection, "candidates", "detected", "TEXT")
            self._ensure_column(connection, "runs", "error_message", "TEXT")
            connection.execute("UPDATE articles SET detected = published WHERE detected IS NULL OR detected = ''")
            connection.execute("UPDATE candidates SET detected = published WHERE detected IS NULL OR detected = ''")

    def _ensure_column(self, connection: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        rows = connection.execute("PRAGMA table_info(%s)" % table).fetchall()
        existing = {str(row[1]) for row in rows}
        if column not in existing:
            connection.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, column_type))

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path))
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
