from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.db.models.open_position import OpenPosition
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.open_position_repo import OpenPositionRepository
from app.db.repositories.user_repo import UserRepository
from app.services.options.alpaca_client import build_occ_symbol
from app.services.options.types import OptionContract
from app.services.positions.monitor import PositionMonitor, _alerts_for_position
from app.services.positions.plans import ActivePositionPlan

pytestmark = pytest.mark.asyncio


class FakePremiumClient:
    def __init__(self, premium: Decimal | None) -> None:
        self.premium = premium
        self.calls: list[dict[str, Any]] = []

    async def fetch_premium(self, ticker: str, **kwargs: Any) -> Decimal | None:
        self.calls.append({"ticker": ticker, **kwargs})
        return self.premium

    async def fetch_chain(self, ticker: str, **kwargs: Any) -> tuple[OptionContract, ...]:
        self.calls.append({"ticker": ticker, **kwargs})
        if self.premium is None:
            return ()
        symbols = kwargs.get("symbols") or (None,)
        return tuple(
            OptionContract(
                ticker=ticker,
                option_type="call",
                strike=Decimal("104.00"),
                expiry=date(2026, 5, 11),
                bid=self.premium,
                ask=self.premium,
                mid=self.premium,
                source="alpaca",
                symbol=symbol,
            )
            for symbol in symbols
        )


@dataclass(slots=True)
class FakeNotifier:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        reply_markup: Any | None = None,
    ) -> str | None:
        self.calls.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return "message-1"


async def _seed_position(
    session: AsyncSession,
    *,
    expiry: date = date(2026, 5, 16),
    exit_by_date: date | None = date(2026, 5, 15),
    alpaca: bool = False,
) -> OpenPosition:
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
            alpaca_api_key_encrypted=crypto.encrypt("alp-key") if alpaca else None,
            alpaca_api_secret_encrypted=crypto.encrypt("alp-secret") if alpaca else None,
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
        expiry=expiry,
        suggested_entry=Decimal("1.25"),
        target_option_price=Decimal("2.00"),
        stop_loss_option_price=Decimal("0.50"),
        exit_by_date=exit_by_date,
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
    return position


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


async def test_monitor_sends_target_alert_once(db_session: AsyncSession) -> None:
    position = await _seed_position(db_session)
    notifier = FakeNotifier()
    monitor = PositionMonitor(
        sessionmaker=_sessionmaker_for(db_session),
        yfinance=FakePremiumClient(Decimal("2.05")),
        alpaca=FakePremiumClient(None),
        notifier=notifier,
        today_factory=lambda: date(2026, 5, 10),
        market_open_checker=lambda: True,
    )

    await monitor.poll_open_positions()
    await monitor.poll_open_positions()

    refreshed = await OpenPositionRepository(db_session).get(position.id)
    assert refreshed is not None
    assert refreshed.last_premium == Decimal("2.0500")
    assert refreshed.last_data_source == "yfinance"
    assert refreshed.target_alert_count == 1
    assert refreshed.alerts_sent == []
    assert len(notifier.calls) == 1
    assert "Target price has been reached." in notifier.calls[0]["text"]


async def test_monitor_switches_to_alpaca_near_expiry(db_session: AsyncSession) -> None:
    position = await _seed_position(
        db_session,
        expiry=date(2026, 5, 11),
        exit_by_date=None,
        alpaca=True,
    )
    yfinance = FakePremiumClient(Decimal("1.20"))
    alpaca = FakePremiumClient(Decimal("1.55"))
    notifier = FakeNotifier()
    monitor = PositionMonitor(
        sessionmaker=_sessionmaker_for(db_session),
        yfinance=yfinance,
        alpaca=alpaca,
        notifier=notifier,
        today_factory=lambda: date(2026, 5, 10),
        market_open_checker=lambda: True,
    )

    await monitor.poll_open_positions()

    refreshed = await OpenPositionRepository(db_session).get(position.id)
    assert refreshed is not None
    assert refreshed.last_premium == Decimal("1.5500")
    assert refreshed.last_data_source == "alpaca"
    assert len(alpaca.calls) == 1
    assert yfinance.calls == []
    assert refreshed.alerts_sent == ["expiry_t_minus_1"]


