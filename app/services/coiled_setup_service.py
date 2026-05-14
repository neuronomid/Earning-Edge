from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.services.candidate_models import (
    CandidateBatch,
    CandidateRecord,
    StrategyEventSignal,
    StrategySource,
)
from app.services.finviz.runner import FinvizQueryRunner
from app.services.finviz.strategies import (
    STRATEGY_B_BASE,
    STRATEGY_B_VARIANT_PREFIX,
    STRATEGY_B_VARIANT_VALUES,
)
from app.services.strategy_catalog import build_strategy_report

COILED_STRATEGY_SOURCE: StrategySource = "coiled_setup"


class CoiledSetupCandidateService:
    slug: StrategySource = COILED_STRATEGY_SOURCE

    def __init__(
        self,
        runner: FinvizQueryRunner,
        *,
        logger: Any | None = None,
    ) -> None:
        self.runner = runner
        self.logger = logger or get_logger(__name__)

    async def get_top_five(
        self,
        *,
        limit: int = 5,
        user_id: UUID | None = None,
    ) -> CandidateBatch:
        del user_id
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
            return CandidateBatch(
                candidates=(),
                screener_status="empty",
                fallback_used=False,
                strategy_reports=(
                    build_strategy_report(
                        COILED_STRATEGY_SOURCE,
                        status="empty",
                        raw_row_count=0,
                        candidate_count=0,
                        finviz_candidate_count=0,
                        backup_candidate_count=0,
                        error=str(exc),
                    ),
                ),
            )
        self.logger.info(
            "coiled_setup_rows_extracted",
            tickers=[row.ticker for row in rows],
        )
        final_rows = _with_event_signals(tuple(rows[:limit]))
        return CandidateBatch(
            candidates=final_rows,
            screener_status="success" if final_rows else "empty",
            fallback_used=False,
            strategy_reports=(
                build_strategy_report(
                    COILED_STRATEGY_SOURCE,
                    status="success" if final_rows else "empty",
                    raw_row_count=len(rows),
                    candidate_count=len(final_rows),
                    finviz_candidate_count=len(final_rows),
                    backup_candidate_count=0,
                ),
            ),
        )


def _with_event_signals(rows: tuple[CandidateRecord, ...]) -> tuple[CandidateRecord, ...]:
    total = len(rows)
    return tuple(
        replace(row, event_signal=_coiled_event_signal(index=index, total=total))
        for index, row in enumerate(rows, start=1)
    )


def _coiled_event_signal(*, index: int, total: int) -> StrategyEventSignal:
    structural_percentile = _visible_row_percentile(index=index, total=total)
    relative_volume_percentile = structural_percentile
    score = int(
        min(
            Decimal("100"),
            structural_percentile * Decimal("50") + relative_volume_percentile * Decimal("50"),
        )
    )
    dist_from_52w_high_pct = Decimal("0.20") * (Decimal("1") - structural_percentile)
    relative_volume_x = Decimal("1") + (relative_volume_percentile * Decimal("2"))
    return StrategyEventSignal(
        score=score,
        is_supportive=True,
        detail=(
            f"Coiled setup: {dist_from_52w_high_pct:.1%} from 52w high, "
            f"{relative_volume_x:.1f}x avg volume"
        ),
    )


def _visible_row_percentile(*, index: int, total: int) -> Decimal:
    if total <= 0:
        return Decimal("0")
    clamped_index = max(1, min(index, total))
    return Decimal(total - clamped_index + 1) / Decimal(total)
