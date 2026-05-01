"""Phase 2 settings handler tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.services.api_key_validators import (
    AlpacaValidator,
    AlphaVantageValidator,
    OpenRouterValidator,
    ValidationResult,
)
from app.services.user_service import OnboardingPayload, UserService, decrypt_or_none
from app.telegram.fsm.onboarding_states import SettingsEdit
from app.telegram.handlers import settings as settings_handlers
from app.telegram.keyboards.confirm import ChoiceCB
from app.telegram.keyboards.main_menu import BTN_API_KEYS, BTN_SETTINGS
from app.telegram.keyboards.settings import ApiKeyCB, SettingsCB
from tests.telegram_testkit import (
    SendRecorder,
    make_callback,
    make_message,
    make_state,
    make_user_service_scope,
)

pytestmark = pytest.mark.asyncio


def _payload(chat_id: int) -> OnboardingPayload:
    return OnboardingPayload(
        telegram_chat_id=str(chat_id),
        account_size=Decimal("5000.00"),
        risk_profile="Balanced",
        timezone_label="ET",
        broker="Wealthsimple",
        strategy_permission="long_and_short",
        openrouter_api_key="sk-or-original",
        alpaca_api_key="ALP-OLD",
        alpaca_api_secret="ALP-SECRET-OLD",
        alpha_vantage_api_key="AV-OLD",
    )


@pytest.fixture
def send_recorder(monkeypatch: pytest.MonkeyPatch) -> SendRecorder:
    recorder = SendRecorder()
    monkeypatch.setattr(settings_handlers, "send_text", recorder)
    return recorder


@pytest.fixture
def patch_user_service_scope(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    monkeypatch.setattr(
        settings_handlers,
        "user_service_scope",
        make_user_service_scope(db_session),
    )


@pytest.fixture
def validators_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def openrouter_ok(self: OpenRouterValidator, api_key: str) -> ValidationResult:
        return ValidationResult(True, api_key)

    async def alpaca_ok(
        self: AlpacaValidator, api_key: str, api_secret: str
    ) -> ValidationResult:
        return ValidationResult(True, f"{api_key}:{api_secret}")

    async def av_ok(self: AlphaVantageValidator, api_key: str) -> ValidationResult:
        return ValidationResult(True, api_key)

    monkeypatch.setattr(OpenRouterValidator, "validate", openrouter_ok)
    monkeypatch.setattr(AlpacaValidator, "validate", alpaca_ok)
    monkeypatch.setattr(AlphaVantageValidator, "validate", av_ok)


@pytest_asyncio.fixture
async def seeded_user(db_session: AsyncSession) -> UserService:
    crypto.reset_cache()
    service = UserService(db_session)
    await service.create_from_onboarding(_payload(chat_id=12345))
    await db_session.commit()
    return service


async def test_settings_edit_roundtrip_updates_persisted_user(
    db_session: AsyncSession,
    seeded_user: UserService,
    send_recorder: SendRecorder,
    patch_user_service_scope: None,
    validators_ok: None,
) -> None:
    chat_id = 12345
    state, storage = await make_state(chat_id)
    try:
        await settings_handlers.open_settings(make_message(BTN_SETTINGS, chat_id=chat_id))
        assert "⚙️ <b>Settings</b>" in send_recorder.calls[-1].text
        assert "$5000.00" in send_recorder.calls[-1].text

        account_cb = make_callback(chat_id=chat_id)
        await settings_handlers.on_settings_button(
            account_cb,
            SettingsCB(field="account_size"),
            state,
        )
        assert await state.get_state() == SettingsEdit.account_size.state
        await settings_handlers.edit_account_size(make_message("12000", chat_id=chat_id), state)
        assert await state.get_state() is None

        risk_cb = make_callback(chat_id=chat_id)
        await settings_handlers.on_settings_button(
            risk_cb,
            SettingsCB(field="risk_profile"),
            state,
        )
        assert await state.get_state() == SettingsEdit.risk_profile.state
        await settings_handlers.edit_risk_profile(
            make_callback(chat_id=chat_id),
            ChoiceCB(group="set_risk", value="Aggressive"),
            state,
        )
        assert await state.get_state() is None

        tz_cb = make_callback(chat_id=chat_id)
        await settings_handlers.on_settings_button(
            tz_cb,
            SettingsCB(field="timezone"),
            state,
        )
        assert await state.get_state() == SettingsEdit.timezone.state
        await settings_handlers.edit_timezone(
            make_callback(chat_id=chat_id),
            ChoiceCB(group="set_tz", value="PT"),
            state,
        )
        assert await state.get_state() is None

        broker_cb = make_callback(chat_id=chat_id)
        await settings_handlers.on_settings_button(
            broker_cb,
            SettingsCB(field="broker"),
            state,
        )
        await settings_handlers.edit_broker(
            make_callback(chat_id=chat_id),
            ChoiceCB(group="set_broker", value="Questrade"),
            state,
        )

        strategy_cb = make_callback(chat_id=chat_id)
        await settings_handlers.on_settings_button(
            strategy_cb,
            SettingsCB(field="strategy"),
            state,
        )
        await settings_handlers.edit_strategy_permission(
            make_callback(chat_id=chat_id),
            ChoiceCB(group="set_strategy", value="long"),
            state,
        )

        max_cb = make_callback(chat_id=chat_id)
        await settings_handlers.on_settings_button(
            max_cb,
            SettingsCB(field="max_contracts"),
            state,
        )
        assert await state.get_state() == SettingsEdit.max_contracts.state
        await settings_handlers.edit_max_contracts(make_message("5", chat_id=chat_id), state)
        assert await state.get_state() is None

        openrouter_cb = make_callback(chat_id=chat_id)
        await settings_handlers.on_api_key_button(
            openrouter_cb,
            ApiKeyCB(action="set_openrouter"),
            state,
        )
        assert await state.get_state() == SettingsEdit.openrouter_key.state
        await settings_handlers.edit_openrouter_key(
            make_message("sk-or-updated", chat_id=chat_id),
            state,
        )
        assert await state.get_state() is None

        alpaca_cb = make_callback(chat_id=chat_id)
        await settings_handlers.on_api_key_button(
            alpaca_cb,
            ApiKeyCB(action="set_alpaca"),
            state,
        )
        assert await state.get_state() == SettingsEdit.alpaca_key.state
        await settings_handlers.edit_alpaca_key_step1(
            make_message("ALP-NEW", chat_id=chat_id),
            state,
        )
        assert await state.get_state() == SettingsEdit.alpaca_secret.state
        await settings_handlers.edit_alpaca_secret_step2(
            make_message("ALP-SECRET-NEW", chat_id=chat_id),
            state,
        )
        assert await state.get_state() is None

        av_cb = make_callback(chat_id=chat_id)
        await settings_handlers.on_api_key_button(
            av_cb,
            ApiKeyCB(action="set_av"),
            state,
        )
        assert await state.get_state() == SettingsEdit.alpha_vantage_key.state
        await settings_handlers.edit_av_key(make_message("AV-NEW", chat_id=chat_id), state)
        assert await state.get_state() is None

        user = await seeded_user.get_by_chat_id(str(chat_id))
        assert user is not None
        assert user.account_size == Decimal("12000")
        assert user.risk_profile == "Aggressive"
        assert user.timezone_label == "PT"
        assert user.broker == "Questrade"
        assert user.strategy_permission == "long"
        assert user.max_contracts == 5
        assert decrypt_or_none(user.openrouter_api_key_encrypted) == "sk-or-updated"
        assert decrypt_or_none(user.alpaca_api_key_encrypted) == "ALP-NEW"
        assert decrypt_or_none(user.alpaca_api_secret_encrypted) == "ALP-SECRET-NEW"
        assert decrypt_or_none(user.alpha_vantage_api_key_encrypted) == "AV-NEW"
    finally:
        await storage.close()


async def test_api_keys_screen_and_remove_actions(
    seeded_user: UserService,
    send_recorder: SendRecorder,
    patch_user_service_scope: None,
) -> None:
    chat_id = 12345
    state, storage = await make_state(chat_id)
    try:
        await settings_handlers.open_api_keys(make_message(BTN_API_KEYS, chat_id=chat_id))
        summary = send_recorder.calls[-1].text
        assert "OpenRouter: <b>set</b>" in summary
        assert "Alpaca: <b>set</b>" in summary
        assert "Alpha Vantage: <b>set</b>" in summary

        await settings_handlers.on_api_key_button(
            make_callback(chat_id=chat_id),
            ApiKeyCB(action="remove_alpaca"),
            state,
        )
        await settings_handlers.on_api_key_button(
            make_callback(chat_id=chat_id),
            ApiKeyCB(action="remove_av"),
            state,
        )

        user = await seeded_user.get_by_chat_id(str(chat_id))
        assert user is not None
        assert user.alpaca_api_key_encrypted is None
        assert user.alpaca_api_secret_encrypted is None
        assert user.alpha_vantage_api_key_encrypted is None
    finally:
        await storage.close()
