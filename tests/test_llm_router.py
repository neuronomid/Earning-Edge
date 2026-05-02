"""LLM router tests (Phase 7 / PRD §7).

Covers:

- summarize() success path on the lightweight model (PRD §7.3)
- decide() success path with pydantic schema validation (PRD §7.5)
- malformed JSON / schema-mismatch → LLMValidationError
- 401/403 → LLMAuthenticationError (typed exception for §7.1 retry UX)
- empty key → LLMAuthenticationError before any HTTP call
- §7.4 separation: decide() against the lightweight model raises ValueError
- 5xx retry then bubble as LLMUnavailableError
- 429 final → LLMRateLimitError
- token/cost telemetry surfaces through the sink
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.llm import (
    CallTelemetry,
    CandidateBundle,
    DecisionInput,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMRouter,
    LLMUnavailableError,
    LLMValidationError,
    StructuredDecision,
)

pytestmark = pytest.mark.asyncio

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
HEAVY = "anthropic/claude-opus-4.7-thinking"
LIGHT = "google/gemini-3.1-flash"


def _settings(*, heavy: str = HEAVY, light: str = LIGHT) -> Settings:
    return Settings(
        market_analysis_model=heavy,
        lightweight_model=light,
        app_encryption_key="x" * 44,
    )


def _router(
    *,
    heavy: str = HEAVY,
    light: str = LIGHT,
    max_attempts: int = 3,
    sink: list[CallTelemetry] | None = None,
) -> LLMRouter:
    captured: list[CallTelemetry] = sink if sink is not None else []
    return LLMRouter(
        settings=_settings(heavy=heavy, light=light),
        max_attempts=max_attempts,
        telemetry_sink=captured.append,
    )


def _completion(
    *,
    content: str,
    model: str,
    prompt_tokens: int = 12,
    completion_tokens: int = 7,
    cost: float | None = 0.000123,
) -> dict[str, Any]:
    usage: dict[str, Any] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    if cost is not None:
        usage["cost"] = cost
    return {
        "id": "gen-test",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "usage": usage,
    }


def _decision_input() -> DecisionInput:
    return DecisionInput(
        user_strategy_permission="long_and_short",
        risk_profile="Balanced",
        account_size=Decimal("5000"),
        candidates=[
            CandidateBundle(
                ticker="AMD",
                company_name="Advanced Micro Devices",
                earnings_date=date(2026, 5, 6),
                earnings_timing="AMC",
                market_cap=Decimal("250000000000"),
                current_price=Decimal("180.50"),
                recent_returns={"1d": 0.5, "5d": 2.1, "20d": 4.3},
                trend_indicators={"rsi": 58.0},
                sector_comparison={"vs_sector_20d": 1.2},
                market_comparison={"vs_spy_20d": 0.8},
                news_summary="Bullish AI demand commentary; one bearish broker note.",
                option_chain_candidates=[],
                expected_move=Decimal("8.50"),
                previous_earnings_move=Decimal("6.25"),
                data_confidence_score=82,
            )
        ],
    )


# ---------- summarize ----------


@respx.mock
async def test_summarize_returns_text_and_uses_lightweight_model() -> None:
    captured: list[dict[str, Any]] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json=_completion(content="Bullish AI tone.", model=LIGHT))

    respx.post(CHAT_URL).mock(side_effect=_capture)

    router = _router()
    out = await router.summarize(
        api_key="sk-or-test", system="brief", user="news here", max_tokens=512
    )

    assert out == "Bullish AI tone."
    assert captured[0]["model"] == LIGHT
    assert captured[0]["messages"][0]["role"] == "system"
    assert captured[0]["messages"][1]["content"] == "news here"


@respx.mock
async def test_summarize_handles_segmented_content() -> None:
    payload = {
        "id": "gen-x",
        "model": LIGHT,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Hello "},
                        {"type": "text", "text": "world."},
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=payload))
    out = await _router().summarize(api_key="sk-or-test", system="s", user="u")
    assert out == "Hello world."


# ---------- decide ----------


@respx.mock
async def test_decide_parses_structured_response_and_uses_heavy_model() -> None:
    decision = {
        "action": "recommend",
        "chosen_ticker": "AMD",
        "chosen_contract": {
            "ticker": "AMD",
            "option_type": "call",
            "position_side": "long",
            "strike": "185",
            "expiry": "2026-05-15",
            "rationale": "ATM-ish call into AMC earnings.",
        },
        "direction_score": 72,
        "contract_score": 68,
        "final_score": 70,
        "reasoning": "Trend up, decent IV, liquid chain.",
        "key_evidence": ["Up 4.3% over 20d", "Bullish news"],
        "key_concerns": ["Bearish broker note"],
        "watchlist_tickers": [],
    }
    captured: list[dict[str, Any]] = []

    def _capture(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200, json=_completion(content=json.dumps(decision), model=HEAVY)
        )

    respx.post(CHAT_URL).mock(side_effect=_capture)

    router = _router()
    out = await router.decide(
        api_key="sk-or-test",
        structured_input=_decision_input(),
        response_schema=StructuredDecision,
        system_prompt="be the heavy model",
    )

    assert isinstance(out, StructuredDecision)
    assert out.action == "recommend"
    assert out.chosen_ticker == "AMD"
    assert out.final_score == 70
    sent = captured[0]
    assert sent["model"] == HEAVY
    assert sent["response_format"] == {"type": "json_object"}
    assert "AMD" in sent["messages"][1]["content"]


@respx.mock
async def test_decide_rejects_non_json_output() -> None:
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion(content="not json at all", model=HEAVY))
    )
    with pytest.raises(LLMValidationError):
        await _router().decide(
            api_key="sk-or-test",
            structured_input=_decision_input(),
            response_schema=StructuredDecision,
            system_prompt="x",
        )


@respx.mock
async def test_decide_rejects_schema_mismatch() -> None:
    bad = {"action": "definitely-not-a-real-action", "reasoning": "n/a"}
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(
            200, json=_completion(content=json.dumps(bad), model=HEAVY)
        )
    )
    with pytest.raises(LLMValidationError):
        await _router().decide(
            api_key="sk-or-test",
            structured_input=_decision_input(),
            response_schema=StructuredDecision,
            system_prompt="x",
        )


# ---------- §7.4 separation rule ----------


async def test_decide_against_lightweight_model_raises_value_error() -> None:
    misconfigured = LLMRouter(settings=_settings(heavy=LIGHT, light=LIGHT))
    with pytest.raises(ValueError, match="lightweight model"):
        await misconfigured.decide(
            api_key="sk-or-test",
            structured_input=_decision_input(),
            response_schema=StructuredDecision,
            system_prompt="x",
        )


# ---------- auth ----------


async def test_empty_key_raises_authentication_error_without_http() -> None:
    router = _router()
    with pytest.raises(LLMAuthenticationError):
        await router.summarize(api_key="   ", system="s", user="u")


@respx.mock
async def test_401_surfaces_as_authentication_error() -> None:
    respx.post(CHAT_URL).mock(return_value=httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(LLMAuthenticationError):
        await _router().summarize(api_key="sk-or-bad", system="s", user="u")


@respx.mock
async def test_403_surfaces_as_authentication_error() -> None:
    respx.post(CHAT_URL).mock(return_value=httpx.Response(403, json={"error": "forbidden"}))
    with pytest.raises(LLMAuthenticationError):
        await _router().summarize(api_key="sk-or-bad", system="s", user="u")


# ---------- 5xx retry / 429 ----------


@respx.mock
async def test_5xx_retries_then_succeeds() -> None:
    route = respx.post(CHAT_URL).mock(
        side_effect=[
            httpx.Response(503, text="upstream down"),
            httpx.Response(503, text="still down"),
            httpx.Response(200, json=_completion(content="ok", model=LIGHT)),
        ]
    )
    out = await _router(max_attempts=3).summarize(api_key="sk-or-test", system="s", user="u")
    assert out == "ok"
    assert route.call_count == 3


@respx.mock
async def test_5xx_exhausts_retries_and_raises_unavailable() -> None:
    respx.post(CHAT_URL).mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(LLMUnavailableError):
        await _router(max_attempts=2).summarize(api_key="sk-or-test", system="s", user="u")


@respx.mock
async def test_429_final_raises_rate_limit() -> None:
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(
            429, headers={"x-ratelimit-final": "true"}, text="slow down"
        )
    )
    with pytest.raises(LLMRateLimitError):
        await _router(max_attempts=2).summarize(api_key="sk-or-test", system="s", user="u")


# ---------- telemetry ----------


@respx.mock
async def test_telemetry_sink_receives_usage() -> None:
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(
            200,
            json=_completion(
                content="ok", model=LIGHT, prompt_tokens=21, completion_tokens=5, cost=0.0042
            ),
        )
    )
    captured: list[CallTelemetry] = []
    router = _router(sink=captured)
    await router.summarize(api_key="sk-or-test", system="s", user="u")

    assert len(captured) == 1
    t = captured[0]
    assert t.role == "summarize"
    assert t.model == LIGHT
    assert t.prompt_tokens == 21
    assert t.completion_tokens == 5
    assert t.total_tokens == 26
    assert t.estimated_cost_usd == Decimal("0.0042")
    assert t.duration_ms >= 0


# ---------- pydantic input discipline ----------


async def test_decision_input_requires_at_least_one_candidate() -> None:
    with pytest.raises(ValidationError):
        DecisionInput(
            user_strategy_permission="long_only",
            risk_profile="Balanced",
            account_size=Decimal("1000"),
            candidates=[],
        )


async def test_decision_input_serializes_each_prd_7_5_field() -> None:
    bundle = _decision_input()
    serialized = bundle.model_dump_json()
    for needle in (
        "ticker",
        "company_name",
        "earnings_date",
        "earnings_timing",
        "market_cap",
        "current_price",
        "recent_returns",
        "news_summary",
        "expected_move",
        "previous_earnings_move",
        "data_confidence_score",
        "rejected_contract_reasons",
    ):
        assert needle in serialized


# ---------- additional schema for arbitrary decide() targets ----------


class _SmallSchema(BaseModel):
    label: str
    score: int


@respx.mock
async def test_decide_works_with_arbitrary_response_schema() -> None:
    body = {"label": "ok", "score": 9}
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(
            200, json=_completion(content=json.dumps(body), model=HEAVY)
        )
    )
    out = await _router().decide(
        api_key="sk-or-test",
        structured_input=_decision_input(),
        response_schema=_SmallSchema,
        system_prompt="x",
    )
    assert isinstance(out, _SmallSchema)
    assert out.label == "ok"
    assert out.score == 9
