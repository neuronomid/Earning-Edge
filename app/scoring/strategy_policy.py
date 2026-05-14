from __future__ import annotations

from app.scoring.types import StrategySource

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
