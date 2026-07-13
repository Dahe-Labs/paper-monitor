import argparse
import datetime as dt
import inspect
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PureWindowsPath
from typing import Callable, Dict, Iterable, List, Mapping, Optional

from .app_identity import DISPLAY_NAME
from .refresh_errors import RefreshAlreadyRunning
from .refresh_status import new_refresh_request_id, read_refresh_status
from .windows_mutex import (
    TRAY_MUTEX_NAME,
    WINDOW_MUTEX_NAME,
    acquire_mutex,
    close_handle,
    is_mutex_running,
)
from .windows_window_control import send_window_control

APP_NAME = DISPLAY_NAME
APP_DIR_NAME = "PaperMonitor"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
WM_LBUTTONDBLCLK = 0x0203
LAUNCHED_BY_TRAY_ENV = "PAPER_MONITOR_LAUNCHED_BY_TRAY"
TRAY_SETTINGS_POLL_SECONDS = 0.5
WINDOW_READY_TIMEOUT_SECONDS = 15.0
LAUNCH_REFRESH_DELAY_SECONDS = 2.0
MANUAL_TRAY_LAUNCH_DELAY_SECONDS = 3.0
QUIT_REFRESH_WAIT_SECONDS = 15.0
LOGGER = logging.getLogger(__name__)


def run_app_refresh(
    config_path: Path,
    *,
    request_id: Optional[str] = None,
    reason: str = "app_refresh",
) -> Dict[str, object]:
    from .app_refresh import run_app_refresh as runner

    return runner(config_path, request_id=request_id, reason=reason)


def load_app_config(config_path: Path):
    from .config import load_app_config as loader

    return loader(config_path)


def write_default_config(config_path: Path) -> None:
    from .config import write_default_config as writer

    writer(config_path)


def _is_windows_platform() -> bool:
    return os.name == "nt"


class RefreshReason(str, Enum):
    PROCESS_LAUNCH = "process_launch"
    LOGIN_STARTUP = "login_startup"
    MANUAL_REFRESH = "manual_refresh"
    SCHEDULED_REFRESH = "scheduled_refresh"


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


def build_refresh_command(python_executable, config_path) -> List[str]:
    return [
        str(python_executable),
        "-m",
        "paper_monitor.cli",
        "app-refresh",
        "--config",
        str(config_path),
    ]


def notification_target(article: Dict[str, object], dashboard_path: Path) -> str:
    url = str(article.get("url") or "")
    doi = str(article.get("doi") or "")
    if url.startswith(("http://", "https://")):
        return url
    if doi:
        return "https://doi.org/" + doi
    return Path(dashboard_path).resolve().as_uri()


def build_startup_registry_value(executable_path) -> str:
    return f'"{executable_path}" tray --quiet'


def app_window_command(config_path: Path, path: str = "/") -> List[str]:
    command = "settings" if str(path or "/") == "/settings" else "window"
    executable = str(Path(sys.executable).resolve())
    if getattr(sys, "frozen", False):
        return [executable, command, "--config", str(config_path)]
    return [executable, "-m", "paper_monitor.windows_tray", command, "--config", str(config_path)]


def tray_process_command(
    config_path: Path,
    refresh_on_launch: bool = True,
    launch_reason: Optional[RefreshReason] = None,
) -> List[str]:
    executable = str(Path(sys.executable).resolve())
    if getattr(sys, "frozen", False):
        command = [executable, "tray", "--quiet"]
    else:
        command = [executable, "-m", "paper_monitor.windows_tray", "tray", "--quiet"]
    if not refresh_on_launch:
        command.append("--no-launch-refresh")
    if launch_reason is not None:
        command.extend(["--launch-reason", launch_reason.value])
    command.extend(["--config", str(config_path)])
    return command


def launch_app_window(config_path: Path, path: str = "/") -> Optional[subprocess.Popen]:
    kwargs: Dict[str, object] = {}
    if _is_windows_platform():
        if _is_window_mutex_running():
            return None
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        kwargs["stdin"] = subprocess.DEVNULL
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
        env = _internal_child_environment()
        env[LAUNCHED_BY_TRAY_ENV] = "1"
        kwargs["env"] = env
    return subprocess.Popen(app_window_command(Path(config_path), path=path), **kwargs)


def _internal_child_environment() -> Dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if getattr(sys, "frozen", False):
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


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


def show_tray_message(message: str) -> None:
    if not _is_windows_platform():
        _write_stderr(message)
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x40)
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
            handle.write(
                f"{timestamp} {context}: {type(error).__name__}: {error}\n"
            )
    except Exception:
        return


