from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

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
