from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.models.open_position import OpenPosition
from app.db.models.position_revalidation import PositionRevalidation
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.repositories.position_plan_override_repo import PositionPlanOverrideRepository
from app.db.repositories.position_revalidation_repo import PositionRevalidationRepository
from app.db.session import get_sessionmaker
from app.llm import LLMRouter
from app.llm.types import LLMError
from app.pipeline.orchestrator import AiogramNotifier, TelegramNotifier
from app.services.market_hours import MarketSession, current_market_session, next_market_open
from app.services.positions.drift import (
    DriftEvaluation,
    NewsHeadline,
    evaluate_position_drift,
)
from app.services.positions.plans import ActivePositionPlan, active_position_plan
from app.services.positions.snapshots import PositionQuoteSnapshot, PositionSnapshotService
from app.services.positions.thesis_builder import PositionThesisBuilder
from app.services.positions.validation_schemas import (
    PositionValidationInput,
    ProposedAdjustment,
    StructuredPositionValidation,
    ValidationEvidence,
)
from app.services.run_lock import RunLockHandle, RunLockService, get_redis_client
from app.services.user_service import decrypt_or_none
from app.telegram.keyboards.settings import validation_result_keyboard
from app.telegram.templates.validation import render_validation_result


@dataclass(frozen=True, slots=True)
class ValidationRunResult:
    status: str
    message: str
    reply_markup: Any | None = None
    revalidation_id: UUID | None = None
    revalidation: PositionRevalidation | None = None


@dataclass(frozen=True, slots=True)
class _ValidationContext:
    user: User
    position: OpenPosition
    recommendation: Recommendation
    thesis: Any
    plan: ActivePositionPlan


@dataclass(frozen=True, slots=True)
class _NormalizedValidation:
    action_final: str
    confidence_band: str
    summary: str
    evidence: list[dict[str, Any]]
    proposed_adjustment: dict[str, Any] | None
    notes: list[str]


