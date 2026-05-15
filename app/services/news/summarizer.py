from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError

from app.core.logging import get_logger
from app.llm import LLMRouter
from app.services.news.types import NewsArticle, NewsBrief, NewsBriefStatus


@dataclass(frozen=True)
class SummarizeOutcome:
    """Result of a NewsSummarizer.summarize() call.

    Carries the brief plus an independent status field. `status="ok"` means the
    lightweight model returned a valid summary. `status="raw_extractive"` means
    the model failed but we built a deterministic headline-only brief from the
    raw articles so downstream still sees the real news context.
    """

    brief: NewsBrief
    status: NewsBriefStatus


class LightweightSummarizer(Protocol):
    async def summarize(
        self,
        *,
        api_key: str,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.3,
        response_format: dict[str, Any] | None = None,
    ) -> str: ...


class NewsSummaryError(RuntimeError):
    """Base class for phase-8 summarization failures."""


class NewsSummaryValidationError(NewsSummaryError):
    """Raised when the lightweight model does not return a valid NewsBrief."""


_PRIMARY_MAX_TOKENS = 4096
_RETRY_MAX_TOKENS = 8192


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
    ) -> SummarizeOutcome:
        if not ticker.strip():
            raise ValueError("ticker is required")
        if not articles:
            raise ValueError("at least one article is required")
        if not api_key.strip():
            raise ValueError("api_key is required")

        normalized_ticker = ticker.strip().upper()
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
        company_label = company_name.strip() if company_name else normalized_ticker
        user_prompt = (
            f"TICKER: {normalized_ticker}\n"
            f"COMPANY: {company_label}\n"
            f"RESPONSE_SCHEMA: {schema_json}\n"
            f"ARTICLES_JSON: {article_payload}"
        )

        brief = await self._attempt(
            api_key=api_key.strip(),
            system=_system_prompt(),
            user=user_prompt,
            max_tokens=_PRIMARY_MAX_TOKENS,
            ticker=normalized_ticker,
            attempt="primary",
        )
        if brief is not None:
            return SummarizeOutcome(brief=brief, status="ok")

        # Most failures are JSON truncated mid-string because the model bumped
        # into max_tokens. Retry once with a larger budget + brevity hint so the
        # response is forced to fit in a single complete JSON object.
        retry_brief = await self._attempt(
            api_key=api_key.strip(),
            system=_system_prompt()
            + (
                "\n\nIMPORTANT: keep `summary` under 600 characters and prefer "
                "compact `key_facts` entries — the JSON output must be a single "
                "syntactically complete object that fits in this response."
            ),
            user=user_prompt,
            max_tokens=_RETRY_MAX_TOKENS,
            ticker=normalized_ticker,
            attempt="retry",
        )
        if retry_brief is not None:
            return SummarizeOutcome(brief=retry_brief, status="ok")

        # Both attempts failed. Don't lie about news availability — build a
        # deterministic raw-headline brief so downstream decisioning still sees
        # the real article evidence. Only the *summary* failed, not the data.
        self.logger.warning(
            "gemini_brief_using_raw_fallback",
            ticker=normalized_ticker,
            article_count=len(articles),
        )
        return SummarizeOutcome(
            brief=_raw_extractive_brief(articles),
            status="raw_extractive",
        )

    async def _attempt(
        self,
        *,
        api_key: str,
        system: str,
        user: str,
        max_tokens: int,
        ticker: str,
        attempt: str,
    ) -> NewsBrief | None:
        try:
            text = await self.router.summarize(
                api_key=api_key,
                system=system,
                user=user,
                max_tokens=max_tokens,
                temperature=0,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            self.logger.warning(
                "gemini_brief_failed",
                ticker=ticker,
                attempt=attempt,
                error=str(exc),
            )
            return None

        try:
            payload = _parse_json_payload(text)
            return NewsBrief.model_validate(payload)
        except (ValidationError, NewsSummaryValidationError) as exc:
            self.logger.warning(
                "gemini_brief_invalid",
                ticker=ticker,
                attempt=attempt,
                error=str(exc),
                response_length=len(text),
                response_tail=text[-200:] if text else "",
            )
            return None


def _failure_brief() -> NewsBrief:
    return NewsBrief(
        summary="",
        key_facts=[],
        quoted_statements=[],
        named_actions=[],
        neutral_contextual_evidence=[],
        key_uncertainty="news service unavailable",
    )


_MAX_RAW_HEADLINES = 12


def _raw_extractive_brief(articles: Sequence[NewsArticle]) -> NewsBrief:
    """Deterministic fallback brief built from raw article metadata.

    Used when the lightweight summary model cannot produce valid JSON. We keep
    the most recent articles, list them as `key_facts` in `title — source (date)`
    form, and surface the data gap honestly in `key_uncertainty` so the heavy
    decision model knows the brief is mechanical, not interpreted.
    """
    ordered = sorted(
        articles,
        key=lambda a: a.published_at or _MIN_DATETIME,
        reverse=True,
    )[:_MAX_RAW_HEADLINES]
    key_facts: list[str] = []
    for article in ordered:
        title = article.title.strip() or article.url
        source = article.source.strip() if article.source else "unknown source"
        date_part = article.published_at.date().isoformat() if article.published_at else "undated"
        key_facts.append(f"{title} — {source} ({date_part})")
    context = [
        f"Raw extractive brief built from {len(articles)} fetched articles after the "
        "lightweight summary model could not produce a valid JSON response.",
        "Headlines preserved verbatim; no synthesis was attempted.",
    ]
    return NewsBrief(
        summary="",
        key_facts=key_facts,
        quoted_statements=[],
        named_actions=[],
        neutral_contextual_evidence=context,
        key_uncertainty=("Lightweight summary model unavailable; raw article headlines below."),
    )


_MIN_DATETIME = datetime.min.replace(tzinfo=UTC)


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
    except json.JSONDecodeError as first_exc:
        repaired = _repair_loose_json(candidate)
        if repaired is None:
            raise NewsSummaryValidationError(
                f"Lightweight model returned invalid JSON: {first_exc}"
            ) from first_exc
        try:
            payload = json.loads(repaired)
        except json.JSONDecodeError as second_exc:
            raise NewsSummaryValidationError(
                f"Lightweight model returned invalid JSON even after repair: {second_exc}"
            ) from second_exc
    if not isinstance(payload, dict):
        raise NewsSummaryValidationError("Lightweight model returned a non-object payload.")
    return payload


def _repair_loose_json(text: str) -> str | None:
    """Best-effort fix for common Gemini JSON malformations.

    Handles two recurring patterns in summarize() output that we cannot
    re-prompt for cheaply: trailing commas before ``}``/``]``, and unescaped
    embedded double quotes inside string values (the column-155 failures we
    see in practice). Returns ``None`` if the input does not look like a JSON
    object at all so the caller fails closed.
    """
    if "{" not in text or "}" not in text:
        return None
    repaired = re.sub(r",(\s*[}\]])", r"\1", text)
    repaired = _escape_inner_double_quotes(repaired)
    return repaired


def _escape_inner_double_quotes(text: str) -> str:
    """Escape un-escaped double quotes that appear inside JSON string values.

    Walks the buffer manually because a regex cannot tell the difference
    between a closing quote and a stray inner one. The heuristic: a ``"`` ends
    the current string only when the next non-space char is ``,``, ``}``,
    ``]``, or ``:`` (key-context).
    """
    out: list[str] = []
    in_string = False
    escape = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if escape:
            out.append(ch)
            escape = False
            i += 1
            continue
        if ch == "\\":
            out.append(ch)
            escape = True
            i += 1
            continue
        if ch == '"':
            if not in_string:
                in_string = True
                out.append(ch)
            else:
                # Look ahead: if the next meaningful char ends the value, this
                # is a real closing quote. Otherwise treat as a stray quote
                # inside the string and escape it.
                j = i + 1
                while j < n and text[j] in " \t":
                    j += 1
                next_char = text[j] if j < n else ""
                if next_char in {",", "}", "]", ":", "\n", "\r", ""}:
                    in_string = False
                    out.append(ch)
                else:
                    out.append("\\")
                    out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)
