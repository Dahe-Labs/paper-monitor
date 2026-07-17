import re
from dataclasses import dataclass
from typing import Tuple

_DOI_RESOLVER_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
)
_DOI_QUERY_SUFFIX = re.compile(r"\?[A-Za-z][A-Za-z0-9._~-]*=")


@dataclass(frozen=True)
class Article:
    title: str
    journal: str
    url: str
    doi: str
    published: str
    abstract: str
    source: str
    detected: str = ""
    authors: Tuple[str, ...] = ()
    source_id: str = ""

    @property
    def identity(self) -> str:
        doi = normalize_doi(self.doi)
        if doi:
            return "doi:" + doi
        normalized_title = " ".join(self.title.lower().split())
        normalized_url = self.url.strip().lower()
        return "title-url:" + normalized_title + "|" + normalized_url


def normalize_doi(value: str) -> str:
    doi = (value or "").strip()
    folded = doi.casefold()
    if folded.startswith("doi:"):
        doi = doi[4:].strip()
        folded = doi.casefold()
    for prefix in _DOI_RESOLVER_PREFIXES:
        if folded.startswith(prefix):
            doi = doi[len(prefix) :]
            break
    doi = doi.split("#", 1)[0]
    query = _DOI_QUERY_SUFFIX.search(doi)
    if query is not None:
        doi = doi[: query.start()]
    return doi.strip().rstrip(".,;)").casefold()
