import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from .analysis_refresh import run_crossref_keyword_analysis
from .app_refresh import RefreshAlreadyRunning, run_app_refresh
from .config import load_app_config
from .config_store import update_config_atomic
from .dashboard_writer import write_latest_dashboard
from .windows_runtime_settings import sync_windows_runtime_settings
from .windows_settings import (
    default_settings_payload,
    render_settings_page,
    save_settings,
    settings_payload,
)

MAX_SEARCH_TERM_LENGTH = 120
_ANALYSIS_LOCK = threading.Lock()
_REFRESH_LOCK = threading.Lock()
WindowController = Callable[[Dict[str, object]], Dict[str, object]]


class WindowsDashboardServer:
    def __init__(
        self,
        config_path: Path,
        host: str = "127.0.0.1",
        port: int = 0,
        token: Optional[str] = None,
        keyword_analysis_runner: Callable[..., Dict[str, object]] = run_crossref_keyword_analysis,
        refresh_runner: Callable[[Path], Dict[str, object]] = run_app_refresh,
        window_controller: Optional[WindowController] = None,
    ):
        self.config_path = Path(config_path)
        self.host = host
        self.port = port
        self.token = token or secrets.token_urlsafe(24)
        self.keyword_analysis_runner = keyword_analysis_runner
        self.refresh_runner = refresh_runner
        self.window_controller = window_controller
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        if self._server is None:
            return f"http://{self.host}:{self.port}/"
        host, port = self._server.server_address
        return f"http://{host}:{port}/"

    def start(self) -> str:
        if self._server is not None:
            return self.url

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def do_GET(self):
                path = urlsplit(self.path).path
                if path in ("/", "/index.html"):
                    html = outer.dashboard_html()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(html.encode("utf-8"))
                    return

                if path == "/settings":
                    html = render_settings_page(outer.config_path, outer.url.rstrip("/"), outer.token)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(html.encode("utf-8"))
                    return

                if path == "/api/settings":
                    if not outer.authorized(self.headers):
                        _send_json(self, 403, {"error": "Unauthorized"})
                        return
                    try:
                        _send_json(self, 200, settings_payload(outer.config_path))
                    except Exception as exc:
                        _send_json(self, 500, {"error": "Could not load settings: %s" % exc})
                    return

                if path == "/api/settings/defaults":
                    if not outer.authorized(self.headers):
                        _send_json(self, 403, {"error": "Unauthorized"})
                        return
                    try:
                        _send_json(self, 200, default_settings_payload(outer.config_path))
                    except Exception as exc:
                        _send_json(self, 500, {"error": "Could not load default settings: %s" % exc})
                    return

                self.send_error(404)

            def do_POST(self):
                path = urlsplit(self.path).path
                length = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(length) if length else b"{}"
                if not outer.authorized(self.headers):
                    _send_json(self, 403, {"error": "Unauthorized"})
                    return
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    _send_json(self, 400, {"error": "Invalid JSON payload"})
                    return
                if not isinstance(payload, dict):
                    _send_json(self, 400, {"error": "JSON payload must be an object"})
                    return
                status, response = outer.handle_api_request(path, payload)
                _send_json(self, status, response)

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="PaperMonitorDashboardServer", daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None

    def authorized(self, headers: Mapping[str, str]) -> bool:
        return str(headers.get("X-Paper-Monitor-Token") or "") == self.token

    def set_window_controller(self, window_controller: Optional[WindowController]) -> None:
        self.window_controller = window_controller

    def dashboard_html(self) -> str:
        app_config = load_app_config(self.config_path)
        write_latest_dashboard(app_config)
        html = app_config.dashboard_path.read_text(encoding="utf-8")
        return _inject_bridge_config(html, self.url.rstrip("/"), self.token)

    def handle_api_request(self, path: str, payload: Dict[str, object]) -> Tuple[int, Dict[str, object]]:
        if path == "/api/settings":
            response = save_settings(self.config_path, payload)
            if response.get("ok"):
                try:
                    sync_windows_runtime_settings(self.config_path)
                except Exception as exc:
                    return 500, {"error": f"Settings saved, but Windows startup settings could not be applied: {exc}"}
            return (200 if response.get("ok") else 400), response

        if path == "/api/add-search-term":
            term = normalized_search_term(str(payload.get("term") or ""))
            if not term:
                return 400, {"error": "Invalid search term"}
            add_include_term(self.config_path, term)
            return 200, {"ok": True}

        if path == "/api/refresh-now":
            if not _REFRESH_LOCK.acquire(blocking=False):
                return 409, {"ok": False, "error": "refresh_already_running"}
            try:
                return 200, {"ok": True, "result": self.refresh_runner(self.config_path)}
            except RefreshAlreadyRunning:
                return 409, {"ok": False, "error": "refresh_already_running"}
            except Exception as exc:
                return 500, {"ok": False, "error": f"Refresh failed: {exc}"}
            finally:
                _REFRESH_LOCK.release()

        if path == "/api/window-control":
            if self.window_controller is None:
                return 503, {"ok": False, "error": "window_control_unavailable"}
            try:
                response = self.window_controller(payload)
            except Exception as exc:
                return 500, {"ok": False, "error": f"Window control failed: {exc}"}
            if not isinstance(response, dict):
                return 500, {"ok": False, "error": "Window control returned an invalid response"}
            return (200 if response.get("ok", True) else 400), response

        if path == "/api/analyze-keywords":
            if not _ANALYSIS_LOCK.acquire(blocking=False):
                return 409, {"ok": False, "error": "analysis_already_running"}
            try:
                return 200, self.keyword_analysis_runner(
                    self.config_path,
                    date_from=str(payload.get("date_from") or ""),
                    date_to=str(payload.get("date_to") or ""),
                    sort_mode=_sort_mode(payload.get("sort_mode")),
                    analysis_depth=_analysis_depth(payload.get("analysis_depth")),
                    top_n=_positive_int(payload.get("top_n"), 30),
                    selected_journals=_journals(payload.get("journals")),
                )
            except Exception as exc:
                return 500, {"error": f"Crossref analysis failed: {exc}"}
            finally:
                _ANALYSIS_LOCK.release()

        return 404, {"error": "Unknown API endpoint"}


