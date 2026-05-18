from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.db.models.user import User
from app.pipeline.orchestrator import (
    PipelineOrchestrator,
    UserSecrets,
    build_user_context,
    select_decision_finalists,
)
from app.pipeline.steps.decide import HeuristicDecisionStep
from app.pipeline.types import PipelineOutcome
from app.scoring.types import OptionContractInput
from app.services.candidate_models import (
    CandidateBatch,
    CandidateRecord,
    StrategyEventSignal,
    StrategyRunReport,
)
from app.services.market_data.cache import snapshot_from_json, snapshot_to_json
from app.services.market_data.types import MarketSnapshot
from app.services.news.types import NewsBundle


@dataclass(slots=True, frozen=True)
class ReplayCandidateInput:
    record: CandidateRecord
    market_snapshot: MarketSnapshot
    news_bundle: NewsBundle
    option_chain: tuple[OptionContractInput, ...]


@dataclass(slots=True, frozen=True)
class ReplayInput:
    reference_dt_utc: datetime
    reference_trading_date: date | None
    user_profile: dict[str, Any]
    batch: CandidateBatch
    candidates: tuple[ReplayCandidateInput, ...]


@dataclass(slots=True, frozen=True)
class ReplayResult:
    lane: str
    reference_dt_utc: datetime
    reference_trading_date: date | None
    candidate_signature: list[dict[str, Any]]
    decision_candidates: list[str]
    decision: dict[str, Any]
    heuristic_trace: dict[str, Any]

    def hashable_payload(self) -> dict[str, Any]:
        return {
            "candidate_signature": self.candidate_signature,
            "decision_candidates": self.decision_candidates,
            "decision": self.decision,
            "heuristic_trace": self.heuristic_trace,
        }


def capture_replay_input(
    *,
    outcome: PipelineOutcome,
    user: User,
    reference_dt: datetime,
    has_openrouter_key: bool,
) -> ReplayInput:
    candidates = tuple(
        ReplayCandidateInput(
            record=item.record,
            market_snapshot=item.context.market_snapshot,
            news_bundle=item.news_bundle,
            option_chain=item.context.option_chain,
        )
        for item in outcome.candidates
    )
    return ReplayInput(
        reference_dt_utc=reference_dt.astimezone(UTC),
        reference_trading_date=min(
            (
                item.context.valuation_date
                for item in outcome.candidates
                if item.context.valuation_date is not None
            ),
            default=None,
        ),
        user_profile={
            "account_size": _dec(user.account_size),
            "risk_profile": user.risk_profile,
            "broker": user.broker,
            "timezone_label": user.timezone_label,
            "timezone_iana": user.timezone_iana,
            "strategy_permission": user.strategy_permission,
            "max_contracts": user.max_contracts,
            "has_openrouter_key": has_openrouter_key,
        },
        batch=outcome.batch,
        candidates=candidates,
    )


