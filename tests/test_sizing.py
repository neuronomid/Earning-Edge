from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.scoring.types import OptionContractInput, UserContext
from app.services.sizing import SizingPermissionError, size


def test_long_sizing_reproduces_prd_example() -> None:
    user = _user(account_size="5000", risk_profile="Balanced")
    contract = _contract(
        option_type="call",
        position_side="long",
        strike="105",
        ask="0.85",
    )

    result = size(user, contract)

    assert result.quantity == 1
    assert result.max_loss_text == "$85.00 max loss per contract"
    assert result.account_risk_pct == Decimal("0.02")
    assert result.broker_verification_required is False
    assert result.watch_only is False
    assert result.trade_budget == Decimal("100.00")
    assert result.max_loss_per_contract == Decimal("85.00")


def test_zero_quantity_returns_watch_only_for_over_budget_long_contract() -> None:
    user = _user(account_size="5000", risk_profile="Balanced")
    contract = _contract(
        option_type="put",
        position_side="long",
        strike="95",
        ask="1.50",
    )

    result = size(user, contract)

    assert result.quantity == 0
    assert result.watch_only is True
    assert result.broker_verification_required is False
    assert result.max_loss_text == "$150.00 max loss per contract"


def test_short_call_labeling_and_margin_flag_are_returned() -> None:
    user = _user(account_size="50000", risk_profile="Balanced", max_contracts=5)
    contract = _contract(
        option_type="call",
        position_side="short",
        strike="50",
        bid="1.20",
        ask="1.35",
    )

    result = size(user, contract)

    assert result.quantity == 2
    assert result.max_loss_text == "Undefined for naked short call"
    assert result.account_risk_pct == Decimal("0.20")
    assert result.broker_verification_required is True
    assert result.watch_only is False
    assert result.margin_requirement_text == "Broker/margin dependent"
    assert result.max_short_notional_exposure == Decimal("10000.00")
    assert result.contract_notional_exposure == Decimal("5000")
    assert result.premium_collected == Decimal("120.00")


@pytest.mark.parametrize(
    ("risk_profile", "expected_pct", "expected_qty"),
    [
        ("Conservative", Decimal("0.10"), 2),
        ("Balanced", Decimal("0.20"), 4),
        ("Aggressive", Decimal("0.35"), 7),
    ],
)
def test_short_put_sizing_uses_risk_profile_notional_caps(
    risk_profile: str,
    expected_pct: Decimal,
    expected_qty: int,
) -> None:
    user = _user(account_size="100000", risk_profile=risk_profile, max_contracts=10)
    contract = _contract(
        option_type="put",
        position_side="short",
        strike="50",
        bid="1.10",
        ask="1.25",
    )

    result = size(user, contract)

    assert result.quantity == expected_qty
    assert result.account_risk_pct == expected_pct
    assert result.watch_only is False
    assert result.max_loss_text == "Approx. $5,000.00 notional exposure per contract"


def test_strategy_permission_gate_blocks_short_sizing() -> None:
    user = _user(
        account_size="50000",
        risk_profile="Balanced",
        strategy_permission="long",
    )
    contract = _contract(
        option_type="put",
        position_side="short",
        strike="90",
        bid="1.05",
        ask="1.20",
    )

    with pytest.raises(SizingPermissionError, match="Short option sizing is disabled"):
        size(user, contract)


def _user(
    *,
    account_size: str,
    risk_profile: str,
    strategy_permission: str = "long_and_short",
    max_contracts: int = 3,
) -> UserContext:
    return UserContext(
        account_size=Decimal(account_size),
        risk_profile=risk_profile,  # type: ignore[arg-type]
        strategy_permission=strategy_permission,  # type: ignore[arg-type]
        max_contracts=max_contracts,
    )


def _contract(
    *,
    option_type: str,
    position_side: str,
    strike: str,
    bid: str | None = None,
    ask: str | None = None,
) -> OptionContractInput:
    return OptionContractInput(
        ticker="ABC",
        option_type=option_type,  # type: ignore[arg-type]
        position_side=position_side,  # type: ignore[arg-type]
        strike=Decimal(strike),
        expiry=date(2026, 5, 15),
        bid=Decimal(bid) if bid is not None else None,
        ask=Decimal(ask) if ask is not None else None,
    )
