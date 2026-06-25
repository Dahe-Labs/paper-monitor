import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Tuple

from .analysis_refresh import run_crossref_keyword_analysis
from .config import load_app_config
from .dashboard import write_dashboard
from .journal_metrics import load_journal_metrics
from .keyword_analysis import AnalysisScope
from .storage import ArticleStore


MAX_SEARCH_TERM_LENGTH = 120


class WindowsDashboardServer:
    def __init__(
        self,
        config_path: Path,
        host: str = "127.0.0.1",
        port: int = 0,
        token: Optional[str] = None,
        keyword_analysis_runner: Callable[..., Dict[str, object]] = run_crossref_keyword_analysis,
    ):
        self.config_path = Path(config_path)
        self.host = host
        self.port = port
        self.token = token or secrets.token_urlsafe(24)
        self.keyword_analysis_runner = keyword_analysis_runner
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
                if self.path not in ("/", "/index.html"):
                    self.send_error(404)
                    return
                html = outer.dashboard_html()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(length) if length else b"{}"
                if not outer.authorized(self.headers):
                    self.send_response(403)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Unauthorized"}, ensure_ascii=False).encode("utf-8"))
                    return
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = {}
                status, response = outer.handle_api_request(self.path, payload)
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))

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

    def dashboard_html(self) -> str:
        app_config = load_app_config(self.config_path)
        if not app_config.dashboard_path.exists():
            store = ArticleStore(app_config.database_path)
            latest_run = store.latest_run()
            candidates = store.candidates_for_run(int(latest_run["id"])) if latest_run else []
            write_dashboard(
                app_config.dashboard_path,
                latest_run,
                candidates,
                load_journal_metrics(app_config.journal_metrics_path),
                AnalysisScope(
                    selected_journals=tuple(app_config.monitor_config.filter_config.journals),
                    top_n=app_config.journal_scope_top_n,
                ),
            )
        html = app_config.dashboard_path.read_text(encoding="utf-8")
        return _inject_bridge_config(html, self.url.rstrip("/"), self.token)

    def handle_api_request(self, path: str, payload: Dict[str, object]) -> Tuple[int, Dict[str, object]]:
        if path == "/api/add-search-term":
            term = normalized_search_term(str(payload.get("term") or ""))
            if not term:
                return 400, {"error": "Invalid search term"}
            add_include_term(self.config_path, term)
            return 200, {"ok": True}

        if path == "/api/analyze-keywords":
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

        return 404, {"error": "Unknown API endpoint"}


def add_include_term(config_path: Path, term: str) -> None:
    config_path = Path(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    terms = payload.get("include_terms")
    if not isinstance(terms, list):
        terms = []

    seen = {" ".join(str(value).casefold().split()) for value in terms}
    key = " ".join(term.casefold().split())
    if key not in seen:
        terms.append(term)
    payload["include_terms"] = terms

    temp_path = config_path.with_name(f".{config_path.name}.windows-dashboard.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(config_path)


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
        "</script>"
    )
    if "window.paperMonitorBridgeBaseURL =" in html:
        return html
    if "<head>" in html:
        return html.replace("<head>", "<head>" + script, 1)
    return script + html


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
