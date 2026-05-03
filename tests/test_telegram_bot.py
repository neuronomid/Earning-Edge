from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramConflictError
from aiogram.methods import GetUpdates

from app.core.config import Settings
from app.telegram.bot import BotStartupError, build_bot, ensure_polling_available


def test_build_bot_requires_token() -> None:
    settings = Settings(telegram_bot_token="")

    with pytest.raises(BotStartupError, match="TELEGRAM_BOT_TOKEN is not set"):
        build_bot(settings)


@pytest.mark.asyncio
async def test_ensure_polling_available_raises_clear_error_on_conflict() -> None:
    bot = AsyncMock()
    bot.get_updates.side_effect = TelegramConflictError(
        GetUpdates(),
        "Conflict: terminated by other getUpdates request; make sure that only one bot instance is running",
    )

    with pytest.raises(BotStartupError, match="Another bot instance is already polling"):
        await ensure_polling_available(bot)


@pytest.mark.asyncio
async def test_ensure_polling_available_allows_polling_when_token_is_free() -> None:
    bot = AsyncMock()
    bot.get_updates.return_value = []

    await ensure_polling_available(bot)

    bot.get_updates.assert_awaited_once_with(timeout=0, limit=1, allowed_updates=[])
