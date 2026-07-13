"""Standalone Windows dashboard window for Paper Monitor."""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional, Protocol

from .windows_mutex import WINDOW_MUTEX_NAME, acquire_mutex, close_handle
from .windows_window_control import (
    WindowControlError,
    clear_window_control,
    send_window_control,
    write_window_control,
)

DEFAULT_TITLE = "Paper Monitor"
DEFAULT_WIDTH = 1180
DEFAULT_HEIGHT = 760
DEFAULT_MIN_SIZE = (720, 520)
LOGGER = logging.getLogger(__name__)


class DashboardServer(Protocol):
    def start(self) -> str:
        ...

    def stop(self) -> None:
        ...


DashboardServerFactory = Callable[[Path], DashboardServer]


def _default_dashboard_server_factory(config_path: Path) -> DashboardServer:
    from .windows_dashboard_server import WindowsDashboardServer

    return WindowsDashboardServer(config_path)


def open_dashboard_window(
    config_path: Path,
    dashboard_server_factory: DashboardServerFactory = _default_dashboard_server_factory,
    title: str = DEFAULT_TITLE,
    path: str = "/",
) -> int:
    """Open the dashboard in a pywebview window and stop the server on close."""

    window_mutex = _acquire_window_mutex()
    if window_mutex is None:
        try:
            send_window_control(config_path, "show", route=path)
        except WindowControlError:
            pass
        return 0

    server: Optional[DashboardServer] = None
    stopped = False
    close_requested = threading.Event()

    def stop_server() -> None:
        nonlocal stopped
        if stopped or server is None:
            return
        stopped = True
        server.stop()

    try:
        webview = _load_webview()
        server = dashboard_server_factory(Path(config_path))
        base_url = server.start()
        if not isinstance(base_url, str) or not base_url.strip():
            raise RuntimeError("Dashboard server start() did not return a URL.")
        url = _server_url(base_url, path)

        window = webview.create_window(
            title,
            url,
            width=DEFAULT_WIDTH,
            height=DEFAULT_HEIGHT,
            min_size=DEFAULT_MIN_SIZE,
        )
        _register_window_control(
            config_path,
            server,
            base_url,
            window,
            close_requested,
        )
        _attach_closing_handler(window, close_requested)
        _attach_closed_handler(window, lambda: _close_native_window(window, stop_server))
        _attach_loaded_handler(window)
        # The local dashboard does not need persistent browser cookies or
        # storage. Private mode makes pywebview dispose the WebView2 control on
        # close instead of waiting for a later garbage-collection pass.
        webview.start(private_mode=True)
        return 0
    finally:
        clear_window_control(config_path)
        stop_server()
        close_handle(window_mutex)


def main(
    argv: Optional[Iterable[str]] = None,
    dashboard_server_factory: DashboardServerFactory = _default_dashboard_server_factory,
) -> int:
    """Parse window-launch arguments without taking over any application entry."""

    parser = argparse.ArgumentParser(prog="paper-monitor-window")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--path", default="/")
    args = parser.parse_args(list(argv) if argv is not None else None)
    return open_dashboard_window(
        args.config,
        dashboard_server_factory=dashboard_server_factory,
        title=args.title,
        path=args.path,
    )


def _load_webview():
    _prepare_pywebview_runtime()
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "pywebview is required to open the Paper Monitor dashboard window. "
            "Install the Windows dependencies or run `pip install pywebview`."
        ) from exc
    _prepare_pywebview_runtime()
    return webview


def _server_url(base_url: str, path: str) -> str:
    clean_base = str(base_url).rstrip("/")
    clean_path = str(path or "/")
    if not clean_path.startswith("/"):
        clean_path = "/" + clean_path
    return clean_base + clean_path


