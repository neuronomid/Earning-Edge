from __future__ import annotations

import csv
import getpass
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.config import Settings, get_settings
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.pipeline.types import PipelineCandidate, PipelineOutcome
from app.scoring.types import ContractScoreResult
from app.services.candidate_models import StrategyRunReport
from app.services.strategy_catalog import (
    all_strategy_definitions,
    build_strategy_report,
)

_CSV_COLUMNS = (
    "record_type",
    "run_id",
    "run_local_date",
    "run_started_at",
    "run_finished_at",
    "trigger_type",
    "run_status",
    "screener_status",
    "warning_text",
    "fallback_used",
    "decision_engine",
    "llm_triggered",
    "model_used_heavy",
    "model_used_light",
    "final_decision_action",
    "final_selected_ticker",
    "strategy_source",
    "strategy_label",
    "strategy_status",
    "strategy_provider",
    "strategy_raw_row_count",
    "strategy_candidate_count",
    "strategy_finviz_candidate_count",
    "strategy_backup_candidate_count",
    "strategy_fallback_used",
    "strategy_query_urls",
    "strategy_filter_codes",
    "strategy_criteria_summary",
    "strategy_sort_summary",
    "strategy_note",
    "ticker",
    "company_name",
    "candidate_origin",
    "candidate_sources",
    "data_sources_used",
    "screener_rank",
    "combined_rank",
    "selected_for_final",
    "selected_contract_matches_best_scored",
    "market_cap",
    "current_price",
    "sector",
    "sector_etf",
    "earnings_date",
    "earnings_date_verified",
    "earnings_timing",
    "direction_classification",
    "candidate_direction_score",
    "data_confidence_score",
    "final_opportunity_score",
    "best_strategy",
    "option_contracts_considered",
    "viable_contract_count",
    "stock_return_1d",
    "stock_return_5d",
    "stock_return_20d",
    "stock_return_50d",
    "latest_volume",
    "average_volume_20d",
    "volume_vs_average_20d",
    "relative_strength_vs_spy",
    "relative_strength_vs_qqq",
    "relative_strength_vs_sector",
    "news_used_llm_summary",
    "selected_contract_option_type",
    "selected_contract_position_side",
    "selected_contract_strike",
    "selected_contract_expiry",
    "selected_contract_bid",
    "selected_contract_ask",
    "selected_contract_mid",
    "selected_contract_volume",
    "selected_contract_open_interest",
    "selected_contract_implied_volatility",
    "selected_contract_delta",
    "selected_contract_breakeven",
    "selected_contract_spread_percent",
    "selected_contract_liquidity_score",
    "selected_contract_score",
    "selected_contract_passed_hard_filters",
    "selected_contract_rejection_reason",
    "best_scored_contract_option_type",
    "best_scored_contract_position_side",
    "best_scored_contract_strike",
    "best_scored_contract_expiry",
    "best_scored_contract_score",
    "best_scored_contract_passed_hard_filters",
    "best_scored_contract_rejection_reason",
    "missing_data_fields",
    "validation_notes",
    "scoring_reasons",
    "decision_reasoning",
)


@dataclass(slots=True, frozen=True)
class ExportedResultFiles:
    strategy_a: Path
    strategy_b: Path
    combined: Path
    strategy_paths: dict[str, Path]