class RevalidationService:
    def __init__(
        self,
        *,
        sessionmaker: Callable[[], Any] | None = None,
        snapshot_service: PositionSnapshotService | None = None,
        llm_router: LLMRouter | None = None,
        notifier: TelegramNotifier | None = None,
        settings: Settings | None = None,
        market_session_provider: Callable[[], MarketSession | None] | None = None,
        lock_service: RunLockService | None = None,
        logger: Any | None = None,
    ) -> None:
        self.sessionmaker = sessionmaker or get_sessionmaker()
        self.snapshot_service = snapshot_service or PositionSnapshotService()
        self.llm_router = llm_router or LLMRouter()
        self.notifier = notifier or AiogramNotifier()
        self.settings = settings or get_settings()
        self.market_session_provider = market_session_provider or current_market_session
        self.lock_service = lock_service or _default_validation_lock_service(self.settings)
        self.logger = logger or get_logger(__name__)

    async def validate_position_manual(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
    ) -> ValidationRunResult:
        session = self.market_session_provider()
        if session is None:
            return ValidationRunResult(
                status="market_closed",
                message=(
                    "Market is closed. Position reviews resume at the next market open:\n"
                    f"{next_market_open().strftime('%Y-%m-%d %H:%M %Z')}."
                ),
            )

        handle = await self._acquire_lock(position_id)
        if handle is None:
            return ValidationRunResult(
                status="already_running",
                message="A review is already running for this position.",
            )
        try:
            context = await self._load_context(
                position_id=position_id,
                user_id=user_id,
                backfill_missing_thesis=True,
            )
            if context is None:
                return ValidationRunResult(
                    status="inactive",
                    message="That position is no longer active.",
                )
            current = await self._fetch_current_snapshot(context, session)
            drift = evaluate_position_drift(
                thesis=context.thesis,
                current=current,
                session=session,
                new_headlines=(),
                plan=context.plan,
            )
            return await self._run_validation(
                context=context,
                market_session=session,
                current=current,
                drift=drift,
                trigger="manual",
                trigger_codes=tuple(item.code for item in drift.fired),
                notify=False,
            )
        finally:
            await handle.release()

    async def validate_position_auto(
        self,
        *,
        position_id: UUID,
        trigger_codes: Sequence[str],
        drift_snapshot: dict[str, Any] | None = None,
    ) -> ValidationRunResult:
        session = self.market_session_provider()
        if session is None:
            return ValidationRunResult(status="market_closed", message="")
        actionable = tuple(code for code in trigger_codes if code != "data_unavailable")
        if not actionable:
            return ValidationRunResult(status="skipped", message="")

        handle = await self._acquire_lock(position_id)
        if handle is None:
            return ValidationRunResult(status="already_running", message="")
        try:
            context = await self._load_context(
                position_id=position_id,
                user_id=None,
                backfill_missing_thesis=True,
            )
            if context is None:
                return ValidationRunResult(status="inactive", message="")
            if await self._auto_suppressed(context.position.id, actionable, session):
                return ValidationRunResult(status="suppressed", message="")
            current = await self._fetch_current_snapshot(context, session)
            drift = evaluate_position_drift(
                thesis=context.thesis,
                current=current,
                session=session,
                new_headlines=(),
                plan=context.plan,
            )
            if drift_snapshot:
                drift = DriftEvaluation(
                    fired=drift.fired,
                    snapshot={**drift.snapshot, "monitor_snapshot": drift_snapshot},
                    data_quality=drift.data_quality,
                )
            result = await self._run_validation(
                context=context,
                market_session=session,
                current=current,
                drift=drift,
                trigger="auto",
                trigger_codes=actionable,
                notify=True,
            )
            return result
        finally:
            await handle.release()

    async def _load_context(
        self,
        *,
        position_id: UUID,
        user_id: UUID | None,
        backfill_missing_thesis: bool,
    ) -> _ValidationContext | None:
        async with self.sessionmaker() as db:
            result = await db.execute(
                select(OpenPosition, Recommendation, User)
                .join(Recommendation, Recommendation.id == OpenPosition.recommendation_id)
                .join(User, User.id == OpenPosition.user_id)
                .where(OpenPosition.id == position_id)
            )
            row = result.first()
            if row is None:
                return None
            position, recommendation, user = row
            if user_id is not None and position.user_id != user_id:
                return None
            if position.status != "active":
                return None
            thesis = await PositionThesisBuilder(db).ensure_thesis_for_position(
                position=position,
                recommendation=recommendation,
                user=user,
                entry_snapshot=None,
                backfilled=backfill_missing_thesis,
            )
            override = await PositionPlanOverrideRepository(db).latest_for_position(position.id)
            plan = active_position_plan(recommendation, override)
            await db.commit()
            return _ValidationContext(
                user=user,
                position=position,
                recommendation=recommendation,
                thesis=thesis,
                plan=plan,
            )

    async def _fetch_current_snapshot(
        self,
        context: _ValidationContext,
        market_session: MarketSession,
    ) -> PositionQuoteSnapshot:
        try:
            return await self.snapshot_service.fetch_current(
                user=context.user,
                recommendation=context.recommendation,
                today=market_session.session_date,
            )
        except Exception as exc:
            self.logger.warning(
                "position_validation_snapshot_failed",
                position_id=str(context.position.id),
                ticker=context.recommendation.ticker,
                error=str(exc),
            )
            return _unavailable_snapshot(context.recommendation, note=f"snapshot_error:{exc}")

    async def _run_validation(
        self,
        *,
        context: _ValidationContext,
        market_session: MarketSession,
        current: PositionQuoteSnapshot,
        drift: DriftEvaluation,
        trigger: str,
        trigger_codes: Sequence[str],
        notify: bool,
    ) -> ValidationRunResult:
        llm_input = _validation_input(
            context=context,
            current=current,
            drift=drift,
            trigger=trigger,
            trigger_codes=trigger_codes,
        )
        started = time.monotonic()
        raw: StructuredPositionValidation
        notes: list[str] = []
        try:
            raw = await self.llm_router.decide(
                api_key=decrypt_or_none(context.user.openrouter_api_key_encrypted) or "",
                structured_input=llm_input,
                response_schema=StructuredPositionValidation,
                system_prompt=_validation_prompt(),
                max_tokens=2048,
            )
        except LLMError as exc:
            notes.append(f"llm_error:{type(exc).__name__}")
            raw = StructuredPositionValidation(
                action="insufficient_data",
                confidence_band="low",
                evidence=[
                    ValidationEvidence(
                        code="data_quality:llm_unavailable",
                        observation="The model review could not complete.",
                        significance="material",
                    )
                ],
                summary=(
                    "I could not complete the thesis review. The position is still being "
                    "tracked for target, stop, exit date, and expiry alerts."
                ),
            )
        duration_ms = int((time.monotonic() - started) * 1000)

        normalized = _normalize_validation(
            raw=raw,
            drift=drift,
            current=current,
            context=context,
            headlines=(),
            inherited_notes=notes,
        )
        persisted = await self._persist_revalidation(
            context=context,
            market_session=market_session,
            current=current,
            drift=drift,
            trigger=trigger,
            trigger_codes=trigger_codes,
            raw=raw,
            normalized=normalized,
            duration_ms=duration_ms,
        )
        message = render_validation_result(
            persisted,
            context.position,
            context.recommendation,
        )
        reply_markup = validation_result_keyboard(persisted)
        if notify:
            delivered_id = await self.notifier.send_text(
                context.user.telegram_chat_id,
                message,
                reply_markup=reply_markup,
            )
            if delivered_id is not None:
                await self._mark_delivered(persisted.id, delivered_id)
        return ValidationRunResult(
            status="completed",
            message=message,
            reply_markup=reply_markup,
            revalidation_id=persisted.id,
            revalidation=persisted,
        )

    async def _auto_suppressed(
        self,
        position_id: UUID,
        trigger_codes: Sequence[str],
        market_session: MarketSession,
    ) -> bool:
        cooldown = timedelta(minutes=self.settings.position_validation_auto_cooldown_minutes)
        since = datetime.now(UTC) - cooldown
        async with self.sessionmaker() as db:
            repo = PositionRevalidationRepository(db)
            auto_count = await repo.count_auto_for_session(
                position_id,
                session_date=market_session.session_date,
            )
            if auto_count >= self.settings.position_validation_auto_daily_cap:
                self.logger.info(
                    "position_validation_auto_cap",
                    position_id=str(position_id),
                    session_date=market_session.session_date.isoformat(),
                )
                return True
            return await repo.already_handled_codes(
                position_id,
                trigger_codes=trigger_codes,
                since=since,
            )

    async def _persist_revalidation(
        self,
        *,
        context: _ValidationContext,
        market_session: MarketSession,
        current: PositionQuoteSnapshot,
        drift: DriftEvaluation,
        trigger: str,
        trigger_codes: Sequence[str],
        raw: StructuredPositionValidation,
        normalized: _NormalizedValidation,
        duration_ms: int,
    ) -> PositionRevalidation:
        async with self.sessionmaker() as db:
            repo = PositionRevalidationRepository(db)
            row = await repo.add(
                PositionRevalidation(
                    open_position_id=context.position.id,
                    position_thesis_id=context.thesis.id,
                    user_id=context.user.id,
                    fired_at=datetime.now(UTC),
                    trigger=trigger,
                    trigger_codes_json=[str(code) for code in trigger_codes],
                    market_session_date=market_session.session_date,
                    market_open_at=market_session.open_at,
                    market_close_at=market_session.close_at,
                    current_underlying_price=current.underlying_price,
                    current_option_premium=current.liquidation_premium,
                    current_option_bid=current.option_bid,
                    current_option_ask=current.option_ask,
                    current_option_mid=current.option_mid,
                    current_implied_volatility=current.implied_volatility,
                    current_delta=current.delta,
                    current_gamma=current.gamma,
                    current_theta=current.theta,
                    current_vega=current.vega,
                    quote_source=current.source,
                    quote_status=current.status,
                    drift_snapshot_json=drift.snapshot,
                    new_headlines_json=[],
                    llm_action_raw=raw.action,
                    llm_action_final=normalized.action_final,
                    llm_confidence_band=normalized.confidence_band,
                    llm_summary=normalized.summary,
                    llm_evidence_json=normalized.evidence,
                    proposed_adjustment_json=normalized.proposed_adjustment,
                    normalization_notes_json=normalized.notes,
                    llm_model_used=self.llm_router.heavy_model,
                    llm_call_duration_ms=duration_ms,
                )
            )
            await db.commit()
            return row

    async def _mark_delivered(self, revalidation_id: UUID, delivered_id: str) -> None:
        async with self.sessionmaker() as db:
            row = await PositionRevalidationRepository(db).get(revalidation_id)
            if row is not None:
                row.delivered_telegram_message_id = delivered_id
            await db.commit()

    async def _acquire_lock(self, position_id: UUID) -> RunLockHandle | None:
        try:
            return await self.lock_service.acquire(position_id)
        except (OSError, RedisError, ValueError) as exc:
            self.logger.warning(
                "position_validation_lock_unavailable",
                position_id=str(position_id),
                error=str(exc),
            )
            return _NoopLockHandle()


