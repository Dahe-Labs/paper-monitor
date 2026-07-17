"""One bounded refresh across configuration, sources, matching, and lifecycle state."""

from __future__ import annotations

import sys
import threading
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, Tuple

from .article_lifecycle import (
    ArticleDetection,
    ArticleLifecycle,
    CommitOutcome,
    DashboardSnapshot,
    NotificationAdapter,
    NotificationOutcome,
    RefreshCommit,
    RefreshRunStatus,
)
from .config import AppConfig, load_app_config
from .filtering import match_article
from .journal_metrics import JournalMetrics, load_journal_metrics
from .models import Article, normalize_doi
from .refresh_errors import RefreshAlreadyRunning
from .sources import fetch_all_sources
from .windows_mutex import REFRESH_MUTEX_NAME, acquire_mutex, close_handle

_PROCESS_REFRESH_LOCK = threading.Lock()


class RefreshIntent(str, Enum):
    BACKGROUND = "Background"
    VISIBLE = "Visible"


@dataclass(frozen=True)
class RefreshOutcome:
    run_id: str
    intent: RefreshIntent
    status: RefreshRunStatus
    fetched: int
    matched: int
    new_matches: int
    skipped: int
    source_statuses: Tuple[Mapping[str, object], ...]
    commit: CommitOutcome
    notification: Optional[NotificationOutcome] = None
    snapshot: Optional[DashboardSnapshot] = None
    error: str = ""


@dataclass(frozen=True)
class _ExecutionDependencies:
    load_config: Callable[[Path], AppConfig]
    fetch_sources: Callable[[Mapping[str, object]], Sequence[Article]]
    load_metrics: Callable[[Path], JournalMetrics]
    lifecycle_factory: Callable[[Path], ArticleLifecycle]
    notification_adapter_factory: Callable[[AppConfig], Optional[NotificationAdapter]]
    acquire_refresh_mutex: Callable[[], object]
    close_refresh_mutex: Callable[[object], None]
    new_run_id: Callable[[], str]


class RefreshExecution:
    """Execute one Refresh Run; callers choose only Background or Visible intent."""

    def __init__(
        self,
        config_path: Path,
        *,
        fetch_sources: Optional[
            Callable[[Mapping[str, object]], Sequence[Article]]
        ] = None,
    ) -> None:
        self.config_path = Path(config_path).expanduser().resolve()
        dependencies = _production_dependencies()
        if fetch_sources is not None:
            dependencies = replace(dependencies, fetch_sources=fetch_sources)
        self._dependencies = dependencies

    def execute(self, intent: RefreshIntent) -> RefreshOutcome:
        refresh_intent = RefreshIntent(intent)
        if not _PROCESS_REFRESH_LOCK.acquire(blocking=False):
            raise RefreshAlreadyRunning("A Paper Monitor refresh is already running.")

        refresh_mutex = None
        try:
            refresh_mutex = self._dependencies.acquire_refresh_mutex()
            if refresh_mutex is None:
                raise RefreshAlreadyRunning("A Paper Monitor refresh is already running.")
            return self._execute_owned(refresh_intent)
        finally:
            self._dependencies.close_refresh_mutex(refresh_mutex)
            _PROCESS_REFRESH_LOCK.release()

    def _execute_owned(self, intent: RefreshIntent) -> RefreshOutcome:
        config = self._dependencies.load_config(self.config_path)
        lifecycle = self._dependencies.lifecycle_factory(config.database_path)
        run_id = str(self._dependencies.new_run_id())

        try:
            fetched_articles = self._dependencies.fetch_sources(config.source_config)
        except Exception as exc:
            return self._failed_outcome(
                lifecycle,
                run_id,
                intent,
                source_statuses=(),
                error=f"{type(exc).__name__}: {exc}",
            )

        source_statuses = _source_statuses(fetched_articles)
        if _all_sources_failed(fetched_articles, source_statuses):
            error = _source_failure_message(fetched_articles, source_statuses)
            return self._failed_outcome(
                lifecycle,
                run_id,
                intent,
                source_statuses=source_statuses,
                error=error,
                fetched=len(fetched_articles),
            )

        metrics = self._dependencies.load_metrics(config.journal_metrics_path)
        detections = []
        matched_count = 0
        skipped_count = 0
        for article in fetched_articles:
            match = match_article(article, config.monitor_config.filter_config)
            if not match.matched:
                skipped_count += 1
                continue
            matched_count += 1
            url = str(article.url or "").strip()
            doi = normalize_doi(article.doi)
            if not url and doi:
                url = "https://doi.org/" + doi
            if not url:
                skipped_count += 1
                continue
            metric = metrics.lookup(match.journal_match or article.journal)
            detections.append(
                ArticleDetection(
                    title=article.title,
                    authors=tuple(article.authors),
                    journal=article.journal,
                    impact_reference=metric.impact_factor if metric is not None else None,
                    url=url,
                    doi=doi,
                    source=article.source,
                    source_id=article.source_id,
                    published=article.published,
                )
            )

        status = (
            RefreshRunStatus.PARTIAL
            if _is_partial(fetched_articles, source_statuses)
            else RefreshRunStatus.SUCCEEDED
        )
        commit = lifecycle.commit_refresh(
            RefreshCommit(
                run_id=run_id,
                status=status,
                detections=tuple(detections),
                source_statuses=source_statuses,
                fetched=len(fetched_articles),
                matched=matched_count,
                skipped=skipped_count,
                error=_partial_error(source_statuses) if status is RefreshRunStatus.PARTIAL else "",
            )
        )

        notification = None
        snapshot = None
        if intent is RefreshIntent.BACKGROUND and config.app_settings.notifications_enabled:
            notifier = self._dependencies.notification_adapter_factory(config)
            if notifier is not None:
                notification = lifecycle.deliver_notification(run_id, notifier)
            else:
                notification = NotificationOutcome(
                    run_id=run_id,
                    state="deferred",
                    attempted=False,
                    article_count=commit.notification_eligible_count,
                    error="Notification adapter is not configured.",
                )
        if intent is RefreshIntent.VISIBLE:
            snapshot = lifecycle.dashboard_snapshot()

        return RefreshOutcome(
            run_id=run_id,
            intent=intent,
            status=status,
            fetched=len(fetched_articles),
            matched=matched_count,
            new_matches=commit.new_count,
            skipped=skipped_count,
            source_statuses=source_statuses,
            commit=commit,
            notification=notification,
            snapshot=snapshot,
            error=_partial_error(source_statuses) if status is RefreshRunStatus.PARTIAL else "",
        )

    def _failed_outcome(
        self,
        lifecycle: ArticleLifecycle,
        run_id: str,
        intent: RefreshIntent,
        *,
        source_statuses: Tuple[Mapping[str, object], ...],
        error: str,
        fetched: int = 0,
    ) -> RefreshOutcome:
        commit = lifecycle.commit_refresh(
            RefreshCommit(
                run_id=run_id,
                status=RefreshRunStatus.FAILED,
                source_statuses=source_statuses,
                fetched=fetched,
                error=error,
            )
        )
        return RefreshOutcome(
            run_id=run_id,
            intent=intent,
            status=RefreshRunStatus.FAILED,
            fetched=fetched,
            matched=0,
            new_matches=0,
            skipped=0,
            source_statuses=source_statuses,
            commit=commit,
            error=error,
        )


