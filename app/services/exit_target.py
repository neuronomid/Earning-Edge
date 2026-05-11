from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.scoring.types import (
    ZERO,
    CandidateContext,
    DirectionResult,
    ExitTarget,
    ExtendedTargetMethod,
    OptionContractInput,
    option_mid,
    option_premium,
)

ONE = Decimal("1")
HUNDRED = Decimal("100")
SHORT_PREMIUM_PROFIT_TARGET = Decimal("0.50")
SHORT_PREMIUM_STOP_LOSS_MULTIPLE = Decimal("3.00")
SHORT_CALL_UNDERLYING_STOP_BUFFER = Decimal("1.02")
DEFAULT_SHORT_CALL_DELTA = Decimal("0.30")
LONG_STOP_LOSS_FRACTION = Decimal("0.50")
LONG_MIN_TARGET_MULTIPLE = Decimal("1.20")
LONG_MIN_PROJECTED_MULTIPLE = Decimal("1.08")


@dataclass(slots=True, frozen=True)
class ExitTargetService:
    def build(
        self,
        candidate: CandidateContext,
        contract: OptionContractInput,
        direction: DirectionResult,
    ) -> ExitTarget | None:
        current_price = candidate.market_snapshot.current_price
        current_mid = option_mid(contract)
        entry_price = option_premium(contract)
        if (
            current_price is None
            or current_price <= ZERO
            or current_mid is None
            or current_mid <= ZERO
            or entry_price is None
            or entry_price <= ZERO
        ):
            return None

        valuation_date = (
            candidate.valuation_date
            or candidate.market_snapshot.as_of_date
            or date.today()
        )
        if contract.expiry <= valuation_date:
            return None

        if contract.position_side == "short":
            return _short_premium_target(
                candidate=candidate,
                contract=contract,
                valuation_date=valuation_date,
                current_price=current_price,
                current_mid=current_mid,
                entry_credit=entry_price,
            )

        days_to_expiry = max((contract.expiry - valuation_date).days, 1)
        planned_holding_days = _planned_holding_days(
            valuation_date=valuation_date,
            expiry=contract.expiry,
            earnings_date=candidate.earnings_date,
        )
        exit_by_date = valuation_date + timedelta(days=planned_holding_days)
        target_pricing_days = _target_pricing_days(planned_holding_days)
        move_fraction = _expected_move_fraction(candidate, contract, days_to_expiry)
        if move_fraction is None or move_fraction <= ZERO:
            return None

        conviction = _conviction_fraction(direction.score)
        stock_move = current_price * move_fraction * conviction
        if stock_move <= ZERO:
            return None

        if contract.option_type == "call":
            target_stock_price = current_price + stock_move
        else:
            target_stock_price = max(Decimal("0.01"), current_price - stock_move)

        earnings_cross = (
            candidate.earnings_date is not None
            and valuation_date <= candidate.earnings_date <= contract.expiry
        )
        expected_iv_change = _expected_iv_change(contract, earnings_cross)

        target_option_price: Decimal
        target_method: ExtendedTargetMethod
        if _has_full_greeks(contract):
            target_option_price = (
                current_mid
                + (contract.delta or ZERO) * (target_stock_price - current_price)
                + Decimal("0.5")
                * (contract.gamma or ZERO)
                * (target_stock_price - current_price) ** 2
                + (contract.theta or ZERO) * Decimal(target_pricing_days)
                + (contract.vega or ZERO) * (expected_iv_change or ZERO)
            )
            target_method = "full_greeks"
        elif contract.delta is not None:
            projected = current_mid + contract.delta * (target_stock_price - current_price)
            target_option_price = _apply_earnings_profit_haircut(
                current_mid=current_mid,
                projected=projected,
                earnings_cross=earnings_cross,
            )
            target_method = "delta_fallback"
        else:
            target_option_price = _intrinsic_target_price(
                contract=contract,
                current_price=current_price,
                current_mid=current_mid,
                target_stock_price=target_stock_price,
                earnings_cross=earnings_cross,
            )
            target_method = "intrinsic_fallback"

        target_option_price = max(Decimal("0.01"), target_option_price.quantize(Decimal("0.01")))
        target_option_price = _realistic_long_target(
            target_option_price=target_option_price,
            entry_price=entry_price,
        )
        if target_option_price is None:
            return None
        stop_loss_option_price = max(
            Decimal("0.01"),
            (entry_price * LONG_STOP_LOSS_FRACTION).quantize(Decimal("0.01")),
        )
        target_gain_percent = None
        if entry_price > ZERO:
            target_gain_percent = (
                ((target_option_price - entry_price) / entry_price) * HUNDRED
            ).quantize(Decimal("0.01"))

        return ExitTarget(
            target_stock_price=target_stock_price.quantize(Decimal("0.01")),
            target_option_price=target_option_price,
            target_gain_percent=target_gain_percent,
            stop_loss_option_price=stop_loss_option_price,
            exit_by_date=exit_by_date,
            expected_holding_days=planned_holding_days,
            target_method=target_method,
            expected_iv_change=expected_iv_change,
        )


def _has_full_greeks(contract: OptionContractInput) -> bool:
    return (
        contract.delta is not None
        and contract.gamma is not None
        and contract.theta is not None
        and contract.vega is not None
        and contract.implied_volatility is not None
        and option_mid(contract) is not None
    )


