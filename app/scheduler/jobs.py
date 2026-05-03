"""Workflow runner + phase-11 pipeline entrypoint."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.run_repo import WorkflowRunRepository
from app.db.session import get_sessionmaker
from app.pipeline.orchestrator import get_pipeline_orchestrator
from app.services.run_lock import RunLockService, get_run_lock_service

RUN_ALREADY_ACTIVE_TEXT = (
    "⏳ A scan is already running. " "I\u2019ll show the result here when it finishes."
)
logger = get_logger(__name__)

PipelineFunc = Callable[[AsyncSession, WorkflowRun], Awaitable[object | None]]


@dataclass(slots=True)
class WorkflowRunResult:
    outcome: Literal["success", "already_running", "failed"]
    run_id: UUID | None = None
    error_message: str | None = None


class WorkflowRunner:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        run_lock: RunLockService,
        *,
        pipeline: PipelineFunc | None = None,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.run_lock = run_lock
        self.pipeline = pipeline or _default_pipeline

    async def run_workflow(self, user_id: UUID | str, *, trigger_type: str) -> WorkflowRunResult:
        user_uuid = _coerce_uuid(user_id)
        handle = await self.run_lock.acquire(user_uuid)
        if handle is None:
            return WorkflowRunResult(outcome="already_running")

        run_id: UUID | None = None
        try:
            async with self.sessionmaker() as session:
                run = await WorkflowRunRepository(session).add(
                    WorkflowRun(user_id=user_uuid, trigger_type=trigger_type, status="running")
                )
                run_id = run.id
                await session.commit()

            async with self.sessionmaker() as session:
                run = await _get_run(session, run_id)
                await self.pipeline(session, run)
                if run.status == "running":
                    run.status = "success"
                if run.finished_at is None:
                    run.finished_at = datetime.now(UTC)
                await session.commit()

            return WorkflowRunResult(outcome="success", run_id=run_id)
        except Exception as exc:
            logger.exception(
                "workflow_run_failed",
                user_id=str(user_uuid),
                trigger_type=trigger_type,
                run_id=str(run_id) if run_id is not None else None,
            )
            if run_id is not None:
                async with self.sessionmaker() as session:
                    run = await _get_run(session, run_id)
                    run.status = "failed"
                    run.error_message = str(exc)
                    run.finished_at = datetime.now(UTC)
                    await session.commit()
            return WorkflowRunResult(
                outcome="failed",
                run_id=run_id,
                error_message=str(exc),
            )
        finally:
            await handle.release()


async def _default_pipeline(_: AsyncSession, __: WorkflowRun) -> None:
    await get_pipeline_orchestrator().run(_, __)


async def _get_run(session: AsyncSession, run_id: UUID) -> WorkflowRun:
    run = await WorkflowRunRepository(session).get(run_id)
    if run is None:
        raise LookupError(f"Workflow run {run_id} disappeared before completion")
    return run


def _coerce_uuid(user_id: UUID | str) -> UUID:
    return user_id if isinstance(user_id, UUID) else UUID(user_id)


@lru_cache(maxsize=1)
def get_workflow_runner() -> WorkflowRunner:
    return WorkflowRunner(get_sessionmaker(), get_run_lock_service())


async def run_workflow(user_id: str, trigger_type: str = "cron") -> WorkflowRunResult:
    return await get_workflow_runner().run_workflow(user_id, trigger_type=trigger_type)
