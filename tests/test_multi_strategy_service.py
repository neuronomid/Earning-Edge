from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.services.candidate_models import (
    CandidateBatch,
    CandidateRecord,
    ScreenerStatus,
    StrategySource,
)
from app.services.candidate_service import FINVIZ_FALLBACK_WARNING
from app.services.multi_strategy_service import (
    BOTH_FAILED_WARNING,
    CATALYST_FAILED_WARNING,
    CATALYST_ONLY_WARNING,
    COILED_FAILED_WARNING,
    COILED_ONLY_WARNING,
    LEGACY_ARMS_EMPTY_WARNING,
    MultiStrategyCandidateService,
)
from app.services.strategy_catalog import build_strategy_report

pytestmark = pytest.mark.asyncio


def _row(ticker: str, *, rank: int, strategy_source: StrategySource) -> CandidateRecord:
    return CandidateRecord(
        ticker=ticker,
        company_name=f"{ticker} Co",
        market_cap=Decimal("1000"),
        earnings_date=None,
        current_price=Decimal("100"),
        screener_rank=rank,
        sources=("finviz",),
        strategy_source=strategy_source,
    )


@dataclass
class FakeArm:
    slug: StrategySource
    rows: tuple[CandidateRecord, ...] = ()
    screener_status: ScreenerStatus = "success"
    fallback_used: bool = False
    warning_text: str | None = None
    error: Exception | None = None

    async def get_top_five(
        self,
        *,
        limit: int = 5,
        user_id: object | None = None,
    ) -> CandidateBatch:
        del user_id
        if self.error is not None:
            raise self.error
        rows = self.rows[:limit]
        if self.screener_status == "failed" and not rows:
            report_status = "failed"
        else:
            report_status = "empty" if not rows else "success"
        return CandidateBatch(
            candidates=rows,
            screener_status=self.screener_status if rows else "empty",
            fallback_used=self.fallback_used,
            warning_text=self.warning_text,
            strategy_reports=(
                build_strategy_report(
                    self.slug,
                    status=report_status,
                    raw_row_count=len(self.rows),
                    candidate_count=len(rows),
                    finviz_candidate_count=len(rows),
                    backup_candidate_count=0,
                    fallback_used=self.fallback_used,
                    warning_text=self.warning_text,
                ),
            ),
        )


def _arm(
    slug: StrategySource,
    tickers: list[str] | tuple[str, ...] = (),
    *,
    error: Exception | None = None,
) -> FakeArm:
    return FakeArm(
        slug=slug,
        rows=tuple(
            _row(ticker, rank=index, strategy_source=slug)
            for index, ticker in enumerate(tickers, start=1)
        ),
        error=error,
    )


async def test_merges_disjoint_strategies() -> None:
    service = MultiStrategyCandidateService(
        (
            _arm("catalyst_confluence", ["A", "B", "C", "D", "E"]),
            _arm("coiled_setup", ["F", "G", "H", "I", "J"]),
        )
    )

    batch = await service.get_candidates()

    assert batch.screener_status == "success"
    assert batch.warning_text is None
    assert batch.fallback_used is False
    assert len(batch.candidates) == 10
    sources = {row.strategy_source for row in batch.candidates}
    assert sources == {"catalyst_confluence", "coiled_setup"}
    assert {report.strategy_source for report in batch.strategy_reports} == {
        "catalyst_confluence",
        "coiled_setup",
    }


async def test_five_arm_merge_with_empty_stubs_matches_legacy_output() -> None:
    catalyst = _arm("catalyst_confluence", ["A", "B"])
    coiled = _arm("coiled_setup", ["C", "D"])
    legacy = MultiStrategyCandidateService((catalyst, coiled))
    five_arm = MultiStrategyCandidateService(
        (
            catalyst,
            _arm("pead_continuation"),
            coiled,
            _arm("sector_relative_strength"),
            _arm("activist_13d_followthrough"),
        )
    )

    legacy_batch = await legacy.get_candidates()
    five_arm_batch = await five_arm.get_candidates()

    assert five_arm_batch.candidates == legacy_batch.candidates
    assert [report.strategy_source for report in five_arm_batch.strategy_reports] == [
        "catalyst_confluence",
        "pead_continuation",
        "coiled_setup",
        "sector_relative_strength",
        "activist_13d_followthrough",
    ]