def _expected_move_fraction(
    candidate: CandidateContext,
    contract: OptionContractInput,
    days_to_expiry: int,
) -> Decimal | None:
    if candidate.expected_move_percent is not None and abs(candidate.expected_move_percent) > ZERO:
        return abs(candidate.expected_move_percent)
    iv = contract.implied_volatility
    if iv is None or iv <= ZERO:
        return None
    return iv * (_decimal_sqrt(Decimal(days_to_expiry) / Decimal("365")))


def _conviction_fraction(direction_score: int) -> Decimal:
    if direction_score >= 75:
        return ONE
    if direction_score >= 60:
        return Decimal("0.65")
    return Decimal("0.40")


def _planned_holding_days(
    *,
    valuation_date: date,
    expiry: date,
    earnings_date: date | None,
) -> int:
    latest_safe_exit = expiry - timedelta(days=5)
    if latest_safe_exit <= valuation_date:
        return max((expiry - valuation_date).days - 1, 1)
    max_days = max((latest_safe_exit - valuation_date).days, 1)
    if earnings_date is not None and valuation_date <= earnings_date <= expiry:
        return max(1, min(max_days, max((earnings_date - valuation_date).days, 1)))
    return min(max_days, 7)


def _target_pricing_days(planned_holding_days: int) -> int:
    return max(1, min(planned_holding_days, 2))


def _realistic_long_target(
    *,
    target_option_price: Decimal,
    entry_price: Decimal,
) -> Decimal | None:
    if target_option_price < (entry_price * LONG_MIN_PROJECTED_MULTIPLE):
        return None
    return max(
        target_option_price,
        (entry_price * LONG_MIN_TARGET_MULTIPLE).quantize(Decimal("0.01")),
    )


def _short_premium_target(
    *,
    candidate: CandidateContext,
    contract: OptionContractInput,
    valuation_date: date,
    current_price: Decimal,
    current_mid: Decimal,
    entry_credit: Decimal,
) -> ExitTarget | None:
    planned_holding_days = _planned_holding_days(
        valuation_date=valuation_date,
        expiry=contract.expiry,
        earnings_date=candidate.earnings_date,
    )
    target_option_price = max(
        Decimal("0.01"),
        (entry_credit * SHORT_PREMIUM_PROFIT_TARGET).quantize(Decimal("0.01")),
    )
    target_gain_percent = ((entry_credit - target_option_price) / entry_credit * HUNDRED).quantize(
        Decimal("0.01")
    )
    stop_loss_option_price = (entry_credit * SHORT_PREMIUM_STOP_LOSS_MULTIPLE).quantize(
        Decimal("0.01")
    )
    underlying_stop_price = None
    target_method: ExtendedTargetMethod = "short_premium"

    if contract.strategy == "short_call":
        underlying_stop_price = (contract.strike * SHORT_CALL_UNDERLYING_STOP_BUFFER).quantize(
            Decimal("0.01")
        )
        adverse_move = max(underlying_stop_price - current_price, ZERO)
        delta = abs(contract.delta) if contract.delta is not None else DEFAULT_SHORT_CALL_DELTA
        option_stop = current_mid + (delta * adverse_move)
        stop_loss_option_price = max(
            Decimal("0.01"),
            option_stop.quantize(Decimal("0.01")),
        )
        target_method = "short_call_underlying"

    return ExitTarget(
        target_stock_price=None,
        target_option_price=target_option_price,
        target_gain_percent=target_gain_percent,
        stop_loss_option_price=stop_loss_option_price,
        exit_by_date=valuation_date + timedelta(days=planned_holding_days),
        expected_holding_days=planned_holding_days,
        target_method=target_method,
        expected_iv_change=Decimal("0.00"),
        underlying_stop_price=underlying_stop_price,
    )


def _expected_iv_change(contract: OptionContractInput, earnings_cross: bool) -> Decimal | None:
    if contract.implied_volatility is None:
        return None
    if not earnings_cross:
        return Decimal("0.00")
    return -(contract.implied_volatility * Decimal("0.25")).quantize(Decimal("0.000001"))


def _apply_earnings_profit_haircut(
    *,
    current_mid: Decimal,
    projected: Decimal,
    earnings_cross: bool,
) -> Decimal:
    if not earnings_cross:
        return projected
    profit = projected - current_mid
    haircut = profit * Decimal("0.75")
    return current_mid + haircut


def _intrinsic_target_price(
    *,
    contract: OptionContractInput,
    current_price: Decimal,
    current_mid: Decimal,
    target_stock_price: Decimal,
    earnings_cross: bool,
) -> Decimal:
    if contract.option_type == "call":
        target_intrinsic = max(target_stock_price - contract.strike, ZERO)
        current_intrinsic = max(current_price - contract.strike, ZERO)
    else:
        target_intrinsic = max(contract.strike - target_stock_price, ZERO)
        current_intrinsic = max(contract.strike - current_price, ZERO)
    current_extrinsic = max(current_mid - current_intrinsic, ZERO)
    retention = Decimal("0.50") if earnings_cross else Decimal("0.75")
    return target_intrinsic + (current_extrinsic * retention)


def _decimal_sqrt(value: Decimal) -> Decimal:
    if value <= ZERO:
        return ZERO
    return value.sqrt() if hasattr(value, "sqrt") else value ** Decimal("0.5")
