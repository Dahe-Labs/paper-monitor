import copy
import json
from importlib import resources
from typing import Dict, List, Mapping, Optional

_FALLBACK_CATALOG: Dict[str, object] = {
    "default_preset": "solid_state_battery_general",
    "presets": [
        {
            "id": "solid_state_battery_general",
            "label": "Solid-state battery general",
            "crossref_query": (
                "solid electrolyte OR electrolyte OR all-solid-state battery OR solid-state battery "
                "OR electrode OR LLZTO OR LLZO OR silicon anode OR Si anode OR NCM"
            ),
            "openalex_query": (
                "solid electrolyte OR electrolyte OR all-solid-state battery OR solid-state battery "
                "OR electrode OR LLZTO OR LLZO OR silicon anode OR Si anode OR NCM"
            ),
            "include_terms": [
                "all-solid-state battery",
                "solid-state battery",
                "solid electrolyte",
                "electrolyte",
                "electrode",
                "LLZTO",
                "LLZO",
                "silicon anode",
                "Si anode",
                "NCM",
            ],
            "exclude_terms": [
                "solid-state laser",
                "solid state laser",
                "solid-state lighting",
                "solid-state drive",
            ],
            "aliases": [],
            "is_custom": False,
        },
        {
            "id": "solid_electrolyte",
            "label": "Solid electrolyte",
            "crossref_query": (
                "solid electrolyte OR sulfide electrolyte OR oxide electrolyte OR halide electrolyte "
                "OR argyrodite OR LLZO OR LLZTO OR NASICON"
            ),
            "openalex_query": (
                "solid electrolyte OR sulfide electrolyte OR oxide electrolyte OR halide electrolyte "
                "OR argyrodite OR LLZO OR LLZTO OR NASICON"
            ),
            "include_terms": [
                "solid electrolyte",
                "sulfide electrolyte",
                "oxide electrolyte",
                "halide electrolyte",
                "argyrodite",
                "LLZO",
                "LLZTO",
                "NASICON",
            ],
            "exclude_terms": [
                "solid-state laser",
                "solid state laser",
                "solid-state lighting",
                "solid-state drive",
            ],
            "aliases": [],
            "is_custom": False,
        },
        {
            "id": "lithium_metal_anode",
            "label": "Lithium metal anode",
            "crossref_query": (
                "lithium metal anode OR Li metal anode OR dendrite OR lithium dendrite "
                "OR solid electrolyte interphase OR SEI"
            ),
            "openalex_query": (
                "lithium metal anode OR Li metal anode OR dendrite OR lithium dendrite "
                "OR solid electrolyte interphase OR SEI"
            ),
            "include_terms": [
                "lithium metal anode",
                "Li metal anode",
                "dendrite",
                "lithium dendrite",
                "solid electrolyte interphase",
                "SEI",
            ],
            "exclude_terms": [
                "solid-state laser",
                "solid state laser",
                "solid-state lighting",
                "solid-state drive",
            ],
            "aliases": [],
            "is_custom": False,
        },
        {
            "id": "interface_interphase",
            "label": "Interface / interphase",
            "crossref_query": (
                "solid electrolyte interface OR interphase OR interfacial impedance "
                "OR space charge layer OR cathode interface OR anode interface"
            ),
            "openalex_query": (
                "solid electrolyte interface OR interphase OR interfacial impedance "
                "OR space charge layer OR cathode interface OR anode interface"
            ),
            "include_terms": [
                "solid electrolyte interface",
                "interphase",
                "interfacial impedance",
                "space charge layer",
                "cathode interface",
                "anode interface",
            ],
            "exclude_terms": [
                "solid-state laser",
                "solid state laser",
                "solid-state lighting",
                "solid-state drive",
            ],
            "aliases": [
                "interface_impedance",
            ],
            "is_custom": False,
        },
        {
            "id": "custom",
            "label": "Custom",
            "crossref_query": "",
            "openalex_query": "",
            "include_terms": [],
            "exclude_terms": [],
            "aliases": [
                "cathode_materials",
            ],
            "is_custom": True,
        },
    ],
}


def _validate_catalog(payload: object) -> Dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("search direction preset catalog must be a JSON object")
    presets = payload.get("presets")
    if not isinstance(presets, list) or not presets:
        raise ValueError("search direction preset catalog must contain presets")
    return payload


def _load_catalog() -> Dict[str, object]:
    resource = resources.files("paper_monitor").joinpath("resources", "search_direction_presets.json")
    try:
        payload = json.loads(resource.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError):
        payload = copy.deepcopy(_FALLBACK_CATALOG)
    return _validate_catalog(payload)


_CATALOG = _load_catalog()


def search_direction_presets() -> List[Dict[str, object]]:
    return copy.deepcopy(_CATALOG["presets"])  # type: ignore[index]


def default_preset_id() -> str:
    return str(_CATALOG.get("default_preset") or "solid_state_battery_general")


def find_preset(preset_id: object, include_aliases: bool = True) -> Optional[Mapping[str, object]]:
    text = str(preset_id or "").strip()
    if not text:
        return None
    for preset in _CATALOG["presets"]:  # type: ignore[index]
        if not isinstance(preset, dict):
            continue
        if str(preset.get("id") or "") == text:
            return preset
        aliases = preset.get("aliases") if include_aliases else []
        if isinstance(aliases, list) and text in {str(alias) for alias in aliases}:
            return preset
    return None


def preset_ids() -> List[str]:
    return [str(preset["id"]) for preset in search_direction_presets()]


def _default_search_direction() -> Dict[str, object]:
    preset = find_preset(default_preset_id(), include_aliases=False)
    if preset is None:
        raise ValueError("default search direction preset is missing from catalog")
    return {
        "preset": str(preset["id"]),
        "label": str(preset["label"]),
        "crossref_query": str(preset["crossref_query"]),
        "openalex_query": str(preset["openalex_query"]),
        "query_manually_edited": False,
    }


DEFAULT_SEARCH_DIRECTION = _default_search_direction()
SEARCH_DIRECTION_PRESETS = search_direction_presets()
