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
                        None if article.published_at is None else article.published_at.isoformat()
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
        try:
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
                temperature=0,
            )
        except Exception as exc:
            self.logger.warning(
                "gemini_brief_failed",
                ticker=ticker.strip().upper(),
                error=str(exc),
            )
            return _failure_brief()

        try:
            payload = _parse_json_payload(text)
            return NewsBrief.model_validate(payload)
        except (ValidationError, NewsSummaryValidationError) as exc:
            self.logger.warning(
                "gemini_brief_invalid",
                ticker=ticker.strip().upper(),
                error=str(exc),
            )
            return _failure_brief()


def _failure_brief() -> NewsBrief:
    return NewsBrief(
        summary="",
        key_facts=[],
        quoted_statements=[],
        named_actions=[],
        neutral_contextual_evidence=[],
        key_uncertainty="news service unavailable",
    )


def _system_prompt() -> str:
    return (
        "You are a factual extractor for an earnings options workflow. "
        "Read the supplied articles and return JSON ONLY matching the response "
        "schema. Do not produce directional opinions or trade advice — your job is "
        "to preserve facts faithfully so a downstream analyst can interpret them.\n"
        "\n"
        "Required behavior:\n"
        "- Preserve every quantitative figure verbatim: guidance ranges, EPS "
        "  estimates, revenue numbers, percentage changes, dollar amounts.\n"
        "- Quote executives and analysts directly when their words appear; attach "
        "  the speaker's name and role.\n"
        "- Name every analyst with their action (upgrade, downgrade, target change) "
        "  and the new target where stated.\n"
        "- Include all dates of upcoming events (earnings, investor days, deal "
        "  closings, regulatory deadlines).\n"
        "- Capture M&A specifics (parties, price, structure) and regulatory actions "
        "  (agency, charge, status) in full.\n"
        "- Use `summary` for a neutral paragraph-length overview that scales with "
        "  substance. Use `key_facts` for the unbounded list of preserved facts. "
        "  Use `quoted_statements` for verbatim quotes with attribution. Use "
        "  `named_actions` for analyst/regulatory/M&A actions with full detail. "
        "  Use `neutral_contextual_evidence` for sector/macro context that does "
        "  not name a specific action. Use `key_uncertainty` for factual gaps.\n"
        "\n"
        "Completeness check (mandatory before returning): re-scan every article "
        "and verify that no quantitative figure, quoted statement, or named "
        "action was summarized away. If anything was dropped, add it back to "
        "`key_facts`, `quoted_statements`, or `named_actions` before responding."
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
        raise NewsSummaryValidationError(f"Lightweight model returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise NewsSummaryValidationError("Lightweight model returned a non-object payload.")
    return payload
