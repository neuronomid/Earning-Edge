from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.core.logging import get_logger
from app.services.news.types import NewsArticle, SearchResult

DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class ArticleFetcher:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        max_chars: int = 6000,
        logger: Any | None = None,
    ) -> None:
        self._client = client
        self.max_chars = max_chars
        self.logger = logger or get_logger(__name__)

    async def fetch(self, result: SearchResult) -> NewsArticle | None:
        raw_html = await self._download(result.url)
        text = await asyncio.to_thread(_extract_text, raw_html)
        normalized = _normalize_text(text)
        if len(normalized.split()) < 40:
            return None

        content = normalized[: self.max_chars].strip()
        return NewsArticle(
            title=result.title,
            url=result.url,
            snippet=result.snippet,
            content=content,
            source=result.source or _domain_from_url(result.url),
            published_at=result.published_at,
            is_ir_fallback=result.is_ir_fallback,
        )

    async def fetch_many(
        self,
        results: Sequence[SearchResult],
        *,
        limit: int | None = None,
    ) -> tuple[NewsArticle, ...]:
        selected = tuple(results[:limit] if limit is not None else results)
        fetched = await asyncio.gather(
            *(self.fetch(result) for result in selected),
            return_exceptions=True,
        )

        articles: list[NewsArticle] = []
        for result, item in zip(selected, fetched, strict=True):
            if isinstance(item, BaseException):
                self.logger.warning(
                    "news_fetch_failed",
                    url=result.url,
                    title=result.title,
                    error=str(item),
                )
                continue
            if item is not None:
                articles.append(item)
        return tuple(articles)

    async def _download(self, url: str) -> str:
        parsed = urlsplit(url)
        if parsed.scheme == "file":
            path = Path(unquote(parsed.path))
            return await asyncio.to_thread(path.read_text, encoding="utf-8")

        if self._client is not None:
            response = await self._client.get(url, follow_redirects=True)
            response.raise_for_status()
            return response.text

        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text


def _extract_text(raw_html: str) -> str:
    try:
        import trafilatura
    except ImportError as exc:  # pragma: no cover - exercised through dependency install
        raise RuntimeError("trafilatura is not installed. Add phase-8 dependencies first.") from exc

    extracted = trafilatura.extract(
        raw_html,
        output_format="txt",
        include_comments=False,
        deduplicate=True,
        favor_precision=True,
    )
    if extracted:
        return extracted

    soup = BeautifulSoup(raw_html, "lxml")
    return soup.get_text("\n")


def _normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    nonempty = [line for line in lines if line]
    return "\n".join(nonempty)


def _domain_from_url(url: str) -> str | None:
    netloc = urlsplit(url).netloc.strip().lower()
    return netloc or None
