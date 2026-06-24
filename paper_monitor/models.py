from dataclasses import dataclass
from typing import Tuple


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
    if doi.lower().startswith("doi:"):
        doi = doi[4:]
    if doi.lower().startswith("https://doi.org/"):
        doi = doi[16:]
    if doi.lower().startswith("http://doi.org/"):
        doi = doi[15:]
    return doi.strip().lower()
