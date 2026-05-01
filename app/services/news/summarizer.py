from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import ValidationError

from app.core.logging import get_logger
from app.llm import LLMRouter
from app.services.news.types import NewsArticle, NewsBrief


class LightweightSummarizer(Protocol):
    async def summarize(
        self,
        *,
        api_key: str,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str: ...


class NewsSummaryError(RuntimeError):
    """Base class for phase-8 summarization failures."""


class NewsSummaryValidationError(NewsSummaryError):
    """Raised when the lightweight model does not return a valid NewsBrief."""


class NewsSummarizer:
    def __init__(
        self,
        *,
        router: LightweightSummarizer | None = None,
        logger: Any | None = None,
    ) -> None:
        self.router = router or LLMRouter()
        self.logger = logger or get_logger(__name__)

    async def summarize(
        self,
        *,
        ticker: str,
        company_name: str | None = None,
        articles: Sequence[NewsArticle],
        api_key: str,
    ) -> NewsBrief:
        if not ticker.strip():
            raise ValueError("ticker is required")
        if not articles:
            raise ValueError("at least one article is required")
        if not api_key.strip():
            raise ValueError("api_key is required")

        schema_json = json.dumps(NewsBrief.model_json_schema(), separators=(",", ":"))
        article_payload = json.dumps(
            [
                {
                    "title": article.title,
                    "url": article.url,
                    "source": article.source,
                    "published_at": (
                        None
                        if article.published_at is None
                        else article.published_at.isoformat()
                    ),
                    "is_ir_fallback": article.is_ir_fallback,
                    "snippet": article.snippet[:400],
                    "content": article.content[:1800],
                }
                for article in articles
            ],
            ensure_ascii=True,
        )
        company_label = company_name.strip() if company_name else ticker.strip().upper()
        text = await self.router.summarize(
            api_key=api_key.strip(),
            system=_system_prompt(),
            user=(
                f"TICKER: {ticker.strip().upper()}\n"
                f"COMPANY: {company_label}\n"
                f"RESPONSE_SCHEMA: {schema_json}\n"
                f"ARTICLES_JSON: {article_payload}"
            ),
            max_tokens=1200,
            temperature=0.2,
        )

        payload = _parse_json_payload(text)
        try:
            return NewsBrief.model_validate(payload)
        except ValidationError as exc:
            raise NewsSummaryValidationError(
                f"Lightweight model returned an invalid NewsBrief: {exc}"
            ) from exc


def _system_prompt() -> str:
    return (
        "You summarize recent company and sector news for an earnings options workflow. "
        "Return JSON only. Be concrete, concise, and evidence-based. "
        "Use short bullet-style strings inside the evidence arrays. "
        "Keep News confidence as an integer from 0 to 100 based on article quality, "
        "recency, and agreement across sources."
    )


def _parse_json_payload(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = candidate[start : end + 1]

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise NewsSummaryValidationError(
            f"Lightweight model returned invalid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise NewsSummaryValidationError("Lightweight model returned a non-object payload.")
    return payload
