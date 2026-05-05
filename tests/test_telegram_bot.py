from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramConflictError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.methods import GetUpdates

from app.core.config import Settings
from app.telegram.bot import (
    BotStartupError,
    build_bot,
    build_runtime_storage,
    build_storage,
    ensure_polling_available,
)


def test_build_bot_requires_token() -> None:
    settings = Settings(telegram_bot_token="")

    with pytest.raises(BotStartupError, match="TELEGRAM_BOT_TOKEN is not set"):
        build_bot(settings)


def test_build_storage_uses_memory_for_tests() -> None:
    settings = Settings(app_env="test")

    storage = build_storage(settings)

    assert isinstance(storage, MemoryStorage)


@pytest.mark.asyncio
async def test_build_runtime_storage_falls_back_when_redis_unreachable(monkeypatch) -> None:
    settings = Settings(app_env="development", redis_host="missing-redis")
    ping = AsyncMock(return_value="Error connecting to Redis")
    monkeypatch.setattr("app.telegram.bot._redis_ping_error", ping)

    storage = await build_runtime_storage(settings)

    assert isinstance(storage, MemoryStorage)
    ping.assert_awaited_once_with(settings.redis_url)


@pytest.mark.asyncio
async def test_build_runtime_storage_requires_reachable_redis_in_production(
    monkeypatch,
) -> None:
    settings = Settings(app_env="production", redis_host="missing-redis")
    ping = AsyncMock(return_value="Error connecting to Redis")
    monkeypatch.setattr("app.telegram.bot._redis_ping_error", ping)

    with pytest.raises(BotStartupError, match="Redis is not reachable"):
        await build_runtime_storage(settings)

    ping.assert_awaited_once_with(settings.redis_url)


@pytest.mark.asyncio
async def test_build_runtime_storage_uses_redis_when_reachable(monkeypatch) -> None:
    settings = Settings(app_env="development", redis_host="localhost")
    ping = AsyncMock(return_value=None)
    monkeypatch.setattr("app.telegram.bot._redis_ping_error", ping)

    storage = await build_runtime_storage(settings)

    assert isinstance(storage, RedisStorage)
    ping.assert_awaited_once_with(settings.redis_url)
    await storage.close()


@pytest.mark.asyncio
async def test_ensure_polling_available_raises_clear_error_on_conflict() -> None:
    bot = AsyncMock()
    bot.get_updates.side_effect = TelegramConflictError(
        GetUpdates(),
        "Conflict: terminated by other getUpdates request; make sure that only "
        "one bot instance is running",
    )

    with pytest.raises(BotStartupError, match="Another bot instance is already polling"):
        await ensure_polling_available(bot)


@pytest.mark.asyncio
async def test_ensure_polling_available_allows_polling_when_token_is_free() -> None:
    bot = AsyncMock()
    bot.get_updates.return_value = []

    await ensure_polling_available(bot)

    bot.get_updates.assert_awaited_once_with(timeout=0, limit=1, allowed_updates=[])
