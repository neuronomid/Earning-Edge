"""Phase 2 onboarding FSM tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.services.api_key_validators import (
    AlpacaValidator,
    AlphaVantageValidator,
    OpenRouterValidator,
    ValidationResult,
)
from app.services.user_service import TIMEZONE_MAP, UserService, decrypt_or_none
from app.telegram.fsm.onboarding_states import Onboarding
from app.telegram.handlers import onboarding as onboarding_handlers
from app.telegram.handlers import start as start_handlers
from app.telegram.keyboards.confirm import ChoiceCB
from app.telegram.keyboards.main_menu import BTN_RUN_SCAN
from tests.telegram_testkit import (
    SendRecorder,
    make_callback,
    make_message,
    make_state,
    make_user_service_scope,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def send_recorder(monkeypatch: pytest.MonkeyPatch) -> SendRecorder:
    recorder = SendRecorder()
    monkeypatch.setattr(start_handlers, "send_text", recorder)
    monkeypatch.setattr(onboarding_handlers, "send_text", recorder)
    return recorder


@pytest.fixture
def patch_user_service_scope(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    scope = make_user_service_scope(db_session)
    monkeypatch.setattr(start_handlers, "user_service_scope", scope)
    monkeypatch.setattr(onboarding_handlers, "user_service_scope", scope)


@pytest.fixture
def validators_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def openrouter_ok(self: OpenRouterValidator, api_key: str) -> ValidationResult:
        return ValidationResult(True, f"OpenRouter accepted {api_key}")

    async def alpaca_ok(
        self: AlpacaValidator, api_key: str, api_secret: str
    ) -> ValidationResult:
        return ValidationResult(True, f"Alpaca accepted {api_key}/{api_secret}")

    async def av_ok(self: AlphaVantageValidator, api_key: str) -> ValidationResult:
        return ValidationResult(True, f"Alpha Vantage accepted {api_key}")

    monkeypatch.setattr(OpenRouterValidator, "validate", openrouter_ok)
    monkeypatch.setattr(AlpacaValidator, "validate", alpaca_ok)
    monkeypatch.setattr(AlphaVantageValidator, "validate", av_ok)


async def test_full_onboarding_flow_persists_user_and_default_cron(
    db_session: AsyncSession,
    send_recorder: SendRecorder,
    patch_user_service_scope: None,
    validators_ok: None,
) -> None:
    chat_id = 12345
    crypto.reset_cache()

    state, storage = await make_state(chat_id)
    try:
        await start_handlers.on_start(make_message("/start", chat_id=chat_id), state)
        assert await state.get_state() == Onboarding.account_size.state
        assert "Welcome to <b>Earning Edge</b>" in send_recorder.calls[0].text
        assert "account size" in send_recorder.calls[1].text.lower()

        await onboarding_handlers.step_account_size(
            make_message("$7,500", chat_id=chat_id), state
        )
        assert await state.get_state() == Onboarding.risk_profile.state

        risk_cb = make_callback(chat_id=chat_id)
        await onboarding_handlers.step_risk_profile(
            risk_cb,
            ChoiceCB(group="risk", value="Balanced"),
            state,
        )
        assert await state.get_state() == Onboarding.timezone.state
        risk_cb.answer.assert_awaited()

        tz_cb = make_callback(chat_id=chat_id)
        await onboarding_handlers.step_timezone(
            tz_cb,
            ChoiceCB(group="tz", value="MT"),
            state,
        )
        assert await state.get_state() == Onboarding.broker.state

        broker_cb = make_callback(chat_id=chat_id)
        await onboarding_handlers.step_broker(
            broker_cb,
            ChoiceCB(group="broker", value="IBKR"),
            state,
        )
        assert await state.get_state() == Onboarding.strategy_permission.state

        strategy_cb = make_callback(chat_id=chat_id)
        await onboarding_handlers.step_strategy(
            strategy_cb,
            ChoiceCB(group="strategy", value="short"),
            state,
        )
        assert await state.get_state() == Onboarding.openrouter_key.state

        await onboarding_handlers.step_openrouter_key(
            make_message("sk-or-live", chat_id=chat_id), state
        )
        assert await state.get_state() == Onboarding.alpaca_key.state

        await onboarding_handlers.step_alpaca_key(
            make_message("ALPACA-KEY", chat_id=chat_id), state
        )
        assert await state.get_state() == Onboarding.alpaca_secret.state

        await onboarding_handlers.step_alpaca_secret(
            make_message("ALPACA-SECRET", chat_id=chat_id), state
        )
        assert await state.get_state() == Onboarding.alpha_vantage_key.state

        await onboarding_handlers.step_av_key(make_message("AV-KEY", chat_id=chat_id), state)
        assert await state.get_state() == Onboarding.confirm.state
        assert "Setup summary" in send_recorder.calls[-1].text
        assert "Mountain (MT)" in send_recorder.calls[-1].text
        assert "IBKR" in send_recorder.calls[-1].text
        assert "Short only" in send_recorder.calls[-1].text

        confirm_cb = make_callback(chat_id=chat_id)
        await onboarding_handlers.confirm_yes(confirm_cb, state)
        assert await state.get_state() is None
        confirm_cb.answer.assert_awaited_with("Saved.")

        service = UserService(db_session)
        user = await service.get_by_chat_id(str(chat_id))
        assert user is not None
        assert user.account_size == Decimal("7500")
        assert user.risk_profile == "Balanced"
        assert user.timezone_label == "MT"
        assert user.timezone_iana == TIMEZONE_MAP["MT"]
        assert user.broker == "IBKR"
        assert user.strategy_permission == "short"
        assert user.openrouter_api_key_encrypted != "sk-or-live"
        assert decrypt_or_none(user.openrouter_api_key_encrypted) == "sk-or-live"
        assert decrypt_or_none(user.alpaca_api_key_encrypted) == "ALPACA-KEY"
        assert decrypt_or_none(user.alpaca_api_secret_encrypted) == "ALPACA-SECRET"
        assert decrypt_or_none(user.alpha_vantage_api_key_encrypted) == "AV-KEY"

        crons = await service.crons.list_for_user(user.id)
        assert len(crons) == 1
        assert crons[0].day_of_week == "monday"
        assert crons[0].local_time == "10:30"
        assert crons[0].timezone_iana == TIMEZONE_MAP["MT"]

        final_markup = send_recorder.calls[-1].kwargs["reply_markup"]
        assert final_markup.keyboard[0][0].text == BTN_RUN_SCAN
    finally:
        await storage.close()


async def test_onboarding_skip_path_omits_optional_keys(
    db_session: AsyncSession,
    send_recorder: SendRecorder,
    patch_user_service_scope: None,
    validators_ok: None,
) -> None:
    chat_id = 40404
    state, storage = await make_state(chat_id)
    try:
        await state.set_state(Onboarding.openrouter_key)
        await state.update_data(
            account_size="5000",
            risk_profile="Conservative",
            timezone="ET",
            broker="Wealthsimple",
            strategy_permission="long_and_short",
        )

        await onboarding_handlers.step_openrouter_key(
            make_message("sk-or-minimal", chat_id=chat_id), state
        )
        assert await state.get_state() == Onboarding.alpaca_key.state

        await onboarding_handlers.skip_alpaca(make_message("⏭ Skip", chat_id=chat_id), state)
        assert await state.get_state() == Onboarding.alpha_vantage_key.state

        await onboarding_handlers.skip_av(make_message("⏭ Skip", chat_id=chat_id), state)
        assert await state.get_state() == Onboarding.confirm.state
        assert "yfinance fallback" in send_recorder.calls[-1].text
        assert "Alpha Vantage: <b>skipped</b>" in send_recorder.calls[-1].text

        await onboarding_handlers.confirm_yes(make_callback(chat_id=chat_id), state)

        service = UserService(db_session)
        user = await service.get_by_chat_id(str(chat_id))
        assert user is not None
        assert decrypt_or_none(user.openrouter_api_key_encrypted) == "sk-or-minimal"
        assert user.alpaca_api_key_encrypted is None
        assert user.alpaca_api_secret_encrypted is None
        assert user.alpha_vantage_api_key_encrypted is None
    finally:
        await storage.close()


async def test_onboarding_reprompts_when_openrouter_key_is_invalid(
    send_recorder: SendRecorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def openrouter_bad(
        self: OpenRouterValidator, api_key: str
    ) -> ValidationResult:
        return ValidationResult(False, f"{api_key} is invalid")

    monkeypatch.setattr(OpenRouterValidator, "validate", openrouter_bad)

    state, storage = await make_state(22222)
    try:
        await state.set_state(Onboarding.openrouter_key)

        await onboarding_handlers.step_openrouter_key(
            make_message("bad-key", chat_id=22222), state
        )

        assert await state.get_state() == Onboarding.openrouter_key.state
        assert "didn't work" in send_recorder.calls[-1].text
        assert "Try again" in send_recorder.calls[-1].text
    finally:
        await storage.close()
