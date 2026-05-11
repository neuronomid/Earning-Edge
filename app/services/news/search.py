from __future__ import annotations

import asyncio
import os
import warnings
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

from app.core.logging import get_logger
from app.services.news.types import SearchResponse, SearchResult

SearchSection = Literal["news", "text"]


class SearchProvider(Protocol):
    async def search(
        self,
        query: str,
        *,
        max_results: int,
        section: SearchSection = "news",
    ) -> list[SearchResult]: ...


class DuckDuckGoSearchProvider:
    def __init__(
        self,
        *,
        region: str = "wt-wt",
        safesearch: str = "moderate",
        timelimit: str = "m",
        logger: Any | None = None,
    ) -> None:
        self.region = region
        self.safesearch = safesearch
        self.timelimit = timelimit
        self.logger = logger or get_logger(__name__)

    async def search(
        self,
        query: str,
        *,
        max_results: int,
        section: SearchSection = "news",
    ) -> list[SearchResult]:
        return await asyncio.to_thread(
            self._search_sync,
            query,
            max_results=max_results,
            section=section,
        )

    def _search_sync(
        self,
        query: str,
        *,
        max_results: int,
        section: SearchSection,
    ) -> list[SearchResult]:
        ddgs_cls = _load_ddgs()

        with ddgs_cls() as ddgs:
            if section == "news":
                rows = list(
                    ddgs.news(
                        query,
                        region=self.region,
                        safesearch=self.safesearch,
                        timelimit=self.timelimit,
                        max_results=max_results,
                    )
                )
            else:
                rows = list(
                    ddgs.text(
                        query,
                        region=self.region,
                        safesearch=self.safesearch,
                        timelimit=self.timelimit,
                        max_results=max_results,
                    )
                )

        return [
            SearchResult(
                query=query,
                title=str(row.get("title") or row.get("heading") or ""),
                url=str(row.get("url") or row.get("href") or ""),
                snippet=str(row.get("body") or row.get("snippet") or ""),
                source=_coerce_source(row),
                published_at=_parse_published_at(row),
            )
            for row in rows
            if row.get("url") or row.get("href")
        ]


class NewsSearchService:
    def __init__(
        self,
        provider: SearchProvider | None = None,
        *,
        max_results_per_query: int = 4,
        min_primary_results: int = 3,
        logger: Any | None = None,
    ) -> None:
        self.provider = provider or DuckDuckGoSearchProvider()
        self.max_results_per_query = max_results_per_query
        self.min_primary_results = min_primary_results
        self.logger = logger or get_logger(__name__)

    async def search_ticker(
        self,
        ticker: str,
        *,
        company_name: str | None = None,
    ) -> SearchResponse:
        normalized = ticker.strip().upper()
        if not normalized:
            raise ValueError("ticker is required")

        primary = await self._run_queries(
            _primary_queries(normalized, company_name),
            section="news",
            mark_ir_fallback=False,
        )
        fallback: tuple[SearchResult, ...] = ()
        if len(primary) < self.min_primary_results:
            fallback = await self._run_queries(
                _fallback_queries(normalized, company_name),
                section="text",
                mark_ir_fallback=True,
                seen_urls={_normalized_url(result.url) for result in primary},
            )

        return SearchResponse(
            ticker=normalized,
            company_name=company_name,
            primary_results=primary,
            fallback_results=fallback,
        )

    async def _run_queries(
        self,
        queries: Sequence[str],
        *,
        section: SearchSection,
        mark_ir_fallback: bool,
        seen_urls: set[str] | None = None,
    ) -> tuple[SearchResult, ...]:
        seen = set() if seen_urls is None else set(seen_urls)
        merged: list[SearchResult] = []
        for query in queries:
            try:
                result = await self.provider.search(
                    query,
                    max_results=self.max_results_per_query,
                    section=section,
                )
            except BaseException as exc:
                self.logger.warning(
                    "news_search_query_failed",
                    query=query,
                    section=section,
                    error=str(exc),
                )
                if section == "news" and _is_rate_limited(exc):
                    break
                continue

            for row in result:
                normalized_url = _normalized_url(row.url)
                if (
                    not normalized_url
                    or normalized_url in seen
                    or not _is_allowed_result_url(row.url, is_fallback=mark_ir_fallback)
                ):
                    continue
                seen.add(normalized_url)
                merged.append(
                    row.model_copy(
                        update={"is_ir_fallback": mark_ir_fallback or row.is_ir_fallback}
                    )
                )
        return tuple(merged)


