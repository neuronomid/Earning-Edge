from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_log_level: str = "INFO"
    app_host: str = "0.0.0.0"  # noqa: S104
    app_port: int = 8000

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "earning_edge"
    postgres_user: str = "earning_edge"
    postgres_password: str = "earning_edge_dev"  # noqa: S105

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0

    app_encryption_key: str = Field(default="")
    workflow_run_lock_ttl_seconds: int = 900

    telegram_bot_token: str = Field(default="")
    telegram_use_webhook: bool = False
    telegram_webhook_url: str = Field(default="")
    telegram_webhook_secret: str = Field(default="")

    market_analysis_model: str = "claude-opus-4.7-thinking"
    lightweight_model: str = "gemini-3.1-flash"
    tradingview_email: str = Field(default="")
    tradingview_password: str = Field(default="")
    tradingview_headless: bool = False
    tradingview_timeout_ms: int = 30000
    tradingview_storage_state_path: str = "var/tradingview/storage-state.json"
    finnhub_api_key: str = Field(default="")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def scheduler_database_url(self) -> str:
        url = make_url(self.database_url)
        if url.drivername == "postgresql+asyncpg":
            return str(url.set(drivername="postgresql+psycopg"))
        if url.drivername == "sqlite+aiosqlite":
            return str(url.set(drivername="sqlite"))
        return str(url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
