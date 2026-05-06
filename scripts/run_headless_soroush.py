from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.core.config import get_settings
from app.pipeline.steps.decide import HeuristicDecisionStep, resolve_selected_contract
from app.pipeline.steps.market_data import MarketDataFetchStep
from app.pipeline.steps.news import NewsBriefStep
from app.pipeline.steps.options import OptionsFetchStep
from app.pipeline.steps.scoring import CandidateScoringStep
from app.pipeline.steps.sizing import PositionSizingStep
from app.pipeline.types import PipelineCandidate
from app.scoring.types import CandidateContext, UserContext
from app.services.candidate_models import CandidateBatch, CandidateRecord
from app.services.candidate_service import CandidateService
from app.services.coiled_setup_service import CoiledSetupCandidateService
from app.services.earnings_calendar.finnhub_source import FinnhubEarningsSource
from app.services.earnings_calendar.yfinance_source import YFinanceEarningsSource
from app.services.finviz.browser import FinvizBrowserClient
from app.services.finviz.runner import FinvizQueryRunner
from app.services.market_data.service import MarketDataService
from app.services.market_data.types import ConfidenceNote, MarketSnapshot, ReturnMetrics
from app.services.multi_strategy_service import MultiStrategyCandidateService
from app.services.news.service import NewsService
from app.services.news.types import NewsBrief, NewsBundle
from app.services.options.service import OptionsService
from app.services.sizing import BROKER_MARGIN_DEPENDENT_TEXT, SizingError, SizingPermissionError
from app.services.sizing_types import SizingResult

ZERO = Decimal("0")
DECISION_FINALIST_LIMIT = 4
RUN_DATE = "20260505"
RESULTS_DIR = Path(r"C:\Users\sseif\Desktop\Earning-Edge-main\results")


@dataclass(slots=True, frozen=True)
class RunInputs:
    account_size: Decimal = Decimal("10000")
    risk_profile: str = "Balanced"
    timezone_label: str = "ET"
    timezone_iana: str = "America/Toronto"
    broker: str = "wealthsimple"
    strategy_permission: str = "long_and_short"
    max_contracts: int = 3
    openrouter_api_key: str = ""
    alpha_vantage_api_key: str | None = None
    alpaca_api_key: str | None = None
    alpaca_api_secret: str | None = None


