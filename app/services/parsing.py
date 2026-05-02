from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

_COMPACT_NUMBER_RE = re.compile(
    r"(?P<value>[+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<unit>[KMBT])?\b",
    re.IGNORECASE,
)
_UNIT_MULTIPLIER = {
    "K": Decimal("1000"),
    "M": Decimal("1000000"),
    "B": Decimal("1000000000"),
    "T": Decimal("1000000000000"),
}
_DATE_FORMATS_WITH_YEAR = (
    "%Y-%m-%d",
    "%b %d, %Y",
    "%b %d %Y",
    "%B %d, %Y",
    "%B %d %Y",
)
_DATE_FORMATS_WITHOUT_YEAR = ("%b %d", "%B %d")


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_compact_decimal(text: str) -> Decimal | None:
    normalized = normalize_text(text).translate({0x2212: 0x2D})
    match = _COMPACT_NUMBER_RE.search(normalized)
    if match is None:
        return None
    raw_value = match.group("value").replace(",", "")
    unit = (match.group("unit") or "").upper()
    try:
        value = Decimal(raw_value)
    except InvalidOperation:
        return None
    return value * _UNIT_MULTIPLIER.get(unit, Decimal("1"))


def parse_compact_int(text: str) -> int | None:
    value = parse_compact_decimal(text)
    return None if value is None else int(value)


def parse_percent(text: str) -> Decimal | None:
    normalized = normalize_text(text).replace("%", "").translate({0x2212: 0x2D})
    if normalized == "":
        return None
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def parse_date_value(text: str, *, today: date | None = None) -> date | None:
    normalized = normalize_text(text)
    if normalized == "":
        return None
    for fmt in _DATE_FORMATS_WITH_YEAR:
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    reference = today or date.today()
    for fmt in _DATE_FORMATS_WITHOUT_YEAR:
        try:
            parsed = datetime.strptime(normalized, fmt).date().replace(year=reference.year)
        except ValueError:
            continue
        if parsed < reference:
            return parsed.replace(year=reference.year + 1)
        return parsed
    return None
