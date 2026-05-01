from __future__ import annotations

from decimal import Decimal

from app.scoring.types import (
    OptionContractInput,
    Strategy,
    breakeven_move_percent,
    spread_percent,
)


def select_strike_candidates(
    contracts: tuple[OptionContractInput, ...],
    *,
    current_price: Decimal,
    strategy: Strategy,
) -> tuple[OptionContractInput, ...]:
    if current_price is None or current_price <= 0:
        return ()

    matching = tuple(contract for contract in contracts if contract.strategy == strategy)
    if not matching:
        return ()

    selected: list[OptionContractInput] = []
    categories = (
        _closest(matching, current_price=current_price, target="atm"),
        _closest(matching, current_price=current_price, target="slight_itm"),
        _closest(matching, current_price=current_price, target="slight_otm"),
        _closest(matching, current_price=current_price, target="moderate_otm"),
        max(matching, key=_liquidity_proxy),
        _best_breakeven(matching, current_price=current_price),
    )

    seen: set[tuple[str, str, object, object]] = set()
    for contract in categories:
        if contract is None:
            continue
        key = (
            contract.option_type,
            contract.position_side,
            contract.expiry,
            contract.strike,
        )
        if key in seen:
            continue
        seen.add(key)
        selected.append(contract)
    return tuple(selected)


def _closest(
    contracts: tuple[OptionContractInput, ...],
    *,
    current_price: Decimal,
    target: str,
) -> OptionContractInput | None:
    matches = [contract for contract in contracts if _match_target(contract, current_price, target)]
    if not matches:
        return None
    return min(matches, key=lambda contract: abs(_relative_distance(contract, current_price)))


def _match_target(contract: OptionContractInput, current_price: Decimal, target: str) -> bool:
    distance = abs(_relative_distance(contract, current_price))
    if target == "atm":
        return distance <= 0.02
    relation = _relationship(contract, current_price)
    if target == "slight_itm":
        return relation == "itm" and distance <= 0.05
    if target == "slight_otm":
        return relation == "otm" and distance <= 0.05
    return relation == "otm" and 0.05 < distance <= 0.12


def _relationship(contract: OptionContractInput, current_price: Decimal) -> str:
    diff = contract.strike - current_price
    if abs(diff / current_price) <= 0.02:
        return "atm"
    if contract.option_type == "call":
        return "itm" if diff < 0 else "otm"
    return "itm" if diff > 0 else "otm"


def _relative_distance(contract: OptionContractInput, current_price: Decimal) -> Decimal:
    return (contract.strike - current_price) / current_price


def _best_breakeven(
    contracts: tuple[OptionContractInput, ...], *, current_price: Decimal
) -> OptionContractInput | None:
    if not contracts:
        return None
    if contracts[0].position_side == "long":
        return min(
            contracts,
            key=lambda contract: breakeven_move_percent(contract, current_price) or 1,
        )
    return max(contracts, key=lambda contract: _short_safety_buffer(contract, current_price))


def _short_safety_buffer(contract: OptionContractInput, current_price: Decimal) -> Decimal:
    breakeven = breakeven_move_percent(contract, current_price)
    if breakeven is None:
        return Decimal("0")
    return breakeven


def _liquidity_proxy(contract: OptionContractInput) -> float:
    oi = float(contract.open_interest or 0)
    volume = float(contract.volume or 0)
    spread = float(spread_percent(contract) or 0)
    return (oi * 0.6) + (volume * 0.4) - (spread * 100)
