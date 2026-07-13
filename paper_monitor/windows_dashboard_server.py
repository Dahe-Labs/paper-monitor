import ipaddress
import json
import secrets
import socket
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from .article_lifecycle import ArticleLifecycle, DashboardSnapshot, UnknownPresentationToken
from .refresh_errors import RefreshAlreadyRunning
from .refresh_execution import RefreshExecution, RefreshIntent, RefreshOutcome
from .windows_mutex import REFRESH_MUTEX_NAME, is_mutex_running

MAX_SEARCH_TERM_LENGTH = 120
MAX_REQUEST_BODY_BYTES = 1024 * 1024
MAX_ANALYSIS_JOURNALS = 100
MAX_EXHAUSTIVE_ANALYSIS_JOURNALS = 50
MAX_ANALYSIS_DATE_SPAN_DAYS = 366
MAX_EXHAUSTIVE_ANALYSIS_DATE_SPAN_DAYS = 93
MAX_ANALYSIS_TOP_N = 100
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'none'; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "img-src 'self' data: https:; "
    "object-src 'none'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'"
)
_ANALYSIS_LOCK = threading.Lock()
WindowController = Callable[[Dict[str, object]], Dict[str, object]]
LifecycleFactory = Callable[[Path], ArticleLifecycle]
RefreshRunner = Callable[[Path], RefreshOutcome]


def _default_keyword_analysis_runner(*args, **kwargs) -> Dict[str, object]:
    from .analysis_refresh import run_crossref_keyword_analysis

    return run_crossref_keyword_analysis(*args, **kwargs)


def _default_refresh_runner(config_path: Path) -> RefreshOutcome:
    return RefreshExecution(config_path).execute(RefreshIntent.VISIBLE)


