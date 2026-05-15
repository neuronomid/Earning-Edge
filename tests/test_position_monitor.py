from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import crypto
from app.db.models.open_position import OpenPosition
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.open_position_repo import OpenPositionRepository
from app.db.repositories.user_repo import UserRepository
from app.services.options.alpaca_client import build_occ_symbol
from app.services.options.types import OptionContract
from app.services.positions.monitor import PositionMonitor, _alerts_for_position, _render_alert
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


class ClosingPremiumClient(FakePremiumClient):
    def __init__(
        self,
        premium: Decimal | None,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        position_id: Any,
    ) -> None:
        super().__init__(premium)
        self.sessionmaker = sessionmaker
        self.position_id = position_id

    async def fetch_premium(self, ticker: str, **kwargs: Any) -> Decimal | None:
        async with self.sessionmaker() as session:
            position = await session.get(OpenPosition, self.position_id)
            assert position is not None
            position.status = "closed_sold"
            position.close_at = datetime(2026, 5, 10, tzinfo=UTC)
            await session.commit()
        return await super().fetch_premium(ticker, **kwargs)


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


def _new_sessionmaker_for(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    bind = session.bind
    assert bind is not None
    return async_sessionmaker(bind=bind, expire_on_commit=False, class_=AsyncSession)


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
    assert "🟢" in notifier.calls[0]["text"]
    assert "Target price has been reached." in notifier.calls[0]["text"]


async def test_monitor_skips_position_closed_after_active_list(
    db_session: AsyncSession,
) -> None:
    position = await _seed_position(db_session)
    sessionmaker = _new_sessionmaker_for(db_session)
    notifier = FakeNotifier()
    monitor = PositionMonitor(
        sessionmaker=sessionmaker,
        yfinance=ClosingPremiumClient(
            Decimal("2.05"),
            sessionmaker=sessionmaker,
            position_id=position.id,
        ),
        alpaca=FakePremiumClient(None),
        notifier=notifier,
        today_factory=lambda: date(2026, 5, 10),
        market_open_checker=lambda: True,
    )

    await monitor.poll_open_positions()

    async with sessionmaker() as session:
        refreshed = await OpenPositionRepository(session).get(position.id)
        assert refreshed is not None
        assert refreshed.status == "closed_sold"
        assert refreshed.target_alert_count == 0
        assert refreshed.last_premium is None
    assert notifier.calls == []


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


async def test_alerts_for_position_ignores_closed_position() -> None:
    position = SimpleNamespace(
        status="closed_sold",
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
        exit_by_date=date(2026, 5, 10),
        expiry=date(2026, 5, 11),
    )

    alerts = _alerts_for_position(
        position,
        recommendation,
        Decimal("2.10"),
        today=date(2026, 5, 10),
        now=datetime(2026, 5, 10, tzinfo=UTC),
    )

    assert alerts == []


async def test_stop_alert_message_includes_stop_emoji() -> None:
    recommendation = SimpleNamespace(
        ticker="AMD",
        position_side="long",
        target_option_price=Decimal("2.00"),
        stop_loss_option_price=Decimal("0.50"),
        underlying_stop_price=None,
    )

    rendered = _render_alert(recommendation, "stop_hit", Decimal("0.45"))

    assert "🛑 Stop level has been reached." in rendered


async def test_alerts_for_pead_sector_rs_and_activist_13d_positions(
    db_session: AsyncSession,
) -> None:
    """Phase 5: the monitor reads positions strategy-agnostically.

    Three positions sourced from PEAD, sector-RS, and activist-13D recommendations
    must each emit a target-hit alert with no special-casing for ``strategy_source``.
    """
    notifier = FakeNotifier()
    strategies = (
        "pead_continuation",
        "sector_relative_strength",
        "activist_13d_followthrough",
    )
    tickers = ("PEAD", "SRSX", "AKTV")
    crypto.reset_cache()
    user = await UserRepository(db_session).add(
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
    db_session.add(run)
    await db_session.flush()

    position_repo = OpenPositionRepository(db_session)
    for ticker, strategy_source in zip(tickers, strategies, strict=True):
        recommendation = Recommendation(
            user_id=user.id,
            run_id=run.id,
            ticker=ticker,
            company_name=f"{ticker} Corp.",
            strategy_source=strategy_source,
            strategy="long_call",
            option_type="call",
            position_side="long",
            strike=Decimal("100.00"),
            expiry=date(2026, 5, 16),
            suggested_entry=Decimal("1.25"),
            target_option_price=Decimal("2.00"),
            stop_loss_option_price=Decimal("0.50"),
            exit_by_date=date(2026, 5, 15),
            suggested_quantity=2,
            estimated_max_loss="$125.00 max loss per contract",
            account_risk_percent=Decimal("2.0000"),
            confidence_score=82,
            risk_level="High",
            reasoning_summary=f"{strategy_source} cleared the bar.",
            key_evidence_json=["Momentum held."],
            key_concerns_json=["IV crush."],
        )
        db_session.add(recommendation)
        await db_session.flush()
        await position_repo.add(
            OpenPosition(
                recommendation_id=recommendation.id,
                user_id=user.id,
                entry_price=Decimal("1.25"),
                entry_quantity=2,
                status="active",
            )
        )
    await db_session.commit()

    monitor = PositionMonitor(
        sessionmaker=_sessionmaker_for(db_session),
        yfinance=FakePremiumClient(Decimal("2.05")),
        alpaca=FakePremiumClient(None),
        notifier=notifier,
        today_factory=lambda: date(2026, 5, 10),
        market_open_checker=lambda: True,
    )

    await monitor.poll_open_positions()

    assert len(notifier.calls) == 3
    notified_tickers = sorted(call["text"].split()[0].replace("<b>", "") for call in notifier.calls)
    assert notified_tickers == sorted(tickers)
    for call in notifier.calls:
        assert "🟢" in call["text"]
        assert "Target price has been reached." in call["text"]


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