async def main() -> None:
    settings = get_settings()
    inputs = RunInputs()

    browser = FinvizBrowserClient(headless=True, timeout_ms=settings.finviz_timeout_ms)
    runner = FinvizQueryRunner(browser, cache=None)
    candidate_service = MultiStrategyCandidateService(
        CandidateService(
            runner,
            sources=(
                YFinanceEarningsSource(),
                FinnhubEarningsSource(api_key=settings.finnhub_api_key),
            ),
        ),
        CoiledSetupCandidateService(runner),
    )
    market_step = MarketDataFetchStep(service=MarketDataService(cache=None))
    news_step = NewsBriefStep(service=NewsService(cache=None))
    options_step = OptionsFetchStep(service=OptionsService())
    scoring_step = CandidateScoringStep()
    sizing_step = PositionSizingStep()
    decision_step = HeuristicDecisionStep()

    batch = await candidate_service.get_candidates()
    user_context = UserContext(
        account_size=inputs.account_size,
        risk_profile=inputs.risk_profile,  # type: ignore[arg-type]
        strategy_permission=inputs.strategy_permission,  # type: ignore[arg-type]
        max_contracts=inputs.max_contracts,
        has_valid_openrouter_api_key=False,
    )

    candidates = []
    for record in batch.candidates:
        item = await analyze_candidate(
            record=record,
            user_context=user_context,
            market_step=market_step,
            news_step=news_step,
            options_step=options_step,
            scoring_step=scoring_step,
            sizing_step=sizing_step,
            inputs=inputs,
        )
        candidates.append(item)

    finalists = sorted(
        candidates,
        key=lambda item: (
            item.evaluation.final_score,
            item.evaluation.confidence.score,
            item.evaluation.direction.score,
        ),
        reverse=True,
    )[:DECISION_FINALIST_LIMIT]
    decision_result = await decision_step.execute(
        finalists,
        user_context,
        openrouter_api_key="",
    )
    selected = next(
        (item for item in candidates if item.record.ticker == decision_result.decision.chosen_ticker),
        None,
    )
    selected_contract = (
        None
        if selected is None
        else resolve_selected_contract(selected, decision_result.decision.chosen_contract)
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    write_chosen_stocks_csv(batch, candidates)
    write_strategies_csv(batch)
    write_final_option_csv(selected, selected_contract, decision_result.decision, inputs)
    write_final_target_option_csv(selected, selected_contract)

    print(f"batch_status={batch.screener_status}")
    print(f"candidates={len(candidates)}")
    print(f"decision_action={decision_result.decision.action}")
    print(f"selected_ticker={'' if selected is None else selected.record.ticker}")
    print(f"selected_strategy={'' if selected_contract is None else selected_contract.strategy}")


async def analyze_candidate(
    *,
    record: CandidateRecord,
    user_context: UserContext,
    market_step: MarketDataFetchStep,
    news_step: NewsBriefStep,
    options_step: OptionsFetchStep,
    scoring_step: CandidateScoringStep,
    sizing_step: PositionSizingStep,
    inputs: RunInputs,
) -> PipelineCandidate:
    calculation_errors: list[str] = []

    try:
        market_snapshot = await market_step.execute(
            record,
            alpha_vantage_api_key=inputs.alpha_vantage_api_key,
        )
    except Exception as exc:
        calculation_errors.append(f"Market data fallback used: {exc}")
        market_snapshot = fallback_market_snapshot(record, error=str(exc))

    try:
        news_bundle = await news_step.execute(
            record,
            openrouter_api_key=inputs.openrouter_api_key,
        )
    except Exception as exc:
        calculation_errors.append(f"News fallback used: {exc}")
        news_bundle = fallback_news_bundle(record, error=str(exc))

    try:
        option_chain = await options_step.execute(
            record,
            alpaca_api_key=inputs.alpaca_api_key,
            alpaca_api_secret=inputs.alpaca_api_secret,
            strategy_permission=inputs.strategy_permission,
        )
    except Exception as exc:
        calculation_errors.append(f"Option chain unavailable: {exc}")
        option_chain = ()

    context = CandidateContext(
        ticker=record.ticker,
        company_name=record.company_name or market_snapshot.company_name or record.ticker,
        earnings_date=record.earnings_date or datetime.now(timezone.utc).date(),
        earnings_timing="unknown",
        market_snapshot=market_snapshot,
        news_brief=news_bundle.brief,
        option_chain=option_chain,
        verified_earnings_date=record.earnings_date_verified,
        identity_verified=bool(record.ticker and (record.company_name or market_snapshot.company_name)),
        source_conflicts=(),
        calculation_errors=tuple(calculation_errors),
    )
    evaluation = await scoring_step.execute(context, user_context)
    sizing = None
    if evaluation.chosen_contract is not None:
        try:
            sizing = await sizing_step.execute(user_context, evaluation.chosen_contract.contract)
        except (SizingError, SizingPermissionError):
            sizing = fallback_sizing(evaluation.chosen_contract.contract.position_side)

    return PipelineCandidate(
        record=record,
        context=context,
        evaluation=evaluation,
        news_bundle=news_bundle,
        sizing=sizing,
    )


def write_chosen_stocks_csv(batch: CandidateBatch, candidates: list[PipelineCandidate]) -> None:
    path = RESULTS_DIR / f"soroush-chosen-stocks-{RUN_DATE}.csv"
    ranked = sorted(
        candidates,
        key=lambda item: (item.evaluation.final_score, item.evaluation.confidence.score),
        reverse=True,
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ticker",
                "company_name",
                "strategy_source",
                "screener_rank",
                "current_price",
                "earnings_date",
                "direction",
                "direction_score",
                "data_confidence_score",
                "final_opportunity_score",
                "best_strategy",
                "candidate_action",
                "warning_text",
            ],
        )
        writer.writeheader()
        for item in ranked:
            writer.writerow(
                {
                    "ticker": item.record.ticker,
                    "company_name": item.context.company_name,
                    "strategy_source": item.record.strategy_source or "",
                    "screener_rank": item.record.screener_rank or "",
                    "current_price": dec(item.context.market_snapshot.current_price),
                    "earnings_date": item.context.earnings_date.isoformat(),
                    "direction": item.evaluation.direction.classification,
                    "direction_score": item.evaluation.direction.score,
                    "data_confidence_score": item.evaluation.confidence.score,
                    "final_opportunity_score": item.evaluation.final_score,
                    "best_strategy": ""
                    if item.evaluation.chosen_contract is None
                    else item.evaluation.chosen_contract.strategy,
                    "candidate_action": item.evaluation.action,
                    "warning_text": batch.warning_text or "",
                }
            )


