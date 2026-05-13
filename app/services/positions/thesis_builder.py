from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.candidate import Candidate
from app.db.models.open_position import OpenPosition
from app.db.models.option_contract import OptionContract
from app.db.models.position_thesis import PositionThesis
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.position_thesis_repo import PositionThesisRepository
from app.services.market_hours import market_sessions_between
from app.services.positions.snapshots import PositionQuoteSnapshot


@dataclass(frozen=True, slots=True)
class ContractMetadata:
    underlying_price: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    mid: Decimal | None = None
    implied_volatility: Decimal | None = None
    delta: Decimal | None = None
    gamma: Decimal | None = None
    theta: Decimal | None = None
    vega: Decimal | None = None
    contract_score: int | None = None
    direction_score: int | None = None
    final_score: int | None = None
    data_confidence_score: int | None = None


class PositionThesisBuilder:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_thesis_for_position(
        self,
        *,
        position: OpenPosition,
        recommendation: Recommendation,
        user: User,
        entry_snapshot: PositionQuoteSnapshot | None = None,
        backfilled: bool = False,
    ) -> PositionThesis:
        repo = PositionThesisRepository(self.session)
        existing = await repo.get_for_position(position.id)
        if existing is not None:
            return existing
        thesis = await self.build(
            position=position,
            recommendation=recommendation,
            user=user,
            entry_snapshot=entry_snapshot,
            backfilled=backfilled,
        )
        return await repo.add(thesis)

    async def build(
        self,
        *,
        position: OpenPosition,
        recommendation: Recommendation,
        user: User,
        entry_snapshot: PositionQuoteSnapshot | None = None,
        backfilled: bool = False,
    ) -> PositionThesis:
        run = await self.session.get(WorkflowRun, recommendation.run_id)
        metadata = await self._resolve_contract_metadata(recommendation, run)
        entry_status = _entry_snapshot_status(entry_snapshot, backfilled=backfilled)
        entry_notes = _entry_snapshot_notes(entry_snapshot, backfilled=backfilled)
        news = _news_baseline(run, recommendation, backfilled=backfilled)
        entry_underlying_price = _first_decimal(
            None if entry_snapshot is None else entry_snapshot.underlying_price,
            metadata.underlying_price,
        )
        trajectory = _expected_trajectory(
            position,
            recommendation,
            entry_underlying_price=entry_underlying_price,
        )
        criteria = _invalidation_criteria(
            recommendation=recommendation,
            entry_underlying_price=entry_underlying_price,
            entry_iv=_first_decimal(
                None if entry_snapshot is None else entry_snapshot.implied_volatility,
                metadata.implied_volatility,
            ),
            trajectory=trajectory,
            news_baseline_status=news["status"],
        )
        return PositionThesis(
            open_position_id=position.id,
            recommendation_id=recommendation.id,
            user_id=user.id,
            ticker=recommendation.ticker,
            company_name=recommendation.company_name,
            strategy_source=getattr(
                recommendation,
                "strategy_source",
                "catalyst_confluence",
            ),
            strategy=recommendation.strategy,
            option_type=recommendation.option_type,
            position_side=recommendation.position_side,
            strike=recommendation.strike,
            expiry=recommendation.expiry,
            entered_at=_aware(position.entry_at),
            entry_option_premium=position.entry_price,
            entry_quantity=position.entry_quantity,
            entry_underlying_price=entry_underlying_price,
            entry_option_bid=_first_decimal(
                None if entry_snapshot is None else entry_snapshot.option_bid,
                metadata.bid,
            ),
            entry_option_ask=_first_decimal(
                None if entry_snapshot is None else entry_snapshot.option_ask,
                metadata.ask,
            ),
            entry_option_mid=_first_decimal(
                None if entry_snapshot is None else entry_snapshot.option_mid,
                metadata.mid,
            ),
            entry_implied_volatility=_first_decimal(
                None if entry_snapshot is None else entry_snapshot.implied_volatility,
                metadata.implied_volatility,
            ),
            entry_delta=_first_decimal(
                None if entry_snapshot is None else entry_snapshot.delta,
                metadata.delta,
            ),
            entry_gamma=_first_decimal(
                None if entry_snapshot is None else entry_snapshot.gamma,
                metadata.gamma,
            ),
            entry_theta=_first_decimal(
                None if entry_snapshot is None else entry_snapshot.theta,
                metadata.theta,
            ),
            entry_vega=_first_decimal(
                None if entry_snapshot is None else entry_snapshot.vega,
                metadata.vega,
            ),
            entry_snapshot_source=None if entry_snapshot is None else entry_snapshot.source,
            entry_snapshot_status=entry_status,
            entry_snapshot_notes_json=entry_notes,
            target_option_price=recommendation.target_option_price,
            target_stock_price=recommendation.target_stock_price,
            stop_loss_option_price=recommendation.stop_loss_option_price,
            underlying_stop_price=getattr(recommendation, "underlying_stop_price", None),
            exit_by_date=recommendation.exit_by_date,
            expected_holding_days=recommendation.expected_holding_days,
            expected_move_percent=getattr(recommendation, "expected_move_percent", None),
            expected_trajectory_json=trajectory,
            catalyst_kind="earnings" if recommendation.earnings_date is not None else "none",
            catalyst_event_date=recommendation.earnings_date,
            catalyst_baseline_json={
                "earnings_date": _date_json(recommendation.earnings_date),
                "strategy_source": getattr(
                    recommendation,
                    "strategy_source",
                    "catalyst_confluence",
                ),
            },
            invalidation_criteria_json=criteria,
            direction_score=metadata.direction_score,
            final_score=metadata.final_score,
            contract_score=metadata.contract_score,
            data_confidence_score=metadata.data_confidence_score,
            reasoning_summary=recommendation.reasoning_summary,
            key_evidence_json=recommendation.key_evidence_json or [],
            key_concerns_json=recommendation.key_concerns_json or [],
            news_brief_json=news["brief"],
            news_articles_baseline_json=news["articles"],
            news_coverage=recommendation.news_coverage,
            stale_news=recommendation.stale_news,
            news_published_max_at=news["published_max_at"],
            news_baseline_status=news["status"],
            decision_engine=news["decision_engine"],
            heavy_model_used=news["heavy_model_used"],
        )

    async def _resolve_contract_metadata(
        self,
        recommendation: Recommendation,
        run: WorkflowRun | None,
    ) -> ContractMetadata:
        artifact = _match_contract_artifact(
            () if run is None else tuple(run.option_contracts_json or ()),
            recommendation,
        )
        candidate_card = _match_candidate_card(
            () if run is None else tuple(run.candidate_cards_json or ()),
            recommendation,
        )
        if artifact is not None:
            scores = _candidate_scores(candidate_card)
            return ContractMetadata(
                underlying_price=_decimal(
                    None if candidate_card is None else candidate_card.get("current_price")
                ),
                bid=_decimal(artifact.get("bid")),
                ask=_decimal(artifact.get("ask")),
                mid=_decimal(artifact.get("mid")),
                implied_volatility=_decimal(artifact.get("implied_volatility")),
                delta=_decimal(artifact.get("delta")),
                gamma=_decimal(artifact.get("gamma")),
                theta=_decimal(artifact.get("theta")),
                vega=_decimal(artifact.get("vega")),
                contract_score=_int(artifact.get("contract_score")),
                direction_score=scores["direction_score"],
                final_score=scores["final_score"],
                data_confidence_score=scores["data_confidence_score"],
            )

        sql_match = await self._match_sql_contract(recommendation)
        if sql_match is None:
            scores = _candidate_scores(candidate_card)
            return ContractMetadata(
                underlying_price=_decimal(
                    None if candidate_card is None else candidate_card.get("current_price")
                ),
                direction_score=scores["direction_score"],
                final_score=scores["final_score"],
                data_confidence_score=scores["data_confidence_score"],
            )
        candidate, contract = sql_match
        return ContractMetadata(
            bid=contract.bid,
            underlying_price=candidate.current_price,
            ask=contract.ask,
            mid=contract.mid,
            implied_volatility=contract.implied_volatility,
            delta=contract.delta,
            gamma=contract.gamma,
            theta=contract.theta,
            vega=contract.vega,
            contract_score=contract.contract_opportunity_score,
            direction_score=candidate.candidate_direction_score,
            final_score=candidate.final_opportunity_score,
            data_confidence_score=candidate.data_confidence_score,
        )

    async def _match_sql_contract(
        self,
        recommendation: Recommendation,
    ) -> tuple[Candidate, OptionContract] | None:
        result = await self.session.execute(
            select(Candidate, OptionContract)
            .join(OptionContract, OptionContract.candidate_id == Candidate.id)
            .where(
                Candidate.run_id == recommendation.run_id,
                Candidate.ticker == recommendation.ticker,
                Candidate.strategy_source
                == getattr(recommendation, "strategy_source", "catalyst_confluence"),
                OptionContract.option_type == recommendation.option_type,
                OptionContract.position_side == recommendation.position_side,
                OptionContract.strike == recommendation.strike,
                OptionContract.expiry == recommendation.expiry,
            )
            .limit(1)
        )
        row = result.first()
        if row is None:
            return None
        candidate, contract = row
        return candidate, contract


