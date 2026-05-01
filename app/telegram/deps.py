"""Tiny DI helpers for handlers.

Handlers need a DB session and a UserService scoped to the current update.
Keeping this in one place avoids each handler module reimplementing it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_sessionmaker
from app.services.user_service import UserService


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def user_service_scope() -> AsyncIterator[tuple[AsyncSession, UserService]]:
    async with session_scope() as session:
        yield session, UserService(session)
