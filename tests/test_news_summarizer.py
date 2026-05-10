from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

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

    async def summarize(
        self,
        *,
        api_key: str,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str:
        del api_key, system, user, max_tokens
        self.captured_temperature = temperature
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

            brief = await summarizer.summarize(
                ticker="AMD",
                company_name="Advanced Micro Devices",
                articles=(_sample_article(),),
                api_key="test-openrouter-key",
            )

    assert brief.summary == "Data center backlog improved; margins still need to prove out."
    assert brief.key_facts == ["Backlog up double digits quarter-over-quarter."]
    assert brief.key_uncertainty == "Guidance wording could still move the stock sharply."


async def test_news_summarizer_returns_failure_brief_on_schema_invalid_response() -> None:
    """When Gemini returns a payload missing required fields, return the explicit
    failure brief instead of raising. Opus then sees the unavailable marker."""
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
                                "content": '{"unexpected_field":"value"}'
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 9, "total_tokens": 17},
                },
            )

            brief = await summarizer.summarize(
                ticker="AMD",
                company_name="Advanced Micro Devices",
                articles=(_sample_article(),),
                api_key="test-openrouter-key",
            )

    assert brief.key_uncertainty == "news service unavailable"
    assert brief.summary == ""


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
