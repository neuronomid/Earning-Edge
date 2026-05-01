from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.scheduler.scheduler import get_scheduler_service
from app.services.run_lock import close_redis_client


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log = get_logger("app")
    settings = get_settings()
    log.info("app.startup", env=settings.app_env)
    scheduler = None
    if settings.app_env != "test":
        scheduler = get_scheduler_service()
        await scheduler.start()
    yield
    if scheduler is not None:
        await scheduler.shutdown()
    await close_redis_client()
    log.info("app.shutdown")


app = FastAPI(title="Earning Edge", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
