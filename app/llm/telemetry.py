"""Per-call telemetry for the LLM router.

OpenRouter's chat-completion responses include a ``usage`` object with token
counts, and recent versions also include ``cost`` (in USD). We record both,
plus duration, and surface them through a ``TelemetrySink`` callback so the
caller (a workflow run, a test, structured logging) can persist them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(slots=True, frozen=True)
class CallTelemetry:
    role: str  # "summarize" or "decide"
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: Decimal | None
    duration_ms: int


class TelemetrySink(Protocol):
    def __call__(self, telemetry: CallTelemetry) -> None: ...


def parse_usage(payload: dict) -> tuple[int, int, int, Decimal | None]:
    """Extract (prompt_tokens, completion_tokens, total_tokens, cost_usd).

    Missing fields default to 0. ``cost`` is optional — OpenRouter only sets
    it when ``usage.include`` is requested.
    """
    usage = payload.get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    cost_raw = usage.get("cost")
    cost: Decimal | None = None
    if cost_raw is not None:
        try:
            cost = Decimal(str(cost_raw))
        except (ValueError, ArithmeticError):
            cost = None
    return prompt, completion, total, cost
