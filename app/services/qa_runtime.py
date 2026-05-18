from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models.user import User
from app.pipeline.orchestrator import UserSecrets
from app.services.market_hours import NEW_YORK_TZ, trading_reference_date
from app.services.user_service import (
    OnboardingPayload,
    RiskProfile,
    StrategyPermission,
    TimezoneLabel,
    UserService,
)

_PLACEHOLDER_SECRET = "qa-runtime-placeholder"


@dataclass(slots=True, frozen=True)
class QARuntimeConfig:
    root_dir: Path
    user_chat_id: str
    account_size: Decimal
    risk_profile: str
    timezone_label: str
    timezone_iana: str
    broker: str
    strategy_permission: str
    max_contracts: int


@dataclass(slots=True, frozen=True)
class QARuntimeSecrets:
    openrouter_api_key: str
    alpha_vantage_api_key: str
    alpaca_api_key: str
    alpaca_api_secret: str

    def as_user_secrets(self) -> UserSecrets:
        return UserSecrets(
            openrouter_api_key=self.openrouter_api_key,
            alpha_vantage_api_key=self.alpha_vantage_api_key or None,
            alpaca_api_key=self.alpaca_api_key or None,
            alpaca_api_secret=self.alpaca_api_secret or None,
        )


class NoopNotifier:
    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        reply_markup: object | None = None,
    ) -> str | None:
        del chat_id, text, reply_markup
        return None


def get_qa_runtime_config(settings: Settings | None = None) -> QARuntimeConfig:
    resolved = settings or get_settings()
    return QARuntimeConfig(
        root_dir=Path(resolved.qa_root_dir),
        user_chat_id=resolved.qa_user_chat_id.strip() or "qa_intraday",
        account_size=resolved.qa_account_size,
        risk_profile=resolved.qa_risk_profile,
        timezone_label=resolved.qa_timezone_label.strip() or "ET",
        timezone_iana=resolved.qa_timezone_iana.strip() or "America/Toronto",
        broker=resolved.qa_broker.strip() or "Wealthsimple",
        strategy_permission=resolved.qa_strategy_permission,
        max_contracts=resolved.qa_max_contracts,
    )


def get_qa_runtime_secrets(
    settings: Settings | None = None,
    *,
    require_all: bool,
) -> QARuntimeSecrets:
    resolved = settings or get_settings()
    secrets = QARuntimeSecrets(
        openrouter_api_key=resolved.qa_openrouter_api_key.strip(),
        alpha_vantage_api_key=resolved.qa_alpha_vantage_api_key.strip(),
        alpaca_api_key=resolved.qa_alpaca_api_key.strip(),
        alpaca_api_secret=resolved.qa_alpaca_api_secret.strip(),
    )
    if require_all:
        missing = []
        if not secrets.openrouter_api_key:
            missing.append("QA_OPENROUTER_API_KEY")
        if not secrets.alpha_vantage_api_key:
            missing.append("QA_ALPHA_VANTAGE_API_KEY")
        if not secrets.alpaca_api_key:
            missing.append("QA_ALPACA_API_KEY")
        if not secrets.alpaca_api_secret:
            missing.append("QA_ALPACA_API_SECRET")
        if missing:
            raise ValueError(
                "Missing QA credentials in .env: " + ", ".join(missing)
            )
    return secrets


async def ensure_qa_user(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
) -> User:
    resolved = settings or get_settings()
    runtime = get_qa_runtime_config(resolved)
    service = UserService(session)
    payload = OnboardingPayload(
        telegram_chat_id=runtime.user_chat_id,
        account_size=runtime.account_size,
        risk_profile=cast(RiskProfile, runtime.risk_profile),
        timezone_label=cast(TimezoneLabel, runtime.timezone_label),
        broker=runtime.broker,
        strategy_permission=cast(StrategyPermission, runtime.strategy_permission),
        openrouter_api_key=_PLACEHOLDER_SECRET,
        max_contracts=runtime.max_contracts,
    )
    user = await service.create_from_onboarding(payload)
    user.timezone_iana = runtime.timezone_iana
    await service.pause_all_crons(user)
    await session.flush()
    return user


def qa_reference_datetime(value: datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def qa_reference_trading_date(reference_dt: datetime) -> datetime.date:
    return trading_reference_date(reference_dt)


def qa_day_dir(
    *,
    settings: Settings | None = None,
    reference_dt: datetime,
) -> Path:
    runtime = get_qa_runtime_config(settings)
    return runtime.root_dir / reference_dt.astimezone(NEW_YORK_TZ).date().isoformat()
