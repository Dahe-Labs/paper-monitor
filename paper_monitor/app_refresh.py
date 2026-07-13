import threading
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from .config import load_app_config
from .dashboard import write_dashboard
from .filtering import MatchResult
from .journal_metrics import load_journal_metrics
from .keyword_analysis import AnalysisScope
from .models import Article
from .monitor import run_once
from .refresh_errors import RefreshAlreadyRunning, RefreshSourcesFailed
from .refresh_status import (
    begin_refresh,
    finish_refresh,
    new_refresh_owner_id,
    new_refresh_request_id,
    read_refresh_status,
)
from .sources import fetch_all_sources
from .storage import ArticleStore
from .windows_mutex import REFRESH_MUTEX_NAME, acquire_mutex, close_handle

_APP_REFRESH_LOCK = threading.Lock()

def run_app_refresh(
    config_path: Path,
    fetch_articles: Optional[Callable[[], List[Article]]] = None,
    *,
    request_id: Optional[str] = None,
    reason: str = "app_refresh",
) -> Dict[str, object]:
    if not _APP_REFRESH_LOCK.acquire(blocking=False):
        raise RefreshAlreadyRunning(
            "A Paper Monitor refresh is already running.",
            state=read_refresh_status(config_path),
        )

    refresh_mutex = None
    refresh_request_id = str(request_id or new_refresh_request_id())
    owner_id = new_refresh_owner_id(refresh_request_id)
    state_started = False
    try:
        refresh_mutex = acquire_mutex(REFRESH_MUTEX_NAME)
        if refresh_mutex is None:
            raise RefreshAlreadyRunning(
                "A Paper Monitor refresh is already running.",
                state=read_refresh_status(config_path),
            )
        begin_refresh(
            config_path,
            request_id=refresh_request_id,
            reason=reason,
            owner_id=owner_id,
        )
        state_started = True
        scheduled = str(reason).strip().casefold() == "scheduled_refresh"
        result = _run_app_refresh(
            config_path,
            fetch_articles=fetch_articles,
            render_dashboard=not scheduled,
            queue_notifications=scheduled,
        )
        result["request_id"] = refresh_request_id
        status = "partial" if bool(result.get("partial")) else "succeeded"
        result["status"] = status
        if not finish_refresh(
            config_path,
            request_id=refresh_request_id,
            owner_id=owner_id,
            status=status,
            result=result,
            error=_source_error_summary(result.get("source_statuses", ())) if status == "partial" else "",
        ):
            raise RuntimeError("Refresh status ownership was lost before completion.")
        return result
    except RefreshAlreadyRunning:
        raise
    except Exception as exc:
        if state_started:
            error_result = _failure_result(exc)
            finish_refresh(
                config_path,
                request_id=refresh_request_id,
                owner_id=owner_id,
                status="failed",
                result=error_result,
                error=f"{type(exc).__name__}: {exc}",
            )
        raise
    finally:
        close_handle(refresh_mutex)
        _APP_REFRESH_LOCK.release()


def _run_app_refresh(
    config_path: Path,
    fetch_articles: Optional[Callable[[], List[Article]]] = None,
    *,
    render_dashboard: bool = True,
    queue_notifications: bool = False,
) -> Dict[str, object]:
    app_config = load_app_config(config_path)
    store = ArticleStore(app_config.database_path)
    captured: List[Dict[str, object]] = []

    def capture_notification(article: Article, match: MatchResult) -> None:
        captured.append(
            {
                "identity": article.identity,
                "title": article.title,
                "journal": article.journal,
                "url": article.url,
                "doi": article.doi,
                "published": article.published,
                "detected": article.detected or article.published,
                "source": article.source,
                "matched_terms": list(match.matched_terms),
                "journal_match": match.journal_match,
            }
        )

    summary = run_once(
        config=app_config.monitor_config,
        store=store,
        fetch_articles=fetch_articles or (lambda: fetch_all_sources(app_config.source_config)),
        notify=capture_notification,
    )
    source_statuses = _source_statuses(summary)
    partial, all_failed = _source_outcome(source_statuses)
    result: Dict[str, object] = {
        "run_id": summary.run_id,
        "fetched": summary.fetched,
        "matched": summary.matched,
        "new_matches": summary.new_matches,
        "skipped": summary.skipped,
        "dashboard_path": str(app_config.dashboard_path),
        "articles": captured,
        "source_statuses": source_statuses,
        "partial": partial,
    }
    if all_failed:
        raise RefreshSourcesFailed(_all_sources_failed_message(source_statuses), result=result)

    notifications_queued = 0
    if queue_notifications and app_config.app_settings.notifications_enabled:
        notifications_queued = store.enqueue_notifications(captured)
    result["notifications_queued"] = notifications_queued

    if render_dashboard:
        metrics = load_journal_metrics(app_config.journal_metrics_path)
        write_dashboard(
            app_config.dashboard_path,
            store.latest_run(),
            store.candidates_for_run(summary.run_id),
            metrics,
            AnalysisScope(
                selected_journals=tuple(app_config.monitor_config.filter_config.journals),
                top_n=app_config.journal_scope_top_n,
            ),
        )
    result["dashboard_updated"] = bool(render_dashboard)
    return result


def _source_statuses(summary: object) -> List[Dict[str, object]]:
    raw_statuses = getattr(summary, "source_statuses", ()) or ()
    statuses: List[Dict[str, object]] = []
    for item in raw_statuses:
        if is_dataclass(item) and not isinstance(item, type):
            payload = asdict(item)
        elif isinstance(item, Mapping):
            payload = dict(item)
        else:
            continue
        statuses.append({str(key): value for key, value in payload.items()})
    return statuses


def _failure_result(error: BaseException) -> Optional[Mapping[str, object]]:
    result = getattr(error, "result", None)
    if isinstance(result, Mapping):
        return result
    raw_statuses = getattr(error, "source_statuses", None)
    if not raw_statuses:
        return None
    statuses = []
    for item in raw_statuses:
        if isinstance(item, Mapping):
            statuses.append(dict(item))
    return {"source_statuses": statuses, "partial": False} if statuses else None


def _source_outcome(source_statuses: Sequence[Mapping[str, object]]) -> tuple[bool, bool]:
    if not source_statuses:
        return False, False
    states = [str(item.get("status") or "").strip().lower() for item in source_statuses]
    has_degraded_source = any(state in {"failed", "partial"} for state in states)
    has_successful_source = any(state in {"succeeded", "partial"} for state in states)
    all_failed = has_degraded_source and not has_successful_source
    if not has_successful_source and all(state in {"failed", "skipped"} for state in states):
        all_failed = True
    return has_degraded_source and has_successful_source, all_failed


def _all_sources_failed_message(source_statuses: Sequence[Mapping[str, object]]) -> str:
    details = []
    for item in source_statuses:
        source = str(item.get("source") or item.get("target") or "source")
        error = str(item.get("error") or "failed")
        details.append(f"{source}: {error}")
    return "All configured article sources failed" + (" (" + "; ".join(details) + ")" if details else ".")


def _source_error_summary(source_statuses: object) -> str:
    if not isinstance(source_statuses, (list, tuple)):
        return ""
    details = []
    for item in source_statuses:
        if not isinstance(item, Mapping) or not item.get("error"):
            continue
        source = str(item.get("source") or item.get("target") or "source")
        details.append(f"{source}: {item.get('error')}")
    return "; ".join(details)