def _entry_snapshot_status(
    snapshot: PositionQuoteSnapshot | None,
    *,
    backfilled: bool,
) -> str:
    if backfilled:
        return "backfilled"
    if snapshot is None:
        return "partial"
    return snapshot.status


def _entry_snapshot_notes(
    snapshot: PositionQuoteSnapshot | None,
    *,
    backfilled: bool,
) -> list[str]:
    notes = [] if snapshot is None else [str(note) for note in snapshot.notes]
    if backfilled:
        notes.append("backfilled_without_live_entry_snapshot")
    elif snapshot is None:
        notes.append("entry_snapshot_unavailable")
    return notes


def _expected_trajectory(
    position: OpenPosition,
    recommendation: Recommendation,
    *,
    entry_underlying_price: Decimal | None,
) -> dict[str, Any]:
    target_premium = recommendation.target_option_price
    target_underlying = recommendation.target_stock_price
    end_date = recommendation.exit_by_date or recommendation.expiry
    if target_premium is None or target_premium <= 0 or end_date is None:
        return {"method": "unavailable", "reason": "missing target"}

    sessions = market_sessions_between(_aware(position.entry_at).date(), end_date)
    if not sessions:
        return {"method": "unavailable", "reason": "no market sessions"}

    last_index = max(len(sessions) - 1, 1)
    points: list[dict[str, Any]] = []
    for index, session in enumerate(sessions):
        fraction = Decimal(index) / Decimal(last_index)
        expected_premium = position.entry_price + (
            (target_premium - position.entry_price) * fraction
        )
        point: dict[str, Any] = {
            "session_index": index,
            "session_date": session.session_date.isoformat(),
            "expected_premium": _decimal_json(expected_premium),
        }
        if entry_underlying_price is not None and target_underlying is not None:
            expected_underlying = entry_underlying_price + (
                (target_underlying - entry_underlying_price) * fraction
            )
            point["expected_underlying"] = _decimal_json(expected_underlying)
        points.append(point)
    return {"method": "linear_market_sessions", "points": points}


