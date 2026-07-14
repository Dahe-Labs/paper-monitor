"""Canonical article state and notification eligibility for Paper Monitor."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import sqlite3
import threading
import unicodedata
import urllib.parse
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator, Mapping, Optional, Protocol, Sequence, Tuple

from .models import normalize_doi

_BUSY_TIMEOUT_MS = 30_000
_DEFAULT_RETENTION_DAYS = 30
_PRESENTATION_TOKEN_RETENTION_DAYS = 7
_LEGACY_MIGRATION_NAME = "legacy-article-store-v1"
_CANONICAL_DOI_MIGRATION_NAME = "canonical-doi-query-v1"
_LEGACY_STORAGE_REMOVAL_NAME = "remove-legacy-article-store-v1"
_LEGACY_STORAGE_QUERIES = (
    ("candidates", "SELECT COUNT(*) FROM candidates", "DROP TABLE IF EXISTS candidates"),
    (
        "notification_outbox",
        "SELECT COUNT(*) FROM notification_outbox",
        "DROP TABLE IF EXISTS notification_outbox",
    ),
    ("runs", "SELECT COUNT(*) FROM runs", "DROP TABLE IF EXISTS runs"),
    ("articles", "SELECT COUNT(*) FROM articles", "DROP TABLE IF EXISTS articles"),
)
_LEGACY_STORAGE_TABLES = tuple(item[0] for item in _LEGACY_STORAGE_QUERIES)


class RefreshRunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class NotificationDelivery(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    AMBIGUOUS = "ambiguous"


class ArticleIdentityConflict(RuntimeError):
    """Raised when exact aliases point at more than one active Article."""


class UnknownPresentationToken(KeyError):
    """Raised when a presentation acknowledgement has no matching snapshot."""


@dataclass(frozen=True)
class ArticleDetection:
    title: str
    authors: Tuple[str, ...]
    journal: str
    impact_reference: Optional[float]
    url: str
    doi: str = ""
    source: str = ""
    source_id: str = ""
    published: str = ""


@dataclass(frozen=True)
class RefreshCommit:
    run_id: str
    status: RefreshRunStatus
    detections: Tuple[ArticleDetection, ...] = ()
    source_statuses: Tuple[Mapping[str, object], ...] = ()
    fetched: int = 0
    matched: int = 0
    skipped: int = 0
    error: str = ""


@dataclass(frozen=True)
class CommitOutcome:
    run_id: str
    status: RefreshRunStatus
    new_count: int
    active_count: int
    notification_eligible_count: int


@dataclass(frozen=True)
class DashboardArticle:
    article_id: str
    title: str
    authors: Tuple[str, ...]
    journal: str
    impact_reference: Optional[float]
    url: str
    first_detected_at: str


@dataclass(frozen=True)
class DashboardSnapshot:
    presentation_token: str
    articles: Tuple[DashboardArticle, ...]


@dataclass(frozen=True)
class NotificationArticle:
    article_id: str
    title: str
    journal: str
    url: str
    doi: str
    published: str
    source: str


@dataclass(frozen=True)
class NotificationHandoff:
    run_id: str
    article_count: int
    articles: Tuple[NotificationArticle, ...]


@dataclass(frozen=True)
class RefreshNotification:
    run_id: str
    heading: str
    body: str
    article_count: int
    preview_titles: Tuple[str, ...]


class NotificationAdapter(Protocol):
    def deliver(self, notification: RefreshNotification) -> NotificationDelivery:
        """Submit one notification and classify whether Windows accepted it."""


@dataclass(frozen=True)
class NotificationOutcome:
    run_id: str
    state: str
    attempted: bool
    article_count: int
    delivery: Optional[NotificationDelivery] = None
    notification: Optional[RefreshNotification] = None
    error: str = ""


class ArticleLifecycle:
    """Keep Article identity, listing retention, presentation, and notification atomic."""

    def __init__(
        self,
        database_path: Path,
        *,
        retention_days: int = _DEFAULT_RETENTION_DAYS,
        _clock: Optional[Callable[[], dt.datetime]] = None,
    ) -> None:
        if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 1:
            raise ValueError("retention_days must be a positive integer")
        self.path = Path(database_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self._clock = _clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self._thread_lock = threading.RLock()
        self._initialize()

    def commit_refresh(self, commit: RefreshCommit) -> CommitOutcome:
        run_id = str(commit.run_id or "").strip()
        if not run_id:
            raise ValueError("run_id must not be empty")
        status = RefreshRunStatus(commit.status)
        detections = tuple(commit.detections)
        if status is RefreshRunStatus.FAILED and detections:
            raise ValueError("a failed Refresh Run cannot commit Article Detections")
        for name, value in (
            ("fetched", commit.fetched),
            ("matched", commit.matched),
            ("skipped", commit.skipped),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._prune_expired(connection)
            if connection.execute(
                "SELECT 1 FROM lifecycle_refresh_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone():
                return self._commit_outcome(connection, run_id)

            connection.execute(
                """
                INSERT INTO lifecycle_refresh_runs (
                    run_id, status, source_statuses_json, fetched, matched, skipped,
                    new_count, error, committed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    run_id,
                    status.value,
                    _json_dumps(tuple(dict(item) for item in commit.source_statuses)),
                    commit.fetched,
                    commit.matched,
                    commit.skipped,
                    _compact_error(commit.error),
                    now,
                ),
            )

            for detection in detections:
                article_id, was_new = self._commit_detection(connection, detection, now)
                connection.execute(
                    """
                    INSERT OR IGNORE INTO lifecycle_refresh_articles (run_id, article_id, was_new)
                    VALUES (?, ?, ?)
                    """,
                    (run_id, article_id, 1 if was_new else 0),
                )

            new_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM lifecycle_refresh_articles
                    WHERE run_id = ? AND was_new = 1
                    """,
                    (run_id,),
                ).fetchone()[0]
            )
            connection.execute(
                "UPDATE lifecycle_refresh_runs SET new_count = ? WHERE run_id = ?",
                (new_count, run_id),
            )
            return self._commit_outcome(connection, run_id)

    def dashboard_snapshot(self) -> DashboardSnapshot:
        now = self._now()
        token = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._prune_expired(connection)
            rows = self._dashboard_rows(connection)
            connection.execute(
                """
                INSERT INTO lifecycle_presentation_tokens (token, created_at, confirmed_at)
                VALUES (?, ?, NULL)
                """,
                (token, now),
            )
            connection.executemany(
                """
                INSERT INTO lifecycle_presentation_articles (token, article_id)
                VALUES (?, ?)
                """,
                ((token, str(row["article_id"])) for row in rows),
            )

        return DashboardSnapshot(
            presentation_token=token,
            articles=_dashboard_articles(rows),
        )

    def list_articles(self, limit: Optional[int] = None) -> Tuple[DashboardArticle, ...]:
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
        ):
            raise ValueError("limit must be a positive integer or None")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._prune_expired(connection)
            rows = self._dashboard_rows(connection, limit=limit)
        return _dashboard_articles(rows)

    def confirm_presentation(self, token: str) -> int:
        normalized_token = str(token or "").strip()
        if not normalized_token:
            raise UnknownPresentationToken(token)
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT confirmed_at FROM lifecycle_presentation_tokens WHERE token = ?",
                (normalized_token,),
            ).fetchone()
            if row is None:
                raise UnknownPresentationToken(normalized_token)
            if row["confirmed_at"]:
                return 0
            cursor = connection.execute(
                """
                UPDATE lifecycle_articles
                SET presented_at = ?, notification_state = 'consumed'
                WHERE presented_at IS NULL
                  AND article_id IN (
                      SELECT article_id
                      FROM lifecycle_presentation_articles
                      WHERE token = ?
                  )
                """,
                (now, normalized_token),
            )
            connection.execute(
                "UPDATE lifecycle_presentation_tokens SET confirmed_at = ? WHERE token = ?",
                (now, normalized_token),
            )
            return max(cursor.rowcount, 0)

    def accept_notification_handoff(
        self,
        run_id: str,
        *,
        limit: int,
    ) -> NotificationHandoff:
        """Atomically hand eligible Articles to a shell that owns notification UI.

        The handoff preserves the legacy macOS/CLI contract: once the shell accepts
        the batch, Articles are not offered again even if that shell suppresses UI.
        """

        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            raise ValueError("run_id must not be empty")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._prune_expired(connection)
            if connection.execute(
                "SELECT 1 FROM lifecycle_refresh_runs WHERE run_id = ?",
                (normalized_run_id,),
            ).fetchone() is None:
                raise KeyError(normalized_run_id)
            prior = connection.execute(
                "SELECT state FROM lifecycle_notification_attempts WHERE run_id = ?",
                (normalized_run_id,),
            ).fetchone()
            if prior is not None and str(prior["state"]) != "rejected":
                return NotificationHandoff(normalized_run_id, 0, ())

            rows = connection.execute(
                """
                SELECT article.article_id, article.title, article.journal, article.url,
                       article.doi, article.published, article.source
                FROM lifecycle_refresh_articles AS detected
                JOIN lifecycle_articles AS article ON article.article_id = detected.article_id
                WHERE detected.run_id = ?
                  AND article.presented_at IS NULL
                  AND article.notification_state = 'eligible'
                ORDER BY article.first_detected_at DESC, article.article_id ASC
                """,
                (normalized_run_id,),
            ).fetchall()
            if not rows:
                self._write_notification_attempt(
                    connection,
                    normalized_run_id,
                    state="not_needed",
                    article_count=0,
                    now=now,
                    last_error="",
                )
                return NotificationHandoff(normalized_run_id, 0, ())

            article_ids = tuple(str(row["article_id"]) for row in rows)
            placeholders = ",".join("?" for _ in article_ids)
            connection.execute(
                f"""
                UPDATE lifecycle_articles
                SET notification_state = 'consumed', notified_at = ?
                WHERE article_id IN ({placeholders})
                  AND presented_at IS NULL
                  AND notification_state = 'eligible'
                """,  # nosec B608
                (now, *article_ids),
            )
            self._write_notification_attempt(
                connection,
                normalized_run_id,
                state="accepted",
                article_count=len(article_ids),
                now=now,
                last_error="",
            )
            selected = rows[:limit]

        return NotificationHandoff(
            run_id=normalized_run_id,
            article_count=len(article_ids),
            articles=tuple(
                NotificationArticle(
                    article_id=str(row["article_id"]),
                    title=str(row["title"]),
                    journal=str(row["journal"]),
                    url=str(row["url"]),
                    doi=str(row["doi"]),
                    published=str(row["published"]),
                    source=str(row["source"]),
                )
                for row in selected
            ),
        )

    def deliver_notification(
        self,
        run_id: str,
        notifier: NotificationAdapter,
    ) -> NotificationOutcome:
        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            raise ValueError("run_id must not be empty")
        now = self._now()
        article_ids: Tuple[str, ...]
        notification: RefreshNotification

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._prune_expired(connection)
            if connection.execute(
                "SELECT 1 FROM lifecycle_refresh_runs WHERE run_id = ?",
                (normalized_run_id,),
            ).fetchone() is None:
                raise KeyError(normalized_run_id)

            prior = connection.execute(
                """
                SELECT state, attempt_count, article_count, last_error
                FROM lifecycle_notification_attempts
                WHERE run_id = ?
                """,
                (normalized_run_id,),
            ).fetchone()
            if prior is not None and str(prior["state"]) != "rejected":
                state = str(prior["state"])
                delivery = (
                    NotificationDelivery.AMBIGUOUS
                    if state == "attempting"
                    else _optional_delivery(state)
                )
                return NotificationOutcome(
                    run_id=normalized_run_id,
                    state=state,
                    attempted=False,
                    article_count=int(prior["article_count"]),
                    delivery=delivery,
                    error=str(prior["last_error"] or ""),
                )

            rows = connection.execute(
                """
                SELECT article.article_id, article.title, article.journal
                FROM lifecycle_refresh_articles AS detected
                JOIN lifecycle_articles AS article ON article.article_id = detected.article_id
                WHERE detected.run_id = ?
                  AND article.presented_at IS NULL
                  AND article.notification_state = 'eligible'
                ORDER BY article.first_detected_at DESC, article.article_id ASC
                """,
                (normalized_run_id,),
            ).fetchall()
            if not rows:
                self._write_notification_attempt(
                    connection,
                    normalized_run_id,
                    state="not_needed",
                    article_count=0,
                    now=now,
                    last_error="",
                )
                return NotificationOutcome(
                    run_id=normalized_run_id,
                    state="not_needed",
                    attempted=False,
                    article_count=0,
                )

            article_ids = tuple(str(row["article_id"]) for row in rows)
            notification = _build_notification(normalized_run_id, rows)
            placeholders = ",".join("?" for _ in article_ids)
            connection.execute(
                f"""
                UPDATE lifecycle_articles
                SET notification_state = 'consumed', notified_at = ?
                WHERE article_id IN ({placeholders})
                  AND presented_at IS NULL
                  AND notification_state = 'eligible'
                """,
                (now, *article_ids),
            )
            self._write_notification_attempt(
                connection,
                normalized_run_id,
                state="attempting",
                article_count=len(article_ids),
                now=now,
                last_error="",
            )

        error = ""
        try:
            delivery = NotificationDelivery(notifier.deliver(notification))
        except Exception as exc:
            delivery = NotificationDelivery.AMBIGUOUS
            error = _compact_error(f"{type(exc).__name__}: {exc}")

        finished_at = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if delivery is NotificationDelivery.REJECTED:
                placeholders = ",".join("?" for _ in article_ids)
                connection.execute(
                    f"""
                    UPDATE lifecycle_articles
                    SET notification_state = 'eligible', notified_at = NULL
                    WHERE article_id IN ({placeholders})
                      AND presented_at IS NULL
                      AND notification_state = 'consumed'
                    """,
                    article_ids,
                )
            connection.execute(
                """
                UPDATE lifecycle_notification_attempts
                SET state = ?, completed_at = ?, last_error = ?
                WHERE run_id = ? AND state = 'attempting'
                """,
                (delivery.value, finished_at, error, normalized_run_id),
            )

        return NotificationOutcome(
            run_id=normalized_run_id,
            state=delivery.value,
            attempted=True,
            article_count=len(article_ids),
            delivery=delivery,
            notification=notification,
            error=error,
        )

    def _commit_detection(
        self,
        connection: sqlite3.Connection,
        detection: ArticleDetection,
        now: str,
    ) -> Tuple[str, bool]:
        normalized = _normalize_detection(detection)
        alias_hashes = _identity_alias_hashes(normalized)
        existing_ids = self._article_ids_for_aliases(connection, alias_hashes)
        if len(existing_ids) > 1:
            existing_ids = {self._merge_article_records(connection, existing_ids)}

        was_new = not existing_ids
        article_id = (
            next(iter(existing_ids))
            if existing_ids
            else hashlib.sha256(b"article\0" + min(alias_hashes)).hexdigest()
        )
        values = (
            normalized.title,
            _json_dumps(normalized.authors),
            normalized.journal,
            normalized.impact_reference,
            normalized.url,
            normalized.doi,
            normalized.source,
            normalized.source_id,
            normalized.published,
            now,
        )
        if was_new:
            connection.execute(
                """
                INSERT INTO lifecycle_articles (
                    article_id, title, authors_json, journal, impact_reference, url, doi,
                    source, source_id, published, first_detected_at, last_detected_at,
                    presented_at, notified_at, notification_state
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'eligible')
                """,
                (article_id, *values[:-1], now, now),
            )
        else:
            connection.execute(
                """
                UPDATE lifecycle_articles
                SET title = ?, authors_json = ?, journal = ?, impact_reference = ?, url = ?,
                    doi = ?, source = ?, source_id = ?, published = ?, last_detected_at = ?
                WHERE article_id = ?
                """,
                (*values, article_id),
            )
        connection.executemany(
            """
            INSERT OR IGNORE INTO lifecycle_article_aliases (alias_hash, article_id)
            VALUES (?, ?)
            """,
            ((alias_hash, article_id) for alias_hash in alias_hashes),
        )
        return article_id, was_new

    def _merge_article_records(
        self,
        connection: sqlite3.Connection,
        article_ids: Sequence[str],
    ) -> str:
        normalized_ids = tuple(sorted({str(article_id) for article_id in article_ids}))
        if not normalized_ids:
            raise ValueError("article_ids must not be empty")
        placeholders = ",".join("?" for _ in normalized_ids)
        rows = connection.execute(
            f"SELECT * FROM lifecycle_articles WHERE article_id IN ({placeholders})",  # nosec B608
            normalized_ids,
        ).fetchall()
        if len(rows) != len(normalized_ids):
            raise ArticleIdentityConflict("cannot merge missing active Articles")
        survivor = min(rows, key=_article_survivor_key)
        survivor_id = str(survivor["article_id"])
        duplicate_ids = tuple(
            str(row["article_id"])
            for row in rows
            if str(row["article_id"]) != survivor_id
        )
        if not duplicate_ids:
            return survivor_id

        all_placeholders = ",".join("?" for _ in normalized_ids)
        affected_runs_query = f"SELECT DISTINCT run_id FROM lifecycle_refresh_articles WHERE article_id IN ({all_placeholders})"  # nosec B608
        affected_runs = tuple(
            str(row["run_id"])
            for row in connection.execute(
                affected_runs_query,
                normalized_ids,
            ).fetchall()
        )
        refresh_rows_query = f"SELECT run_id, MAX(was_new) AS was_new FROM lifecycle_refresh_articles WHERE article_id IN ({all_placeholders}) GROUP BY run_id"  # nosec B608
        refresh_rows = connection.execute(
            refresh_rows_query,
            normalized_ids,
        ).fetchall()
        for row in refresh_rows:
            connection.execute(
                """
                INSERT OR IGNORE INTO lifecycle_refresh_articles (run_id, article_id, was_new)
                VALUES (?, ?, ?)
                """,
                (str(row["run_id"]), survivor_id, int(row["was_new"])),
            )
            connection.execute(
                """
                UPDATE lifecycle_refresh_articles
                SET was_new = MAX(was_new, ?)
                WHERE run_id = ? AND article_id = ?
                """,
                (int(row["was_new"]), str(row["run_id"]), survivor_id),
            )

        presentation_tokens_query = f"SELECT DISTINCT token FROM lifecycle_presentation_articles WHERE article_id IN ({all_placeholders})"  # nosec B608
        presentation_tokens = connection.execute(
            presentation_tokens_query,
            normalized_ids,
        ).fetchall()
        connection.executemany(
            """
            INSERT OR IGNORE INTO lifecycle_presentation_articles (token, article_id)
            VALUES (?, ?)
            """,
            ((str(row["token"]), survivor_id) for row in presentation_tokens),
        )

        aliases_query = f"SELECT alias_hash FROM lifecycle_article_aliases WHERE article_id IN ({all_placeholders})"  # nosec B608
        alias_rows = connection.execute(
            aliases_query,
            normalized_ids,
        ).fetchall()
        duplicate_placeholders = ",".join("?" for _ in duplicate_ids)
        connection.execute(
            f"DELETE FROM lifecycle_article_aliases WHERE article_id IN ({duplicate_placeholders})",  # nosec B608
            duplicate_ids,
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO lifecycle_article_aliases (alias_hash, article_id)
            VALUES (?, ?)
            """,
            ((row["alias_hash"], survivor_id) for row in alias_rows),
        )

        first_detected = min(str(row["first_detected_at"]) for row in rows)
        last_detected = max(str(row["last_detected_at"]) for row in rows)
        presented_at = _earliest_optional_timestamp(row["presented_at"] for row in rows)
        notified_at = _earliest_optional_timestamp(row["notified_at"] for row in rows)
        notification_state = (
            "consumed"
            if presented_at
            or notified_at
            or any(str(row["notification_state"]) == "consumed" for row in rows)
            else "eligible"
        )
        impact_reference = survivor["impact_reference"]
        if impact_reference is None:
            impact_reference = next(
                (row["impact_reference"] for row in rows if row["impact_reference"] is not None),
                None,
            )
        connection.execute(
            """
            UPDATE lifecycle_articles
            SET impact_reference = ?, first_detected_at = ?, last_detected_at = ?,
                presented_at = ?, notified_at = ?, notification_state = ?
            WHERE article_id = ?
            """,
            (
                impact_reference,
                first_detected,
                last_detected,
                presented_at,
                notified_at,
                notification_state,
                survivor_id,
            ),
        )
        connection.execute(
            f"DELETE FROM lifecycle_articles WHERE article_id IN ({duplicate_placeholders})",  # nosec B608
            duplicate_ids,
        )
        for run_id in affected_runs:
            connection.execute(
                """
                UPDATE lifecycle_refresh_runs
                SET new_count = (
                    SELECT COUNT(*)
                    FROM lifecycle_refresh_articles
                    WHERE run_id = ? AND was_new = 1
                )
                WHERE run_id = ?
                """,
                (run_id, run_id),
            )
        return survivor_id

    def _commit_outcome(self, connection: sqlite3.Connection, run_id: str) -> CommitOutcome:
        row = connection.execute(
            "SELECT status, new_count FROM lifecycle_refresh_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        counts = connection.execute(
            """
            SELECT
                COUNT(*) AS active_count,
                COALESCE(SUM(
                    CASE
                        WHEN article.presented_at IS NULL
                         AND article.notification_state = 'eligible'
                        THEN 1 ELSE 0
                    END
                ), 0) AS eligible_count
            FROM lifecycle_refresh_articles AS detected
            JOIN lifecycle_articles AS article ON article.article_id = detected.article_id
            WHERE detected.run_id = ?
            """,
            (run_id,),
        ).fetchone()
        return CommitOutcome(
            run_id=run_id,
            status=RefreshRunStatus(str(row["status"])),
            new_count=int(row["new_count"]),
            active_count=int(counts["active_count"]),
            notification_eligible_count=int(counts["eligible_count"]),
        )

    def _write_notification_attempt(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        *,
        state: str,
        article_count: int,
        now: str,
        last_error: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO lifecycle_notification_attempts (
                run_id, state, attempt_count, article_count, attempted_at, completed_at, last_error
            )
            VALUES (?, ?, 1, ?, ?, CASE WHEN ? = 'attempting' THEN NULL ELSE ? END, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                state = excluded.state,
                attempt_count = lifecycle_notification_attempts.attempt_count + 1,
                article_count = excluded.article_count,
                attempted_at = excluded.attempted_at,
                completed_at = excluded.completed_at,
                last_error = excluded.last_error
            """,
            (run_id, state, article_count, now, state, now, _compact_error(last_error)),
        )

    def _migrate_canonical_dois(self, connection: sqlite3.Connection, now: str) -> None:
        if connection.execute(
            "SELECT 1 FROM lifecycle_migrations WHERE name = ?",
            (_CANONICAL_DOI_MIGRATION_NAME,),
        ).fetchone():
            return

        groups = {}
        rows = connection.execute(
            "SELECT article_id, doi FROM lifecycle_articles ORDER BY article_id"
        ).fetchall()
        for row in rows:
            canonical_doi = normalize_doi(str(row["doi"] or ""))
            if canonical_doi:
                groups.setdefault(canonical_doi, []).append(row)

        corrected = 0
        merged = 0
        for canonical_doi, doi_rows in groups.items():
            doi_alias = hashlib.sha256(("doi:" + canonical_doi).encode("utf-8")).digest()
            article_ids = {str(row["article_id"]) for row in doi_rows}
            article_ids.update(self._article_ids_for_aliases(connection, (doi_alias,)))
            corrected += sum(
                str(row["doi"] or "").strip().casefold() != canonical_doi
                for row in doi_rows
            )
            if len(article_ids) > 1:
                merged += len(article_ids) - 1
                survivor_id = self._merge_article_records(connection, tuple(article_ids))
            else:
                survivor_id = next(iter(article_ids))
            connection.execute(
                "UPDATE lifecycle_articles SET doi = ? WHERE article_id = ?",
                (canonical_doi, survivor_id),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO lifecycle_article_aliases (alias_hash, article_id)
                VALUES (?, ?)
                """,
                (doi_alias, survivor_id),
            )

        connection.execute(
            """
            INSERT INTO lifecycle_migrations (name, applied_at, details_json)
            VALUES (?, ?, ?)
            """,
            (
                _CANONICAL_DOI_MIGRATION_NAME,
                now,
                _json_dumps({"corrected": corrected, "merged": merged}),
            ),
        )

    def _remove_legacy_storage(self, connection: sqlite3.Connection, now: str) -> bool:
        existing_tables = tuple(
            table for table in _LEGACY_STORAGE_TABLES if _table_exists(connection, table)
        )
        if not existing_tables:
            if connection.execute(
                "SELECT 1 FROM lifecycle_migrations WHERE name = ?",
                (_LEGACY_STORAGE_REMOVAL_NAME,),
            ).fetchone() is None:
                connection.execute(
                    """
                    INSERT INTO lifecycle_migrations (name, applied_at, details_json)
                    VALUES (?, ?, ?)
                    """,
                    (_LEGACY_STORAGE_REMOVAL_NAME, now, _json_dumps({"removed": {}})),
                )
            return False

        removed = {
            table: int(connection.execute(count_query).fetchone()[0])
            for table, count_query, _drop_query in _LEGACY_STORAGE_QUERIES
            if table in existing_tables
        }
        for _table, _count_query, drop_query in _LEGACY_STORAGE_QUERIES:
            connection.execute(drop_query)
        connection.execute(
            """
            INSERT INTO lifecycle_migrations (name, applied_at, details_json)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                applied_at = excluded.applied_at,
                details_json = excluded.details_json
            """,
            (
                _LEGACY_STORAGE_REMOVAL_NAME,
                now,
                _json_dumps({"removed": removed}),
            ),
        )
        return True

    def _migrate_legacy_state(self, connection: sqlite3.Connection, now: str) -> None:
        if connection.execute(
            "SELECT 1 FROM lifecycle_migrations WHERE name = ?",
            (_LEGACY_MIGRATION_NAME,),
        ).fetchone():
            return
        if not _table_exists(connection, "articles"):
            return

        _require_columns(
            connection,
            "articles",
            {
                "identity",
                "doi",
                "title",
                "journal",
                "url",
                "published",
                "detected",
                "source",
                "first_seen_at",
            },
        )
        migrated_at = _parse_timestamp(now, fallback=self._clock())
        cutoff = migrated_at - dt.timedelta(days=self.retention_days)
        counts = {
            "active_imported": 0,
            "expired_discarded": 0,
            "pending_eligible": 0,
            "attempted_suppressed": 0,
            "skipped": 0,
        }
        rows = connection.execute(
            """
            SELECT identity, doi, title, journal, url, published, detected, source, first_seen_at
            FROM articles
            ORDER BY identity ASC
            """
        ).fetchall()
        for row in rows:
            result = self._migrate_legacy_article(connection, row, migrated_at, cutoff)
            counts[result] += 1

        outbox_counts = self._migrate_legacy_outbox(connection)
        counts["pending_eligible"] += outbox_counts["pending_eligible"]
        counts["attempted_suppressed"] += outbox_counts["attempted_suppressed"]
        counts["skipped"] += outbox_counts["skipped"]
        connection.execute(
            """
            INSERT INTO lifecycle_migrations (name, applied_at, details_json)
            VALUES (?, ?, ?)
            """,
            (_LEGACY_MIGRATION_NAME, now, _json_dumps(counts)),
        )

    def _migrate_legacy_article(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        migrated_at: dt.datetime,
        cutoff: dt.datetime,
    ) -> str:
        doi = normalize_doi(str(row["doi"] or ""))
        url = str(row["url"] or "").strip()
        if (not url or not _canonical_url(url)) and doi:
            url = "https://doi.org/" + doi
        try:
            detection = _normalize_detection(
                ArticleDetection(
                    title=str(row["title"] or ""),
                    authors=(),
                    journal=str(row["journal"] or ""),
                    impact_reference=None,
                    url=url,
                    doi=doi,
                    source=str(row["source"] or ""),
                    source_id=_legacy_source_id(str(row["identity"] or "")),
                    published=str(row["published"] or ""),
                )
            )
            alias_hashes = _identity_alias_hashes(detection)
        except (TypeError, ValueError):
            return "skipped"

        existing_ids = self._article_ids_for_aliases(connection, alias_hashes)
        if len(existing_ids) > 1:
            raise ArticleIdentityConflict("legacy aliases point to multiple active Articles")
        if existing_ids:
            article_id = next(iter(existing_ids))
            connection.execute(
                "UPDATE lifecycle_articles SET notification_state = 'consumed' WHERE article_id = ?",
                (article_id,),
            )
            return "active_imported"

        first_seen = _parse_timestamp(
            str(row["first_seen_at"] or row["detected"] or row["published"] or ""),
            fallback=migrated_at,
        )
        if first_seen < cutoff:
            return "expired_discarded"

        article_id, _was_new = self._commit_detection(
            connection,
            detection,
            _timestamp(first_seen),
        )
        connection.execute(
            "UPDATE lifecycle_articles SET notification_state = 'consumed' WHERE article_id = ?",
            (article_id,),
        )
        return "active_imported"

    def _migrate_legacy_outbox(self, connection: sqlite3.Connection) -> Mapping[str, int]:
        counts = {"pending_eligible": 0, "attempted_suppressed": 0, "skipped": 0}
        if not _table_exists(connection, "notification_outbox"):
            return counts
        _require_columns(
            connection,
            "notification_outbox",
            {"id", "payload_json", "attempt_count"},
        )
        rows = connection.execute(
            """
            SELECT payload_json, attempt_count
            FROM notification_outbox
            ORDER BY id ASC
            """
        ).fetchall()
        pending_article_ids = set()
        attempted_article_ids = set()
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except (TypeError, ValueError):
                counts["skipped"] += 1
                continue
            if not isinstance(payload, Mapping):
                counts["skipped"] += 1
                continue
            doi = normalize_doi(str(payload.get("doi") or ""))
            url = str(payload.get("url") or "").strip()
            if (not url or not _canonical_url(url)) and doi:
                url = "https://doi.org/" + doi
            raw_authors = payload.get("authors")
            authors = (
                tuple(str(author) for author in raw_authors)
                if isinstance(raw_authors, (list, tuple))
                else ()
            )
            try:
                detection = _normalize_detection(
                    ArticleDetection(
                        title=str(payload.get("title") or ""),
                        authors=authors,
                        journal=str(payload.get("journal") or ""),
                        impact_reference=None,
                        url=url,
                        doi=doi,
                        source=str(payload.get("source") or ""),
                        source_id=str(payload.get("source_id") or ""),
                        published=str(payload.get("published") or ""),
                    )
                )
                article_ids = self._article_ids_for_aliases(
                    connection,
                    _identity_alias_hashes(detection),
                )
            except (TypeError, ValueError):
                counts["skipped"] += 1
                continue
            if len(article_ids) != 1:
                if len(article_ids) > 1:
                    raise ArticleIdentityConflict(
                        "legacy notification aliases point to multiple active Articles"
                    )
                counts["skipped"] += 1
                continue
            article_id = next(iter(article_ids))
            if int(row["attempt_count"] or 0) > 0:
                attempted_article_ids.add(article_id)
                continue
            pending_article_ids.add(article_id)

        if attempted_article_ids:
            placeholders = ",".join("?" for _ in attempted_article_ids)
            connection.execute(
                f"""
                UPDATE lifecycle_articles
                SET notification_state = 'consumed'
                WHERE article_id IN ({placeholders})
                """,
                tuple(attempted_article_ids),
            )
        counts["attempted_suppressed"] = len(attempted_article_ids)
        for article_id in sorted(pending_article_ids - attempted_article_ids):
            cursor = connection.execute(
                """
                UPDATE lifecycle_articles
                SET notification_state = 'eligible'
                WHERE article_id = ? AND presented_at IS NULL AND notified_at IS NULL
                """,
                (article_id,),
            )
            counts["pending_eligible"] += max(cursor.rowcount, 0)
        return counts

    @staticmethod
    def _article_ids_for_aliases(
        connection: sqlite3.Connection,
        alias_hashes: Sequence[bytes],
    ) -> set[str]:
        placeholders = ",".join("?" for _ in alias_hashes)
        rows = connection.execute(
            f"SELECT DISTINCT article_id FROM lifecycle_article_aliases WHERE alias_hash IN ({placeholders})",
            tuple(alias_hashes),
        ).fetchall()
        return {str(row["article_id"]) for row in rows}

    @staticmethod
    def _dashboard_rows(
        connection: sqlite3.Connection,
        *,
        limit: Optional[int] = None,
    ) -> Sequence[sqlite3.Row]:
        query = """
            SELECT article_id, title, authors_json, journal, impact_reference, url,
                   first_detected_at
            FROM lifecycle_articles
            ORDER BY first_detected_at DESC, article_id ASC
        """
        if limit is None:
            return connection.execute(query).fetchall()
        return connection.execute(query + " LIMIT ?", (limit,)).fetchall()

    def _prune_expired(self, connection: sqlite3.Connection) -> None:
        cutoff = _timestamp(self._clock() - dt.timedelta(days=self.retention_days))
        connection.execute(
            "DELETE FROM lifecycle_articles WHERE first_detected_at < ?",
            (cutoff,),
        )
        connection.execute(
            "DELETE FROM lifecycle_refresh_runs WHERE committed_at < ?",
            (cutoff,),
        )
        token_cutoff = _timestamp(
            self._clock() - dt.timedelta(days=_PRESENTATION_TOKEN_RETENTION_DAYS)
        )
        connection.execute(
            "DELETE FROM lifecycle_presentation_tokens WHERE created_at < ?",
            (token_cutoff,),
        )

    def _initialize(self) -> None:
        removed_legacy_storage = False
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL").fetchone()
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS lifecycle_articles (
                    article_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    authors_json TEXT NOT NULL,
                    journal TEXT NOT NULL,
                    impact_reference REAL,
                    url TEXT NOT NULL,
                    doi TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    published TEXT NOT NULL,
                    first_detected_at TEXT NOT NULL,
                    last_detected_at TEXT NOT NULL,
                    presented_at TEXT,
                    notified_at TEXT,
                    notification_state TEXT NOT NULL CHECK(notification_state IN ('eligible', 'consumed'))
                );

                CREATE TABLE IF NOT EXISTS lifecycle_article_aliases (
                    alias_hash BLOB PRIMARY KEY,
                    article_id TEXT NOT NULL REFERENCES lifecycle_articles(article_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS lifecycle_refresh_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK(status IN ('succeeded', 'partial', 'failed')),
                    source_statuses_json TEXT NOT NULL,
                    fetched INTEGER NOT NULL,
                    matched INTEGER NOT NULL,
                    skipped INTEGER NOT NULL,
                    new_count INTEGER NOT NULL,
                    error TEXT NOT NULL,
                    committed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS lifecycle_refresh_articles (
                    run_id TEXT NOT NULL REFERENCES lifecycle_refresh_runs(run_id) ON DELETE CASCADE,
                    article_id TEXT NOT NULL REFERENCES lifecycle_articles(article_id) ON DELETE CASCADE,
                    was_new INTEGER NOT NULL,
                    PRIMARY KEY(run_id, article_id)
                );

                CREATE TABLE IF NOT EXISTS lifecycle_presentation_tokens (
                    token TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS lifecycle_presentation_articles (
                    token TEXT NOT NULL REFERENCES lifecycle_presentation_tokens(token) ON DELETE CASCADE,
                    article_id TEXT NOT NULL REFERENCES lifecycle_articles(article_id) ON DELETE CASCADE,
                    PRIMARY KEY(token, article_id)
                );

                CREATE TABLE IF NOT EXISTS lifecycle_notification_attempts (
                    run_id TEXT PRIMARY KEY REFERENCES lifecycle_refresh_runs(run_id) ON DELETE CASCADE,
                    state TEXT NOT NULL CHECK(state IN ('attempting', 'accepted', 'rejected', 'ambiguous', 'not_needed')),
                    attempt_count INTEGER NOT NULL,
                    article_count INTEGER NOT NULL,
                    attempted_at TEXT NOT NULL,
                    completed_at TEXT,
                    last_error TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS lifecycle_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_lifecycle_articles_first_detected
                ON lifecycle_articles(first_detected_at DESC);

                CREATE INDEX IF NOT EXISTS idx_lifecycle_refresh_articles_article
                ON lifecycle_refresh_articles(article_id);
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            removed_retired_fingerprints = _table_exists(
                connection,
                "retired_article_fingerprints",
            )
            connection.execute("DROP TABLE IF EXISTS retired_article_fingerprints")
            self._migrate_legacy_state(connection, self._now())
            self._migrate_canonical_dois(connection, self._now())
            removed_legacy_storage = self._remove_legacy_storage(
                connection,
                self._now(),
            )
        if removed_legacy_storage or removed_retired_fingerprints:
            with self._connect() as connection:
                connection.execute("VACUUM")

    def _now(self) -> str:
        return _timestamp(self._clock())

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with self._thread_lock:
            connection = sqlite3.connect(str(self.path), timeout=_BUSY_TIMEOUT_MS / 1_000)
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
            connection.execute("PRAGMA foreign_keys = ON")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
            finally:
                connection.close()


def _normalize_detection(detection: ArticleDetection) -> ArticleDetection:
    title = _compact_text(detection.title)
    journal = _compact_text(detection.journal)
    url = str(detection.url or "").strip()
    if not title or not journal or not url:
        raise ValueError("Article Detection requires title, journal, and URL")
    parsed_url = urllib.parse.urlsplit(url)
    if parsed_url.scheme.casefold() not in {"http", "https"} or not parsed_url.hostname:
        raise ValueError("Article Detection URL must be HTTP(S)")
    impact = detection.impact_reference
    if impact is not None and (not isinstance(impact, (int, float)) or not math.isfinite(float(impact))):
        raise ValueError("impact_reference must be a finite number or None")
    return ArticleDetection(
        title=title,
        authors=tuple(_compact_text(author) for author in detection.authors if _compact_text(author)),
        journal=journal,
        impact_reference=float(impact) if impact is not None else None,
        url=url,
        doi=normalize_doi(detection.doi),
        source=_compact_text(detection.source),
        source_id=_compact_text(detection.source_id),
        published=_compact_text(detection.published),
    )


def _identity_alias_hashes(detection: ArticleDetection) -> Tuple[bytes, ...]:
    aliases = []
    if detection.doi:
        aliases.append("doi:" + normalize_doi(detection.doi))
    if detection.source and detection.source_id:
        aliases.append(
            "source:" + _identity_text(detection.source) + ":" + _identity_text(detection.source_id)
        )
    canonical_url = _canonical_url(detection.url)
    if canonical_url:
        aliases.append("url:" + canonical_url)
    year_match = re.search(r"(?<!\d)(\d{4})(?!\d)", detection.published)
    if detection.authors and year_match:
        aliases.append(
            "title-author-year:"
            + _identity_text(detection.title)
            + "|"
            + _identity_text(detection.authors[0])
            + "|"
            + year_match.group(1)
        )
    if not aliases:
        raise ValueError("Article Detection has no exact identity alias")
    return tuple(sorted({hashlib.sha256(alias.encode("utf-8")).digest() for alias in aliases}))


def _canonical_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(str(value or "").strip())
    scheme = parsed.scheme.casefold()
    hostname = (parsed.hostname or "").casefold()
    if scheme not in {"http", "https"} or not hostname:
        return ""
    port = parsed.port
    netloc = hostname
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc += f":{port}"
    path = urllib.parse.unquote(parsed.path or "/")
    path = urllib.parse.quote(path, safe="/%:@")
    if path != "/":
        path = path.rstrip("/")
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = urllib.parse.urlencode(
        sorted((key, value) for key, value in query_pairs if not key.casefold().startswith("utm_"))
    )
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def _identity_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def _compact_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _dashboard_articles(rows: Sequence[sqlite3.Row]) -> Tuple[DashboardArticle, ...]:
    return tuple(
        DashboardArticle(
            article_id=str(row["article_id"]),
            title=str(row["title"]),
            authors=tuple(json.loads(str(row["authors_json"]))),
            journal=str(row["journal"]),
            impact_reference=(
                float(row["impact_reference"])
                if row["impact_reference"] is not None
                else None
            ),
            url=str(row["url"]),
            first_detected_at=str(row["first_detected_at"]),
        )
        for row in rows
    )


def _article_survivor_key(row: sqlite3.Row) -> Tuple[object, ...]:
    raw_doi = str(row["doi"] or "").strip().casefold()
    canonical_doi = normalize_doi(raw_doi)
    return (
        not canonical_doi,
        raw_doi != canonical_doi,
        str(row["first_detected_at"]),
        str(row["article_id"]),
    )


def _earliest_optional_timestamp(values) -> Optional[str]:
    timestamps = tuple(str(value or "").strip() for value in values if str(value or "").strip())
    return min(timestamps) if timestamps else None


def _compact_error(value: object, limit: int = 500) -> str:
    text = _compact_text(str(value or ""))
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."[:limit]


def _build_notification(run_id: str, rows: Sequence[sqlite3.Row]) -> RefreshNotification:
    titles = tuple(str(row["title"]) for row in rows)
    if len(rows) == 1:
        heading = "New article detected"
        body = titles[0] + "\n" + str(rows[0]["journal"])
    else:
        heading = f"{len(rows)} new articles detected"
        body = "; ".join(titles[:3])
    return RefreshNotification(
        run_id=run_id,
        heading=heading,
        body=body,
        article_count=len(rows),
        preview_titles=titles[:3],
    )


def _optional_delivery(value: str) -> Optional[NotificationDelivery]:
    try:
        return NotificationDelivery(value)
    except ValueError:
        return None


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _timestamp(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: object, *, fallback: dt.datetime) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        try:
            parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _legacy_source_id(identity: str) -> str:
    prefix = "source-id:"
    normalized = str(identity or "").strip()
    return normalized[len(prefix) :] if normalized.casefold().startswith(prefix) else ""


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _require_columns(
    connection: sqlite3.Connection,
    table: str,
    required: set[str],
) -> None:
    rows = connection.execute("SELECT name FROM pragma_table_info(?)", (table,)).fetchall()
    existing = {str(row["name"]) for row in rows}
    missing = sorted(required - existing)
    if missing:
        raise RuntimeError(f"Legacy table {table} is missing required columns: {', '.join(missing)}")
