from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings
from app.scoring.strategy_policy import NO_EARNINGS_REQUIRED_STRATEGIES
from app.scoring.types import (
    CandidateContext,
    DataConfidenceResult,
    OptionContractInput,
    StrategySource,
    UserContext,
    clamp_int,
    option_premium,
    spread_percent,
)

# Maximum raw score each component can produce.
_MAX_IDENTITY: int = 15
_MAX_EARNINGS: int = 20
_MAX_EVENT: int = 20
_MAX_MARKET: int = 15
_MAX_OPTIONS: int = 20
_MAX_CROSS_SOURCE: int = 10
_MAX_CALCULATION: int = 10


@dataclass(frozen=True, slots=True)
class ConfidenceWeights:
    identity: float
    earnings: float
    event: float
    market: float
    options: float
    cross_source: float
    calculation: float


# Not renormalized: max raw confidence is 97 by design (see PLAN_News §8.2).
_LEGACY_CONFIDENCE = ConfidenceWeights(
    identity=0.13,
    earnings=0.25,
    event=0.00,
    market=0.20,
    options=0.22,
    cross_source=0.10,
    calculation=0.07,
)
_V2_CONFIDENCE: dict[StrategySource, ConfidenceWeights] = {
    "catalyst_confluence": ConfidenceWeights(0.13, 0.25, 0.00, 0.20, 0.22, 0.10, 0.07),
    "coiled_setup": ConfidenceWeights(0.13, 0.00, 0.20, 0.25, 0.22, 0.10, 0.07),
    "pead_continuation": ConfidenceWeights(0.13, 0.20, 0.05, 0.22, 0.22, 0.10, 0.05),
    "sector_relative_strength": ConfidenceWeights(0.13, 0.00, 0.20, 0.25, 0.22, 0.10, 0.07),
    "activist_13d_followthrough": ConfidenceWeights(
        0.13,
        0.00,
        0.20,
        0.22,
        0.22,
        0.10,
        0.10,
    ),
}


def compute_data_confidence(
    candidate: CandidateContext,
    user: UserContext,
    *,
    selected_contract: OptionContractInput | None = None,
    require_selected_contract: bool = False,
) -> DataConfidenceResult:
    notes: list[str] = []
    blockers: list[str] = []
    weights = _confidence_weights(candidate.strategy_source)

    # --- raw component scores (same logic as before) ---
    identity_score = _identity_score(candidate, blockers)
    earnings_score = _earnings_score(candidate, blockers)
    event_score = _event_score(candidate)
    market_score = _market_score(candidate, blockers)
    options_score = _options_data_score(candidate, selected_contract, notes)
    cross_source_score = _cross_source_score(candidate, notes)
    calculation_score = _calculation_score(candidate, notes)

    # --- normalize each component to [0, 1] then apply weight ---
    weighted = (
        (identity_score / _MAX_IDENTITY) * weights.identity
        + (earnings_score / _MAX_EARNINGS) * weights.earnings
        + (event_score / _MAX_EVENT) * weights.event
        + (market_score / _MAX_MARKET) * weights.market
        + (options_score / _MAX_OPTIONS) * weights.options
        + (cross_source_score / _MAX_CROSS_SOURCE) * weights.cross_source
        + (calculation_score / _MAX_CALCULATION) * weights.calculation
    )

    raw_score = round(weighted * 100) + candidate.market_snapshot.confidence_adjustment

    if require_selected_contract:
        blockers.extend(_contract_blockers(selected_contract))
    if user.account_size <= 0:
        blockers.append("User account size is unavailable.")
    if not user.has_valid_openrouter_api_key:
        blockers.append("OpenRouter API key is unavailable or invalid.")

    score = clamp_int(raw_score)
    if score >= 85:
        label = "strong"
    elif score >= 70:
        label = "good"
    elif score >= 55:
        label = "partial"
    elif score >= 40:
        label = "weak"
    else:
        label = "critical"

    for note in candidate.market_snapshot.confidence_notes:
        notes.append(f"{note.field}: {note.detail}")

    return DataConfidenceResult(
        score=score,
        label=label,
        blockers=tuple(dict.fromkeys(blockers)),
        notes=tuple(dict.fromkeys(notes)),
    )