async def test_tie_precedence_a_over_c_over_b_over_d_over_e() -> None:
    service = MultiStrategyCandidateService(
        (
            _arm("catalyst_confluence", ["TIE", "A_ONLY"]),
            _arm("pead_continuation", ["TIE", "C_OVER_B"]),
            _arm("coiled_setup", ["C_OVER_B", "B_OVER_D"]),
            _arm("sector_relative_strength", ["B_OVER_D", "D_OVER_E"]),
            _arm("activist_13d_followthrough", ["D_OVER_E", "E_ONLY"]),
        )
    )

    batch = await service.get_candidates()

    by_ticker = {row.ticker: row.strategy_source for row in batch.candidates}
    assert by_ticker == {
        "TIE": "catalyst_confluence",
        "A_ONLY": "catalyst_confluence",
        "C_OVER_B": "pead_continuation",
        "B_OVER_D": "coiled_setup",
        "D_OVER_E": "sector_relative_strength",
        "E_ONLY": "activist_13d_followthrough",
    }


async def test_partial_when_only_catalyst_returns() -> None:
    service = MultiStrategyCandidateService(
        (
            _arm("catalyst_confluence", ["AAA"]),
            _arm("coiled_setup"),
        )
    )

    batch = await service.get_candidates()

    assert batch.screener_status == "partial"
    assert batch.warning_text == CATALYST_ONLY_WARNING
    assert len(batch.candidates) == 1
    coiled_report = next(
        report for report in batch.strategy_reports if report.strategy_source == "coiled_setup"
    )
    assert coiled_report.status == "empty"


async def test_partial_when_only_coiled_returns() -> None:
    service = MultiStrategyCandidateService(
        (
            _arm("catalyst_confluence"),
            _arm("coiled_setup", ["XXX"]),
        )
    )

    batch = await service.get_candidates()

    assert batch.screener_status == "partial"
    assert batch.warning_text == COILED_ONLY_WARNING
    assert [row.ticker for row in batch.candidates] == ["XXX"]


async def test_failed_when_all_empty() -> None:
    service = MultiStrategyCandidateService(
        (
            _arm("catalyst_confluence"),
            _arm("pead_continuation"),
            _arm("coiled_setup"),
            _arm("sector_relative_strength"),
            _arm("activist_13d_followthrough"),
        )
    )

    batch = await service.get_candidates()

    assert batch.screener_status == "failed"
    assert batch.warning_text == BOTH_FAILED_WARNING
    assert batch.candidates == ()


async def test_catalyst_exception_treated_as_zero_rows() -> None:
    service = MultiStrategyCandidateService(
        (
            _arm("catalyst_confluence", error=RuntimeError("catalyst exploded")),
            _arm("coiled_setup", ["XXX"]),
        )
    )

    batch = await service.get_candidates()

    assert batch.screener_status == "partial"
    assert batch.warning_text == CATALYST_FAILED_WARNING
    assert [row.ticker for row in batch.candidates] == ["XXX"]


async def test_catalyst_failed_batch_without_exception_uses_empty_warning() -> None:
    catalyst = _arm("catalyst_confluence")
    catalyst.screener_status = "failed"
    service = MultiStrategyCandidateService(
        (
            catalyst,
            _arm("coiled_setup", ["XXX"]),
        )
    )

    batch = await service.get_candidates()

    assert batch.screener_status == "partial"
    assert batch.warning_text == COILED_ONLY_WARNING
    catalyst_report = next(
        report
        for report in batch.strategy_reports
        if report.strategy_source == "catalyst_confluence"
    )
    assert catalyst_report.status == "failed"


async def test_coiled_exception_is_reported_as_failed_not_empty() -> None:
    service = MultiStrategyCandidateService(
        (
            _arm("catalyst_confluence", ["AAA"]),
            _arm("coiled_setup", error=RuntimeError("coiled exploded")),
        )
    )

    batch = await service.get_candidates()

    assert batch.screener_status == "partial"
    assert batch.warning_text == COILED_FAILED_WARNING
    coiled_report = next(
        report for report in batch.strategy_reports if report.strategy_source == "coiled_setup"
    )
    assert coiled_report.status == "failed"


