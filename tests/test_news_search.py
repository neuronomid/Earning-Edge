from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.services.news.search import NewsSearchService
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

    assert [result.url for result in response.primary_results] == ["https://example.com/amd-primary"]
    assert [result.url for result in response.fallback_results] == [
        "https://ir.example.com/amd-update"
    ]
    assert response.fallback_results[0].is_ir_fallback is True
    assert ("news", '"Advanced Micro Devices" AMD analyst expectations') in provider.calls
    assert ("text", '"Advanced Micro Devices" investor relations') in provider.calls
