"""Adapt canonical lifecycle snapshots to the existing dashboard renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from .article_lifecycle import DashboardSnapshot
from .config import AppConfig
from .dashboard import render_dashboard
from .journal_metrics import load_journal_metrics
from .keyword_analysis import AnalysisScope

if TYPE_CHECKING:
    from .refresh_execution import RefreshOutcome


def render_lifecycle_dashboard(
    config: AppConfig,
    snapshot: DashboardSnapshot,
    refresh: Optional[RefreshOutcome] = None,
) -> str:
    """Render the 30-day canonical Article listing without reading legacy storage."""

    run = _refresh_summary(refresh)
    candidates = _snapshot_candidates(snapshot)
    return render_dashboard(
        run,
        candidates,
        load_journal_metrics(config.journal_metrics_path),
        AnalysisScope(
            selected_journals=tuple(config.monitor_config.filter_config.journals),
            top_n=config.journal_scope_top_n,
        ),
        lifecycle_listing=True,
    )


def _snapshot_candidates(snapshot: DashboardSnapshot) -> List[Dict[str, object]]:
    return [
        {
            "article_id": article.article_id,
            "title": article.title,
            "authors": list(article.authors),
            "journal": article.journal,
            "impact_factor": article.impact_reference,
            "url": article.url,
            "detected": article.first_detected_at,
            "matched": True,
            "matched_terms": [],
            "_lifecycle_listing": True,
        }
        for article in snapshot.articles
    ]


def _refresh_summary(refresh: Optional[RefreshOutcome]) -> Dict[str, object]:
    if refresh is None:
        return {}
    return {"id": refresh.run_id}
