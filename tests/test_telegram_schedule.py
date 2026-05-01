from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.scheduler.jobs import RUN_ALREADY_ACTIVE_TEXT, WorkflowRunResult
from app.services.user_service import OnboardingPayload, UserService
from app.telegram.fsm.onboarding_states import ScheduleEdit
from app.telegram.handlers import menu as menu_handlers
from app.telegram.handlers import schedule as schedule_handlers
from app.telegram.keyboards.main_menu import BTN_MANAGE_SCHEDULE, BTN_RUN_SCAN
from app.telegram.keyboards.schedule import ScheduleActionCB, ScheduleDayCB
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
        openrouter_api_key="sk-or-schedule",
    )


@dataclass
class FakeSchedulerService:
    sync_calls: int = 0

    async def sync_from_database(self) -> None:
        self.sync_calls += 1


class FakeWorkflowRunner:
    def __init__(self, result: WorkflowRunResult) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def run_workflow(self, user_id, *, trigger_type: str) -> WorkflowRunResult:
        self.calls.append((str(user_id), trigger_type))
        return self.result


@pytest.fixture
def send_recorder(monkeypatch: pytest.MonkeyPatch) -> SendRecorder:
    recorder = SendRecorder()
    monkeypatch.setattr(schedule_handlers, "send_text", recorder)
    monkeypatch.setattr(menu_handlers, "send_text", recorder)
    return recorder


@pytest.fixture
def patch_user_service_scope(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    scope = make_user_service_scope(db_session)
    monkeypatch.setattr(schedule_handlers, "user_service_scope", scope)
    monkeypatch.setattr(menu_handlers, "user_service_scope", scope)


@pytest_asyncio.fixture
async def seeded_user(db_session: AsyncSession) -> UserService:
    service = UserService(db_session)
    await service.create_from_onboarding(_payload(chat_id=12345))
    await db_session.commit()
    return service


@pytest.fixture
def fake_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> FakeSchedulerService:
    scheduler = FakeSchedulerService()
    monkeypatch.setattr(schedule_handlers, "get_scheduler_service", lambda: scheduler)
    return scheduler


async def test_manage_schedule_add_edit_pause_resume_and_delete(
    db_session: AsyncSession,
    seeded_user: UserService,
    send_recorder: SendRecorder,
    patch_user_service_scope: None,
    fake_scheduler: FakeSchedulerService,
) -> None:
    chat_id = 12345
    state, storage = await make_state(chat_id)
    try:
        await schedule_handlers.open_schedule(make_message(BTN_MANAGE_SCHEDULE, chat_id=chat_id))
        assert "🗓 <b>Your Schedule</b>" in send_recorder.calls[-1].text
        assert "Monday" in send_recorder.calls[-1].text

        await schedule_handlers.on_schedule_action(
            make_callback(chat_id=chat_id),
            ScheduleActionCB(action="add"),
            state,
        )
        assert await state.get_state() == ScheduleEdit.day_of_week.state

        await schedule_handlers.choose_schedule_day(
            make_callback(chat_id=chat_id),
            ScheduleDayCB(day_of_week="wednesday"),
            state,
        )
        assert await state.get_state() == ScheduleEdit.local_time.state

        await schedule_handlers.save_schedule_time(
            make_message("09:00", chat_id=chat_id),
            state,
        )
        assert await state.get_state() is None

        user = await seeded_user.get_by_chat_id(str(chat_id))
        assert user is not None
        crons = await seeded_user.list_crons_for_user(user)
        assert len(crons) == 2
        added = next(cron for cron in crons if cron.day_of_week == "wednesday")
        assert added.local_time == "09:00"
        assert fake_scheduler.sync_calls == 1

        await schedule_handlers.on_schedule_action(
            make_callback(chat_id=chat_id),
            ScheduleActionCB(action="edit", cron_id=str(added.id)),
            state,
        )
        assert await state.get_state() == ScheduleEdit.day_of_week.state

        await schedule_handlers.choose_schedule_day(
            make_callback(chat_id=chat_id),
            ScheduleDayCB(day_of_week="friday"),
            state,
        )
        await schedule_handlers.save_schedule_time(
            make_message("08:15", chat_id=chat_id),
            state,
        )

        user = await seeded_user.get_by_chat_id(str(chat_id))
        assert user is not None
        crons = await seeded_user.list_crons_for_user(user)
        edited = next(cron for cron in crons if cron.id == added.id)
        assert edited.day_of_week == "friday"
        assert edited.local_time == "08:15"
        assert fake_scheduler.sync_calls == 2

        await schedule_handlers.on_schedule_action(
            make_callback(chat_id=chat_id),
            ScheduleActionCB(action="pause_all"),
            state,
        )
        crons = await seeded_user.list_crons_for_user(user)
        assert all(cron.is_active is False for cron in crons)
        assert fake_scheduler.sync_calls == 3

        await schedule_handlers.on_schedule_action(
            make_callback(chat_id=chat_id),
            ScheduleActionCB(action="resume_all"),
            state,
        )
        crons = await seeded_user.list_crons_for_user(user)
        assert all(cron.is_active is True for cron in crons)
        assert fake_scheduler.sync_calls == 4

        await schedule_handlers.on_schedule_action(
            make_callback(chat_id=chat_id),
            ScheduleActionCB(action="delete", cron_id=str(added.id)),
            state,
        )
        crons = await seeded_user.list_crons_for_user(user)
        assert len(crons) == 1
        assert crons[0].day_of_week == "monday"
        assert fake_scheduler.sync_calls == 5
    finally:
        await storage.close()


async def test_manage_schedule_reprompts_on_invalid_time(
    fake_scheduler: FakeSchedulerService,
    send_recorder: SendRecorder,
) -> None:
    del fake_scheduler
    state, storage = await make_state(12345)
    try:
        await state.set_state(ScheduleEdit.local_time)
        await state.update_data(schedule_mode="add", schedule_day_of_week="monday")

        await schedule_handlers.save_schedule_time(make_message("25:61", chat_id=12345), state)

        assert await state.get_state() == ScheduleEdit.local_time.state
        assert "HH:MM" in send_recorder.calls[-1].text
    finally:
        await storage.close()


async def test_run_scan_now_shows_duplicate_run_message(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_user_service_scope: None,
    seeded_user: UserService,
) -> None:
    del seeded_user
    runner = FakeWorkflowRunner(WorkflowRunResult(outcome="already_running"))
    monkeypatch.setattr(menu_handlers, "get_workflow_runner", lambda: runner)

    await menu_handlers.run_scan_now(make_message(BTN_RUN_SCAN, chat_id=12345))

    assert send_recorder.calls[-1].text == RUN_ALREADY_ACTIVE_TEXT
    assert runner.calls[0][1] == "manual"


async def test_run_scan_now_starts_manual_workflow(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_user_service_scope: None,
    seeded_user: UserService,
) -> None:
    del seeded_user
    runner = FakeWorkflowRunner(WorkflowRunResult(outcome="success"))
    monkeypatch.setattr(menu_handlers, "get_workflow_runner", lambda: runner)

    await menu_handlers.run_scan_now(make_message(BTN_RUN_SCAN, chat_id=12345))

    assert "🚀 Scan started." in send_recorder.calls[-1].text
    assert runner.calls[0][1] == "manual"
