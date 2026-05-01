from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.scoring.types import (
    HUNDRED,
    SHORT_NOTIONAL_CAP_PCTS,
    ZERO,
    OptionContractInput,
    UserContext,
    risk_percent,
)
from app.services.sizing_types import SizingResult

SHORT_CALL_MAX_LOSS_TEXT = "Undefined for naked short call"
BROKER_MARGIN_DEPENDENT_TEXT = "Broker/margin dependent"
_CENTS = Decimal("0.01")


class SizingError(ValueError):
    """Raised when a contract cannot be sized from the available inputs."""


class SizingPermissionError(PermissionError):
    """Raised when the user's strategy permission forbids the contract."""


def size(user: UserContext, contract: OptionContractInput) -> SizingResult:
    _enforce_strategy_permission(user, contract)

    if contract.position_side == "long":
        return _size_long_position(user, contract)
    if contract.strategy == "short_put":
        return _size_short_put(user, contract)
    return _size_short_call(user, contract)


def _size_long_position(user: UserContext, contract: OptionContractInput) -> SizingResult:
    ask = contract.ask
    if ask is None or ask <= ZERO:
        raise SizingError("Long option sizing requires a positive ask price.")

    account_risk_pct = risk_percent(user)
    trade_budget = _non_negative(user.account_size * account_risk_pct)
    max_loss_per_contract = ask * HUNDRED
    quantity = _bounded_quantity(
        user,
        int(trade_budget // max_loss_per_contract) if max_loss_per_contract > ZERO else 0,
    )
    if user.max_option_premium is not None and ask > user.max_option_premium:
        quantity = 0

    return SizingResult(
        quantity=quantity,
        max_loss_text=f"{_format_currency(max_loss_per_contract)} max loss per contract",
        account_risk_pct=account_risk_pct,
        broker_verification_required=False,
        watch_only=quantity == 0,
        trade_budget=trade_budget,
        max_loss_per_contract=max_loss_per_contract,
    )


def _size_short_put(user: UserContext, contract: OptionContractInput) -> SizingResult:
    max_short_notional = _max_short_notional(user, contract)
    per_contract_exposure = contract.strike * HUNDRED
    quantity = _bounded_quantity(user, int(max_short_notional // per_contract_exposure))

    return SizingResult(
        quantity=quantity,
        max_loss_text=(
            f"Approx. {_format_currency(per_contract_exposure)} "
            "notional exposure per contract"
        ),
        account_risk_pct=SHORT_NOTIONAL_CAP_PCTS[user.risk_profile],
        broker_verification_required=True,
        watch_only=quantity == 0,
        max_short_notional_exposure=max_short_notional,
        contract_notional_exposure=per_contract_exposure,
        premium_collected=_premium_collected(contract),
        margin_requirement_text=BROKER_MARGIN_DEPENDENT_TEXT,
    )


def _size_short_call(user: UserContext, contract: OptionContractInput) -> SizingResult:
    max_short_notional = _max_short_notional(user, contract)
    per_contract_exposure = contract.strike * HUNDRED
    quantity = _bounded_quantity(user, int(max_short_notional // per_contract_exposure))

    return SizingResult(
        quantity=quantity,
        max_loss_text=SHORT_CALL_MAX_LOSS_TEXT,
        account_risk_pct=SHORT_NOTIONAL_CAP_PCTS[user.risk_profile],
        broker_verification_required=True,
        watch_only=quantity == 0,
        max_short_notional_exposure=max_short_notional,
        contract_notional_exposure=per_contract_exposure,
        premium_collected=_premium_collected(contract),
        margin_requirement_text=BROKER_MARGIN_DEPENDENT_TEXT,
    )


def _enforce_strategy_permission(user: UserContext, contract: OptionContractInput) -> None:
    if contract.position_side == "short" and user.strategy_permission == "long":
        raise SizingPermissionError("Short option sizing is disabled for this user.")
    if contract.position_side == "long" and user.strategy_permission == "short":
        raise SizingPermissionError("Long option sizing is disabled for this user.")


def _max_short_notional(user: UserContext, contract: OptionContractInput) -> Decimal:
    if contract.strike <= ZERO:
        raise SizingError("Short option sizing requires a positive strike price.")
    return _non_negative(user.account_size * SHORT_NOTIONAL_CAP_PCTS[user.risk_profile])


def _bounded_quantity(user: UserContext, quantity: int) -> int:
    if quantity <= 0 or user.max_contracts <= 0:
        return 0
    return min(quantity, user.max_contracts)


def _premium_collected(contract: OptionContractInput) -> Decimal | None:
    if contract.bid is None or contract.bid <= ZERO:
        return None
    return contract.bid * HUNDRED


def _non_negative(value: Decimal) -> Decimal:
    return value if value > ZERO else ZERO


def _format_currency(value: Decimal) -> str:
    rounded = value.quantize(_CENTS, rounding=ROUND_HALF_UP)
    return f"${rounded:,.2f}"
