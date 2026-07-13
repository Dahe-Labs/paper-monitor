import copy
import json
import shutil
from collections.abc import Mapping
from importlib import resources
from pathlib import Path
from typing import Dict, List, Optional

from .config import DEFAULT_CONFIG
from .config_store import update_config_atomic
from .journal_metrics import load_journal_metrics
from .search_presets import SEARCH_DIRECTION_PRESETS, find_preset


class SettingsError(ValueError):
    pass


INT_RANGES = {
    "interval_seconds": (60, 60 * 60 * 24 * 30),
    "max_notifications": (1, 100),
    "journal_scope.top_n": (1, 300),
    "sources.crossref.days_back": (1, 3650),
    "sources.crossref.rows": (1, 1000),
    "sources.crossref.rows_per_journal": (1, 1000),
    "sources.crossref.timeout_seconds": (1, 120),
    "sources.crossref.max_workers": (1, 16),
    "sources.openalex.days_back": (1, 3650),
    "sources.openalex.per_page": (1, 200),
    "sources.openalex.max_pages": (1, 50),
    "sources.arxiv.days_back": (1, 3650),
    "sources.arxiv.max_results": (1, 2000),
    "sources.arxiv.timeout_seconds": (1, 120),
}

LIST_LIMITS = {
    "include_terms": (500, 160),
    "exclude_terms": (500, 160),
    "journal_scope.selected_journals": (500, 200),
}

REFRESH_FREQUENCY_OPTIONS = [
    {"label": "1h", "seconds": 60 * 60},
    {"label": "6h", "seconds": 6 * 60 * 60},
    {"label": "12h", "seconds": 12 * 60 * 60},
    {"label": "1 day", "seconds": 24 * 60 * 60},
    {"label": "2 day", "seconds": 2 * 24 * 60 * 60},
    {"label": "3 day", "seconds": 3 * 24 * 60 * 60},
    {"label": "7 day", "seconds": 7 * 24 * 60 * 60},
]

def render_settings_page(config_path: Path, base_url: str, token: str) -> str:
    context = {
        "baseUrl": str(base_url).rstrip("/"),
        "token": str(token),
    }
    html = _resource_text("templates", "windows", "settings.html")
    html = html.replace("__SETTINGS_CSS__", _resource_text("static", "windows", "settings.css").rstrip())
    html = html.replace("__SETTINGS_JS__", _resource_text("static", "windows", "settings.js").rstrip())
    return html.replace("__SETTINGS_CONTEXT__", json.dumps(context, ensure_ascii=False))


def _resource_text(*parts: str) -> str:
    resource = resources.files("paper_monitor")
    for part in parts:
        resource = resource.joinpath(part)
    return resource.read_text(encoding="utf-8")


def settings_payload(config_path: Path) -> Dict[str, object]:
    return _settings_payload_from_raw(_read_config(config_path), config_path=Path(config_path))


def default_settings_payload(config_path: Optional[Path] = None) -> Dict[str, object]:
    payload_path = Path(config_path) if config_path is not None else Path("config.example.json")
    return _settings_payload_from_raw(copy.deepcopy(DEFAULT_CONFIG), config_path=payload_path)


def save_settings(config_path: Path, payload: object) -> Dict[str, object]:
    try:
        if not isinstance(payload, Mapping):
            raise SettingsError("Settings payload must be a JSON object.")

        def mutate(raw: Dict[str, object]) -> Dict[str, object]:
            merged = _merge_known_settings(_settings_payload_from_raw(raw), payload)
            settings = _validated_settings(merged)
            return _apply_settings(raw, settings)

        update_config_atomic(config_path, mutate)
        return {"ok": True}
    except SettingsError as exc:
        return {"error": str(exc)}
    except (json.JSONDecodeError, ValueError) as exc:
        return {"error": "Config file is not valid JSON: %s" % exc}
    except OSError as exc:
        return {"error": "Could not save settings: %s" % exc}


