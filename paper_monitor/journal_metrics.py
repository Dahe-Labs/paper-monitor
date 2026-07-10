import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class JournalMetric:
    journal: str
    aliases: List[str]
    impact_factor: Optional[float]
    impact_factor_year: Optional[int]
    five_year_impact_factor: Optional[float]
    level: str
    source_url: str
    rank: Optional[int] = None
    default_selected: bool = True
    category: str = ""
    impact_metric: str = "Journal Impact Factor"
    impact_label: str = "IF"
    cited_by_count: Optional[int] = None


class JournalMetrics:
    def __init__(self, metrics: List[JournalMetric]):
        self.metrics = metrics
        self._by_name: Dict[str, JournalMetric] = {}
        for metric in metrics:
            self._by_name[_normalize(metric.journal)] = metric
            for alias in metric.aliases:
                self._by_name[_normalize(alias)] = metric

    def lookup(self, journal: str) -> Optional[JournalMetric]:
        return self._by_name.get(_normalize(journal))

    def names_for(self, journal: str) -> List[str]:
        metric = self.lookup(journal)
        if metric is None:
            return [journal]
        return [metric.journal] + list(metric.aliases)


def load_journal_metrics(path: Path) -> JournalMetrics:
    path = Path(path)
    if not path.exists():
        return JournalMetrics([])
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = [
        JournalMetric(
            journal=str(item.get("journal", "")),
            aliases=[str(alias) for alias in item.get("aliases", [])],
            impact_factor=_optional_float(item.get("impact_factor")),
            impact_factor_year=_optional_int(item.get("impact_factor_year")),
            five_year_impact_factor=_optional_float(item.get("five_year_impact_factor")),
            level=str(item.get("level", "")),
            source_url=str(item.get("source_url", "")),
            rank=_optional_int(item.get("rank")),
            default_selected=bool(item.get("default_selected", True)),
            category=str(item.get("category", "")),
            impact_metric=str(item.get("impact_metric", "Journal Impact Factor")),
            impact_label=str(item.get("impact_label", "IF")),
            cited_by_count=_optional_int(item.get("cited_by_count")),
        )
        for item in payload.get("journals", [])
        if item.get("journal")
    ]
    return JournalMetrics(metrics)


def _normalize(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _optional_float(value: object) -> Optional[float]:
    if value in ("", None):
        return None
    return float(value)


def _optional_int(value: object) -> Optional[int]:
    if value in ("", None):
        return None
    return int(value)
