from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import pytest

from app.services.news.search import NewsSearchService, _load_ddgs
from app.services.news.types import SearchResult

pytestmark = pytest.mark.asyncio


@dataclass
class FakeProvider:
    responses: dict[tuple[str, str], list[SearchResult]]
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def search(
        self,
        query: str,
        *,
        max_results: int,
        section: str = "news",
    ) -> list[SearchResult]:
        self.calls.append((section, query))
        return self.responses.get((section, query), [])[:max_results]


async def test_news_search_service_uses_ir_fallback_and_deduplicates_urls() -> None:
    provider = FakeProvider(
        responses={
            ("news", '"Advanced Micro Devices" AMD news'): [
                SearchResult(
                    query=' "ignored" ',
                    title="Primary article",
                    url="https://example.com/amd-primary",
                    snippet="snippet",
                    source="Example",
                ),
                SearchResult(
                    query=' "ignored" ',
                    title="Duplicate primary article",
                    url="https://example.com/amd-primary",
                    snippet="duplicate",
                    source="Example",
                ),
            ],
            ("text", '"Advanced Micro Devices" investor relations'): [
                SearchResult(
                    query=' "ignored" ',
                    title="IR page",
                    url="https://ir.example.com/amd-update",
                    snippet="IR fallback",
                    source="IR",
                )
            ],
        }
    )
    service = NewsSearchService(provider=provider, max_results_per_query=3, min_primary_results=3)

    response = await service.search_ticker("amd", company_name="Advanced Micro Devices")

    assert [result.url for result in response.primary_results] == [
        "https://example.com/amd-primary"
    ]
    assert [result.url for result in response.fallback_results] == [
        "https://ir.example.com/amd-update"
    ]
    assert response.fallback_results[0].is_ir_fallback is True
    assert ("news", '"Advanced Micro Devices" AMD analyst expectations') in provider.calls
    assert ("text", '"Advanced Micro Devices" investor relations') in provider.calls


@dataclass
class FailingProvider:
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def search(
        self,
        query: str,
        *,
        max_results: int,
        section: str = "news",
    ) -> list[SearchResult]:
        del max_results
        self.calls.append((section, query))
        if section == "news":
            raise RuntimeError("https://duckduckgo.com/news.js 403 Ratelimit")
        return [
            SearchResult(
                query=query,
                title="IR page",
                url="https://ir.example.com/amd-update",
                snippet="IR fallback",
                source="IR",
            ),
            SearchResult(
                query=query,
                title="Junk page",
                url="https://www.zhihu.com/question/123",
                snippet="junk",
                source="Zhihu",
            ),
        ]


async def test_news_search_service_stops_after_news_rate_limit_and_filters_fallback_noise() -> None:
    provider = FailingProvider()
    service = NewsSearchService(provider=provider, max_results_per_query=3, min_primary_results=3)

    response = await service.search_ticker("amd", company_name="Advanced Micro Devices")

    assert response.primary_results == ()
    assert [result.url for result in response.fallback_results] == [
        "https://ir.example.com/amd-update"
    ]
    assert provider.calls == [
        ("news", '"Advanced Micro Devices" AMD news'),
        ("text", '"Advanced Micro Devices" investor relations'),
        ("text", '"Advanced Micro Devices" AMD press release'),
    ]


async def test_load_ddgs_suppresses_legacy_package_rename_warning() -> None:
    ddgs_cls = _load_ddgs()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ddgs = ddgs_cls()

    assert not any("renamed to `ddgs`" in str(item.message) for item in caught)
    del ddgs
