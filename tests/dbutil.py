from __future__ import annotations

import asyncpg

from app.core.config import get_settings


async def _connect(*, database: str) -> asyncpg.Connection:
    settings = get_settings()
    return await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=database,
        timeout=1.0,
    )


async def ensure_database() -> bool:
    settings = get_settings()
    try:
        conn = await _connect(database=settings.postgres_db)
    except asyncpg.InvalidCatalogNameError:
        try:
            admin = await _connect(database="postgres")
        except (OSError, asyncpg.PostgresError):
            return False

        database_name = settings.postgres_db.replace('"', '""')
        exists = await admin.fetchval(
            "select 1 from pg_database where datname = $1",
            settings.postgres_db,
        )
        if not exists:
            await admin.execute(f'create database "{database_name}"')
        await admin.close()

        conn = await _connect(database=settings.postgres_db)
    except (OSError, asyncpg.PostgresError):
        return False

    await conn.close()
    return True


async def postgres_authenticates() -> bool:
    return await ensure_database()
