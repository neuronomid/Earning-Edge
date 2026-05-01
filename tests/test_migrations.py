from __future__ import annotations

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from tests.dbutil import postgres_authenticates

EXPECTED_TABLES = {
    "users",
    "cron_jobs",
    "workflow_runs",
    "candidates",
    "option_contracts",
    "recommendations",
    "feedback_events",
}


def _alembic_config(async_url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", async_url)
    return cfg


async def _async_table_names(async_url: str) -> set[str]:
    engine = create_async_engine(async_url)
    try:
        async with engine.connect() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
            return set(tables)
    finally:
        await engine.dispose()


def _table_names(async_url: str) -> set[str]:
    return asyncio.run(_async_table_names(async_url))


async def _drop_all_tables(async_url: str) -> None:
    from sqlalchemy import text

    engine = create_async_engine(async_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def test_migration_up_and_down() -> None:
    if not asyncio.run(postgres_authenticates()):
        pytest.skip("Postgres is not configured; start docker compose to run migration tests")

    settings = get_settings()
    async_url = settings.database_url
    cfg = _alembic_config(async_url)

    asyncio.run(_drop_all_tables(async_url))
    command.upgrade(cfg, "head")

    tables = _table_names(async_url)
    assert EXPECTED_TABLES.issubset(tables), f"missing: {EXPECTED_TABLES - tables}"

    command.downgrade(cfg, "base")
    tables = _table_names(async_url)
    assert not (EXPECTED_TABLES & tables), f"leftover: {EXPECTED_TABLES & tables}"

    command.upgrade(cfg, "head")