def _register_window_control(
    config_path: Path,
    server,
    base_url: str,
    window,
    close_requested: Optional[threading.Event] = None,
    lifecycle=None,
) -> None:
    token = getattr(server, "token", None)
    set_controller = getattr(server, "set_window_controller", None)
    if not token or not callable(set_controller):
        return
    set_controller(_window_control_handler(window, base_url, close_requested, lifecycle))
    write_window_control(config_path, base_url, str(token), os.getpid())


def _window_control_handler(
    window,
    base_url: str,
    close_requested: Optional[threading.Event] = None,
    lifecycle=None,
) -> Callable[[dict], dict]:
    def handle(payload: dict) -> dict:
        action = str(payload.get("action") or "")
        if action == "show":
            if close_requested is not None and close_requested.is_set():
                return {"ok": False, "error": "window_closing"}
            return _show_window_url(window, _server_url(base_url, _controlled_route(payload.get("route"))))
        if action == "reload":
            if close_requested is not None and close_requested.is_set():
                return {"ok": False, "error": "window_closing"}
            route = _controlled_route(payload.get("route"))
            if route == "/settings":
                return _load_window_url(window, _cache_busted_url(_server_url(base_url, route)))
            return _refresh_complete_window(window, _cache_busted_url(_server_url(base_url, "/")))
        if action == "refresh-complete":
            if close_requested is not None and close_requested.is_set():
                return {"ok": False, "error": "window_closing"}
            return _refresh_complete_window(window, _cache_busted_url(_server_url(base_url, "/")))
        if action == "ping":
            return {"ok": True}
        if action == "close":
            if close_requested is not None:
                close_requested.set()
            return _destroy_window(window, close_requested=close_requested)
        return {"ok": False, "error": "unknown_window_control_action"}

    return handle


def _controlled_route(route: object) -> str:
    candidate = str(route or "/")
    if candidate == "/settings":
        return "/settings"
    return "/"


def _cache_busted_url(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}t={int(time.time() * 1000)}"


def _load_window_url(window, url: str) -> dict:
    load_url = getattr(window, "load_url", None)
    if not callable(load_url):
        return {"ok": False, "error": "window_load_unavailable"}
    if not _defer_window_call(lambda: load_url(url)):
        return {"ok": False, "error": "window_call_unavailable"}
    return {"ok": True}


def _show_window_url(window, url: str) -> dict:
    load_url = getattr(window, "load_url", None)
    if not callable(load_url):
        return {"ok": False, "error": "window_load_unavailable"}

    def show() -> None:
        restore = getattr(window, "restore", None)
        if callable(restore):
            try:
                restore()
            except Exception as exc:
                LOGGER.debug("Could not restore Paper Monitor window: %s", exc)
        show_window = getattr(window, "show", None)
        if callable(show_window):
            try:
                show_window()
            except Exception as exc:
                LOGGER.debug("Could not show Paper Monitor window: %s", exc)
        load_url(url)

    if not _defer_window_call(show):
        return {"ok": False, "error": "window_call_unavailable"}
    return {"ok": True}


def _refresh_complete_window(window, dashboard_url: str) -> dict:
    """Reload a dashboard view while leaving an open settings form untouched."""

    evaluate_js = getattr(window, "evaluate_js", None)
    if not callable(evaluate_js):
        return {"ok": False, "error": "window_script_unavailable"}
    destination = json.dumps(str(dashboard_url))
    script = f"""
        (function () {{
          if (String(window.location.pathname || '') === '/settings') return 'settings';
          var analysis = document.getElementById('keyword-analysis');
          var state = {{
            view: analysis && !analysis.hidden ? 'analysis' : 'dashboard',
            scrollY: Number(window.scrollY || 0)
          }};
          try {{ sessionStorage.setItem('paperMonitor.refreshView.v1', JSON.stringify(state)); }} catch (_error) {{}}
          window.location.replace({destination});
          return 'reloading';
        }})()
    """
    if not _defer_window_call(lambda: evaluate_js(script)):
        return {"ok": False, "error": "window_call_unavailable"}
    return {"ok": True}


