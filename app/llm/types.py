"""Typed errors raised by the LLM router."""

from __future__ import annotations


class LLMError(RuntimeError):
    """Base class for every router-level failure."""


class LLMAuthenticationError(LLMError):
    """OpenRouter rejected the key (HTTP 401/403).

    The Telegram settings UI catches this and prompts the user to update
    their OpenRouter key (PRD §7.1).
    """


class LLMRateLimitError(LLMError):
    """OpenRouter returned HTTP 429."""


class LLMUnavailableError(LLMError):
    """All retries exhausted without a usable response."""


class LLMValidationError(LLMError):
    """Heavy-model output failed schema validation (PRD §7.5).

    ``raw_response`` carries the model's text output (when available) so the
    caller can log it or feed it back into a corrective retry.
    """

    def __init__(self, message: str, *, raw_response: str | None = None) -> None:
        super().__init__(message)
        self.raw_response = raw_response
