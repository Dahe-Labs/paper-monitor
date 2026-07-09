import json
import os
import sys
from pathlib import Path
from typing import Mapping, Optional


def sync_windows_runtime_settings(config_path: Path, executable_path: Optional[Path] = None) -> None:
    if os.name != "nt":
        return
    settings = _app_settings(config_path)
    executable = Path(executable_path or sys.executable).resolve()
    from .windows_tray import set_startup_enabled

    set_startup_enabled(bool(settings.get("startup_enabled", False)), executable)


def _app_settings(config_path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    settings = payload.get("app_settings")
    return settings if isinstance(settings, dict) else {}
