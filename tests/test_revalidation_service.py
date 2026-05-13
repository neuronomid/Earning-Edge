from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.db.models.open_position import OpenPosition
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.open_position_repo import OpenPositionRepository
from app.db.repositories.position_revalidation_repo import PositionRevalidationRepository
from app.db.repositories.user_repo import UserRepository
from app.services.market_hours import MarketSession
from app.services.positions.drift import DriftEvaluation, FiredCriterion
from app.services.positions.plans import ActivePositionPlan
from app.services.positions.revalidation_service import (
    RevalidationService,
    _normalize_validation,
)
from app.services.positions.snapshots import PositionQuoteSnapshot
from app.services.positions.validation_schemas import (
    StructuredPositionValidation,
    ValidationEvidence,
)


class FakeRouter:
    heavy_model = "fixture-heavy"

    async def decide(self, **kwargs):
        del kwargs
        return StructuredPositionValidation(
            action="hold",
            confidence_band="standard",
            evidence=[
                ValidationEvidence(
                    code="premium_vs_expected_ratio",
                    observation="Premium remains close enough to the expected path.",
                    significance="marginal",
                )
            ],
            summary="The thesis remains intact.",
        )


class FakeSnapshotService:
    async def fetch_current(self, **kwargs):
        del kwargs
        return _snapshot()


def _sessionmaker_for(session: AsyncSession):
    @asynccontextmanager
    async def scope():
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    return scope


def _market_session() -> MarketSession:
    tz = ZoneInfo("America/New_York")
    return MarketSession(
        session_date=date(2026, 5, 12),
        open_at=datetime(2026, 5, 12, 9, 30, tzinfo=tz),
        close_at=datetime(2026, 5, 12, 16, 0, tzinfo=tz),
    )


def _snapshot(**overrides) -> PositionQuoteSnapshot:
    defaults = {
        "ticker": "AMD",
        "option_type": "call",
        "position_side": "long",
        "strike": Decimal("104.00"),
        "expiry": date(2026, 5, 16),
        "underlying_price": Decimal("101.00"),
        "option_bid": Decimal("1.20"),
        "option_ask": Decimal("1.30"),
        "option_mid": Decimal("1.25"),
        "liquidation_premium": Decimal("1.20"),
        "implied_volatility": Decimal("0.48"),
        "delta": Decimal("0.50"),
        "gamma": None,
        "theta": None,
        "vega": None,
        "source": "fixture",
        "status": "complete",
        "notes": (),
    }
    defaults.update(overrides)
    return PositionQuoteSnapshot(**defaults)


async def _seed_position(session: AsyncSession) -> tuple[User, OpenPosition]:
    crypto.reset_cache()
    user = await UserRepository(session).add(
        User(
            telegram_chat_id="12345",
            account_size=Decimal("15000.00"),
            risk_profile="Balanced",
            broker="IBKR",
            timezone_label="ET",
            timezone_iana="America/Toronto",
            strategy_permission="long_and_short",
            max_contracts=3,
            openrouter_api_key_encrypted=crypto.encrypt("sk-or-test"),
        )
    )
    run = WorkflowRun(user_id=user.id, trigger_type="manual", status="success")
    session.add(run)
    await session.flush()
    recommendation = Recommendation(
        user_id=user.id,
        run_id=run.id,
        ticker="AMD",
        company_name="AMD Corp.",
        strategy="long_call",
        option_type="call",
        position_side="long",
        strike=Decimal("104.00"),
        expiry=date(2026, 5, 16),
        earnings_date=date(2026, 5, 11),
        suggested_entry=Decimal("1.25"),
        target_option_price=Decimal("2.00"),
        stop_loss_option_price=Decimal("0.50"),
        underlying_stop_price=Decimal("95.00"),
        expected_holding_days=5,
        expected_move_percent=Decimal("6.00"),
        suggested_quantity=2,
        estimated_max_loss="$125.00 max loss per contract",
        account_risk_percent=Decimal("2.0000"),
        confidence_score=82,
        risk_level="High",
        reasoning_summary="AMD had the cleanest setup.",
        key_evidence_json=["Momentum held."],
        key_concerns_json=["IV crush."],
    )
    session.add(recommendation)
    await session.flush()
    position = await OpenPositionRepository(session).add(
        OpenPosition(
            recommendation_id=recommendation.id,
            user_id=user.id,
            entry_price=Decimal("1.25"),
            entry_quantity=2,
            status="active",
        )
    )
    await session.commit()
    return user, position


