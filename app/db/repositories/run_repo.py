from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from app.db.models.workflow_run import WorkflowRun
from app.db.repositories._base import BaseRepository


class WorkflowRunRepository(BaseRepository[WorkflowRun]):
    model = WorkflowRun

    async def list_by_user_status(self, user_id: UUID, status: str) -> list[WorkflowRun]:
        result = await self.session.execute(
            select(WorkflowRun).where(
                WorkflowRun.user_id == user_id, WorkflowRun.status == status
            )
        )
        return list(result.scalars().all())

    async def list_recent_for_user(
        self,
        user_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[WorkflowRun]:
        result = await self.session.execute(
            select(WorkflowRun)
            .where(WorkflowRun.user_id == user_id)
            .order_by(WorkflowRun.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_for_user(self, user_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(WorkflowRun).where(WorkflowRun.user_id == user_id)
        )
        return int(result.scalar_one())
