from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.services.news.fetcher import ArticleFetcher
from app.services.news.search import NewsSearchService
from app.services.news.service import NewsBundleCache, NewsService
from app.services.news.summarizer import NewsSummarizer
from app.services.news.types import NewsArticle, NewsBrief, SearchResponse, SearchResult

pytestmark = pytest.mark.asyncio


@dataclass
class FakeSearchClient:
    response: SearchResponse
    calls: Counter[str] = field(default_factory=Counter)

    async def search_ticker(
        self,
        ticker: str,
        *,
        company_name: str | None = None,
    ) -> SearchResponse:
        del company_name
        self.calls.update([ticker])
        return self.response


@dataclass
class FakeFetcher:
    articles: tuple[NewsArticle, ...]
    calls: int = 0

    async def fetch_many(
        self,
        results: tuple[SearchResult, ...] | list[SearchResult],
        *,
        limit: int | None = None,
    ) -> tuple[NewsArticle, ...]:
        del results, limit
        self.calls += 1
        return self.articles


@dataclass
class FakeSummarizer:
    brief: NewsBrief
    calls: int = 0

    async def summarize(
        self,
        *,
        ticker: str,
        company_name: str | None = None,
        articles: tuple[NewsArticle, ...] | list[NewsArticle],
        api_key: str,
    ) -> NewsBrief:
        del ticker, company_name, articles, api_key
        self.calls += 1
        return self.brief


@dataclass
class FakeRedis:
    values: dict[str, str] = field(default_factory=dict)
    ttl_by_key: dict[str, int] = field(default_factory=dict)

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> bool:
        self.values[key] = value
        self.ttl_by_key[key] = ex
        return True


@dataclass
class FixtureProvider:
    responses: dict[tuple[str, str], list[SearchResult]]

    async def search(
        self,
        query: str,
        *,
        max_results: int,
        section: str = "news",
    ) -> list[SearchResult]:
        return self.responses.get((section, query), [])[:max_results]


