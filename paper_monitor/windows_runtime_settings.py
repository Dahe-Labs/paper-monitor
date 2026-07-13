import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Optional

SECONDS_PER_HOUR = 60 * 60
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
LEGACY_RUN_VALUE_NAME = "Paper Monitor"


def sync_windows_runtime_settings(
    config_path: Path,
    executable_path: Optional[Path] = None,
    *,
    enabled_override: Optional[bool] = None,
    cleanup_legacy_startup: bool = True,
) -> None:
    if os.name != "nt":
        return
    payload = _config_payload(config_path)
    settings = _app_settings(payload)
    interval_hours = _interval_hours(payload)
    start_time = str(payload.get("refresh_start_time") or "").strip()

    from .windows_scheduled_task import sync_scheduled_refresh

    executable = Path(executable_path or sys.executable).resolve()
    scheduler_kwargs = {"executable": executable} if executable_path is not None else {}
    sync_scheduled_refresh(
        Path(config_path).resolve(),
        bool(settings.get("startup_enabled", False))
        if enabled_override is None
        else bool(enabled_override),
        interval_hours,
        start_time,
        **scheduler_kwargs,
    )
    if cleanup_legacy_startup:
        remove_legacy_startup_entry()


def remove_legacy_startup_entry(*, registry_module=None) -> None:
    """Remove the obsolete Python tray login entry if an older release left it behind."""

    if registry_module is None:
        import winreg as registry_module

    try:
        key = registry_module.OpenKey(
            registry_module.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            registry_module.KEY_SET_VALUE,
        )
    except FileNotFoundError:
        return
    try:
        try:
            registry_module.DeleteValue(key, LEGACY_RUN_VALUE_NAME)
        except (FileNotFoundError, OSError):
            pass
    finally:
        registry_module.CloseKey(key)


def _config_payload(config_path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise RuntimeError(f"Could not read runtime settings from {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Runtime settings are not valid JSON: {config_path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Runtime settings root must be an object: {config_path}")
    return payload


def _app_settings(payload: Mapping[str, object]) -> Mapping[str, object]:
    settings = payload.get("app_settings")
    return settings if isinstance(settings, dict) else {}


def _interval_hours(payload: Mapping[str, object]) -> int:
    try:
        interval_seconds = int(payload.get("interval_seconds", 12 * SECONDS_PER_HOUR))
    except (TypeError, ValueError):
        interval_seconds = 12 * SECONDS_PER_HOUR
    interval_seconds = max(SECONDS_PER_HOUR, interval_seconds)
    rounded_hours = (interval_seconds + SECONDS_PER_HOUR - 1) // SECONDS_PER_HOUR
    return min(24 * 30, rounded_hours)