class WindowsDashboardServer:
    def __init__(
        self,
        config_path: Path,
        host: str = "127.0.0.1",
        port: int = 0,
        token: Optional[str] = None,
        keyword_analysis_runner: Callable[..., Dict[str, object]] = _default_keyword_analysis_runner,
        refresh_runner: RefreshRunner = _default_refresh_runner,
        lifecycle_factory: LifecycleFactory = ArticleLifecycle,
        window_controller: Optional[WindowController] = None,
    ):
        self.config_path = Path(config_path)
        self.host = host
        self.port = port
        self.token = token or secrets.token_urlsafe(24)
        self.keyword_analysis_runner = keyword_analysis_runner
        self.refresh_runner = refresh_runner
        self.lifecycle_factory = lifecycle_factory
        self.window_controller = window_controller
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._refresh_state_lock = threading.Lock()
        self._refresh_thread: Optional[threading.Thread] = None
        self._pending_snapshot: Optional[DashboardSnapshot] = None
        self._last_refresh: Optional[RefreshOutcome] = None
        self._refresh_state: Dict[str, object] = {
            "ok": True,
            "status": "idle",
            "request_id": "",
            "error": "",
            "result": None,
            "owner": "",
        }

    @property
    def url(self) -> str:
        if self._server is None:
            return f"http://{_url_host(self.host)}:{self.port}/"
        host, port = self._server.server_address[:2]
        return f"http://{_url_host(str(host))}:{port}/"

    def start(self) -> str:
        if self._server is not None:
            return self.url
        if not _is_loopback_host(self.host):
            raise ValueError("Windows dashboard server must bind to a loopback host")

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def do_GET(self):
                if not outer.valid_host_header(self.headers):
                    _send_json(self, 400, {"error": "Invalid Host header"})
                    return
                path = urlsplit(self.path).path
                if path in ("/", "/index.html"):
                    html = outer.dashboard_html()
                    _send_html(self, 200, html)
                    return

                if path == "/settings":
                    from .windows_settings import render_settings_page

                    html = render_settings_page(outer.config_path, outer.url.rstrip("/"), outer.token)
                    _send_html(self, 200, html)
                    return

                if path == "/api/settings":
                    from .windows_settings import settings_payload

                    if not outer.authorized(self.headers):
                        _send_json(self, 403, {"error": "Unauthorized"})
                        return
                    try:
                        _send_json(self, 200, settings_payload(outer.config_path))
                    except Exception as exc:
                        _send_json(self, 500, {"error": "Could not load settings: %s" % exc})
                    return

                if path == "/api/settings/defaults":
                    from .windows_settings import default_settings_payload

                    if not outer.authorized(self.headers):
                        _send_json(self, 403, {"error": "Unauthorized"})
                        return
                    try:
                        _send_json(self, 200, default_settings_payload(outer.config_path))
                    except Exception as exc:
                        _send_json(self, 500, {"error": "Could not load default settings: %s" % exc})
                    return

                if path == "/api/refresh-status":
                    if not outer.authorized(self.headers):
                        _send_json(self, 403, {"error": "Unauthorized"})
                        return
                    _send_json(self, 200, outer.refresh_status())
                    return

                _send_json(self, 404, {"error": "Not found"})

            def do_POST(self):
                if not outer.valid_host_header(self.headers):
                    _send_json(self, 400, {"error": "Invalid Host header"})
                    return
                path = urlsplit(self.path).path
                if not outer.authorized(self.headers):
                    _send_json(self, 403, {"error": "Unauthorized"})
                    return
                length, length_error = _request_content_length(self.headers)
                if length_error:
                    _send_json(self, length_error[0], {"error": length_error[1]})
                    return
                try:
                    raw = self.rfile.read(length) if length else b"{}"
                except OSError:
                    _send_json(self, 400, {"error": "Could not read request body"})
                    return
                if len(raw) != length:
                    _send_json(self, 400, {"error": "Incomplete request body"})
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

    def valid_host_header(self, headers: Mapping[str, str]) -> bool:
        if self._server is None:
            return False
        values = _header_values(headers, "Host")
        if len(values) != 1:
            return False
        host, port = self._server.server_address[:2]
        expected = f"{_url_host(str(host))}:{port}"
        return values[0].strip().casefold() == expected.casefold()

    def set_window_controller(self, window_controller: Optional[WindowController]) -> None:
        self.window_controller = window_controller

    def dashboard_html(self) -> str:
        from .config import load_app_config
        from .lifecycle_dashboard import render_lifecycle_dashboard

        app_config = load_app_config(self.config_path)
        with self._refresh_state_lock:
            snapshot = self._pending_snapshot
            self._pending_snapshot = None
            last_refresh = self._last_refresh
        if snapshot is None:
            snapshot = self.lifecycle_factory(app_config.database_path).dashboard_snapshot()
        html = render_lifecycle_dashboard(app_config, snapshot, last_refresh)
        return _inject_bridge_config(
            html,
            self.url.rstrip("/"),
            self.token,
            snapshot.presentation_token,
        )

    def handle_api_request(self, path: str, payload: Dict[str, object]) -> Tuple[int, Dict[str, object]]:
        if path == "/api/settings":
            from .config_store import update_config_atomic
            from .windows_native_tray import reconcile_native_tray
            from .windows_runtime_settings import sync_windows_runtime_settings
            from .windows_settings import save_settings

            try:
                original_payload = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
                if not isinstance(original_payload, dict):
                    raise ValueError("Config file must contain a JSON object.")
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return 500, {"error": f"Could not load settings before saving: {exc}"}
            response = save_settings(self.config_path, payload)
            if response.get("ok"):
                try:
                    sync_windows_runtime_settings(self.config_path)
                except Exception as exc:
                    rollback_error = None
                    try:
                        update_config_atomic(self.config_path, lambda _current: original_payload)
                        sync_windows_runtime_settings(self.config_path)
                    except Exception as rollback_exc:
                        rollback_error = rollback_exc
                    if rollback_error is not None:
                        return 500, {
                            "error": (
                                "Settings were saved but Windows background monitoring failed, "
                                f"and rollback also failed: {rollback_error}"
                            )
                        }
                    return 500, {
                        "error": (
                            "Windows background monitoring could not be applied; "
                            f"settings were rolled back: {exc}"
                        )
                    }
                reconcile_native_tray(self.config_path)
            return (200 if response.get("ok") else 400), response

        if path == "/api/add-search-term":
            term = normalized_search_term(str(payload.get("term") or ""))
            if not term:
                return 400, {"error": "Invalid search term"}
            add_include_term(self.config_path, term)
            return 200, {"ok": True}

        if path == "/api/refresh-now":
            return self.start_refresh()

        if path == "/api/confirm-presentation":
            token = str(payload.get("presentation_token") or "").strip()
            if not token:
                return 400, {"ok": False, "error": "presentation_token is required"}
            from .config import load_app_config

            try:
                app_config = load_app_config(self.config_path)
                confirmed = self.lifecycle_factory(app_config.database_path).confirm_presentation(token)
            except UnknownPresentationToken:
                return 409, {"ok": False, "error": "presentation_token is unknown or expired"}
            except Exception as exc:
                return 500, {"ok": False, "error": f"Could not confirm presentation: {exc}"}
            return 200, {"ok": True, "confirmed": confirmed}

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
            options, validation_error = _analysis_request_options(payload)
            if validation_error:
                return 400, {"ok": False, "error": validation_error}
            if not _ANALYSIS_LOCK.acquire(blocking=False):
                return 409, {"ok": False, "error": "analysis_already_running"}
            try:
                return 200, self.keyword_analysis_runner(self.config_path, **options)
            except Exception as exc:
                return 500, {"error": f"Crossref analysis failed: {exc}"}
            finally:
                _ANALYSIS_LOCK.release()

        return 404, {"error": "Unknown API endpoint"}

    def start_refresh(self) -> Tuple[int, Dict[str, object]]:
        with self._refresh_state_lock:
            if self._window_refresh_running_locked():
                return 202, self._public_refresh_state_locked()

        if is_mutex_running(REFRESH_MUTEX_NAME):
            with self._refresh_state_lock:
                if self._window_refresh_running_locked():
                    return 202, self._public_refresh_state_locked()
                self._set_external_refresh_locked()
                return 202, self._public_refresh_state_locked()

        request_id = "window-" + secrets.token_urlsafe(8)
        with self._refresh_state_lock:
            self._refresh_state = {
                "ok": True,
                "status": "running",
                "request_id": request_id,
                "error": "",
                "result": None,
                "owner": "window",
            }
            try:
                thread = threading.Thread(
                    target=lambda: self._run_refresh_task(request_id),
                    name="PaperMonitorDashboardRefresh",
                    daemon=True,
                )
                self._refresh_thread = thread
                thread.start()
            except Exception as exc:
                self._refresh_thread = None
                self._refresh_state = {
                    "ok": False,
                    "status": "failed",
                    "request_id": request_id,
                    "error": f"Refresh failed to start: {exc}",
                    "result": None,
                    "owner": "",
                }
                return 500, self._public_refresh_state_locked()
            return 202, self._public_refresh_state_locked()

    def refresh_status(self) -> Dict[str, object]:
        with self._refresh_state_lock:
            refresh_thread_alive = self._refresh_thread is not None and self._refresh_thread.is_alive()
            own_refresh_running = (
                self._refresh_state.get("status") == "running"
                and self._refresh_state.get("owner") == "window"
                and refresh_thread_alive
            )
            if own_refresh_running:
                return self._public_refresh_state_locked()
            if self._refresh_state.get("owner") != "external" and self._refresh_state.get("status") in (
                "succeeded",
                "failed",
                "partial",
                "completed",
            ):
                return self._public_refresh_state_locked()

        external_running = is_mutex_running(REFRESH_MUTEX_NAME)
        with self._refresh_state_lock:
            if external_running and self._refresh_state.get("owner") != "window":
                self._set_external_refresh_locked()
                return self._public_refresh_state_locked()
            if self._refresh_state.get("owner") == "external":
                self._refresh_state.update(
                    ok=True,
                    status="completed",
                    owner="",
                    error="",
                    result=None,
                )
            return self._public_refresh_state_locked()

    def _run_refresh_task(self, request_id: str) -> None:
        try:
            result = self.refresh_runner(self.config_path)
        except RefreshAlreadyRunning:
            with self._refresh_state_lock:
                if self._refresh_state.get("request_id") == request_id:
                    self._set_external_refresh_locked()
        except Exception as exc:
            with self._refresh_state_lock:
                if self._refresh_state.get("request_id") == request_id:
                    self._refresh_state.update(
                        ok=False,
                        status="failed",
                        error=f"Refresh failed: {exc}",
                        result=None,
                        owner="",
                    )
        else:
            with self._refresh_state_lock:
                if self._refresh_state.get("request_id") == request_id:
                    status = result.status.value
                    self._refresh_state.update(
                        ok=status != "failed",
                        status=status,
                        error=result.error,
                        result=_refresh_outcome_payload(result),
                        owner="",
                    )
                    self._last_refresh = result
                    self._pending_snapshot = result.snapshot

    def _set_external_refresh_locked(self) -> None:
        request_id = str(self._refresh_state.get("request_id") or "")
        if self._refresh_state.get("owner") != "external" or not request_id:
            request_id = "external-" + secrets.token_urlsafe(8)
        self._refresh_state = {
            "ok": True,
            "status": "running",
            "request_id": request_id,
            "error": "",
            "result": None,
            "owner": "external",
        }

    def _window_refresh_running_locked(self) -> bool:
        return (
            self._refresh_state.get("status") == "running"
            and self._refresh_state.get("owner") == "window"
            and self._refresh_thread is not None
            and self._refresh_thread.is_alive()
        )

    def _public_refresh_state_locked(self) -> Dict[str, object]:
        return {
            "ok": bool(self._refresh_state.get("ok", True)),
            "status": str(self._refresh_state.get("status") or "idle"),
            "request_id": str(self._refresh_state.get("request_id") or ""),
            "error": str(self._refresh_state.get("error") or ""),
            "result": self._refresh_state.get("result"),
        }


