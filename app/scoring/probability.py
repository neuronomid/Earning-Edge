from __future__ import annotations

from datetime import date
from decimal import Decimal
from math import erf, sqrt

from app.scoring.types import (
    ONE,
    ZERO,
    CandidateContext,
    ExitTarget,
    OptionContractInput,
    OptionRealityCheck,
    breakeven_price,
)
from app.services.market_hours import (
    is_trading_session,
    trading_sessions_after_until,
)

TRADING_DAYS_PER_YEAR = Decimal("252")
CATALYST_STRATEGIES = frozenset(
    {
        "catalyst_confluence",
        "pead_continuation",
        "activist_13d_followthrough",
    }
)


def assess_option_reality(
    candidate: CandidateContext,
    contract: OptionContractInput,
    exit_target: ExitTarget | None,
) -> OptionRealityCheck:
    valuation_date = (
        candidate.valuation_date
        or candidate.market_snapshot.as_of_date
        or date.today()
    )
    dte_calendar = max((contract.expiry - valuation_date).days, 0)
    dte_trading_sessions = len(trading_sessions_after_until(valuation_date, contract.expiry))
    exit_by = exit_target.exit_by_date if exit_target is not None else valuation_date
    exit_is_session = is_trading_session(exit_by)
    trading_days_to_exit = len(trading_sessions_after_until(valuation_date, exit_by))

    current_price = candidate.market_snapshot.current_price or contract.underlying_price
    expected_move_to_exit = _expected_move_to_exit(candidate, contract, trading_days_to_exit)
    sigma_percent = _sigma_percent(contract, trading_days_to_exit)

    target_stock = None if exit_target is None else exit_target.target_stock_price
    required_sigma_to_strike = _required_sigma_for_price(
        current_price,
        contract.strike,
        sigma_percent,
    )
    required_sigma_to_breakeven = _required_sigma_for_price(
        current_price,
        breakeven_price(contract),
        sigma_percent,
    )
    required_sigma_to_target = _required_sigma_for_price(
        current_price,
        target_stock,
        sigma_percent,
    )
    approx_touch = _probability_touch(required_sigma_to_target)
    approx_itm = _probability_expire_itm(contract, current_price, sigma_percent)
    theta_cost = None
    if contract.theta is not None:
        theta_cost = (abs(contract.theta) * Decimal(max(trading_days_to_exit, 1))).quantize(
            Decimal("0.0001")
        )
    has_named_catalyst = _has_named_catalyst_before_exit(
        candidate,
        valuation_date=valuation_date,
        exit_by_date=exit_by,
    )

    flags = _reality_flags(
        candidate=candidate,
        contract=contract,
        dte_calendar=dte_calendar,
        trading_days_to_exit=trading_days_to_exit,
        exit_is_session=exit_is_session,
        has_named_catalyst=has_named_catalyst,
        required_sigma_to_breakeven=required_sigma_to_breakeven,
        required_sigma_to_target=required_sigma_to_target,
        approx_probability_touch_target=approx_touch,
        expected_move_to_exit_percent=expected_move_to_exit,
    )

    return OptionRealityCheck(
        dte_calendar=dte_calendar,
        dte_trading_sessions=dte_trading_sessions,
        trading_days_to_exit=trading_days_to_exit,
        exit_is_trading_session=exit_is_session,
        expected_move_to_exit_percent=expected_move_to_exit,
        required_sigma_to_strike=required_sigma_to_strike,
        required_sigma_to_breakeven=required_sigma_to_breakeven,
        required_sigma_to_target=required_sigma_to_target,
        approx_probability_touch_target=approx_touch,
        approx_probability_expire_itm=approx_itm,
        theta_cost_to_exit=theta_cost,
        has_named_catalyst_before_exit=has_named_catalyst,
        flags=flags,
    )


def _expected_move_to_exit(
    candidate: CandidateContext,
    contract: OptionContractInput,
    trading_days_to_exit: int,
) -> Decimal | None:
    if trading_days_to_exit <= 0:
        return ZERO
    if contract.implied_volatility is not None and contract.implied_volatility > ZERO:
        return (
            contract.implied_volatility
            * (Decimal(trading_days_to_exit) / TRADING_DAYS_PER_YEAR).sqrt()
        ).quantize(Decimal("0.000001"))
    if candidate.expected_move_percent is None or candidate.expected_move_percent <= ZERO:
        return None
    valuation_date = candidate.valuation_date or candidate.market_snapshot.as_of_date
    if valuation_date is None:
        return abs(candidate.expected_move_percent)
    dte_trading = len(trading_sessions_after_until(valuation_date, contract.expiry))
    if dte_trading <= 0:
        return abs(candidate.expected_move_percent)
    scale = (Decimal(trading_days_to_exit) / Decimal(dte_trading)).sqrt()
    return (abs(candidate.expected_move_percent) * scale).quantize(Decimal("0.000001"))