@dataclass
class FakeRouter:
    response_text: str
    calls: int = 0

    async def summarize(
        self,
        *,
        api_key: str,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str:
        del api_key, system, user, max_tokens, temperature
        self.calls += 1
        return self.response_text


async def test_news_service_uses_cache_on_repeat_requests() -> None:
    search = FakeSearchClient(response=_search_response())
    fetcher = FakeFetcher(articles=(_article("Primary article"),))
    summarizer = FakeSummarizer(
        brief=NewsBrief(
            bullish_evidence=["Backlog improved"],
            bearish_evidence=[],
            neutral_contextual_evidence=["Sector demand is steady"],
            key_uncertainty="Guidance still matters.",
            news_confidence=72,
        )
    )
    redis = FakeRedis()
    service = NewsService(
        search=search,
        fetcher=fetcher,
        summarizer=summarizer,
        cache=NewsBundleCache(redis, ttl_seconds=3600),
    )

    first = await service.bundle("amd", api_key="test-key")
    second = await service.bundle("AMD", api_key="test-key")

    assert first == second
    assert search.calls["AMD"] == 1
    assert fetcher.calls == 1
    assert summarizer.calls == 1
    assert redis.ttl_by_key["news:AMD"] == 3600


async def test_news_service_returns_low_confidence_brief_when_no_articles_are_available() -> None:
    service = NewsService(
        search=FakeSearchClient(
            response=SearchResponse(
                ticker="AMD",
                company_name="Advanced Micro Devices",
                primary_results=(),
                fallback_results=(),
            )
        ),
        fetcher=FakeFetcher(articles=()),
        summarizer=FakeSummarizer(
            brief=NewsBrief(
                bullish_evidence=["Should not be used"],
                bearish_evidence=[],
                neutral_contextual_evidence=[],
                key_uncertainty="unused",
                news_confidence=99,
            )
        ),
        cache=None,
    )

    brief = await service.brief("AMD")

    assert brief.news_confidence == 25
    assert brief.neutral_contextual_evidence == ["Recent company-specific reporting was sparse."]


async def test_news_service_caps_confidence_when_coverage_is_thin() -> None:
    service = NewsService(
        search=FakeSearchClient(
            response=SearchResponse(
                ticker="AMD",
                company_name="Advanced Micro Devices",
                primary_results=(),
                fallback_results=(
                    SearchResult(
                        query="fallback",
                        title="IR page",
                        url="https://ir.example.com/amd",
                        snippet="IR",
                        source="IR",
                        is_ir_fallback=True,
                    ),
                ),
            )
        ),
        fetcher=FakeFetcher(articles=(_article("IR article", is_ir_fallback=True),)),
        summarizer=FakeSummarizer(
            brief=NewsBrief(
                bullish_evidence=["Official update was constructive"],
                bearish_evidence=[],
                neutral_contextual_evidence=[],
                key_uncertainty="Independent confirmation is limited.",
                news_confidence=92,
            )
        ),
        cache=None,
    )

    brief = await service.brief("AMD", api_key="test-key")

    assert brief.news_confidence == 45
    assert "company IR" in brief.neutral_contextual_evidence[-1]


async def test_news_service_offline_fixture_run_builds_bundle_end_to_end() -> None:
    fixture_dir = Path(__file__).parent / "fixtures" / "news"
    provider = FixtureProvider(
        responses={
            ("news", '"Advanced Micro Devices" AMD news'): [
                SearchResult(
                    query="news",
                    title="AMD product launch",
                    url=(fixture_dir / "amd_product_launch.html").resolve().as_uri(),
                    snippet="AMD expands accelerator roadmap",
                    source="Fixture News",
                )
            ],
            ("news", '"Advanced Micro Devices" AMD earnings preview'): [
                SearchResult(
                    query="preview",
                    title="Sector demand context",
                    url=(fixture_dir / "semi_sector_demand.html").resolve().as_uri(),
                    snippet="Semiconductor demand remains constructive",
                    source="Fixture Sector",
                )
            ],
            ("text", '"Advanced Micro Devices" investor relations'): [
                SearchResult(
                    query="ir",
                    title="Investor relations update",
                    url=(fixture_dir / "amd_ir_release.html").resolve().as_uri(),
                    snippet="AMD schedules its earnings call",
                    source="Fixture IR",
                )
            ],
        }
    )
    service = NewsService(
        search=NewsSearchService(provider=provider, max_results_per_query=3, min_primary_results=3),
        fetcher=ArticleFetcher(),
        summarizer=NewsSummarizer(
            router=FakeRouter(
                response_text=(
                    '{"bullish_evidence":["New accelerator roadmap supports sentiment"],'
                    '"bearish_evidence":["Higher expectations raise the bar for guidance"],'
                    '"neutral_contextual_evidence":["Sector demand remains constructive"],'
                    '"key_uncertainty":'
                    '"Execution on large customer deployments still needs proof.",'
                    '"news_confidence":68}'
                )
            )
        ),
        cache=None,
    )

    bundle = await service.bundle(
        "AMD",
        company_name="Advanced Micro Devices",
        api_key="test-key",
    )

    assert bundle.ticker == "AMD"
    assert bundle.used_ir_fallback is True
    assert len(bundle.search_results) == 3
    assert len(bundle.articles) == 3
    assert bundle.brief.bullish_evidence == ["New accelerator roadmap supports sentiment"]
    assert bundle.brief.news_confidence == 68


def _search_response() -> SearchResponse:
    return SearchResponse(
        ticker="AMD",
        company_name="Advanced Micro Devices",
        primary_results=(
            SearchResult(
                query="news",
                title="Primary article",
                url="https://example.com/amd-primary",
                snippet="snippet",
                source="Example",
            ),
        ),
        fallback_results=(),
    )


def _article(title: str, *, is_ir_fallback: bool = False) -> NewsArticle:
    return NewsArticle(
        title=title,
        url="https://example.com/article",
        snippet="snippet",
        content=(
            "This article discusses AMD demand trends, guidance expectations, margin "
            "questions, and broader semiconductor sentiment in enough detail to "
            "support a structured news summary."
        ),
        source="example.com",
        published_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        is_ir_fallback=is_ir_fallback,
    )
