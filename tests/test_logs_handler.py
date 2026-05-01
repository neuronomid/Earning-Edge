from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.user_repo import UserRepository
from app.telegram.handlers import logs as logs_handlers
from tests.telegram_testkit import SendRecorder, make_callback, make_message

pytestmark = pytest.mark.asyncio


@pytest.fixture
def send_recorder(monkeypatch: pytest.MonkeyPatch) -> SendRecorder:
    recorder = SendRecorder()
    monkeypatch.setattr(logs_handlers, "send_text", recorder)
    return recorder


@pytest.fixture
def patch_session_scope(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    @asynccontextmanager
    async def scope():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    monkeypatch.setattr(logs_handlers, "session_scope", scope)


@pytest_asyncio.fixture
async def seeded_runs(db_session: AsyncSession) -> None:
    crypto.reset_cache()
    user = await UserRepository(db_session).add(
        User(
            telegram_chat_id="12345",
            account_size=Decimal("15000.00"),
            risk_profile="Balanced",
            broker="IBKR",
            timezone_label="ET",
            timezone_iana="America/Toronto",
            strategy_permission="long_and_short",
            max_contracts=3,
            openrouter_api_key_encrypted=crypto.encrypt("sk-or-test"),
        )
    )
    base = datetime(2026, 5, 1, 15, 0, tzinfo=UTC)
    for index in range(6):
        started_at = base + timedelta(minutes=index)
        db_session.add(
            WorkflowRun(
                user_id=user.id,
                trigger_type="manual" if index % 2 == 0 else "cron",
                status="success" if index < 5 else "no_trade",
                started_at=started_at,
                finished_at=started_at + timedelta(minutes=1),
                run_summary_json={
                    "started_at": started_at.isoformat(),
                    "finished_at": (started_at + timedelta(minutes=1)).isoformat(),
                    "warning_text": None if index != 4 else "Backup earnings data was used.",
                },
                recommendation_card_json={
                    "selected_ticker": f"T{index}",
                    "selected_strategy": "Long call" if index < 5 else "No trade",
                    "confidence_score": 80 - index,
                    "data_confidence": 90 - index,
                    "decision_reasoning": f"Run {index} reasoning snapshot.",
                },
            )
        )
    await db_session.commit()


async def test_logs_handler_paginates_recent_runs(
    send_recorder: SendRecorder,
    patch_session_scope: None,
    seeded_runs: None,
) -> None:
    await logs_handlers.show_logs(make_message(chat_id=12345))

    first_page = send_recorder.calls[-1]
    assert "📘 <b>Recent Runs</b> (1/2)" in first_page.text
    assert "T5" in first_page.text
    assert "T1" in first_page.text
    assert "T0" not in first_page.text
    assert first_page.kwargs["reply_markup"] is not None

    editable_message = SimpleNamespace(
        chat=SimpleNamespace(id=12345),
        edit_text=AsyncMock(),
    )
    callback = make_callback(chat_id=12345, message=editable_message)

    await logs_handlers.logs_page(callback, logs_handlers.LogsCB(page=1))

    edited_text = editable_message.edit_text.await_args.args[0]
    assert "📘 <b>Recent Runs</b> (2/2)" in edited_text
    assert "T0" in edited_text
    assert "T5" not in edited_text
    callback.answer.assert_awaited()
