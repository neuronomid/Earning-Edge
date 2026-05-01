"""User upsert + settings helpers.

Encrypts API keys at the boundary so the rest of the codebase only ever sees
ciphertext. PRD §8 covers the editable surface; this module owns the
persistence side of every setting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.db.models.cron_job import CronJob
from app.db.models.user import User
from app.db.repositories.cron_repo import CronJobRepository
from app.db.repositories.user_repo import UserRepository

RiskProfile = Literal["Conservative", "Balanced", "Aggressive"]
StrategyPermission = Literal["long", "short", "long_and_short"]
TimezoneLabel = Literal["PT", "MT", "CT", "ET", "AT", "NT"]

# PRD §8.2 mapping. America/Toronto chosen for ET (Montreal default per §8.2).
TIMEZONE_MAP: dict[TimezoneLabel, str] = {
    "PT": "America/Vancouver",
    "MT": "America/Edmonton",
    "CT": "America/Winnipeg",
    "ET": "America/Toronto",
    "AT": "America/Halifax",
    "NT": "America/St_Johns",
}

TIMEZONE_DISPLAY: dict[TimezoneLabel, str] = {
    "PT": "Pacific (PT)",
    "MT": "Mountain (MT)",
    "CT": "Central (CT)",
    "ET": "Eastern (ET)",
    "AT": "Atlantic (AT)",
    "NT": "Newfoundland (NT)",
}

# PRD §8.3 defaults
DEFAULT_RISK_PROFILE: RiskProfile = "Balanced"
DEFAULT_STRATEGY_PERMISSION: StrategyPermission = "long_and_short"
DEFAULT_MAX_CONTRACTS = 3
DEFAULT_TIMEZONE_LABEL: TimezoneLabel = "ET"
DEFAULT_BROKER = "Other"

# PRD §12.1 default cron
DEFAULT_CRON_DAY = "monday"
DEFAULT_CRON_TIME = time(10, 30)


@dataclass(slots=True)
class OnboardingPayload:
    telegram_chat_id: str
    account_size: Decimal
    risk_profile: RiskProfile
    timezone_label: TimezoneLabel
    broker: str
    strategy_permission: StrategyPermission
    openrouter_api_key: str
    alpaca_api_key: str | None = None
    alpaca_api_secret: str | None = None
    alpha_vantage_api_key: str | None = None
    max_contracts: int = DEFAULT_MAX_CONTRACTS


class UserService:
    """Owns all user/cron persistence used by the Telegram layer."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.crons = CronJobRepository(session)

    # ---------- queries ----------

    async def get_by_chat_id(self, telegram_chat_id: str) -> User | None:
        return await self.users.get_by_telegram_chat_id(telegram_chat_id)

    # ---------- onboarding ----------

    async def create_from_onboarding(self, payload: OnboardingPayload) -> User:
        """Create a fully-configured user + the default Monday 10:30 cron job.

        Idempotent on `telegram_chat_id`: re-running onboarding for an existing
        chat updates the user record in-place rather than failing on the unique
        constraint.
        """
        existing = await self.users.get_by_telegram_chat_id(payload.telegram_chat_id)
        if existing is not None:
            return await self._apply_onboarding_to(existing, payload)

        user = User(
            telegram_chat_id=payload.telegram_chat_id,
            account_size=payload.account_size,
            risk_profile=payload.risk_profile,
            broker=payload.broker,
            timezone_label=payload.timezone_label,
            timezone_iana=TIMEZONE_MAP[payload.timezone_label],
            strategy_permission=payload.strategy_permission,
            max_contracts=payload.max_contracts,
            openrouter_api_key_encrypted=crypto.encrypt(payload.openrouter_api_key),
            alpaca_api_key_encrypted=_encrypt_optional(payload.alpaca_api_key),
            alpaca_api_secret_encrypted=_encrypt_optional(payload.alpaca_api_secret),
            alpha_vantage_api_key_encrypted=_encrypt_optional(payload.alpha_vantage_api_key),
            is_active=True,
        )
        await self.users.add(user)
        await self._ensure_default_cron(user)
        return user

    async def _apply_onboarding_to(self, user: User, payload: OnboardingPayload) -> User:
        user.account_size = payload.account_size
        user.risk_profile = payload.risk_profile
        user.broker = payload.broker
        user.timezone_label = payload.timezone_label
        user.timezone_iana = TIMEZONE_MAP[payload.timezone_label]
        user.strategy_permission = payload.strategy_permission
        user.max_contracts = payload.max_contracts
        user.openrouter_api_key_encrypted = crypto.encrypt(payload.openrouter_api_key)
        user.alpaca_api_key_encrypted = _encrypt_optional(payload.alpaca_api_key)
        user.alpaca_api_secret_encrypted = _encrypt_optional(payload.alpaca_api_secret)
        user.alpha_vantage_api_key_encrypted = _encrypt_optional(payload.alpha_vantage_api_key)
        user.is_active = True
        await self.session.flush()
        await self._ensure_default_cron(user)
        return user

    async def _ensure_default_cron(self, user: User) -> None:
        existing = await self.crons.list_for_user(user.id)
        if existing:
            return
        cron = CronJob(
            user_id=user.id,
            day_of_week=DEFAULT_CRON_DAY,
            local_time=DEFAULT_CRON_TIME.strftime("%H:%M"),
            timezone_label=user.timezone_label,
            timezone_iana=user.timezone_iana,
            is_active=True,
        )
        await self.crons.add(cron)

    # ---------- per-field updates (Settings UI) ----------

    async def update_account_size(self, user: User, account_size: Decimal) -> None:
        user.account_size = account_size
        await self.session.flush()

    async def update_risk_profile(self, user: User, risk_profile: RiskProfile) -> None:
        user.risk_profile = risk_profile
        await self.session.flush()

    async def update_timezone(self, user: User, label: TimezoneLabel) -> None:
        user.timezone_label = label
        user.timezone_iana = TIMEZONE_MAP[label]
        await self.session.flush()

    async def update_broker(self, user: User, broker: str) -> None:
        user.broker = broker
        await self.session.flush()

    async def update_strategy_permission(
        self, user: User, permission: StrategyPermission
    ) -> None:
        user.strategy_permission = permission
        await self.session.flush()

    async def update_max_contracts(self, user: User, n: int) -> None:
        user.max_contracts = n
        await self.session.flush()

    # ---------- API-key edits (Settings UI) ----------

    async def replace_openrouter_key(self, user: User, api_key: str) -> None:
        user.openrouter_api_key_encrypted = crypto.encrypt(api_key)
        await self.session.flush()

    async def replace_alpaca_creds(
        self, user: User, api_key: str | None, api_secret: str | None
    ) -> None:
        user.alpaca_api_key_encrypted = _encrypt_optional(api_key)
        user.alpaca_api_secret_encrypted = _encrypt_optional(api_secret)
        await self.session.flush()

    async def replace_alpha_vantage_key(self, user: User, api_key: str | None) -> None:
        user.alpha_vantage_api_key_encrypted = _encrypt_optional(api_key)
        await self.session.flush()


def _encrypt_optional(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return crypto.encrypt(value)


def decrypt_or_none(ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    return crypto.decrypt(ciphertext)
