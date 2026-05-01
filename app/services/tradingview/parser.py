from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup, Tag

from app.services.candidate_models import CandidateRecord

_COMPACT_NUMBER_RE = re.compile(
    r"(?P<value>[+-]?\d+(?:,\d{3})*(?:\.\d+)?)\s*(?P<unit>[KMBT])?\b",
    re.IGNORECASE,
)
_HEADER_MAP = {
    "symbol": "symbol",
    "price": "price",
    "change %": "change_pct",
    "volume": "volume",
    "market cap": "market_cap",
    "sector": "sector",
    "upcoming earnings date": "earnings_date",
}
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
_ARIA_ROW_RE = re.compile(r'^\s*-\s+row(?:\s+"(?P<row_text>.*)")?:?\s*$')
_ARIA_CELL_RE = re.compile(r'^\s*-\s+cell(?:\s+"(?P<cell_text>.*)")?:?\s*$')


def normalize_text(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def canonicalize_header(text: str) -> str | None:
    normalized = normalize_text(text).lower()
    for prefix, alias in _HEADER_MAP.items():
        if normalized.startswith(prefix):
            return alias
    return None


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

    multiplier = _UNIT_MULTIPLIER.get(unit, Decimal("1"))
    return value * multiplier


def parse_compact_int(text: str) -> int | None:
    value = parse_compact_decimal(text)
    if value is None:
        return None
    return int(value)


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


def parse_candidate_table(
    html: str,
    *,
    today: date | None = None,
    limit: int = 5,
) -> list[CandidateRecord]:
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if table is None:
        return []

    header_cells: list[Tag]
    header_cells = list(table.find_all("th"))
    if not header_cells:
        first_row = table.find("tr")
        if first_row is None:
            return []
        header_cells = list(first_row.find_all(["th", "td"], recursive=False))

    aliases = [canonicalize_header(cell.get_text(" ", strip=True)) for cell in header_cells]
    body = table.find("tbody")
    rows: list[Tag]
    if body is not None:
        rows = list(body.find_all("tr", recursive=False))
    else:
        all_rows = list(table.find_all("tr"))
        rows = all_rows[1:] if len(all_rows) > 1 else []

    parsed_rows: list[CandidateRecord] = []
    for row in rows:
        cells = row.find_all(["td", "th"], recursive=False)
        if not cells:
            continue

        by_alias = {
            alias: cells[index]
            for index, alias in enumerate(aliases[: len(cells)])
            if alias is not None
        }
        ticker, company_name = _extract_symbol_fields(by_alias.get("symbol"))
        if ticker == "":
            continue

        parsed_rows.append(
            CandidateRecord(
                ticker=ticker,
                company_name=company_name,
                market_cap=_parse_cell_decimal(by_alias.get("market_cap")),
                earnings_date=_parse_cell_date(by_alias.get("earnings_date"), today=today),
                current_price=_parse_cell_decimal(by_alias.get("price")),
                daily_change_percent=_parse_cell_percent(by_alias.get("change_pct")),
                volume=_parse_cell_int(by_alias.get("volume")),
                sector=_parse_cell_text(by_alias.get("sector")),
                sources=("tradingview",),
            )
        )
        if len(parsed_rows) >= limit:
            break
    return parsed_rows


def parse_aria_snapshot(snapshot: str, *, limit: int = 5) -> list[CandidateRecord]:
    rows: list[CandidateRecord] = []
    current_cells: list[str] | None = None

    for line in snapshot.splitlines():
        if _ARIA_ROW_RE.match(line):
            if current_cells is not None:
                record = _candidate_from_aria_cells(current_cells)
                if record is not None:
                    rows.append(record)
                    if len(rows) >= limit:
                        return rows
            current_cells = []
            continue

        cell_match = _ARIA_CELL_RE.match(line)
        if current_cells is not None and cell_match is not None:
            current_cells.append(cell_match.group("cell_text") or "")

    if current_cells is not None and len(rows) < limit:
        record = _candidate_from_aria_cells(current_cells)
        if record is not None:
            rows.append(record)
    return rows[:limit]


def _extract_symbol_fields(cell: Tag | None) -> tuple[str, str | None]:
    if cell is None:
        return "", None

    links = cell.find_all("a")
    if links:
        ticker = normalize_text(links[0].get_text(" ", strip=True)).upper()
        company = normalize_text(links[1].get_text(" ", strip=True)) if len(links) > 1 else None
        return ticker, company

    text = normalize_text(cell.get_text(" ", strip=True))
    if text == "":
        return "", None

    parts = text.split(" ", 1)
    ticker = parts[0].upper()
    company = _clean_company_suffix(parts[1]) if len(parts) > 1 else None
    return ticker, company


def _parse_cell_text(cell: Tag | None) -> str | None:
    if cell is None:
        return None
    text = normalize_text(cell.get_text(" ", strip=True))
    return text or None


def _parse_cell_decimal(cell: Tag | None) -> Decimal | None:
    if cell is None:
        return None
    return parse_compact_decimal(cell.get_text(" ", strip=True))


def _parse_cell_int(cell: Tag | None) -> int | None:
    if cell is None:
        return None
    return parse_compact_int(cell.get_text(" ", strip=True))


def _parse_cell_percent(cell: Tag | None) -> Decimal | None:
    if cell is None:
        return None
    return parse_percent(cell.get_text(" ", strip=True))


def _parse_cell_date(cell: Tag | None, *, today: date | None) -> date | None:
    if cell is None:
        return None
    return parse_date_value(cell.get_text(" ", strip=True), today=today)


def _candidate_from_aria_cells(cells: list[str]) -> CandidateRecord | None:
    if len(cells) < 6:
        return None

    ticker, company_name = _extract_symbol_fields_from_text(cells[0])
    if ticker == "" or ticker == "SYMBOL":
        return None

    sector = normalize_text(cells[10]) if len(cells) > 10 and cells[10] != "" else None
    return CandidateRecord(
        ticker=ticker,
        company_name=company_name,
        market_cap=parse_compact_decimal(cells[5]),
        earnings_date=None,
        current_price=parse_compact_decimal(cells[1]),
        daily_change_percent=parse_percent(cells[2]),
        volume=parse_compact_int(cells[3]),
        sector=sector,
        sources=("tradingview",),
    )


def _extract_symbol_fields_from_text(text: str) -> tuple[str, str | None]:
    normalized = normalize_text(text)
    if normalized == "":
        return "", None
    parts = normalized.split(" ", 1)
    ticker = parts[0].upper()
    company = _clean_company_suffix(parts[1]) if len(parts) > 1 else None
    return ticker, company


def _clean_company_suffix(value: str) -> str:
    cleaned = normalize_text(value)
    for suffix in (" D DR", " DR", " D"):
        if cleaned.endswith(suffix):
            return cleaned[: -len(suffix)].rstrip()
    return cleaned
