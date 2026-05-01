from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.db.models.cron_job import CronJob
from app.db.repositories._base import BaseRepository


class CronJobRepository(BaseRepository[CronJob]):
    model = CronJob

    async def list_for_user(self, user_id: UUID) -> list[CronJob]:
        result = await self.session.execute(
            select(CronJob).where(CronJob.user_id == user_id).order_by(CronJob.created_at)
        )
        return list(result.scalars().all())

    async def list_active(self) -> list[CronJob]:
        result = await self.session.execute(select(CronJob).where(CronJob.is_active.is_(True)))
        return list(result.scalars().all())
