"""User upsert + settings helpers.

Encrypts API keys at the boundary so the rest of the codebase only ever sees
ciphertext. PRD §8 covers the editable surface; this module owns the
persistence side of every setting.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.db.models.cron_job import CronJob
from app.db.models.user import User
from app.db.repositories.cron_repo import CronJobRepository
from app.db.repositories.user_repo import UserRepository
from app.scoring.types import validate_custom_risk_percent

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
DEFAULT_DASHBOARD_ACCOUNT_SIZE = Decimal("150000")
DEFAULT_DASHBOARD_BROKER = "IBKR Paper"

# PRD §12.1 default cron
DEFAULT_CRON_DAY = "monday"
DEFAULT_CRON_TIME = time(10, 30)
PASSWORD_SCHEME = "pbkdf2_sha256"  # noqa: S105 - scheme name, not a secret.
PASSWORD_ITERATIONS = 260_000


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

    async def get_by_dashboard_username(self, username: str) -> User | None:
        return await self.users.get_by_dashboard_username(normalize_dashboard_username(username))

    # ---------- dashboard auth ----------

    async def create_dashboard_user(self, username: str, password: str) -> User:
        normalized_username = normalize_dashboard_username(username)
        if len(normalized_username) < 2:
            raise ValueError("Username must be at least 2 characters.")
        existing = await self.users.get_by_dashboard_username(normalized_username)
        if existing is not None:
            raise ValueError("That username is already registered.")

        user = User(
            telegram_chat_id=f"dashboard:{normalized_username}",
            dashboard_username=normalized_username,
            dashboard_password_hash=hash_dashboard_password(password),
            account_size=DEFAULT_DASHBOARD_ACCOUNT_SIZE,
            risk_profile=DEFAULT_RISK_PROFILE,
            broker=DEFAULT_DASHBOARD_BROKER,
            timezone_label=DEFAULT_TIMEZONE_LABEL,
            timezone_iana=TIMEZONE_MAP[DEFAULT_TIMEZONE_LABEL],
            strategy_permission=DEFAULT_STRATEGY_PERMISSION,
            max_contracts=DEFAULT_MAX_CONTRACTS,
            openrouter_api_key_encrypted=crypto.encrypt(""),
            alpaca_api_key_encrypted=None,
            alpaca_api_secret_encrypted=None,
            alpha_vantage_api_key_encrypted=None,
            is_active=True,
        )
        await self.users.add(user)
        await self._ensure_default_cron(user)
        return user

    async def authenticate_dashboard_user(self, username: str, password: str) -> User | None:
        normalized_username = normalize_dashboard_username(username)
        if len(normalized_username) < 2:
            return None
        user = await self.users.get_by_dashboard_username(normalized_username)
        if user is None or not user.is_active or not user.dashboard_password_hash:
            return None
        if not verify_dashboard_password(password, user.dashboard_password_hash):
            return None
        return user

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

    async def update_custom_risk_percent(
        self, user: User, custom_risk_percent: Decimal | None
    ) -> None:
        user.custom_risk_percent = validate_custom_risk_percent(custom_risk_percent)
        await self.session.flush()

    async def update_timezone(self, user: User, label: TimezoneLabel) -> None:
        user.timezone_label = label
        user.timezone_iana = TIMEZONE_MAP[label]
        crons = await self.crons.list_for_user(user.id)
        for cron in crons:
            cron.timezone_label = label
            cron.timezone_iana = TIMEZONE_MAP[label]
        await self.session.flush()

    async def update_broker(self, user: User, broker: str) -> None:
        user.broker = broker
        await self.session.flush()

    async def update_strategy_permission(self, user: User, permission: StrategyPermission) -> None:
        user.strategy_permission = permission
        await self.session.flush()

    async def update_max_contracts(self, user: User, n: int) -> None:
        user.max_contracts = n
        await self.session.flush()

    async def update_alert_mute_duration(self, user: User, duration: str) -> None:
        user.alert_mute_duration = duration
        await self.session.flush()

    # ---------- API-key edits (Settings UI) ----------

    async def replace_openrouter_key(self, user: User, api_key: str | None) -> None:
        user.openrouter_api_key_encrypted = crypto.encrypt(api_key or "")
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

    # ---------- cron management (Phase 3) ----------

    async def list_crons_for_user(self, user: User) -> list[CronJob]:
        return await self.crons.list_for_user(user.id)

    async def get_cron_for_user(self, user: User, cron_id: UUID) -> CronJob | None:
        return await self.crons.get_for_user(user.id, cron_id)

    async def add_cron_for_user(self, user: User, *, day_of_week: str, local_time: str) -> CronJob:
        cron = CronJob(
            user_id=user.id,
            day_of_week=day_of_week,
            local_time=local_time,
            timezone_label=user.timezone_label,
            timezone_iana=user.timezone_iana,
            is_active=True,
        )
        await self.crons.add(cron)
        return cron

    async def update_cron(self, cron: CronJob, *, day_of_week: str, local_time: str) -> CronJob:
        cron.day_of_week = day_of_week
        cron.local_time = local_time
        await self.session.flush()
        return cron

    async def delete_cron(self, cron: CronJob) -> None:
        await self.crons.delete(cron)

    async def pause_all_crons(self, user: User) -> int:
        crons = await self.crons.list_for_user(user.id)
        changed = 0
        for cron in crons:
            if cron.is_active:
                cron.is_active = False
                changed += 1
        await self.session.flush()
        return changed

    async def resume_all_crons(self, user: User) -> int:
        crons = await self.crons.list_for_user(user.id)
        changed = 0
        for cron in crons:
            if not cron.is_active:
                cron.is_active = True
                changed += 1
        await self.session.flush()
        return changed


def _encrypt_optional(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return crypto.encrypt(value)


def decrypt_or_none(ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    return crypto.decrypt(ciphertext)


def normalize_dashboard_username(username: str) -> str:
    return username.strip().lower()


def hash_dashboard_password(password: str) -> str:
    salt = secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    )
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${salt}${encoded_digest}"


def verify_dashboard_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, raw_iterations, salt, encoded_digest = stored_hash.split("$", 3)
        iterations = int(raw_iterations)
    except ValueError:
        return False

    if scheme != PASSWORD_SCHEME:
        return False

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    expected = base64.urlsafe_b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, encoded_digest)
