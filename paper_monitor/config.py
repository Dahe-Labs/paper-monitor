import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from .filtering import FilterConfig
from .journal_metrics import load_journal_metrics
from .search_presets import DEFAULT_SEARCH_DIRECTION

SOURCE_ONLY_JOURNAL_KEYS = {"arxiv"}


DEFAULT_CONFIG = {
    "database_path": "work/paper-monitor/articles.sqlite3",
    "dashboard_path": "work/paper-monitor/dashboard/latest.html",
    "journal_metrics_path": "journal_metrics.json",
    "settings_schema_version": 2,
    "interval_seconds": 43200,
    "refresh_start_time": "",
    "max_notifications": 5,
    "app_settings": {
        "startup_enabled": False,
        "show_tray_icon": True,
        "notifications_enabled": True,
        "silent_startup_notifications": True,
        "refresh_on_launch": True,
    },
    "include_terms": [
        "all-solid-state battery",
        "all-solid-state batteries",
        "solid-state battery",
        "solid-state batteries",
        "solid electrolyte",
        "solid electrolytes",
        "electrolyte",
        "sulfide electrolyte",
        "oxide electrolyte",
        "halide electrolyte",
        "garnet electrolyte",
        "electrode",
        "argyrodite",
        "LLZTO",
        "LLZO",
        "NASICON",
        "silicon anode",
        "Si anode",
        "NCM",
        "lithium metal anode",
        "interfacial impedance",
        "dendrite",
    ],
    "exclude_terms": [
        "solid-state laser",
        "solid state laser",
        "solid-state lighting",
        "solid-state drive",
    ],
    "journals": [
        "Nature",
        "Science",
        "Nature Energy",
        "Nature Materials",
        "Nature Nanotechnology",
        "Nature Chemistry",
        "Nature Communications",
        "Science Advances",
        "Advanced Materials",
        "Advanced Functional Materials",
        "Advanced Energy Materials",
        "Advanced Science",
        "Energy & Environmental Science",
        "ACS Energy Letters",
        "Joule",
        "Matter",
        "Energy Storage Materials",
        "Nano Energy",
        "Chem",
        "Angewandte Chemie International Edition",
        "Journal of the American Chemical Society",
        "ACS Nano",
        "Nano Letters",
        "Chemistry of Materials",
        "Journal of Materials Chemistry A",
        "Materials Horizons",
        "Energy & Environmental Materials",
        "Small",
        "ACS Applied Materials & Interfaces",
        "Journal of Power Sources",
    ],
    "journal_scope": {
        "top_n": 15,
        "selected_journals": [
            "Nature",
            "Science",
            "Nature Energy",
            "Nature Materials",
            "Nature Nanotechnology",
            "Nature Chemistry",
            "Nature Communications",
            "Science Advances",
            "Advanced Materials",
            "Advanced Functional Materials",
            "Advanced Energy Materials",
            "Advanced Science",
            "Energy & Environmental Science",
            "ACS Energy Letters",
            "Joule",
        ],
    },
    "search_direction": copy.deepcopy(DEFAULT_SEARCH_DIRECTION),
    "sources": {
        "rss": [
            {
                "name": "Nature Energy",
                "url": "https://feeds.nature.com/nenergy/rss/current",
            },
            {
                "name": "Nature Materials",
                "url": "https://feeds.nature.com/nmat/rss/current",
            },
            {
                "name": "Advanced Energy Materials",
                "url": "https://advanced.onlinelibrary.wiley.com/action/showFeed?jc=16146840&type=etoc&feed=rss",
            },
            {
                "name": "Advanced Materials",
                "url": "https://advanced.onlinelibrary.wiley.com/action/showFeed?jc=15214095&type=etoc&feed=rss",
            },
        ],
        "crossref": {
            "enabled": True,
            "days_back": 15,
            "rows": 100,
            "rows_per_journal": 25,
            "timeout_seconds": 20,
            "max_workers": 3,
            "retry_count": 2,
            "min_request_interval_seconds": None,
            "journal_titles": [],
            "query": DEFAULT_SEARCH_DIRECTION["crossref_query"],
            "mailto": "",
        },
        "openalex": {
            "enabled": False,
            "days_back": 15,
            "per_page": 100,
            "max_pages": 3,
            "query": DEFAULT_SEARCH_DIRECTION["openalex_query"],
            "api_key": "",
        },
        "arxiv": {
            "enabled": False,
            "days_back": 15,
            "max_results": 100,
            "query": "solid electrolyte OR all-solid-state battery OR solid-state battery OR electrode OR LLZO OR LLZTO",
            "search_field": "title",
            "timeout_seconds": 20,
        },
    },
}


@dataclass(frozen=True)
class RuntimeAppSettings:
    startup_enabled: bool
    show_tray_icon: bool
    notifications_enabled: bool
    silent_startup_notifications: bool
    refresh_on_launch: bool


@dataclass(frozen=True)
class MonitorConfig:
    """Matching and notification limits loaded from the shared config file."""

    filter_config: FilterConfig
    max_notifications: int


@dataclass(frozen=True)
class AppConfig:
    database_path: Path
    dashboard_path: Path
    journal_metrics_path: Path
    interval_seconds: int
    refresh_start_time: str
    monitor_config: MonitorConfig
    source_config: Dict[str, object]
    journal_scope_top_n: int
    app_settings: RuntimeAppSettings


