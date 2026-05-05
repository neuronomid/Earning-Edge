from __future__ import annotations

from app.core.logging import get_logger
from app.services.candidate_models import CandidateRecord
from app.services.finviz.runner import FinvizQueryRunner
from app.services.finviz.strategies import (
    STRATEGY_B_BASE,
    STRATEGY_B_VARIANT_PREFIX,
    STRATEGY_B_VARIANT_VALUES,
)

COILED_STRATEGY_SOURCE = "coiled_setup"


class CoiledSetupCandidateService:
    def __init__(
        self,
        runner: FinvizQueryRunner,
        *,
        logger=None,
    ) -> None:
        self.runner = runner
        self.logger = logger or get_logger(__name__)

    async def get_top_five(self, *, limit: int = 5) -> tuple[CandidateRecord, ...]:
        try:
            rows = await self.runner.run_with_swap(
                STRATEGY_B_BASE,
                swap_prefix=STRATEGY_B_VARIANT_PREFIX,
                swap_values=STRATEGY_B_VARIANT_VALUES,
                limit=limit,
                strategy_source=COILED_STRATEGY_SOURCE,
            )
        except Exception as exc:
            self.logger.warning("coiled_setup_finviz_failed", error=str(exc))
            return ()
        self.logger.info(
            "coiled_setup_rows_extracted",
            tickers=[row.ticker for row in rows],
        )
        return tuple(rows[:limit])
