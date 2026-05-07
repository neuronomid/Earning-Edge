from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.telegram.handlers import position as position_handlers
from app.telegram.keyboards.settings import PosCB
from tests.telegram_testkit import (
    SendRecorder,
    make_callback,
    make_message,
    make_state,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def send_recorder(monkeypatch: pytest.MonkeyPatch) -> SendRecorder:
    recorder = SendRecorder()
    monkeypatch.setattr(position_handlers, "send_text", recorder)
    return recorder


@pytest.fixture
def patch_session_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def scope():
        yield object()

    monkeypatch.setattr(position_handlers, "session_scope", scope)


def _patch_handler_deps(
    monkeypatch: pytest.MonkeyPatch,
    *,
    user: object | None,
    position: object | None,
    recommendation: object | None = None,
    feedback_events: list[object] | None = None,
) -> None:
    class StubUserService:
        def __init__(self, session) -> None:
            self.session = session

        async def get_by_chat_id(self, telegram_chat_id: str):
            del telegram_chat_id
            return user

    class StubOpenPositionRepository:
        def __init__(self, session) -> None:
            self.session = session

        async def get_active_for_user(self, user_id, position_id):
            del user_id
            return position if position is not None and position.id == position_id else None

    class StubRecommendationRepository:
        def __init__(self, session) -> None:
            self.session = session

        async def get(self, recommendation_id):
            if recommendation is None or recommendation.id != recommendation_id:
                return None
            return recommendation

    class StubFeedbackEventRepository:
        def __init__(self, session) -> None:
            self.session = session

        async def add(self, instance):
            if feedback_events is not None:
                feedback_events.append(instance)
            return instance

    monkeypatch.setattr(position_handlers, "UserService", StubUserService)
    monkeypatch.setattr(position_handlers, "OpenPositionRepository", StubOpenPositionRepository)
    monkeypatch.setattr(
        position_handlers,
        "RecommendationRepository",
        StubRecommendationRepository,
    )
    monkeypatch.setattr(
        position_handlers,
        "FeedbackEventRepository",
        StubFeedbackEventRepository,
    )


async def test_sold_action_starts_close_flow(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_session_scope: None,
) -> None:
    user = SimpleNamespace(id=uuid4())
    position = SimpleNamespace(
        id=uuid4(),
        user_id=user.id,
        recommendation_id=uuid4(),
        status="active",
    )
    _patch_handler_deps(monkeypatch, user=user, position=position)
    callback = make_callback(chat_id=12345, message=make_message(chat_id=12345))
    state, _ = await make_state(chat_id=12345)

    await position_handlers.position_action(
        callback,
        PosCB(action="sold", position_id=str(position.id)),
        state,
    )

    callback.answer.assert_awaited_once_with()
    assert send_recorder.calls[-1].text == "What price did you sell it for per contract?"
    assert await state.get_state() == "ClosePositionStates:close_price"
    assert (await state.get_data())["close_position_id"] == str(position.id)


async def test_holding_action_acknowledges_active_position(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_session_scope: None,
) -> None:
    user = SimpleNamespace(id=uuid4())
    position = SimpleNamespace(
        id=uuid4(),
        user_id=user.id,
        recommendation_id=uuid4(),
        status="active",
    )
    _patch_handler_deps(monkeypatch, user=user, position=position)
    callback = make_callback(chat_id=12345, message=make_message(chat_id=12345))
    state, _ = await make_state(chat_id=12345)

    await position_handlers.position_action(
        callback,
        PosCB(action="holding", position_id=str(position.id)),
        state,
    )

    callback.answer.assert_awaited_once_with("Noted")
    assert send_recorder.calls[-1].text == "Noted. I will keep tracking this position."


async def test_closed_position_alert_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_session_scope: None,
) -> None:
    user = SimpleNamespace(id=uuid4())
    _patch_handler_deps(monkeypatch, user=user, position=None)
    callback = make_callback(chat_id=12345, message=make_message(chat_id=12345))
    state, _ = await make_state(chat_id=12345)

    await position_handlers.position_action(
        callback,
        PosCB(action="sold", position_id=str(uuid4())),
        state,
    )

    callback.answer.assert_awaited_once_with(position_handlers.POSITION_INACTIVE_TEXT)
    assert send_recorder.calls == []
    assert await state.get_state() is None


async def test_capture_close_price_closes_active_position_and_logs_feedback(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_session_scope: None,
) -> None:
    user = SimpleNamespace(id=uuid4(), account_size=Decimal("10000"))
    recommendation = SimpleNamespace(id=uuid4(), position_side="long")
    position = SimpleNamespace(
        id=uuid4(),
        user_id=user.id,
        recommendation_id=recommendation.id,
        entry_price=Decimal("1.25"),
        entry_quantity=2,
        status="active",
        close_price=None,
        close_at=None,
        pnl_applied=False,
    )
    feedback_events: list[object] = []
    _patch_handler_deps(
        monkeypatch,
        user=user,
        position=position,
        recommendation=recommendation,
        feedback_events=feedback_events,
    )
    state, _ = await make_state(chat_id=12345)
    await state.set_state(position_handlers.ClosePositionStates.close_price)
    await state.update_data(close_position_id=str(position.id))

    await position_handlers.capture_close_price(
        make_message("2.10", chat_id=12345),
        state,
    )

    assert position.status == "closed_sold"
    assert position.close_price == Decimal("2.10")
    assert isinstance(position.close_at, datetime)
    assert position.close_at.tzinfo == UTC
    assert len(feedback_events) == 1
    assert feedback_events[0].user_action == "closed"
    assert feedback_events[0].exit_price == Decimal("2.10")
    assert feedback_events[0].pnl == Decimal("170.00")
    assert send_recorder.calls[-1].text == "Position closed. Logged P/L: $170.00."
    assert await state.get_state() is None


async def test_capture_close_price_rejects_stale_closed_position(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_session_scope: None,
) -> None:
    user = SimpleNamespace(id=uuid4())
    feedback_events: list[object] = []
    _patch_handler_deps(
        monkeypatch,
        user=user,
        position=None,
        recommendation=None,
        feedback_events=feedback_events,
    )
    state, _ = await make_state(chat_id=12345)
    await state.set_state(position_handlers.ClosePositionStates.close_price)
    await state.update_data(close_position_id=str(uuid4()))

    await position_handlers.capture_close_price(
        make_message("2.10", chat_id=12345),
        state,
    )

    assert send_recorder.calls[-1].text == position_handlers.POSITION_INACTIVE_TEXT
    assert feedback_events == []
    assert await state.get_state() is None
