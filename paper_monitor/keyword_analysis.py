import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .date_utils import first_iso_date, parse_iso_date
from .journal_metrics import JournalMetrics


@dataclass(frozen=True)
class TaxonomyCategory:
    name: str
    aliases: Tuple[str, ...]


@dataclass(frozen=True)
class AnalysisScope:
    date_from: str = ""
    date_to: str = ""
    selected_journals: Tuple[str, ...] = ()
    selected_terms: Tuple[str, ...] = ()
    sort_mode: str = "time"
    top_n: int = 30
    selected_paper_ids: Tuple[str, ...] = ()


DEFAULT_TAXONOMY: Tuple[TaxonomyCategory, ...] = (
    TaxonomyCategory(
        "all-solid-state battery",
        (
            "all solid state battery",
            "all solid state batteries",
            "solid-state battery",
            "solid-state batteries",
            "solid state battery",
            "solid state batteries",
            "ASSB",
            "SSB",
        ),
    ),
    TaxonomyCategory(
        "solid electrolyte",
        (
            "solid electrolytes",
            "solid-state electrolyte",
            "solid-state electrolytes",
            "solid state electrolyte",
            "solid state electrolytes",
            "SSE",
        ),
    ),
    TaxonomyCategory(
        "liquid electrolyte",
        (
            "liquid electrolytes",
            "organic liquid electrolyte",
            "carbonate electrolyte",
            "ether electrolyte",
        ),
    ),
    TaxonomyCategory("electrode", ("electrodes", "composite electrode", "composite electrodes")),
    TaxonomyCategory("cathode", ("cathodes", "positive electrode", "positive electrodes")),
    TaxonomyCategory("anode", ("anodes", "negative electrode", "negative electrodes")),
    TaxonomyCategory("lithium metal", ("lithium-metal", "li metal", "lithium metal anode")),
    TaxonomyCategory("interface", ("interfaces", "interfacial", "interfacial layer")),
    TaxonomyCategory(
        "interphase",
        (
            "interphases",
            "solid electrolyte interphase",
            "SEI",
            "cathode electrolyte interphase",
            "CEI",
        ),
    ),
    TaxonomyCategory(
        "ionic conductivity",
        (
            "ion conductivity",
            "lithium ion conductivity",
            "lithium-ion conductivity",
            "li ion conductivity",
            "li-ion conductivity",
        ),
    ),
    TaxonomyCategory("oxide", ("oxides", "oxide electrolyte", "oxide solid electrolyte")),
    TaxonomyCategory("sulfide", ("sulfides", "sulphide", "sulphides", "sulfide electrolyte")),
    TaxonomyCategory("halide", ("halides", "halide electrolyte", "halide solid electrolyte")),
    TaxonomyCategory("polymer", ("polymers", "polymer electrolyte", "gel polymer electrolyte")),
    TaxonomyCategory("garnet", ("garnets", "garnet electrolyte", "LLZO", "Li7La3Zr2O12")),
    TaxonomyCategory("NASICON", ("nasicon electrolyte", "LATP", "LAGP")),
    TaxonomyCategory("argyrodite", ("argyrodites", "argyrodite electrolyte", "Li6PS5Cl")),
    TaxonomyCategory("perovskite", ("perovskites", "perovskite electrolyte", "LLTO")),
    TaxonomyCategory(
        "dry processing",
        ("dry coating", "dry electrode processing", "solvent free processing", "solvent-free processing"),
    ),
    TaxonomyCategory("stack pressure", ("external pressure", "applied pressure", "cell pressure")),
    TaxonomyCategory("thermal stability", ("thermal runaway", "heat resistance", "thermally stable")),
    TaxonomyCategory(
        "mechanical stability",
        ("mechanical properties", "mechanical strength", "fracture toughness", "chemo-mechanical stability"),
    ),
)


DEFAULT_BLOCKLIST: Set[str] = {
    "a",
    "about",
    "after",
    "against",
    "all",
    "also",
    "an",
    "and",
    "are",
    "as",
    "at",
    "battery",
    "batteries",
    "be",
    "been",
    "between",
    "by",
    "can",
    "cell",
    "cells",
    "during",
    "for",
    "from",
    "has",
    "have",
    "high",
    "how",
    "in",
    "into",
    "is",
    "it",
    "low",
    "material",
    "materials",
    "new",
    "of",
    "on",
    "or",
    "paper",
    "performance",
    "review",
    "study",
    "that",
    "the",
    "their",
    "these",
    "this",
    "through",
    "to",
    "toward",
    "towards",
    "using",
    "via",
    "was",
    "were",
    "why",
    "with",
    "article",
}


