from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.scoring.types import EarningsTiming, RiskProfile, Strategy, round_decimal


def is_valid_expiry(
    expiry: date,
    earnings_date: date | None,
    earnings_timing: EarningsTiming,
    *,
    valuation_date: date | None = None,
) -> bool:
    if earnings_date is None:
        base_date = valuation_date or date.today()
        return base_date < expiry <= base_date + timedelta(days=45)
    if expiry < earnings_date:
        return False
    if expiry > earnings_date + timedelta(days=30):
        return False
    if expiry == earnings_date and earnings_timing != "BMO":
        return False
    return True


def days_after_earnings(expiry: date, earnings_date: date | None) -> int | None:
    if earnings_date is None:
        return None
    return (expiry - earnings_date).days


def score_expiry_fit(
    expiry: date,
    earnings_date: date | None,
    earnings_timing: EarningsTiming,
    strategy: Strategy,
    risk_profile: RiskProfile,
    *,
    valuation_date: date | None = None,
) -> int:
    if not is_valid_expiry(
        expiry,
        earnings_date,
        earnings_timing,
        valuation_date=valuation_date,
    ):
        return 0

    if earnings_date is None:
        base_date = valuation_date or date.today()
        days_to_expiry = max((expiry - base_date).days, 1)
        strategy_unit = _dte_strategy_preference(days_to_expiry, strategy)
        risk_unit = _risk_preference(days_to_expiry, risk_profile)
        combined = (strategy_unit * Decimal("0.65")) + (risk_unit * Decimal("0.35"))
        return round_decimal(Decimal("15") * combined)

    days = days_after_earnings(expiry, earnings_date)
    assert days is not None
    strategy_unit = _strategy_preference(days, strategy)
    risk_unit = _risk_preference(days, risk_profile)
    if days == 0 and earnings_timing == "BMO" and strategy.startswith("long"):
        strategy_unit = min(strategy_unit, Decimal("0.55"))

    combined = (strategy_unit * Decimal("0.65")) + (risk_unit * Decimal("0.35"))
    return round_decimal(Decimal("15") * combined)


def _dte_strategy_preference(days: int, strategy: Strategy) -> Decimal:
    if strategy.startswith("long"):
        if 7 <= days <= 30:
            return Decimal("1")
        if 3 <= days <= 6 or 31 <= days <= 45:
            return Decimal("0.65")
        return Decimal("0.40")

    if 7 <= days <= 30:
        return Decimal("1")
    if 1 <= days <= 6 or 31 <= days <= 45:
        return Decimal("0.65")
    return Decimal("0.40")


def _strategy_preference(days: int, strategy: Strategy) -> Decimal:
    if strategy.startswith("long"):
        if 3 <= days <= 21:
            return Decimal("1")
        if 1 <= days <= 2 or 22 <= days <= 30:
            return Decimal("0.65")
        if days == 0:
            return Decimal("0.45")
        return Decimal("0")

    if 0 <= days <= 14:
        return Decimal("1")
    if 15 <= days <= 21:
        return Decimal("0.70")
    if 22 <= days <= 30:
        return Decimal("0.40")
    return Decimal("0")


def _risk_preference(days: int, risk_profile: RiskProfile) -> Decimal:
    if risk_profile == "Aggressive":
        if 0 <= days <= 7:
            return Decimal("1")
        if 8 <= days <= 14:
            return Decimal("0.75")
        return Decimal("0.45")

    if risk_profile == "Conservative":
        if 14 <= days <= 30:
            return Decimal("1")
        if 8 <= days <= 13:
            return Decimal("0.70")
        return Decimal("0.40")

    if 3 <= days <= 21:
        return Decimal("1")
    if 0 <= days <= 2 or 22 <= days <= 30:
        return Decimal("0.65")
    return Decimal("0.40")