def _destroy_window(window, close_requested: Optional[threading.Event] = None) -> dict:
    destroy = getattr(window, "destroy", None)
    if not callable(destroy):
        destroy = getattr(window, "close", None)
    if not callable(destroy):
        if close_requested is not None:
            close_requested.clear()
        return {"ok": False, "error": "window_close_unavailable"}
    on_error = close_requested.clear if close_requested is not None else None
    if not _defer_window_call(destroy, on_error=on_error):
        if close_requested is not None:
            close_requested.clear()
        return {"ok": False, "error": "window_call_unavailable"}
    return {"ok": True}


def _defer_window_call(
    callback: Callable[[], None],
    on_error: Optional[Callable[[], None]] = None,
) -> bool:
    def guarded_callback() -> None:
        try:
            callback()
        except Exception as exc:
            if LOGGER.hasHandlers():
                LOGGER.debug("Deferred Paper Monitor window call failed: %s", exc)
            if on_error is not None:
                try:
                    on_error()
                except Exception:
                    pass

    timer = threading.Timer(0.05, guarded_callback)
    timer.daemon = True
    try:
        timer.start()
    except Exception as exc:
        if LOGGER.hasHandlers():
            LOGGER.debug("Could not schedule Paper Monitor window call: %s", exc)
        if on_error is not None:
            try:
                on_error()
            except Exception:
                pass
        return False
    return True


def _attach_closed_handler(window, callback: Callable[[], None]) -> None:
    events = getattr(window, "events", None)
    closed = getattr(events, "closed", None)
    if closed is None:
        return
    try:
        events.closed += _safe_closed_callback(callback)
    except (AttributeError, TypeError):
        return


def _close_native_window(window, stop_server: Callable[[], None]) -> None:
    """Release this window's WebView2 process tree, then stop its local server."""

    try:
        _release_webview2_resources(window)
    finally:
        stop_server()


def _release_webview2_resources(window) -> None:
    """Dispose a private WebView2 controller and reap only its browser tree."""

    process_ids = set(_webview2_child_process_ids())
    user_data_folder = ""
    try:
        browser = window.native.browser
        control = browser.webview
        process_id = int(control.CoreWebView2.BrowserProcessId)
        if process_id > 0:
            process_ids.add(process_id)
        user_data_folder = str(getattr(browser, "user_data_folder", "") or "")
    except Exception as exc:
        LOGGER.debug("Could not inspect Paper Monitor WebView2 control: %s", exc)
    else:
        try:
            control.Dispose()
        except Exception as exc:
            LOGGER.debug("Could not dispose Paper Monitor WebView2 control: %s", exc)

    for process_id in sorted(process_ids):
        _terminate_webview2_tree(process_id)
    _remove_private_webview_data(user_data_folder)


def _webview2_child_process_ids(parent_process_id: Optional[int] = None) -> set[int]:
    """Return root WebView2 descendants owned by this Paper Monitor process."""

    if os.name != "nt":
        return set()
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessEntry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        if snapshot in (0, wintypes.HANDLE(-1).value):
            return set()
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        processes: dict[int, tuple[int, str]] = {}
        try:
            success = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while success:
                processes[int(entry.th32ProcessID)] = (
                    int(entry.th32ParentProcessID),
                    str(entry.szExeFile).casefold(),
                )
                success = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
    except Exception as exc:
        LOGGER.debug("Could not enumerate Paper Monitor WebView2 processes: %s", exc)
        return set()

    owner = int(parent_process_id or os.getpid())
    descendants: set[int] = set()
    changed = True
    while changed:
        changed = False
        for process_id, (parent_id, _name) in processes.items():
            if process_id not in descendants and (parent_id == owner or parent_id in descendants):
                descendants.add(process_id)
                changed = True
    webview_ids = {
        process_id
        for process_id in descendants
        if processes[process_id][1] == "msedgewebview2.exe"
    }
    return {
        process_id
        for process_id in webview_ids
        if processes[process_id][0] not in webview_ids
    }