_WORD_RE = re.compile(r"[a-z0-9]+")
MAX_CANDIDATE_TERMS = 40
DEFAULT_CANDIDATE_PHRASE_LENGTHS = (2, 3)
_ALLOWED_CANDIDATE_PHRASE_LENGTHS = (1, 2, 3, 4)
_DOMAIN_ANCHOR_TERMS: Set[str] = {
    "anode",
    "argyrodite",
    "cathode",
    "cei",
    "ceramic",
    "coating",
    "composite",
    "conductivity",
    "current",
    "degradation",
    "dendrite",
    "dendrites",
    "density",
    "deposition",
    "diffusion",
    "electrochemical",
    "electrode",
    "electrodes",
    "electrolyte",
    "electrolytes",
    "garnet",
    "halide",
    "impedance",
    "interfacial",
    "interface",
    "interfaces",
    "interphase",
    "interphases",
    "ion",
    "ionic",
    "lagp",
    "latp",
    "li",
    "liquid",
    "lithium",
    "llto",
    "llzo",
    "mechanical",
    "nasicon",
    "oxide",
    "oxides",
    "perovskite",
    "polymer",
    "pressure",
    "resistance",
    "sei",
    "separator",
    "solid",
    "stability",
    "sulfide",
    "sulfides",
    "sulphide",
    "thermal",
    "transport",
}
_LOW_VALUE_CANDIDATE_TOKENS = DEFAULT_BLOCKLIST | {
    "approach",
    "based",
    "better",
    "different",
    "excellent",
    "general",
    "good",
    "important",
    "improved",
    "improves",
    "method",
    "methods",
    "novel",
    "rapid",
    "result",
    "results",
    "screening",
    "shows",
    "significant",
    "strategy",
    "system",
    "systems",
}
_PUBLICATION_METADATA_TOKENS = {
    "accepted",
    "ahead",
    "april",
    "article",
    "august",
    "december",
    "earlyview",
    "february",
    "issue",
    "january",
    "july",
    "june",
    "march",
    "may",
    "november",
    "october",
    "online",
    "published",
    "september",
    "volume",
    "vol",
}
_BROAD_CANDIDATE_TOKENS = {
    "battery",
    "batteries",
    "cell",
    "cells",
    "electrolyte",
    "electrolytes",
    "li",
    "lithium",
    "material",
    "materials",
    "solid",
    "state",
}


def build_keyword_analysis_payload(
    candidates: List[Dict[str, object]], metrics: JournalMetrics, scope: Optional[AnalysisScope] = None
) -> Dict[str, object]:
    analysis_scope = scope or AnalysisScope()
    papers = _all_matched_papers(candidates, metrics)
    selected = selected_papers(candidates, metrics, analysis_scope)
    categories = classify_papers(selected, DEFAULT_TAXONOMY)
    candidate_terms = discover_candidate_terms(selected, 2, DEFAULT_BLOCKLIST, DEFAULT_TAXONOMY)

    return {
        "scope": _scope_payload(analysis_scope),
        "taxonomy": [_taxonomy_payload(category) for category in DEFAULT_TAXONOMY],
        "blocklist": sorted(DEFAULT_BLOCKLIST),
        "journal_catalog": _journal_catalog_payload(metrics),
        "papers": papers,
        "selected_paper_ids": [str(paper["id"]) for paper in selected],
        "categories": categories,
        "candidate_terms": candidate_terms,
    }


def selected_papers(
    candidates: List[Dict[str, object]], metrics: JournalMetrics, scope: AnalysisScope
) -> List[Dict[str, object]]:
    date_from = parse_iso_date(scope.date_from)
    date_to = parse_iso_date(scope.date_to)
    selected_journal_keys = _selected_journal_keys(scope.selected_journals, metrics)
    selected_terms = {_normalize_phrase(term) for term in scope.selected_terms if _normalize_phrase(term)}
    selected_ids = _selected_paper_id_set(scope.selected_paper_ids)

    papers: List[Dict[str, object]] = []
    paper_dates: Dict[str, Optional[date]] = {}

    for candidate in candidates:
        record = _paper_record(candidate, metrics)
        if record is None:
            continue

        paper, paper_date, journal_keys, matched_term_keys = record
        if date_from and (paper_date is None or paper_date < date_from):
            continue
        if date_to and (paper_date is None or paper_date > date_to):
            continue

        if selected_journal_keys and not (selected_journal_keys & journal_keys):
            continue

        if selected_terms and not (selected_terms & matched_term_keys):
            continue

        paper_id = str(paper["id"])
        if selected_ids and paper_id not in selected_ids:
            continue

        papers.append(paper)
        paper_dates[paper_id] = paper_date

    _sort_papers(papers, paper_dates, scope.sort_mode)
    return papers


