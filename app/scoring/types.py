from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.services.market_data.types import MarketSnapshot
from app.services.news.types import NewsBrief

DirectionClassification = Literal["bullish", "bearish", "neutral", "avoid"]
DecisionAction = Literal["recommend", "watchlist", "no_trade"]
RiskProfile = Literal["Conservative", "Balanced", "Aggressive"]
StrategyPermission = Literal["long", "short", "long_and_short"]
OptionType = Literal["call", "put"]
PositionSide = Literal["long", "short"]
Strategy = Literal["long_call", "long_put", "short_put", "short_call"]
EarningsTiming = Literal["BMO", "AMC", "unknown"]
ConflictSeverity = Literal["slight", "moderate", "severe"]

RISK_PROFILE_PCTS: dict[RiskProfile, Decimal] = {
    "Conservative": Decimal("0.01"),
    "Balanced": Decimal("0.02"),
    "Aggressive": Decimal("0.04"),
}

SHORT_NOTIONAL_CAP_PCTS: dict[RiskProfile, Decimal] = {
    "Conservative": Decimal("0.10"),
    "Balanced": Decimal("0.20"),
    "Aggressive": Decimal("0.35"),
}

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


@dataclass(slots=True, frozen=True)
class UserContext:
    account_size: Decimal
    risk_profile: RiskProfile
    strategy_permission: StrategyPermission
    max_contracts: int = 3
    max_option_premium: Decimal | None = None
    custom_risk_percent: Decimal | None = None
    has_valid_openrouter_api_key: bool = True


@dataclass(slots=True, frozen=True)
class SourceConflict:
    field: str
    severity: ConflictSeverity
    detail: str


@dataclass(slots=True, frozen=True)
class OptionContractInput:
    ticker: str
    option_type: OptionType
    position_side: PositionSide
    strike: Decimal
    expiry: date
    bid: Decimal | None = None
    ask: Decimal | None = None
    mid: Decimal | None = None
    volume: int | None = None
    open_interest: int | None = None
    implied_volatility: Decimal | None = None
    delta: Decimal | None = None
    theta: Decimal | None = None
    source: str = "unknown"
    quote_timestamp: date | None = None
    is_tradable: bool = True
    is_stale: bool = False

    @property
    def strategy(self) -> Strategy:
        if self.position_side == "long" and self.option_type == "call":
            return "long_call"
        if self.position_side == "long" and self.option_type == "put":
            return "long_put"
        if self.position_side == "short" and self.option_type == "put":
            return "short_put"
        return "short_call"


@dataclass(slots=True, frozen=True)
class CandidateContext:
    ticker: str
    company_name: str
    earnings_date: date
    earnings_timing: EarningsTiming
    market_snapshot: MarketSnapshot
    news_brief: NewsBrief
    option_chain: tuple[OptionContractInput, ...] = ()
    verified_earnings_date: bool = True
    identity_verified: bool = True
    expected_move_percent: Decimal | None = None
    previous_earnings_move_percent: Decimal | None = None
    source_conflicts: tuple[SourceConflict, ...] = ()
    calculation_errors: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ScoreFactor:
    name: str
    score: int
    weight: int
    detail: str


@dataclass(slots=True, frozen=True)
class HardVeto:
    code: str
    reason: str


@dataclass(slots=True, frozen=True)
class SoftPenalty:
    code: str
    reason: str
    score_delta: int


@dataclass(slots=True, frozen=True)
class DataConfidenceResult:
    score: int
    label: str
    blockers: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class DirectionResult:
    classification: DirectionClassification
    bias: Decimal
    score: int
    factors: tuple[ScoreFactor, ...]
    reasons: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class StrategySelection:
    allowed_strategies: tuple[Strategy, ...]
    preferred_order: tuple[Strategy, ...]
    reason: str


