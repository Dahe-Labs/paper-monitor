import re
from dataclasses import dataclass
from typing import List, Optional

from .models import Article


@dataclass(frozen=True)
class FilterConfig:
    include_terms: List[str]
    exclude_terms: List[str]
    journals: List[str]


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    reason: str
    matched_terms: List[str]
    journal_match: Optional[str]


def match_article(article: Article, config: FilterConfig) -> MatchResult:
    text = _searchable_text(article)
    excluded = [term for term in config.exclude_terms if _contains_term(text, term)]
    if excluded:
        return MatchResult(False, "excluded-term", [], None)

    journal_match = _match_journal(article.journal, config.journals)
    if config.journals and journal_match is None:
        return MatchResult(False, "journal-not-allowed", [], None)

    matched_terms = [term for term in config.include_terms if _contains_term(text, term)]
    if not matched_terms:
        return MatchResult(False, "no-include-term", [], journal_match)

    return MatchResult(True, "matched", matched_terms, journal_match)


def _searchable_text(article: Article) -> str:
    return _normalize_search_text(" ".join([article.title, article.abstract, article.journal]))


def _contains_term(text: str, term: str) -> bool:
    normalized = _normalize_search_text(term)
    return bool(normalized) and normalized in text


def _match_journal(journal: str, allowlist: List[str]) -> Optional[str]:
    normalized_journal = _normalize_name(journal)
    for allowed in allowlist:
        if _normalize_name(allowed) == normalized_journal:
            return allowed
    return None


def _normalize_name(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _normalize_search_text(value: str) -> str:
    value = (value or "").casefold()
    value = re.sub(r"[\u2010-\u2015\-]+", " ", value)
    return " ".join(value.split())
