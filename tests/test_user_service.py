"""UserService onboarding + settings tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.services.user_service import (
    TIMEZONE_MAP,
    OnboardingPayload,
    UserService,
)

pytestmark = pytest.mark.asyncio


def _payload(chat_id: str = "tg-onb-1", **overrides) -> OnboardingPayload:
    base = OnboardingPayload(
        telegram_chat_id=chat_id,
        account_size=Decimal("5000.00"),
        risk_profile="Balanced",
        timezone_label="ET",
        broker="Wealthsimple",
        strategy_permission="long_and_short",
        openrouter_api_key="sk-or-real",
        alpaca_api_key="ALP-K",
        alpaca_api_secret="ALP-S",
        alpha_vantage_api_key=None,
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


async def test_create_from_onboarding_persists_and_encrypts(
    db_session: AsyncSession,
) -> None:
    crypto.reset_cache()
    service = UserService(db_session)
    user = await service.create_from_onboarding(_payload())
    await db_session.commit()

    assert user.id is not None
    assert user.timezone_iana == TIMEZONE_MAP["ET"]
    # Ciphertext != plaintext, decrypt roundtrips.
    assert user.openrouter_api_key_encrypted != "sk-or-real"
    assert crypto.decrypt(user.openrouter_api_key_encrypted) == "sk-or-real"
    assert user.alpaca_api_key_encrypted is not None
    assert crypto.decrypt(user.alpaca_api_key_encrypted) == "ALP-K"
    assert user.alpaca_api_secret_encrypted is not None
    assert crypto.decrypt(user.alpaca_api_secret_encrypted) == "ALP-S"
    assert user.alpha_vantage_api_key_encrypted is None


async def test_create_from_onboarding_creates_default_cron(
    db_session: AsyncSession,
) -> None:
    crypto.reset_cache()
    service = UserService(db_session)
    user = await service.create_from_onboarding(_payload(chat_id="tg-onb-cron"))
    await db_session.commit()

    crons = await service.crons.list_for_user(user.id)
    assert len(crons) == 1
    cron = crons[0]
    assert cron.day_of_week == "monday"
    assert cron.local_time == "10:30"
    assert cron.timezone_iana == TIMEZONE_MAP["ET"]
    assert cron.is_active is True


async def test_onboarding_is_idempotent_per_chat_id(db_session: AsyncSession) -> None:
    crypto.reset_cache()
    service = UserService(db_session)
    user_a = await service.create_from_onboarding(_payload(chat_id="tg-idem"))
    await db_session.commit()
    # Re-running with a different account size should update, not duplicate.
    user_b = await service.create_from_onboarding(
        _payload(chat_id="tg-idem", account_size=Decimal("9999.00"))
    )
    await db_session.commit()
    assert user_a.id == user_b.id
    assert user_b.account_size == Decimal("9999.00")
    # And cron not duplicated.
    crons = await service.crons.list_for_user(user_b.id)
    assert len(crons) == 1


async def test_settings_field_updates_roundtrip(db_session: AsyncSession) -> None:
    crypto.reset_cache()
    service = UserService(db_session)
    user = await service.create_from_onboarding(_payload(chat_id="tg-edit"))
    await db_session.commit()

    await service.update_account_size(user, Decimal("12000"))
    await service.update_risk_profile(user, "Aggressive")
    await service.update_timezone(user, "PT")
    await service.update_broker(user, "IBKR")
    await service.update_strategy_permission(user, "long")
    await service.update_max_contracts(user, 5)
    await db_session.commit()

    fetched = await service.get_by_chat_id("tg-edit")
    assert fetched is not None
    assert fetched.account_size == Decimal("12000.00")
    assert fetched.risk_profile == "Aggressive"
    assert fetched.timezone_label == "PT"
    assert fetched.timezone_iana == TIMEZONE_MAP["PT"]
    assert fetched.broker == "IBKR"
    assert fetched.strategy_permission == "long"
    assert fetched.max_contracts == 5

    crons = await service.list_crons_for_user(fetched)
    assert len(crons) == 1
    assert crons[0].timezone_label == "PT"
    assert crons[0].timezone_iana == TIMEZONE_MAP["PT"]


async def test_replace_alpaca_creds_clears_when_none(db_session: AsyncSession) -> None:
    crypto.reset_cache()
    service = UserService(db_session)
    user = await service.create_from_onboarding(_payload(chat_id="tg-clear"))
    await service.replace_alpaca_creds(user, None, None)
    await db_session.commit()

    fetched = await service.get_by_chat_id("tg-clear")
    assert fetched is not None
    assert fetched.alpaca_api_key_encrypted is None
    assert fetched.alpaca_api_secret_encrypted is None


async def test_replace_openrouter_key_changes_ciphertext(
    db_session: AsyncSession,
) -> None:
    crypto.reset_cache()
    service = UserService(db_session)
    user = await service.create_from_onboarding(_payload(chat_id="tg-orkey"))
    original = user.openrouter_api_key_encrypted

    await service.replace_openrouter_key(user, "sk-or-new")
    await db_session.commit()

    fetched = await service.get_by_chat_id("tg-orkey")
    assert fetched is not None
    assert fetched.openrouter_api_key_encrypted != original
    assert crypto.decrypt(fetched.openrouter_api_key_encrypted) == "sk-or-new"