def _terminate_webview2_tree(process_id: int) -> None:
    if os.name != "nt" or process_id <= 0:
        return
    system_root = str(os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows")
    taskkill = Path(system_root) / "System32" / "taskkill.exe"
    try:
        # Fixed system executable and validated numeric PID; no shell is used.
        subprocess.run(  # nosec B603
            [str(taskkill), "/PID", str(int(process_id)), "/T", "/F"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOGGER.debug("Could not reap Paper Monitor WebView2 process tree: %s", exc)


def _remove_private_webview_data(user_data_folder: str) -> None:
    if not user_data_folder:
        return
    try:
        candidate = Path(user_data_folder).resolve(strict=False)
        temp_root = Path(tempfile.gettempdir()).resolve(strict=False)
        candidate.relative_to(temp_root)
    except (OSError, ValueError):
        return
    if candidate == temp_root:
        return
    shutil.rmtree(candidate, ignore_errors=True)


def _attach_loaded_handler(window) -> None:
    events = getattr(window, "events", None)
    loaded = getattr(events, "loaded", None)
    if loaded is None:
        return
    try:
        events.loaded += _restore_refresh_view(window)
    except (AttributeError, TypeError):
        return


def _restore_refresh_view(window) -> Callable[..., None]:
    def restore(*_args, **_kwargs) -> None:
        evaluate_js = getattr(window, "evaluate_js", None)
        if not callable(evaluate_js):
            return
        script = """
            (function () {
              var raw = '';
              try {
                raw = sessionStorage.getItem('paperMonitor.refreshView.v1') || '';
                sessionStorage.removeItem('paperMonitor.refreshView.v1');
              } catch (_error) { return; }
              if (!raw) return;
              var state;
              try { state = JSON.parse(raw); } catch (_error) { return; }
              if (state.view === 'analysis' && typeof showKeywordAnalysisView === 'function') {
                showKeywordAnalysisView();
              } else if (typeof showDashboardView === 'function') {
                showDashboardView();
              }
              var scrollY = Number(state.scrollY || 0);
              if (Number.isFinite(scrollY)) window.scrollTo(0, scrollY);
            })()
        """
        try:
            evaluate_js(script)
        except Exception as exc:
            if LOGGER.hasHandlers():
                LOGGER.debug("Could not restore Paper Monitor dashboard view: %s", exc)

    return restore


def _attach_closing_handler(
    window,
    close_requested: threading.Event,
    lifecycle=None,
) -> None:
    events = getattr(window, "events", None)
    closing = getattr(events, "closing", None)
    if closing is None:
        return
    try:
        closing += _close_window_process(close_requested, window)
    except (AttributeError, TypeError):
        return


def _close_window_process(
    close_requested: threading.Event,
    window=None,
) -> Callable[..., bool]:
    """Allow the native close and mark this short-lived UI process as closing."""

    def wrapped(*_args, **_kwargs) -> bool:
        close_requested.set()
        if window is not None:
            _release_webview2_resources(window)
        return True

    return wrapped


def _hide_instead_of_close(
    window,
    close_requested: threading.Event,
    lifecycle=None,
) -> Callable[..., bool]:
    """Compatibility alias for callers of the former hide-on-close helper."""

    del window, lifecycle
    return _close_window_process(close_requested)


def _safe_closed_callback(callback: Callable[[], None]) -> Callable[..., None]:
    def wrapped(*_args, **_kwargs) -> None:
        try:
            callback()
        except Exception:
            return

    return wrapped


def _prepare_pywebview_runtime() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    _configure_text_stream(sys.stdout)
    _configure_text_stream(sys.stderr)

    logger = logging.getLogger("pywebview")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    logger.setLevel(logging.CRITICAL)


def _configure_text_stream(stream) -> None:
    if stream is None or not hasattr(stream, "reconfigure"):
        return
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        return
def _acquire_window_mutex():
    return acquire_mutex(WINDOW_MUTEX_NAME)
