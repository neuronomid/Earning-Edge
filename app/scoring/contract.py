from __future__ import annotations

from decimal import Decimal

from app.scoring.expiry import days_after_earnings, score_expiry_fit
from app.scoring.penalties import collect_soft_penalties
from app.scoring.types import (
    CandidateContext,
    ContractScoreResult,
    DirectionResult,
    OptionContractInput,
    ScoreFactor,
    UserContext,
    breakeven_move_percent,
    breakeven_price,
    clamp_int,
    estimate_max_contracts,
    option_premium,
    risk_percent,
    round_decimal,
    spread_percent,
)
from app.scoring.vetoes import evaluate_hard_vetoes

ZERO = Decimal("0")


def score_contract(
    candidate: CandidateContext,
    user: UserContext,
    contract: OptionContractInput,
    direction: DirectionResult,
) -> ContractScoreResult:
    current_price = candidate.market_snapshot.current_price
    factors = (
        ScoreFactor(
            "breakeven feasibility",
            _score_breakeven(candidate, contract),
            20,
            "breakeven was compared against expected and historical earnings moves",
        ),
        ScoreFactor(
            "option liquidity",
            round_decimal(Decimal("15") * Decimal(liquidity_quality(contract)) / Decimal("100")),
            15,
            "liquidity blends open interest, same-day volume, and spread quality",
        ),
        ScoreFactor(
            "expiry fit",
            score_expiry_fit(
                contract.expiry,
                candidate.earnings_date,
                candidate.earnings_timing,
                contract.strategy,
                user.risk_profile,
            ),
            15,
            "expiry fit checks the earnings timing rule and preferred holding window",
        ),
        ScoreFactor(
            "strike/moneyness fit",
            _score_strike_fit(contract, current_price),
            15,
            "strike fit follows PRD delta and moneyness guidance",
        ),
        ScoreFactor(
            "IV setup",
            _score_iv_setup(contract),
            15,
            "IV setup prefers reasonable vol for longs and rich vol for shorts",
        ),
        ScoreFactor(
            "premium/risk fit",
            _score_premium_fit(user, contract),
            10,
            "premium fit checks budget pressure and estimated contract capacity",
        ),
        ScoreFactor(
            "direction compatibility",
            _score_direction_fit(direction, contract),
            10,
            "direction compatibility checks that the contract matches the thesis strength",
        ),
    )

    base_score = sum(factor.score for factor in factors)
    penalties = collect_soft_penalties(candidate, user, contract, direction)
    vetoes = evaluate_hard_vetoes(candidate, user, contract)
    penalty_total = sum(penalty.score_delta for penalty in penalties)
    final_score = 0 if vetoes else clamp_int(base_score + penalty_total)

    reasons = (
        tuple(factor.detail for factor in factors if factor.score >= factor.weight // 2)
        + tuple(penalty.reason for penalty in penalties)
    )
    return ContractScoreResult(
        strategy=contract.strategy,
        contract=contract,
        base_score=base_score,
        score=final_score,
        factors=factors,
        penalties=penalties,
        vetoes=vetoes,
        breakeven=breakeven_price(contract),
        breakeven_move_percent=breakeven_move_percent(contract, current_price),
        liquidity_score=liquidity_quality(contract),
        expiry_days_after_earnings=days_after_earnings(contract.expiry, candidate.earnings_date),
        reasons=reasons,
    )


def liquidity_quality(contract: OptionContractInput) -> int:
    score = 0
    open_interest = contract.open_interest or 0
    volume = contract.volume or 0
    spread = spread_percent(contract)

    if open_interest >= 100:
        score += 35
    elif open_interest >= 50:
        score += 25
    elif open_interest > 0:
        score += 10

    if volume >= 25:
        score += 30
    elif volume >= 20:
        score += 24
    elif volume > 0:
        score += 10

    premium = option_premium(contract)
    if spread is not None:
        if spread <= Decimal("0.15"):
            score += 35
        elif spread <= Decimal("0.25"):
            score += 25
        elif spread <= Decimal("0.35"):
            score += 10
    elif premium is not None and premium > ZERO:
        score += 15

    return clamp_int(score)


def _score_breakeven(candidate: CandidateContext, contract: OptionContractInput) -> int:
    current_price = candidate.market_snapshot.current_price
    required_move = breakeven_move_percent(contract, current_price)
    if required_move is None:
        return 0

    context_move = _context_move(candidate)
    if contract.position_side == "long":
        if context_move is None or context_move <= ZERO:
            unit = _fallback_long_breakeven_unit(required_move)
        else:
            ratio = context_move / max(required_move, Decimal("0.0001"))
            if ratio >= Decimal("1.25"):
                unit = Decimal("1")
            elif ratio >= Decimal("1.0"):
                unit = Decimal("0.8")
            elif ratio >= Decimal("0.85"):
                unit = Decimal("0.6")
            elif ratio >= Decimal("0.7"):
                unit = Decimal("0.4")
            else:
                unit = Decimal("0.2")
    else:
        buffer = _short_buffer_percent(contract, current_price)
        if context_move is None or context_move <= ZERO:
            unit = Decimal("1") if buffer >= Decimal("0.04") else Decimal("0.55")
        else:
            ratio = buffer / context_move
            if ratio >= Decimal("1.20"):
                unit = Decimal("1")
            elif ratio >= Decimal("1.0"):
                unit = Decimal("0.8")
            elif ratio >= Decimal("0.85"):
                unit = Decimal("0.6")
            else:
                unit = Decimal("0.3")

    return round_decimal(Decimal("20") * unit)


def _score_strike_fit(contract: OptionContractInput, current_price: Decimal | None) -> int:
    if current_price is None or current_price <= ZERO:
        return 0

    if contract.delta is not None:
        abs_delta = abs(contract.delta)
        if contract.position_side == "long":
            if Decimal("0.30") <= abs_delta <= Decimal("0.70"):
                return 15
            if Decimal("0.20") <= abs_delta <= Decimal("0.80"):
                return 11
            return 5
        if Decimal("0.15") <= abs_delta <= Decimal("0.40"):
            return 15
        if Decimal("0.10") <= abs_delta <= Decimal("0.50"):
            return 11
        return 5

    diff = (contract.strike - current_price) / current_price
    abs_diff = abs(diff)
    if contract.strategy in {"long_call", "long_put"}:
        if abs_diff <= Decimal("0.05"):
            return 15
        if abs_diff <= Decimal("0.10"):
            return 11
        return 4

    otm = _short_otm_distance(contract, current_price)
    if Decimal("0.02") <= otm <= Decimal("0.08"):
        return 15
    if Decimal("0.01") <= otm <= Decimal("0.12"):
        return 11
    return 4


def _score_iv_setup(contract: OptionContractInput) -> int:
    if contract.implied_volatility is None:
        return 8

    iv = contract.implied_volatility
    if contract.position_side == "long":
        if iv <= Decimal("0.40"):
            return 15
        if iv <= Decimal("0.60"):
            return 12
        if iv <= Decimal("0.80"):
            return 8
        return 4

    if iv >= Decimal("0.60"):
        return 15
    if iv >= Decimal("0.45"):
        return 12
    if iv >= Decimal("0.30"):
        return 8
    return 4


def _score_premium_fit(user: UserContext, contract: OptionContractInput) -> int:
    estimated_contracts = estimate_max_contracts(user, contract)
    if estimated_contracts >= 1:
        return 10

    if contract.position_side == "short":
        return 0

    premium = option_premium(contract)
    if premium is None or premium <= ZERO:
        return 0
    trade_budget = user.account_size * risk_percent(user)
    ratio = (premium * Decimal("100")) / trade_budget
    if ratio <= Decimal("1.25"):
        return 6
    if ratio <= Decimal("1.50"):
        return 3
    return 0


def _score_direction_fit(direction: DirectionResult, contract: OptionContractInput) -> int:
    if direction.classification == "neutral":
        return 3
    if direction.classification == "avoid":
        return 0
    if direction.score >= 80:
        return 10
    if direction.score >= 68:
        return 8
    if direction.score >= 55:
        return 6
    return 4


def _context_move(candidate: CandidateContext) -> Decimal | None:
    values = [
        (
            abs(candidate.expected_move_percent)
            if candidate.expected_move_percent is not None
            else None
        ),
        abs(candidate.previous_earnings_move_percent)
        if candidate.previous_earnings_move_percent is not None
        else None,
    ]
    observed = [value for value in values if value is not None and value > ZERO]
    if not observed:
        return None
    return max(observed)


def _fallback_long_breakeven_unit(required_move: Decimal) -> Decimal:
    if required_move <= Decimal("0.03"):
        return Decimal("0.9")
    if required_move <= Decimal("0.06"):
        return Decimal("0.7")
    if required_move <= Decimal("0.10"):
        return Decimal("0.5")
    return Decimal("0.25")


def _short_otm_distance(contract: OptionContractInput, current_price: Decimal) -> Decimal:
    if contract.strategy == "short_put":
        return max(ZERO, (current_price - contract.strike) / current_price)
    return max(ZERO, (contract.strike - current_price) / current_price)


def _short_buffer_percent(contract: OptionContractInput, current_price: Decimal | None) -> Decimal:
    if current_price is None or current_price <= ZERO:
        return ZERO
    breakeven = breakeven_price(contract)
    if breakeven is None:
        return ZERO
    if contract.strategy == "short_put":
        return max(ZERO, (current_price - breakeven) / current_price)
    return max(ZERO, (breakeven - current_price) / current_price)