@dataclass(slots=True, frozen=True)
class ContractScoreResult:
    strategy: Strategy
    contract: OptionContractInput
    base_score: int
    score: int
    factors: tuple[ScoreFactor, ...]
    penalties: tuple[SoftPenalty, ...]
    vetoes: tuple[HardVeto, ...]
    breakeven: Decimal | None
    breakeven_move_percent: Decimal | None
    liquidity_score: int
    expiry_days_after_earnings: int | None
    reasons: tuple[str, ...]

    @property
    def is_viable(self) -> bool:
        return not self.vetoes and self.score > 0


@dataclass(slots=True, frozen=True)
class CandidateEvaluation:
    ticker: str
    direction: DirectionResult
    confidence: DataConfidenceResult
    strategy_selection: StrategySelection
    considered_contracts: tuple[ContractScoreResult, ...]
    chosen_contract: ContractScoreResult | None
    final_score: int
    action: DecisionAction
    reasons: tuple[str, ...]


def clamp_int(value: int, lower: int = 0, upper: int = 100) -> int:
    return max(lower, min(upper, value))


def round_decimal(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def risk_percent(user: UserContext) -> Decimal:
    if user.custom_risk_percent is not None and user.custom_risk_percent > ZERO:
        return user.custom_risk_percent
    return RISK_PROFILE_PCTS[user.risk_profile]


def option_mid(contract: OptionContractInput) -> Decimal | None:
    if contract.mid is not None and contract.mid > ZERO:
        return contract.mid
    if (
        contract.bid is not None
        and contract.ask is not None
        and contract.bid >= ZERO
        and contract.ask >= ZERO
    ):
        return (contract.bid + contract.ask) / Decimal("2")
    if contract.ask is not None and contract.ask > ZERO:
        return contract.ask
    if contract.bid is not None and contract.bid > ZERO:
        return contract.bid
    return None


def option_premium(contract: OptionContractInput) -> Decimal | None:
    if contract.position_side == "long":
        if contract.ask is not None and contract.ask > ZERO:
            return contract.ask
        return option_mid(contract)
    if contract.bid is not None and contract.bid > ZERO:
        return contract.bid
    return option_mid(contract)


def absolute_spread(contract: OptionContractInput) -> Decimal | None:
    if contract.bid is None or contract.ask is None:
        return None
    return contract.ask - contract.bid


def spread_percent(contract: OptionContractInput) -> Decimal | None:
    spread = absolute_spread(contract)
    mid = option_mid(contract)
    if spread is None or mid is None or mid <= ZERO:
        return None
    return spread / mid


def preferred_absolute_spread_limit(premium: Decimal | None) -> Decimal:
    if premium is None or premium < Decimal("0.50"):
        return Decimal("0.10")
    if premium <= Decimal("2.00"):
        return Decimal("0.25")
    return Decimal("0.50")


def breakeven_price(contract: OptionContractInput) -> Decimal | None:
    premium = option_premium(contract)
    if premium is None:
        return None
    if contract.strategy == "long_call":
        return contract.strike + premium
    if contract.strategy == "long_put":
        return contract.strike - premium
    if contract.strategy == "short_put":
        return contract.strike - premium
    return contract.strike + premium


def breakeven_move_percent(
    contract: OptionContractInput, current_price: Decimal | None
) -> Decimal | None:
    breakeven = breakeven_price(contract)
    if breakeven is None or current_price is None or current_price <= ZERO:
        return None
    return abs(breakeven - current_price) / current_price


def estimate_max_contracts(user: UserContext, contract: OptionContractInput) -> int:
    if user.account_size <= ZERO or user.max_contracts <= 0:
        return 0

    if contract.position_side == "long":
        premium = option_premium(contract)
        if premium is None or premium <= ZERO:
            return 0
        if user.max_option_premium is not None and premium > user.max_option_premium:
            return 0
        trade_budget = user.account_size * risk_percent(user)
        if trade_budget <= ZERO:
            return 0
        contracts = int(trade_budget // (premium * HUNDRED))
    else:
        exposure_cap = user.account_size * SHORT_NOTIONAL_CAP_PCTS[user.risk_profile]
        if exposure_cap <= ZERO or contract.strike <= ZERO:
            return 0
        contracts = int(exposure_cap // (contract.strike * HUNDRED))

    return max(0, min(user.max_contracts, contracts))