@pytest.mark.asyncio
async def test_manual_revalidation_persists_history(db_session: AsyncSession) -> None:
    user, position = await _seed_position(db_session)
    service = RevalidationService(
        sessionmaker=_sessionmaker_for(db_session),
        snapshot_service=FakeSnapshotService(),
        llm_router=FakeRouter(),
        market_session_provider=_market_session,
    )

    result = await service.validate_position_manual(user_id=user.id, position_id=position.id)

    assert result.status == "completed"
    assert "Action: HOLD" in result.message
    rows = await PositionRevalidationRepository(db_session).list_for_position(position.id)
    assert len(rows) == 1
    assert rows[0].llm_action_final == "hold"
    assert rows[0].trigger == "manual"


def test_close_without_kill_is_normalized_to_insufficient_data() -> None:
    context = SimpleNamespace(
        recommendation=SimpleNamespace(position_side="long"),
        plan=ActivePositionPlan(
            target_option_price=Decimal("2.00"),
            stop_loss_option_price=Decimal("0.50"),
            underlying_stop_price=None,
        ),
    )
    raw = StructuredPositionValidation(
        action="close",
        confidence_band="standard",
        evidence=[
            ValidationEvidence(
                code="premium_vs_expected_ratio",
                observation="Premium is a little behind.",
                significance="marginal",
            )
        ],
        summary="Close it.",
    )
    drift = DriftEvaluation(
        fired=(),
        snapshot={"premium_vs_expected_ratio": "0.9000"},
        data_quality=(),
    )

    normalized = _normalize_validation(
        raw=raw,
        drift=drift,
        current=_snapshot(),
        context=context,
        headlines=(),
        inherited_notes=[],
    )

    assert normalized.action_final == "insufficient_data"
    assert "downgraded close" in normalized.notes[0]


def test_hold_with_unexplained_kill_is_normalized() -> None:
    context = SimpleNamespace(
        recommendation=SimpleNamespace(position_side="long"),
        plan=ActivePositionPlan(
            target_option_price=Decimal("2.00"),
            stop_loss_option_price=Decimal("0.50"),
            underlying_stop_price=None,
        ),
    )
    raw = StructuredPositionValidation(
        action="hold",
        confidence_band="standard",
        evidence=[
            ValidationEvidence(
                code="premium_vs_expected_ratio",
                observation="Premium is close to plan.",
                significance="marginal",
            )
        ],
        summary="Hold it.",
    )
    drift = DriftEvaluation(
        fired=(
            FiredCriterion(
                code="option_stop_breach",
                severity="kill",
                observation="Stop breached.",
            ),
        ),
        snapshot={"premium_vs_expected_ratio": "0.9000"},
        data_quality=(),
    )

    normalized = _normalize_validation(
        raw=raw,
        drift=drift,
        current=_snapshot(),
        context=context,
        headlines=(),
        inherited_notes=[],
    )

    assert normalized.action_final == "insufficient_data"


def test_adjust_stop_must_tighten_risk() -> None:
    context = SimpleNamespace(
        recommendation=SimpleNamespace(position_side="long"),
        plan=ActivePositionPlan(
            target_option_price=Decimal("2.00"),
            stop_loss_option_price=Decimal("0.50"),
            underlying_stop_price=None,
        ),
    )
    raw = StructuredPositionValidation(
        action="adjust_stop",
        confidence_band="standard",
        evidence=[
            ValidationEvidence(
                code="premium_vs_expected_ratio",
                observation="Premium is below plan.",
                significance="material",
            )
        ],
        summary="Tighten risk.",
        proposed_adjustment={
            "stop_loss_option_price": Decimal("0.75"),
            "reason": "Premium lagged but stop has not failed.",
        },
    )
    drift = DriftEvaluation(
        fired=(),
        snapshot={"premium_vs_expected_ratio": "0.7000"},
        data_quality=(),
    )

    normalized = _normalize_validation(
        raw=raw,
        drift=drift,
        current=_snapshot(liquidation_premium=Decimal("1.20")),
        context=context,
        headlines=(),
        inherited_notes=[],
    )

    assert normalized.action_final == "adjust_stop"
    assert normalized.proposed_adjustment is not None
    assert normalized.proposed_adjustment["stop_loss_option_price"] == "0.7500"
