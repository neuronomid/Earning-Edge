from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from freezegun import freeze_time

from app.db.models.cron_job import CronJob
from app.scheduler.scheduler import (
    SchedulerService,
    build_cron_trigger,
    cron_job_id,
)


@freeze_time("2026-05-04 14:29:00+00:00")
def test_schedule_fires_at_the_expected_local_time() -> None:
    trigger = build_cron_trigger("monday", "10:30", "America/Toronto")

    next_fire = trigger.get_next_fire_time(None, datetime.now(UTC))

    assert next_fire == datetime(2026, 5, 4, 10, 30, tzinfo=ZoneInfo("America/Toronto"))
    assert next_fire.astimezone(UTC) == datetime(2026, 5, 4, 14, 30, tzinfo=UTC)


@freeze_time("2026-03-01 05:00:00+00:00")
def test_spring_forward_schedule_fires_exactly_once() -> None:
    zone = ZoneInfo("America/Toronto")
    trigger = build_cron_trigger("sunday", "02:30", "America/Toronto")

    first = trigger.get_next_fire_time(None, datetime.now(UTC).astimezone(zone))
    assert first is not None

    second = trigger.get_next_fire_time(first, first)
    third = trigger.get_next_fire_time(second, second) if second is not None else None

    assert first.astimezone(UTC) == datetime(2026, 3, 1, 7, 30, tzinfo=UTC)
    assert second is not None
    assert second.astimezone(UTC) == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    assert third is not None
    assert third.astimezone(UTC) == datetime(2026, 3, 15, 6, 30, tzinfo=UTC)


def test_scheduler_syncs_multiple_crons_and_prunes_inactive_jobs() -> None:
    scheduler = AsyncIOScheduler(jobstores={"default": MemoryJobStore()}, timezone="UTC")
    service = SchedulerService(scheduler=scheduler)

    user_id = uuid4()
    cron_a = CronJob(
        id=uuid4(),
        user_id=user_id,
        day_of_week="monday",
        local_time="10:30",
        timezone_label="ET",
        timezone_iana="America/Toronto",
        is_active=True,
    )
    cron_b = CronJob(
        id=uuid4(),
        user_id=user_id,
        day_of_week="wednesday",
        local_time="09:00",
        timezone_label="ET",
        timezone_iana="America/Toronto",
        is_active=True,
    )

    service.sync_jobs([cron_a, cron_b])
    assert {job.id for job in scheduler.get_jobs()} == {
        cron_job_id(cron_a),
        cron_job_id(cron_b),
    }

    cron_b.is_active = False
    service.sync_jobs([cron_a, cron_b])
    assert {job.id for job in scheduler.get_jobs()} == {cron_job_id(cron_a)}