async def test_one_arm_raises_others_succeed_partial_status() -> None:
    service = MultiStrategyCandidateService(
        (
            _arm("catalyst_confluence", ["AAA"]),
            _arm("pead_continuation", error=RuntimeError("pead exploded")),
            _arm("coiled_setup", ["BBB"]),
            _arm("sector_relative_strength", ["CCC"]),
            _arm("activist_13d_followthrough", ["DDD"]),
        )
    )

    batch = await service.get_candidates()

    assert batch.screener_status == "partial"
    assert batch.warning_text is None
    failed_report = next(
        report for report in batch.strategy_reports if report.strategy_source == "pead_continuation"
    )
    assert failed_report.status == "failed"


async def test_screener_status_empty_propagates() -> None:
    service = MultiStrategyCandidateService(
        (
            _arm("catalyst_confluence", ["AAA"]),
            _arm("pead_continuation"),
            _arm("coiled_setup", ["BBB"]),
        )
    )

    batch = await service.get_candidates()

    assert [row.ticker for row in batch.candidates] == ["AAA", "BBB"]
    empty_report = next(
        report for report in batch.strategy_reports if report.strategy_source == "pead_continuation"
    )
    assert empty_report.status == "empty"
    assert empty_report.candidate_count == 0


async def test_propagates_fallback_used_from_catalyst() -> None:
    catalyst = _arm("catalyst_confluence", ["AAA"])
    catalyst.fallback_used = True
    catalyst.warning_text = "catalyst-fallback warning"
    catalyst.screener_status = "failed"
    service = MultiStrategyCandidateService(
        (
            catalyst,
            _arm("coiled_setup", ["BBB"]),
        )
    )

    batch = await service.get_candidates()

    assert batch.fallback_used is True
    assert batch.screener_status == "success"
    assert batch.warning_text == "catalyst-fallback warning"


async def test_legacy_arms_empty_warning_when_only_new_strategies_return_rows() -> None:
    """When A and B both produce zero rows but C/D/E succeed, the user must
    see a warning explaining that the legacy screens came up empty."""
    service = MultiStrategyCandidateService(
        (
            FakeArm(slug="catalyst_confluence", rows=(), screener_status="empty"),
            FakeArm(
                slug="pead_continuation",
                rows=(_row("PEAD", rank=1, strategy_source="pead_continuation"),),
            ),
            FakeArm(slug="coiled_setup", rows=(), screener_status="empty"),
            FakeArm(
                slug="sector_relative_strength",
                rows=(_row("SRSX", rank=1, strategy_source="sector_relative_strength"),),
            ),
            FakeArm(
                slug="activist_13d_followthrough",
                rows=(_row("AKTV", rank=1, strategy_source="activist_13d_followthrough"),),
            ),
        )
    )
    batch = await service.get_candidates()
    assert batch.warning_text == LEGACY_ARMS_EMPTY_WARNING
    assert len(batch.candidates) == 3
    assert batch.screener_status == "partial"


async def test_legacy_warning_strings_unchanged() -> None:
    assert (
        FINVIZ_FALLBACK_WARNING
        == "⚠️ Finviz did not load correctly, so I used backup earnings data for this scan."
    )
    assert (
        CATALYST_ONLY_WARNING == "⚠️ Coiled-setup screen returned no candidates this scan — "
        "showing catalyst-driven setups only."
    )
    assert (
        COILED_ONLY_WARNING == "⚠️ Catalyst screen returned no setups this scan — "
        "showing structure-driven candidates only."
    )
    assert BOTH_FAILED_WARNING == "⚠️ Both screening strategies failed to return candidates."
    assert (
        COILED_FAILED_WARNING
        == "⚠️ Coiled-setup screen failed this scan — showing catalyst-driven candidates only."
    )
    assert (
        CATALYST_FAILED_WARNING
        == "⚠️ Catalyst screen failed this scan — showing structure-driven candidates only."
    )
