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
            "id": "sulfide_solid_electrolyte",
            "label": "Sulfide solid electrolyte",
            "crossref_query": (
                "sulfide solid electrolyte OR sulfide electrolyte OR sulfide-based all-solid-state battery "
                "OR thiophosphate electrolyte OR lithium thiophosphate OR argyrodite OR LGPS OR Li10GeP2S12 "
                "OR LPSCl OR Li6PS5Cl OR Li7P3S11 OR Li3PS4"
            ),
            "openalex_query": (
                "sulfide solid electrolyte OR sulfide electrolyte OR sulfide-based all-solid-state battery "
                "OR thiophosphate electrolyte OR lithium thiophosphate OR argyrodite OR LGPS OR Li10GeP2S12 "
                "OR LPSCl OR Li6PS5Cl OR Li7P3S11 OR Li3PS4"
            ),
            "include_terms": [
                "sulfide solid electrolyte",
                "sulfide electrolyte",
                "sulfide-based all-solid-state battery",
                "thiophosphate electrolyte",
                "lithium thiophosphate",
                "argyrodite",
                "LGPS",
                "Li10GeP2S12",
                "LPSCl",
                "Li6PS5Cl",
                "Li7P3S11",
                "Li3PS4",
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
            "id": "halide_solid_electrolyte",
            "label": "Halide solid electrolyte",
            "crossref_query": (
                "halide solid electrolyte OR halide electrolyte OR halide-based all-solid-state battery "
                "OR chloride solid electrolyte OR lithium halide electrolyte OR Li3YCl6 OR Li3InCl6 "
                "OR Li2ZrCl6 OR Li3ScCl6 OR Li3YBr6"
            ),
            "openalex_query": (
                "halide solid electrolyte OR halide electrolyte OR halide-based all-solid-state battery "
                "OR chloride solid electrolyte OR lithium halide electrolyte OR Li3YCl6 OR Li3InCl6 "
                "OR Li2ZrCl6 OR Li3ScCl6 OR Li3YBr6"
            ),
            "include_terms": [
                "halide solid electrolyte",
                "halide electrolyte",
                "halide-based all-solid-state battery",
                "chloride solid electrolyte",
                "lithium halide electrolyte",
                "Li3YCl6",
                "Li3InCl6",
                "Li2ZrCl6",
                "Li3ScCl6",
                "Li3YBr6",
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
            "id": "latp_solid_electrolyte",
            "label": "LATP solid electrolyte",
            "crossref_query": (
                "LATP OR LATP electrolyte OR LATP solid electrolyte OR lithium aluminum titanium phosphate "
                "OR lithium aluminium titanium phosphate OR Li1+xAlxTi2-x(PO4)3 "
                "OR Li1.3Al0.3Ti1.7(PO4)3 OR NASICON LATP"
            ),
            "openalex_query": (
                "LATP OR LATP electrolyte OR LATP solid electrolyte OR lithium aluminum titanium phosphate "
                "OR lithium aluminium titanium phosphate OR Li1+xAlxTi2-x(PO4)3 "
                "OR Li1.3Al0.3Ti1.7(PO4)3 OR NASICON LATP"
            ),
            "include_terms": [
                "LATP",
                "LATP electrolyte",
                "LATP solid electrolyte",
                "lithium aluminum titanium phosphate",
                "lithium aluminium titanium phosphate",
                "Li1+xAlxTi2-x(PO4)3",
                "Li1.3Al0.3Ti1.7(PO4)3",
                "NASICON LATP",
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
            "id": "llzo_garnet_electrolyte",
            "label": "LLZO / LLZTO garnet electrolyte",
            "crossref_query": (
                "LLZO OR LLZTO OR LLZO electrolyte OR Li7La3Zr2O12 OR lithium lanthanum zirconium oxide "
                "OR lithium lanthanum zirconate OR garnet solid electrolyte OR garnet electrolyte"
            ),
            "openalex_query": (
                "LLZO OR LLZTO OR LLZO electrolyte OR Li7La3Zr2O12 OR lithium lanthanum zirconium oxide "
                "OR lithium lanthanum zirconate OR garnet solid electrolyte OR garnet electrolyte"
            ),
            "include_terms": [
                "LLZO",
                "LLZTO",
                "LLZO electrolyte",
                "Li7La3Zr2O12",
                "lithium lanthanum zirconium oxide",
                "lithium lanthanum zirconate",
                "garnet solid electrolyte",
                "garnet electrolyte",
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
            "id": "silicon_anode",
            "label": "Silicon anode",
            "crossref_query": (
                "silicon anode OR Si anode OR silicon-based anode OR silicon negative electrode "
                "OR silicon-carbon anode OR silicon carbon anode OR silicon/graphite anode "
                "OR Si/C anode OR prelithiated silicon"
            ),
            "openalex_query": (
                "silicon anode OR Si anode OR silicon-based anode OR silicon negative electrode "
                "OR silicon-carbon anode OR silicon carbon anode OR silicon/graphite anode "
                "OR Si/C anode OR prelithiated silicon"
            ),
            "include_terms": [
                "silicon anode",
                "Si anode",
                "silicon-based anode",
                "silicon negative electrode",
                "silicon-carbon anode",
                "silicon carbon anode",
                "silicon/graphite anode",
                "Si/C anode",
                "prelithiated silicon",
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
            "id": "sodium_battery",
            "label": "Sodium battery",
            "crossref_query": (
                "sodium-ion battery OR sodium ion battery OR Na-ion battery OR sodium-ion batteries "
                "OR Na-ion batteries OR sodium metal battery OR all-solid-state sodium battery "
                "OR solid-state sodium battery OR sodium solid electrolyte OR Na battery"
            ),
            "openalex_query": (
                "sodium-ion battery OR sodium ion battery OR Na-ion battery OR sodium-ion batteries "
                "OR Na-ion batteries OR sodium metal battery OR all-solid-state sodium battery "
                "OR solid-state sodium battery OR sodium solid electrolyte OR Na battery"
            ),
            "include_terms": [
                "sodium-ion battery",
                "sodium ion battery",
                "Na-ion battery",
                "sodium-ion batteries",
                "Na-ion batteries",
                "sodium metal battery",
                "all-solid-state sodium battery",
                "solid-state sodium battery",
                "sodium solid electrolyte",
                "Na battery",
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
