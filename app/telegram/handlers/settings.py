"""Settings + API keys screens (PRD §10.5).

Every editable field has a one-step FSM "edit" flow: tap field → bot prompts →
user replies → bot validates → save → confirm message.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from app.services.api_key_validators import (
    AlpacaValidator,
    AlphaVantageValidator,
    OpenRouterValidator,
)
from app.services.user_service import (
    TIMEZONE_DISPLAY,
    TIMEZONE_MAP,
    TimezoneLabel,
    UserService,
)
from app.telegram.deps import user_service_scope
from app.telegram.fsm.onboarding_states import SettingsEdit
from app.telegram.handlers._common import send_text
from app.telegram.handlers.onboarding import (
    BROKER_OPTIONS,
    RISK_OPTIONS,
    STRATEGY_OPTIONS,
    TIMEZONE_OPTIONS,
)
from app.telegram.keyboards.confirm import (
    CANCEL_BTN,
    ChoiceCB,
    cancel_keyboard,
    choice_keyboard,
)
from app.telegram.keyboards.main_menu import BTN_API_KEYS, BTN_SETTINGS, main_menu_keyboard
from app.telegram.keyboards.settings import (
    ApiKeyCB,
    SettingsCB,
    api_keys_keyboard,
    settings_keyboard,
)

router = Router(name="settings")


# ---------- entry points from main menu ----------


@router.message(F.text == BTN_SETTINGS)
async def open_settings(message: Message) -> None:
    chat_id = str(message.chat.id)
    async with user_service_scope() as (_, service):
        user = await service.get_by_chat_id(chat_id)
    if user is None:
        await send_text(
            message,
            "Send /start to finish setup first.",
            reply_markup=main_menu_keyboard(),
        )
        return

    summary = (
        "⚙️ <b>Settings</b>\n\n"
        f"💰 Account size: <b>${user.account_size}</b>\n"
        f"🎚 Risk profile: <b>{user.risk_profile}</b>\n"
        f"🌎 Timezone: <b>{TIMEZONE_DISPLAY.get(user.timezone_label, user.timezone_label)}</b> "  # type: ignore[arg-type]
        f"(<code>{user.timezone_iana}</code>)\n"
        f"🏦 Broker: <b>{user.broker}</b>\n"
        f"📜 Strategy: <b>{user.strategy_permission}</b>\n"
        f"🔢 Max contracts: <b>{user.max_contracts}</b>\n\n"
        "Pick a field to edit:"
    )
    await send_text(message, summary, reply_markup=settings_keyboard())


@router.message(F.text == BTN_API_KEYS)
async def open_api_keys(message: Message) -> None:
    chat_id = str(message.chat.id)
    async with user_service_scope() as (_, service):
        user = await service.get_by_chat_id(chat_id)
    if user is None:
        await send_text(message, "Send /start to finish setup first.")
        return

    has_alpaca = bool(user.alpaca_api_key_encrypted and user.alpaca_api_secret_encrypted)
    has_av = bool(user.alpha_vantage_api_key_encrypted)

    text = (
        "🔑 <b>API Keys</b>\n\n"
        f"OpenRouter: <b>{'set' if user.openrouter_api_key_encrypted else 'missing'}</b>\n"
        f"Alpaca: <b>{'set' if has_alpaca else 'not set (using yfinance)'}</b>\n"
        f"Alpha Vantage: <b>{'set' if has_av else 'not set'}</b>\n\n"
        "Pick what to update:"
    )
    await send_text(
        message,
        text,
        reply_markup=api_keys_keyboard(has_alpaca=has_alpaca, has_alpha_vantage=has_av),
    )


# ---------- field router (settings inline buttons) ----------


@router.callback_query(SettingsCB.filter())
async def on_settings_button(
    callback: CallbackQuery, callback_data: SettingsCB, state: FSMContext
) -> None:
    if callback.message is None:
        return
    field = callback_data.field
    await callback.answer()

    if field == "account_size":
        await state.set_state(SettingsEdit.account_size)
        await send_text(
            callback.message,
            "💰 Send the new <b>account size</b> in USD (e.g. <code>7500</code>).",
            reply_markup=cancel_keyboard(),
        )
    elif field == "risk_profile":
        await state.set_state(SettingsEdit.risk_profile)
        await send_text(
            callback.message,
            "🎚 Pick a new <b>risk profile</b>:",
            reply_markup=choice_keyboard("set_risk", RISK_OPTIONS),
        )
    elif field == "timezone":
        await state.set_state(SettingsEdit.timezone)
        await send_text(
            callback.message,
            "🌎 Pick a new <b>timezone</b>:",
            reply_markup=choice_keyboard("set_tz", TIMEZONE_OPTIONS),
        )
    elif field == "broker":
        await state.set_state(SettingsEdit.broker)
        await send_text(
            callback.message,
            "🏦 Pick your <b>broker</b>:",
            reply_markup=choice_keyboard("set_broker", BROKER_OPTIONS),
        )
    elif field == "strategy":
        await state.set_state(SettingsEdit.strategy_permission)
        await send_text(
            callback.message,
            "📜 Pick a <b>strategy permission</b>:",
            reply_markup=choice_keyboard("set_strategy", STRATEGY_OPTIONS),
        )
    elif field == "max_contracts":
        await state.set_state(SettingsEdit.max_contracts)
        await send_text(
            callback.message,
            "🔢 Send the new <b>max contracts per trade</b> (1–20):",
            reply_markup=cancel_keyboard(),
        )


# ---------- field router (API keys inline buttons) ----------


@router.callback_query(ApiKeyCB.filter())
async def on_api_key_button(
    callback: CallbackQuery, callback_data: ApiKeyCB, state: FSMContext
) -> None:
    if callback.message is None:
        return
    action = callback_data.action
    await callback.answer()

    if action == "set_openrouter":
        await state.set_state(SettingsEdit.openrouter_key)
        await send_text(
            callback.message,
            "🔑 Send your new <b>OpenRouter API key</b>. I'll validate it first.",
            reply_markup=cancel_keyboard(),
        )
    elif action == "set_alpaca":
        await state.set_state(SettingsEdit.alpaca_key)
        await send_text(
            callback.message,
            "🔑 Send your <b>Alpaca API key</b>:",
            reply_markup=cancel_keyboard(),
        )
    elif action == "set_av":
        await state.set_state(SettingsEdit.alpha_vantage_key)
        await send_text(
            callback.message,
            "🔑 Send your new <b>Alpha Vantage API key</b>:",
            reply_markup=cancel_keyboard(),
        )
    elif action == "remove_alpaca":
        async with user_service_scope() as (_, service):
            user = await service.get_by_chat_id(str(callback.from_user.id))
            if user is not None:
                await service.replace_alpaca_creds(user, None, None)
        await send_text(
            callback.message,
            "🗑 Alpaca credentials removed. I'll fall back to yfinance.",
            reply_markup=main_menu_keyboard(),
        )
    elif action == "remove_av":
        async with user_service_scope() as (_, service):
            user = await service.get_by_chat_id(str(callback.from_user.id))
            if user is not None:
                await service.replace_alpha_vantage_key(user, None)
        await send_text(
            callback.message,
            "🗑 Alpha Vantage key removed.",
            reply_markup=main_menu_keyboard(),
        )


# ---------- field handlers (text input) ----------


@router.message(SettingsEdit.account_size, F.text == CANCEL_BTN)
@router.message(SettingsEdit.openrouter_key, F.text == CANCEL_BTN)
@router.message(SettingsEdit.alpaca_key, F.text == CANCEL_BTN)
@router.message(SettingsEdit.alpaca_secret, F.text == CANCEL_BTN)
@router.message(SettingsEdit.alpha_vantage_key, F.text == CANCEL_BTN)
@router.message(SettingsEdit.max_contracts, F.text == CANCEL_BTN)
async def cancel_settings_edit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_text(message, "Cancelled.", reply_markup=main_menu_keyboard())


@router.message(SettingsEdit.account_size)
async def edit_account_size(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("$", "")
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        await send_text(message, "Couldn't parse a number. Try <code>5000</code>.")
        return
    if value < Decimal("100") or value > Decimal("100000000"):
        await send_text(message, "Use a value between $100 and $100,000,000.")
        return
    async with user_service_scope() as (_, service):
        user = await _user(service, message)
        if user is None:
            return
        await service.update_account_size(user, value)
    await state.clear()
    await send_text(message, f"✅ Account size updated to <b>${value}</b>.", reply_markup=main_menu_keyboard())


@router.message(SettingsEdit.max_contracts)
async def edit_max_contracts(message: Message, state: FSMContext) -> None:
    try:
        n = int((message.text or "").strip())
    except ValueError:
        await send_text(message, "Send a whole number, e.g. <code>3</code>.")
        return
    if n < 1 or n > 20:
        await send_text(message, "Pick a number between 1 and 20.")
        return
    async with user_service_scope() as (_, service):
        user = await _user(service, message)
        if user is None:
            return
        await service.update_max_contracts(user, n)
    await state.clear()
    await send_text(message, f"✅ Max contracts updated to <b>{n}</b>.", reply_markup=main_menu_keyboard())


@router.message(SettingsEdit.openrouter_key)
async def edit_openrouter_key(message: Message, state: FSMContext) -> None:
    key = (message.text or "").strip()
    result = await OpenRouterValidator().validate(key)
    if not result.ok:
        await send_text(
            message,
            f"❌ {result.detail}\nTry again, or tap <b>Cancel</b>.",
        )
        return
    async with user_service_scope() as (_, service):
        user = await _user(service, message)
        if user is None:
            return
        await service.replace_openrouter_key(user, key)
    await state.clear()
    await send_text(
        message,
        "✅ OpenRouter key updated and validated.",
        reply_markup=main_menu_keyboard(),
    )


@router.message(SettingsEdit.alpaca_key)
async def edit_alpaca_key_step1(message: Message, state: FSMContext) -> None:
    key = (message.text or "").strip()
    if not key:
        await send_text(message, "Send a non-empty key, or tap <b>Cancel</b>.")
        return
    await state.update_data(_alpaca_pending_key=key)
    await state.set_state(SettingsEdit.alpaca_secret)
    await send_text(
        message,
        "🔑 Now send the <b>Alpaca API secret</b>:",
        reply_markup=cancel_keyboard(),
    )


@router.message(SettingsEdit.alpaca_secret)
async def edit_alpaca_secret_step2(message: Message, state: FSMContext) -> None:
    secret = (message.text or "").strip()
    data = await state.get_data()
    api_key = data.get("_alpaca_pending_key", "")
    if not secret:
        await send_text(message, "Send a non-empty secret.")
        return
    result = await AlpacaValidator().validate(api_key, secret)
    if not result.ok:
        await send_text(message, f"❌ {result.detail}\nTry again, or tap <b>Cancel</b>.")
        return
    async with user_service_scope() as (_, service):
        user = await _user(service, message)
        if user is None:
            return
        await service.replace_alpaca_creds(user, api_key, secret)
    await state.clear()
    await send_text(
        message,
        "✅ Alpaca credentials updated and validated.",
        reply_markup=main_menu_keyboard(),
    )


@router.message(SettingsEdit.alpha_vantage_key)
async def edit_av_key(message: Message, state: FSMContext) -> None:
    key = (message.text or "").strip()
    result = await AlphaVantageValidator().validate(key)
    if not result.ok:
        await send_text(message, f"❌ {result.detail}\nTry again, or tap <b>Cancel</b>.")
        return
    async with user_service_scope() as (_, service):
        user = await _user(service, message)
        if user is None:
            return
        await service.replace_alpha_vantage_key(user, key)
    await state.clear()
    await send_text(
        message,
        "✅ Alpha Vantage key updated.",
        reply_markup=main_menu_keyboard(),
    )


# ---------- callback handlers (choice keyboards) ----------


@router.callback_query(SettingsEdit.risk_profile, ChoiceCB.filter(F.group == "set_risk"))
async def edit_risk_profile(
    callback: CallbackQuery, callback_data: ChoiceCB, state: FSMContext
) -> None:
    if callback_data.value not in {"Conservative", "Balanced", "Aggressive"}:
        await callback.answer("Invalid.")
        return
    async with user_service_scope() as (_, service):
        user = await _user_by_id(service, str(callback.from_user.id))
        if user is None:
            await callback.answer()
            return
        await service.update_risk_profile(user, callback_data.value)  # type: ignore[arg-type]
    await callback.answer("Saved.")
    await state.clear()
    if callback.message:
        await send_text(
            callback.message,
            f"✅ Risk profile set to <b>{callback_data.value}</b>.",
            reply_markup=main_menu_keyboard(),
        )


@router.callback_query(SettingsEdit.timezone, ChoiceCB.filter(F.group == "set_tz"))
async def edit_timezone(
    callback: CallbackQuery, callback_data: ChoiceCB, state: FSMContext
) -> None:
    if callback_data.value not in TIMEZONE_MAP:
        await callback.answer("Invalid.")
        return
    label: TimezoneLabel = callback_data.value  # type: ignore[assignment]
    async with user_service_scope() as (_, service):
        user = await _user_by_id(service, str(callback.from_user.id))
        if user is None:
            await callback.answer()
            return
        await service.update_timezone(user, label)
    await callback.answer("Saved.")
    await state.clear()
    if callback.message:
        await send_text(
            callback.message,
            (
                f"✅ Timezone set to <b>{TIMEZONE_DISPLAY[label]}</b> "
                f"(<code>{TIMEZONE_MAP[label]}</code>)."
            ),
            reply_markup=main_menu_keyboard(),
        )


@router.callback_query(SettingsEdit.broker, ChoiceCB.filter(F.group == "set_broker"))
async def edit_broker(
    callback: CallbackQuery, callback_data: ChoiceCB, state: FSMContext
) -> None:
    async with user_service_scope() as (_, service):
        user = await _user_by_id(service, str(callback.from_user.id))
        if user is None:
            await callback.answer()
            return
        await service.update_broker(user, callback_data.value)
    await callback.answer("Saved.")
    await state.clear()
    if callback.message:
        await send_text(
            callback.message,
            f"✅ Broker set to <b>{callback_data.value}</b>.",
            reply_markup=main_menu_keyboard(),
        )


@router.callback_query(
    SettingsEdit.strategy_permission, ChoiceCB.filter(F.group == "set_strategy")
)
async def edit_strategy_permission(
    callback: CallbackQuery, callback_data: ChoiceCB, state: FSMContext
) -> None:
    if callback_data.value not in {"long", "short", "long_and_short"}:
        await callback.answer("Invalid.")
        return
    async with user_service_scope() as (_, service):
        user = await _user_by_id(service, str(callback.from_user.id))
        if user is None:
            await callback.answer()
            return
        await service.update_strategy_permission(user, callback_data.value)  # type: ignore[arg-type]
    await callback.answer("Saved.")
    await state.clear()
    if callback.message:
        await send_text(
            callback.message,
            f"✅ Strategy permission set to <b>{callback_data.value}</b>.",
            reply_markup=ReplyKeyboardRemove(),
        )


# ---------- helpers ----------


async def _user(service: UserService, message: Message):  # noqa: ANN201 — internal helper
    user = await service.get_by_chat_id(str(message.chat.id))
    if user is None:
        await send_text(
            message,
            "Send /start to finish setup first.",
            reply_markup=main_menu_keyboard(),
        )
    return user


async def _user_by_id(service: UserService, chat_id: str):  # noqa: ANN201
    return await service.get_by_chat_id(chat_id)
