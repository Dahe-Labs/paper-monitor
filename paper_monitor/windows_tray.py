import argparse
import datetime as dt
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
from .app_refresh import RefreshAlreadyRunning, run_app_refresh
from .config import load_app_config, write_default_config
from .windows_mutex import (
    TRAY_MUTEX_NAME,
    WINDOW_MUTEX_NAME,
    acquire_mutex,
    close_handle,
    is_mutex_running,
)
from .windows_window_control import send_window_control, send_window_control_with_retry

APP_NAME = DISPLAY_NAME
APP_DIR_NAME = "PaperMonitor"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
WM_LBUTTONDBLCLK = 0x0203
LAUNCHED_BY_TRAY_ENV = "PAPER_MONITOR_LAUNCHED_BY_TRAY"
TRAY_SETTINGS_POLL_SECONDS = 0.5
WINDOW_READY_TIMEOUT_SECONDS = 15.0
LOGGER = logging.getLogger(__name__)


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


def dispatch_window_control(config_path: Path, action: str, route: Optional[str] = None) -> bool:
    send_window_control(config_path, action, route=route)
    return True


def activate_existing_app_window(
    config_path: Path,
    path: str = "/",
    ready_timeout: float = WINDOW_READY_TIMEOUT_SECONDS,
) -> bool:
    try:
        send_window_control_with_retry(
            config_path,
            "show",
            route=path,
            ready_timeout=ready_timeout,
        )
    except Exception as exc:
        if LOGGER.hasHandlers():
            LOGGER.debug("Existing window did not accept route %s: %s", path, exc)
        return False
    focus_existing_app_window()
    return True


def set_startup_enabled(enabled: bool, executable_path, registry_module=None) -> None:
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


@dataclass
class TrayStatus:
    last_run: str = "Last Run: never"
    last_result: str = "Last Result: none"
    refreshing: bool = False


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
            self._start_refresh_thread(
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
        if not self._refresh_lock.acquire(blocking=False):
            self.status.last_result = "Last Result: Refresh already running"
            return
        try:
            self.status.refreshing = True
            self.status.last_result = "Last Result: Refreshing..."
            result = self.refresh_function(self.config_path)
            app_config = load_app_config(self.config_path)
            self.status.last_run = "Last Run: " + time.strftime("%Y-%m-%d %H:%M")
            self.status.last_result = _format_result(result)
            should_notify = app_config.app_settings.notifications_enabled
            if (
                reason == RefreshReason.LOGIN_STARTUP
                and app_config.app_settings.silent_startup_notifications
            ):
                should_notify = False
            if should_notify:
                for article in result.get("articles", []):
                    if isinstance(article, dict):
                        self.notifier.notify_article(article, app_config.dashboard_path)
            self._reload_open_window()
        except RefreshAlreadyRunning:
            self.status.last_result = "Last Result: Refresh already running"
        except Exception as exc:
            self.status.last_result = "Last Result: Refresh failed"
            _log_app_error(self.config_path, "Paper Monitor refresh failed", exc)
            _write_stderr(f"{APP_NAME} refresh failed: {exc}")
        finally:
            self.status.refreshing = False
            self._refresh_lock.release()

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
        self._send_window_control("close")
        self._stop_event.set()
        if self._icon is not None:
            self._icon.stop()

    def _send_window_control(self, action: str, route: Optional[str] = None) -> bool:
        try:
            return bool(self.control_window(self.config_path, action, route))
        except Exception as exc:
            if LOGGER.hasHandlers():
                LOGGER.debug("Window control %s %s failed: %s", action, route, exc)
            return False

    def _reload_open_window(self) -> None:
        if _process_is_running(self._window_process) or (_is_windows_platform() and _is_window_mutex_running()):
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
        try:
            while time.monotonic() < deadline and not self._stop_event.is_set():
                if self._deliver_pending_window_route():
                    return
                if process is not None and not _process_is_running(process):
                    with self._window_launch_lock:
                        if self._window_process is process:
                            self._window_process = None
                    process = None
                    if not _is_windows_platform() or not _is_window_mutex_running():
                        error = RuntimeError(
                            "The Paper Monitor window process exited before becoming ready."
                        )
                        _log_window_launch_error(self.config_path, path, error)
                        with self._window_launch_lock:
                            self._pending_window_route = None
                        self.status.last_result = "Last Result: Could not open window"
                        self.launch_error_handler(error, path)
                        return
                if process is None and _is_windows_platform() and not _is_window_mutex_running():
                    error = RuntimeError("The running Paper Monitor window did not become ready.")
                    _log_window_launch_error(self.config_path, path, error)
                    with self._window_launch_lock:
                        self._pending_window_route = None
                    self.status.last_result = "Last Result: Could not open window"
                    self.launch_error_handler(error, path)
                    return
                self._stop_event.wait(0.25)

            if self._stop_event.is_set():
                return

            error = RuntimeError("The Paper Monitor window process did not become ready.")
            _log_window_launch_error(self.config_path, path, error)
            with self._window_launch_lock:
                if self._window_process is process:
                    self._window_process = None
                self._pending_window_route = None
            if process is not None:
                _terminate_process(process)
            self.status.last_result = "Last Result: Could not open window"
            self.launch_error_handler(error, path)
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
            lambda *_: threading.Thread(
                target=lambda: app.refresh_now(reason=RefreshReason.MANUAL_REFRESH),
                daemon=True,
            ).start(),
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
        choices=("window", "settings", "tray", "run", "install-startup", "uninstall-startup", "test-notification"),
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

    if args.command == "install-startup":
        set_startup_enabled(True, Path(sys.executable).resolve())
        return 0
    if args.command == "uninstall-startup":
        set_startup_enabled(False, Path(sys.executable).resolve())
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
    if args.command in ("window", "settings", "run"):
        window_path = "/settings" if args.command == "settings" else "/"
        if _is_windows_platform() and _is_window_mutex_running():
            if activate_existing_app_window(config_path, path=window_path):
                return 0
            error = RuntimeError("The running Paper Monitor window did not respond.")
            _log_window_launch_error(config_path, window_path, error)
            show_window_launch_error(error, window_path)
            return 1
        if os.environ.get(LAUNCHED_BY_TRAY_ENV) != "1":
            ensure_tray_process(
                config_path,
                refresh_on_launch=True,
                launch_reason=RefreshReason.PROCESS_LAUNCH,
            )
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


def _format_result(result: Dict[str, object]) -> str:
    return "Last Result: Fetched {fetched} | Matched {matched} | New {new_matches}".format(
        fetched=result.get("fetched", 0),
        matched=result.get("matched", 0),
        new_matches=result.get("new_matches", 0),
    )


def _truncate(value: str, limit: int) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


if __name__ == "__main__":
    raise SystemExit(main())
