from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.llm import LLMRouter
from app.services.news.summarizer import NewsSummarizer, NewsSummaryValidationError
from app.services.news.types import NewsArticle

pytestmark = pytest.mark.asyncio


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
  "bullish_evidence": ["Data center backlog improved"],
  "bearish_evidence": ["Margins still need to prove out"],
  "neutral_contextual_evidence": ["Sector demand remains constructive"],
  "key_uncertainty": "Guidance wording could still move the stock sharply.",
  "news_confidence": 74
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

    assert brief.bullish_evidence == ["Data center backlog improved"]
    assert brief.bearish_evidence == ["Margins still need to prove out"]
    assert brief.news_confidence == 74


async def test_news_summarizer_rejects_schema_invalid_openrouter_response() -> None:
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
                                "content": (
                                    '{"bullish_evidence":["Good backlog"],'
                                    '"bearish_evidence":[],"neutral_contextual_evidence":[],'
                                    '"key_uncertainty":"Need cleaner guide"}'
                                )
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 9, "total_tokens": 17},
                },
            )

            with pytest.raises(NewsSummaryValidationError, match="invalid NewsBrief"):
                await summarizer.summarize(
                    ticker="AMD",
                    company_name="Advanced Micro Devices",
                    articles=(_sample_article(),),
                    api_key="test-openrouter-key",
                )


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