def classify_papers(
    papers: List[Dict[str, object]], taxonomy: Sequence[TaxonomyCategory]
) -> List[Dict[str, object]]:
    denominator = len(papers)
    if denominator == 0:
        return []

    results: List[Dict[str, object]] = []
    category_aliases = [
        (category, tuple(_normalize_phrase(alias) for alias in (category.name, *category.aliases)))
        for category in taxonomy
    ]

    for category, aliases in category_aliases:
        paper_ids: List[str] = []
        for paper in papers:
            text = _analysis_text(paper)
            if any(_contains_phrase(text, alias) for alias in aliases if alias):
                paper_ids.append(str(paper.get("id") or _paper_id(paper)))

        if not paper_ids:
            continue

        count = len(paper_ids)
        results.append(
            {
                "name": category.name,
                "aliases": list(category.aliases),
                "count": count,
                "percentage": round((count / denominator) * 100.0, 1),
                "paper_ids": paper_ids,
            }
        )

    results.sort(key=lambda item: (-int(item["count"]), str(item["name"]).casefold()))
    return results


def discover_candidate_terms(
    papers: List[Dict[str, object]],
    threshold: int,
    blocklist: Iterable[str],
    taxonomy: Sequence[TaxonomyCategory],
    phrase_lengths: Sequence[object] = DEFAULT_CANDIDATE_PHRASE_LENGTHS,
) -> List[Dict[str, object]]:
    minimum_count = max(int(threshold), 1)
    candidate_phrase_lengths = _candidate_phrase_lengths(phrase_lengths)
    blocked_phrases = {_normalize_phrase(term) for term in blocklist if _normalize_phrase(term)}
    taxonomy_phrases = _taxonomy_phrases(taxonomy)
    counts: Dict[str, Set[str]] = {}

    for paper in papers:
        paper_id = str(paper.get("id") or _paper_id(paper))
        normalized_text = _analysis_text(paper)
        tokens = _tokens_without_blocked_phrases(normalized_text, blocked_phrases)
        paper_terms: Set[str] = set()

        for width in candidate_phrase_lengths:
            if len(tokens) < width:
                continue
            for index in range(0, len(tokens) - width + 1):
                term = " ".join(tokens[index : index + width])
                if not _is_candidate_term(term, blocked_phrases, taxonomy_phrases, candidate_phrase_lengths):
                    continue
                paper_terms.add(term)

        for term in paper_terms:
            counts.setdefault(term, set()).add(paper_id)

    results = [
        {"term": term, "count": len(paper_ids), "paper_ids": sorted(paper_ids)}
        for term, paper_ids in counts.items()
        if len(paper_ids) >= minimum_count
    ]
    results.sort(
        key=lambda item: (
            -int(item["count"]),
            len(str(item["term"]).split()),
            -_candidate_term_score(str(item["term"])),
            str(item["term"]),
        )
    )
    return results[:MAX_CANDIDATE_TERMS]


def _scope_payload(scope: AnalysisScope) -> Dict[str, object]:
    payload = asdict(scope)
    for key in ("selected_journals", "selected_terms", "selected_paper_ids"):
        payload[key] = list(payload[key])
    return payload


def _taxonomy_payload(category: TaxonomyCategory) -> Dict[str, object]:
    return {"name": category.name, "aliases": list(category.aliases)}


def _journal_catalog_payload(metrics: JournalMetrics) -> List[Dict[str, object]]:
    def impact_value(metric) -> float:
        return metric.impact_factor if metric.impact_factor is not None else -1.0

    ordered = sorted(
        metrics.metrics,
        key=lambda metric: (-impact_value(metric), metric.journal.casefold()),
    )
    return [
        {
            "journal": metric.journal,
            "aliases": list(metric.aliases),
            "impact_factor": metric.impact_factor,
            "impact_metric": metric.impact_metric,
            "impact_label": metric.impact_label,
            "category": metric.category,
        }
        for metric in ordered
        if metric.journal
    ]


