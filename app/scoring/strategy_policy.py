from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.scoring.types import Strategy, StrategySource

NO_EARNINGS_REQUIRED_STRATEGIES: frozenset[StrategySource] = frozenset(
    {
        "coiled_setup",
        "sector_relative_strength",
        "activist_13d_followthrough",
    }
)
EARNINGS_HISTORY_RELEVANT_STRATEGIES: frozenset[StrategySource] = frozenset(
    {
        "catalyst_confluence",
    }
)


@dataclass(frozen=True, slots=True)
class StrategyTradePolicy:
    min_dte_calendar: int
    max_dte_calendar: int
    min_trading_days_to_exit: int
    max_required_sigma_to_target: Decimal
    min_target_touch_probability: Decimal
    allow_weeklies_without_named_catalyst: bool
    max_spread_percent: Decimal
    preferred_contract_sides: tuple[Strategy, ...]


_POLICIES: dict[StrategySource, StrategyTradePolicy] = {
    "catalyst_confluence": StrategyTradePolicy(
        min_dte_calendar=3,
        max_dte_calendar=30,
        min_trading_days_to_exit=1,
        max_required_sigma_to_target=Decimal("1.35"),
        min_target_touch_probability=Decimal("0.20"),
        allow_weeklies_without_named_catalyst=True,
        max_spread_percent=Decimal("0.35"),
        preferred_contract_sides=("long_call", "long_put", "short_put", "short_call"),
    ),
    "pead_continuation": StrategyTradePolicy(
        min_dte_calendar=14,
        max_dte_calendar=35,
        min_trading_days_to_exit=4,
        max_required_sigma_to_target=Decimal("1.00"),
        min_target_touch_probability=Decimal("0.35"),
        allow_weeklies_without_named_catalyst=False,
        max_spread_percent=Decimal("0.30"),
        preferred_contract_sides=("long_call", "long_put"),
    ),
    "coiled_setup": StrategyTradePolicy(
        min_dte_calendar=14,
        max_dte_calendar=45,
        min_trading_days_to_exit=4,
        max_required_sigma_to_target=Decimal("1.00"),
        min_target_touch_probability=Decimal("0.35"),
        allow_weeklies_without_named_catalyst=False,
        max_spread_percent=Decimal("0.30"),
        preferred_contract_sides=("long_call", "long_put"),
    ),
    "sector_relative_strength": StrategyTradePolicy(
        min_dte_calendar=14,
        max_dte_calendar=45,
        min_trading_days_to_exit=4,
        max_required_sigma_to_target=Decimal("1.00"),
        min_target_touch_probability=Decimal("0.35"),
        allow_weeklies_without_named_catalyst=False,
        max_spread_percent=Decimal("0.30"),
        preferred_contract_sides=("long_call", "long_put"),
    ),
    "activist_13d_followthrough": StrategyTradePolicy(
        min_dte_calendar=14,
        max_dte_calendar=45,
        min_trading_days_to_exit=4,
        max_required_sigma_to_target=Decimal("1.00"),
        min_target_touch_probability=Decimal("0.35"),
        allow_weeklies_without_named_catalyst=False,
        max_spread_percent=Decimal("0.30"),
        preferred_contract_sides=("long_call", "long_put"),
    ),
}


def trade_policy_for(strategy_source: StrategySource) -> StrategyTradePolicy:
    return _POLICIES[strategy_source]