def _invalidation_criteria(
    *,
    recommendation: Recommendation,
    entry_underlying_price: Decimal | None,
    entry_iv: Decimal | None,
    trajectory: dict[str, Any],
    news_baseline_status: str,
) -> list[dict[str, Any]]:
    side = _direction(recommendation)
    return [
        _criterion(
            "option_stop_breach",
            "kill",
            recommendation.stop_loss_option_price is not None,
            ["current_option_premium", "stop_loss_option_price"],
            {"position_side": recommendation.position_side},
        ),
        _criterion(
            "underlying_stop_breach",
            "kill",
            getattr(recommendation, "underlying_stop_price", None) is not None,
            ["current_underlying_price", "underlying_stop_price"],
            {"direction": side},
        ),
        _criterion(
            "adverse_underlying_drift",
            "degrade",
            entry_underlying_price is not None
            and getattr(recommendation, "expected_move_percent", None) is not None,
            ["entry_underlying_price", "current_underlying_price", "expected_move_percent"],
            {"direction": side},
        ),
        _criterion(
            "premium_trajectory_lag",
            "degrade",
            trajectory.get("method") == "linear_market_sessions",
            ["current_option_premium", "expected_trajectory"],
            {"position_side": recommendation.position_side},
        ),
        _criterion(
            "iv_adverse_move",
            "degrade",
            entry_iv is not None,
            ["entry_implied_volatility", "current_implied_volatility"],
            {"position_side": recommendation.position_side},
        ),
        _criterion(
            "time_decay_overshoot",
            "degrade",
            recommendation.position_side == "long"
            and recommendation.expected_holding_days is not None,
            ["entry_option_premium", "current_option_premium", "sessions_held"],
            {"position_side": recommendation.position_side},
        ),
        _criterion(
            "catalyst_passed_no_follow_through",
            "degrade",
            recommendation.earnings_date is not None
            and getattr(recommendation, "expected_move_percent", None) is not None,
            ["catalyst_event_date", "current_underlying_price", "expected_move_percent"],
            {"direction": side},
        ),
        _criterion(
            "expiry_imminent_unresolved",
            "kill",
            True,
            ["expiry", "current_option_premium", "target_option_price"],
            {"position_side": recommendation.position_side},
        ),
        _criterion(
            "new_material_news_candidate",
            "degrade",
            news_baseline_status == "complete",
            ["news_published_max_at", "new_headlines"],
            {},
        ),
        _criterion(
            "data_unavailable",
            "informational",
            True,
            ["current_option_premium", "current_underlying_price"],
            {},
        ),
    ]


