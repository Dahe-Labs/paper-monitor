"""Compatibility bridge for desktop shells that execute the shared refresh CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

from .article_lifecycle import ArticleLifecycle, RefreshRunStatus
from .config import load_app_config
from .lifecycle_dashboard import write_lifecycle_dashboard
from .models import Article
from .refresh_errors import RefreshSourcesFailed
from .refresh_execution import RefreshExecution, RefreshIntent, RefreshOutcome


def run_app_refresh(
    config_path: Path,
    fetch_articles: Optional[Callable[[], List[Article]]] = None,
) -> Dict[str, object]:
    """Refresh once and emit the stable JSON contract consumed by macOS."""

    if fetch_articles is None:
        source_fetcher = None
    else:
        def source_fetcher(_source_config):
            return fetch_articles()
    outcome = RefreshExecution(
        config_path,
        fetch_sources=source_fetcher,
    ).execute(RefreshIntent.VISIBLE)
    result = _result_payload(config_path, outcome)
    if outcome.status is RefreshRunStatus.FAILED:
        raise RefreshSourcesFailed(
            outcome.error or "Every configured article source failed.",
            result=result,
        )
    return result


def _result_payload(config_path: Path, outcome: RefreshOutcome) -> Dict[str, object]:
    config = load_app_config(config_path)
    source_statuses = [dict(status) for status in outcome.source_statuses]
    result: Dict[str, object] = {
        "run_id": outcome.run_id,
        "fetched": outcome.fetched,
        "matched": outcome.matched,
        "new_matches": outcome.new_matches,
        "skipped": outcome.skipped,
        "dashboard_path": str(config.dashboard_path),
        "articles": [],
        "source_statuses": source_statuses,
        "partial": outcome.status is RefreshRunStatus.PARTIAL,
        "status": outcome.status.value,
        "dashboard_updated": False,
    }
    if outcome.status is RefreshRunStatus.FAILED or outcome.snapshot is None:
        return result

    write_lifecycle_dashboard(config, outcome.snapshot, outcome)
    lifecycle = ArticleLifecycle(config.database_path)
    handoff = lifecycle.accept_notification_handoff(
        outcome.run_id,
        limit=config.monitor_config.max_notifications,
    )
    result["articles"] = [
        {
            "identity": article.article_id,
            "title": article.title,
            "journal": article.journal,
            "url": article.url,
            "doi": article.doi,
            "published": article.published,
            "detected": article.published,
            "source": article.source,
            "matched_terms": [],
            "journal_match": article.journal,
        }
        for article in handoff.articles
    ]
    result["notification_article_count"] = handoff.article_count
    result["dashboard_updated"] = True
    return result
