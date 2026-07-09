from pathlib import Path

from .config import AppConfig
from .dashboard import write_dashboard
from .journal_metrics import load_journal_metrics
from .keyword_analysis import AnalysisScope
from .storage import ArticleStore


def write_latest_dashboard(app_config: AppConfig) -> Path:
    store = ArticleStore(app_config.database_path)
    latest_run = store.latest_run()
    candidates = store.candidates_for_run(int(latest_run["id"])) if latest_run else []
    write_dashboard(
        app_config.dashboard_path,
        latest_run,
        candidates,
        load_journal_metrics(app_config.journal_metrics_path),
        AnalysisScope(
            selected_journals=tuple(app_config.monitor_config.filter_config.journals),
            top_n=app_config.journal_scope_top_n,
        ),
    )
    return app_config.dashboard_path
