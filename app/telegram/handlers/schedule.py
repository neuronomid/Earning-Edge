"""Schedule-management UI for Phase 3."""

from __future__ import annotations

from uuid import UUID

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.db.models.cron_job import CronJob
from app.db.models.user import User
from app.scheduler.scheduler import DAY_OPTIONS, get_scheduler_service, parse_local_time
from app.services.user_service import TIMEZONE_DISPLAY, UserService
from app.telegram.deps import user_service_scope
from app.telegram.fsm.onboarding_states import ScheduleEdit
from app.telegram.handlers._common import send_text
from app.telegram.keyboards.confirm import CANCEL_BTN, cancel_keyboard
from app.telegram.keyboards.main_menu import BTN_MANAGE_SCHEDULE, main_menu_keyboard
from app.telegram.keyboards.schedule import (
    ScheduleActionCB,
    ScheduleDayCB,
    schedule_day_keyboard,
    schedule_keyboard,
)

router = Router(name="schedule")

_DAY_LABELS = {value: label for label, value in DAY_OPTIONS}


@router.message(F.text == BTN_MANAGE_SCHEDULE)
async def open_schedule(message: Message) -> None:
    async with user_service_scope() as (_, service):
        user = await service.get_by_chat_id(str(message.chat.id))
        if user is None:
            await send_text(
                message,
                "Send /start to finish setup first.",
                reply_markup=main_menu_keyboard(),
            )
            return
        crons = await service.list_crons_for_user(user)

    await send_text(
        message,
        _schedule_summary(user.timezone_label, crons),
        reply_markup=schedule_keyboard(crons),
    )


@router.callback_query(ScheduleActionCB.filter())
async def on_schedule_action(
    callback: CallbackQuery, callback_data: ScheduleActionCB, state: FSMContext
) -> None:
    if callback.message is None:
        return
    await callback.answer()

    action = callback_data.action
    if action == "add":
        await state.clear()
        await state.update_data(schedule_mode="add")
        await state.set_state(ScheduleEdit.day_of_week)
        await send_text(
            callback.message,
            "🗓 Pick the <b>day of week</b> for this schedule:",
            reply_markup=schedule_day_keyboard(),
        )
        return

    if action == "cancel":
        await state.clear()
        await send_text(callback.message, "Cancelled.", reply_markup=main_menu_keyboard())
        return

    if action in {"pause_all", "resume_all"}:
        async with user_service_scope() as (_, service):
            user = await _require_user(service, callback)
            if user is None:
                return
            if action == "pause_all":
                await service.pause_all_crons(user)
            else:
                await service.resume_all_crons(user)
            crons = await service.list_crons_for_user(user)
            timezone_label = user.timezone_label

        await get_scheduler_service().sync_from_database()
        await send_text(
            callback.message,
            _schedule_summary(timezone_label, crons),
            reply_markup=schedule_keyboard(crons),
        )
        return

    if callback_data.cron_id == "":
        await send_text(callback.message, "I couldn't identify that schedule entry.")
        return

    cron_id = UUID(callback_data.cron_id)
    async with user_service_scope() as (_, service):
        user = await _require_user(service, callback)
        if user is None:
            return
        cron = await service.get_cron_for_user(user, cron_id)
        if cron is None:
            await send_text(
                callback.message,
                "That schedule no longer exists. Open Manage Schedule again to refresh.",
                reply_markup=main_menu_keyboard(),
            )
            return

        if action == "edit":
            await state.clear()
            await state.update_data(schedule_mode="edit", schedule_cron_id=str(cron.id))
            await state.set_state(ScheduleEdit.day_of_week)
            await send_text(
                callback.message,
                (
                    f"✏️ Editing <b>{_DAY_LABELS[cron.day_of_week]}</b> at "
                    f"<b>{cron.local_time}</b>.\n\nPick the new <b>day of week</b>:"
                ),
                reply_markup=schedule_day_keyboard(),
            )
            return

        if action == "delete":
            await service.delete_cron(cron)
            crons = await service.list_crons_for_user(user)
        else:
            await send_text(callback.message, "Unsupported schedule action.")
            return

        timezone_label = user.timezone_label

    await get_scheduler_service().sync_from_database()
    await send_text(
        callback.message,
        _schedule_summary(timezone_label, crons),
        reply_markup=schedule_keyboard(crons),
    )


