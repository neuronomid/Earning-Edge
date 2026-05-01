from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

TradingViewStatus = Literal["success", "failed"]


@dataclass(slots=True, frozen=True)
class CandidateRecord:
    ticker: str
    company_name: str | None
    market_cap: Decimal | None
    earnings_date: date | None
    current_price: Decimal | None
    daily_change_percent: Decimal | None = None
    volume: int | None = None
    sector: str | None = None
    sources: tuple[str, ...] = ("tradingview",)
    validation_notes: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class CandidateBatch:
    candidates: tuple[CandidateRecord, ...]
    tradingview_status: TradingViewStatus
    fallback_used: bool
    warning_text: str | None = None
