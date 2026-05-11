from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.api import dashboard as dashboard_api
from app.db.models.recommendation import Recommendation
from app.db.models.workflow_run import WorkflowRun
from app.main import app
from app.services.api_key_validators import ValidationResult
from app.services.market_data.alpaca_stock_client import AlpacaStockQuote
from app.services.user_service import OnboardingPayload, UserService, decrypt_or_none

pytestmark = pytest.mark.asyncio


def _payload(chat_id: str) -> OnboardingPayload:
    return OnboardingPayload(
        telegram_chat_id=chat_id,
        account_size=Decimal("5000"),
        risk_profile="Balanced",
        timezone_label="ET",
        broker="Wealthsimple",
        strategy_permission="long_and_short",
        openrouter_api_key="sk-or-original",
        alpaca_api_key="alp-old",
        alpaca_api_secret="alp-secret-old",
        alpha_vantage_api_key="av-old",
    )


async def test_dashboard_updates_openrouter_key(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = UserService(db_session)
    await service.create_from_onboarding(_payload("dashboard-openrouter"))
    await db_session.commit()

    async def override_session():
        yield db_session

    async def openrouter_ok(self, api_key: str) -> ValidationResult:
        return ValidationResult(True, f"accepted:{api_key}")

    monkeypatch.setattr(dashboard_api.OpenRouterValidator, "validate", openrouter_ok)
    app.dependency_overrides[dashboard_api.get_session] = override_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/dashboard/api-keys/openrouter",
            json={"apiKey": "sk-or-updated"},
        )
        snapshot_response = await client.get("/api/dashboard/snapshot")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "OpenRouter key updated and validated."
    assert snapshot_response.status_code == 200
    system = snapshot_response.json()["system"]
    assert system["openRouterStatus"] == "Configured"
    assert system["openRouterKeyDisplay"] == "sk-or-up...ated"
    assert system["openRouterKeyDisplay"] != "sk-or-updated"

    user = await service.get_by_chat_id("dashboard-openrouter")
    assert user is not None
    assert decrypt_or_none(user.openrouter_api_key_encrypted) == "sk-or-updated"


async def test_dashboard_register_login_and_update_user_settings(
    db_session,
) -> None:
    async def override_session():
        yield db_session

    app.dependency_overrides[dashboard_api.get_session] = override_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        register = await client.post(
            "/api/dashboard/auth/register",
            json={"username": "Sep Trader", "password": "pass1234"},
        )
        login = await client.post(
            "/api/dashboard/auth/login",
            json={"username": "sep trader", "password": "pass1234"},
        )
        bad_login = await client.post(
            "/api/dashboard/auth/login",
            json={"username": "sep trader", "password": "wrong-pass"},
        )

        user_id = register.json()["user"]["id"]
        settings = await client.patch(
            f"/api/dashboard/settings?user_id={user_id}",
            json={
                "accountSize": 250000,
                "riskProfile": "Aggressive",
                "timezoneLabel": "PT",
                "broker": "IBKR Live",
                "strategyPermission": "long",
                "maxContracts": 7,
            },
        )
        snapshot = await client.get(f"/api/dashboard/snapshot?user_id={user_id}")

    app.dependency_overrides.clear()

    assert register.status_code == 200
    assert register.json()["user"]["username"] == "sep trader"
    assert login.status_code == 200
    assert login.json()["user"]["id"] == user_id
    assert bad_login.status_code == 401
    assert settings.status_code == 200

    user_payload = snapshot.json()["user"]
    assert user_payload["accountSize"] == 250000
    assert user_payload["riskProfile"] == "Aggressive"
    assert user_payload["timezone"] == "Pacific (PT)"
    assert user_payload["timezoneLabel"] == "PT"
    assert user_payload["broker"] == "IBKR Live"
    assert user_payload["strategyPermission"] == "long"
    assert user_payload["maxContracts"] == 7

    service = UserService(db_session)
    user = await service.get_by_dashboard_username("sep trader")
    assert user is not None
    assert user.dashboard_password_hash is not None
    assert "pass1234" not in user.dashboard_password_hash
    assert user.telegram_chat_id == "dashboard:sep trader"


