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
    # Long-premium reality floors. Apply only when the contract is long and no
    # named catalyst falls before the planned exit — a true catalyst trade can
    # justify a coin-flip R:R or a thin chain on event-day liquidity, but a
    # structural sector / coiled / activist setup cannot.
    min_long_premium_risk_reward: Decimal = Decimal("0.80")
    min_volume_non_catalyst_long: int = 5
    min_open_interest_non_catalyst_long: int = 10


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
        min_long_premium_risk_reward=Decimal("0.50"),
        min_volume_non_catalyst_long=1,
        min_open_interest_non_catalyst_long=1,
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
        min_long_premium_risk_reward=Decimal("0.80"),
        min_volume_non_catalyst_long=5,
        min_open_interest_non_catalyst_long=10,
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
        min_long_premium_risk_reward=Decimal("0.80"),
        min_volume_non_catalyst_long=5,
        min_open_interest_non_catalyst_long=10,
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
        min_long_premium_risk_reward=Decimal("0.80"),
        min_volume_non_catalyst_long=5,
        min_open_interest_non_catalyst_long=10,
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
        min_long_premium_risk_reward=Decimal("0.80"),
        min_volume_non_catalyst_long=5,
        min_open_interest_non_catalyst_long=10,
    ),
}


def trade_policy_for(strategy_source: StrategySource) -> StrategyTradePolicy:
    return _POLICIES[strategy_source]