def _all_matched_papers(candidates: List[Dict[str, object]], metrics: JournalMetrics) -> List[Dict[str, object]]:
    papers: List[Dict[str, object]] = []
    paper_dates: Dict[str, Optional[date]] = {}

    for candidate in candidates:
        record = _paper_record(candidate, metrics)
        if record is None:
            continue
        paper, paper_date, _, _ = record
        papers.append(paper)
        paper_dates[str(paper["id"])] = paper_date

    _sort_papers(papers, paper_dates, "time")
    return papers


def _paper_record(
    candidate: Dict[str, object], metrics: JournalMetrics
) -> Optional[Tuple[Dict[str, object], Optional[date], Set[str], Set[str]]]:
    if not _is_matched_candidate(candidate):
        return None

    published = _string_value(candidate.get("published"))
    detected = _string_value(candidate.get("detected")) or published
    paper_date = first_iso_date(detected)
    display_journal, impact_factor, journal_keys = _journal_details(candidate, metrics)
    matched_terms = _terms(candidate.get("matched_terms"))
    matched_term_keys = {_normalize_phrase(term) for term in matched_terms if _normalize_phrase(term)}
    paper_id = _paper_id(candidate)
    paper = {
        "id": paper_id,
        "title": _string_value(candidate.get("title")),
        "journal": display_journal,
        "url": _string_value(candidate.get("url")),
        "doi": _string_value(candidate.get("doi")),
        "authors": _terms(candidate.get("authors")),
        "published": published,
        "detected": detected,
        "abstract": _string_value(candidate.get("abstract")),
        "source": _string_value(candidate.get("source")),
        "matched_terms": matched_terms,
        "impact_factor": impact_factor,
    }
    return paper, paper_date, journal_keys, matched_term_keys


def _sort_papers(
    papers: List[Dict[str, object]], paper_dates: Dict[str, Optional[date]], sort_mode: str
) -> None:
    def impact_value(paper: Dict[str, object]) -> float:
        value = paper.get("impact_factor")
        return value if isinstance(value, (int, float)) else -1.0

    def date_value(paper: Dict[str, object]) -> date:
        return paper_dates.get(str(paper["id"])) or date.min

    if sort_mode == "impact_factor":
        papers.sort(key=lambda paper: (impact_value(paper), date_value(paper)), reverse=True)
    elif sort_mode == "relevance":
        papers.sort(key=lambda paper: (len(paper.get("matched_terms", [])), date_value(paper)), reverse=True)
    else:
        papers.sort(key=lambda paper: (date_value(paper), impact_value(paper)), reverse=True)


def _paper_id(paper: Dict[str, object]) -> str:
    explicit_id = _string_value(paper.get("id")).strip()
    if explicit_id:
        return explicit_id

    identity = _string_value(paper.get("identity")).strip()
    if identity:
        return identity

    doi = _string_value(paper.get("doi")).strip()
    if doi:
        return f"doi:{doi.casefold()}"

    url = _string_value(paper.get("url")).strip()
    if url:
        return f"url:{url}"

    title = _normalize_phrase(_string_value(paper.get("title")))
    return f"title:{title}"


def _journal_details(candidate: Dict[str, object], metrics: JournalMetrics) -> Tuple[str, Optional[float], Set[str]]:
    raw_values = [
        _string_value(candidate.get("journal")),
        _string_value(candidate.get("journal_match")),
        _string_value(candidate.get("source")),
    ]

    metric = None
    for value in raw_values:
        if not value:
            continue
        metric = metrics.lookup(value)
        if metric:
            break

    fallback_journal = next((value for value in raw_values if value), "")
    display_journal = metric.journal if metric else fallback_journal
    impact_factor = metric.impact_factor if metric and metric.impact_factor is not None else _float_value(candidate.get("impact_factor"))

    journal_keys = {_normalize_journal(display_journal)}
    for value in raw_values:
        if value:
            journal_keys.add(_normalize_journal(value))
    if metric:
        journal_keys.add(_normalize_journal(metric.journal))
        for alias in metric.aliases:
            journal_keys.add(_normalize_journal(alias))

    return display_journal, impact_factor, {key for key in journal_keys if key}


