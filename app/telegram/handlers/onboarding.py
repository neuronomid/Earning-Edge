"""Onboarding flow (PRD §11.1).

Twelve steps: welcome → account size → risk profile → timezone → broker →
strategy permission → OpenRouter key → Alpaca key+secret (skippable) →
Alpha Vantage key (optional) → default cron auto-created → summary → confirm
→ main menu.

Validators (PRD §7.1) run inline; bad keys reprompt rather than persist.
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
    DEFAULT_MAX_CONTRACTS,
    OnboardingPayload,
    TIMEZONE_DISPLAY,
    TIMEZONE_MAP,
    RiskProfile,
    StrategyPermission,
    TimezoneLabel,
)
from app.telegram.deps import user_service_scope
from app.telegram.fsm.onboarding_states import Onboarding
from app.telegram.handlers._common import send_text
from app.telegram.keyboards.confirm import (
    CANCEL_BTN,
    ChoiceCB,
    ConfirmCB,
    SKIP_BTN,
    cancel_keyboard,
    choice_keyboard,
    confirm_keyboard,
    skip_or_cancel_keyboard,
)
from app.telegram.keyboards.main_menu import main_menu_keyboard

router = Router(name="onboarding")


# ---------- choice option tables ----------

RISK_OPTIONS: list[tuple[str, str]] = [
    ("🛡 Conservative — 1% per trade", "Conservative"),
    ("⚖️ Balanced — 2% per trade (default)", "Balanced"),
    ("🔥 Aggressive — 4% per trade", "Aggressive"),
]

TIMEZONE_OPTIONS: list[tuple[str, str]] = [
    (TIMEZONE_DISPLAY["PT"], "PT"),
    (TIMEZONE_DISPLAY["MT"], "MT"),
    (TIMEZONE_DISPLAY["CT"], "CT"),
    (f"{TIMEZONE_DISPLAY['ET']} (default)", "ET"),
    (TIMEZONE_DISPLAY["AT"], "AT"),
    (TIMEZONE_DISPLAY["NT"], "NT"),
]

BROKER_OPTIONS: list[tuple[str, str]] = [
    ("Wealthsimple", "Wealthsimple"),
    ("Interactive Brokers", "IBKR"),
    ("Questrade", "Questrade"),
    ("Other / Skip for now", "Other"),
]

STRATEGY_OPTIONS: list[tuple[str, str]] = [
    ("📈 Long options only", "long"),
    ("📉 Short options only", "short"),
    ("🔁 Long and short (default)", "long_and_short"),
]


# ---------- step 1: account size ----------


@router.message(Onboarding.account_size, F.text == CANCEL_BTN)
async def cancel_in_account(message: Message, state: FSMContext) -> None:
    await _cancel(message, state)


@router.message(Onboarding.account_size)
async def step_account_size(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("$", "")
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        await send_text(
            message,
            "I couldn't parse that as a number. Try something like <code>5000</code>.",
        )
        return
    if value < Decimal("100") or value > Decimal("100000000"):
        await send_text(
            message,
            "Please enter a realistic amount between $100 and $100,000,000.",
        )
        return
    await state.update_data(account_size=str(value))
    await state.set_state(Onboarding.risk_profile)
    await send_text(
        message,
        "🎚 Pick your <b>risk profile</b>:",
        reply_markup=choice_keyboard("risk", RISK_OPTIONS),
    )


# ---------- step 2: risk profile ----------


@router.callback_query(Onboarding.risk_profile, ChoiceCB.filter(F.group == "risk"))
async def step_risk_profile(
    callback: CallbackQuery, callback_data: ChoiceCB, state: FSMContext
) -> None:
    if callback_data.value not in {"Conservative", "Balanced", "Aggressive"}:
        await callback.answer("Invalid choice.")
        return
    await state.update_data(risk_profile=callback_data.value)
    await callback.answer()
    await state.set_state(Onboarding.timezone)
    if callback.message:
        await send_text(
            callback.message,
            f"Got it: <b>{callback_data.value}</b>.\n\n🌎 Pick your <b>timezone</b>:",
            reply_markup=choice_keyboard("tz", TIMEZONE_OPTIONS),
        )


# ---------- step 3: timezone ----------


@router.callback_query(Onboarding.timezone, ChoiceCB.filter(F.group == "tz"))
async def step_timezone(
    callback: CallbackQuery, callback_data: ChoiceCB, state: FSMContext
) -> None:
    if callback_data.value not in TIMEZONE_MAP:
        await callback.answer("Invalid timezone.")
        return
    await state.update_data(timezone=callback_data.value)
    await callback.answer()
    await state.set_state(Onboarding.broker)
    if callback.message:
        await send_text(
            callback.message,
            (
                f"Saved: <b>{TIMEZONE_DISPLAY[callback_data.value]}</b> "  # type: ignore[index]
                f"(<code>{TIMEZONE_MAP[callback_data.value]}</code>).\n\n"  # type: ignore[index]
                "🏦 Which <b>broker</b> do you use?"
            ),
            reply_markup=choice_keyboard("broker", BROKER_OPTIONS),
        )


# ---------- step 4: broker ----------


@router.callback_query(Onboarding.broker, ChoiceCB.filter(F.group == "broker"))
async def step_broker(
    callback: CallbackQuery, callback_data: ChoiceCB, state: FSMContext
) -> None:
    await state.update_data(broker=callback_data.value)
    await callback.answer()
    await state.set_state(Onboarding.strategy_permission)
    if callback.message:
        await send_text(
            callback.message,
            "📜 Which option strategies should I consider for you?",
            reply_markup=choice_keyboard("strategy", STRATEGY_OPTIONS),
        )


# ---------- step 5: strategy permission ----------


@router.callback_query(
    Onboarding.strategy_permission, ChoiceCB.filter(F.group == "strategy")
)
async def step_strategy(
    callback: CallbackQuery, callback_data: ChoiceCB, state: FSMContext
) -> None:
    if callback_data.value not in {"long", "short", "long_and_short"}:
        await callback.answer("Invalid option.")
        return
    await state.update_data(strategy_permission=callback_data.value)
    await callback.answer()
    await state.set_state(Onboarding.openrouter_key)
    if callback.message:
        await send_text(
            callback.message,
            (
                "🔑 Send your <b>OpenRouter API key</b>.\n"
                "I'll run a single test call to confirm it works. "
                "It is stored encrypted and never logged.\n\n"
                "Get one at <code>openrouter.ai/keys</code>."
            ),
            reply_markup=cancel_keyboard(),
        )


# ---------- step 6: OpenRouter key ----------


@router.message(Onboarding.openrouter_key, F.text == CANCEL_BTN)
async def cancel_in_openrouter(message: Message, state: FSMContext) -> None:
    await _cancel(message, state)


@router.message(Onboarding.openrouter_key)
async def step_openrouter_key(message: Message, state: FSMContext) -> None:
    key = (message.text or "").strip()
    if not key:
        await send_text(message, "Please paste a non-empty key.")
        return

    validator = OpenRouterValidator()
    result = await validator.validate(key)
    if not result.ok:
        await send_text(
            message,
            (
                "❌ That key didn't work. "
                f"<i>{_short(result.detail)}</i>\n"
                "Try again, or send /cancel to stop."
            ),
        )
        return

    await state.update_data(openrouter_api_key=key)
    await state.set_state(Onboarding.alpaca_key)
    await send_text(
        message,
        (
            "✅ OpenRouter key validated.\n\n"
            "🔑 Now your <b>Alpaca API key</b> (recommended for option-chain data).\n"
            "Tap <b>Skip</b> to use the yfinance fallback instead. "
            "You can add Alpaca later from Settings."
        ),
        reply_markup=skip_or_cancel_keyboard(),
    )


# ---------- step 7: Alpaca key ----------


@router.message(Onboarding.alpaca_key, F.text == CANCEL_BTN)
async def cancel_in_alpaca_key(message: Message, state: FSMContext) -> None:
    await _cancel(message, state)


@router.message(Onboarding.alpaca_key, F.text == SKIP_BTN)
async def skip_alpaca(message: Message, state: FSMContext) -> None:
    await state.update_data(alpaca_api_key=None, alpaca_api_secret=None)
    await state.set_state(Onboarding.alpha_vantage_key)
    await send_text(
        message,
        (
            "Skipped Alpaca — I'll use the yfinance fallback for option chains.\n\n"
            "🔑 Optionally send your <b>Alpha Vantage API key</b> for cross-checking, "
            "or tap <b>Skip</b> to continue without it."
        ),
        reply_markup=skip_or_cancel_keyboard(),
    )


@router.message(Onboarding.alpaca_key)
async def step_alpaca_key(message: Message, state: FSMContext) -> None:
    key = (message.text or "").strip()
    if not key:
        await send_text(message, "Please paste a key, or tap <b>Skip</b>.")
        return
    await state.update_data(alpaca_api_key=key)
    await state.set_state(Onboarding.alpaca_secret)
    await send_text(
        message,
        "🔑 Now send your <b>Alpaca API secret</b>:",
        reply_markup=cancel_keyboard(),
    )


# ---------- step 8: Alpaca secret ----------


@router.message(Onboarding.alpaca_secret, F.text == CANCEL_BTN)
async def cancel_in_alpaca_secret(message: Message, state: FSMContext) -> None:
    await _cancel(message, state)


@router.message(Onboarding.alpaca_secret)
async def step_alpaca_secret(message: Message, state: FSMContext) -> None:
    secret = (message.text or "").strip()
    if not secret:
        await send_text(message, "Please paste the Alpaca secret.")
        return
    data = await state.get_data()
    api_key = data.get("alpaca_api_key", "")

    validator = AlpacaValidator()
    result = await validator.validate(api_key, secret)
    if not result.ok:
        await send_text(
            message,
            (
                "❌ Alpaca rejected those credentials. "
                f"<i>{_short(result.detail)}</i>\n"
                "Re-send the secret, or send /cancel to stop and skip Alpaca."
            ),
        )
        return

    await state.update_data(alpaca_api_secret=secret)
    await state.set_state(Onboarding.alpha_vantage_key)
    await send_text(
        message,
        (
            "✅ Alpaca credentials validated.\n\n"
            "🔑 Optionally send your <b>Alpha Vantage API key</b>, "
            "or tap <b>Skip</b> to continue without it."
        ),
        reply_markup=skip_or_cancel_keyboard(),
    )


# ---------- step 9: Alpha Vantage key ----------


@router.message(Onboarding.alpha_vantage_key, F.text == CANCEL_BTN)
async def cancel_in_av(message: Message, state: FSMContext) -> None:
    await _cancel(message, state)


@router.message(Onboarding.alpha_vantage_key, F.text == SKIP_BTN)
async def skip_av(message: Message, state: FSMContext) -> None:
    await state.update_data(alpha_vantage_api_key=None)
    await _show_summary(message, state)


@router.message(Onboarding.alpha_vantage_key)
async def step_av_key(message: Message, state: FSMContext) -> None:
    key = (message.text or "").strip()
    if not key:
        await send_text(message, "Please paste a key, or tap <b>Skip</b>.")
        return

    validator = AlphaVantageValidator()
    result = await validator.validate(key)
    if not result.ok:
        await send_text(
            message,
            (
                "❌ Alpha Vantage didn't accept that key. "
                f"<i>{_short(result.detail)}</i>\n"
                "Try again, or tap <b>Skip</b> to continue without it."
            ),
        )
        return

    await state.update_data(alpha_vantage_api_key=key)
    await _show_summary(message, state)


# ---------- step 10/11: summary + confirm ----------


async def _show_summary(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tz_label: TimezoneLabel = data["timezone"]  # type: ignore[assignment]

    has_alpaca = bool(data.get("alpaca_api_key"))
    has_av = bool(data.get("alpha_vantage_api_key"))

    summary = (
        "📋 <b>Setup summary</b>\n\n"
        f"💰 Account size: <b>${data['account_size']}</b>\n"
        f"🎚 Risk profile: <b>{data['risk_profile']}</b>\n"
        f"🌎 Timezone: <b>{TIMEZONE_DISPLAY[tz_label]}</b> "
        f"(<code>{TIMEZONE_MAP[tz_label]}</code>)\n"
        f"🏦 Broker: <b>{data['broker']}</b>\n"
        f"📜 Strategy: <b>{_pretty_strategy(data['strategy_permission'])}</b>\n"
        f"🔑 OpenRouter: <b>set</b>\n"
        f"🔑 Alpaca: <b>{'set' if has_alpaca else 'skipped (yfinance fallback)'}</b>\n"
        f"🔑 Alpha Vantage: <b>{'set' if has_av else 'skipped'}</b>\n\n"
        "🗓 Default cron: <b>Monday 10:30 AM</b> in your timezone.\n\n"
        "Confirm to save, or pick <b>Edit</b> to start over."
    )
    await state.set_state(Onboarding.confirm)
    await send_text(
        message,
        summary,
        reply_markup=confirm_keyboard(yes_label="✅ Confirm", no_label="✏️ Start over"),
    )


@router.callback_query(Onboarding.confirm, ConfirmCB.filter(F.action == "no"))
async def confirm_no(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Starting over.")
    await state.clear()
    if callback.message:
        await state.set_state(Onboarding.account_size)
        await send_text(
            callback.message,
            "Restarting onboarding. 💰 What's your <b>account size</b> in USD?",
            reply_markup=ReplyKeyboardRemove(),
        )


@router.callback_query(Onboarding.confirm, ConfirmCB.filter(F.action == "yes"))
async def confirm_yes(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    chat_id = str(callback.from_user.id) if callback.from_user else None
    if chat_id is None:
        await callback.answer("Missing chat id.")
        return

    payload = OnboardingPayload(
        telegram_chat_id=chat_id,
        account_size=Decimal(data["account_size"]),
        risk_profile=data["risk_profile"],  # type: ignore[arg-type]
        timezone_label=data["timezone"],  # type: ignore[arg-type]
        broker=data["broker"],
        strategy_permission=data["strategy_permission"],  # type: ignore[arg-type]
        openrouter_api_key=data["openrouter_api_key"],
        alpaca_api_key=data.get("alpaca_api_key"),
        alpaca_api_secret=data.get("alpaca_api_secret"),
        alpha_vantage_api_key=data.get("alpha_vantage_api_key"),
        max_contracts=DEFAULT_MAX_CONTRACTS,
    )
    async with user_service_scope() as (_, service):
        await service.create_from_onboarding(payload)

    await callback.answer("Saved.")
    await state.clear()
    if callback.message:
        await send_text(
            callback.message,
            (
                "🎉 You're all set.\n\n"
                "I'll run the first scan automatically every Monday at 10:30 AM in your timezone. "
                "You can also tap <b>🚀 Run Scan Now</b> below any time."
            ),
            reply_markup=main_menu_keyboard(),
        )


# ---------- helpers ----------


async def _cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_text(
        message,
        "Cancelled. Send /start when you're ready to try again.",
        reply_markup=ReplyKeyboardRemove(),
    )


def _short(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


_STRATEGY_PRETTY: dict[StrategyPermission, str] = {
    "long": "Long only",
    "short": "Short only",
    "long_and_short": "Long and short",
}


def _pretty_strategy(value: str) -> str:
    return _STRATEGY_PRETTY.get(value, value)  # type: ignore[arg-type]


_RISK: tuple[RiskProfile, ...] = ("Conservative", "Balanced", "Aggressive")
__all__ = ["router"]