def _read_config(config_path: Path) -> Dict[str, object]:
    path = Path(config_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SettingsError("Config file not found.")
    except json.JSONDecodeError as exc:
        raise SettingsError("Config file is not valid JSON: %s" % exc)
    if not isinstance(raw, dict):
        raise SettingsError("Config file must contain a JSON object.")
    return raw


def _settings_payload_from_raw(raw: Mapping[str, object], config_path: Optional[Path] = None) -> Dict[str, object]:
    default_scope = _mapping(DEFAULT_CONFIG.get("journal_scope"), "default journal_scope")
    default_sources = _mapping(DEFAULT_CONFIG.get("sources"), "default sources")
    sources = raw.get("sources") if isinstance(raw.get("sources"), Mapping) else {}
    scope = raw.get("journal_scope") if isinstance(raw.get("journal_scope"), Mapping) else {}
    search_direction = raw.get("search_direction") if isinstance(raw.get("search_direction"), Mapping) else {}

    crossref = _source_mapping(sources, "crossref")
    openalex = _source_mapping(sources, "openalex")
    arxiv = _source_mapping(sources, "arxiv")
    default_crossref = _source_mapping(default_sources, "crossref")
    default_openalex = _source_mapping(default_sources, "openalex")
    default_arxiv = _source_mapping(default_sources, "arxiv")

    if "selected_journals" in scope:
        selected_journals = _dedupe_list(
            scope.get("selected_journals", []),
            "journal_scope.selected_journals",
        )
    else:
        selected_journals = _dedupe_list(
            raw.get("journals", default_scope.get("selected_journals", [])),
            "journal_scope.selected_journals",
        )
    arxiv_raw_enabled = arxiv.get("enabled", default_arxiv.get("enabled", False))
    arxiv_enabled = _bool_value(arxiv_raw_enabled) or _contains_normalized(selected_journals, "arxiv")
    selected_journals = _sync_arxiv_selection(selected_journals, arxiv_enabled)

    crossref_query = _clean_text(
        search_direction.get("crossref_query")
        or crossref.get("query", default_crossref.get("query", "")),
        "sources.crossref.query",
        max_length=2000,
        allow_empty=True,
    )
    openalex_query = _clean_text(
        search_direction.get("openalex_query")
        or openalex.get("query", default_openalex.get("query", "")),
        "sources.openalex.query",
        max_length=2000,
        allow_empty=True,
    )

    search_direction_payload = _search_direction_payload(search_direction, crossref_query, openalex_query)

    return {
        "interval_seconds": _int_value(
            raw.get("interval_seconds", DEFAULT_CONFIG["interval_seconds"]),
            "interval_seconds",
            fallback=int(DEFAULT_CONFIG["interval_seconds"]),
        ),
        "refresh_start_time": _time_value(
            raw.get("refresh_start_time", DEFAULT_CONFIG.get("refresh_start_time", "")),
            "refresh_start_time",
            fallback=str(DEFAULT_CONFIG.get("refresh_start_time", "")),
        ),
        "refresh_frequency_options": copy.deepcopy(REFRESH_FREQUENCY_OPTIONS),
        "max_notifications": _int_value(
            raw.get("max_notifications", DEFAULT_CONFIG["max_notifications"]),
            "max_notifications",
            fallback=int(DEFAULT_CONFIG["max_notifications"]),
        ),
        "app_settings": _app_settings_payload(raw.get("app_settings")),
        "search_direction": search_direction_payload,
        "include_terms": _dedupe_list(raw.get("include_terms", DEFAULT_CONFIG["include_terms"]), "include_terms"),
        "exclude_terms": _dedupe_list(raw.get("exclude_terms", DEFAULT_CONFIG["exclude_terms"]), "exclude_terms"),
        "journal_scope": {
            "top_n": _int_value(
                scope.get("top_n", default_scope.get("top_n", 15)),
                "journal_scope.top_n",
                fallback=int(default_scope.get("top_n", 15)),
            ),
            "selected_journals": selected_journals,
        },
        "journal_catalog": _journal_catalog_payload(raw, config_path),
        "sources": {
            "crossref": {
                "enabled": _bool_value(crossref.get("enabled", default_crossref.get("enabled", True))),
                "days_back": _int_value(crossref.get("days_back", default_crossref.get("days_back", 15)), "sources.crossref.days_back"),
                "rows": _int_value(crossref.get("rows", default_crossref.get("rows", 100)), "sources.crossref.rows"),
                "rows_per_journal": _int_value(
                    crossref.get("rows_per_journal", default_crossref.get("rows_per_journal", 25)),
                    "sources.crossref.rows_per_journal",
                ),
                "timeout_seconds": _int_value(
                    crossref.get("timeout_seconds", default_crossref.get("timeout_seconds", 20)),
                    "sources.crossref.timeout_seconds",
                ),
                "max_workers": _int_value(
                    crossref.get("max_workers", default_crossref.get("max_workers", 3)),
                    "sources.crossref.max_workers",
                ),
                "mailto": _clean_text(crossref.get("mailto", default_crossref.get("mailto", "")), "sources.crossref.mailto", 254, True),
                "query": crossref_query,
            },
            "openalex": {
                "enabled": _bool_value(openalex.get("enabled", default_openalex.get("enabled", False))),
                "days_back": _int_value(openalex.get("days_back", default_openalex.get("days_back", 15)), "sources.openalex.days_back"),
                "per_page": _int_value(openalex.get("per_page", default_openalex.get("per_page", 100)), "sources.openalex.per_page"),
                "max_pages": _int_value(openalex.get("max_pages", default_openalex.get("max_pages", 3)), "sources.openalex.max_pages"),
                "query": openalex_query,
                "api_key": _clean_text(openalex.get("api_key", default_openalex.get("api_key", "")), "sources.openalex.api_key", 500, True),
            },
            "arxiv": {
                "enabled": arxiv_enabled,
                "days_back": _int_value(arxiv.get("days_back", default_arxiv.get("days_back", 15)), "sources.arxiv.days_back"),
                "max_results": _int_value(arxiv.get("max_results", default_arxiv.get("max_results", 100)), "sources.arxiv.max_results"),
                "search_field": _search_field_value(arxiv.get("search_field", default_arxiv.get("search_field", "title"))),
                "timeout_seconds": _int_value(
                    arxiv.get("timeout_seconds", default_arxiv.get("timeout_seconds", 20)),
                    "sources.arxiv.timeout_seconds",
                ),
                "query": _clean_text(arxiv.get("query", default_arxiv.get("query", "")), "sources.arxiv.query", 2000, True),
            },
        },
    }


def _journal_catalog_payload(raw: Mapping[str, object], config_path: Optional[Path]) -> List[Dict[str, object]]:
    metrics_path = _journal_metrics_path(raw, config_path)
    try:
        metrics = load_journal_metrics(metrics_path).metrics
    except (OSError, json.JSONDecodeError, ValueError):
        metrics = []

    entries = [
        {
            "journal": metric.journal,
            "aliases": list(metric.aliases),
            "rank": metric.rank,
            "impact_factor": metric.impact_factor,
            "impact_factor_year": metric.impact_factor_year,
            "impact_metric": metric.impact_metric,
            "impact_label": metric.impact_label,
            "category": metric.category,
            "level": metric.level,
            "source_url": metric.source_url,
            "default_selected": metric.default_selected,
        }
        for metric in metrics
    ]
    entries.sort(key=_journal_catalog_sort_key)
    return entries


def _journal_metrics_path(raw: Mapping[str, object], config_path: Optional[Path]) -> Path:
    value = Path(str(raw.get("journal_metrics_path") or DEFAULT_CONFIG["journal_metrics_path"]))
    if value.is_absolute():
        return value
    if config_path is not None:
        return Path(config_path).resolve().parent / value
    return value


def _journal_catalog_sort_key(entry: Mapping[str, object]):
    impact = entry.get("impact_factor")
    try:
        impact_value = float(impact) if impact is not None else None
    except (TypeError, ValueError):
        impact_value = None
    rank = entry.get("rank")
    try:
        rank_value = int(rank) if rank is not None else 9999
    except (TypeError, ValueError):
        rank_value = 9999
    return (impact_value is None, -(impact_value or 0.0), rank_value, str(entry.get("journal") or "").casefold())


def _validated_settings(payload: Mapping[str, object]) -> Dict[str, object]:
    journal_scope = _mapping(payload.get("journal_scope"), "journal_scope")
    sources = _mapping(payload.get("sources"), "sources")
    crossref = _mapping(sources.get("crossref"), "sources.crossref")
    openalex = _mapping(sources.get("openalex"), "sources.openalex")
    arxiv = _mapping(sources.get("arxiv"), "sources.arxiv")
    search_direction = _mapping(payload.get("search_direction"), "search_direction")
    crossref_enabled = _required_bool(crossref.get("enabled"), "sources.crossref.enabled")
    openalex_enabled = _required_bool(openalex.get("enabled"), "sources.openalex.enabled")
    arxiv_enabled = _required_bool(arxiv.get("enabled"), "sources.arxiv.enabled")

    result = {
        "interval_seconds": _bounded_int(payload.get("interval_seconds"), "interval_seconds"),
        "refresh_start_time": _time_value(payload.get("refresh_start_time", ""), "refresh_start_time"),
        "max_notifications": _bounded_int(payload.get("max_notifications"), "max_notifications"),
        "app_settings": _validated_app_settings(payload.get("app_settings")),
        "include_terms": _dedupe_list(payload.get("include_terms", []), "include_terms"),
        "exclude_terms": _dedupe_list(payload.get("exclude_terms", []), "exclude_terms"),
        "journal_scope": {
            "top_n": _bounded_int(journal_scope.get("top_n"), "journal_scope.top_n"),
            "selected_journals": _dedupe_list(
                journal_scope.get("selected_journals", []),
                "journal_scope.selected_journals",
            ),
        },
        "sources": {
            "crossref": {
                "enabled": crossref_enabled,
                "days_back": _bounded_int(crossref.get("days_back"), "sources.crossref.days_back"),
                "rows": _bounded_int(crossref.get("rows"), "sources.crossref.rows"),
                "rows_per_journal": _bounded_int(crossref.get("rows_per_journal"), "sources.crossref.rows_per_journal"),
                "timeout_seconds": _bounded_int(crossref.get("timeout_seconds"), "sources.crossref.timeout_seconds"),
                "max_workers": _bounded_int(crossref.get("max_workers"), "sources.crossref.max_workers"),
                "mailto": _clean_text(crossref.get("mailto", ""), "sources.crossref.mailto", 254, True),
                "query": _clean_text(crossref.get("query", ""), "sources.crossref.query", 2000, not crossref_enabled),
            },
            "openalex": {
                "enabled": openalex_enabled,
                "days_back": _bounded_int(openalex.get("days_back"), "sources.openalex.days_back"),
                "per_page": _bounded_int(openalex.get("per_page"), "sources.openalex.per_page"),
                "max_pages": _bounded_int(openalex.get("max_pages"), "sources.openalex.max_pages"),
                "query": _clean_text(openalex.get("query", ""), "sources.openalex.query", 2000, not openalex_enabled),
                "api_key": _clean_text(openalex.get("api_key", ""), "sources.openalex.api_key", 500, not openalex_enabled),
            },
            "arxiv": {
                "enabled": arxiv_enabled,
                "days_back": _bounded_int(arxiv.get("days_back"), "sources.arxiv.days_back"),
                "max_results": _bounded_int(arxiv.get("max_results"), "sources.arxiv.max_results"),
                "search_field": _search_field(arxiv.get("search_field", "title")),
                "timeout_seconds": _bounded_int(arxiv.get("timeout_seconds"), "sources.arxiv.timeout_seconds"),
                "query": _clean_text(arxiv.get("query", ""), "sources.arxiv.query", 2000, not arxiv_enabled),
            },
        },
    }
    result["search_direction"] = _validated_search_direction(
        search_direction,
        result["sources"]["crossref"]["query"],
        result["sources"]["openalex"]["query"],
        openalex_enabled,
    )
    result["sources"]["crossref"]["query"] = result["search_direction"]["crossref_query"]
    result["sources"]["openalex"]["query"] = result["search_direction"]["openalex_query"]
    result["journal_scope"]["selected_journals"] = _sync_arxiv_selection(
        result["journal_scope"]["selected_journals"],
        result["sources"]["arxiv"]["enabled"],
    )
    return result


def _apply_settings(raw: Mapping[str, object], settings: Mapping[str, object]) -> Dict[str, object]:
    updated = copy.deepcopy(dict(raw))
    try:
        current_schema_version = int(updated.get("settings_schema_version", 1) or 1)
    except (TypeError, ValueError):
        current_schema_version = 1
    updated["settings_schema_version"] = max(current_schema_version, 2)
    updated["interval_seconds"] = settings["interval_seconds"]
    updated["refresh_start_time"] = settings["refresh_start_time"]
    updated["max_notifications"] = settings["max_notifications"]
    app_settings = updated.get("app_settings") if isinstance(updated.get("app_settings"), dict) else {}
    app_settings.update(settings["app_settings"])
    updated["app_settings"] = app_settings
    updated["include_terms"] = settings["include_terms"]
    updated["exclude_terms"] = settings["exclude_terms"]

    journal_scope = updated.get("journal_scope") if isinstance(updated.get("journal_scope"), dict) else {}
    journal_scope["top_n"] = settings["journal_scope"]["top_n"]
    journal_scope["selected_journals"] = settings["journal_scope"]["selected_journals"]
    updated["journal_scope"] = journal_scope
    selected_journals = settings["journal_scope"]["selected_journals"]
    updated["journals"] = selected_journals

    sources = updated.get("sources") if isinstance(updated.get("sources"), dict) else {}
    updated["sources"] = sources
    for source_name in ("crossref", "openalex", "arxiv"):
        source_settings = settings["sources"][source_name]
        source_config = sources.get(source_name) if isinstance(sources.get(source_name), dict) else {}
        source_config.update(source_settings)
        sources[source_name] = source_config
    sources["crossref"]["journal_titles"] = _formal_journal_titles(selected_journals)

    updated["search_direction"] = dict(settings["search_direction"])

    return updated


def _search_direction_payload(
    direction: Mapping[str, object],
    crossref_query: str,
    openalex_query: str,
) -> Dict[str, object]:
    preset_id = _clean_text(
        direction.get("preset", DEFAULT_CONFIG["search_direction"]["preset"]),
        "search_direction.preset",
        max_length=80,
        allow_empty=True,
    )
    preset = _search_preset(preset_id)
    matched = _matching_search_preset(crossref_query, openalex_query)
    manually_edited = _bool_value(direction.get("query_manually_edited", False))

    if matched is not None:
        active = matched
        manually_edited = False
    elif preset is not None and preset["id"] != "custom" and not manually_edited:
        active = preset
    else:
        active = _search_preset("custom")
        manually_edited = True

    label = _clean_text(
        direction.get("label", active["label"]),
        "search_direction.label",
        max_length=120,
        allow_empty=True,
    )
    if active["id"] != "custom":
        label = active["label"]
        crossref_query = active["crossref_query"]
        openalex_query = active["openalex_query"]
    if not label:
        label = active["label"]

    return {
        "preset": active["id"],
        "label": label,
        "crossref_query": crossref_query,
        "openalex_query": openalex_query,
        "query_manually_edited": manually_edited,
        "presets": copy.deepcopy(SEARCH_DIRECTION_PRESETS),
    }


def _validated_search_direction(
    value: Mapping[str, object],
    fallback_crossref_query: str,
    fallback_openalex_query: str,
    openalex_query_required: bool = True,
) -> Dict[str, object]:
    preset_id = _clean_text(
        value.get("preset", "custom"),
        "search_direction.preset",
        max_length=80,
        allow_empty=False,
    )
    preset = _search_preset(preset_id)
    if preset is None:
        raise SettingsError("search_direction.preset must be a known search direction.")

    if preset["id"] != "custom":
        return {
            "preset": preset["id"],
            "label": preset["label"],
            "crossref_query": preset["crossref_query"],
            "openalex_query": preset["openalex_query"],
            "query_manually_edited": False,
        }

    label = _clean_text(
        value.get("label", "Custom"),
        "search_direction.label",
        max_length=120,
        allow_empty=False,
    )
    crossref_query = _clean_text(
        value.get("crossref_query", fallback_crossref_query),
        "search_direction.crossref_query",
        max_length=2000,
        allow_empty=False,
    )
    openalex_query = _clean_text(
        value.get("openalex_query", fallback_openalex_query),
        "search_direction.openalex_query",
        max_length=2000,
        allow_empty=not openalex_query_required,
    )
    return {
        "preset": "custom",
        "label": label,
        "crossref_query": crossref_query,
        "openalex_query": openalex_query,
        "query_manually_edited": True,
    }


def _app_settings_payload(value: object) -> Dict[str, bool]:
    defaults = DEFAULT_CONFIG["app_settings"]
    mapping = value if isinstance(value, Mapping) else {}
    return {
        "startup_enabled": _bool_value(mapping.get("startup_enabled", defaults["startup_enabled"])),
        "show_tray_icon": _bool_value(mapping.get("show_tray_icon", defaults["show_tray_icon"])),
        "notifications_enabled": _bool_value(mapping.get("notifications_enabled", defaults["notifications_enabled"])),
    }


def _validated_app_settings(value: object) -> Dict[str, bool]:
    mapping = _mapping(value, "app_settings")
    return {
        "startup_enabled": _required_bool(mapping.get("startup_enabled"), "app_settings.startup_enabled"),
        "show_tray_icon": _required_bool(mapping.get("show_tray_icon"), "app_settings.show_tray_icon"),
        "notifications_enabled": _required_bool(mapping.get("notifications_enabled"), "app_settings.notifications_enabled"),
    }


def _matching_search_preset(crossref_query: str, openalex_query: str):
    for preset in SEARCH_DIRECTION_PRESETS:
        if preset["id"] == "custom":
            continue
        if _same_query(crossref_query, preset["crossref_query"]) and _same_query(
            openalex_query,
            preset["openalex_query"],
        ):
            return preset
    return None


def _search_preset(preset_id: object):
    text = str(preset_id or "").strip()
    return find_preset(text)


def _same_query(left: object, right: object) -> bool:
    return " ".join(str(left or "").split()) == " ".join(str(right or "").split())


def _time_value(value: object, name: str, fallback: object = None) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return "" if fallback is None else str(fallback or "").strip()
    parts = text.split(":")
    if len(parts) == 2:
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            hour = -1
            minute = -1
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    if fallback is not None:
        return str(fallback or "").strip()
    raise SettingsError("%s must be empty or in HH:MM format." % name)


def _write_config_with_backup(config_path: Path, payload: Mapping[str, object]) -> None:
    path = Path(config_path)
    backup_path = path.with_name(path.name + ".bak")
    temp_path = path.with_name(".%s.windows-settings.tmp" % path.name)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    temp_path.write_text(text, encoding="utf-8")
    shutil.copy2(str(path), str(backup_path))
    temp_path.replace(path)


def _merge_known_settings(base: Mapping[str, object], incoming: Mapping[str, object]) -> Dict[str, object]:
    merged = copy.deepcopy(dict(base))
    _merge_into(merged, incoming)
    return merged


def _merge_into(base: Dict[str, object], incoming: Mapping[str, object]) -> None:
    for key, value in incoming.items():
        if key not in base:
            continue
        if isinstance(base[key], dict) and isinstance(value, Mapping):
            _merge_into(base[key], value)
        else:
            base[key] = value


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SettingsError("%s must be a JSON object." % name)
    return value


def _source_mapping(sources: Mapping[str, object], source_name: str) -> Mapping[str, object]:
    value = sources.get(source_name)
    return value if isinstance(value, Mapping) else {}


def _bounded_int(value: object, name: str) -> int:
    minimum, maximum = INT_RANGES[name]
    parsed = _parse_int(value, name)
    if parsed < minimum or parsed > maximum:
        raise SettingsError("%s must be between %d and %d." % (name, minimum, maximum))
    return parsed


def _int_value(value: object, name: str, fallback: int = 1) -> int:
    try:
        return _bounded_int(value, name)
    except SettingsError:
        minimum, maximum = INT_RANGES[name]
        return min(max(int(fallback), minimum), maximum)


def _parse_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise SettingsError("%s must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    raise SettingsError("%s must be an integer." % name)


def _required_bool(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise SettingsError("%s must be true or false." % name)


def _bool_value(value: object, fallback: bool = False) -> bool:
    try:
        return _required_bool(value, "boolean setting")
    except SettingsError:
        return fallback


def _dedupe_list(value: object, name: str) -> List[str]:
    max_items, max_length = LIST_LIMITS[name]
    if isinstance(value, str):
        values = value.splitlines()
    elif isinstance(value, list) or isinstance(value, tuple):
        values = list(value)
    else:
        raise SettingsError("%s must be a list or multiline string." % name)

    result = []
    seen = set()
    for item in values:
        text = _clean_text(item, name, max_length=max_length, allow_empty=True)
        if not text:
            continue
        key = _normalized_key(text)
        if key in seen:
            continue
        seen.add(key)
        result.append(text)

    if len(result) > max_items:
        raise SettingsError("%s must contain no more than %d items." % (name, max_items))
    return result


def _clean_text(value: object, name: str, max_length: int, allow_empty: bool) -> str:
    text = "" if value is None else str(value)
    text = text.strip()
    if not text and not allow_empty:
        raise SettingsError("%s cannot be empty." % name)
    if len(text) > max_length:
        raise SettingsError("%s must be %d characters or fewer." % (name, max_length))
    if any(ord(char) < 32 and char not in ("\t", "\n", "\r") for char in text):
        raise SettingsError("%s contains unsupported control characters." % name)
    return text


def _search_field(value: object) -> str:
    text = _clean_text(value, "sources.arxiv.search_field", 32, False).strip().lower()
    if text in ("ti", "title"):
        return "title"
    if text in ("all", "any"):
        return "all"
    raise SettingsError("sources.arxiv.search_field must be title or all.")


def _search_field_value(value: object) -> str:
    try:
        return _search_field(value)
    except SettingsError:
        return "title"


def _sync_arxiv_selection(selected_journals: List[str], enabled: bool) -> List[str]:
    without_arxiv = [journal for journal in selected_journals if _normalized_key(journal) != "arxiv"]
    if enabled:
        without_arxiv.append("arxiv")
    return without_arxiv


def _formal_journal_titles(selected_journals: List[str]) -> List[str]:
    return [journal for journal in selected_journals if _normalized_key(journal) != "arxiv"]


def _contains_normalized(values: List[str], needle: str) -> bool:
    normalized = _normalized_key(needle)
    return any(_normalized_key(value) == normalized for value in values)


def _normalized_key(value: object) -> str:
    return " ".join(str(value or "").casefold().split())
