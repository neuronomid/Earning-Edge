"""Pydantic schemas for the heavy-model decision step (PRD §7.5).

Every field listed in §7.5 must travel through ``DecisionInput`` so the heavy
model receives structured data, never vague prompts. The output schema mirrors
the recommendation card §13/§23 needs without the Telegram polish — Gemini
adds wording in Phase 11.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EarningsTiming = Literal["BMO", "AMC", "unknown"]
StrategyPermission = Literal["long_only", "short_only", "long_and_short"]
RiskProfile = Literal["Conservative", "Balanced", "Aggressive"]
DecisionAction = Literal["recommend", "no_trade", "watchlist"]
OptionType = Literal["call", "put"]
PositionSide = Literal["long", "short"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OptionChainCandidate(_Frozen):
    option_type: OptionType
    position_side: PositionSide
    strike: Decimal
    expiry: date
    bid: Decimal | None = None
    ask: Decimal | None = None
    mid: Decimal | None = None
    spread_percent: Decimal | None = None
    implied_volatility: Decimal | None = None
    delta: Decimal | None = None
    volume: int | None = None
    open_interest: int | None = None
    liquidity_score: int | None = None
    breakeven: Decimal | None = None


class CandidateBundle(_Frozen):
    """Per-stock structured payload — mirrors PRD §7.5 exactly."""

    ticker: str
    company_name: str
    earnings_date: date
    earnings_timing: EarningsTiming = "unknown"
    market_cap: Decimal | None = None
    current_price: Decimal | None = None
    recent_returns: dict[str, float] = Field(default_factory=dict)
    trend_indicators: dict[str, float] = Field(default_factory=dict)
    sector_comparison: dict[str, float] = Field(default_factory=dict)
    market_comparison: dict[str, float] = Field(default_factory=dict)
    news_summary: str = ""
    option_chain_candidates: list[OptionChainCandidate] = Field(default_factory=list)
    expected_move: Decimal | None = None
    previous_earnings_move: Decimal | None = None
    data_confidence_score: int = Field(ge=0, le=100, default=100)
    rejected_contract_reasons: list[str] = Field(default_factory=list)


class DecisionInput(_Frozen):
    """Top-level structured input to ``LLMRouter.decide`` (PRD §7.5)."""

    user_strategy_permission: StrategyPermission
    risk_profile: RiskProfile
    account_size: Decimal
    candidates: list[CandidateBundle] = Field(min_length=1)


class ChosenContract(_Frozen):
    ticker: str
    option_type: OptionType
    position_side: PositionSide
    strike: Decimal
    expiry: date
    rationale: str


class StructuredDecision(_Frozen):
    """Heavy-model response (PRD §7.4 final decision authority)."""

    action: DecisionAction
    chosen_ticker: str | None = None
    chosen_contract: ChosenContract | None = None
    direction_score: int | None = Field(default=None, ge=0, le=100)
    contract_score: int | None = Field(default=None, ge=0, le=100)
    final_score: int | None = Field(default=None, ge=0, le=100)
    reasoning: str
    key_evidence: list[str] = Field(default_factory=list)
    key_concerns: list[str] = Field(default_factory=list)
    watchlist_tickers: list[str] = Field(default_factory=list)