def _send_json(handler: BaseHTTPRequestHandler, status: int, response: Dict[str, object]) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.end_headers()
    handler.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))


def add_include_term(config_path: Path, term: str) -> None:
    def mutate(payload: Dict[str, object]) -> Dict[str, object]:
        terms = payload.get("include_terms")
        if not isinstance(terms, list):
            terms = []

        seen = {" ".join(str(value).casefold().split()) for value in terms}
        key = " ".join(term.casefold().split())
        if key not in seen:
            terms = list(terms) + [term]
        payload["include_terms"] = terms
        return payload

    update_config_atomic(config_path, mutate)


def normalized_search_term(term: str) -> Optional[str]:
    for char in term:
        if ord(char) < 32 and char not in ("\t", "\n", "\r"):
            return None
    normalized = " ".join(term.split())
    if not normalized or len(normalized) > MAX_SEARCH_TERM_LENGTH:
        return None
    return normalized


def _inject_bridge_config(html: str, base_url: str, token: str) -> str:
    script = (
        "<script>"
        f"window.paperMonitorBridgeBaseURL = {json.dumps(base_url)};"
        f"window.paperMonitorBridgeToken = {json.dumps(token)};"
        "document.addEventListener('DOMContentLoaded', function () {"
        "var header = document.querySelector('.header-main');"
        "if (!header) return;"
        "var nav = document.getElementById('keyword-analysis-nav');"
        "var actions = header.querySelector('.header-actions');"
        "if (!actions) {"
        "actions = document.createElement('div');"
        "actions.className = 'header-actions';"
        "header.appendChild(actions);"
        "}"
        "actions.style.display = 'flex';"
        "actions.style.alignItems = 'center';"
        "actions.style.justifyContent = 'flex-end';"
        "actions.style.gap = '8px';"
        "actions.style.marginLeft = 'auto';"
        "var link = document.getElementById('paper-monitor-settings-link');"
        "if (!link) {"
        "link = document.createElement('a');"
        "link.id = 'paper-monitor-settings-link';"
        "link.textContent = 'Settings';"
        "}"
        "link.href = String(window.paperMonitorBridgeBaseURL || '').replace(/\\/+$/, '') + '/settings';"
        "link.hidden = false;"
        "link.className = 'header-action-link';"
        "link.style.display = 'inline-flex';"
        "link.style.alignItems = 'center';"
        "link.style.justifyContent = 'center';"
        "link.style.height = '36px';"
        "link.style.padding = '0 13px';"
        "link.style.borderRadius = '7px';"
        "link.style.background = '#ffffff';"
        "link.style.color = '#1f2933';"
        "link.style.border = '1px solid #d8dee4';"
        "link.style.fontWeight = '700';"
        "link.style.textDecoration = 'none';"
        "if (link.parentElement !== actions) actions.insertBefore(link, actions.firstChild);"
        "var refresh = document.getElementById('paper-monitor-refresh-button');"
        "if (!refresh) {"
        "refresh = document.createElement('button');"
        "refresh.id = 'paper-monitor-refresh-button';"
        "refresh.type = 'button';"
        "refresh.textContent = 'Refresh Now';"
        "}"
        "refresh.hidden = false;"
        "refresh.className = 'header-action-button';"
        "refresh.style.display = 'inline-flex';"
        "refresh.style.alignItems = 'center';"
        "refresh.style.justifyContent = 'center';"
        "refresh.style.height = '36px';"
        "refresh.style.padding = '0 13px';"
        "refresh.style.borderRadius = '7px';"
        "refresh.style.background = '#ffffff';"
        "refresh.style.color = '#1f2933';"
        "refresh.style.border = '1px solid #d8dee4';"
        "refresh.style.fontWeight = '700';"
        "refresh.style.cursor = 'pointer';"
        "if (refresh.parentElement !== actions) actions.insertBefore(refresh, nav || null);"
        "if (refresh.dataset.paperMonitorRefreshWired !== '1') {"
        "refresh.dataset.paperMonitorRefreshWired = '1';"
        "refresh.addEventListener('click', function () {"
        "var base = String(window.paperMonitorBridgeBaseURL || '').replace(/\\/+$/, '');"
        "if (!base || typeof fetch !== 'function') return;"
        "var original = refresh.textContent || 'Refresh Now';"
        "refresh.disabled = true;"
        "refresh.textContent = 'Refreshing...';"
        "var headers = {'Content-Type': 'application/json'};"
        "var token = String(window.paperMonitorBridgeToken || '');"
        "if (token) headers['X-Paper-Monitor-Token'] = token;"
        "fetch(base + '/api/refresh-now', {method: 'POST', headers: headers, body: '{}'}).then(function (response) {"
        "return response.json().catch(function () { return {}; }).then(function (data) {"
        "if (!response.ok || data.error) throw new Error(data.error || 'Refresh failed.');"
        "return data;"
        "});"
        "}).then(function () {"
        "window.location.href = base + '/?t=' + Date.now();"
        "}).catch(function (error) {"
        "var message = String(error && error.message || 'Refresh failed.');"
        "refresh.textContent = message === 'refresh_already_running' ? 'Already Refreshing' : 'Refresh Failed';"
        "window.setTimeout(function () { refresh.textContent = original; refresh.disabled = false; }, 1800);"
        "});"
        "});"
        "}"
        "if (nav && nav.parentElement !== actions) actions.appendChild(nav);"
        "});"
        "</script>"
    )
    if "</body>" in html:
        return html.replace("</body>", script + "</body>", 1)
    if "<head>" in html:
        return html.replace("<head>", "<head>" + script, 1)
    return html + script


def _sort_mode(value: object) -> str:
    text = normalized_search_term(str(value or "")) or "time"
    return text if text in ("time", "impact_factor", "relevance") else "time"


def _analysis_depth(value: object) -> str:
    return "exhaustive" if str(value or "").strip().lower() == "exhaustive" else "fast"


def _positive_int(value: object, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _journals(value: object):
    if not isinstance(value, list):
        return None
    return [journal for journal in (normalized_search_term(str(item or "")) for item in value) if journal]
