"""Tone linter tests (PRD §10.6)."""

from __future__ import annotations

import pytest

from app.telegram.tone import ToneError, assert_clean, lint, scan


@pytest.mark.parametrize(
    "text",
    [
        "This is a guaranteed winner.",
        "It's basically risk-free, you can't lose.",
        "Recommendation generated. Execute according to parameters.",
        "Surefire setup, easy money.",
    ],
)
def test_scan_flags_forbidden_phrases(text: str) -> None:
    issues = scan(text)
    assert issues, f"expected tone issues for {text!r}"


def test_scan_passes_friendly_message() -> None:
    text = (
        "📊 Weekly scan is ready.\n"
        "I found one setup that looks stronger than the rest. "
        "It is still an earnings trade, so review carefully before entry."
    )
    assert scan(text) == []


def test_assert_clean_raises_on_hype() -> None:
    with pytest.raises(ToneError):
        assert_clean("This is a guaranteed winner.")


def test_lint_returns_tuple() -> None:
    ok, issues = lint("Hello there.")
    assert ok is True
    assert list(issues) == []


def test_emoji_overuse_flagged() -> None:
    msg = "🚀" * 12
    issues = scan(msg)
    assert any(i.kind == "emoji_overuse" for i in issues)


@pytest.mark.xfail(
    reason=(
        "Phase 2 spec calls for flagging overly plain long messages, "
        "but the linter does not implement that rule yet."
    ),
    strict=False,
)
def test_long_plain_message_is_flagged_for_missing_friendly_framing() -> None:
    text = (
        "Weekly scan is ready. I found one setup that looks stronger than the rest. "
        "It is still an earnings trade, so review carefully before entry and confirm "
        "the contract details in your broker before acting."
    )
    issues = scan(text)
    assert any(issue.kind == "plain_long_message" for issue in issues)
