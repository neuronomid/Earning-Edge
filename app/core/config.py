from decimal import Decimal
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
    position_validation_lock_ttl_seconds: int = 300
    position_validation_auto_cooldown_minutes: int = 30
    position_validation_auto_daily_cap: int = 20
    position_validation_shadow_mode: bool = True
    position_validation_monitor_enabled: bool = True

    telegram_bot_token: str = Field(default="")
    telegram_use_webhook: bool = False
    telegram_webhook_url: str = Field(default="")
    telegram_webhook_secret: str = Field(default="")

    market_analysis_model: str = "anthropic/claude-opus-4.7"
    lightweight_model: str = "google/gemini-3.1-pro-preview"
    market_analysis_reasoning_effort: Literal["off", "low", "medium", "high"] = "medium"
    finviz_headless: bool = True
    finviz_timeout_ms: int = 30000
    finviz_query_cache_ttl_seconds: int = 600
    finnhub_api_key: str = Field(default="")
    alpha_vantage_api_key: str = Field(default="")
    finnhub_news_lookback_days: int = 120
    sec_edgar_user_agent: str = "Earning-Edge/1.0 (contact: ops@example.com)"
    scoring_fairness_v2: bool = True
    pead_min_surprise_pct: Decimal = Decimal("0.05")
    pead_min_day1_reaction: Decimal = Decimal("0.03")
    pead_min_market_cap_usd: Decimal = Decimal("300000000")
    pead_max_market_cap_usd: Decimal = Decimal("10000000000")
    sector_rs_min_4w_return: Decimal = Decimal("0.02")
    sector_rs_sma_window: int = 50

    activist_13d_min_price_usd: Decimal = Decimal("15")
    activist_13d_min_avg_vol: int = 750_000
    activist_13d_min_market_cap_usd: Decimal = Decimal("500000000")
    activist_13d_lookback_tier1_days: int = 5
    activist_13d_lookback_tier2_days: int = 10
    activist_13d_lookback_tier3_days: int = 20
    activist_13d_user_agent: str = "EarningEdge research@earningedge.local"
    activist_13d_filing_cache_ttl_seconds: int = 86400
    activist_13d_throttle_rps: int = 8

    news_brief_schema_version: str = "v4"
    news_prompt_version: str = "v3"

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
            url = url.set(drivername="postgresql+psycopg")
        elif url.drivername == "sqlite+aiosqlite":
            url = url.set(drivername="sqlite")
        return url.render_as_string(hide_password=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
