from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from app.llm import LLMRouter
from app.services.news.summarizer import NewsSummarizer
from app.services.news.types import NewsArticle

pytestmark = pytest.mark.asyncio


@dataclass
class RecordingRouter:
    response_text: str
    captured_temperature: float | None = None
    captured_max_tokens: int | None = None
    captured_response_format: dict[str, Any] | None = None
    call_count: int = 0
    responses: list[str] = field(default_factory=list)

    async def summarize(
        self,
        *,
        api_key: str,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.3,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        del api_key, system, user
        self.captured_temperature = temperature
        self.captured_max_tokens = max_tokens
        self.captured_response_format = response_format
        self.call_count += 1
        if self.responses:
            return self.responses.pop(0)
        return self.response_text


async def test_news_summarizer_parses_valid_openrouter_response() -> None:
    async with httpx.AsyncClient() as client:
        router = LLMRouter(client=client)
        summarizer = NewsSummarizer(router=router)

        with respx.mock(assert_all_called=True) as mock:
            mock.post("https://openrouter.ai/api/v1/chat/completions").respond(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": """
```json
{
  "neutral_contextual_evidence": ["Sector demand remains constructive"],
  "key_uncertainty": "Guidance wording could still move the stock sharply.",
  "summary": "Data center backlog improved; margins still need to prove out.",
  "key_facts": ["Backlog up double digits quarter-over-quarter."],
  "quoted_statements": [],
  "named_actions": []
}
```"""
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
                },
            )

            outcome = await summarizer.summarize(
                ticker="AMD",
                company_name="Advanced Micro Devices",
                articles=(_sample_article(),),
                api_key="test-openrouter-key",
            )

    brief = outcome.brief
    assert outcome.status == "ok"
    assert brief.summary == "Data center backlog improved; margins still need to prove out."
    assert brief.key_facts == ["Backlog up double digits quarter-over-quarter."]
    assert brief.key_uncertainty == "Guidance wording could still move the stock sharply."


async def test_news_summarizer_returns_raw_extractive_brief_when_model_fails() -> None:
    """When Gemini returns invalid JSON twice, fall back to a deterministic raw
    extractive brief built from the article headlines. This prevents a
    summarizer hiccup from masquerading as a news blackout — the downstream
    LLM still sees real article evidence."""
    async with httpx.AsyncClient() as client:
        router = LLMRouter(client=client)
        summarizer = NewsSummarizer(router=router)

        with respx.mock(assert_all_called=True) as mock:
            mock.post("https://openrouter.ai/api/v1/chat/completions").respond(
                200,
                json={
                    "choices": [{"message": {"content": '{"unexpected_field":"value"}'}}],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 9, "total_tokens": 17},
                },
            )

            outcome = await summarizer.summarize(
                ticker="AMD",
                company_name="Advanced Micro Devices",
                articles=(_sample_article(),),
                api_key="test-openrouter-key",
            )

    assert outcome.status == "raw_extractive"
    brief = outcome.brief
    assert brief.summary == ""
    assert brief.key_facts, "raw extractive brief must surface at least one headline"
    assert "AMD preview" in brief.key_facts[0]
    assert "raw extractive" in " ".join(brief.neutral_contextual_evidence).lower()


async def test_news_summarizer_uses_zero_temperature() -> None:
    router = RecordingRouter(
        response_text=(
            '{"neutral_contextual_evidence":[],'
            '"key_uncertainty":"Need guidance.",'
            '"summary":"Supportive note.","key_facts":[],'
            '"quoted_statements":[],"named_actions":[]}'
        )
    )
    summarizer = NewsSummarizer(router=router)

    await summarizer.summarize(
        ticker="AMD",
        company_name="Advanced Micro Devices",
        articles=(_sample_article(),),
        api_key="test-openrouter-key",
    )

    assert router.captured_temperature == 0


async def test_news_summarizer_retries_with_wider_budget_on_truncated_json() -> None:
    """If the lightweight model returns truncated JSON (mid-string), retry once
    with a larger token budget and a brevity hint. This matches the production
    Gemini failure that produced 'news service unavailable' across all
    finalists earlier this run."""

    truncated = (
        '{"summary": "Primo Brands Corporation reported Q1 2026 results posting'
        " sales of $1,626"  # deliberately cut off mid-string
    )
    valid = (
        '{"neutral_contextual_evidence":[],'
        '"key_uncertainty":"None notable.",'
        '"summary":"Compact valid brief.","key_facts":["Sales up modestly."],'
        '"quoted_statements":[],"named_actions":[]}'
    )
    router = RecordingRouter(response_text=valid, responses=[truncated, valid])
    summarizer = NewsSummarizer(router=router)

    outcome = await summarizer.summarize(
        ticker="PRMB",
        company_name="Primo Brands Corp",
        articles=(_sample_article(),),
        api_key="test-openrouter-key",
    )

    assert router.call_count == 2  # retried once
    assert outcome.status == "ok"
    brief = outcome.brief
    assert brief.summary == "Compact valid brief."
    assert brief.key_uncertainty == "None notable."
    assert router.captured_max_tokens is not None and router.captured_max_tokens >= 4096


async def test_news_summarizer_passes_response_format_json_object() -> None:
    """Both attempts ask OpenRouter for a JSON object response so providers
    that honour the constraint (Gemini, OpenAI) return parseable output."""
    valid = (
        '{"neutral_contextual_evidence":[],'
        '"key_uncertainty":"None.",'
        '"summary":"OK.","key_facts":[],'
        '"quoted_statements":[],"named_actions":[]}'
    )
    router = RecordingRouter(response_text=valid)
    summarizer = NewsSummarizer(router=router)

    await summarizer.summarize(
        ticker="PRMB",
        articles=(_sample_article(),),
        api_key="test-openrouter-key",
    )

    assert router.captured_response_format == {"type": "json_object"}


def _sample_article() -> NewsArticle:
    return NewsArticle(
        title="AMD preview",
        url="https://example.com/amd-preview",
        snippet="AMD preview snippet",
        content=(
            "AMD described broader cloud demand and improving backlog visibility ahead of "
            "earnings, while analysts still want proof that margins can expand as the "
            "company ramps its next accelerator platform."
        ),
        source="example.com",
        published_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        is_ir_fallback=False,
    )
