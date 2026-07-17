import re
from datetime import date
from typing import Optional, Tuple

_FULL_ISO_DATE_RE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
_ISO_DATE_PARTS_RE = re.compile(
    r"(?<!\d)(?P<year>\d{4})(?:-(?P<month>\d{2})(?:-(?P<day>\d{2}))?)?(?![-\d])"
)
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


def first_iso_date_key(value: object) -> str:
    """Return the first valid ISO date while preserving source precision."""

    parts = _first_iso_date_parts(value)
    if parts is None:
        return ""
    year, month, day = parts
    if day is not None:
        return f"{year:04d}-{month:02d}-{day:02d}"
    if month is not None:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}"


def iso_date_sort_key(value: object) -> Tuple[int, int, int, int]:
    """Sort full and partial ISO dates without inventing missing precision."""

    parts = _first_iso_date_parts(value)
    if parts is None:
        return (0, 0, 0, 0)
    year, month, day = parts
    precision = 3 if day is not None else 2 if month is not None else 1
    return (year, month or 0, day or 0, precision)


def format_display_date(value: object, style: str = "compact") -> str:
    parsed = first_iso_date(value)
    if parsed is None:
        parts = _first_iso_date_parts(value)
        if parts is None:
            return str(value or "").strip()
        year, month, _day = parts
        if month is None:
            return str(year)
        month_names = _LONG_MONTHS if style == "long" else _SHORT_MONTHS
        if style not in {"compact", "long", "short"}:
            raise ValueError(f"Unsupported display date style: {style}")
        return f"{month_names[month - 1]} {year}"

    if style == "compact":
        return f"{_SHORT_MONTHS[parsed.month - 1]} {parsed.day}, {parsed.year}"
    if style == "long":
        return f"{_LONG_MONTHS[parsed.month - 1]} {parsed.day}, {parsed.year}"
    if style == "short":
        return f"{_SHORT_MONTHS[parsed.month - 1]} {parsed.day}"
    raise ValueError(f"Unsupported display date style: {style}")


def display_article_date(value: object) -> str:
    return format_display_date(value, style="compact")


def _first_iso_date_parts(value: object) -> Optional[Tuple[int, Optional[int], Optional[int]]]:
    for match in _ISO_DATE_PARTS_RE.finditer(str(value or "")):
        year = int(match.group("year"))
        month_text = match.group("month")
        day_text = match.group("day")
        month = int(month_text) if month_text is not None else None
        day = int(day_text) if day_text is not None else None
        if month is not None and not 1 <= month <= 12:
            continue
        if day is not None:
            try:
                date(year, month or 1, day)
            except ValueError:
                continue
        return year, month, day
    return None