def _validation_input(
    *,
    context: _ValidationContext,
    current: PositionQuoteSnapshot,
    drift: DriftEvaluation,
    trigger: str,
    trigger_codes: Sequence[str],
) -> PositionValidationInput:
    allowed_evidence_codes = sorted(
        _valid_evidence_codes(
            drift,
            (),
            current=current,
        )
    )
    return PositionValidationInput(
        trigger="auto" if trigger == "auto" else "manual",
        trigger_codes=[str(code) for code in trigger_codes],
        allowed_evidence_codes=allowed_evidence_codes,
        position={
            "id": str(context.position.id),
            "ticker": context.recommendation.ticker,
            "option_type": context.recommendation.option_type,
            "position_side": context.recommendation.position_side,
            "strike": _decimal_json(context.recommendation.strike),
            "expiry": context.recommendation.expiry.isoformat(),
            "entry_price": _decimal_json(context.position.entry_price),
            "entry_quantity": context.position.entry_quantity,
            "entry_at": context.position.entry_at.isoformat(),
        },
        thesis=_thesis_json(context.thesis),
        active_plan={
            "target_option_price": _decimal_json(context.plan.target_option_price),
            "stop_loss_option_price": _decimal_json(context.plan.stop_loss_option_price),
            "underlying_stop_price": _decimal_json(context.plan.underlying_stop_price),
            "source": context.plan.source,
        },
        current_snapshot=_snapshot_json(current),
        drift_snapshot=drift.snapshot,
        fired_criteria=[
            {
                "code": item.code,
                "severity": item.severity,
                "observation": item.observation,
            }
            for item in drift.fired
        ],
        data_quality=list(drift.data_quality),
        new_headlines=[],
    )