def write_strategies_csv(batch: CandidateBatch) -> None:
    path = RESULTS_DIR / f"soroush-strategies-{RUN_DATE}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "strategy_source",
                "strategy_label",
                "status",
                "provider",
                "raw_row_count",
                "candidate_count",
                "finviz_candidate_count",
                "backup_candidate_count",
                "fallback_used",
                "query_urls",
                "filter_codes",
                "criteria_summary",
                "sort_summary",
                "warning_text",
                "error",
            ],
        )
        writer.writeheader()
        for report in batch.strategy_reports:
            writer.writerow(
                {
                    "strategy_source": report.strategy_source,
                    "strategy_label": report.strategy_label,
                    "status": report.status,
                    "provider": report.provider,
                    "raw_row_count": report.raw_row_count,
                    "candidate_count": report.candidate_count,
                    "finviz_candidate_count": report.finviz_candidate_count,
                    "backup_candidate_count": report.backup_candidate_count,
                    "fallback_used": report.fallback_used,
                    "query_urls": "|".join(report.query_urls),
                    "filter_codes": "|".join(report.filter_codes),
                    "criteria_summary": report.criteria_summary or "",
                    "sort_summary": report.sort_summary or "",
                    "warning_text": report.warning_text or "",
                    "error": report.error or "",
                }
            )


def write_final_option_csv(selected, selected_contract, decision, inputs: RunInputs) -> None:
    path = RESULTS_DIR / f"soroush-final-option-{RUN_DATE}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ticker",
                "company_name",
                "strategy",
                "option_type",
                "position_side",
                "strike",
                "expiry",
                "entry_price",
                "quantity",
                "estimated_max_loss",
                "confidence_score",
                "decision_action",
                "reasoning",
                "account_size",
                "risk_profile",
                "broker",
                "timezone",
                "strategy_permission",
            ],
        )
        writer.writeheader()
        if selected is None or selected_contract is None:
            writer.writerow(
                {
                    "ticker": "",
                    "company_name": "",
                    "strategy": "",
                    "option_type": "",
                    "position_side": "",
                    "strike": "",
                    "expiry": "",
                    "entry_price": "",
                    "quantity": "",
                    "estimated_max_loss": "",
                    "confidence_score": decision.final_score or 0,
                    "decision_action": decision.action,
                    "reasoning": decision.reasoning,
                    "account_size": dec(inputs.account_size),
                    "risk_profile": inputs.risk_profile,
                    "broker": inputs.broker,
                    "timezone": inputs.timezone_label,
                    "strategy_permission": inputs.strategy_permission,
                }
            )
            return

        sizing = selected.sizing or fallback_sizing(selected_contract.contract.position_side)
        quantity = 0 if decision.action == "watchlist" else sizing.quantity
        writer.writerow(
            {
                "ticker": selected.record.ticker,
                "company_name": selected.context.company_name,
                "strategy": selected_contract.strategy,
                "option_type": selected_contract.contract.option_type,
                "position_side": selected_contract.contract.position_side,
                "strike": dec(selected_contract.contract.strike),
                "expiry": selected_contract.contract.expiry.isoformat(),
                "entry_price": dec(selected_contract.contract.ask or selected_contract.contract.mid),
                "quantity": quantity,
                "estimated_max_loss": sizing.max_loss_text,
                "confidence_score": decision.final_score or selected.evaluation.final_score,
                "decision_action": decision.action,
                "reasoning": decision.reasoning,
                "account_size": dec(inputs.account_size),
                "risk_profile": inputs.risk_profile,
                "broker": inputs.broker,
                "timezone": inputs.timezone_label,
                "strategy_permission": inputs.strategy_permission,
            }
        )


