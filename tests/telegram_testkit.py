from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.user_service import UserService


@dataclass(slots=True)
class SentCall:
    target: object
    text: str
    kwargs: dict[str, Any]


@dataclass(slots=True)
class SendRecorder:
    calls: list[SentCall] = field(default_factory=list)

    async def __call__(self, target: object, text: str, **kwargs: Any) -> object:
        self.calls.append(SentCall(target=target, text=text, kwargs=kwargs))
        return SimpleNamespace(text=text, reply_markup=kwargs.get("reply_markup"))


async def make_state(chat_id: int = 12345, *, bot_id: int = 1) -> tuple[FSMContext, MemoryStorage]:
    storage = MemoryStorage()
    key = StorageKey(bot_id=bot_id, chat_id=chat_id, user_id=chat_id)
    return FSMContext(storage=storage, key=key), storage


def make_message(text: str | None = None, *, chat_id: int = 12345) -> object:
    return SimpleNamespace(
        text=text,
        chat=SimpleNamespace(id=chat_id),
        from_user=SimpleNamespace(id=chat_id),
    )


def make_callback(*, chat_id: int = 12345, message: object | None = None) -> object:
    return SimpleNamespace(
        from_user=SimpleNamespace(id=chat_id),
        message=message or make_message(chat_id=chat_id),
        answer=AsyncMock(),
    )


def make_user_service_scope(session: AsyncSession):
    @asynccontextmanager
    async def scope() -> AsyncIterator[tuple[AsyncSession, UserService]]:
        try:
            yield session, UserService(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    return scope