def _normalize_validation(
    *,
    raw: StructuredPositionValidation,
    drift: DriftEvaluation,
    current: PositionQuoteSnapshot,
    context: _ValidationContext,
    headlines: Sequence[NewsHeadline],
    inherited_notes: list[str],
) -> _NormalizedValidation:
    notes = list(inherited_notes)
    action = raw.action
    evidence = _normalized_evidence(raw.evidence)
    proposed = _proposed_json(raw.proposed_adjustment)
    fired_kill = {item.code for item in drift.fired if item.severity == "kill"}
    fired_codes = {item.code for item in drift.fired}
    valid_codes = _valid_evidence_codes(
        drift,
        headlines,
        current=current,
    )
    invalid_evidence = [item["code"] for item in evidence if item["code"] not in valid_codes]
    if invalid_evidence:
        notes.append("discarded unsupported evidence: " + ", ".join(invalid_evidence))
        evidence = [item for item in evidence if item["code"] in valid_codes]
    if not evidence:
        action = "insufficient_data"
        evidence = [
            {
                "code": "data_quality:insufficient_supported_evidence",
                "observation": "No model evidence mapped to supplied drift data.",
                "significance": "material",
                "source_ref": None,
            }
        ]

    if current.liquidation_premium is None and current.underlying_price is None:
        action = "insufficient_data"
        notes.append("current option premium and underlying price unavailable")

    if (
        raw.action == "close"
        and not fired_kill
        and not _has_material_headline_evidence(
            evidence,
            headlines,
        )
    ):
        if proposed is not None and _valid_stop_adjustment(
            proposed,
            context=context,
            current=current,
        ):
            action = "adjust_stop"
            notes.append("downgraded close to adjust_stop because no kill criterion fired")
        else:
            action = "insufficient_data"
            notes.append(
                "downgraded close because no kill criterion or material headline was supplied"
            )

    explained_kill = fired_kill & {item["code"] for item in evidence}
    if raw.action == "hold" and fired_kill and not explained_kill:
        action = "insufficient_data"
        notes.append("model returned hold while a kill criterion fired without explaining it")

    if raw.action == "adjust_stop" and not _valid_stop_adjustment(
        proposed,
        context=context,
        current=current,
    ):
        action = "insufficient_data"
        notes.append("invalid stop adjustment proposal")
        proposed = None

    if raw.action == "adjust_target" and not _valid_target_adjustment(
        proposed,
        context=context,
        current=current,
    ):
        action = "insufficient_data"
        notes.append("invalid target adjustment proposal")
        proposed = None

    if action == "hold" and fired_codes:
        notes.append("hold returned with deterministic drift signals present")

    return _NormalizedValidation(
        action_final=action,
        confidence_band=raw.confidence_band,
        summary=raw.summary,
        evidence=evidence,
        proposed_adjustment=proposed,
        notes=notes,
    )


