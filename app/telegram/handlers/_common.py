"""Shared helpers for handlers.

`send_text` runs every outgoing string through the tone linter — it logs (does
not raise) when issues are found in production but raises in tests so the bug
surfaces immediately.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram.types import Message

from app.core.config import get_settings
from app.telegram.tone import ToneError, assert_clean, lint

_logger = logging.getLogger(__name__)


async def send_text(message: Message, text: str, **kwargs: Any) -> Message:
    enforce_tone(text)
    return await message.answer(text, **kwargs)


def enforce_tone(text: str) -> None:
    if get_settings().app_env == "test":
        # Tests should fail loudly when forbidden phrases sneak in.
        assert_clean(text)
        return
    ok, issues = lint(text)
    if not ok:
        _logger.warning("tone-issue detected: %s | text=%r", list(issues), text)


__all__ = ["send_text", "ToneError", "enforce_tone"]
