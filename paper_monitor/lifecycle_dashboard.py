"""Adapt canonical lifecycle snapshots to the existing dashboard renderer."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from .article_lifecycle import DashboardSnapshot, RefreshRunSummary
from .config import AppConfig, formal_journal_names
from .dashboard import keyword_analysis_payload, render_dashboard, write_dashboard_html
from .journal_metrics import load_journal_metrics
from .keyword_analysis import AnalysisScope

if TYPE_CHECKING:
    from .refresh_execution import RefreshOutcome


def render_lifecycle_dashboard(
    config: AppConfig,
    snapshot: DashboardSnapshot,
    refresh: Optional[RefreshOutcome | RefreshRunSummary] = None,
    *,
    defer_keyword_analysis: bool = False,
) -> str:
    """Render the 30-day canonical Article listing without reading legacy storage."""

    run = _refresh_summary(refresh)
    candidates = _snapshot_candidates(snapshot)
    available_journals = tuple(
        formal_journal_names(config.monitor_config.filter_config.journals)
    )
    return render_dashboard(
        run,
        candidates,
        load_journal_metrics(config.journal_metrics_path),
        AnalysisScope(
            available_journals=available_journals,
            selected_journals=available_journals,
        ),
        lifecycle_listing=True,
        defer_keyword_analysis=defer_keyword_analysis,
    )


def lifecycle_keyword_analysis_payload(
    config: AppConfig,
    snapshot: DashboardSnapshot,
) -> Dict[str, object]:
    available_journals = tuple(
        formal_journal_names(config.monitor_config.filter_config.journals)
    )
    return keyword_analysis_payload(
        _snapshot_candidates(snapshot),
        load_journal_metrics(config.journal_metrics_path),
        AnalysisScope(
            available_journals=available_journals,
            selected_journals=available_journals,
        ),
        include_computed_analysis=False,
    )


def write_lifecycle_dashboard(
    config: AppConfig,
    snapshot: DashboardSnapshot,
    refresh: Optional[RefreshOutcome | RefreshRunSummary] = None,
) -> Path:
    html = render_lifecycle_dashboard(config, snapshot, refresh)
    write_dashboard_html(config.dashboard_path, html)
    return config.dashboard_path


def _snapshot_candidates(snapshot: DashboardSnapshot) -> List[Dict[str, object]]:
    return [
        {
            "article_id": article.article_id,
            "title": article.title,
            "authors": list(article.authors),
            "journal": article.journal,
            "impact_factor": article.impact_reference,
            "url": article.url,
            "published": article.published,
            # The lifecycle timeline answers "when did Paper Monitor find this?"
            # Publication dates remain useful metadata, but they can be partial
            # (for example ``2026-07``) or refer to a future issue. Using them as
            # the sort key can bury a just-notified paper below older results.
            "detected": article.first_detected_at,
            "first_detected_at": article.first_detected_at,
            "matched": True,
            "matched_terms": [],
            "_lifecycle_listing": True,
        }
        for article in snapshot.articles
    ]


def _refresh_summary(
    refresh: Optional[RefreshOutcome | RefreshRunSummary],
) -> Dict[str, object]:
    if refresh is None:
        return {}
    return {
        "id": refresh.run_id,
        "status": refresh.status.value,
        "fetched": refresh.fetched,
        "matched": refresh.matched,
        "new_matches": refresh.new_matches,
        "skipped": refresh.skipped,
        "error_message": refresh.error,
        "finished_at": getattr(refresh, "committed_at", ""),
    }
