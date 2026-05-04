"""Phase 2 keyboard surface tests."""

from __future__ import annotations

from app.telegram.keyboards.main_menu import ALL_MAIN_MENU_BUTTONS, main_menu_keyboard
from app.telegram.keyboards.settings import (
    AltRecCB,
    api_keys_keyboard,
    recommendation_keyboard,
    settings_keyboard,
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
    ]


def test_api_keys_keyboard_shows_remove_buttons_only_when_keys_exist() -> None:
    no_keys = _flatten_inline_labels(
        api_keys_keyboard(has_alpaca=False, has_alpha_vantage=False)
    )
    with_keys = _flatten_inline_labels(
        api_keys_keyboard(has_alpaca=True, has_alpha_vantage=True)
    )

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
    labels = _flatten_inline_labels(
        recommendation_keyboard("rec-123", include_alternative=False)
    )
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