def _sync_windows_runtime_settings(config_path: Path) -> None:
    """Apply startup scheduling lazily without making the UI depend on it."""

    try:
        from .windows_runtime_settings import sync_windows_runtime_settings

        sync_windows_runtime_settings(config_path)
    except Exception as exc:
        _log_app_error(config_path, "Could not synchronize Paper Monitor runtime settings", exc)


def dispatch_window_control(config_path: Path, action: str, route: Optional[str] = None) -> bool:
    send_window_control(config_path, action, route=route)
    return True


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


def set_startup_enabled(enabled: bool, executable_path, registry_module=None) -> None:
    """Manage the legacy logon Run entry.

    New releases only call this with ``False`` while migrating users to a
    short-lived Task Scheduler job.  The function stays public so old installs
    and callers can remove the former resident tray entry safely.
    """

    if registry_module is None:
        import winreg as registry_module

    key = registry_module.OpenKey(
        registry_module.HKEY_CURRENT_USER,
        RUN_KEY_PATH,
        0,
        registry_module.KEY_SET_VALUE,
    )
    try:
        if enabled:
            registry_module.SetValueEx(
                key,
                APP_NAME,
                0,
                registry_module.REG_SZ,
                build_startup_registry_value(executable_path),
            )
        else:
            try:
                registry_module.DeleteValue(key, APP_NAME)
            except (FileNotFoundError, OSError):
                pass
    finally:
        registry_module.CloseKey(key)


def set_background_monitoring_enabled(
    config_path: Path,
    enabled: bool,
    *,
    executable_path: Optional[Path] = None,
) -> None:
    """Apply and persist the non-resident schedule without leaving split state."""

    from .config_store import update_config_atomic
    from .windows_runtime_settings import sync_windows_runtime_settings

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

    try:
        set_startup_enabled(False, executable)
    except FileNotFoundError:
        pass


