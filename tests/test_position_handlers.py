from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.telegram.handlers import position as position_handlers
from app.telegram.keyboards.settings import PosCB, PositionAdjustCB
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
    deleted_positions: list[object] | None = None,
    overrides: list[object] | None = None,
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

        async def get_for_user_with_recommendation(self, user_id, position_id):
            del user_id
            if position is not None and recommendation is not None and position.id == position_id:
                return position, recommendation
            return None

        async def delete(self, instance):
            if deleted_positions is not None:
                deleted_positions.append(instance)

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

        async def delete_for_recommendation_user(self, recommendation_id, user_id):
            del recommendation_id, user_id

    class StubPositionPlanOverrideRepository:
        def __init__(self, session) -> None:
            self.session = session

        async def latest_for_position(self, position_id):
            if overrides is None:
                return None
            for override in reversed(overrides):
                if override.open_position_id == position_id:
                    return override
            return None

        async def add(self, instance):
            if overrides is not None:
                overrides.append(instance)
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
    monkeypatch.setattr(
        position_handlers,
        "PositionPlanOverrideRepository",
        StubPositionPlanOverrideRepository,
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


async def test_adjust_action_shows_adjust_choices(
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
        PosCB(action="adjust", position_id=str(position.id)),
        state,
    )

    callback.answer.assert_awaited_once_with()
    labels = [
        button.text
        for row in send_recorder.calls[-1].kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert labels == ["🟢 Target Price", "🛑 Stop Loss", "⚪️ TP and SL", "↩ Back"]


async def test_adjust_cancel_returns_to_position_actions(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_session_scope: None,
) -> None:
    user = SimpleNamespace(id=uuid4())
    recommendation = SimpleNamespace(
        id=uuid4(),
        target_option_price=Decimal("2.00"),
        stop_loss_option_price=Decimal("0.50"),
        underlying_stop_price=None,
    )
    position = SimpleNamespace(
        id=uuid4(),
        user_id=user.id,
        recommendation_id=recommendation.id,
        status="active",
    )
    _patch_handler_deps(monkeypatch, user=user, position=position, recommendation=recommendation)
    callback = make_callback(chat_id=12345, message=make_message(chat_id=12345))
    state, _ = await make_state(chat_id=12345)
    await state.set_state(position_handlers.AdjustPositionStates.target_price)

    await position_handlers.position_adjust_choice(
        callback,
        PositionAdjustCB(action="cancel", position_id=str(position.id)),
        state,
    )

    callback.answer.assert_awaited_once_with("Cancelled")
    assert send_recorder.calls[-1].text == "No changes made."
    labels = [
        button.text
        for row in send_recorder.calls[-1].kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "Adjust" in labels
    assert await state.get_state() is None


async def test_delete_action_requires_confirmation(
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
    deleted_positions: list[object] = []
    _patch_handler_deps(
        monkeypatch,
        user=user,
        position=position,
        deleted_positions=deleted_positions,
    )
    callback = make_callback(chat_id=12345, message=make_message(chat_id=12345))
    state, _ = await make_state(chat_id=12345)

    await position_handlers.position_action(
        callback,
        PosCB(action="delete", position_id=str(position.id)),
        state,
    )

    callback.answer.assert_awaited_once_with()
    assert "Delete this active position?" in send_recorder.calls[-1].text
    labels = [
        button.text
        for row in send_recorder.calls[-1].kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert labels == ["✅ Delete position", "✖️ Cancel"]
    assert deleted_positions == []


async def test_delete_cancel_returns_to_position_actions(
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
    deleted_positions: list[object] = []
    _patch_handler_deps(
        monkeypatch,
        user=user,
        position=position,
        deleted_positions=deleted_positions,
    )
    callback = make_callback(chat_id=12345, message=make_message(chat_id=12345))
    state, _ = await make_state(chat_id=12345)

    await position_handlers.position_action(
        callback,
        PosCB(action="delete_cancel", position_id=str(position.id)),
        state,
    )

    callback.answer.assert_awaited_once_with("Cancelled")
    assert send_recorder.calls[-1].text == "Delete cancelled."
    assert deleted_positions == []


async def test_delete_confirm_removes_active_position(
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
    deleted_positions: list[object] = []
    _patch_handler_deps(
        monkeypatch,
        user=user,
        position=position,
        deleted_positions=deleted_positions,
    )
    callback = make_callback(chat_id=12345, message=make_message(chat_id=12345))
    state, _ = await make_state(chat_id=12345)

    await position_handlers.position_action(
        callback,
        PosCB(action="delete_confirm", position_id=str(position.id)),
        state,
    )

    callback.answer.assert_awaited_once_with("Deleted")
    assert send_recorder.calls[-1].text == (
        "Position deleted. It will not count toward P/L or account size."
    )
    assert deleted_positions == [position]


async def test_adjust_target_choice_starts_target_state(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_session_scope: None,
) -> None:
    user = SimpleNamespace(id=uuid4())
    recommendation = SimpleNamespace(
        id=uuid4(),
        target_option_price=Decimal("2.00"),
        stop_loss_option_price=Decimal("0.50"),
        underlying_stop_price=None,
    )
    position = SimpleNamespace(
        id=uuid4(),
        user_id=user.id,
        recommendation_id=recommendation.id,
        status="active",
    )
    overrides: list[object] = []
    _patch_handler_deps(
        monkeypatch,
        user=user,
        position=position,
        recommendation=recommendation,
        overrides=overrides,
    )
    callback = make_callback(chat_id=12345, message=make_message(chat_id=12345))
    state, _ = await make_state(chat_id=12345)

    await position_handlers.position_adjust_choice(
        callback,
        PositionAdjustCB(action="target", position_id=str(position.id)),
        state,
    )

    callback.answer.assert_awaited_once_with()
    assert await state.get_state() == "AdjustPositionStates:target_price"
    assert (await state.get_data())["adjust_position_id"] == str(position.id)
    assert "Current: $2.00" in send_recorder.calls[-1].text


async def test_adjust_target_saves_full_override_and_resets_target_alert(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_session_scope: None,
) -> None:
    user = SimpleNamespace(id=uuid4())
    recommendation = SimpleNamespace(
        id=uuid4(),
        target_option_price=Decimal("2.00"),
        stop_loss_option_price=Decimal("0.50"),
        underlying_stop_price=Decimal("95.00"),
    )
    position = SimpleNamespace(
        id=uuid4(),
        user_id=user.id,
        recommendation_id=recommendation.id,
        status="active",
        target_dismissed=True,
        target_muted_until=datetime.now(UTC),
        target_alert_count=3,
        stop_dismissed=True,
        stop_muted_until=datetime.now(UTC),
        stop_alert_count=4,
    )
    overrides: list[object] = []
    _patch_handler_deps(
        monkeypatch,
        user=user,
        position=position,
        recommendation=recommendation,
        overrides=overrides,
    )
    state, _ = await make_state(chat_id=12345)
    await state.set_state(position_handlers.AdjustPositionStates.target_price)
    await state.update_data(adjust_position_id=str(position.id))

    await position_handlers.capture_adjust_target(
        make_message("2.50", chat_id=12345),
        state,
    )

    assert len(overrides) == 1
    assert overrides[0].open_position_id == position.id
    assert overrides[0].target_option_price == Decimal("2.50")
    assert overrides[0].stop_loss_option_price == Decimal("0.50")
    assert overrides[0].underlying_stop_price == Decimal("95.00")
    assert position.target_dismissed is False
    assert position.target_muted_until is None
    assert position.target_alert_count == 0
    assert position.stop_dismissed is True
    assert position.stop_alert_count == 4
    assert send_recorder.calls[-1].text == "Adjusted. Target: $2.50 · Stop: $0.50."
    assert await state.get_state() is None


async def test_adjust_both_saves_target_and_stop(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_session_scope: None,
) -> None:
    user = SimpleNamespace(id=uuid4())
    recommendation = SimpleNamespace(
        id=uuid4(),
        target_option_price=Decimal("2.00"),
        stop_loss_option_price=Decimal("0.50"),
        underlying_stop_price=None,
    )
    position = SimpleNamespace(
        id=uuid4(),
        user_id=user.id,
        recommendation_id=recommendation.id,
        status="active",
        target_dismissed=True,
        target_muted_until=datetime.now(UTC),
        target_alert_count=3,
        stop_dismissed=True,
        stop_muted_until=datetime.now(UTC),
        stop_alert_count=4,
    )
    overrides: list[object] = []
    _patch_handler_deps(
        monkeypatch,
        user=user,
        position=position,
        recommendation=recommendation,
        overrides=overrides,
    )
    state, _ = await make_state(chat_id=12345)
    await state.set_state(position_handlers.AdjustPositionStates.both_target_price)
    await state.update_data(adjust_position_id=str(position.id))

    await position_handlers.capture_adjust_both_target(
        make_message("2.40", chat_id=12345),
        state,
    )
    await position_handlers.capture_adjust_both_stop(
        make_message("0.70", chat_id=12345),
        state,
    )

    assert overrides[0].target_option_price == Decimal("2.40")
    assert overrides[0].stop_loss_option_price == Decimal("0.70")
    assert position.target_dismissed is False
    assert position.stop_dismissed is False
    assert position.target_alert_count == 0
    assert position.stop_alert_count == 0
    assert await state.get_state() is None


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