def _valid_evidence_codes(
    drift: DriftEvaluation,
    headlines: Sequence[NewsHeadline],
    *,
    current: PositionQuoteSnapshot | None = None,
) -> set[str]:
    codes = {item.code for item in drift.fired}
    codes.update(str(key) for key in drift.snapshot)
    codes.update(f"drift_signal:{key}" for key in drift.snapshot)
    codes.update(f"data_quality:{item}" for item in drift.data_quality)
    codes.update(headline.id for headline in headlines)
    codes.update({"data_quality:llm_unavailable", "data_quality:insufficient_supported_evidence"})
    if _can_use_no_breach_evidence(drift, current):
        codes.update({"drift_signal:no_breach", "drift_signal:within_plan"})
    return codes


def _can_use_no_breach_evidence(
    drift: DriftEvaluation,
    current: PositionQuoteSnapshot | None,
) -> bool:
    actionable = {item.code for item in drift.fired if item.severity in {"kill", "degrade"}}
    if actionable:
        return False
    if current is None:
        return True
    return not (current.liquidation_premium is None and current.underlying_price is None)


def _valid_stop_adjustment(
    proposed: dict[str, Any] | None,
    *,
    context: _ValidationContext,
    current: PositionQuoteSnapshot,
) -> bool:
    if proposed is None:
        return False
    new_stop = _decimal(proposed.get("stop_loss_option_price"))
    if new_stop is None or new_stop <= 0:
        return False
    current_premium = current.liquidation_premium
    old_stop = context.plan.stop_loss_option_price
    if context.recommendation.position_side == "short":
        if current_premium is not None and new_stop <= current_premium:
            return False
        return old_stop is None or new_stop < old_stop
    if current_premium is not None and new_stop >= current_premium:
        return False
    return old_stop is None or new_stop > old_stop


def _valid_target_adjustment(
    proposed: dict[str, Any] | None,
    *,
    context: _ValidationContext,
    current: PositionQuoteSnapshot,
) -> bool:
    if proposed is None:
        return False
    new_target = _decimal(proposed.get("target_option_price"))
    if new_target is None or new_target <= 0:
        return False
    current_premium = current.liquidation_premium
    if current_premium is None:
        return True
    if context.recommendation.position_side == "short":
        return new_target < current_premium
    return new_target > current_premium


def _has_material_headline_evidence(
    evidence: list[dict[str, Any]],
    headlines: Sequence[NewsHeadline],
) -> bool:
    headline_ids = {headline.id for headline in headlines}
    return any(
        item["code"] in headline_ids and item.get("significance") == "material" for item in evidence
    )


def _normalized_evidence(evidence: Sequence[ValidationEvidence]) -> list[dict[str, Any]]:
    return [
        {
            "code": item.code,
            "observation": item.observation,
            "significance": item.significance,
            "source_ref": item.source_ref,
        }
        for item in evidence
    ]


def _proposed_json(adjustment: ProposedAdjustment | None) -> dict[str, Any] | None:
    if adjustment is None:
        return None
    return {
        "target_option_price": _decimal_json(adjustment.target_option_price),
        "stop_loss_option_price": _decimal_json(adjustment.stop_loss_option_price),
        "underlying_stop_price": _decimal_json(adjustment.underlying_stop_price),
        "reason": adjustment.reason,
    }