def ensure_tray_process(
    config_path: Path,
    refresh_on_launch: bool = True,
    launch_reason: RefreshReason = RefreshReason.PROCESS_LAUNCH,
) -> bool:
    if not _is_windows_platform() or _is_tray_mutex_running():
        return False

    creationflags = 0
    for name in ("CREATE_NO_WINDOW", "DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= int(getattr(subprocess, name, 0))

    try:
        subprocess.Popen(
            tray_process_command(
                config_path,
                refresh_on_launch=refresh_on_launch,
                launch_reason=launch_reason,
            ),
            cwd=str(Path(config_path).parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_internal_child_environment(),
            close_fds=True,
            creationflags=creationflags,
        )
    except OSError as exc:
        _log_app_error(config_path, "Could not start Paper Monitor tray process", exc)
        return False
    return True


def ensure_tray_process_delayed(
    config_path: Path,
    refresh_on_launch: bool = True,
    launch_reason: RefreshReason = RefreshReason.PROCESS_LAUNCH,
    delay_seconds: float = MANUAL_TRAY_LAUNCH_DELAY_SECONDS,
) -> Optional[threading.Timer]:
    if not _is_windows_platform() or _is_tray_mutex_running():
        return None

    timer = threading.Timer(
        max(0.0, delay_seconds),
        lambda: ensure_tray_process(
            config_path,
            refresh_on_launch=refresh_on_launch,
            launch_reason=launch_reason,
        ),
    )
    timer.name = "PaperMonitorTrayLaunch"
    timer.daemon = True
    timer.start()
    return timer


def _is_tray_mutex_running() -> bool:
    return is_mutex_running(TRAY_MUTEX_NAME)


def _is_window_mutex_running() -> bool:
    return is_mutex_running(WINDOW_MUTEX_NAME)


def _acquire_tray_mutex():
    return acquire_mutex(TRAY_MUTEX_NAME)


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


def run_scheduled_refresh(
    config_path: Path,
    *,
    notifier: Optional["WindowsToastNotifier"] = None,
    refresh_function=None,
) -> int:
    """Run one scheduled refresh and exit without creating a tray or window."""

    config_path = Path(config_path)
    runner = refresh_function or run_app_refresh
    try:
        result = runner(config_path, reason=RefreshReason.SCHEDULED_REFRESH.value)
        if not isinstance(result, dict):
            raise RuntimeError("Scheduled refresh returned an invalid result.")
        status = str(result.get("status") or "succeeded").strip().lower()
        if status not in {"succeeded", "partial"}:
            raise RuntimeError(f"Scheduled refresh finished with status {status or 'unknown'}.")

        app_config = load_app_config(config_path)
        notification_failures = 0
        if app_config.app_settings.notifications_enabled:
            notification_sender = notifier or WindowsToastNotifier(icon_path=windows_icon_path())
            if "notifications_queued" in result:
                from .storage import ArticleStore

                store = ArticleStore(app_config.database_path)
                for pending in store.pending_notifications():
                    notification_id = int(pending["id"])
                    article = pending["article"]
                    try:
                        delivered = bool(
                            notification_sender.notify_article(article, app_config.dashboard_path)
                        )
                    except Exception as exc:
                        delivered = False
                        error_message = f"{type(exc).__name__}: {exc}"
                    else:
                        error_message = "Desktop notification API reported delivery failure"
                    if delivered:
                        store.mark_notification_sent(notification_id)
                    else:
                        notification_failures += 1
                        store.mark_notification_failed(notification_id, error_message)
            else:
                # Compatibility for injected refresh runners used by integrators/tests.
                for article in result.get("articles", ()):
                    if not isinstance(article, dict):
                        continue
                    if not notification_sender.notify_article(article, app_config.dashboard_path):
                        notification_failures += 1
        if notification_failures:
            error = RuntimeError(
                f"{notification_failures} scheduled notification(s) could not be delivered."
            )
            _log_app_error(config_path, "Paper Monitor scheduled notification delivery failed", error)
            return 1
        return 0
    except Exception as exc:
        _log_app_error(config_path, "Paper Monitor scheduled refresh failed", exc)
        _write_stderr(f"{APP_NAME} scheduled refresh failed: {exc}")
        return 1


@dataclass
class TrayStatus:
    last_run: str = "Last Run: never"
    last_result: str = "Last Result: none"
    refreshing: bool = False
    refresh_status: str = "idle"
    refresh_request_id: str = ""
    notification_attempts: int = 0
    notification_failures: int = 0


class WindowsToastNotifier:
    def __init__(self, app_id: str = APP_NAME, icon_path: Optional[Path] = None):
        self.app_id = app_id
        self.icon_path = icon_path

    def notify_article(self, article: Dict[str, object], dashboard_path: Path) -> bool:
        target = notification_target(article, dashboard_path)
        title = _truncate(str(article.get("title") or APP_NAME), 120)
        journal = _truncate(str(article.get("journal") or article.get("source") or ""), 80)
        message = str(article.get("doi") or article.get("url") or "Open dashboard")
        try:
            from win11toast import notify
        except ImportError:
            return False

        kwargs = {"on_click": target}
        if self.icon_path is not None:
            kwargs["icon"] = str(self.icon_path)
        try:
            notify(title, f"{journal}\n{message}".strip(), **kwargs)
        except Exception as exc:
            if LOGGER.hasHandlers():
                LOGGER.warning("Windows notification failed: %s", exc)
            return False
        return True


class WindowsTrayApp:
    def __init__(
        self,
        config_path: Path,
        notifier: Optional[WindowsToastNotifier] = None,
        refresh_function=run_app_refresh,
        open_window: Callable[[Path, str], object] = launch_app_window,
        focus_window: Callable[[], bool] = focus_existing_app_window,
        launch_error_handler: Callable[[BaseException, str], None] = show_window_launch_error,
        control_window: Callable[[Path, str, Optional[str]], bool] = dispatch_window_control,
        message_handler: Callable[[str], None] = show_tray_message,
    ):
        self.config_path = Path(config_path)
        self.notifier = notifier or WindowsToastNotifier(icon_path=windows_icon_path())
        self.refresh_function = refresh_function
        self.open_window = open_window
        self.focus_window = focus_window
        self.launch_error_handler = launch_error_handler
        self.control_window = control_window
        self.message_handler = message_handler
        self.status = TrayStatus()
        self._stop_event = threading.Event()
        self._refresh_lock = threading.Lock()
        self._refresh_idle = threading.Event()
        self._refresh_idle.set()
        self._lifecycle_lock = threading.RLock()
        self._accept_refreshes = True
        self._active_refresh_thread: Optional[threading.Thread] = None
        self._scheduler_thread: Optional[threading.Thread] = None
        self._manual_refresh_thread: Optional[threading.Thread] = None
        self._shutdown_thread: Optional[threading.Thread] = None
        self._shutdown_deadline: Optional[float] = None
        self._window_launch_lock = threading.RLock()
        self._window_process = None
        self._pending_window_route: Optional[str] = None
        self._window_control_monitor_active = False
        self._icon = None

    def run(
        self,
        refresh_on_start: bool = True,
        quiet: bool = False,
        launch_reason: Optional[RefreshReason] = None,
    ) -> None:
        tray_mutex = _acquire_tray_mutex()
        if tray_mutex is None:
            return
        try:
            app_config = load_app_config(self.config_path)
            effective_launch_reason = launch_reason or (
                RefreshReason.LOGIN_STARTUP if quiet else RefreshReason.PROCESS_LAUNCH
            )
            self._scheduler_thread = self._start_refresh_thread(
                refresh_on_start=refresh_on_start and app_config.app_settings.refresh_on_launch,
                launch_reason=effective_launch_reason,
            )
            self._icon = self._build_icon()
            self._icon.run(
                setup=lambda icon: self._watch_tray_visibility(
                    icon,
                    initial_visible=app_config.app_settings.show_tray_icon,
                )
            )
        finally:
            self._begin_shutdown()
            self._wait_for_background_work(QUIT_REFRESH_WAIT_SECONDS)
            close_handle(tray_mutex)

    def _watch_tray_visibility(self, icon, initial_visible: bool) -> None:
        visible = bool(initial_visible)
        self._set_tray_icon_visible(icon, visible)
        while not self._stop_event.wait(TRAY_SETTINGS_POLL_SECONDS):
            try:
                configured = load_app_config(self.config_path).app_settings.show_tray_icon
            except Exception as exc:
                if LOGGER.hasHandlers():
                    LOGGER.debug("Could not reload tray visibility setting: %s", exc)
                continue
            if configured == visible:
                continue
            if self._set_tray_icon_visible(icon, configured):
                visible = configured

    def _set_tray_icon_visible(self, icon, visible: bool) -> bool:
        try:
            icon.visible = bool(visible)
            return True
        except Exception as exc:
            _log_app_error(self.config_path, "Could not update tray icon visibility", exc)
            if LOGGER.hasHandlers():
                LOGGER.warning("Could not update tray icon visibility: %s", exc)
            return False

    def refresh_now(self, reason: RefreshReason = RefreshReason.MANUAL_REFRESH) -> None:
        with self._lifecycle_lock:
            if not self._accept_refreshes:
                self.status.last_result = "Last Result: Refresh skipped (app is closing)"
                return
            if not self._refresh_lock.acquire(blocking=False):
                self.status.last_result = "Last Result: Refresh already running"
                return
            self._active_refresh_thread = threading.current_thread()
            self._refresh_idle.clear()

        request_id = new_refresh_request_id()
        try:
            self.status.refreshing = True
            self.status.refresh_status = "running"
            self.status.refresh_request_id = request_id
            self.status.notification_attempts = 0
            self.status.notification_failures = 0
            self.status.last_result = "Last Result: Refreshing..."
            result = _invoke_refresh_function(
                self.refresh_function,
                self.config_path,
                request_id=request_id,
                reason=reason.value,
            )
            persisted = read_refresh_status(self.config_path)
            if persisted and str(persisted.get("request_id") or "") == request_id:
                self.status.refresh_status = str(persisted.get("status") or "succeeded")
                persisted_result = persisted.get("result")
                if isinstance(persisted_result, dict):
                    result = persisted_result
            else:
                self.status.refresh_status = str(result.get("status") or "succeeded")
            app_config = load_app_config(self.config_path)
            self.status.last_run = "Last Run: " + time.strftime("%Y-%m-%d %H:%M")
            should_notify = app_config.app_settings.notifications_enabled
            if (
                reason == RefreshReason.LOGIN_STARTUP
                and app_config.app_settings.silent_startup_notifications
            ):
                should_notify = False
            if should_notify:
                for article in result.get("articles", []):
                    if isinstance(article, dict):
                        self.status.notification_attempts += 1
                        if not self.notifier.notify_article(article, app_config.dashboard_path):
                            self.status.notification_failures += 1
            self.status.last_result = _format_result(
                result,
                notification_attempts=self.status.notification_attempts,
                notification_failures=self.status.notification_failures,
            )
            self._reload_open_window()
        except RefreshAlreadyRunning as exc:
            state = exc.state or read_refresh_status(self.config_path)
            if state:
                self.status.refresh_status = str(state.get("status") or "running")
                self.status.refresh_request_id = str(state.get("request_id") or "")
            self.status.last_result = "Last Result: Refresh already running"
        except Exception as exc:
            state = read_refresh_status(self.config_path)
            if state and str(state.get("request_id") or "") == request_id:
                self.status.refresh_status = str(state.get("status") or "failed")
            else:
                self.status.refresh_status = "failed"
            self.status.last_result = "Last Result: Refresh failed"
            _log_app_error(self.config_path, "Paper Monitor refresh failed", exc)
            _write_stderr(f"{APP_NAME} refresh failed: {exc}")
        finally:
            self.status.refreshing = False
            with self._lifecycle_lock:
                if self._active_refresh_thread is threading.current_thread():
                    self._active_refresh_thread = None
                    self._refresh_idle.set()
                self._refresh_lock.release()

    def start_manual_refresh(self) -> bool:
        """Start one tracked manual refresh without blocking the tray UI thread."""

        with self._lifecycle_lock:
            if not self._accept_refreshes:
                return False
            if self._manual_refresh_thread is not None and self._manual_refresh_thread.is_alive():
                self.status.last_result = "Last Result: Refresh already running"
                return False
            thread = threading.Thread(
                target=lambda: self.refresh_now(reason=RefreshReason.MANUAL_REFRESH),
                name="PaperMonitorManualRefresh",
                daemon=True,
            )
            self._manual_refresh_thread = thread
            try:
                thread.start()
            except Exception:
                self._manual_refresh_thread = None
                raise
            return True

    def open_dashboard(self) -> None:
        self._open_app_window_once("/")

    def open_settings(self) -> None:
        self._open_app_window_once("/settings")

    def _open_app_window_once(self, path: str) -> None:
        with self._window_launch_lock:
            self._pending_window_route = path
            if _process_is_running(self._window_process):
                if self._deliver_pending_window_route():
                    return
                self.focus_window()
                self._start_window_launch_monitor(self._window_process, path)
                return
            if _is_windows_platform() and _is_window_mutex_running():
                if self._deliver_pending_window_route():
                    return
                self.focus_window()
                self._start_window_launch_monitor(None, path)
                return
            try:
                process = self.open_window(self.config_path, path)
            except Exception as exc:
                self.status.last_result = "Last Result: Could not open window"
                _log_window_launch_error(self.config_path, path, exc)
                self.launch_error_handler(exc, path)
                return
            if process is None:
                if self._deliver_pending_window_route():
                    return
                self.focus_window()
                self._start_window_launch_monitor(None, path)
                return
            self._window_process = process if _has_process_poll(process) else None
            if _has_process_pid(process):
                self._start_window_launch_monitor(process, path)

    def post_test_notification(self) -> None:
        app_config = load_app_config(self.config_path)
        sent = self.notifier.notify_article(
            {
                "title": f"{APP_NAME} test",
                "journal": "Notification Test",
                "url": "https://example.org/paper-monitor-test",
                "doi": "",
                "source": "local",
            },
            app_config.dashboard_path,
        )
        if sent:
            self.status.last_result = "Last Result: Test notification sent"
        else:
            self.status.last_result = "Last Result: Test notification failed"
            self.message_handler(
                "Paper Monitor could not send a Windows notification. "
                "Check Windows notification permissions and the win11toast dependency."
            )

    def quit(self) -> None:
        first_request = self._begin_shutdown()
        if first_request:
            self._send_window_control("close")
        icon = self._icon
        if icon is None:
            return
        if self._refresh_idle.is_set():
            _safe_stop_icon(icon)
            return
        with self._lifecycle_lock:
            if self._shutdown_thread is not None and self._shutdown_thread.is_alive():
                return
            thread = threading.Thread(
                target=lambda: self._stop_icon_after_refresh(icon),
                name="PaperMonitorShutdown",
                daemon=True,
            )
            self._shutdown_thread = thread
            thread.start()

    def _begin_shutdown(self) -> bool:
        with self._lifecycle_lock:
            first_request = self._accept_refreshes
            self._accept_refreshes = False
            self._stop_event.set()
            if self._shutdown_deadline is None:
                self._shutdown_deadline = time.monotonic() + QUIT_REFRESH_WAIT_SECONDS
            return first_request

    def _stop_icon_after_refresh(self, icon) -> None:
        self._refresh_idle.wait(self._shutdown_wait_remaining(QUIT_REFRESH_WAIT_SECONDS))
        _safe_stop_icon(icon)

    def _wait_for_background_work(self, timeout: float) -> None:
        deadline = time.monotonic() + self._shutdown_wait_remaining(timeout)
        self._refresh_idle.wait(max(0.0, deadline - time.monotonic()))
        current = threading.current_thread()
        for thread in (self._manual_refresh_thread, self._scheduler_thread):
            if thread is None or thread is current or not thread.is_alive():
                continue
            thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def _shutdown_wait_remaining(self, timeout: float) -> float:
        allowed = max(0.0, float(timeout))
        with self._lifecycle_lock:
            if self._shutdown_deadline is None:
                return allowed
            return min(allowed, max(0.0, self._shutdown_deadline - time.monotonic()))

    def _send_window_control(self, action: str, route: Optional[str] = None) -> bool:
        try:
            return bool(self.control_window(self.config_path, action, route))
        except Exception as exc:
            if LOGGER.hasHandlers():
                LOGGER.debug("Window control %s %s failed: %s", action, route, exc)
            return False

    def _reload_open_window(self) -> None:
        if _process_is_running(self._window_process) or (_is_windows_platform() and _is_window_mutex_running()):
            if self.control_window is dispatch_window_control:
                self._send_window_control("refresh-complete")
            else:
                # Preserve compatibility for older injected window controllers.
                self._send_window_control("reload", "/")

    def _deliver_pending_window_route(self) -> bool:
        with self._window_launch_lock:
            route = self._pending_window_route
        if route is None or not self._send_window_control("show", route):
            return False
        with self._window_launch_lock:
            if self._pending_window_route == route:
                self._pending_window_route = None
        self.focus_window()
        return True

    def _start_window_launch_monitor(self, process, path: str) -> None:
        with self._window_launch_lock:
            if self._window_control_monitor_active:
                return
            self._window_control_monitor_active = True
        thread = threading.Thread(
            target=lambda: self._monitor_window_launch(process, path),
            name="PaperMonitorWindowLaunch",
            daemon=True,
        )
        thread.start()

    def _monitor_window_launch(self, process, path: str) -> None:
        deadline = time.monotonic() + WINDOW_READY_TIMEOUT_SECONDS
        restart_attempted = False
        try:
            while not self._stop_event.is_set():
                if self._deliver_pending_window_route():
                    return
                if process is not None and not _process_is_running(process):
                    with self._window_launch_lock:
                        if self._window_process is process:
                            self._window_process = None
                    process = None
                window_running = _is_windows_platform() and _is_window_mutex_running()
                if process is None and not window_running:
                    if restart_attempted:
                        self._report_window_launch_failure(
                            RuntimeError("The Paper Monitor window process exited before becoming ready."),
                            path,
                        )
                        return
                    restart_attempted = True
                    try:
                        replacement = self.open_window(self.config_path, path)
                    except Exception as exc:
                        self._report_window_launch_failure(exc, path)
                        return
                    process = replacement if _has_process_poll(replacement) else None
                    with self._window_launch_lock:
                        self._window_process = process
                    deadline = time.monotonic() + WINDOW_READY_TIMEOUT_SECONDS
                    self._stop_event.wait(0.1)
                    continue

                if time.monotonic() >= deadline:
                    if process is not None and not restart_attempted:
                        _terminate_process(process)
                        with self._window_launch_lock:
                            if self._window_process is process:
                                self._window_process = None
                        process = None
                        deadline = time.monotonic() + WINDOW_READY_TIMEOUT_SECONDS
                        continue
                    if process is not None:
                        _terminate_process(process)
                        with self._window_launch_lock:
                            if self._window_process is process:
                                self._window_process = None
                    self._report_window_launch_failure(
                        RuntimeError("The Paper Monitor window process did not become ready."),
                        path,
                    )
                    return
                self._stop_event.wait(0.25)
        finally:
            restart_process = None
            restart_path = None
            with self._window_launch_lock:
                self._window_control_monitor_active = False
                if not self._stop_event.is_set() and self._pending_window_route is not None:
                    restart_path = self._pending_window_route
                    if _process_is_running(self._window_process):
                        restart_process = self._window_process
                    elif not _is_windows_platform() or not _is_window_mutex_running():
                        restart_path = None
            if restart_path is not None:
                self._start_window_launch_monitor(restart_process, restart_path)

    def _report_window_launch_failure(self, error: BaseException, path: str) -> None:
        _log_window_launch_error(self.config_path, path, error)
        with self._window_launch_lock:
            self._pending_window_route = None
        self.status.last_result = "Last Result: Could not open window"
        self.launch_error_handler(error, path)

    def _start_refresh_thread(
        self,
        refresh_on_start: bool,
        launch_reason: RefreshReason = RefreshReason.PROCESS_LAUNCH,
    ) -> threading.Thread:
        def worker() -> None:
            next_run_at = None
            schedule_key = None
            launch_refresh_checked = False

            while not self._stop_event.is_set():
                try:
                    app_config = load_app_config(self.config_path)
                except Exception as exc:
                    _log_app_error(self.config_path, "Could not load refresh settings", exc)
                    _write_stderr(f"{APP_NAME} could not load refresh settings: {exc}")
                    if self._stop_event.wait(60):
                        return
                    continue

                interval_seconds = max(60, int(app_config.interval_seconds))
                current_key = (interval_seconds, app_config.refresh_start_time)
                now = dt.datetime.now()

                if not launch_refresh_checked:
                    launch_refresh_checked = True
                    if refresh_on_start:
                        if self._stop_event.wait(LAUNCH_REFRESH_DELAY_SECONDS):
                            return
                        self.refresh_now(reason=launch_reason)
                        now = dt.datetime.now()
                        if self._stop_event.is_set():
                            return

                if current_key != schedule_key or next_run_at is None:
                    if app_config.refresh_start_time:
                        next_run_at = next_scheduled_refresh_at(
                            now,
                            app_config.refresh_start_time,
                            interval_seconds,
                        )
                    else:
                        next_run_at = now + dt.timedelta(seconds=interval_seconds)
                    schedule_key = current_key

                if now >= next_run_at:
                    due_at = next_run_at
                    self.refresh_now(reason=RefreshReason.SCHEDULED_REFRESH)
                    now = dt.datetime.now()
                    if app_config.refresh_start_time:
                        next_run_at = due_at + dt.timedelta(seconds=interval_seconds)
                        while next_run_at <= now:
                            next_run_at += dt.timedelta(seconds=interval_seconds)
                    else:
                        next_run_at = now + dt.timedelta(seconds=interval_seconds)
                    continue

                wait_seconds = min(60.0, max(0.5, (next_run_at - now).total_seconds()))
                if self._stop_event.wait(wait_seconds):
                    return

        thread = threading.Thread(target=worker, name="PaperMonitorRefresh", daemon=True)
        with self._lifecycle_lock:
            self._scheduler_thread = thread
        thread.start()
        return thread

    def _build_icon(self):
        try:
            import pystray
        except ImportError as exc:
            raise RuntimeError("Install Windows tray dependencies from requirements-windows.txt") from exc

        image = _build_tray_image()
        icon_class = _tray_icon_class(pystray, self.open_dashboard)
        return icon_class(
            APP_DIR_NAME,
            image,
            APP_NAME,
            menu=_tray_menu(pystray, self),
        )


def _tray_menu(pystray, app: WindowsTrayApp):
    return pystray.Menu(
        pystray.MenuItem(APP_NAME, None, enabled=False),
        pystray.MenuItem(lambda _: app.status.last_run, None, enabled=False),
        pystray.MenuItem(lambda _: app.status.last_result, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Paper Monitor", lambda *_: app.open_dashboard()),
        pystray.MenuItem("Settings...", lambda *_: app.open_settings()),
        pystray.MenuItem(
            "Refresh Now",
            lambda *_: app.start_manual_refresh(),
        ),
        pystray.MenuItem("Test Notification", lambda *_: app.post_test_notification()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda *_: app.quit()),
    )


def _tray_icon_class(pystray, double_click_action: Callable[[], None]):
    if not _is_windows_platform():
        return pystray.Icon
    try:
        from pystray._util import win32
        from pystray._win32 import Icon as Win32Icon
    except Exception:
        return pystray.Icon

    class DoubleClickIcon(Win32Icon):
        def _on_notify(self, wparam, lparam):
            if lparam == getattr(win32, "WM_LBUTTONDBLCLK", WM_LBUTTONDBLCLK):
                double_click_action()
                return 0
            return super()._on_notify(wparam, lparam)

    return DoubleClickIcon


def _has_process_poll(process) -> bool:
    return callable(getattr(process, "poll", None))


def _process_is_running(process) -> bool:
    if not _has_process_poll(process):
        return False
    try:
        return process.poll() is None
    except Exception:
        return False


def _has_process_pid(process) -> bool:
    try:
        return int(getattr(process, "pid")) > 0
    except (AttributeError, TypeError, ValueError):
        return False


def _terminate_process(process) -> None:
    terminate = getattr(process, "terminate", None)
    if not callable(terminate):
        return
    try:
        terminate()
    except Exception:
        return


def tray_menu_labels() -> List[str]:
    return [
        APP_NAME,
        "Last Run: never",
        "Last Result: none",
        "Open Paper Monitor",
        "Settings...",
        "Refresh Now",
        "Test Notification",
        "Quit",
    ]


def next_scheduled_refresh_at(now: dt.datetime, start_time: str, interval_seconds: int) -> dt.datetime:
    anchor = _daily_anchor(now, start_time)
    if anchor >= now:
        return anchor
    interval = dt.timedelta(seconds=max(60, int(interval_seconds)))
    elapsed = now - anchor
    intervals_elapsed = int(elapsed.total_seconds() // interval.total_seconds()) + 1
    return anchor + (interval * intervals_elapsed)


def _daily_anchor(now: dt.datetime, start_time: str) -> dt.datetime:
    try:
        hour_text, minute_text = str(start_time).split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (TypeError, ValueError):
        hour = now.hour
        minute = now.minute
    hour = min(23, max(0, hour))
    minute = min(59, max(0, minute))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def windows_icon_path() -> Optional[Path]:
    candidates = (
        bundled_source_root() / "windows" / "assets" / "PaperMonitor.ico",
        Path(sys.executable).resolve().parent / "PaperMonitor.ico",
        Path(__file__).resolve().parents[1] / "windows" / "assets" / "PaperMonitor.ico",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="PaperMonitor")
    parser.add_argument(
        "command",
        nargs="?",
        choices=(
            "window",
            "settings",
            "tray",
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
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--no-launch-refresh", action="store_true")
    parser.add_argument(
        "--launch-reason",
        choices=tuple(reason.value for reason in RefreshReason),
    )
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
        sent = WindowsToastNotifier(icon_path=windows_icon_path()).notify_article(
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

    app = WindowsTrayApp(config_path=config_path)
    run_kwargs: Dict[str, object] = {
        "refresh_on_start": not args.no_launch_refresh,
        "quiet": args.quiet,
    }
    if args.launch_reason:
        run_kwargs["launch_reason"] = RefreshReason(args.launch_reason)
    try:
        app.run(**run_kwargs)
        return 0
    except Exception as exc:
        _log_app_error(config_path, "Paper Monitor tray process failed", exc)
        if not args.quiet:
            show_tray_message(
                f"{APP_NAME} could not start the background tray process.\n\n"
                f"{type(exc).__name__}: {exc}"
            )
        return 1


def _build_tray_image():
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Install Pillow from requirements-windows.txt") from exc

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 60, 60), fill=(21, 101, 192, 255))
    draw.line((22, 19, 43, 19, 22, 30, 42, 30, 42, 43, 21, 43), fill=(255, 255, 255, 255), width=7)
    return image


def _format_result(
    result: Dict[str, object],
    *,
    notification_attempts: int = 0,
    notification_failures: int = 0,
) -> str:
    outcome = "Partial | " if str(result.get("status") or "") == "partial" or result.get("partial") else ""
    formatted = "Last Result: {outcome}Fetched {fetched} | Matched {matched} | New {new_matches}".format(
        outcome=outcome,
        fetched=result.get("fetched", 0),
        matched=result.get("matched", 0),
        new_matches=result.get("new_matches", 0),
    )
    if notification_attempts:
        sent = max(0, int(notification_attempts) - int(notification_failures))
        formatted += f" | Notifications {sent} sent / {int(notification_failures)} failed"
    return formatted


def _invoke_refresh_function(
    refresh_function,
    config_path: Path,
    *,
    request_id: str,
    reason: str,
) -> Dict[str, object]:
    """Pass refresh metadata when supported while retaining injected-runner compatibility."""

    try:
        signature = inspect.signature(refresh_function)
    except (TypeError, ValueError):
        signature = None
    if signature is not None:
        parameters = signature.parameters
        accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
        if accepts_kwargs or {"request_id", "reason"}.issubset(parameters):
            return refresh_function(config_path, request_id=request_id, reason=reason)
    return refresh_function(config_path)


def _safe_stop_icon(icon) -> None:
    try:
        icon.stop()
    except Exception as exc:
        if LOGGER.hasHandlers():
            LOGGER.debug("Could not stop Paper Monitor tray icon: %s", exc)


def _truncate(value: str, limit: int) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


if __name__ == "__main__":
    raise SystemExit(main())