def _primary_queries(ticker: str, company_name: str | None) -> tuple[str, ...]:
    label = company_name.strip() if company_name else ticker
    return (
        f'"{label}" {ticker} news',
        f'"{label}" {ticker} earnings preview',
        f'"{label}" {ticker} analyst expectations',
    )


def _fallback_queries(ticker: str, company_name: str | None) -> tuple[str, ...]:
    label = company_name.strip() if company_name else ticker
    return (
        f'"{label}" investor relations',
        f'"{label}" {ticker} press release',
    )


def _coerce_source(row: dict[str, Any]) -> str | None:
    source = row.get("source")
    if source is not None:
        return str(source)
    return None


def _parse_published_at(row: dict[str, Any]) -> datetime | None:
    raw = row.get("date") or row.get("published") or row.get("published_at")
    if raw in {None, ""}:
        return None
    if isinstance(raw, datetime):
        if raw.tzinfo is not None:
            return raw
        return raw.replace(tzinfo=UTC)

    value = str(raw).strip()
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed
    return parsed.replace(tzinfo=UTC)


def _normalized_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme == "file" and parts.path:
        path = parts.path.rstrip("/") or "/"
        return urlunsplit(("file", "", path, "", ""))
    if not parts.scheme or not parts.netloc:
        return ""
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            path,
            parts.query,
            "",
        )
    )


def _load_ddgs():
    try:
        from ddgs import DDGS

        return DDGS
    except ImportError:
        try:
            import primp
            from duckduckgo_search import DDGS as LEGACY_DDGS
            from duckduckgo_search.utils import _expand_proxy_tb_alias

            class QuietLegacyDDGS(LEGACY_DDGS):
                def __init__(
                    self,
                    headers: dict[str, str] | None = None,
                    proxy: str | None = None,
                    proxies: dict[str, str] | str | None = None,
                    timeout: int | None = 10,
                    verify: bool = True,
                ) -> None:
                    ddgs_proxy = os.environ.get("DDGS_PROXY")
                    self.proxy = ddgs_proxy if ddgs_proxy else _expand_proxy_tb_alias(proxy)
                    assert self.proxy is None or isinstance(self.proxy, str), "proxy must be a str"
                    if not proxy and proxies:
                        warnings.warn("'proxies' is deprecated, use 'proxy' instead.", stacklevel=1)
                        self.proxy = (
                            proxies.get("http") or proxies.get("https")
                            if isinstance(proxies, dict)
                            else proxies
                        )
                    self.headers = headers if headers else {}
                    self.timeout = timeout
                    self.client = primp.Client(
                        proxy=self.proxy,
                        timeout=self.timeout,
                        cookie_store=True,
                        referer=True,
                        impersonate="random",
                        impersonate_os="random",
                        follow_redirects=False,
                        verify=verify,
                    )
                    self.sleep_timestamp = 0.0

            return QuietLegacyDDGS
        except ImportError as exc:  # pragma: no cover - exercised through dependency install
            raise RuntimeError(
                "ddgs is not installed. Add the news-search dependency first."
            ) from exc


def _is_rate_limited(error: BaseException) -> bool:
    message = str(error).lower()
    return "ratelimit" in message or ("403" in message and "duckduckgo" in message)


def _is_allowed_result_url(url: str, *, is_fallback: bool) -> bool:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    path = parts.path.lower()
    if parts.scheme == "file" and parts.path:
        return True
    if not host:
        return False
    if host in {"duckduckgo.com", "www.duckduckgo.com", "bing.com", "www.bing.com"}:
        return False
    if not is_fallback:
        return True

    allowed_tokens = (
        "investor",
        "ir.",
        "press-release",
        "pressrelease",
        "newsroom",
        "media",
        "news/",
        "prnewswire",
        "businesswire",
        "globenewswire",
        "accessnewswire",
        "newsfilecorp",
        "sec.gov",
    )
    haystack = f"{host}{path}"
    return any(token in haystack for token in allowed_tokens)
