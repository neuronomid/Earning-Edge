"""Bot + Dispatcher bootstrap.

Long-polling is the default for development. To enable webhook mode in
production, set TELEGRAM_USE_WEBHOOK=true and provide TELEGRAM_WEBHOOK_URL +
TELEGRAM_WEBHOOK_SECRET; the FastAPI app exposes /telegram/webhook in that case
(wired in a later phase).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramConflictError
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.telegram.handlers import (
    help as help_handlers,
)
from app.telegram.handlers import (
    history as history_handlers,
)
from app.telegram.handlers import (
    menu as menu_handlers,
)
from app.telegram.handlers import (
    onboarding as onboarding_handlers,
)
from app.telegram.handlers import (
    position as position_handlers,
)
from app.telegram.handlers import (
    recommendation as recommendation_handlers,
)
from app.telegram.handlers import (
    schedule as schedule_handlers,
)
from app.telegram.handlers import (
    settings as settings_handlers,
)
from app.telegram.handlers import (
    start as start_handlers,
)


class BotStartupError(RuntimeError):
    """Raised when the bot cannot start cleanly in the current environment."""


def build_storage(settings: Settings) -> BaseStorage:
    """Pick an FSM storage backend.

    Redis is the default outside tests so onboarding state survives restarts.
    The polling entry point uses build_runtime_storage() to verify reachability
    before wiring this into the dispatcher.
    """
    if settings.app_env == "test":
        return MemoryStorage()
    return RedisStorage.from_url(settings.redis_url)


async def build_runtime_storage(
    settings: Settings,
    *,
    logger: logging.Logger | None = None,
) -> BaseStorage:
    """Build FSM storage for a live bot process.

    RedisStorage.from_url() does not connect immediately, so a bad local
    hostname otherwise surfaces later while handling an update.
    """
    if settings.app_env == "test":
        return MemoryStorage()
    redis_error = await _redis_ping_error(settings.redis_url)
    if redis_error is not None:
        if settings.app_env == "production":
            raise BotStartupError(
                "Redis is not reachable for Telegram FSM storage: "
                f"{redis_error}"
            )
        (logger or logging.getLogger(__name__)).warning(
            "telegram_fsm_redis_unavailable; falling back to memory storage: %s",
            redis_error,
        )
        return MemoryStorage()
    try:
        return RedisStorage.from_url(settings.redis_url)
    except Exception:
        return MemoryStorage()


async def _redis_ping_error(redis_url: str) -> str | None:
    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        await client.ping()
    except (OSError, RedisError, ValueError) as exc:
        return str(exc)
    finally:
        await client.aclose()
    return None


def build_bot(settings: Settings | None = None) -> Bot:
    settings = settings or get_settings()
    if not settings.telegram_bot_token:
        raise BotStartupError(
            "TELEGRAM_BOT_TOKEN is not set. Create a bot via @BotFather and add the token to .env."
        )
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher(storage: BaseStorage | None = None) -> Dispatcher:
    """Wire all routers in priority order.

    Order matters: onboarding states must run before the menu router so that a
    user mid-onboarding doesn't accidentally trigger the main-menu reply
    handler.
    """
    settings = get_settings()
    dp = Dispatcher(storage=storage or build_storage(settings))
    dp.include_router(start_handlers.router)
    dp.include_router(onboarding_handlers.router)
    dp.include_router(settings_handlers.router)
    dp.include_router(schedule_handlers.router)
    dp.include_router(position_handlers.router)
    dp.include_router(recommendation_handlers.router)
    dp.include_router(history_handlers.router)
    dp.include_router(menu_handlers.router)
    dp.include_router(help_handlers.router)
    return dp


async def ensure_polling_available(bot: Bot) -> None:
    """Fail fast when another bot instance already owns getUpdates for this token."""
    try:
        await bot.get_updates(timeout=0, limit=1, allowed_updates=[])
    except TelegramConflictError as exc:
        raise BotStartupError(
            "Another bot instance is already polling this TELEGRAM_BOT_TOKEN. "
            "Stop the other poller or use a dedicated local token before running ./dev.sh."
        ) from exc


async def run_polling() -> None:
    configure_logging()
    settings = get_settings()
    bot = build_bot(settings)
    try:
        logger = logging.getLogger(__name__)
        storage = await build_runtime_storage(settings, logger=logger)
        dp = build_dispatcher(storage=storage)
        logger.info("starting telegram bot in long-polling mode")
        await bot.delete_webhook(drop_pending_updates=False)
        await ensure_polling_available(bot)
        await dp.start_polling(bot, **{"workflow_data": _polling_workflow_data()})
    finally:
        await bot.session.close()


def _polling_workflow_data() -> dict[str, Any]:
    return {}


def main() -> None:
    try:
        asyncio.run(run_polling())
    except BotStartupError as exc:
        logging.getLogger(__name__).error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