def _selected_journal_keys(selected_journals: Sequence[str], metrics: JournalMetrics) -> Set[str]:
    keys: Set[str] = set()
    for journal in selected_journals:
        value = _string_value(journal)
        if not value:
            continue
        metric = metrics.lookup(value)
        if metric:
            keys.add(_normalize_journal(metric.journal))
            for alias in metric.aliases:
                keys.add(_normalize_journal(alias))
        keys.add(_normalize_journal(value))
    return {key for key in keys if key}


def _analysis_text(paper: Dict[str, object]) -> str:
    terms = " ".join(_terms(paper.get("matched_terms")))
    return _normalize_phrase(
        " ".join(
            [
                _string_value(paper.get("title")),
                _string_value(paper.get("abstract")),
                terms,
            ]
        )
    )


def _contains_phrase(text: str, phrase: str) -> bool:
    return bool(re.search(rf"(?:^| ){re.escape(phrase)}(?: |$)", text))


def _taxonomy_phrases(taxonomy: Sequence[TaxonomyCategory]) -> Set[str]:
    phrases: Set[str] = set()
    for category in taxonomy:
        for alias in (category.name, *category.aliases):
            normalized = _normalize_phrase(alias)
            if normalized:
                phrases.add(normalized)
    return phrases


def _tokens_without_blocked_phrases(text: str, blocked_phrases: Set[str]) -> List[str]:
    filtered = f" {text} "
    multiword_blocked = sorted((term for term in blocked_phrases if " " in term), key=len, reverse=True)
    for phrase in multiword_blocked:
        filtered = re.sub(rf" {re.escape(phrase)} ", " ", filtered)

    single_blocked = {term for term in blocked_phrases if " " not in term}
    return [token for token in _WORD_RE.findall(filtered) if token not in single_blocked]


def _candidate_phrase_lengths(values: Sequence[object]) -> Tuple[int, ...]:
    normalized_values: Set[int] = set()
    for value in values:
        try:
            phrase_length = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if phrase_length in _ALLOWED_CANDIDATE_PHRASE_LENGTHS:
            normalized_values.add(phrase_length)
    normalized = tuple(sorted(normalized_values))
    return normalized or DEFAULT_CANDIDATE_PHRASE_LENGTHS


def _is_candidate_term(
    term: str,
    blocked_phrases: Set[str],
    taxonomy_phrases: Set[str],
    phrase_lengths: Sequence[int],
) -> bool:
    if term in blocked_phrases or term in taxonomy_phrases:
        return False
    tokens = term.split()
    if len(tokens) not in phrase_lengths:
        return False
    if len(set(tokens)) < len(tokens):
        return False
    if any(len(token) < 2 and token != "li" for token in tokens):
        return False
    if any(_is_publication_metadata_token(token) for token in tokens):
        return False
    if not any(token in _DOMAIN_ANCHOR_TERMS for token in tokens):
        return False
    if all(token in _BROAD_CANDIDATE_TOKENS for token in tokens):
        return False
    if all(token in _LOW_VALUE_CANDIDATE_TOKENS for token in tokens):
        return False
    return True


def _is_publication_metadata_token(token: str) -> bool:
    if token in _PUBLICATION_METADATA_TOKENS:
        return True
    if re.fullmatch(r"\d{4}", token):
        return 1900 <= int(token) <= 2100
    return False


def _candidate_term_score(term: str) -> int:
    tokens = term.split()
    anchor_count = sum(1 for token in tokens if token in _DOMAIN_ANCHOR_TERMS)
    low_value_count = sum(1 for token in tokens if token in _LOW_VALUE_CANDIDATE_TOKENS)
    return (anchor_count * 4) + len(tokens) - low_value_count


def _terms(value: object) -> List[str]:
    if isinstance(value, (list, tuple, set)):
        return [_string_value(item) for item in value if _string_value(item)]
    if value:
        return [_string_value(value)]
    return []


def _selected_paper_id_set(values: Sequence[object]) -> Set[str]:
    return {value for value in (_string_value(paper_id) for paper_id in values) if value}


def _is_matched_candidate(candidate: Dict[str, object]) -> bool:
    return "matched" not in candidate or bool(candidate.get("matched"))


def _normalize_journal(value: str) -> str:
    return " ".join(_string_value(value).casefold().split())


def _normalize_phrase(value: object) -> str:
    text = _string_value(value).casefold()
    text = text.replace("-", " ")
    return " ".join(_WORD_RE.findall(text))


def _string_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _float_value(value: object) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
