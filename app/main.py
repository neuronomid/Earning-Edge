from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.dashboard import router as dashboard_router
from app.api.live_market_data import router as live_market_data_router
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(dashboard_router)
app.include_router(live_market_data_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
