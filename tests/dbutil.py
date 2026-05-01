from __future__ import annotations

import asyncpg

from app.core.config import get_settings


async def postgres_authenticates() -> bool:
    settings = get_settings()
    try:
        conn = await asyncpg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            user=settings.postgres_user,
            password=settings.postgres_password,
            database=settings.postgres_db,
            timeout=1.0,
        )
    except (OSError, asyncpg.PostgresError):
        return False
    await conn.close()
    return True
