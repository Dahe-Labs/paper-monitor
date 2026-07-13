"""Windows application entry point and non-resident runtime coordination."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path, PureWindowsPath
from typing import Dict, Iterable, Mapping, Optional

from .app_identity import DISPLAY_NAME
from .windows_mutex import WINDOW_MUTEX_NAME, is_mutex_running
from .windows_window_control import send_window_control

APP_NAME = DISPLAY_NAME
APP_DIR_NAME = "PaperMonitor"
WINDOW_READY_TIMEOUT_SECONDS = 15.0
LOGGER = logging.getLogger(__name__)


def load_app_config(config_path: Path):
    from .config import load_app_config as loader

    return loader(config_path)


def write_default_config(config_path: Path) -> None:
    from .config import write_default_config as writer

    writer(config_path)


def _is_windows_platform() -> bool:
    return os.name == "nt"


def bundled_source_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[1]


def default_windows_app_dir(env: Optional[Mapping[str, str]] = None):
    env = env or os.environ
    appdata = env.get("APPDATA")
    if appdata:
        return PureWindowsPath(appdata) / APP_DIR_NAME
    return Path.home() / "AppData" / "Roaming" / APP_DIR_NAME


def focus_existing_app_window(title: str = APP_NAME) -> bool:
    if not _is_windows_platform():
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    matches = []

    user32.EnumWindows.argtypes = [enum_windows_proc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int

    def enum_window(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        window_title = buffer.value.strip()
        if window_title == title or window_title.startswith(title + " "):
            matches.append(hwnd)
            return False
        return True

    try:
        user32.EnumWindows(enum_windows_proc(enum_window), 0)
        if not matches:
            return False
        hwnd = matches[0]
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception:
        return False


def _write_stderr(message: str) -> None:
    stream = sys.stderr
    if stream is None:
        return
    try:
        print(message, file=stream)
    except Exception:
        return


def show_window_launch_error(error: BaseException, path: str = "/") -> None:
    target = "settings" if str(path or "/") == "/settings" else "dashboard"
    message = (
        f"{APP_NAME} could not open the {target} window.\n\n"
        f"{type(error).__name__}: {error}"
    )
    if not _is_windows_platform():
        _write_stderr(message)
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    except Exception:
        _write_stderr(message)


def _log_window_launch_error(config_path: Path, path: str, error: BaseException) -> None:
    _log_app_error(config_path, f"Failed to open Paper Monitor window {path}", error)


def _log_app_error(config_path: Path, context: str, error: BaseException) -> None:
    if LOGGER.hasHandlers():
        LOGGER.error(
            "%s: %s",
            context,
            error,
            exc_info=(type(error), error, error.__traceback__),
        )
    try:
        log_path = Path(config_path).expanduser().resolve().parent / "PaperMonitor.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(f"{timestamp} {context}: {type(error).__name__}: {error}\n")
    except Exception:
        return


def _sync_windows_runtime_settings(config_path: Path) -> None:
    """Apply startup scheduling lazily without making the UI depend on it."""

    try:
        from .windows_runtime_settings import sync_windows_runtime_settings

        sync_windows_runtime_settings(config_path)
    except Exception as exc:
        _log_app_error(config_path, "Could not synchronize Paper Monitor runtime settings", exc)


def activate_existing_app_window(
    config_path: Path,
    path: str = "/",
    ready_timeout: float = WINDOW_READY_TIMEOUT_SECONDS,
) -> bool:
    deadline = time.monotonic() + max(0.0, ready_timeout)
    while True:
        try:
            send_window_control(config_path, "show", route=path)
        except Exception as exc:
            if _is_windows_platform() and not _is_window_mutex_running():
                return False
            if time.monotonic() >= deadline:
                if LOGGER.hasHandlers():
                    LOGGER.debug("Existing window did not accept route %s: %s", path, exc)
                return False
            time.sleep(0.1)
            continue
        focus_existing_app_window()
        return True


def set_background_monitoring_enabled(
    config_path: Path,
    enabled: bool,
    *,
    executable_path: Optional[Path] = None,
) -> None:
    """Apply and persist the non-resident schedule without leaving split state."""

    from .config_store import update_config_atomic
    from .windows_runtime_settings import (
        remove_legacy_startup_entry,
        sync_windows_runtime_settings,
    )

    resolved_config = Path(config_path).expanduser().resolve()
    original_payload = json.loads(resolved_config.read_text(encoding="utf-8-sig"))
    if not isinstance(original_payload, dict):
        raise ValueError("Config file must contain a JSON object.")
    original_settings = original_payload.get("app_settings")
    original_enabled = bool(
        original_settings.get("startup_enabled", False)
        if isinstance(original_settings, Mapping)
        else False
    )
    executable = Path(executable_path or sys.executable).resolve()

    sync_windows_runtime_settings(
        resolved_config,
        executable_path=executable,
        enabled_override=bool(enabled),
        cleanup_legacy_startup=False,
    )

    def mutate(payload: Dict[str, object]) -> Dict[str, object]:
        existing = payload.get("app_settings")
        app_settings = dict(existing) if isinstance(existing, Mapping) else {}
        app_settings["startup_enabled"] = bool(enabled)
        payload["app_settings"] = app_settings
        return payload

    try:
        update_config_atomic(resolved_config, mutate)
    except Exception:
        try:
            sync_windows_runtime_settings(
                resolved_config,
                executable_path=executable,
                enabled_override=original_enabled,
                cleanup_legacy_startup=False,
            )
        except Exception as rollback_error:
            _log_app_error(
                resolved_config,
                "Could not roll back background monitoring after a settings write failure",
                rollback_error,
            )
        raise

    remove_legacy_startup_entry()


def _is_window_mutex_running() -> bool:
    return is_mutex_running(WINDOW_MUTEX_NAME)


def ensure_windows_app_files(app_dir=None, source_root: Optional[Path] = None) -> Path:
    app_dir = Path(app_dir or default_windows_app_dir())
    source_root = source_root or bundled_source_root()
    app_dir.mkdir(parents=True, exist_ok=True)

    config_path = app_dir / "config.json"
    if not config_path.exists():
        example_config = source_root / "config.example.json"
        if example_config.exists():
            shutil.copy2(example_config, config_path)
        else:
            write_default_config(config_path)

    for name in ("config.example.json", "journal_metrics.json"):
        src = source_root / name
        if src.exists():
            shutil.copy2(src, app_dir / name)

    return config_path


def run_self_test(source_root: Optional[Path] = None) -> None:
    """Validate bundled read-only resources without touching the user's app data."""

    root = Path(source_root or bundled_source_root())
    config_path = root / "config.example.json"
    metrics_path = root / "journal_metrics.json"
    missing = [str(path.name) for path in (config_path, metrics_path) if not path.is_file()]
    if missing:
        raise RuntimeError("Missing bundled resource(s): " + ", ".join(missing))
    app_config = load_app_config(config_path)
    if not app_config.journal_metrics_path.is_file():
        raise RuntimeError("Bundled config does not resolve to journal_metrics.json.")
    from .journal_metrics import load_journal_metrics

    load_journal_metrics(app_config.journal_metrics_path)


