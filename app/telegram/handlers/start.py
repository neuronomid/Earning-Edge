"""/start entry point. Routes existing users to the main menu and new users
into onboarding (PRD §11.1)."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from app.telegram.deps import user_service_scope
from app.telegram.fsm.onboarding_states import Onboarding
from app.telegram.handlers._common import send_text
from app.telegram.keyboards.main_menu import main_menu_keyboard

router = Router(name="start")

WELCOME_TEXT = (
    "👋 Welcome to <b>Earning Edge</b>.\n\n"
    "I scan the largest companies reporting earnings next week, study the option chains, "
    "and send you one clear setup per scan — never both a call and a put for the same stock.\n\n"
    "Let's set up your account. You can cancel any time with /cancel."
)

PROMPT_ACCOUNT_SIZE = (
    "💰 What's your <b>account size</b> in USD?\n"
    "Send a number, e.g. <code>5000</code>."
)


@router.message(CommandStart())
async def on_start(message: Message, state: FSMContext) -> None:
    chat_id = str(message.chat.id)
    async with user_service_scope() as (_, service):
        existing = await service.get_by_chat_id(chat_id)

    if existing is not None:
        await state.clear()
        await send_text(
            message,
            "👋 Welcome back. Pick an action below.",
            reply_markup=main_menu_keyboard(),
        )
        return

    await state.clear()
    await send_text(message, WELCOME_TEXT, reply_markup=ReplyKeyboardRemove())
    await state.set_state(Onboarding.account_size)
    await send_text(message, PROMPT_ACCOUNT_SIZE)


@router.message(Command("cancel"))
async def on_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await send_text(
            message, "Nothing to cancel right now.", reply_markup=main_menu_keyboard()
        )
        return
    await state.clear()
    await send_text(
        message,
        "Cancelled. You can /start again whenever you're ready.",
        reply_markup=ReplyKeyboardRemove(),
    )
