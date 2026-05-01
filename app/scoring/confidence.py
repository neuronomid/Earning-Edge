from __future__ import annotations

from app.scoring.types import (
    CandidateContext,
    DataConfidenceResult,
    OptionContractInput,
    UserContext,
    clamp_int,
    option_premium,
    spread_percent,
)


def compute_data_confidence(
    candidate: CandidateContext,
    user: UserContext,
    *,
    selected_contract: OptionContractInput | None = None,
    require_selected_contract: bool = False,
) -> DataConfidenceResult:
    notes: list[str] = []
    blockers: list[str] = []

    identity_score = 15 if candidate.identity_verified and candidate.ticker.strip() else 8

    if not candidate.ticker.strip():
        blockers.append("Ticker is missing.")
        identity_score = 0

    if candidate.verified_earnings_date:
        earnings_score = 20
    else:
        earnings_score = 12
        blockers.append("Earnings date could not be verified.")

    market_score = 15
    if candidate.market_snapshot.current_price is None:
        market_score = 0
        blockers.append("Current price is unavailable.")
    elif candidate.market_snapshot.as_of_date is None:
        market_score = 10
        notes.append("Market snapshot has no as-of date.")
    elif candidate.market_snapshot.latest_volume is None:
        market_score = 12
        notes.append("Market snapshot has no fresh volume reading.")

    options_score = _options_data_score(candidate, selected_contract, notes)
    cross_source_score = _cross_source_score(candidate, notes)
    news_score = _news_score(candidate, notes)
    calculation_score = _calculation_score(candidate, notes)

    raw_score = (
        identity_score
        + earnings_score
        + market_score
        + options_score
        + cross_source_score
        + news_score
        + calculation_score
        + candidate.market_snapshot.confidence_adjustment
    )

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

    deduped_notes = tuple(dict.fromkeys(notes))
    deduped_blockers = tuple(dict.fromkeys(blockers))
    return DataConfidenceResult(
        score=score,
        label=label,
        blockers=deduped_blockers,
        notes=deduped_notes,
    )


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

    premium = option_premium(contract)
    if premium is not None:
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

    return clamp_int(score, lower=0, upper=20)


def _cross_source_score(candidate: CandidateContext, notes: list[str]) -> int:
    if not candidate.source_conflicts:
        return 10

    severe = any(conflict.severity == "severe" for conflict in candidate.source_conflicts)
    moderate = any(conflict.severity == "moderate" for conflict in candidate.source_conflicts)
    for conflict in candidate.source_conflicts:
        notes.append(f"{conflict.field}: {conflict.detail}")

    if severe:
        return 2
    if moderate:
        return 6
    return 8


def _news_score(candidate: CandidateContext, notes: list[str]) -> int:
    confidence = candidate.news_brief.news_confidence
    if confidence >= 70:
        return 10
    if confidence >= 55:
        return 8
    if confidence >= 40:
        return 6
    notes.append("News coverage was thin, so catalyst confidence is reduced.")
    return 4


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
