from pathlib import Path

from .article_lifecycle import ArticleLifecycle
from .config import AppConfig
from .lifecycle_dashboard import write_lifecycle_dashboard


def write_latest_dashboard(
    app_config: AppConfig,
    *,
    confirm_presentation: bool = False,
) -> Path:
    lifecycle = ArticleLifecycle(app_config.database_path)
    snapshot = lifecycle.dashboard_snapshot()
    path = write_lifecycle_dashboard(app_config, snapshot)
    if confirm_presentation:
        lifecycle.confirm_presentation(snapshot.presentation_token)
    return path