def _send_json(handler: BaseHTTPRequestHandler, status: int, response: Dict[str, object]) -> None:
    body = json.dumps(response, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    _send_security_headers(handler)
    handler.end_headers()
    handler.wfile.write(body)


def _send_html(handler: BaseHTTPRequestHandler, status: int, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    _send_security_headers(handler)
    handler.end_headers()
    handler.wfile.write(body)


def _send_security_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("Cache-Control", "no-store, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    handler.send_header("Cross-Origin-Resource-Policy", "same-origin")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")


def _request_content_length(headers: Mapping[str, str]) -> Tuple[int, Optional[Tuple[int, str]]]:
    if _header_values(headers, "Transfer-Encoding"):
        return 0, (400, "Transfer-Encoding is not supported")
    values = _header_values(headers, "Content-Length")
    if not values:
        return 0, (411, "Content-Length header is required")
    if len(values) != 1:
        return 0, (400, "Exactly one Content-Length header is required")
    value = values[0].strip()
    try:
        length = int(value)
    except (TypeError, ValueError):
        return 0, (400, "Invalid Content-Length header")
    if length < 0:
        return 0, (400, "Content-Length must not be negative")
    if not value.isascii() or not value.isdigit():
        return 0, (400, "Invalid Content-Length header")
    if length > MAX_REQUEST_BODY_BYTES:
        return 0, (413, f"Request body exceeds the {MAX_REQUEST_BODY_BYTES}-byte limit")
    return length, None


def _header_values(headers: Mapping[str, str], name: str) -> List[str]:
    get_all = getattr(headers, "get_all", None)
    if callable(get_all):
        values = get_all(name)
        return [str(value) for value in (values or [])]
    value = headers.get(name)
    return [] if value is None else [str(value)]


def _is_loopback_host(host: str) -> bool:
    clean_host = str(host or "").strip().strip("[]")
    if not clean_host:
        return False
    try:
        return ipaddress.ip_address(clean_host.split("%", 1)[0]).is_loopback
    except ValueError:
        pass
    try:
        addresses = socket.getaddrinfo(clean_host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    resolved = []
    for address in addresses:
        try:
            resolved.append(ipaddress.ip_address(str(address[4][0]).split("%", 1)[0]))
        except ValueError:
            return False
    return bool(resolved) and all(address.is_loopback for address in resolved)


def _url_host(host: str) -> str:
    clean_host = str(host or "").strip().strip("[]")
    return f"[{clean_host}]" if ":" in clean_host else clean_host


def _refresh_outcome_payload(outcome: RefreshOutcome) -> Dict[str, object]:
    return {
        "run_id": outcome.run_id,
        "status": outcome.status.value,
        "fetched": outcome.fetched,
        "matched": outcome.matched,
        "new_matches": outcome.new_matches,
        "skipped": outcome.skipped,
    }


def add_include_term(config_path: Path, term: str) -> None:
    from .config_store import update_config_atomic

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


def _inject_bridge_config(
    html: str,
    base_url: str,
    token: str,
    presentation_token: str,
) -> str:
    script = (
        "<script>"
        f"window.paperMonitorBridgeBaseURL = {json.dumps(base_url)};"
        f"window.paperMonitorBridgeToken = {json.dumps(token)};"
        f"window.paperMonitorPresentationToken = {json.dumps(presentation_token)};"
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
        "if (nav && nav.parentElement !== actions) actions.appendChild(nav);"
        "var confirmPresentation = function (attempt) {"
        "var presentationToken = String(window.paperMonitorPresentationToken || '');"
        "var base = String(window.paperMonitorBridgeBaseURL || '').replace(/\\/+$/, '');"
        "if (!presentationToken || !base || typeof fetch !== 'function') return;"
        "fetch(base + '/api/confirm-presentation', {"
        "method: 'POST',"
        "headers: {'Content-Type': 'application/json', 'X-Paper-Monitor-Token': String(window.paperMonitorBridgeToken || '')},"
        "body: JSON.stringify({presentation_token: presentationToken})"
        "}).then(function (response) {"
        "if (!response.ok) throw new Error('presentation confirmation failed');"
        "window.paperMonitorPresentationToken = '';"
        "}).catch(function () {"
        "var nextAttempt = Number(attempt || 0) + 1;"
        "if (nextAttempt <= 3) window.setTimeout(function () { confirmPresentation(nextAttempt); }, nextAttempt * 500);"
        "});"
        "};"
        "var afterPaint = function () {"
        "if (typeof window.requestAnimationFrame === 'function') {"
        "window.requestAnimationFrame(function () { window.requestAnimationFrame(function () { confirmPresentation(0); }); });"
        "} else { window.setTimeout(function () { confirmPresentation(0); }, 0); }"
        "};"
        "afterPaint();"
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


def _analysis_request_options(payload: Dict[str, object]) -> Tuple[Dict[str, object], Optional[str]]:
    date_from_text, date_from_value = _analysis_date(payload.get("date_from"))
    if date_from_value is None:
        return {}, "date_from must be a valid date in YYYY-MM-DD format"
    date_to_text, date_to_value = _analysis_date(payload.get("date_to"))
    if date_to_value is None:
        return {}, "date_to must be a valid date in YYYY-MM-DD format"
    if date_from_value > date_to_value:
        return {}, "date_from must be on or before date_to"

    analysis_depth = _analysis_depth(payload.get("analysis_depth"))
    max_span = (
        MAX_EXHAUSTIVE_ANALYSIS_DATE_SPAN_DAYS
        if analysis_depth == "exhaustive"
        else MAX_ANALYSIS_DATE_SPAN_DAYS
    )
    span_days = (date_to_value - date_from_value).days + 1
    if span_days > max_span:
        return {}, f"Date range for {analysis_depth} analysis must not exceed {max_span} days"

    top_n, top_n_error = _analysis_top_n(payload.get("top_n", 30))
    if top_n_error:
        return {}, top_n_error

    journals, journals_error = _analysis_journals(payload.get("journals"), analysis_depth)
    if journals_error:
        return {}, journals_error

    return {
        "date_from": date_from_text,
        "date_to": date_to_text,
        "sort_mode": _sort_mode(payload.get("sort_mode")),
        "analysis_depth": analysis_depth,
        "top_n": top_n,
        "selected_journals": journals,
    }, None


def _analysis_date(value: object) -> Tuple[str, Optional[date]]:
    text = str(value or "").strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return text, None
    if parsed.isoformat() != text:
        return text, None
    return text, parsed


def _analysis_top_n(value: object) -> Tuple[int, Optional[str]]:
    if isinstance(value, bool):
        return 0, f"top_n must be an integer between 1 and {MAX_ANALYSIS_TOP_N}"
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0, f"top_n must be an integer between 1 and {MAX_ANALYSIS_TOP_N}"
    if isinstance(value, float) and not value.is_integer():
        return 0, f"top_n must be an integer between 1 and {MAX_ANALYSIS_TOP_N}"
    if parsed < 1 or parsed > MAX_ANALYSIS_TOP_N:
        return 0, f"top_n must be between 1 and {MAX_ANALYSIS_TOP_N}"
    return parsed, None


def _analysis_journals(value: object, analysis_depth: str) -> Tuple[List[str], Optional[str]]:
    if not isinstance(value, list):
        return [], "journals must be a list"
    max_journals = MAX_EXHAUSTIVE_ANALYSIS_JOURNALS if analysis_depth == "exhaustive" else MAX_ANALYSIS_JOURNALS
    if len(value) > max_journals:
        return [], f"{analysis_depth.capitalize()} analysis supports at most {max_journals} journals"

    journals = []
    seen = set()
    for index, item in enumerate(value):
        if not isinstance(item, str):
            return [], f"journals[{index}] must be a string"
        journal = normalized_search_term(item)
        if not journal:
            return [], f"journals[{index}] must be a non-empty name up to {MAX_SEARCH_TERM_LENGTH} characters"
        key = journal.casefold()
        if key in seen:
            continue
        seen.add(key)
        journals.append(journal)
    return journals, None