def _confidence_weights(strategy_source: StrategySource) -> ConfidenceWeights:
    if not get_settings().scoring_fairness_v2:
        return _LEGACY_CONFIDENCE
    return _V2_CONFIDENCE[strategy_source]


def _identity_score(candidate: CandidateContext, blockers: list[str]) -> int:
    if not candidate.ticker.strip():
        blockers.append("Ticker is missing.")
        return 0
    return 15 if candidate.identity_verified else 8


def _earnings_score(candidate: CandidateContext, blockers: list[str]) -> int:
    if candidate.earnings_date is None:
        if candidate.strategy_source in NO_EARNINGS_REQUIRED_STRATEGIES:
            return 20
        blockers.append("Earnings date is unavailable.")
        return 0
    if candidate.verified_earnings_date:
        return 20
    blockers.append("Earnings date could not be verified.")
    return 12


def _event_score(candidate: CandidateContext) -> int:
    if candidate.event_signal is None:
        return 0
    clamped_score = max(0, min(100, candidate.event_signal.score))
    return round((clamped_score / 100) * _MAX_EVENT)


def _market_score(candidate: CandidateContext, blockers: list[str]) -> int:
    if candidate.market_snapshot.current_price is None:
        blockers.append("Current price is unavailable.")
        return 0
    if candidate.market_snapshot.as_of_date is None:
        return 10
    if candidate.market_snapshot.latest_volume is None:
        return 12
    return 15


def _options_data_score(
    candidate: CandidateContext,
    selected_contract: OptionContractInput | None,
    notes: list[str],
) -> int:
    chain = candidate.option_chain
    if not chain:
        notes.append("Option chain is unavailable.")
        return 0

    contract = selected_contract or max(chain, key=_completeness_proxy)
    score = 8

    if contract.strike > 0 and contract.expiry is not None:
        score += 4

    if option_premium(contract) is not None:
        score += 4

    if contract.volume is not None or contract.open_interest is not None:
        score += 2

    if contract.delta is not None or contract.implied_volatility is not None:
        score += 2
    else:
        notes.append("Greeks were unavailable, so moneyness and premium must stand in.")
        score -= 4

    if selected_contract is not None:
        spread = spread_percent(contract)
        if spread is not None and spread > 0.25:
            notes.append("Selected contract has a wide spread.")
            score -= 2
        if contract.source.lower() == "yfinance":
            notes.append("Selected contract relies on yfinance option data.")
            score -= 2

    return clamp_int(score, lower=0, upper=_MAX_OPTIONS)


def _cross_source_score(candidate: CandidateContext, notes: list[str]) -> int:
    if not candidate.source_conflicts:
        return 10
    severe = any(c.severity == "severe" for c in candidate.source_conflicts)
    moderate = any(c.severity == "moderate" for c in candidate.source_conflicts)
    for conflict in candidate.source_conflicts:
        notes.append(f"{conflict.field}: {conflict.detail}")
    if severe:
        return 2
    if moderate:
        return 6
    return 8


def _calculation_score(candidate: CandidateContext, notes: list[str]) -> int:
    if not candidate.calculation_errors:
        return 10
    notes.extend(candidate.calculation_errors)
    return 4


def _contract_blockers(selected_contract: OptionContractInput | None) -> tuple[str, ...]:
    if selected_contract is None:
        return ("No usable option contract was selected.",)
    blockers: list[str] = []
    if not selected_contract.option_type:
        blockers.append("Contract type is unavailable.")
    if not selected_contract.position_side:
        blockers.append("Position side is unavailable.")
    if selected_contract.strike <= 0:
        blockers.append("Strike is unavailable.")
    if selected_contract.expiry is None:
        blockers.append("Expiry is unavailable.")
    if option_premium(selected_contract) is None:
        blockers.append("Usable bid/ask or mid pricing is unavailable.")
    return tuple(blockers)


def _completeness_proxy(contract: OptionContractInput) -> int:
    score = 0
    if contract.bid is not None or contract.ask is not None or contract.mid is not None:
        score += 4
    if contract.volume is not None:
        score += 2
    if contract.open_interest is not None:
        score += 2
    if contract.implied_volatility is not None:
        score += 1
    if contract.delta is not None:
        score += 1
    return score
