"""Standalone Windows dashboard window for Paper Monitor."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional, Protocol

from .windows_dashboard_server import WindowsDashboardServer
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
DEFAULT_MIN_SIZE = (900, 600)


class DashboardServer(Protocol):
    def start(self) -> str:
        ...

    def stop(self) -> None:
        ...


DashboardServerFactory = Callable[[Path], DashboardServer]


def open_dashboard_window(
    config_path: Path,
    dashboard_server_factory: DashboardServerFactory = WindowsDashboardServer,
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
        _register_window_control(config_path, server, base_url, window)
        _attach_closed_handler(window, stop_server)
        webview.start(
            private_mode=False,
            storage_path=str(_webview_storage_path(config_path)),
        )
        return 0
    finally:
        clear_window_control(config_path)
        stop_server()
        close_handle(window_mutex)


def main(
    argv: Optional[Iterable[str]] = None,
    dashboard_server_factory: DashboardServerFactory = WindowsDashboardServer,
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


def _register_window_control(config_path: Path, server, base_url: str, window) -> None:
    token = getattr(server, "token", None)
    set_controller = getattr(server, "set_window_controller", None)
    if not token or not callable(set_controller):
        return
    set_controller(_window_control_handler(window, base_url))
    write_window_control(config_path, base_url, str(token), os.getpid())


def _window_control_handler(window, base_url: str) -> Callable[[dict], dict]:
    def handle(payload: dict) -> dict:
        action = str(payload.get("action") or "")
        if action == "show":
            return _load_window_url(window, _server_url(base_url, _controlled_route(payload.get("route"))))
        if action == "reload":
            return _load_window_url(
                window,
                _cache_busted_url(_server_url(base_url, _controlled_route(payload.get("route")))),
            )
        if action == "ping":
            return {"ok": True}
        if action == "close":
            return _destroy_window(window)
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
    _defer_window_call(lambda: load_url(url))
    return {"ok": True}


def _destroy_window(window) -> dict:
    destroy = getattr(window, "destroy", None)
    if not callable(destroy):
        destroy = getattr(window, "close", None)
    if not callable(destroy):
        return {"ok": False, "error": "window_close_unavailable"}
    _defer_window_call(destroy)
    return {"ok": True}


def _defer_window_call(callback: Callable[[], None]) -> None:
    timer = threading.Timer(0.05, callback)
    timer.daemon = True
    timer.start()


def _attach_closed_handler(window, callback: Callable[[], None]) -> None:
    events = getattr(window, "events", None)
    closed = getattr(events, "closed", None)
    if closed is None:
        return
    try:
        events.closed += _safe_closed_callback(callback)
    except (AttributeError, TypeError):
        return


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


def _webview_storage_path(config_path: Path) -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "PaperMonitor" / "WebView2"
    return Path(config_path).expanduser().resolve().parent / "webview2"


def _acquire_window_mutex():
    return acquire_mutex(WINDOW_MUTEX_NAME)