def _criterion(
    code: str,
    severity: str,
    enabled: bool,
    field_requirements: list[str],
    params: dict[str, Any],
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "enabled": enabled,
        "source": "deterministic",
        "field_requirements": field_requirements,
        "condition_human": code.replace("_", " "),
        "params": params,
    }


def _news_baseline(
    run: WorkflowRun | None,
    recommendation: Recommendation,
    *,
    backfilled: bool,
) -> dict[str, Any]:
    card = {} if run is None else dict(run.recommendation_card_json or {})
    brief = {
        "recommendation_card": card,
        "candidate_cards": [] if run is None else list(run.candidate_cards_json or []),
    }
    status = "backfilled_or_unknown" if backfilled else "metadata_missing"
    return {
        "brief": brief,
        "articles": [],
        "published_max_at": None,
        "status": status,
        "decision_engine": card.get("decision_engine"),
        "heavy_model_used": card.get("model_used_heavy"),
    }


def _match_contract_artifact(
    artifacts: tuple[Any, ...],
    recommendation: Recommendation,
) -> dict[str, Any] | None:
    for item in artifacts:
        if not isinstance(item, dict):
            continue
        if (
            str(item.get("ticker", "")).upper() == recommendation.ticker.upper()
            and str(item.get("option_type", "")).lower() == recommendation.option_type.lower()
            and str(item.get("position_side", "")).lower() == recommendation.position_side.lower()
            and _decimal(item.get("strike")) == Decimal(str(recommendation.strike))
            and _date_value(item.get("expiry")) == recommendation.expiry
        ):
            return item
    return None


def _match_candidate_card(
    cards: tuple[Any, ...],
    recommendation: Recommendation,
) -> dict[str, Any] | None:
    for item in cards:
        if not isinstance(item, dict):
            continue
        if str(item.get("ticker", "")).upper() == recommendation.ticker.upper():
            return item
    return None


def _candidate_scores(candidate_card: dict[str, Any] | None) -> dict[str, int | None]:
    if candidate_card is None:
        return {
            "direction_score": None,
            "final_score": None,
            "data_confidence_score": None,
        }
    return {
        "direction_score": _int(candidate_card.get("candidate_direction_score")),
        "final_score": _int(candidate_card.get("final_opportunity_score")),
        "data_confidence_score": _int(candidate_card.get("data_confidence_score")),
    }


def _direction(recommendation: Recommendation) -> str:
    strategy = recommendation.strategy.lower()
    if strategy in {"long_put", "short_call"}:
        return "bearish"
    if strategy in {"long_call", "short_put"}:
        return "bullish"
    if recommendation.option_type.lower() == "put":
        return "bearish" if recommendation.position_side.lower() == "long" else "bullish"
    return "bullish" if recommendation.position_side.lower() == "long" else "bearish"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _first_decimal(*values: Decimal | None) -> Decimal | None:
    return next((value for value in values if value is not None), None)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _date_value(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _date_json(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _decimal_json(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(Decimal("0.0001")))