def _sigma_percent(contract: OptionContractInput, trading_days: int) -> Decimal | None:
    if contract.implied_volatility is None or contract.implied_volatility <= ZERO:
        return None
    return contract.implied_volatility * (
        Decimal(max(trading_days, 1)) / TRADING_DAYS_PER_YEAR
    ).sqrt()


def _required_sigma_for_price(
    current_price: Decimal | None,
    target_price: Decimal | None,
    sigma_percent: Decimal | None,
) -> Decimal | None:
    if (
        current_price is None
        or current_price <= ZERO
        or target_price is None
        or target_price <= ZERO
        or sigma_percent is None
        or sigma_percent <= ZERO
    ):
        return None
    return (abs(target_price - current_price) / current_price / sigma_percent).quantize(
        Decimal("0.01")
    )


def _probability_touch(required_sigma: Decimal | None) -> Decimal | None:
    if required_sigma is None:
        return None
    sigma = max(float(required_sigma), 0.0)
    probability = max(0.0, min(1.0, 2.0 * (1.0 - _normal_cdf(sigma))))
    return Decimal(str(probability)).quantize(Decimal("0.0001"))


def _probability_expire_itm(
    contract: OptionContractInput,
    current_price: Decimal | None,
    sigma_percent: Decimal | None,
) -> Decimal | None:
    if contract.delta is not None:
        return min(ONE, max(ZERO, abs(contract.delta))).quantize(Decimal("0.0001"))
    required = _required_sigma_for_price(current_price, contract.strike, sigma_percent)
    if required is None:
        return None
    probability = 1.0 - _normal_cdf(float(required))
    return Decimal(str(max(0.0, min(1.0, probability)))).quantize(Decimal("0.0001"))


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def _has_named_catalyst_before_exit(
    candidate: CandidateContext,
    *,
    valuation_date: date,
    exit_by_date: date,
) -> bool:
    if (
        candidate.earnings_date is not None
        and valuation_date <= candidate.earnings_date <= exit_by_date
    ):
        return True
    if candidate.strategy_source not in CATALYST_STRATEGIES:
        return False
    return bool(candidate.event_signal and candidate.event_signal.is_supportive)


def _reality_flags(
    *,
    candidate: CandidateContext,
    contract: OptionContractInput,
    dte_calendar: int,
    trading_days_to_exit: int,
    exit_is_session: bool,
    has_named_catalyst: bool,
    required_sigma_to_breakeven: Decimal | None,
    required_sigma_to_target: Decimal | None,
    approx_probability_touch_target: Decimal | None,
    expected_move_to_exit_percent: Decimal | None,
) -> tuple[str, ...]:
    flags: list[str] = []

    if not exit_is_session:
        flags.append("invalid_exit_session")
    if trading_days_to_exit <= 0:
        flags.append("no_actionable_exit_window")

    is_long_otm = _is_long_otm(contract)
    no_named_catalyst = not has_named_catalyst
    if contract.position_side == "long" and no_named_catalyst:
        if dte_calendar < 10 and is_long_otm:
            flags.append("weekly_otm_no_catalyst")
        if trading_days_to_exit < 3:
            flags.append("too_few_exit_sessions_no_catalyst")

    if no_named_catalyst and candidate.strategy_source in {
        "coiled_setup",
        "sector_relative_strength",
        "activist_13d_followthrough",
    }:
        if required_sigma_to_target is not None and required_sigma_to_target > Decimal("1.00"):
            flags.append("target_unreachable_by_exit")
        if (
            approx_probability_touch_target is not None
            and approx_probability_touch_target < Decimal("0.35")
        ):
            flags.append("low_pot_no_catalyst")
        if (
            required_sigma_to_breakeven is not None
            and required_sigma_to_breakeven > Decimal("1.00")
        ):
            flags.append("breakeven_outside_exit_move")
        if expected_move_to_exit_percent == ZERO:
            flags.append("missing_exit_horizon_move")

    return tuple(dict.fromkeys(flags))


def _is_long_otm(contract: OptionContractInput) -> bool:
    underlying = contract.underlying_price
    if contract.position_side != "long" or underlying is None or underlying <= ZERO:
        return False
    if contract.option_type == "call":
        return contract.strike > underlying
    return contract.strike < underlying