def replay_input_to_json(replay_input: ReplayInput) -> str:
    payload = {
        "reference_dt_utc": replay_input.reference_dt_utc.isoformat(),
        "reference_trading_date": _date(replay_input.reference_trading_date),
        "user_profile": replay_input.user_profile,
        "batch": _batch_to_dict(replay_input.batch),
        "candidates": [_candidate_input_to_dict(item) for item in replay_input.candidates],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def replay_input_from_json(payload: str) -> ReplayInput:
    data = json.loads(payload)
    return ReplayInput(
        reference_dt_utc=datetime.fromisoformat(data["reference_dt_utc"]).astimezone(UTC),
        reference_trading_date=_parse_date(data.get("reference_trading_date")),
        user_profile=dict(data["user_profile"]),
        batch=_batch_from_dict(data["batch"]),
        candidates=tuple(_candidate_input_from_dict(item) for item in data["candidates"]),
    )


async def run_replay(
    replay_input: ReplayInput,
    *,
    lane: str,
) -> ReplayResult:
    data_by_ticker = {item.record.ticker: item for item in replay_input.candidates}
    has_openrouter_key = bool(replay_input.user_profile.get("has_openrouter_key"))
    user = User(
        telegram_chat_id="qa-replay",
        account_size=Decimal(str(replay_input.user_profile["account_size"])),
        risk_profile=replay_input.user_profile["risk_profile"],
        broker=replay_input.user_profile["broker"],
        timezone_label=replay_input.user_profile["timezone_label"],
        timezone_iana=replay_input.user_profile["timezone_iana"],
        strategy_permission=replay_input.user_profile["strategy_permission"],
        max_contracts=int(replay_input.user_profile["max_contracts"]),
        openrouter_api_key_encrypted="qa-replay-placeholder",
    )
    orchestrator = PipelineOrchestrator(
        market_data_step=_ReplayMarketDataStep(data_by_ticker),
        news_step=_ReplayNewsStep(data_by_ticker),
        options_step=_ReplayOptionsStep(data_by_ticker),
        decision_step=HeuristicDecisionStep(),
        notifier=None,
        user_secrets_resolver=lambda _: UserSecrets(
            openrouter_api_key="present" if has_openrouter_key else "",
            alpha_vantage_api_key=None,
            alpaca_api_key=None,
            alpaca_api_secret=None,
        ),
    )
    outcome = await orchestrator.evaluate_batch(
        replay_input.batch,
        user,
        reference_dt=replay_input.reference_dt_utc,
    )
    decision_candidates = select_decision_finalists(list(outcome.candidates))
    user_context = build_user_context(
        user,
        has_valid_openrouter_api_key=has_openrouter_key,
    )
    heuristic = await HeuristicDecisionStep().execute(
        decision_candidates,
        user_context,
        openrouter_api_key="",
    )
    return ReplayResult(
        lane=lane,
        reference_dt_utc=replay_input.reference_dt_utc,
        reference_trading_date=replay_input.reference_trading_date,
        candidate_signature=_candidate_signature(outcome),
        decision_candidates=[item.record.ticker for item in decision_candidates],
        decision=outcome.decision.model_dump(mode="json"),
        heuristic_trace={
            "engine": heuristic.trace.engine,
            "heavy_model_used": heuristic.trace.heavy_model_used,
            "notes": list(heuristic.trace.notes),
            "decision": heuristic.decision.model_dump(mode="json"),
        },
    )


def compare_replay_results(left: ReplayResult, right: ReplayResult) -> dict[str, Any]:
    left_payload = left.hashable_payload()
    right_payload = right.hashable_payload()
    differences = []
    if left.candidate_signature != right.candidate_signature:
        differences.append("candidate_signature")
    if left.decision_candidates != right.decision_candidates:
        differences.append("decision_candidates")
    if left.decision != right.decision:
        differences.append("decision")
    if left.heuristic_trace != right.heuristic_trace:
        differences.append("heuristic_trace")
    return {
        "left_lane": left.lane,
        "right_lane": right.lane,
        "matches": left_payload == right_payload,
        "differences": differences,
        "left": left_payload,
        "right": right_payload,
    }


def replay_result_to_json(result: ReplayResult) -> str:
    payload = {
        "lane": result.lane,
        "reference_dt_utc": result.reference_dt_utc.isoformat(),
        "reference_trading_date": _date(result.reference_trading_date),
        "candidate_signature": result.candidate_signature,
        "decision_candidates": result.decision_candidates,
        "decision": result.decision,
        "heuristic_trace": result.heuristic_trace,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


class _ReplayMarketDataStep:
    def __init__(self, data_by_ticker: dict[str, ReplayCandidateInput]) -> None:
        self.data_by_ticker = data_by_ticker

    async def execute(
        self,
        record: CandidateRecord,
        *,
        alpha_vantage_api_key: str | None,
    ) -> MarketSnapshot:
        del alpha_vantage_api_key
        return self.data_by_ticker[record.ticker].market_snapshot


class _ReplayNewsStep:
    def __init__(self, data_by_ticker: dict[str, ReplayCandidateInput]) -> None:
        self.data_by_ticker = data_by_ticker

    async def execute(
        self,
        record: CandidateRecord,
        *,
        openrouter_api_key: str,
        reference_dt: datetime | None = None,
    ) -> NewsBundle:
        del openrouter_api_key, reference_dt
        return self.data_by_ticker[record.ticker].news_bundle


class _ReplayOptionsStep:
    def __init__(self, data_by_ticker: dict[str, ReplayCandidateInput]) -> None:
        self.data_by_ticker = data_by_ticker

    async def execute(
        self,
        record: CandidateRecord,
        *,
        alpaca_api_key: str | None,
        alpaca_api_secret: str | None,
        strategy_permission: str,
        today: date | None = None,
    ) -> tuple[OptionContractInput, ...]:
        del alpaca_api_key, alpaca_api_secret, strategy_permission, today
        return self.data_by_ticker[record.ticker].option_chain


def _candidate_signature(outcome: PipelineOutcome) -> list[dict[str, Any]]:
    rows = []
    for item in sorted(
        outcome.candidates,
        key=lambda candidate: candidate.record.ticker,
    ):
        chosen = item.evaluation.chosen_contract
        rows.append(
            {
                "ticker": item.record.ticker,
                "strategy_source": item.record.strategy_source,
                "final_score": item.evaluation.final_score,
                "confidence_score": item.evaluation.confidence.score,
                "direction_score": item.evaluation.direction.score,
                "action": item.evaluation.action,
                "chosen_strategy": None if chosen is None else chosen.strategy,
                "chosen_contract": None
                if chosen is None
                else {
                    "option_type": chosen.contract.option_type,
                    "position_side": chosen.contract.position_side,
                    "strike": _dec(chosen.contract.strike),
                    "expiry": _date(chosen.contract.expiry),
                },
                "calculation_errors": list(item.context.calculation_errors),
            }
        )
    return rows


def _candidate_input_to_dict(item: ReplayCandidateInput) -> dict[str, Any]:
    return {
        "record": _record_to_dict(item.record),
        "market_snapshot": json.loads(snapshot_to_json(item.market_snapshot)),
        "news_bundle": item.news_bundle.model_dump(mode="json"),
        "option_chain": [_contract_to_dict(contract) for contract in item.option_chain],
    }


def _candidate_input_from_dict(data: dict[str, Any]) -> ReplayCandidateInput:
    return ReplayCandidateInput(
        record=_record_from_dict(data["record"]),
        market_snapshot=snapshot_from_json(json.dumps(data["market_snapshot"])),
        news_bundle=NewsBundle.model_validate(data["news_bundle"]),
        option_chain=tuple(_contract_from_dict(item) for item in data["option_chain"]),
    )


def _batch_to_dict(batch: CandidateBatch) -> dict[str, Any]:
    return {
        "candidates": [_record_to_dict(item) for item in batch.candidates],
        "screener_status": batch.screener_status,
        "fallback_used": batch.fallback_used,
        "warning_text": batch.warning_text,
        "strategy_reports": [_strategy_report_to_dict(item) for item in batch.strategy_reports],
    }


def _batch_from_dict(data: dict[str, Any]) -> CandidateBatch:
    return CandidateBatch(
        candidates=tuple(_record_from_dict(item) for item in data["candidates"]),
        screener_status=data["screener_status"],
        fallback_used=bool(data["fallback_used"]),
        warning_text=data.get("warning_text"),
        strategy_reports=tuple(
            _strategy_report_from_dict(item) for item in data["strategy_reports"]
        ),
    )


def _record_to_dict(record: CandidateRecord) -> dict[str, Any]:
    return {
        "ticker": record.ticker,
        "company_name": record.company_name,
        "market_cap": _dec(record.market_cap),
        "earnings_date": _date(record.earnings_date),
        "current_price": _dec(record.current_price),
        "earnings_date_verified": record.earnings_date_verified,
        "screener_rank": record.screener_rank,
        "daily_change_percent": _dec(record.daily_change_percent),
        "volume": record.volume,
        "sector": record.sector,
        "sources": list(record.sources),
        "validation_notes": list(record.validation_notes),
        "strategy_source": record.strategy_source,
        "event_signal": _event_signal_to_dict(record.event_signal),
    }


def _record_from_dict(data: dict[str, Any]) -> CandidateRecord:
    return CandidateRecord(
        ticker=data["ticker"],
        company_name=data.get("company_name"),
        market_cap=_parse_decimal(data.get("market_cap")),
        earnings_date=_parse_date(data.get("earnings_date")),
        current_price=_parse_decimal(data.get("current_price")),
        earnings_date_verified=bool(data.get("earnings_date_verified", True)),
        screener_rank=data.get("screener_rank"),
        daily_change_percent=_parse_decimal(data.get("daily_change_percent")),
        volume=data.get("volume"),
        sector=data.get("sector"),
        sources=tuple(data.get("sources", ())),
        validation_notes=tuple(data.get("validation_notes", ())),
        strategy_source=data.get("strategy_source"),
        event_signal=_event_signal_from_dict(data.get("event_signal")),
    )


def _strategy_report_to_dict(report: StrategyRunReport) -> dict[str, Any]:
    return {
        "strategy_source": report.strategy_source,
        "strategy_label": report.strategy_label,
        "provider": report.provider,
        "status": report.status,
        "raw_row_count": report.raw_row_count,
        "candidate_count": report.candidate_count,
        "finviz_candidate_count": report.finviz_candidate_count,
        "backup_candidate_count": report.backup_candidate_count,
        "fallback_used": report.fallback_used,
        "query_urls": list(report.query_urls),
        "filter_codes": list(report.filter_codes),
        "criteria_summary": report.criteria_summary,
        "sort_summary": report.sort_summary,
        "warning_text": report.warning_text,
        "error": report.error,
    }


def _strategy_report_from_dict(data: dict[str, Any]) -> StrategyRunReport:
    return StrategyRunReport(
        strategy_source=data["strategy_source"],
        strategy_label=data["strategy_label"],
        provider=data["provider"],
        status=data["status"],
        raw_row_count=int(data["raw_row_count"]),
        candidate_count=int(data["candidate_count"]),
        finviz_candidate_count=int(data.get("finviz_candidate_count", 0)),
        backup_candidate_count=int(data.get("backup_candidate_count", 0)),
        fallback_used=bool(data.get("fallback_used", False)),
        query_urls=tuple(data.get("query_urls", ())),
        filter_codes=tuple(data.get("filter_codes", ())),
        criteria_summary=data.get("criteria_summary"),
        sort_summary=data.get("sort_summary"),
        warning_text=data.get("warning_text"),
        error=data.get("error"),
    )


def _contract_to_dict(contract: OptionContractInput) -> dict[str, Any]:
    return {
        "ticker": contract.ticker,
        "option_type": contract.option_type,
        "position_side": contract.position_side,
        "strike": _dec(contract.strike),
        "expiry": _date(contract.expiry),
        "bid": _dec(contract.bid),
        "ask": _dec(contract.ask),
        "mid": _dec(contract.mid),
        "volume": contract.volume,
        "open_interest": contract.open_interest,
        "implied_volatility": _dec(contract.implied_volatility),
        "delta": _dec(contract.delta),
        "gamma": _dec(contract.gamma),
        "theta": _dec(contract.theta),
        "vega": _dec(contract.vega),
        "underlying_price": _dec(contract.underlying_price),
        "source": contract.source,
        "quote_timestamp": _date(contract.quote_timestamp),
        "is_tradable": contract.is_tradable,
        "is_stale": contract.is_stale,
    }


def _contract_from_dict(data: dict[str, Any]) -> OptionContractInput:
    return OptionContractInput(
        ticker=data["ticker"],
        option_type=data["option_type"],
        position_side=data["position_side"],
        strike=Decimal(data["strike"]),
        expiry=date.fromisoformat(data["expiry"]),
        bid=_parse_decimal(data.get("bid")),
        ask=_parse_decimal(data.get("ask")),
        mid=_parse_decimal(data.get("mid")),
        volume=data.get("volume"),
        open_interest=data.get("open_interest"),
        implied_volatility=_parse_decimal(data.get("implied_volatility")),
        delta=_parse_decimal(data.get("delta")),
        gamma=_parse_decimal(data.get("gamma")),
        theta=_parse_decimal(data.get("theta")),
        vega=_parse_decimal(data.get("vega")),
        underlying_price=_parse_decimal(data.get("underlying_price")),
        source=data.get("source", "unknown"),
        quote_timestamp=_parse_date(data.get("quote_timestamp")),
        is_tradable=bool(data.get("is_tradable", True)),
        is_stale=bool(data.get("is_stale", False)),
    )


def _event_signal_to_dict(signal: StrategyEventSignal | None) -> dict[str, Any] | None:
    if signal is None:
        return None
    return {
        "score": signal.score,
        "is_supportive": signal.is_supportive,
        "detail": signal.detail,
    }


def _event_signal_from_dict(data: dict[str, Any] | None) -> StrategyEventSignal | None:
    if data is None:
        return None
    return StrategyEventSignal(
        score=int(data["score"]),
        is_supportive=bool(data["is_supportive"]),
        detail=str(data["detail"]),
    )


def _dec(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _parse_decimal(value: str | None) -> Decimal | None:
    return None if value in (None, "") else Decimal(value)


def _date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _parse_date(value: str | None) -> date | None:
    return None if value in (None, "") else date.fromisoformat(value)
