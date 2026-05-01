from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import crypto
from app.db.models.user import User
from app.db.repositories.run_repo import WorkflowRunRepository
from app.db.repositories.user_repo import UserRepository
from app.scheduler.jobs import WorkflowRunner
from app.services.run_lock import RunLockService

pytestmark = pytest.mark.asyncio


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, name: str, value: str, *, ex: int, nx: bool) -> bool:
        del ex
        if nx and name in self.store:
            return False
        self.store[name] = value
        return True

    async def get(self, name: str) -> str | None:
        return self.store.get(name)

    async def delete(self, name: str) -> int:
        return 1 if self.store.pop(name, None) is not None else 0

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        del script, numkeys
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


async def _make_user(session: AsyncSession, telegram_chat_id: str) -> User:
    crypto.reset_cache()
    return await UserRepository(session).add(
        User(
            telegram_chat_id=telegram_chat_id,
            account_size=Decimal("5000.00"),
            risk_profile="Balanced",
            broker="Wealthsimple",
            timezone_label="ET",
            timezone_iana="America/Toronto",
            strategy_permission="long_and_short",
            max_contracts=3,
            openrouter_api_key_encrypted=crypto.encrypt("sk-or-test"),
        )
    )


def _sessionmaker_from(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    bind = session.bind
    assert bind is not None
    return async_sessionmaker(bind=bind, expire_on_commit=False, class_=AsyncSession)


async def test_concurrent_run_is_blocked_and_only_one_workflow_row_is_created(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, "tg-run-lock")
    await db_session.commit()

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_pipeline(_: AsyncSession, __) -> None:
        started.set()
        await release.wait()

    runner = WorkflowRunner(
        _sessionmaker_from(db_session),
        RunLockService(FakeRedis(), ttl_seconds=60),
        pipeline=slow_pipeline,
    )

    first_task = asyncio.create_task(runner.run_workflow(user.id, trigger_type="manual"))
    await started.wait()

    second_result = await runner.run_workflow(user.id, trigger_type="cron")
    assert second_result.outcome == "already_running"

    release.set()
    first_result = await first_task
    assert first_result.outcome == "success"
    assert first_result.run_id is not None

    repo = WorkflowRunRepository(db_session)
    assert len(await repo.list_by_user_status(user.id, "success")) == 1
    assert len(await repo.list_by_user_status(user.id, "running")) == 0
    assert len(await repo.list_by_user_status(user.id, "failed")) == 0


async def test_failed_pipeline_marks_workflow_run_failed(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, "tg-run-fail")
    await db_session.commit()

    async def failing_pipeline(_: AsyncSession, __) -> None:
        raise RuntimeError("pipeline exploded")

    runner = WorkflowRunner(
        _sessionmaker_from(db_session),
        RunLockService(FakeRedis(), ttl_seconds=60),
        pipeline=failing_pipeline,
    )

    result = await runner.run_workflow(str(user.id), trigger_type="manual")
    assert result.outcome == "failed"
    assert result.run_id is not None
    assert result.error_message == "pipeline exploded"

    failed_runs = await WorkflowRunRepository(db_session).list_by_user_status(user.id, "failed")
    assert len(failed_runs) == 1
    assert failed_runs[0].id == result.run_id
    assert failed_runs[0].error_message == "pipeline exploded"
    assert failed_runs[0].finished_at is not None
