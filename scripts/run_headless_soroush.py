from __future__ import annotations

import asyncio
import csv
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.core.config import get_settings
from app.llm.types import LLMAuthenticationError
from app.pipeline.steps.decide import get_default_decision_step, resolve_selected_contract
from app.pipeline.steps.market_data import MarketDataFetchStep
from app.pipeline.steps.news import NewsBriefStep
from app.pipeline.steps.options import OptionsFetchStep
from app.pipeline.steps.scoring import CandidateScoringStep
from app.pipeline.steps.sizing import PositionSizingStep
from app.pipeline.types import PipelineCandidate
from app.scoring.types import CandidateContext, ContractScoreResult, UserContext, option_mid
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
RESULTS_DIR = Path(r"C:\Users\sseif\Desktop\Earning-Edge-main\results")


@dataclass(slots=True, frozen=True)
class RunInputs:
    account_size: Decimal
    risk_profile: str
    timezone_label: str
    timezone_iana: str
    broker: str
    strategy_permission: str
    max_contracts: int
    openrouter_api_key: str
    alpha_vantage_api_key: str | None
    alpaca_api_key: str | None
    alpaca_api_secret: str | None
    results_tag: str
    run_stamp: str

    @classmethod
    def from_env(cls) -> RunInputs:
        return cls(
            account_size=_env_decimal("HEADLESS_ACCOUNT_SIZE", Decimal("10000.00")),
            risk_profile=os.environ.get("HEADLESS_RISK_PROFILE", "Balanced").strip() or "Balanced",
            timezone_label=os.environ.get("HEADLESS_TIMEZONE_LABEL", "ET").strip() or "ET",
            timezone_iana=(
                os.environ.get("HEADLESS_TIMEZONE_IANA", "America/Toronto").strip()
                or "America/Toronto"
            ),
            broker=os.environ.get("HEADLESS_BROKER", "Wealthsimple").strip() or "Wealthsimple",
            strategy_permission=(
                os.environ.get("HEADLESS_STRATEGY_PERMISSION", "long_and_short").strip()
                or "long_and_short"
            ),
            max_contracts=_env_int("HEADLESS_MAX_CONTRACTS", 3),
            openrouter_api_key=os.environ.get("HEADLESS_OPENROUTER_API_KEY", "").strip(),
            alpha_vantage_api_key=_optional_env("HEADLESS_ALPHA_VANTAGE_API_KEY"),
            alpaca_api_key=_optional_env("HEADLESS_ALPACA_API_KEY"),
            alpaca_api_secret=_optional_env("HEADLESS_ALPACA_API_SECRET"),
            results_tag=os.environ.get("HEADLESS_RESULTS_TAG", "soroush").strip() or "soroush",
            run_stamp=(
                os.environ.get("HEADLESS_RUN_STAMP", "").strip()
                or datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
            ),
        )


