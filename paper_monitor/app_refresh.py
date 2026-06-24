from pathlib import Path
from typing import Callable, Dict, List, Optional

from .config import load_app_config
from .dashboard import write_dashboard
from .filtering import MatchResult
from .journal_metrics import load_journal_metrics
from .keyword_analysis import AnalysisScope
from .models import Article
from .monitor import run_once
from .sources import fetch_all_sources
from .storage import ArticleStore


def run_app_refresh(
    config_path: Path,
    fetch_articles: Optional[Callable[[], List[Article]]] = None,
) -> Dict[str, object]:
    app_config = load_app_config(config_path)
    store = ArticleStore(app_config.database_path)
    captured: List[Dict[str, object]] = []

    def capture_notification(article: Article, match: MatchResult) -> None:
        captured.append(
            {
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
    return {
        "run_id": summary.run_id,
        "fetched": summary.fetched,
        "matched": summary.matched,
        "new_matches": summary.new_matches,
        "skipped": summary.skipped,
        "dashboard_path": str(app_config.dashboard_path),
        "articles": captured,
    }