def write_default_config(path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_app_config(path: Path) -> AppConfig:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    database_path = _resolve_path(path.parent, str(raw.get("database_path") or DEFAULT_CONFIG["database_path"]))
    dashboard_path = _resolve_path(path.parent, str(raw.get("dashboard_path") or DEFAULT_CONFIG["dashboard_path"]))
    journal_metrics_path = _resolve_path(
        path.parent,
        str(raw.get("journal_metrics_path") or DEFAULT_CONFIG["journal_metrics_path"]),
    )
    selected_journals = _selected_journals(raw)
    monitor_config = MonitorConfig(
        filter_config=FilterConfig(
            include_terms=_dedupe_nonempty(raw.get("include_terms", DEFAULT_CONFIG["include_terms"])),
            exclude_terms=_dedupe_nonempty(raw.get("exclude_terms", DEFAULT_CONFIG["exclude_terms"])),
            journals=selected_journals,
            journal_aliases=_journal_aliases(journal_metrics_path, selected_journals),
        ),
        max_notifications=int(raw.get("max_notifications", DEFAULT_CONFIG["max_notifications"])),
    )
    journals = monitor_config.filter_config.journals
    source_config = copy.deepcopy(raw.get("sources", DEFAULT_CONFIG["sources"]))
    crossref_query, openalex_query = _search_direction_queries(raw)
    crossref_config = source_config.get("crossref")
    if isinstance(crossref_config, dict):
        journal_titles = crossref_config.get("journal_titles") or journals
        crossref_config["journal_titles"] = _formal_journals(journal_titles)
        if crossref_query:
            crossref_config["query"] = crossref_query
    openalex_config = source_config.get("openalex")
    if isinstance(openalex_config, dict) and openalex_query:
        openalex_config["query"] = openalex_query
    arxiv_config = source_config.setdefault("arxiv", copy.deepcopy(DEFAULT_CONFIG["sources"]["arxiv"]))
    if isinstance(arxiv_config, dict):
        arxiv_config["enabled"] = _contains_source_candidate(journals, "arxiv")

    return AppConfig(
        database_path=database_path,
        dashboard_path=dashboard_path,
        journal_metrics_path=journal_metrics_path,
        interval_seconds=int(raw.get("interval_seconds", DEFAULT_CONFIG["interval_seconds"])),
        refresh_start_time=_refresh_start_time(raw),
        monitor_config=monitor_config,
        source_config=source_config,
        journal_scope_top_n=_journal_scope_top_n(raw, len(journals)),
        app_settings=_app_settings(raw),
    )


def _dedupe_nonempty(values):
    result = []
    seen = set()
    for value in values or []:
        text = str(value).strip()
        key = " ".join(text.casefold().split())
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _selected_journals(raw):
    scope = raw.get("journal_scope")
    if isinstance(scope, dict) and "selected_journals" in scope:
        return _dedupe_nonempty(scope.get("selected_journals", []))
    return _dedupe_nonempty(raw.get("journals", DEFAULT_CONFIG["journals"]))


def _formal_journals(values):
    return [
        journal
        for journal in _dedupe_nonempty(values)
        if _normalize_key(journal) not in SOURCE_ONLY_JOURNAL_KEYS
    ]


def _contains_source_candidate(values, source_key: str) -> bool:
    normalized = _normalize_key(source_key)
    return any(_normalize_key(value) == normalized for value in values)


def _journal_aliases(path: Path, journals) -> Dict[str, list]:
    try:
        metrics = load_journal_metrics(path)
    except Exception:
        return {}
    aliases = {}
    for journal in journals:
        names = metrics.names_for(journal)
        values = [name for name in names if _normalize_key(name) != _normalize_key(journal)]
        if values:
            aliases[journal] = values
    return aliases


def _normalize_key(value) -> str:
    return " ".join(str(value or "").casefold().split())


def _journal_scope_top_n(raw, fallback: int) -> int:
    scope = raw.get("journal_scope")
    value = scope.get("top_n") if isinstance(scope, dict) else fallback
    try:
        top_n = int(value)
    except (TypeError, ValueError):
        top_n = fallback
    return min(300, max(1, top_n))


def _search_direction_queries(raw):
    direction = raw.get("search_direction")
    if not isinstance(direction, dict):
        return None, None
    crossref_query = str(direction.get("crossref_query") or "").strip()
    openalex_query = str(direction.get("openalex_query") or "").strip()
    return crossref_query or None, openalex_query or None


def _refresh_start_time(raw) -> str:
    value = str(raw.get("refresh_start_time") or "").strip()
    if not value:
        return ""
    parts = value.split(":")
    if len(parts) != 2:
        return ""
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return ""
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def _app_settings(raw) -> RuntimeAppSettings:
    defaults = DEFAULT_CONFIG["app_settings"]
    values = raw.get("app_settings") if isinstance(raw.get("app_settings"), dict) else {}
    return RuntimeAppSettings(
        startup_enabled=_bool_value(values.get("startup_enabled"), bool(defaults["startup_enabled"])),
        show_tray_icon=_bool_value(values.get("show_tray_icon"), bool(defaults["show_tray_icon"])),
        notifications_enabled=_bool_value(values.get("notifications_enabled"), bool(defaults["notifications_enabled"])),
        silent_startup_notifications=_bool_value(
            values.get("silent_startup_notifications"),
            bool(defaults["silent_startup_notifications"]),
        ),
        refresh_on_launch=_bool_value(values.get("refresh_on_launch"), bool(defaults["refresh_on_launch"])),
    )


def _bool_value(value, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1", "on"}:
            return True
        if normalized in {"false", "no", "0", "off"}:
            return False
    return fallback


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return base_dir / path
