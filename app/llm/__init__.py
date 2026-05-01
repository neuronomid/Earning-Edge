"""OpenRouter-backed LLM router (PRD §7).

Exposes only two operations:

- ``LLMRouter.summarize`` — lightweight model (Gemini 3.1 Flash) for browsing,
  news, and message-drafting work (PRD §7.3).
- ``LLMRouter.decide`` — heavy reasoning model (Claude Opus 4.7 Thinking) for
  the final trade decision (PRD §7.2, §7.4).

The router enforces the §7.4 separation rule: ``decide`` may never run against
the lightweight model.
"""

from app.llm.router import LLMRouter
from app.llm.schemas import (
    CandidateBundle,
    ChosenContract,
    DecisionInput,
    StructuredDecision,
)
from app.llm.telemetry import CallTelemetry, TelemetrySink
from app.llm.types import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMUnavailableError,
    LLMValidationError,
)

__all__ = [
    "CallTelemetry",
    "CandidateBundle",
    "ChosenContract",
    "DecisionInput",
    "LLMAuthenticationError",
    "LLMError",
    "LLMRateLimitError",
    "LLMRouter",
    "LLMUnavailableError",
    "LLMValidationError",
    "StructuredDecision",
    "TelemetrySink",
]