def _production_dependencies() -> _ExecutionDependencies:
    return _ExecutionDependencies(
        load_config=load_app_config,
        fetch_sources=fetch_all_sources,
        load_metrics=load_journal_metrics,
        lifecycle_factory=ArticleLifecycle,
        notification_adapter_factory=_production_notification_adapter,
        acquire_refresh_mutex=lambda: acquire_mutex(REFRESH_MUTEX_NAME),
        close_refresh_mutex=close_handle,
        new_run_id=lambda: uuid.uuid4().hex,
    )


def _production_notification_adapter(_config: AppConfig) -> Optional[NotificationAdapter]:
    if sys.platform != "win32":
        return None
    from .windows_notification import WindowsSummaryNotificationAdapter

    return WindowsSummaryNotificationAdapter()


def _source_statuses(result: object) -> Tuple[Mapping[str, object], ...]:
    statuses = []
    for item in getattr(result, "source_statuses", ()) or ():
        if isinstance(item, Mapping):
            statuses.append({str(key): value for key, value in item.items()})
    return tuple(statuses)


def _all_sources_failed(
    result: object,
    statuses: Sequence[Mapping[str, object]],
) -> bool:
    explicit = getattr(result, "all_failed", None)
    if explicit is not None:
        return bool(explicit)
    attempted = [item for item in statuses if str(item.get("status") or "") != "skipped"]
    return bool(attempted) and not any(
        str(item.get("status") or "") in {"succeeded", "partial"} for item in attempted
    )


def _is_partial(
    result: object,
    statuses: Sequence[Mapping[str, object]],
) -> bool:
    explicit = getattr(result, "partial", None)
    if explicit is not None:
        return bool(explicit)
    states = {str(item.get("status") or "") for item in statuses}
    return bool(states & {"failed", "partial"}) and bool(states & {"succeeded", "partial"})


def _source_failure_message(
    result: object,
    statuses: Sequence[Mapping[str, object]],
) -> str:
    error = getattr(result, "all_failed_error", None)
    if error:
        return str(error)
    details = _partial_error(statuses)
    return details or "Every configured article source failed."


def _partial_error(statuses: Sequence[Mapping[str, object]]) -> str:
    details = []
    for item in statuses:
        error = " ".join(str(item.get("error") or "").split())
        if not error:
            continue
        source = str(item.get("source") or item.get("target") or "source")
        details.append(f"{source}: {error}")
    return "; ".join(details)