async def test_monitor_closes_expired_position(db_session: AsyncSession) -> None:
    position = await _seed_position(db_session, expiry=date(2026, 5, 16))
    notifier = FakeNotifier()
    monitor = PositionMonitor(
        sessionmaker=_sessionmaker_for(db_session),
        yfinance=FakePremiumClient(Decimal("1.00")),
        alpaca=FakePremiumClient(None),
        notifier=notifier,
        today_factory=lambda: date(2026, 5, 17),
        market_open_checker=lambda: True,
    )

    await monitor.poll_open_positions()

    refreshed = await OpenPositionRepository(db_session).get(position.id)
    assert refreshed is not None
    assert refreshed.status == "closed_expired"
    assert notifier.calls == []


async def test_build_occ_symbol_formats_standard_contract_symbol() -> None:
    assert (
        build_occ_symbol(
            "AAPL",
            expiry=date(2025, 6, 20),
            option_type="call",
            strike=Decimal("200"),
        )
        == "AAPL250620C00200000"
    )
    assert (
        build_occ_symbol(
            "AAPL",
            expiry=date(2025, 6, 20),
            option_type="put",
            strike=Decimal("95.5"),
        )
        == "AAPL250620P00095500"
    )


async def test_short_position_alerts_invert_premium_thresholds() -> None:
    position = SimpleNamespace(
        target_dismissed=False,
        target_muted_until=None,
        target_alert_count=0,
        stop_dismissed=False,
        stop_muted_until=None,
        stop_alert_count=0,
        alerts_sent=[],
        last_premium=None,
    )
    recommendation = SimpleNamespace(
        position_side="short",
        target_option_price=Decimal("0.60"),
        stop_loss_option_price=Decimal("3.60"),
        exit_by_date=None,
        expiry=date(2026, 5, 16),
    )

    target_alerts = _alerts_for_position(
        position,
        recommendation,
        Decimal("0.55"),
        today=date(2026, 5, 10),
        now=datetime(2026, 5, 10, tzinfo=UTC),
    )
    stop_alerts = _alerts_for_position(
        position,
        recommendation,
        Decimal("3.75"),
        today=date(2026, 5, 10),
        now=datetime(2026, 5, 10, tzinfo=UTC),
    )

    assert "target_hit" in target_alerts
    assert "stop_hit" in stop_alerts


async def test_alerts_use_active_plan_thresholds_when_provided() -> None:
    position = SimpleNamespace(
        target_dismissed=False,
        target_muted_until=None,
        target_alert_count=0,
        stop_dismissed=False,
        stop_muted_until=None,
        stop_alert_count=0,
        alerts_sent=[],
        last_premium=None,
    )
    recommendation = SimpleNamespace(
        position_side="long",
        target_option_price=Decimal("2.00"),
        stop_loss_option_price=Decimal("0.50"),
        exit_by_date=None,
        expiry=date(2026, 5, 16),
    )
    plan = ActivePositionPlan(
        target_option_price=Decimal("2.50"),
        stop_loss_option_price=Decimal("0.80"),
        underlying_stop_price=None,
        source="user",
    )

    original_target_crossed = _alerts_for_position(
        position,
        recommendation,
        Decimal("2.10"),
        plan=plan,
        today=date(2026, 5, 10),
        now=datetime(2026, 5, 10, tzinfo=UTC),
    )
    adjusted_target_crossed = _alerts_for_position(
        position,
        recommendation,
        Decimal("2.60"),
        plan=plan,
        today=date(2026, 5, 10),
        now=datetime(2026, 5, 10, tzinfo=UTC),
    )

    assert "target_hit" not in original_target_crossed
    assert "target_hit" in adjusted_target_crossed
