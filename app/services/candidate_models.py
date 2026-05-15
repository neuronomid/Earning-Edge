from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

ScreenerStatus = Literal["success", "partial", "failed", "empty"]
StrategySource = Literal[
    "catalyst_confluence",
    "coiled_setup",
    "pead_continuation",
    "sector_relative_strength",
    "activist_13d_followthrough",
]
StrategyRunStatus = Literal["success", "empty", "failed", "fallback"]


@dataclass(slots=True, frozen=True)
class StrategyEventSignal:
    score: int
    is_supportive: bool
    detail: str


@dataclass(slots=True, frozen=True)
class CandidateRecord:
    ticker: str
    company_name: str | None
    market_cap: Decimal | None
    earnings_date: date | None
    current_price: Decimal | None
    earnings_date_verified: bool = True
    screener_rank: int | None = None
    daily_change_percent: Decimal | None = None
    volume: int | None = None
    sector: str | None = None
    sources: tuple[str, ...] = ("finviz",)
    validation_notes: tuple[str, ...] = ()
    strategy_source: StrategySource | None = None
    event_signal: StrategyEventSignal | None = None


@dataclass(slots=True, frozen=True)
class StrategyRunReport:
    strategy_source: StrategySource
    strategy_label: str
    provider: str
    status: StrategyRunStatus
    raw_row_count: int
    candidate_count: int
    finviz_candidate_count: int = 0
    backup_candidate_count: int = 0
    fallback_used: bool = False
    query_urls: tuple[str, ...] = ()
    filter_codes: tuple[str, ...] = ()
    criteria_summary: str | None = None
    sort_summary: str | None = None
    warning_text: str | None = None
    error: str | None = None


@dataclass(slots=True, frozen=True)
class CandidateBatch:
    candidates: tuple[CandidateRecord, ...]
    screener_status: ScreenerStatus
    fallback_used: bool
    warning_text: str | None = None
    strategy_reports: tuple[StrategyRunReport, ...] = ()
