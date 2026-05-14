from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.services.sec.filings_client import FilingHeader

_ACTIVE_INTENT_PHRASES: tuple[str, ...] = (
    "board representation",
    "engagement with management",
    "strategic alternatives",
    "operational changes",
    "shareholder rights",
    "proposals",
    "nominate directors",
    "spin-off",
    "spinoff",
    "review strategic",
    "value-enhancing",
    "unlock shareholder value",
    "operational improvements",
)
_PASSIVE_PHRASES: tuple[str, ...] = (
    "investment purposes only",
    "no plans or proposals",
    "no present intention",
    "solely for investment",
)
_ITEM4_HEADER_RE = re.compile(r"item\s*4\b[^a-z]*purpose", re.IGNORECASE)
_NEXT_ITEM_RE = re.compile(r"item\s*5\b", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_PERCENT_RE = re.compile(r"([0-9]{1,3}(?:[.,][0-9]{1,3})?)\s*%")
_WORD_PERCENT_RE = re.compile(
    r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    r"fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|twenty-five|thirty|"
    r"forty|fifty)\b(?:\s+point\s+([a-z]+))?",
    re.IGNORECASE,
)
_WORD_TO_INT = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "twenty-five": 25,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}


@dataclass(slots=True, frozen=True)
class ActivistFiling:
    cik: str
    ticker: str | None
    filer_name: str | None
    accession: str
    form_type: Literal["SC 13D", "SC 13D/A"]
    filing_date: date
    stake_percent: Decimal | None
    item4_active_intent: bool
    primary_doc_url: str
    is_substantive: bool


def parse_filing(
    header: FilingHeader,
    document_text: str,
    *,
    ticker: str | None = None,
) -> ActivistFiling | None:
    """Parse a fetched 13D filing into an ActivistFiling, or return None if it fails any
    hard guard (no stake percent, no active intent for an SC 13D)."""
    text = _strip_text(document_text)
    if not text:
        return None
    item4 = _extract_item4(text)
    active_intent = _classify_active_intent(item4) if item4 else False
    stake_percent = _extract_stake_percent(text)
    if stake_percent is None:
        return None
    if header.form_type == "SC 13D" and not active_intent:
        return None

    is_substantive = _is_substantive_amendment(text) if header.form_type == "SC 13D/A" else True

    resolved_ticker = (ticker or header.subject_ticker or "").upper() or None

    return ActivistFiling(
        cik=header.cik,
        ticker=resolved_ticker,
        filer_name=header.filer_name,
        accession=header.accession,
        form_type=header.form_type,
        filing_date=header.filing_date,
        stake_percent=stake_percent,
        item4_active_intent=active_intent,
        primary_doc_url=header.primary_doc_url,
        is_substantive=is_substantive,
    )


def _strip_text(value: str) -> str:
    without_tags = _TAG_RE.sub(" ", value)
    return _WHITESPACE_RE.sub(" ", without_tags).strip()


def _extract_item4(text: str) -> str | None:
    match = _ITEM4_HEADER_RE.search(text)
    if match is None:
        return None
    start = match.end()
    next_match = _NEXT_ITEM_RE.search(text, pos=start)
    end = next_match.start() if next_match else min(len(text), start + 4000)
    return text[start:end].strip()


def _classify_active_intent(item4_text: str) -> bool:
    lower = item4_text.lower()
    if any(phrase in lower for phrase in _PASSIVE_PHRASES):
        return False
    return any(phrase in lower for phrase in _ACTIVE_INTENT_PHRASES)


def _extract_stake_percent(text: str) -> Decimal | None:
    # Find the first plausible stake percentage. We bias toward the cover-page region by
    # looking at the first 6000 characters of the cleaned text first.
    head = text[:6000]
    for match in _PERCENT_RE.finditer(head):
        candidate = _to_decimal(match.group(1))
        if candidate is None:
            continue
        if Decimal("4") <= candidate <= Decimal("80"):
            return candidate

    word_match = _WORD_PERCENT_RE.search(head)
    if word_match is not None:
        whole = _WORD_TO_INT.get(word_match.group(1).lower().replace(" ", "-"))
        if whole is not None:
            fractional = word_match.group(2)
            if fractional:
                digit = _WORD_TO_INT.get(fractional.lower())
                if digit is not None and 0 <= digit <= 9:
                    return Decimal(f"{whole}.{digit}")
            return Decimal(whole)
    return None


def _is_substantive_amendment(text: str) -> bool:
    item4 = _extract_item4(text) or ""
    return _classify_active_intent(item4)


def _to_decimal(value: str) -> Decimal | None:
    normalized = value.replace(",", ".")
    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return None