class ResultsExportService:
    def __init__(
        self,
        *,
        results_root: Path | str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.results_root = Path("results") if results_root is None else Path(results_root)

    def export_run(
        self,
        *,
        run: WorkflowRun,
        user: User,
        outcome: PipelineOutcome,
        recommendation: Recommendation | None,
    ) -> ExportedResultFiles:
        self.results_root.mkdir(parents=True, exist_ok=True)
        local_date = _run_local_date(run, user)
        username = _export_username()
        ranked = _rank_candidates(outcome.candidates)
        rank_by_ticker = {
            candidate.record.ticker: index for index, candidate in enumerate(ranked, start=1)
        }
        report_by_source = {
            report.strategy_source: report for report in outcome.batch.strategy_reports
        }

        rows_by_source: dict[str, list[dict[str, str]]] = {
            definition.strategy_source: [] for definition in all_strategy_definitions()
        }
        combined_rows: list[dict[str, str]] = []

        for candidate in ranked:
            source = candidate.record.strategy_source or "catalyst_confluence"
            report = report_by_source.get(source)
            if report is None:
                report = build_strategy_report(
                    source,
                    status="success",
                    raw_row_count=0,
                    candidate_count=sum(
                        1
                        for item in outcome.candidates
                        if (item.record.strategy_source or "catalyst_confluence") == source
                    ),
                    finviz_candidate_count=sum(
                        1
                        for item in outcome.candidates
                        if (item.record.strategy_source or "catalyst_confluence") == source
                        and "finviz" in item.record.sources
                    ),
                    backup_candidate_count=sum(
                        1
                        for item in outcome.candidates
                        if (item.record.strategy_source or "catalyst_confluence") == source
                        and "finviz" not in item.record.sources
                    ),
                )
                report_by_source[source] = report
            row = _candidate_row(
                run=run,
                user=user,
                outcome=outcome,
                recommendation=recommendation,
                candidate=candidate,
                report=report,
                combined_rank=rank_by_ticker[candidate.record.ticker],
                settings=self.settings,
            )
            rows_by_source[source].append(row)
            combined_rows.append(row)

        for definition in all_strategy_definitions():
            if rows_by_source[definition.strategy_source]:
                continue
            report = report_by_source.get(definition.strategy_source)
            if report is None:
                continue
            rows_by_source[definition.strategy_source].append(
                _summary_row(
                    run=run,
                    user=user,
                    outcome=outcome,
                    report=report,
                    settings=self.settings,
                )
            )

        strategy_paths: dict[str, Path] = {}
        for definition in all_strategy_definitions():
            path = self._path_for(
                username=username,
                slug=definition.strategy_slug,
                local_date=local_date,
                run=run,
            )
            _write_csv(path, rows_by_source.get(definition.strategy_source, []))
            strategy_paths[definition.strategy_source] = path

        combined_path = self._path_for(
            username=username,
            slug="combined",
            local_date=local_date,
            run=run,
        )
        _write_csv(combined_path, combined_rows)
        return ExportedResultFiles(
            strategy_a=strategy_paths["catalyst_confluence"],
            strategy_b=strategy_paths["coiled_setup"],
            combined=combined_path,
            strategy_paths=strategy_paths,
        )

    def _path_for(
        self,
        *,
        username: str,
        slug: str,
        local_date: str,
        run: WorkflowRun,
    ) -> Path:
        base = self.results_root / f"{username}_{slug}_{local_date}.csv"
        if not base.exists():
            return base
        return self.results_root / f"{username}_{slug}_{local_date}_{str(run.id)[:8]}.csv"


def _candidate_row(
    *,
    run: WorkflowRun,
    user: User,
    outcome: PipelineOutcome,
    recommendation: Recommendation | None,
    candidate: PipelineCandidate,
    report: StrategyRunReport,
    combined_rank: int,
    settings: Settings,
) -> dict[str, str]:
    snapshot = candidate.context.market_snapshot
    selected = outcome.selected
    selected_contract = (
        outcome.final_contract
        if selected is not None and selected.record.ticker == candidate.record.ticker
        else None
    )
    best_scored = _best_scored_contract(candidate)
    return {
        "record_type": "candidate",
        "run_id": str(run.id),
        "run_local_date": _run_local_date(run, user),
        "run_started_at": _datetime(run.started_at),
        "run_finished_at": _datetime(run.finished_at),
        "trigger_type": run.trigger_type,
        "run_status": run.status,
        "screener_status": outcome.batch.screener_status,
        "warning_text": outcome.batch.warning_text or "",
        "fallback_used": _bool(outcome.batch.fallback_used),
        "decision_engine": outcome.decision_trace.engine,
        "llm_triggered": _bool(outcome.decision_trace.engine == "llm"),
        "model_used_heavy": outcome.decision_trace.heavy_model_used or "",
        "model_used_light": _model_used_light(outcome, settings),
        "final_decision_action": outcome.decision.action,
        "final_selected_ticker": outcome.decision.chosen_ticker or "",
        "strategy_source": report.strategy_source,
        "strategy_label": report.strategy_label,
        "strategy_status": report.status,
        "strategy_provider": report.provider,
        "strategy_raw_row_count": str(report.raw_row_count),
        "strategy_candidate_count": str(report.candidate_count),
        "strategy_finviz_candidate_count": str(report.finviz_candidate_count),
        "strategy_backup_candidate_count": str(report.backup_candidate_count),
        "strategy_fallback_used": _bool(report.fallback_used),
        "strategy_query_urls": "|".join(report.query_urls),
        "strategy_filter_codes": "|".join(report.filter_codes),
        "strategy_criteria_summary": report.criteria_summary or "",
        "strategy_sort_summary": report.sort_summary or "",
        "strategy_note": report.warning_text or report.error or "",
        "ticker": candidate.record.ticker,
        "company_name": candidate.context.company_name,
        "candidate_origin": "finviz_row"
        if "finviz" in candidate.record.sources
        else "backup_source",
        "candidate_sources": "|".join(candidate.record.sources),
        "data_sources_used": "|".join(_data_sources(candidate)),
        "screener_rank": ""
        if candidate.record.screener_rank is None
        else str(candidate.record.screener_rank),
        "combined_rank": str(combined_rank),
        "selected_for_final": _bool(
            selected is not None and selected.record.ticker == candidate.record.ticker
        ),
        "selected_contract_matches_best_scored": _bool(
            _contracts_match(selected_contract, best_scored)
            if selected_contract is not None
            else True
        ),
        "market_cap": _decimal(candidate.record.market_cap or snapshot.market_cap),
        "current_price": _decimal(snapshot.current_price or candidate.record.current_price),
        "sector": snapshot.sector or candidate.record.sector or "",
        "sector_etf": snapshot.sector_etf or "",
        "earnings_date": _date(candidate.context.earnings_date),
        "earnings_date_verified": _bool(candidate.context.verified_earnings_date),
        "earnings_timing": candidate.context.earnings_timing,
        "direction_classification": candidate.evaluation.direction.classification,
        "candidate_direction_score": str(candidate.evaluation.direction.score),
        "data_confidence_score": str(candidate.evaluation.confidence.score),
        "final_opportunity_score": str(candidate.evaluation.final_score),
        "best_strategy": "" if best_scored is None else best_scored.strategy,
        "option_contracts_considered": str(len(candidate.evaluation.considered_contracts)),
        "viable_contract_count": str(
            sum(1 for contract in candidate.evaluation.considered_contracts if contract.is_viable)
        ),
        "stock_return_1d": _decimal(snapshot.stock_returns.one_day),
        "stock_return_5d": _decimal(snapshot.stock_returns.five_day),
        "stock_return_20d": _decimal(snapshot.stock_returns.twenty_day),
        "stock_return_50d": _decimal(snapshot.stock_returns.fifty_day),
        "latest_volume": _int(snapshot.latest_volume),
        "average_volume_20d": _decimal(snapshot.average_volume_20d),
        "volume_vs_average_20d": _decimal(snapshot.volume_vs_average_20d),
        "relative_strength_vs_spy": _decimal(snapshot.relative_strength_vs_spy),
        "relative_strength_vs_qqq": _decimal(snapshot.relative_strength_vs_qqq),
        "relative_strength_vs_sector": _decimal(snapshot.relative_strength_vs_sector),
        "news_used_llm_summary": _bool(candidate.news_bundle.used_llm_summary),
        "selected_contract_option_type": _contract_value(selected_contract, "option_type"),
        "selected_contract_position_side": _contract_value(selected_contract, "position_side"),
        "selected_contract_strike": _contract_nested_decimal(selected_contract, "strike"),
        "selected_contract_expiry": _contract_nested_date(selected_contract, "expiry"),
        "selected_contract_bid": _contract_nested_decimal(selected_contract, "bid"),
        "selected_contract_ask": _contract_nested_decimal(selected_contract, "ask"),
        "selected_contract_mid": _contract_nested_decimal(selected_contract, "mid"),
        "selected_contract_volume": _contract_nested_int(selected_contract, "volume"),
        "selected_contract_open_interest": _contract_nested_int(selected_contract, "open_interest"),
        "selected_contract_implied_volatility": _contract_nested_decimal(
            selected_contract, "implied_volatility"
        ),
        "selected_contract_delta": _contract_nested_decimal(selected_contract, "delta"),
        "selected_contract_breakeven": _decimal(
            None if selected_contract is None else selected_contract.breakeven
        ),
        "selected_contract_spread_percent": _decimal(
            None if selected_contract is None else _contract_spread_percent(selected_contract)
        ),
        "selected_contract_liquidity_score": _contract_int(selected_contract, "liquidity_score"),
        "selected_contract_score": _contract_int(selected_contract, "score"),
        "selected_contract_passed_hard_filters": ""
        if selected_contract is None
        else _bool(not selected_contract.vetoes),
        "selected_contract_rejection_reason": ""
        if selected_contract is None or not selected_contract.vetoes
        else "; ".join(veto.reason for veto in selected_contract.vetoes),
        "best_scored_contract_option_type": _contract_value(best_scored, "option_type"),
        "best_scored_contract_position_side": _contract_value(best_scored, "position_side"),
        "best_scored_contract_strike": _contract_nested_decimal(best_scored, "strike"),
        "best_scored_contract_expiry": _contract_nested_date(best_scored, "expiry"),
        "best_scored_contract_score": _contract_int(best_scored, "score"),
        "best_scored_contract_passed_hard_filters": ""
        if best_scored is None
        else _bool(not best_scored.vetoes),
        "best_scored_contract_rejection_reason": ""
        if best_scored is None or not best_scored.vetoes
        else "; ".join(veto.reason for veto in best_scored.vetoes),
        "missing_data_fields": "|".join(_missing_data_fields(candidate)),
        "validation_notes": "|".join(candidate.record.validation_notes),
        "scoring_reasons": "|".join(candidate.evaluation.reasons),
        "decision_reasoning": recommendation.reasoning_summary
        if recommendation
        else outcome.decision.reasoning,
    }


def _summary_row(
    *,
    run: WorkflowRun,
    user: User,
    outcome: PipelineOutcome,
    report: StrategyRunReport,
    settings: Settings,
) -> dict[str, str]:
    row = {column: "" for column in _CSV_COLUMNS}
    row.update(
        {
            "record_type": "summary",
            "run_id": str(run.id),
            "run_local_date": _run_local_date(run, user),
            "run_started_at": _datetime(run.started_at),
            "run_finished_at": _datetime(run.finished_at),
            "trigger_type": run.trigger_type,
            "run_status": run.status,
            "screener_status": outcome.batch.screener_status,
            "warning_text": outcome.batch.warning_text or "",
            "fallback_used": _bool(outcome.batch.fallback_used),
            "decision_engine": outcome.decision_trace.engine,
            "llm_triggered": _bool(outcome.decision_trace.engine == "llm"),
            "model_used_heavy": outcome.decision_trace.heavy_model_used or "",
            "model_used_light": _model_used_light(outcome, settings),
            "final_decision_action": outcome.decision.action,
            "final_selected_ticker": outcome.decision.chosen_ticker or "",
            "strategy_source": report.strategy_source,
            "strategy_label": report.strategy_label,
            "strategy_status": report.status,
            "strategy_provider": report.provider,
            "strategy_raw_row_count": str(report.raw_row_count),
            "strategy_candidate_count": str(report.candidate_count),
            "strategy_finviz_candidate_count": str(report.finviz_candidate_count),
            "strategy_backup_candidate_count": str(report.backup_candidate_count),
            "strategy_fallback_used": _bool(report.fallback_used),
            "strategy_query_urls": "|".join(report.query_urls),
            "strategy_filter_codes": "|".join(report.filter_codes),
            "strategy_criteria_summary": report.criteria_summary or "",
            "strategy_sort_summary": report.sort_summary or "",
            "strategy_note": report.error
            or report.warning_text
            or "No candidates were stored for this strategy in this run.",
        }
    )
    return row


def _rank_candidates(candidates: tuple[PipelineCandidate, ...]) -> list[PipelineCandidate]:
    return sorted(
        candidates,
        key=lambda item: (
            item.evaluation.final_score,
            item.evaluation.confidence.score,
            item.record.market_cap or Decimal("0"),
        ),
        reverse=True,
    )


def _best_scored_contract(candidate: PipelineCandidate) -> ContractScoreResult | None:
    if candidate.evaluation.chosen_contract is not None:
        return candidate.evaluation.chosen_contract
    if candidate.evaluation.considered_contracts:
        return candidate.evaluation.considered_contracts[0]
    return None


def _missing_data_fields(candidate: PipelineCandidate) -> list[str]:
    missing: list[str] = []
    snapshot = candidate.context.market_snapshot
    if not candidate.context.identity_verified:
        missing.append("company_name")
    if not candidate.context.verified_earnings_date:
        missing.append("earnings_date")
    if candidate.record.market_cap is None and snapshot.market_cap is None:
        missing.append("market_cap")
    if candidate.record.current_price is None and snapshot.current_price is None:
        missing.append("current_price")
    if candidate.context.earnings_timing == "unknown":
        missing.append("earnings_timing")
    if not candidate.context.option_chain:
        missing.append("option_chain")
    if not candidate.news_bundle.articles:
        missing.append("news_articles")
    return missing


def _data_sources(candidate: PipelineCandidate) -> list[str]:
    ordered: list[str] = []
    for value in candidate.record.sources:
        if value not in ordered:
            ordered.append(value)
    for value in candidate.context.market_snapshot.sources:
        if value not in ordered:
            ordered.append(value)
    for item in candidate.news_bundle.search_results:
        if item.source and item.source not in ordered:
            ordered.append(item.source)
    for item in candidate.news_bundle.articles:
        if item.source and item.source not in ordered:
            ordered.append(item.source)
    for contract in candidate.context.option_chain:
        if contract.source and contract.source not in ordered:
            ordered.append(contract.source)
    return ordered


def _contracts_match(left: ContractScoreResult | None, right: ContractScoreResult | None) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return (
        left.contract.ticker == right.contract.ticker
        and left.contract.option_type == right.contract.option_type
        and left.contract.position_side == right.contract.position_side
        and left.contract.strike == right.contract.strike
        and left.contract.expiry == right.contract.expiry
    )


def _contract_spread_percent(contract: ContractScoreResult) -> Decimal | None:
    raw = contract.contract.ask
    if raw is None or contract.contract.bid is None:
        return None
    mid = contract.contract.mid
    if mid is None or mid <= Decimal("0"):
        return None
    return ((raw - contract.contract.bid) / mid) * Decimal("100")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in _CSV_COLUMNS})


