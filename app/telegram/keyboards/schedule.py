"""Schedule-management inline keyboards."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.models.cron_job import CronJob
from app.scheduler.scheduler import DAY_OPTIONS


class ScheduleActionCB(CallbackData, prefix="sched"):
    action: str
    cron_id: str = ""


class ScheduleDayCB(CallbackData, prefix="sched_day"):
    day_of_week: str


def schedule_keyboard(crons: Sequence[CronJob]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="+ Add Schedule",
                callback_data=ScheduleActionCB(action="add").pack(),
            )
        ]
    ]

    for index, cron in enumerate(crons, start=1):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"✏️ Edit #{index}",
                    callback_data=ScheduleActionCB(
                        action="edit",
                        cron_id=str(cron.id),
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text=f"🗑 Delete #{index}",
                    callback_data=ScheduleActionCB(
                        action="delete",
                        cron_id=str(cron.id),
                    ).pack(),
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="⏸ Pause All",
                callback_data=ScheduleActionCB(action="pause_all").pack(),
            ),
            InlineKeyboardButton(
                text="▶️ Resume All",
                callback_data=ScheduleActionCB(action="resume_all").pack(),
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_day_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=label,
                callback_data=ScheduleDayCB(day_of_week=value).pack(),
            )
        ]
        for label, value in DAY_OPTIONS
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="✖️ Cancel",
                callback_data=ScheduleActionCB(action="cancel").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
