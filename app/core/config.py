from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    app_encryption_key: str = Field(default="")

    telegram_bot_token: str = Field(default="")

    market_analysis_model: str = "claude-opus-4.7-thinking"
    lightweight_model: str = "gemini-3.1-flash"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
