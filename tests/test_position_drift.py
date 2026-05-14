from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.services.market_hours import MarketSession
from app.services.positions.drift import evaluate_position_drift
from app.services.positions.snapshots import PositionQuoteSnapshot


def _thesis(**overrides):
    defaults = {
        "ticker": "AMD",
        "strategy": "long_call",
        "option_type": "call",
        "position_side": "long",
        "entered_at": datetime(2026, 5, 11, 14, 0, tzinfo=ZoneInfo("America/New_York")),
        "expiry": date(2026, 5, 16),
        "entry_underlying_price": Decimal("100.00"),
        "entry_option_premium": Decimal("1.00"),
        "entry_implied_volatility": Decimal("0.50"),
        "target_option_price": Decimal("2.00"),
        "stop_loss_option_price": Decimal("0.50"),
        "underlying_stop_price": Decimal("95.00"),
        "expected_holding_days": 5,
        "expected_move_percent": Decimal("6.0"),
        "strategy_source": "catalyst_confluence",
        "expected_trajectory_json": {
            "method": "linear_market_sessions",
            "points": [
                {
                    "session_index": 0,
                    "session_date": "2026-05-11",
                    "expected_premium": "1.0000",
                },
                {
                    "session_index": 1,
                    "session_date": "2026-05-12",
                    "expected_premium": "1.5000",
                },
            ],
        },
        "catalyst_kind": "earnings",
        "catalyst_event_date": date(2026, 5, 11),
        "catalyst_baseline_json": {
            "strategy_source": "catalyst_confluence",
            "strategy_thesis": "pre-earnings catalyst confluence",
        },
        "invalidation_criteria_json": [
            {"code": "option_stop_breach", "enabled": True},
            {"code": "underlying_stop_breach", "enabled": True},
            {"code": "adverse_underlying_drift", "enabled": True},
            {"code": "premium_trajectory_lag", "enabled": True},
            {"code": "iv_adverse_move", "enabled": True},
            {"code": "time_decay_overshoot", "enabled": True},
            {"code": "catalyst_passed_no_follow_through", "enabled": True},
            {"code": "expiry_imminent_unresolved", "enabled": True},
            {"code": "data_unavailable", "enabled": True},
        ],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _snapshot(**overrides) -> PositionQuoteSnapshot:
    defaults = {
        "ticker": "AMD",
        "option_type": "call",
        "position_side": "long",
        "strike": Decimal("104.00"),
        "expiry": date(2026, 5, 16),
        "underlying_price": Decimal("94.00"),
        "option_bid": Decimal("0.45"),
        "option_ask": Decimal("0.55"),
        "option_mid": Decimal("0.50"),
        "liquidation_premium": Decimal("0.45"),
        "implied_volatility": Decimal("0.25"),
        "delta": Decimal("0.30"),
        "gamma": None,
        "theta": None,
        "vega": None,
        "source": "fixture",
        "status": "complete",
        "notes": (),
    }
    defaults.update(overrides)
    return PositionQuoteSnapshot(**defaults)


def _session() -> MarketSession:
    tz = ZoneInfo("America/New_York")
    return MarketSession(
        session_date=date(2026, 5, 12),
        open_at=datetime(2026, 5, 12, 9, 30, tzinfo=tz),
        close_at=datetime(2026, 5, 12, 16, 0, tzinfo=tz),
    )


def test_drift_fires_kill_and_degrade_criteria() -> None:
    result = evaluate_position_drift(
        thesis=_thesis(),
        current=_snapshot(),
        session=_session(),
    )

    codes = {item.code for item in result.fired}
    assert "option_stop_breach" in codes
    assert "underlying_stop_breach" in codes
    assert "premium_trajectory_lag" in codes
    assert "iv_adverse_move" in codes
    assert result.snapshot["premium_vs_expected_ratio"] == "0.3000"


def test_missing_quote_only_fires_data_unavailable() -> None:
    result = evaluate_position_drift(
        thesis=_thesis(
            stop_loss_option_price=None,
            underlying_stop_price=None,
            expected_move_percent=None,
            entry_implied_volatility=None,
            expected_trajectory_json={"method": "unavailable"},
        ),
        current=_snapshot(
            underlying_price=None,
            liquidation_premium=None,
            option_bid=None,
            option_ask=None,
            option_mid=None,
            implied_volatility=None,
            status="unavailable",
            notes=("quote_missing",),
        ),
        session=_session(),
    )

    assert [item.code for item in result.fired] == ["data_unavailable"]
    assert result.auto_trigger_codes == ()


def test_strategy_3_metadata_is_preserved_in_drift_snapshot() -> None:
    result = evaluate_position_drift(
        thesis=_thesis(
            strategy_source="activist_13d_followthrough",
            catalyst_kind="filing",
            catalyst_event_date=None,
            catalyst_baseline_json={
                "strategy_source": "activist_13d_followthrough",
                "strategy_thesis": "fresh activist 13D follow-through",
                "validation_metadata": {
                    "sc_13d_accession": "0001234567-26-000123",
                    "sc_13d_url": "https://www.sec.gov/Archives/example.txt",
                },
            },
        ),
        current=_snapshot(underlying_price=Decimal("102.00"), liquidation_premium=Decimal("1.55")),
        session=_session(),
    )

    assert result.snapshot["strategy_source"] == "activist_13d_followthrough"
    assert result.snapshot["catalyst_kind"] == "filing"
    assert (
        result.snapshot["catalyst_baseline"]["validation_metadata"]["sc_13d_accession"]
        == "0001234567-26-000123"
    )


def test_pead_follow_through_failure_can_fire_as_strategy_specific_drift() -> None:
    result = evaluate_position_drift(
        thesis=_thesis(
            strategy_source="pead_continuation",
            invalidation_criteria_json=[
                {"code": "pead_follow_through_failure", "enabled": True},
                {"code": "data_unavailable", "enabled": True},
            ],
        ),
        current=_snapshot(underlying_price=Decimal("100.50"), liquidation_premium=Decimal("1.20")),
        session=_session(),
    )

    assert "pead_follow_through_failure" in {item.code for item in result.fired}