def run_scheduled_refresh(config_path: Path) -> int:
    """Compatibility entry for older source-mode scheduled task definitions."""

    from .windows_background import run_background_refresh

    return run_background_refresh(config_path)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="PaperMonitor")
    parser.add_argument(
        "command",
        nargs="?",
        choices=(
            "window",
            "settings",
            "scheduled-refresh",
            "sync-runtime",
            "run",
            "install-startup",
            "uninstall-startup",
            "test-notification",
            "self-test",
        ),
        default="window",
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--app-dir", type=Path)
    parser.add_argument("--title", default=f"{APP_NAME} test")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "self-test":
        try:
            run_self_test()
        except Exception as exc:
            _write_stderr(f"{APP_NAME} self-test failed: {type(exc).__name__}: {exc}")
            return 1
        return 0
    if args.command in ("install-startup", "uninstall-startup"):
        config_path = args.config or ensure_windows_app_files(args.app_dir)
        enabled = args.command == "install-startup"
        try:
            set_background_monitoring_enabled(
                config_path,
                enabled,
                executable_path=Path(sys.executable).resolve(),
            )
        except Exception as exc:
            action = "enable" if enabled else "disable"
            _write_stderr(f"Could not {action} background monitoring: {type(exc).__name__}: {exc}")
            return 1
        return 0
    if args.command == "test-notification":
        config_path = args.config or ensure_windows_app_files(args.app_dir)
        app_config = load_app_config(config_path)
        from .windows_notification import WindowsArticleNotificationAdapter

        sent = WindowsArticleNotificationAdapter().deliver(
            {
                "title": args.title,
                "journal": "Notification Test",
                "url": "https://example.org/paper-monitor-test",
                "doi": "",
                "source": "local",
            },
            app_config.dashboard_path,
        )
        return 0 if sent else 1

    config_path = args.config or ensure_windows_app_files(args.app_dir)
    if args.command == "scheduled-refresh":
        return run_scheduled_refresh(config_path)
    if args.command == "sync-runtime":
        try:
            from .windows_runtime_settings import sync_windows_runtime_settings

            sync_windows_runtime_settings(
                config_path,
                executable_path=Path(sys.executable).resolve(),
            )
        except Exception as exc:
            _write_stderr(
                f"Could not synchronize background monitoring: {type(exc).__name__}: {exc}"
            )
            return 1
        return 0
    if args.command in ("window", "settings", "run"):
        _sync_windows_runtime_settings(config_path)
        from .windows_native_tray import ensure_native_tray

        ensure_native_tray(config_path)
        window_path = "/settings" if args.command == "settings" else "/"
        if _is_windows_platform() and _is_window_mutex_running():
            if activate_existing_app_window(config_path, path=window_path):
                return 0
            if _is_window_mutex_running():
                error = RuntimeError("The running Paper Monitor window did not respond.")
                _log_window_launch_error(config_path, window_path, error)
                show_window_launch_error(error, window_path)
                return 1
        from .windows_app_window import open_dashboard_window

        try:
            return open_dashboard_window(config_path, path=window_path)
        except Exception as exc:
            _log_window_launch_error(config_path, window_path, exc)
            show_window_launch_error(exc, window_path)
            return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