def _run_local_date(run: WorkflowRun, user: User) -> str:
    timezone = ZoneInfo(user.timezone_iana)
    base = run.started_at if run.started_at is not None else datetime.now(tz=timezone)
    return base.astimezone(timezone).date().isoformat()


def _export_username() -> str:
    return getpass.getuser().strip().lower().replace(" ", "_")


def _model_used_light(outcome: PipelineOutcome, settings: Settings) -> str:
    for candidate in outcome.candidates:
        if candidate.news_bundle.used_llm_summary and candidate.news_bundle.articles:
            return settings.lightweight_model
    return ""


def _decimal(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def _int(value: int | None) -> str:
    return "" if value is None else str(value)


def _date(value) -> str:
    return "" if value is None else value.isoformat()


def _datetime(value) -> str:
    return "" if value is None else value.isoformat()


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _contract_value(contract: ContractScoreResult | None, field: str) -> str:
    if contract is None:
        return ""
    return str(getattr(contract.contract, field))


def _contract_nested_decimal(contract: ContractScoreResult | None, field: str) -> str:
    if contract is None:
        return ""
    return _decimal(getattr(contract.contract, field))


def _contract_nested_int(contract: ContractScoreResult | None, field: str) -> str:
    if contract is None:
        return ""
    return _int(getattr(contract.contract, field))


def _contract_nested_date(contract: ContractScoreResult | None, field: str) -> str:
    if contract is None:
        return ""
    return _date(getattr(contract.contract, field))


def _contract_int(contract: ContractScoreResult | None, field: str) -> str:
    if contract is None:
        return ""
    return str(getattr(contract, field))
