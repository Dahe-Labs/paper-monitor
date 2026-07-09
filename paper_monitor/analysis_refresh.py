import copy
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .config import load_app_config
from .filtering import match_article
from .journal_metrics import load_journal_metrics
from .keyword_analysis import AnalysisScope, build_keyword_analysis_payload
from .models import Article
from .sources import fetch_all_sources

FetchArticles = Callable[[Dict[str, object]], List[Article]]


def run_crossref_keyword_analysis(
    config_path: Path,
    date_from: str,
    date_to: str,
    sort_mode: str = "time",
    analysis_depth: str = "fast",
    top_n: int = 30,
    selected_journals: Optional[Sequence[str]] = None,
    fetch_articles: Optional[FetchArticles] = None,
) -> Dict[str, object]:
    app_config = load_app_config(config_path)
    clean_analysis_depth = _analysis_depth(analysis_depth)
    if selected_journals is not None and not selected_journals:
        scope = AnalysisScope(
            date_from=date_from,
            date_to=date_to,
            selected_journals=(),
            sort_mode=sort_mode,
            top_n=top_n,
        )
        payload = build_keyword_analysis_payload(
            [],
            load_journal_metrics(app_config.journal_metrics_path),
            scope=scope,
        )
        payload["fetched"] = 0
        payload["matched"] = 0
        payload["skipped"] = 0
        payload["scope"]["source"] = "crossref"  # type: ignore[index]
        payload["scope"]["analysis_depth"] = clean_analysis_depth  # type: ignore[index]
        return payload

    source_config = _crossref_only_source_config(
        app_config.source_config,
        date_from,
        date_to,
        selected_journals,
        clean_analysis_depth,
        cache_dir=app_config.database_path.parent / "crossref-cache",
    )
    fetch = fetch_articles or fetch_all_sources
    fetched_articles = fetch(source_config)
    candidates = []
    seen_identities = set()
    skipped = 0

    for article in fetched_articles:
        if article.identity in seen_identities:
            skipped += 1
            continue
        seen_identities.add(article.identity)
        result = match_article(article, app_config.monitor_config.filter_config)
        if not result.matched:
            skipped += 1
        candidates.append(
            {
                "identity": article.identity,
                "title": article.title,
                "journal": article.journal,
                "url": article.url,
                "doi": article.doi,
                "authors": list(article.authors),
                "published": article.published,
                "detected": article.detected or article.published,
                "abstract": article.abstract,
                "source": article.source,
                "matched": result.matched,
                "reason": result.reason,
                "matched_terms": list(result.matched_terms),
                "journal_match": result.journal_match,
            }
        )

    journals = tuple(selected_journals or app_config.monitor_config.filter_config.journals)
    scope = AnalysisScope(
        date_from=date_from,
        date_to=date_to,
        selected_journals=journals,
        sort_mode=sort_mode,
        top_n=top_n,
    )
    payload = build_keyword_analysis_payload(
        candidates,
        load_journal_metrics(app_config.journal_metrics_path),
        scope=scope,
    )
    payload["fetched"] = len(fetched_articles)
    payload["matched"] = sum(1 for candidate in candidates if candidate["matched"])
    payload["skipped"] = skipped
    payload["scope"]["source"] = "crossref"  # type: ignore[index]
    payload["scope"]["analysis_depth"] = clean_analysis_depth  # type: ignore[index]
    return payload


def _crossref_only_source_config(
    source_config: Dict[str, object],
    date_from: str,
    date_to: str,
    selected_journals: Optional[Sequence[str]],
    analysis_depth: str = "fast",
    cache_dir: Optional[Path] = None,
) -> Dict[str, object]:
    crossref = copy.deepcopy(source_config.get("crossref", {}))
    if not isinstance(crossref, dict):
        crossref = {}
    crossref["enabled"] = True
    crossref["date_from"] = date_from
    crossref["date_to"] = date_to
    crossref["cursor_pagination"] = True
    crossref["retry_count"] = max(_int_setting(crossref.get("retry_count"), 2), 2)
    crossref["retry_base_seconds"] = 0.75
    crossref["retry_max_seconds"] = 8.0
    if _analysis_depth(analysis_depth) == "exhaustive":
        crossref["query_field"] = "bibliographic"
        crossref["rows_per_journal"] = 1000
        crossref["max_workers"] = min(max(_int_setting(crossref.get("max_workers"), 3), 1), 3)
        crossref["date_chunk_days"] = 31
        crossref["max_cursor_pages"] = 100
        crossref["cache_ttl_seconds"] = 3600
        crossref.pop("select_fields", None)
    else:
        crossref["query_field"] = "title"
        crossref["rows_per_journal"] = 1000
        crossref["max_workers"] = 6
        crossref["date_chunk_days"] = 0
        crossref["max_cursor_pages"] = 1
        crossref["cache_ttl_seconds"] = 21600
        crossref["select_fields"] = [
            "DOI",
            "title",
            "container-title",
            "URL",
            "author",
            "published",
            "published-print",
            "published-online",
            "created",
            "deposited",
        ]
    if cache_dir is not None:
        crossref["cache_dir"] = str(cache_dir)
    if selected_journals is not None:
        crossref["journal_titles"] = _formal_crossref_journal_titles(selected_journals)
    return {
        "rss": [],
        "crossref": crossref,
        "openalex": {"enabled": False},
    }


def _formal_crossref_journal_titles(values: Sequence[str]) -> List[str]:
    return [
        str(journal).strip()
        for journal in values
        if str(journal).strip() and _normalized_key(journal) != "arxiv"
    ]


def _normalized_key(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _int_setting(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _analysis_depth(value: object) -> str:
    return "exhaustive" if str(value or "").strip().lower() == "exhaustive" else "fast"
