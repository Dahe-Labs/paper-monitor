#!/usr/bin/env python3
"""Build the bundled interdisciplinary journal catalog from OpenAlex."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OPENALEX_API = "https://api.openalex.org/sources"
OPENALEX_SOURCE_DOCS = "https://developers.openalex.org/api-reference/sources"
METRIC_NAME = "OpenAlex 2-year mean citedness"
METRIC_LABEL = "2Y Impact"
PAGE_SIZE = 200

CATEGORY_ORDER = (
    "AI & Computer Science",
    "Engineering",
    "Medicine & Health",
    "Life Sciences",
    "Physics & Astronomy",
    "Chemistry",
    "Materials & Energy",
    "Environmental & Earth Sciences",
    "Mathematics & Statistics",
    "Social Sciences",
    "Economics & Business",
    "Multidisciplinary",
)

# Minimum representation before the remaining slots are filled by overall citation rank.
CATEGORY_MINIMUMS = {
    "AI & Computer Science": 35,
    "Engineering": 20,
    "Medicine & Health": 25,
    "Life Sciences": 25,
    "Physics & Astronomy": 20,
    "Chemistry": 20,
    "Materials & Energy": 35,
    "Environmental & Earth Sciences": 15,
    "Mathematics & Statistics": 15,
    "Social Sciences": 15,
    "Economics & Business": 15,
    "Multidisciplinary": 15,
}

MULTIDISCIPLINARY_TITLES = {
    "nature",
    "science",
    "proceedings of the national academy of sciences",
    "nature communications",
    "science advances",
    "scientific reports",
    "plos one",
    "national science review",
    "research",
    "the innovation",
    "science bulletin",
    "royal society open science",
    "pnas nexus",
    "heliyon",
    "peerj",
}

RETAINED_JOURNALS = {
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
    "Chemical Engineering Journal",
    "Journal of Energy Chemistry",
    "Electrochimica Acta",
    "ACS Applied Energy Materials",
    "ACS Materials Letters",
    "Batteries & Supercaps",
    "Electrochemical Energy Reviews",
    "EnergyChem",
    "Carbon Energy",
    "Advanced Energy and Sustainability Research",
    "Sustainable Energy & Fuels",
    "ChemSusChem",
    "Green Chemistry",
    "Journal of The Electrochemical Society",
    "Solid State Ionics",
    "Journal of Electroanalytical Chemistry",
    "Materials Today Energy",
    "Battery Energy",
    "Batteries",
    "eTransportation",
}
RETAINED_ALIAS_OVERRIDES = {
    "Advanced Materials": ["Adv Mater", "Adv. Mater."],
    "Advanced Functional Materials": ["Adv Funct Mater", "Adv. Funct. Mater."],
    "Advanced Energy Materials": ["Adv Energy Mater", "Adv. Energy Mater."],
}
JOURNAL_NAME_OVERRIDES = {
    "PLANT PHYSIOLOGY": "Plant Physiology",
    "PEDIATRICS": "Pediatrics",
    "CHEST Journal": "Chest",
    "Physical review. D/Physical review. D.": "Physical Review D",
    "Physical review. B./Physical review. B": "Physical Review B",
    "The Science of The Total Environment": "Science of the Total Environment",
    "Sensors and Actuators B Chemical": "Sensors and Actuators B: Chemical",
    "Proteins Structure Function and Bioinformatics": "Proteins: Structure, Function, and Bioinformatics",
    "Journal of Physics Condensed Matter": "Journal of Physics: Condensed Matter",
    "Astronomy and Astrophysics": "Astronomy & Astrophysics",
}
TITLE_CATEGORY_PATTERNS = (
    (
        "AI & Computer Science",
        (
            "artificial intelligence",
            "machine learning",
            "neural network",
            "pattern analysis",
            "pattern recognition",
            "computer vision",
            "data mining",
            "data science",
            "software engineering",
            "computer science",
            "computing",
            "informatics",
            "cybernetics",
            "information systems",
            "knowledge and data",
            "robotics",
        ),
    ),
    (
        "Materials & Energy",
        (
            "material",
            "battery",
            "batteries",
            "energy",
            "electrochem",
            "power sources",
            "solar",
            "fuel cell",
            "nanomaterial",
            "nanoscience",
            "nanotechnology",
            "nano letters",
            "acs nano",
        ),
    ),
    (
        "Medicine & Health",
        (
            "the lancet",
            "new england journal of medicine",
            "jama",
            "clinical medicine",
            "medical journal",
            "public health",
        ),
    ),
)

FIELD_CATEGORIES = {
    "Computer Science": "AI & Computer Science",
    "Decision Sciences": "AI & Computer Science",
    "Engineering": "Engineering",
    "Chemical Engineering": "Engineering",
    "Medicine": "Medicine & Health",
    "Nursing": "Medicine & Health",
    "Health Professions": "Medicine & Health",
    "Dentistry": "Medicine & Health",
    "Pharmacology, Toxicology and Pharmaceutics": "Medicine & Health",
    "Veterinary": "Medicine & Health",
    "Biochemistry, Genetics and Molecular Biology": "Life Sciences",
    "Agricultural and Biological Sciences": "Life Sciences",
    "Immunology and Microbiology": "Life Sciences",
    "Neuroscience": "Life Sciences",
    "Physics and Astronomy": "Physics & Astronomy",
    "Chemistry": "Chemistry",
    "Materials Science": "Materials & Energy",
    "Energy": "Materials & Energy",
    "Environmental Science": "Environmental & Earth Sciences",
    "Earth and Planetary Sciences": "Environmental & Earth Sciences",
    "Mathematics": "Mathematics & Statistics",
    "Psychology": "Social Sciences",
    "Social Sciences": "Social Sciences",
    "Arts and Humanities": "Social Sciences",
    "Economics, Econometrics and Finance": "Economics & Business",
    "Business, Management and Accounting": "Economics & Business",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("journal_metrics.json"))
    parser.add_argument("--size", type=int, default=300, help="Number of formal journals to include")
    parser.add_argument("--pool-size", type=int, default=3000, help="OpenAlex records considered before balancing")
    parser.add_argument("--snapshot-date", default=date.today().isoformat())
    parser.add_argument("--mailto", default=os.environ.get("OPENALEX_MAILTO", "paper-monitor@example.com"))
    parser.add_argument("--api-key", default=os.environ.get("OPENALEX_API_KEY", ""))
    return parser.parse_args()


def normalized_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold().replace("&", " and ")
    return "".join(character for character in text if character.isalnum())


def clean_aliases(values: list[object], journal: str) -> list[str]:
    journal_key = normalized_key(journal)
    aliases: list[str] = []
    seen = {journal_key}
    for value in values:
        alias = " ".join(str(value or "").split())
        key = normalized_key(alias)
        if not alias or not key or key in seen or len(alias) > 160:
            continue
        seen.add(key)
        aliases.append(alias)
        if len(aliases) == 8:
            break
    return aliases


def request_json(params: dict[str, object], *, retries: int = 4) -> dict[str, Any]:
    query = urlencode({key: value for key, value in params.items() if value not in (None, "")})
    request = Request(
        f"{OPENALEX_API}?{query}",
        headers={"User-Agent": "PaperMonitorCatalog/2.0 (OpenAlex catalog builder)"},
    )
    for attempt in range(retries):
        try:
            # Request is built from the fixed HTTPS OpenAlex endpoint.
            with urlopen(request, timeout=60) as response:  # nosec B310
                return json.load(response)
        except (HTTPError, URLError, TimeoutError):
            if attempt + 1 == retries:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("OpenAlex request exhausted retries")


def source_select_fields() -> str:
    return ",".join(
        (
            "id",
            "issn_l",
            "display_name",
            "host_organization_name",
            "works_count",
            "cited_by_count",
            "summary_stats",
            "homepage_url",
            "alternate_titles",
            "topics",
            "counts_by_year",
            "last_publication_year",
            "type",
            "is_core",
        )
    )


def fetch_pool(pool_size: int, mailto: str, api_key: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    cursor = "*"
    while len(records) < pool_size:
        payload = request_json(
            {
                "filter": "type:journal,is_core:true,last_publication_year:>2024",
                "sort": "cited_by_count:desc",
                "per-page": min(PAGE_SIZE, pool_size - len(records)),
                "cursor": cursor,
                "select": source_select_fields(),
                "mailto": mailto,
                "api_key": api_key,
            }
        )
        page = [record for record in payload.get("results", []) if isinstance(record, dict)]
        if not page:
            break
        records.extend(page)
        cursor = str(payload.get("meta", {}).get("next_cursor") or "")
        if not cursor:
            break
        print(f"Fetched {len(records)} OpenAlex journal records")
    return records[:pool_size]


def search_source(journal: str, mailto: str, api_key: str) -> dict[str, Any] | None:
    payload = request_json(
        {
            "filter": "type:journal,is_core:true",
            "search": journal,
            "per-page": 10,
            "select": source_select_fields(),
            "mailto": mailto,
            "api_key": api_key,
        }
    )
    wanted = normalized_key(journal)
    records = [record for record in payload.get("results", []) if isinstance(record, dict)]
    for record in records:
        if normalized_key(record.get("display_name")) == wanted:
            return record
    for record in records:
        if wanted in {normalized_key(name) for name in record.get("alternate_titles", [])}:
            return record
    return records[0] if records else None


def metric_value(record: dict[str, Any]) -> float | None:
    try:
        value = float(record.get("summary_stats", {}).get("2yr_mean_citedness"))
    except (AttributeError, TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return round(value, 1)


def recent_works(record: dict[str, Any]) -> int:
    rows = [row for row in record.get("counts_by_year", []) if isinstance(row, dict)]
    years = sorted((int(row.get("year") or 0) for row in rows), reverse=True)
    if not years:
        return 0
    cutoff = years[0] - 2
    return sum(int(row.get("works_count") or 0) for row in rows if int(row.get("year") or 0) >= cutoff)


def is_plausible_record(record: dict[str, Any]) -> bool:
    if metric_value(record) is None or not record.get("display_name"):
        return False
    try:
        total_works = max(0, int(record.get("works_count") or 0))
    except (TypeError, ValueError):
        return False
    current_works = recent_works(record)
    if current_works < 5:
        return False
    # This catches OpenAlex source-merge outliers while retaining long-running journals.
    return total_works < 10_000 or current_works / max(1, total_works) >= 0.001


def primary_field(record: dict[str, Any]) -> str:
    counts: Counter[str] = Counter()
    for topic in record.get("topics", []):
        if not isinstance(topic, dict):
            continue
        field = topic.get("field")
        name = str(field.get("display_name") or "") if isinstance(field, dict) else ""
        if name:
            counts[name] += max(1, int(topic.get("count") or 0))
    return counts.most_common(1)[0][0] if counts else ""


def category_for(record: dict[str, Any], journal: str | None = None) -> str:
    title = " ".join(str(journal or record.get("display_name") or "").casefold().split())
    if title in MULTIDISCIPLINARY_TITLES:
        return "Multidisciplinary"
    for category, patterns in TITLE_CATEGORY_PATTERNS:
        if any(pattern in title for pattern in patterns):
            return category
    return FIELD_CATEGORIES.get(primary_field(record), "Multidisciplinary")


def cited_by_count(record: dict[str, Any]) -> int:
    try:
        return max(0, int(record.get("cited_by_count") or 0))
    except (TypeError, ValueError):
        return 0


def load_seed(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("journals", []) if isinstance(payload, dict) else []
    entries = [entry for entry in entries if isinstance(entry, dict)]
    if isinstance(payload, dict) and int(payload.get("catalog_version") or 1) >= 2:
        retained_keys = {normalized_key(journal) for journal in RETAINED_JOURNALS}
        entries = [
            entry
            for entry in entries
            if entry.get("retained_from_previous_catalog")
            or normalized_key(entry.get("journal")) in retained_keys | {"arxiv"}
        ]
        by_key = {normalized_key(entry.get("journal")): entry for entry in entries}
        for journal in sorted(RETAINED_JOURNALS):
            key = normalized_key(journal)
            if key not in by_key:
                entry = {"journal": journal, "aliases": [], "retained_from_previous_catalog": True}
                entries.append(entry)
                by_key[key] = entry
        for entry in entries:
            journal_key = normalized_key(entry.get("journal"))
            entry["aliases"] = [
                alias
                for alias in entry.get("aliases", [])
                if normalized_key(alias) not in retained_keys - {journal_key}
            ]
            journal = str(entry.get("journal") or "")
            if journal in RETAINED_ALIAS_OVERRIDES:
                entry["aliases"] = list(RETAINED_ALIAS_OVERRIDES[journal])
    return entries


def record_name_map(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        key = normalized_key(record.get("display_name"))
        if key:
            result[key] = record
    for record in records:
        for name in record.get("alternate_titles", []):
            key = normalized_key(name)
            if key and key not in result:
                result[key] = record
    return result


def resolve_seed_records(
    seeds: list[dict[str, Any]],
    pool: list[dict[str, Any]],
    mailto: str,
    api_key: str,
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], dict[str, Any] | None]:
    by_name = record_name_map(pool)
    formal: list[tuple[dict[str, Any], dict[str, Any]]] = []
    preprint: dict[str, Any] | None = None
    for seed in seeds:
        journal = str(seed.get("journal") or "").strip()
        if not journal:
            continue
        if normalized_key(journal) == "arxiv":
            preprint = seed
            continue
        record = by_name.get(normalized_key(journal))
        if record is None:
            print(f"Resolving existing journal: {journal}")
            record = search_source(journal, mailto, api_key)
        if record is None or metric_value(record) is None:
            raise RuntimeError(f"Could not resolve an OpenAlex impact metric for existing journal: {journal}")
        formal.append((seed, record))
    return formal, preprint


def choose_records(
    pool: list[dict[str, Any]],
    seed_records: list[tuple[dict[str, Any], dict[str, Any]]],
    size: int,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    eligible = [record for record in pool if is_plausible_record(record)]
    eligible.sort(key=lambda record: (-cited_by_count(record), str(record.get("display_name") or "").casefold()))
    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    seed_by_record: dict[str, dict[str, Any]] = {}

    def add(record: dict[str, Any], seed: dict[str, Any] | None = None) -> bool:
        key = normalized_key(record.get("display_name"))
        if not key or key in selected_keys or len(selected) >= size:
            return False
        selected.append(record)
        selected_keys.add(key)
        if seed is not None:
            seed_by_record[key] = seed
        return True

    for seed, record in seed_records:
        add(record, seed)

    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in eligible:
        by_category[category_for(record)].append(record)

    def category_counts() -> Counter[str]:
        return Counter(category_for(record, seed_by_record.get(normalized_key(record.get("display_name")), {}).get("journal")) for record in selected)

    for category in CATEGORY_ORDER:
        minimum = CATEGORY_MINIMUMS[category]
        for record in by_category[category]:
            if category_counts()[category] >= minimum or len(selected) >= size:
                break
            add(record)

    for record in eligible:
        if len(selected) >= size:
            break
        add(record)

    if len(selected) != size:
        raise RuntimeError(f"Expected {size} formal journals, selected {len(selected)}")
    return selected, seed_by_record


def catalog_entry(
    record: dict[str, Any],
    rank: int,
    snapshot_year: int,
    seed: dict[str, Any] | None,
) -> dict[str, Any]:
    source_name = str(record.get("display_name") or "").strip()
    journal = str((seed or {}).get("journal") or JOURNAL_NAME_OVERRIDES.get(source_name, source_name)).strip()
    alias_values = list((seed or {}).get("aliases", []))
    if source_name.casefold() != journal.casefold():
        alias_values.append(source_name)
    category = category_for(record, journal)
    return {
        "rank": rank,
        "journal": journal,
        "aliases": clean_aliases(alias_values, journal),
        "category": category,
        "impact_factor": metric_value(record),
        "impact_factor_year": snapshot_year,
        "impact_metric": METRIC_NAME,
        "impact_label": METRIC_LABEL,
        "five_year_impact_factor": None,
        "level": f"{category} journal; catalog rank is based on OpenAlex total citations",
        "source_url": str(record.get("id") or OPENALEX_SOURCE_DOCS),
        "issn_l": str(record.get("issn_l") or ""),
        "publisher": str(record.get("host_organization_name") or ""),
        "cited_by_count": cited_by_count(record),
        "default_selected": True,
        "retained_from_previous_catalog": seed is not None,
    }


def preprint_entry(seed: dict[str, Any] | None, rank: int) -> dict[str, Any]:
    source = seed or {}
    return {
        "rank": rank,
        "journal": "arXiv",
        "aliases": clean_aliases(list(source.get("aliases", [])), "arXiv"),
        "category": "Preprints",
        "impact_factor": None,
        "impact_factor_year": None,
        "impact_metric": "Not applicable",
        "impact_label": "Preprint",
        "five_year_impact_factor": None,
        "level": "Preprint server; optional source, disabled by default",
        "source_url": "https://arxiv.org/",
        "issn_l": "",
        "publisher": "Cornell University",
        "cited_by_count": 0,
        "default_selected": False,
        "retained_from_previous_catalog": True,
    }


def build_catalog(args: argparse.Namespace) -> dict[str, Any]:
    seeds = load_seed(args.output)
    pool = fetch_pool(args.pool_size, args.mailto, args.api_key)
    seed_records, preprint = resolve_seed_records(seeds, pool, args.mailto, args.api_key)
    selected, seed_by_record = choose_records(pool, seed_records, args.size)
    selected.sort(key=lambda record: (-cited_by_count(record), str(record.get("display_name") or "").casefold()))
    snapshot_year = int(str(args.snapshot_date).split("-", 1)[0])
    journals = [
        catalog_entry(
            record,
            rank,
            snapshot_year,
            seed_by_record.get(normalized_key(record.get("display_name"))),
        )
        for rank, record in enumerate(selected, start=1)
    ]
    journals.append(preprint_entry(preprint, len(journals) + 1))
    counts = Counter(entry["category"] for entry in journals if entry["default_selected"])
    return {
        "catalog_version": 2,
        "generated_at": args.snapshot_date,
        "formal_journal_count": args.size,
        "selection_method": (
            "Active OpenAlex core journals ranked by total cited-by count, balanced across interdisciplinary categories; "
            "the original Paper Monitor journals are retained."
        ),
        "metric": {
            "name": METRIC_NAME,
            "label": METRIC_LABEL,
            "definition": "Mean citations to a source's works over a two-year window; this is not Clarivate JIF.",
            "source": OPENALEX_SOURCE_DOCS,
            "retrieved_at": args.snapshot_date,
        },
        "category_counts": {category: counts.get(category, 0) for category in CATEGORY_ORDER},
        "journals": journals,
    }


def main() -> int:
    args = parse_args()
    if args.size < len(CATEGORY_ORDER):
        raise SystemExit(f"--size must be at least {len(CATEGORY_ORDER)}")
    catalog = build_catalog(args)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {catalog['formal_journal_count']} journals plus arXiv to {args.output}")
    print(json.dumps(catalog["category_counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
