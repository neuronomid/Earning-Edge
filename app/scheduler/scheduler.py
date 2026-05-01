"""APScheduler bootstrap and cron-row synchronization."""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import lru_cache
from zoneinfo import ZoneInfo

from apscheduler.job import Job
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.db.models.cron_job import CronJob
from app.db.repositories.cron_repo import CronJobRepository
from app.db.session import get_sessionmaker
from app.scheduler.jobs import run_workflow

DAY_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Monday", "monday"),
    ("Tuesday", "tuesday"),
    ("Wednesday", "wednesday"),
    ("Thursday", "thursday"),
    ("Friday", "friday"),
    ("Saturday", "saturday"),
    ("Sunday", "sunday"),
)
VALID_DAYS = {value for _, value in DAY_OPTIONS}
TRIGGER_DAYS = {
    "monday": "mon",
    "tuesday": "tue",
    "wednesday": "wed",
    "thursday": "thu",
    "friday": "fri",
    "saturday": "sat",
    "sunday": "sun",
}
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def parse_local_time(local_time: str) -> tuple[int, int]:
    if not TIME_RE.fullmatch(local_time):
        raise ValueError("Time must use HH:MM 24-hour format")
    hour_text, minute_text = local_time.split(":")
    return int(hour_text), int(minute_text)


def build_cron_trigger(day_of_week: str, local_time: str, timezone_iana: str) -> CronTrigger:
    normalized_day = day_of_week.strip().lower()
    if normalized_day not in VALID_DAYS:
        raise ValueError(f"Unsupported weekday: {day_of_week}")
    hour, minute = parse_local_time(local_time)
    return CronTrigger(
        day_of_week=TRIGGER_DAYS[normalized_day],
        hour=hour,
        minute=minute,
        timezone=ZoneInfo(timezone_iana),
    )


def cron_job_id(cron: CronJob) -> str:
    return f"cron:{cron.id}"


def _build_jobstores(settings: Settings) -> dict[str, MemoryJobStore | SQLAlchemyJobStore]:
    if settings.app_env == "test":
        return {"default": MemoryJobStore()}
    return {"default": SQLAlchemyJobStore(url=settings.scheduler_database_url)}


class SchedulerService:
    def __init__(
        self,
        *,
        scheduler: AsyncIOScheduler | None = None,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.sessionmaker = sessionmaker or get_sessionmaker()
        self.scheduler = scheduler or AsyncIOScheduler(
            jobstores=_build_jobstores(self.settings),
            timezone="UTC",
        )

    async def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
        await self.sync_from_database()

    async def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def sync_from_database(self) -> None:
        async with self.sessionmaker() as session:
            crons = await CronJobRepository(session).list()
        self.sync_jobs(crons)

    def sync_jobs(self, crons: Sequence[CronJob]) -> None:
        active_job_ids = {cron_job_id(cron) for cron in crons if cron.is_active}
        for job in list(self.scheduler.get_jobs()):
            if job.id.startswith("cron:") and job.id not in active_job_ids:
                self.scheduler.remove_job(job.id)

        for cron in crons:
            if not cron.is_active:
                continue
            self.scheduler.add_job(
                run_workflow,
                trigger=build_cron_trigger(
                    cron.day_of_week,
                    cron.local_time,
                    cron.timezone_iana,
                ),
                args=[str(cron.user_id), "cron"],
                id=cron_job_id(cron),
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=300,
            )

    def get_job(self, cron: CronJob) -> Job | None:
        return self.scheduler.get_job(cron_job_id(cron))


@lru_cache(maxsize=1)
def get_scheduler_service() -> SchedulerService:
    return SchedulerService()
