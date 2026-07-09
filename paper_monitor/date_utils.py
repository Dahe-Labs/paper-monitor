import re
from datetime import date
from typing import Optional

_FULL_ISO_DATE_RE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
_SHORT_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_LONG_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


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


def format_display_date(value: object, style: str = "compact") -> str:
    parsed = first_iso_date(value)
    if parsed is None:
        return str(value or "").strip()

    if style == "compact":
        return f"{_SHORT_MONTHS[parsed.month - 1]} {parsed.day}, {parsed.year}"
    if style == "long":
        return f"{_LONG_MONTHS[parsed.month - 1]} {parsed.day}, {parsed.year}"
    if style == "short":
        return f"{_SHORT_MONTHS[parsed.month - 1]} {parsed.day}"
    raise ValueError(f"Unsupported display date style: {style}")


def display_article_date(value: object) -> str:
    return format_display_date(value, style="compact")
