import re
from datetime import date
from typing import Optional


_FULL_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def parse_iso_date(value: object) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def first_iso_date(value: object) -> Optional[date]:
    match = _FULL_ISO_DATE_RE.search(str(value or ""))
    if match is None:
        return None
    return parse_iso_date(match.group(0))


def display_article_date(value: object) -> str:
    parsed = first_iso_date(value)
    if parsed is not None:
        return parsed.isoformat()
    return str(value or "").strip()