async def test_dashboard_stock_price_uses_user_alpaca_credentials(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = UserService(db_session)
    user = await service.create_from_onboarding(_payload("dashboard-stock-price"))
    await db_session.commit()

    async def override_session():
        yield db_session

    async def alpaca_quote(
        self,
        symbol: str,
        *,
        api_key: str,
        api_secret: str,
        feed: str | None = None,
    ):
        assert symbol == "AMD"
        assert api_key == "alp-old"
        assert api_secret == "alp-secret-old"
        assert feed == "iex"
        return AlpacaStockQuote(
            symbol="AMD",
            bid=Decimal("101.20"),
            ask=Decimal("101.30"),
            price=Decimal("101.25"),
            timestamp="2026-05-08T14:30:00Z",
            feed="iex",
        )

    async def previous_close(ticker_upper: str) -> Decimal:
        assert ticker_upper == "AMD"
        return Decimal("100")

    monkeypatch.setattr(dashboard_api.AlpacaStockClient, "fetch_quote", alpaca_quote)
    monkeypatch.setattr(dashboard_api, "_yfinance_previous_close", previous_close)
    app.dependency_overrides[dashboard_api.get_session] = override_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/dashboard/stock-price?user_id={user.id}&ticker=AMD")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "alpaca_iex"
    assert payload["dataMode"] == "REAL_TIME"
    assert payload["price"] == 101.25
    assert payload["bid"] == 101.2
    assert payload["ask"] == 101.3
    assert payload["change"] == 1.25


async def test_dashboard_rejects_invalid_openrouter_key(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = UserService(db_session)
    await service.create_from_onboarding(_payload("dashboard-openrouter-bad"))
    await db_session.commit()

    async def override_session():
        yield db_session

    async def openrouter_bad(self, api_key: str) -> ValidationResult:
        return ValidationResult(False, f"invalid:{api_key}")

    monkeypatch.setattr(dashboard_api.OpenRouterValidator, "validate", openrouter_bad)
    app.dependency_overrides[dashboard_api.get_session] = override_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/dashboard/api-keys/openrouter",
            json={"apiKey": "sk-or-bad"},
        )

    app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid:sk-or-bad"}

    user = await service.get_by_chat_id("dashboard-openrouter-bad")
    assert user is not None
    assert decrypt_or_none(user.openrouter_api_key_encrypted) == "sk-or-original"


async def test_dashboard_can_remove_provider_keys(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = UserService(db_session)
    await service.create_from_onboarding(_payload("dashboard-remove-creds"))
    await db_session.commit()

    async def override_session():
        yield db_session

    async def alpaca_ok(self, api_key: str, api_secret: str) -> ValidationResult:
        return ValidationResult(True, f"{api_key}:{api_secret}")

    async def av_ok(self, api_key: str) -> ValidationResult:
        return ValidationResult(True, api_key)

    monkeypatch.setattr(dashboard_api.AlpacaValidator, "validate", alpaca_ok)
    monkeypatch.setattr(dashboard_api.AlphaVantageValidator, "validate", av_ok)
    app.dependency_overrides[dashboard_api.get_session] = override_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        save_alpaca = await client.post(
            "/api/dashboard/api-keys/alpaca",
            json={"apiKey": "alp-new", "apiSecret": "alp-secret-new"},
        )
        save_av = await client.post(
            "/api/dashboard/api-keys/alpha-vantage",
            json={"apiKey": "av-new"},
        )
        remove_alpaca = await client.delete("/api/dashboard/api-keys/alpaca")
        remove_av = await client.delete("/api/dashboard/api-keys/alpha-vantage")

    app.dependency_overrides.clear()

    assert save_alpaca.status_code == 200
    assert save_av.status_code == 200
    assert remove_alpaca.status_code == 200
    assert remove_av.status_code == 200

    user = await service.get_by_chat_id("dashboard-remove-creds")
    assert user is not None
    assert decrypt_or_none(user.openrouter_api_key_encrypted) == "sk-or-original"
    assert user.alpaca_api_key_encrypted is None
    assert user.alpaca_api_secret_encrypted is None
    assert user.alpha_vantage_api_key_encrypted is None


async def test_dashboard_can_remove_openrouter_key(
    db_session,
) -> None:
    service = UserService(db_session)
    await service.create_from_onboarding(_payload("dashboard-remove-openrouter"))
    await db_session.commit()

    async def override_session():
        yield db_session

    app.dependency_overrides[dashboard_api.get_session] = override_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.delete("/api/dashboard/api-keys/openrouter")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["message"] == "OpenRouter key removed."

    user = await service.get_by_chat_id("dashboard-remove-openrouter")
    assert user is not None
    assert (
        decrypt_or_none(user.openrouter_api_key_encrypted) is None
        or decrypt_or_none(user.openrouter_api_key_encrypted) == ""
    )


async def test_dashboard_snapshot_uses_most_recent_run_even_without_recommendation(
    db_session,
) -> None:
    service = UserService(db_session)
    user = await service.create_from_onboarding(_payload("dashboard-latest-run"))
    await db_session.flush()

    older_run = WorkflowRun(
        user_id=user.id,
        trigger_type="manual",
        status="success",
        started_at=datetime.now(UTC) - timedelta(hours=2),
        finished_at=datetime.now(UTC) - timedelta(hours=2) + timedelta(minutes=5),
        screener_status="success",
        selected_candidate_count=1,
        run_summary_json={"selected_candidate_count": 1, "contracts_considered_count": 1},
        candidate_cards_json=[],
        option_contracts_json=[],
        recommendation_card_json={"selected_ticker": "AMD"},
        telegram_message_text="older recommendation",
    )
    db_session.add(older_run)
    await db_session.flush()

    older_recommendation = Recommendation(
        user_id=user.id,
        run_id=older_run.id,
        ticker="AMD",
        company_name="Advanced Micro Devices",
        strategy="long_call",
        option_type="call",
        position_side="long",
        strike=Decimal("100"),
        expiry=datetime.now(UTC).date() + timedelta(days=7),
        suggested_entry=Decimal("1.25"),
        suggested_quantity=1,
        estimated_max_loss="$125 max loss",
        account_risk_percent=Decimal("2.0"),
        confidence_score=80,
        risk_level="Moderate",
        reasoning_summary="older reasoning",
        key_evidence_json=[],
        key_concerns_json=[],
    )
    db_session.add(older_recommendation)
    await db_session.flush()
    older_run.final_recommendation_id = older_recommendation.id

    newer_run = WorkflowRun(
        user_id=user.id,
        trigger_type="manual",
        status="no_trade",
        started_at=datetime.now(UTC) - timedelta(minutes=30),
        finished_at=datetime.now(UTC) - timedelta(minutes=25),
        screener_status="success",
        selected_candidate_count=0,
        run_summary_json={"selected_candidate_count": 0, "contracts_considered_count": 0},
        candidate_cards_json=[],
        option_contracts_json=[],
        recommendation_card_json={"selected_ticker": None},
        telegram_message_text="newer no trade",
    )
    db_session.add(newer_run)
    await db_session.commit()

    async def override_session():
        yield db_session

    app.dependency_overrides[dashboard_api.get_session] = override_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/dashboard/snapshot")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["selectedRecommendationId"] is None
    assert payload["recommendations"] == []
    assert payload["telegramMessageText"] == "newer no trade"


async def test_dashboard_snapshot_uses_selected_recommendation_contract_and_rank(
    db_session,
) -> None:
    service = UserService(db_session)
    user = await service.create_from_onboarding(_payload("dashboard-selected-contract"))
    selected_expiry = datetime.now(UTC).date() + timedelta(days=5)
    alternate_expiry = selected_expiry + timedelta(days=7)

    run = WorkflowRun(
        user_id=user.id,
        trigger_type="manual",
        status="success",
        started_at=datetime.now(UTC) - timedelta(minutes=10),
        finished_at=datetime.now(UTC) - timedelta(minutes=5),
        screener_status="success",
        selected_candidate_count=2,
        run_summary_json={"selected_candidate_count": 2, "contracts_considered_count": 2},
        candidate_cards_json=[
            {
                "ticker": "SWKS",
                "company_name": "Skyworks Solutions",
                "final_opportunity_score": 70,
                "data_confidence_score": 99,
            },
            {
                "ticker": "MP",
                "company_name": "MP Materials",
                "final_opportunity_score": 64,
                "data_confidence_score": 98,
                "current_price": 67.43,
            },
        ],
        option_contracts_json=[
            {
                "ticker": "MP",
                "option_type": "call",
                "position_side": "long",
                "strike": 75.0,
                "expiry": alternate_expiry.isoformat(),
                "mid": 2.25,
                "contract_score": 90,
            },
            {
                "ticker": "MP",
                "option_type": "call",
                "position_side": "long",
                "strike": 71.0,
                "expiry": selected_expiry.isoformat(),
                "mid": 1.59,
                "breakeven": 72.59,
                "contract_score": 61,
            },
        ],
        recommendation_card_json={"selected_ticker": "MP"},
        telegram_message_text="Best setup: MP",
    )
    db_session.add(run)
    await db_session.flush()

    recommendation = Recommendation(
        user_id=user.id,
        run_id=run.id,
        ticker="MP",
        company_name="MP Materials",
        strategy="long_call",
        option_type="call",
        position_side="long",
        strike=Decimal("71"),
        expiry=selected_expiry,
        suggested_entry=Decimal("1.59"),
        suggested_quantity=0,
        estimated_max_loss="$159 max loss",
        account_risk_percent=Decimal("4.0"),
        confidence_score=62,
        risk_level="Moderate",
        reasoning_summary="Selected by the final decision step.",
        key_evidence_json=[],
        key_concerns_json=[],
    )
    db_session.add(recommendation)
    await db_session.flush()
    run.final_recommendation_id = recommendation.id
    await db_session.commit()

    async def override_session():
        yield db_session

    app.dependency_overrides[dashboard_api.get_session] = override_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/dashboard/snapshot?user_id={user.id}")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    serialized = payload["recommendations"][0]
    assert serialized["rank"] == 1
    assert serialized["setupLabel"] == "Best setup"
    assert serialized["ticker"] == "MP"
    assert serialized["contractId"].endswith(f":MP:{selected_expiry.isoformat()}:CALL:71.00")
    assert serialized["midPrice"] == 1.59