def write_final_target_option_csv(selected, selected_contract) -> None:
    path = RESULTS_DIR / f"soroush-final-traget-option-{RUN_DATE}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ticker",
                "strategy",
                "target_method",
                "target_stock_price",
                "target_option_price",
                "target_gain_percent",
                "stop_loss_option_price",
                "exit_by_date",
                "expected_holding_days",
                "delta",
                "gamma",
                "theta",
                "vega",
                "implied_volatility",
            ],
        )
        writer.writeheader()
        if selected is None or selected_contract is None or selected_contract.exit_target is None:
            writer.writerow({key: "" for key in writer.fieldnames or []})
            return
        target = selected_contract.exit_target
        writer.writerow(
            {
                "ticker": selected.record.ticker,
                "strategy": selected_contract.strategy,
                "target_method": target.target_method,
                "target_stock_price": dec(target.target_stock_price),
                "target_option_price": dec(target.target_option_price),
                "target_gain_percent": dec(target.target_gain_percent),
                "stop_loss_option_price": dec(target.stop_loss_option_price),
                "exit_by_date": target.exit_by_date.isoformat(),
                "expected_holding_days": target.expected_holding_days,
                "delta": dec(selected_contract.contract.delta),
                "gamma": dec(selected_contract.contract.gamma),
                "theta": dec(selected_contract.contract.theta),
                "vega": dec(selected_contract.contract.vega),
                "implied_volatility": dec(selected_contract.contract.implied_volatility),
            }
        )


def fallback_market_snapshot(record: CandidateRecord, *, error: str) -> MarketSnapshot:
    return MarketSnapshot(
        ticker=record.ticker,
        as_of_date=record.earnings_date,
        company_name=record.company_name,
        sector=record.sector,
        sector_etf=None,
        market_cap=record.market_cap,
        current_price=record.current_price,
        latest_volume=record.volume,
        average_volume_20d=None,
        volume_vs_average_20d=None,
        stock_returns=ReturnMetrics(None, None, None, None),
        spy_returns=ReturnMetrics(None, None, None, None),
        qqq_returns=ReturnMetrics(None, None, None, None),
        sector_returns=None,
        relative_strength_vs_spy=None,
        relative_strength_vs_qqq=None,
        relative_strength_vs_sector=None,
        av_news_sentiment=None,
        price_source="candidate_fallback",
        overview_source="candidate_fallback",
        sources=("candidate_selection",),
        confidence_adjustment=-20,
        confidence_notes=(
            ConfidenceNote(
                source="pipeline",
                field="market_data",
                detail=error,
                severity="warning",
                score_delta=-20,
            ),
        ),
    )


def fallback_news_bundle(record: CandidateRecord, *, error: str) -> NewsBundle:
    return NewsBundle(
        ticker=record.ticker,
        company_name=record.company_name,
        generated_at=datetime.now(tz=timezone.utc),
        search_results=(),
        articles=(),
        brief=NewsBrief(
            bullish_evidence=[],
            bearish_evidence=[],
            neutral_contextual_evidence=["Recent coverage was unavailable during this run."],
            key_uncertainty=error,
            news_confidence=25,
        ),
        used_ir_fallback=False,
        used_llm_summary=False,
    )


def fallback_sizing(position_side: str) -> SizingResult:
    return SizingResult(
        quantity=0,
        max_loss_text=(
            BROKER_MARGIN_DEPENDENT_TEXT if position_side == "short" else "Sizing unavailable."
        ),
        account_risk_pct=ZERO,
        broker_verification_required=True,
        watch_only=True,
    )


def dec(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


if __name__ == "__main__":
    asyncio.run(main())