def _thesis_json(thesis: Any) -> dict[str, Any]:
    return {
        "id": str(thesis.id),
        "ticker": thesis.ticker,
        "strategy_source": getattr(thesis, "strategy_source", "catalyst_confluence"),
        "strategy": thesis.strategy,
        "entry_option_premium": _decimal_json(thesis.entry_option_premium),
        "entry_underlying_price": _decimal_json(thesis.entry_underlying_price),
        "entry_implied_volatility": _decimal_json(thesis.entry_implied_volatility),
        "target_option_price": _decimal_json(thesis.target_option_price),
        "stop_loss_option_price": _decimal_json(thesis.stop_loss_option_price),
        "underlying_stop_price": _decimal_json(thesis.underlying_stop_price),
        "expected_move_percent": _decimal_json(thesis.expected_move_percent),
        "expected_trajectory": thesis.expected_trajectory_json,
        "catalyst_kind": getattr(thesis, "catalyst_kind", "none"),
        "catalyst_event_date": _date_json(getattr(thesis, "catalyst_event_date", None)),
        "catalyst_baseline": getattr(thesis, "catalyst_baseline_json", {}),
        "invalidation_criteria": thesis.invalidation_criteria_json,
        "reasoning_summary": thesis.reasoning_summary,
        "key_evidence": thesis.key_evidence_json,
        "key_concerns": thesis.key_concerns_json,
        "news_baseline_status": thesis.news_baseline_status,
    }


def _snapshot_json(snapshot: PositionQuoteSnapshot) -> dict[str, Any]:
    return {
        "underlying_price": _decimal_json(snapshot.underlying_price),
        "option_bid": _decimal_json(snapshot.option_bid),
        "option_ask": _decimal_json(snapshot.option_ask),
        "option_mid": _decimal_json(snapshot.option_mid),
        "liquidation_premium": _decimal_json(snapshot.liquidation_premium),
        "implied_volatility": _decimal_json(snapshot.implied_volatility),
        "delta": _decimal_json(snapshot.delta),
        "gamma": _decimal_json(snapshot.gamma),
        "theta": _decimal_json(snapshot.theta),
        "vega": _decimal_json(snapshot.vega),
        "source": snapshot.source,
        "status": snapshot.status,
        "notes": list(snapshot.notes),
    }


def _unavailable_snapshot(recommendation: Recommendation, *, note: str) -> PositionQuoteSnapshot:
    return PositionQuoteSnapshot(
        ticker=recommendation.ticker,
        option_type=recommendation.option_type,
        position_side=recommendation.position_side,
        strike=recommendation.strike,
        expiry=recommendation.expiry,
        underlying_price=None,
        option_bid=None,
        option_ask=None,
        option_mid=None,
        liquidation_premium=None,
        implied_volatility=None,
        delta=None,
        gamma=None,
        theta=None,
        vega=None,
        source="none",
        status="unavailable",
        notes=(note,),
    )


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _decimal_json(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.0001")))


def _date_json(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@lru_cache(maxsize=1)
def _validation_prompt() -> str:
    return (Path(__file__).parents[2] / "llm" / "prompts" / "validate_position.md").read_text(
        encoding="utf-8"
    )


class _NoopLockHandle(RunLockHandle):
    def __init__(self) -> None:
        self.client = None
        self.key = "noop"
        self.token = "noop-token"  # noqa: S105

    async def release(self) -> None:
        return None


class _NoopValidationLockService(RunLockService):
    def __init__(self) -> None:
        self.client = None
        self.ttl_seconds = 0
        self.key_prefix = "position-validation"

    async def acquire(self, user_id: UUID | str) -> RunLockHandle | None:
        del user_id
        return _NoopLockHandle()


def _default_validation_lock_service(settings: Settings) -> RunLockService:
    if settings.app_env == "test":
        return _NoopValidationLockService()
    return RunLockService(
        get_redis_client(),
        ttl_seconds=settings.position_validation_lock_ttl_seconds,
        key_prefix="position-validation",
    )