async def main() -> None:
    settings = get_settings()
    inputs = RunInputs.from_env()

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
    decision_step = get_default_decision_step(settings=settings)

    batch = await candidate_service.get_candidates()
    user_context = UserContext(
        account_size=inputs.account_size,
        risk_profile=inputs.risk_profile,  # type: ignore[arg-type]
        strategy_permission=inputs.strategy_permission,  # type: ignore[arg-type]
        max_contracts=inputs.max_contracts,
        has_valid_openrouter_api_key=bool(inputs.openrouter_api_key),
    )

    preliminary_candidates = [
        await analyze_candidate(
            record=record,
            user_context=user_context,
            market_step=market_step,
            news_step=news_step,
            options_step=options_step,
            scoring_step=scoring_step,
            sizing_step=sizing_step,
            inputs=inputs,
            live_news=False,
        )
        for record in batch.candidates
    ]

    preliminary_finalists = rank_candidates(preliminary_candidates)[:DECISION_FINALIST_LIMIT]
    refreshed_finalists = [
        await analyze_candidate(
            record=item.record,
            user_context=user_context,
            market_step=market_step,
            news_step=news_step,
            options_step=options_step,
            scoring_step=scoring_step,
            sizing_step=sizing_step,
            inputs=inputs,
            live_news=True,
        )
        for item in preliminary_finalists
    ]

    finalists_by_ticker = {item.record.ticker: item for item in refreshed_finalists}
    candidates = [
        finalists_by_ticker.get(item.record.ticker, item) for item in preliminary_candidates
    ]
    decision_candidates = rank_candidates(refreshed_finalists or preliminary_finalists)[
        :DECISION_FINALIST_LIMIT
    ]
    decision_result = await decision_step.execute(
        decision_candidates,
        user_context,
        openrouter_api_key=inputs.openrouter_api_key,
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
    finalist_tickers = {item.record.ticker for item in decision_candidates}
    write_inputs_csv(inputs)
    write_strategies_csv(batch, inputs)
    write_candidates_csv(batch, candidates, finalist_tickers, inputs)
    write_market_csv(candidates, finalist_tickers, inputs)
    write_news_summary_csv(candidates, finalist_tickers, inputs)
    write_news_articles_csv(candidates, finalist_tickers, inputs)
    write_scoring_csv(candidates, finalist_tickers, inputs)
    write_scoring_factors_csv(candidates, finalist_tickers, inputs)
    write_options_csv(candidates, selected_contract, finalist_tickers, inputs)
    write_decision_csv(
        candidates=candidates,
        decision_candidates=decision_candidates,
        selected=selected,
        selected_contract=selected_contract,
        decision_result=decision_result,
        inputs=inputs,
    )
    write_final_option_csv(selected, selected_contract, decision_result.decision, inputs)
    write_final_target_option_csv(selected, selected_contract, inputs)

    print(f"batch_status={batch.screener_status}")
    print(f"candidates={len(candidates)}")
    print(f"finalists={len(decision_candidates)}")
    print(f"decision_engine={decision_result.trace.engine}")
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
    live_news: bool,
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

    if live_news:
        try:
            news_bundle = await news_step.execute(
                record,
                openrouter_api_key=inputs.openrouter_api_key,
            )
        except LLMAuthenticationError as exc:
            calculation_errors.append(f"News fallback used: {exc}")
            news_bundle = fallback_news_bundle(record, error=str(exc))
        except Exception as exc:
            calculation_errors.append(f"News fallback used: {exc}")
            news_bundle = fallback_news_bundle(record, error=str(exc))
    else:
        news_bundle = deferred_news_bundle(record)

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
        identity_verified=bool(
            record.ticker and (record.company_name or market_snapshot.company_name)
        ),
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


def write_inputs_csv(inputs: RunInputs) -> None:
    write_csv(
        result_path(inputs, "inputs"),
        [
            "run_stamp",
            "account_size",
            "risk_profile",
            "timezone_label",
            "timezone_iana",
            "broker",
            "strategy_permission",
            "max_contracts",
            "openrouter_key_present",
            "alpha_vantage_key_present",
            "alpaca_key_present",
            "alpaca_secret_present",
        ],
        [
            {
                "run_stamp": inputs.run_stamp,
                "account_size": dec(inputs.account_size),
                "risk_profile": inputs.risk_profile,
                "timezone_label": inputs.timezone_label,
                "timezone_iana": inputs.timezone_iana,
                "broker": inputs.broker,
                "strategy_permission": inputs.strategy_permission,
                "max_contracts": str(inputs.max_contracts),
                "openrouter_key_present": yesno(bool(inputs.openrouter_api_key)),
                "alpha_vantage_key_present": yesno(bool(inputs.alpha_vantage_api_key)),
                "alpaca_key_present": yesno(bool(inputs.alpaca_api_key)),
                "alpaca_secret_present": yesno(bool(inputs.alpaca_api_secret)),
            }
        ],
    )


def write_candidates_csv(
    batch: CandidateBatch,
    candidates: list[PipelineCandidate],
    finalist_tickers: set[str],
    inputs: RunInputs,
) -> None:
    ranked = rank_candidates(candidates)
    rows = []
    for index, item in enumerate(ranked, start=1):
        rows.append(
            {
                "combined_rank": str(index),
                "ticker": item.record.ticker,
                "company_name": item.context.company_name,
                "strategy_source": item.record.strategy_source or "",
                "screener_rank": intstr(item.record.screener_rank),
                "finalist": yesno(item.record.ticker in finalist_tickers),
                "current_price": dec(item.context.market_snapshot.current_price),
                "earnings_date": item.context.earnings_date.isoformat(),
                "direction": item.evaluation.direction.classification,
                "direction_score": str(item.evaluation.direction.score),
                "data_confidence_score": str(item.evaluation.confidence.score),
                "final_opportunity_score": str(item.evaluation.final_score),
                "best_strategy": (
                    ""
                    if item.evaluation.chosen_contract is None
                    else item.evaluation.chosen_contract.strategy
                ),
                "candidate_action": item.evaluation.action,
                "candidate_sources": "|".join(item.record.sources),
                "warning_text": batch.warning_text or "",
                "calculation_errors": "|".join(item.context.calculation_errors),
            }
        )
    write_csv(
        result_path(inputs, "candidates"),
        [
            "combined_rank",
            "ticker",
            "company_name",
            "strategy_source",
            "screener_rank",
            "finalist",
            "current_price",
            "earnings_date",
            "direction",
            "direction_score",
            "data_confidence_score",
            "final_opportunity_score",
            "best_strategy",
            "candidate_action",
            "candidate_sources",
            "warning_text",
            "calculation_errors",
        ],
        rows,
    )


def write_strategies_csv(batch: CandidateBatch, inputs: RunInputs) -> None:
    rows = []
    for report in batch.strategy_reports:
        rows.append(
            {
                "strategy_source": report.strategy_source,
                "strategy_label": report.strategy_label,
                "status": report.status,
                "provider": report.provider,
                "raw_row_count": str(report.raw_row_count),
                "candidate_count": str(report.candidate_count),
                "finviz_candidate_count": str(report.finviz_candidate_count),
                "backup_candidate_count": str(report.backup_candidate_count),
                "fallback_used": yesno(report.fallback_used),
                "query_urls": "|".join(report.query_urls),
                "filter_codes": "|".join(report.filter_codes),
                "criteria_summary": report.criteria_summary or "",
                "sort_summary": report.sort_summary or "",
                "warning_text": report.warning_text or "",
                "error": report.error or "",
            }
        )
    write_csv(
        result_path(inputs, "strategies"),
        [
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
        rows,
    )


def write_market_csv(
    candidates: list[PipelineCandidate],
    finalist_tickers: set[str],
    inputs: RunInputs,
) -> None:
    rows = []
    for item in rank_candidates(candidates):
        snapshot = item.context.market_snapshot
        rows.append(
            {
                "ticker": item.record.ticker,
                "finalist": yesno(item.record.ticker in finalist_tickers),
                "company_name": snapshot.company_name or item.context.company_name,
                "as_of_date": snapshot.as_of_date.isoformat(),
                "sector": snapshot.sector or "",
                "sector_etf": snapshot.sector_etf or "",
                "market_cap": dec(snapshot.market_cap),
                "current_price": dec(snapshot.current_price),
                "latest_volume": intstr(snapshot.latest_volume),
                "average_volume_20d": dec(snapshot.average_volume_20d),
                "volume_vs_average_20d": dec(snapshot.volume_vs_average_20d),
                "stock_return_1d": dec(snapshot.stock_returns.one_day),
                "stock_return_5d": dec(snapshot.stock_returns.five_day),
                "stock_return_20d": dec(snapshot.stock_returns.twenty_day),
                "stock_return_50d": dec(snapshot.stock_returns.fifty_day),
                "relative_strength_vs_spy": dec(snapshot.relative_strength_vs_spy),
                "relative_strength_vs_qqq": dec(snapshot.relative_strength_vs_qqq),
                "relative_strength_vs_sector": dec(snapshot.relative_strength_vs_sector),
                "price_source": snapshot.price_source,
                "overview_source": snapshot.overview_source,
                "sources": "|".join(snapshot.sources),
                "confidence_adjustment": str(snapshot.confidence_adjustment),
                "confidence_notes": "|".join(note.detail for note in snapshot.confidence_notes),
            }
        )
    write_csv(
        result_path(inputs, "market"),
        [
            "ticker",
            "finalist",
            "company_name",
            "as_of_date",
            "sector",
            "sector_etf",
            "market_cap",
            "current_price",
            "latest_volume",
            "average_volume_20d",
            "volume_vs_average_20d",
            "stock_return_1d",
            "stock_return_5d",
            "stock_return_20d",
            "stock_return_50d",
            "relative_strength_vs_spy",
            "relative_strength_vs_qqq",
            "relative_strength_vs_sector",
            "price_source",
            "overview_source",
            "sources",
            "confidence_adjustment",
            "confidence_notes",
        ],
        rows,
    )


def write_news_summary_csv(
    candidates: list[PipelineCandidate],
    finalist_tickers: set[str],
    inputs: RunInputs,
) -> None:
    rows = []
    for item in rank_candidates(candidates):
        bundle = item.news_bundle
        brief = bundle.brief
        rows.append(
            {
                "ticker": item.record.ticker,
                "finalist": yesno(item.record.ticker in finalist_tickers),
                "generated_at": bundle.generated_at.isoformat(),
                "article_count": str(len(bundle.articles)),
                "search_result_count": str(len(bundle.search_results)),
                "used_ir_fallback": yesno(bundle.used_ir_fallback),
                "used_llm_summary": yesno(bundle.used_llm_summary),
                "news_confidence": str(brief.news_confidence),
                "bullish_evidence": " | ".join(brief.bullish_evidence),
                "bearish_evidence": " | ".join(brief.bearish_evidence),
                "neutral_context": " | ".join(brief.neutral_contextual_evidence),
                "key_uncertainty": brief.key_uncertainty,
            }
        )
    write_csv(
        result_path(inputs, "news_summary"),
        [
            "ticker",
            "finalist",
            "generated_at",
            "article_count",
            "search_result_count",
            "used_ir_fallback",
            "used_llm_summary",
            "news_confidence",
            "bullish_evidence",
            "bearish_evidence",
            "neutral_context",
            "key_uncertainty",
        ],
        rows,
    )


def write_news_articles_csv(
    candidates: list[PipelineCandidate],
    finalist_tickers: set[str],
    inputs: RunInputs,
) -> None:
    rows = []
    for item in rank_candidates(candidates):
        for index, article in enumerate(item.news_bundle.articles, start=1):
            rows.append(
                {
                    "ticker": item.record.ticker,
                    "finalist": yesno(item.record.ticker in finalist_tickers),
                    "article_rank": str(index),
                    "title": article.title,
                    "source": article.source or "",
                    "published_at": "" if article.published_at is None else article.published_at.isoformat(),
                    "url": article.url,
                    "snippet": article.snippet,
                    "is_ir_fallback": yesno(article.is_ir_fallback),
                }
            )
    write_csv(
        result_path(inputs, "news_articles"),
        [
            "ticker",
            "finalist",
            "article_rank",
            "title",
            "source",
            "published_at",
            "url",
            "snippet",
            "is_ir_fallback",
        ],
        rows,
    )


def write_scoring_csv(
    candidates: list[PipelineCandidate],
    finalist_tickers: set[str],
    inputs: RunInputs,
) -> None:
    rows = []
    for item in rank_candidates(candidates):
        chosen = item.evaluation.chosen_contract
        rows.append(
            {
                "ticker": item.record.ticker,
                "finalist": yesno(item.record.ticker in finalist_tickers),
                "direction_classification": item.evaluation.direction.classification,
                "direction_bias": dec(item.evaluation.direction.bias),
                "direction_score": str(item.evaluation.direction.score),
                "data_confidence_score": str(item.evaluation.confidence.score),
                "data_confidence_label": item.evaluation.confidence.label,
                "final_opportunity_score": str(item.evaluation.final_score),
                "candidate_action": item.evaluation.action,
                "best_strategy": "" if chosen is None else chosen.strategy,
                "chosen_contract_score": "" if chosen is None else str(chosen.score),
                "confidence_blockers": " | ".join(item.evaluation.confidence.blockers),
                "confidence_notes": " | ".join(item.evaluation.confidence.notes),
                "evaluation_reasons": " | ".join(item.evaluation.reasons),
                "calculation_errors": " | ".join(item.context.calculation_errors),
            }
        )
    write_csv(
        result_path(inputs, "scoring"),
        [
            "ticker",
            "finalist",
            "direction_classification",
            "direction_bias",
            "direction_score",
            "data_confidence_score",
            "data_confidence_label",
            "final_opportunity_score",
            "candidate_action",
            "best_strategy",
            "chosen_contract_score",
            "confidence_blockers",
            "confidence_notes",
            "evaluation_reasons",
            "calculation_errors",
        ],
        rows,
    )


def write_scoring_factors_csv(
    candidates: list[PipelineCandidate],
    finalist_tickers: set[str],
    inputs: RunInputs,
) -> None:
    rows = []
    for item in rank_candidates(candidates):
        for factor in item.evaluation.direction.factors:
            rows.append(
                {
                    "ticker": item.record.ticker,
                    "finalist": yesno(item.record.ticker in finalist_tickers),
                    "factor_name": factor.name,
                    "factor_score": str(factor.score),
                    "factor_weight": str(factor.weight),
                    "factor_detail": factor.detail,
                }
            )
    write_csv(
        result_path(inputs, "scoring_factors"),
        ["ticker", "finalist", "factor_name", "factor_score", "factor_weight", "factor_detail"],
        rows,
    )


def write_options_csv(
    candidates: list[PipelineCandidate],
    selected_contract: ContractScoreResult | None,
    finalist_tickers: set[str],
    inputs: RunInputs,
) -> None:
    rows = []
    for item in rank_candidates(candidates):
        for contract in item.evaluation.considered_contracts:
            rows.append(
                {
                    "ticker": item.record.ticker,
                    "finalist": yesno(item.record.ticker in finalist_tickers),
                    "selected_contract": yesno(_contract_matches(contract, selected_contract)),
                    "strategy": contract.strategy,
                    "option_type": contract.contract.option_type,
                    "position_side": contract.contract.position_side,
                    "strike": dec(contract.contract.strike),
                    "expiry": contract.contract.expiry.isoformat(),
                    "bid": dec(contract.contract.bid),
                    "ask": dec(contract.contract.ask),
                    "mid": dec(option_mid(contract.contract)),
                    "volume": intstr(contract.contract.volume),
                    "open_interest": intstr(contract.contract.open_interest),
                    "implied_volatility": dec(contract.contract.implied_volatility),
                    "delta": dec(contract.contract.delta),
                    "gamma": dec(contract.contract.gamma),
                    "theta": dec(contract.contract.theta),
                    "vega": dec(contract.contract.vega),
                    "liquidity_score": str(contract.liquidity_score),
                    "contract_score": str(contract.score),
                    "is_viable": yesno(contract.is_viable),
                    "vetoes": " | ".join(veto.reason for veto in contract.vetoes),
                    "reasons": " | ".join(contract.reasons),
                    "target_method": "" if contract.exit_target is None else contract.exit_target.target_method,
                    "target_stock_price": "" if contract.exit_target is None else dec(contract.exit_target.target_stock_price),
                    "target_option_price": "" if contract.exit_target is None else dec(contract.exit_target.target_option_price),
                    "stop_loss_option_price": "" if contract.exit_target is None else dec(contract.exit_target.stop_loss_option_price),
                    "exit_by_date": "" if contract.exit_target is None else contract.exit_target.exit_by_date.isoformat(),
                }
            )
    write_csv(
        result_path(inputs, "options"),
        [
            "ticker",
            "finalist",
            "selected_contract",
            "strategy",
            "option_type",
            "position_side",
            "strike",
            "expiry",
            "bid",
            "ask",
            "mid",
            "volume",
            "open_interest",
            "implied_volatility",
            "delta",
            "gamma",
            "theta",
            "vega",
            "liquidity_score",
            "contract_score",
            "is_viable",
            "vetoes",
            "reasons",
            "target_method",
            "target_stock_price",
            "target_option_price",
            "stop_loss_option_price",
            "exit_by_date",
        ],
        rows,
    )


def write_decision_csv(
    *,
    candidates: list[PipelineCandidate],
    decision_candidates: list[PipelineCandidate],
    selected: PipelineCandidate | None,
    selected_contract: ContractScoreResult | None,
    decision_result,
    inputs: RunInputs,
) -> None:
    write_csv(
        result_path(inputs, "decision"),
        [
            "decision_engine",
            "heavy_model_used",
            "trace_notes",
            "decision_action",
            "chosen_ticker",
            "chosen_contract_option_type",
            "chosen_contract_position_side",
            "chosen_contract_strike",
            "chosen_contract_expiry",
            "direction_score",
            "contract_score",
            "final_score",
            "reasoning",
            "key_evidence",
            "key_concerns",
            "watchlist_tickers",
            "decision_finalists",
            "selected_contract_strategy",
            "selected_contract_score",
        ],
        [
            {
                "decision_engine": decision_result.trace.engine,
                "heavy_model_used": decision_result.trace.heavy_model_used or "",
                "trace_notes": " | ".join(decision_result.trace.notes),
                "decision_action": decision_result.decision.action,
                "chosen_ticker": decision_result.decision.chosen_ticker or "",
                "chosen_contract_option_type": (
                    ""
                    if decision_result.decision.chosen_contract is None
                    else decision_result.decision.chosen_contract.option_type
                ),
                "chosen_contract_position_side": (
                    ""
                    if decision_result.decision.chosen_contract is None
                    else decision_result.decision.chosen_contract.position_side
                ),
                "chosen_contract_strike": (
                    ""
                    if decision_result.decision.chosen_contract is None
                    else dec(decision_result.decision.chosen_contract.strike)
                ),
                "chosen_contract_expiry": (
                    ""
                    if decision_result.decision.chosen_contract is None
                    else decision_result.decision.chosen_contract.expiry.isoformat()
                ),
                "direction_score": intstr(decision_result.decision.direction_score),
                "contract_score": intstr(decision_result.decision.contract_score),
                "final_score": intstr(decision_result.decision.final_score),
                "reasoning": decision_result.decision.reasoning,
                "key_evidence": " | ".join(decision_result.decision.key_evidence),
                "key_concerns": " | ".join(decision_result.decision.key_concerns),
                "watchlist_tickers": " | ".join(decision_result.decision.watchlist_tickers),
                "decision_finalists": " | ".join(item.record.ticker for item in decision_candidates),
                "selected_contract_strategy": "" if selected_contract is None else selected_contract.strategy,
                "selected_contract_score": "" if selected_contract is None else str(selected_contract.score),
            }
        ],
    )


def write_final_option_csv(
    selected: PipelineCandidate | None,
    selected_contract: ContractScoreResult | None,
    decision,
    inputs: RunInputs,
) -> None:
    rows: list[dict[str, str]] = []
    if selected is None or selected_contract is None:
        rows.append(
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
                "confidence_score": intstr(decision.final_score),
                "decision_action": decision.action,
                "reasoning": decision.reasoning,
                "account_size": dec(inputs.account_size),
                "risk_profile": inputs.risk_profile,
                "broker": inputs.broker,
                "timezone": inputs.timezone_label,
                "strategy_permission": inputs.strategy_permission,
            }
        )
    else:
        sizing = selected.sizing or fallback_sizing(selected_contract.contract.position_side)
        quantity = 0 if decision.action == "watchlist" else sizing.quantity
        rows.append(
            {
                "ticker": selected.record.ticker,
                "company_name": selected.context.company_name,
                "strategy": selected_contract.strategy,
                "option_type": selected_contract.contract.option_type,
                "position_side": selected_contract.contract.position_side,
                "strike": dec(selected_contract.contract.strike),
                "expiry": selected_contract.contract.expiry.isoformat(),
                "entry_price": dec(selected_contract.contract.ask or option_mid(selected_contract.contract)),
                "quantity": str(quantity),
                "estimated_max_loss": sizing.max_loss_text,
                "confidence_score": str(decision.final_score or selected.evaluation.final_score),
                "decision_action": decision.action,
                "reasoning": decision.reasoning,
                "account_size": dec(inputs.account_size),
                "risk_profile": inputs.risk_profile,
                "broker": inputs.broker,
                "timezone": inputs.timezone_label,
                "strategy_permission": inputs.strategy_permission,
            }
        )
    write_csv(
        result_path(inputs, "final_option"),
        [
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
        rows,
    )


def write_final_target_option_csv(
    selected: PipelineCandidate | None,
    selected_contract: ContractScoreResult | None,
    inputs: RunInputs,
) -> None:
    if selected is None or selected_contract is None or selected_contract.exit_target is None:
        rows = [
            {
                "ticker": "",
                "strategy": "",
                "target_method": "",
                "target_stock_price": "",
                "target_option_price": "",
                "target_gain_percent": "",
                "stop_loss_option_price": "",
                "exit_by_date": "",
                "expected_holding_days": "",
                "delta": "",
                "gamma": "",
                "theta": "",
                "vega": "",
                "implied_volatility": "",
            }
        ]
    else:
        target = selected_contract.exit_target
        rows = [
            {
                "ticker": selected.record.ticker,
                "strategy": selected_contract.strategy,
                "target_method": target.target_method,
                "target_stock_price": dec(target.target_stock_price),
                "target_option_price": dec(target.target_option_price),
                "target_gain_percent": dec(target.target_gain_percent),
                "stop_loss_option_price": dec(target.stop_loss_option_price),
                "exit_by_date": target.exit_by_date.isoformat(),
                "expected_holding_days": str(target.expected_holding_days),
                "delta": dec(selected_contract.contract.delta),
                "gamma": dec(selected_contract.contract.gamma),
                "theta": dec(selected_contract.contract.theta),
                "vega": dec(selected_contract.contract.vega),
                "implied_volatility": dec(selected_contract.contract.implied_volatility),
            }
        ]
    write_csv(
        result_path(inputs, "final_target_option"),
        [
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
        rows,
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


def deferred_news_bundle(record: CandidateRecord) -> NewsBundle:
    return NewsBundle(
        ticker=record.ticker,
        company_name=record.company_name,
        generated_at=datetime.now(tz=timezone.utc),
        search_results=(),
        articles=(),
        brief=NewsBrief(
            bullish_evidence=[],
            bearish_evidence=[],
            neutral_contextual_evidence=[
                "News was deferred during preliminary ranking and only fetched for finalists."
            ],
            key_uncertainty="Live news was not fetched for this candidate in the first pass.",
            news_confidence=25,
        ),
        used_ir_fallback=False,
        used_llm_summary=False,
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


def rank_candidates(candidates: list[PipelineCandidate]) -> list[PipelineCandidate]:
    return sorted(
        candidates,
        key=lambda item: (
            item.evaluation.final_score,
            item.evaluation.confidence.score,
            item.evaluation.direction.score,
        ),
        reverse=True,
    )


def result_path(inputs: RunInputs, step: str) -> Path:
    return RESULTS_DIR / f"{inputs.results_tag}_{step}_{inputs.run_stamp}.csv"


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def yesno(value: bool) -> str:
    return "true" if value else "false"


def dec(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def intstr(value: int | None) -> str:
    return "" if value is None else str(value)


def _env_decimal(name: str, default: Decimal) -> Decimal:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a valid decimal value.") from exc


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid integer.") from exc


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _contract_matches(
    left: ContractScoreResult | None,
    right: ContractScoreResult | None,
) -> bool:
    if left is None or right is None:
        return False
    return (
        left.contract.ticker == right.contract.ticker
        and left.contract.option_type == right.contract.option_type
        and left.contract.position_side == right.contract.position_side
        and left.contract.strike == right.contract.strike
        and left.contract.expiry == right.contract.expiry
    )


if __name__ == "__main__":
    asyncio.run(main())
