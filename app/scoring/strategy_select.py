from __future__ import annotations

from decimal import Decimal

from app.scoring.types import (
    DirectionClassification,
    OptionContractInput,
    Strategy,
    StrategyPermission,
    StrategySelection,
)


def select_allowed_strategies(
    classification: DirectionClassification,
    permission: StrategyPermission,
    *,
    direction_score: int,
    option_chain: tuple[OptionContractInput, ...],
) -> StrategySelection:
    if classification == "bullish":
        allowed: tuple[Strategy, ...] = ("long_call", "short_put")
    elif classification == "bearish":
        allowed = ("long_put", "short_call")
    else:
        return StrategySelection((), (), "No directional edge was available.")

    filtered = tuple(strategy for strategy in allowed if _strategy_allowed(strategy, permission))
    if not filtered:
        return StrategySelection((), (), "User strategy permissions blocked every candidate.")

    preferred = filtered
    if len(filtered) == 2:
        median_iv = _median_iv(
            tuple(contract for contract in option_chain if contract.strategy in filtered)
        )
        if median_iv is not None and median_iv >= Decimal("0.60") and direction_score < 80:
            preferred = (filtered[1], filtered[0])
        elif median_iv is not None and median_iv <= Decimal("0.45"):
            preferred = filtered
        elif direction_score >= 80:
            preferred = filtered

    return StrategySelection(
        allowed_strategies=filtered,
        preferred_order=preferred,
        reason="Strategy mapping follows PRD §16.3 and tilts short only when IV is rich.",
    )


def _strategy_allowed(strategy: Strategy, permission: StrategyPermission) -> bool:
    if permission == "long_and_short":
        return True
    if permission == "long":
        return strategy.startswith("long")
    return strategy.startswith("short")


def _median_iv(contracts: tuple[OptionContractInput, ...]) -> Decimal | None:
    values = sorted(
        contract.implied_volatility
        for contract in contracts
        if contract.implied_volatility is not None
    )
    if not values:
        return None
    midpoint = len(values) // 2
    if len(values) % 2 == 1:
        return values[midpoint]
    return (values[midpoint - 1] + values[midpoint]) / Decimal("2")