@router.callback_query(ScheduleEdit.day_of_week, ScheduleDayCB.filter())
async def choose_schedule_day(
    callback: CallbackQuery, callback_data: ScheduleDayCB, state: FSMContext
) -> None:
    if callback.message is None:
        return
    await callback.answer()
    await state.update_data(schedule_day_of_week=callback_data.day_of_week)
    await state.set_state(ScheduleEdit.local_time)
    await send_text(
        callback.message,
        (
            f"🕒 Saved <b>{_DAY_LABELS[callback_data.day_of_week]}</b>.\n"
            "Now send the <b>local time</b> in <code>HH:MM</code> 24-hour format "
            "(example: <code>09:00</code>)."
        ),
        reply_markup=cancel_keyboard(),
    )


@router.message(ScheduleEdit.local_time, F.text == CANCEL_BTN)
async def cancel_schedule_edit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_text(message, "Cancelled.", reply_markup=main_menu_keyboard())


@router.message(ScheduleEdit.local_time)
async def save_schedule_time(message: Message, state: FSMContext) -> None:
    local_time = (message.text or "").strip()
    try:
        parse_local_time(local_time)
    except ValueError:
        await send_text(
            message,
            "Use <code>HH:MM</code> in 24-hour time, for example <code>10:30</code>.",
        )
        return

    data = await state.get_data()
    day_of_week = str(data.get("schedule_day_of_week", "")).lower()
    mode = str(data.get("schedule_mode", ""))
    cron_id = str(data.get("schedule_cron_id", ""))
    if day_of_week not in _DAY_LABELS:
        await state.clear()
        await send_text(
            message,
            "I lost track of that schedule day. Please open Manage Schedule again.",
            reply_markup=main_menu_keyboard(),
        )
        return

    async with user_service_scope() as (_, service):
        user = await service.get_by_chat_id(str(message.chat.id))
        if user is None:
            await state.clear()
            await send_text(
                message,
                "Send /start to finish setup first.",
                reply_markup=main_menu_keyboard(),
            )
            return

        if mode == "add":
            await service.add_cron_for_user(user, day_of_week=day_of_week, local_time=local_time)
        elif mode == "edit":
            cron = await service.get_cron_for_user(user, UUID(cron_id))
            if cron is None:
                await state.clear()
                await send_text(
                    message,
                    "That schedule no longer exists. Open Manage Schedule again to refresh.",
                    reply_markup=main_menu_keyboard(),
                )
                return
            await service.update_cron(cron, day_of_week=day_of_week, local_time=local_time)
        else:
            await state.clear()
            await send_text(
                message,
                "I lost track of that schedule edit. Please open Manage Schedule again.",
                reply_markup=main_menu_keyboard(),
            )
            return

        crons = await service.list_crons_for_user(user)
        timezone_label = user.timezone_label

    await get_scheduler_service().sync_from_database()
    await state.clear()
    await send_text(
        message,
        _schedule_summary(timezone_label, crons),
        reply_markup=schedule_keyboard(crons),
    )


def _schedule_summary(timezone_label: str, crons: list[CronJob]) -> str:
    display_timezone = TIMEZONE_DISPLAY.get(timezone_label, timezone_label)
    if not crons:
        return (
            "🗓 <b>Your Schedule</b>\n\n"
            "No cron jobs yet.\n\n"
            f"New schedules use your current timezone: <b>{display_timezone}</b>."
        )

    lines = [
        "🗓 <b>Your Schedule</b>",
        "",
        f"New schedules use your current timezone: <b>{display_timezone}</b>.",
        "",
    ]
    for index, cron in enumerate(crons, start=1):
        status = "Active" if cron.is_active else "Paused"
        lines.append(
            f"{index}. <b>{_DAY_LABELS[cron.day_of_week]}</b> at "
            f"<b>{cron.local_time}</b> — {status}"
        )
        timezone_name = TIMEZONE_DISPLAY.get(cron.timezone_label, cron.timezone_label)
        lines.append(f"   {timezone_name} (<code>{cron.timezone_iana}</code>)")
    return "\n".join(lines)


async def _require_user(service: UserService, callback: CallbackQuery) -> User | None:
    user = await service.get_by_chat_id(str(callback.from_user.id))
    if user is None and callback.message is not None:
        await send_text(
            callback.message,
            "Send /start to finish setup first.",
            reply_markup=main_menu_keyboard(),
        )
    return user
