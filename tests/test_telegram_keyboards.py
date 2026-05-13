"""Phase 2 keyboard surface tests."""

from __future__ import annotations

from app.telegram.keyboards.main_menu import ALL_MAIN_MENU_BUTTONS, main_menu_keyboard
from app.telegram.keyboards.settings import (
    AltRecCB,
    PosCB,
    PositionAdjustCB,
    ValApplyCB,
    ValCB,
    api_keys_keyboard,
    position_adjust_keyboard,
    position_alert_keyboard,
    position_list_keyboard,
    recommendation_keyboard,
    settings_keyboard,
    validation_result_keyboard,
)


def _flatten_labels(markup) -> list[str]:
    return [button.text for row in markup.keyboard for button in row]


def _flatten_inline_labels(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def test_main_menu_keyboard_matches_phase_2_buttons() -> None:
    markup = main_menu_keyboard()
    labels = _flatten_labels(markup)
    assert set(labels) == set(ALL_MAIN_MENU_BUTTONS)
    assert markup.is_persistent is True
    assert markup.keyboard[0][0].text == "🚀 Run Scan Now"
    assert markup.keyboard[0][1].text == "📊 Last Recommendation"


def test_settings_keyboard_exposes_all_editable_fields() -> None:
    labels = _flatten_inline_labels(settings_keyboard())
    assert labels == [
        "💰 Account Size",
        "🎚 Risk Profile",
        "🌎 Timezone",
        "🏦 Broker",
        "📜 Strategy Permission",
        "🔢 Max Contracts",
        "🔔 Alert Mute Duration",
    ]


def test_api_keys_keyboard_shows_remove_buttons_only_when_keys_exist() -> None:
    no_keys = _flatten_inline_labels(api_keys_keyboard(has_alpaca=False, has_alpha_vantage=False))
    with_keys = _flatten_inline_labels(api_keys_keyboard(has_alpaca=True, has_alpha_vantage=True))

    assert "🗑 Remove Alpaca" not in no_keys
    assert "🗑 Remove Alpha Vantage" not in no_keys
    assert "🗑 Remove Alpaca" in with_keys
    assert "🗑 Remove Alpha Vantage" in with_keys


def test_recommendation_keyboard_includes_feedback_buttons() -> None:
    labels = _flatten_inline_labels(recommendation_keyboard("rec-123"))
    assert labels == [
        "🔍 Why this?",
        "⚖️ Risk / Sizing",
        "📈 Alternatives",
        "📘 Save Note",
        "✅ I bought it",
        "❌ I skipped it",
    ]


def test_recommendation_keyboard_hides_alternative_when_requested() -> None:
    labels = _flatten_inline_labels(recommendation_keyboard("rec-123", include_alternative=False))
    assert labels == [
        "🔍 Why this?",
        "⚖️ Risk / Sizing",
        "📘 Save Note",
        "✅ I bought it",
        "❌ I skipped it",
    ]


def test_recommendation_keyboard_uses_dedicated_alternative_cursor() -> None:
    markup = recommendation_keyboard("rec-123", alternative_cursor_id="rec-456")
    alt_button = markup.inline_keyboard[1][0]
    parsed = AltRecCB.unpack(alt_button.callback_data)

    assert alt_button.text == "📈 Alternatives"
    assert parsed.cursor_rec_id == "rec-456"


def test_position_alert_keyboard_includes_close_actions() -> None:
    markup = position_alert_keyboard("pos-123")
    labels = _flatten_inline_labels(markup)
    parsed_sold = PosCB.unpack(markup.inline_keyboard[0][0].callback_data)
    parsed_holding = PosCB.unpack(markup.inline_keyboard[0][1].callback_data)

    assert labels == ["Sold", "Still holding"]
    assert parsed_sold.action == "sold"
    assert parsed_sold.position_id == "pos-123"
    assert parsed_holding.action == "holding"


def test_position_list_keyboard_includes_adjust_close_delete() -> None:
    markup = position_list_keyboard("pos-123")
    labels = _flatten_inline_labels(markup)
    parsed_validate = ValCB.unpack(markup.inline_keyboard[0][0].callback_data)
    parsed_history = ValCB.unpack(markup.inline_keyboard[0][1].callback_data)
    parsed_adjust = PosCB.unpack(markup.inline_keyboard[1][0].callback_data)
    parsed_close = PosCB.unpack(markup.inline_keyboard[2][0].callback_data)
    parsed_delete = PosCB.unpack(markup.inline_keyboard[2][1].callback_data)

    assert labels == ["Validate now", "Validation history", "Adjust", "🔒 Close", "🗑 Delete"]
    assert parsed_validate.action == "validate"
    assert parsed_history.action == "history"
    assert parsed_adjust.action == "adjust"
    assert parsed_close.action == "sold"
    assert parsed_delete.action == "delete"


def test_position_adjust_keyboard_shows_requested_choices() -> None:
    markup = position_adjust_keyboard("pos-123")
    labels = _flatten_inline_labels(markup)
    parsed_target = PositionAdjustCB.unpack(markup.inline_keyboard[0][0].callback_data)
    parsed_stop = PositionAdjustCB.unpack(markup.inline_keyboard[1][0].callback_data)
    parsed_both = PositionAdjustCB.unpack(markup.inline_keyboard[2][0].callback_data)

    assert labels == ["🟢 Target Price", "🛑 Stop Loss", "⚪️ TP and SL"]
    assert parsed_target.action == "target"
    assert parsed_stop.action == "stop"
    assert parsed_both.action == "both"


def test_validation_result_keyboard_uses_short_apply_callback() -> None:
    review = type(
        "Review",
        (),
        {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "proposed_adjustment_json": {
                "target_option_price": "2.5000",
                "stop_loss_option_price": "0.8000",
            },
        },
    )()

    markup = validation_result_keyboard(review)

    assert markup is not None
    button = markup.inline_keyboard[0][0]
    parsed = ValApplyCB.unpack(button.callback_data)
    assert button.text == "Apply TP and SL"
    assert parsed.action == "apply_both"
    assert parsed.validation_id == review.id
    assert len(button.callback_data) < 64
