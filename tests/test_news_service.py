from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
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
class FakeStructuredSource:
    articles: tuple[NewsArticle, ...]
    calls: int = 0

    async def fetch_ticker(
        self,
        ticker: str,
        *,
        company_name: str | None = None,
        as_of_date: date | None = None,
    ) -> tuple[NewsArticle, ...]:
        del ticker, company_name, as_of_date
        self.calls += 1
        return self.articles


@dataclass
class FakeRedis:
    values: dict[str, str] = field(default_factory=dict)
    ttl_by_key: dict[str, int | None] = field(default_factory=dict)

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
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
            neutral_contextual_evidence=["Sector demand is steady"],
            key_uncertainty="Guidance still matters.",
            summary="Backlog improved across the data center segment.",
            key_facts=["Order backlog up double digits year-over-year."],
        )
    )
    redis = FakeRedis()
    service = NewsService(
        structured_sources=(),
        search=search,
        fetcher=fetcher,
        summarizer=summarizer,
        cache=NewsBundleCache(redis, ttl_seconds=3600),
    )

    first = await service.bundle("amd", api_key="test-key")
    second = await service.bundle("AMD", api_key="test-key")

    assert first == second
    # Articles are now fetched on every call (cache key needs them) but the
    # Gemini summarizer is called only once thanks to content-addressed caching.
    assert search.calls["AMD"] == 2
    assert fetcher.calls == 2
    assert summarizer.calls == 1


async def test_news_service_returns_low_confidence_brief_when_no_articles_are_available() -> None:
    service = NewsService(
        structured_sources=(),
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
                neutral_contextual_evidence=[],
                key_uncertainty="unused",
                summary="Should not be used.",
            )
        ),
        cache=None,
    )

    brief = await service.brief("AMD")

    assert brief.summary == ""
    assert brief.neutral_contextual_evidence == ["Recent company-specific reporting was sparse."]


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
        structured_sources=(),
        search=NewsSearchService(provider=provider, max_results_per_query=3, min_primary_results=3),
        fetcher=ArticleFetcher(),
        summarizer=NewsSummarizer(
            router=FakeRouter(
                response_text=(
                    '{"neutral_contextual_evidence":["Sector demand remains constructive"],'
                    '"key_uncertainty":'
                    '"Execution on large customer deployments still needs proof.",'
                    '"summary":"New accelerator roadmap supports sentiment.",'
                    '"key_facts":["Roadmap update extends product cycle by twelve months."],'
                    '"quoted_statements":[],'
                    '"named_actions":[]}'
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
    assert bundle.brief.summary == "New accelerator roadmap supports sentiment."
    assert bundle.brief.key_facts == ["Roadmap update extends product cycle by twelve months."]


async def test_news_service_prefers_structured_sources_before_open_web_fallback() -> None:
    structured = FakeStructuredSource(
        articles=(
            _article(
                "Cisco Stock Finds New Growth In AI Infrastructure",
                snippet="Cisco kept showing direct AI demand momentum ahead of earnings.",
            ),
            _article(
                "Cisco Systems 8-K filed on 2026-05-01",
                snippet="Official SEC filing.",
                source="SEC EDGAR",
                url="https://www.sec.gov/Archives/edgar/data/858877/filing.htm",
            ),
            _article(
                "Evercore ISI Says Cisco's Silicon One Is An Underappreciated Driver Of Upside",
                snippet="Cisco was named directly in the outlook update.",
            ),
        )
    )
    search = FakeSearchClient(response=_search_response())
    fetcher = FakeFetcher(articles=(_article("Should not be used"),))
    service = NewsService(
        structured_sources=(structured,),
        search=search,
        fetcher=fetcher,
        summarizer=FakeSummarizer(
            brief=NewsBrief(
                neutral_contextual_evidence=[],
                key_uncertainty="Need earnings confirmation.",
                summary="AI demand stayed supportive.",
                key_facts=["Backlog disclosure shows steady AI demand."],
            )
        ),
        cache=None,
    )

    bundle = await service.bundle("CSCO", company_name="Cisco Systems", api_key="test-key")

    assert structured.calls == 1
    assert search.calls["CSCO"] == 0
    assert fetcher.calls == 0
    assert len(bundle.articles) == 3
    assert {
        article.title for article in bundle.articles
    } == {
        "Cisco Stock Finds New Growth In AI Infrastructure",
        "Cisco Systems 8-K filed on 2026-05-01",
        "Evercore ISI Says Cisco's Silicon One Is An Underappreciated Driver Of Upside",
    }
    assert bundle.search_results == ()


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


def _article(
    title: str,
    *,
    snippet: str = "snippet",
    source: str = "example.com",
    url: str = "https://example.com/article",
    is_ir_fallback: bool = False,
) -> NewsArticle:
    return NewsArticle(
        title=title,
        url=url,
        snippet=snippet,
        content=(
            "This article discusses AMD demand trends, guidance expectations, margin "
            "questions, and broader semiconductor sentiment in enough detail to "
            "support a structured news summary."
        ),
        source=source,
        published_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        is_ir_fallback=is_ir_fallback,
    )
