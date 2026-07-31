import json
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Optional

SECONDS_PER_HOUR = 60 * 60
DEFAULT_INTERVAL_SECONDS = 24 * SECONDS_PER_HOUR
# A source request can be configured for up to 120 seconds. Cooperative
# cancellation stops pagination/retries immediately, while this upper bound
# still lets the one in-flight network request release its executable cleanly.
UNINSTALL_EXIT_TIMEOUT_SECONDS = 130.0
UNINSTALL_EXIT_POLL_SECONDS = 0.05
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
LEGACY_RUN_VALUE_NAME = "Paper Monitor"


def sync_windows_runtime_settings(
    config_path: Path,
    executable_path: Optional[Path] = None,
    *,
    enabled_override: Optional[bool] = None,
    launch_at_login_override: Optional[bool] = None,
    cleanup_legacy_startup: bool = True,
) -> None:
    if os.name != "nt":
        return
    payload = _config_payload(config_path)
    settings = _app_settings(payload)
    interval_hours = _interval_hours(payload)
    start_time = str(payload.get("refresh_start_time") or "").strip()

    from .windows_scheduled_task import sync_scheduled_refresh, sync_silent_startup

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
    sync_silent_startup(
        Path(config_path).resolve(),
        bool(settings.get("launch_at_login", False))
        if launch_at_login_override is None
        else bool(launch_at_login_override),
        **scheduler_kwargs,
    )
    if cleanup_legacy_startup:
        remove_legacy_startup_entry()


def remove_windows_runtime_integrations(config_path: Path) -> None:
    """Stop the installed UI/tray and remove tasks without rewriting preferences."""

    if os.name != "nt":
        return
    from .windows_scheduled_task import sync_scheduled_refresh, sync_silent_startup

    resolved_config = Path(config_path).resolve()
    # Disable launch points first so a scheduled instance cannot start between
    # shutdown signalling and the final mutex check.
    sync_scheduled_refresh(resolved_config, False, 1)
    sync_silent_startup(resolved_config, False)
    _stop_installed_runtime(resolved_config)
    remove_legacy_startup_entry()


def _stop_installed_runtime(config_path: Path) -> None:
    """Best-effort shutdown so the uninstaller can remove locked executables."""

    from .windows_mutex import (
        REFRESH_MUTEX_NAME,
        TRAY_MUTEX_NAME,
        WINDOW_MUTEX_NAME,
        is_mutex_running,
    )
    from .windows_native_tray import stop_native_tray
    from .windows_refresh_control import request_refresh_stop
    from .windows_window_control import WindowControlError, send_window_control

    deadline = time.monotonic() + UNINSTALL_EXIT_TIMEOUT_SECONDS
    request_refresh_stop()
    # A visible refresh runs inside the window host. Wait for it to leave its
    # lifecycle/database critical section before asking that host to exit.
    while (
        is_mutex_running(REFRESH_MUTEX_NAME)
        and time.monotonic() < deadline
    ):
        time.sleep(UNINSTALL_EXIT_POLL_SECONDS)

    if is_mutex_running(WINDOW_MUTEX_NAME):
        try:
            send_window_control(config_path, "close")
        except WindowControlError:
            pass
    stop_native_tray()

    runtime_mutexes = (WINDOW_MUTEX_NAME, TRAY_MUTEX_NAME, REFRESH_MUTEX_NAME)
    while time.monotonic() < deadline:
        if not any(is_mutex_running(name) for name in runtime_mutexes):
            return
        time.sleep(UNINSTALL_EXIT_POLL_SECONDS)
    running = [name for name in runtime_mutexes if is_mutex_running(name)]
    if running:
        raise RuntimeError(
            "Paper Monitor processes did not exit before uninstall: "
            + ", ".join(running)
        )


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
        interval_seconds = int(
            payload.get("interval_seconds", DEFAULT_INTERVAL_SECONDS)
        )
    except (TypeError, ValueError):
        interval_seconds = DEFAULT_INTERVAL_SECONDS
    interval_seconds = max(SECONDS_PER_HOUR, interval_seconds)
    rounded_hours = (interval_seconds + SECONDS_PER_HOUR - 1) // SECONDS_PER_HOUR
    return min(24 * 30, rounded_hours)
