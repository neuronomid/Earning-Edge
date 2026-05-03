from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Protocol

from app.core.logging import get_logger
from app.services.news.fetcher import ArticleFetcher
from app.services.news.search import NewsSearchService
from app.services.news.summarizer import NewsSummarizer
from app.services.news.types import NewsArticle, NewsBrief, NewsBundle, SearchResponse
from app.services.run_lock import get_redis_client


class SearchClient(Protocol):
    async def search_ticker(
        self,
        ticker: str,
        *,
        company_name: str | None = None,
    ) -> SearchResponse: ...


class ArticleClient(Protocol):
    async def fetch_many(
        self,
        results: tuple[Any, ...] | list[Any],
        *,
        limit: int | None = None,
    ) -> tuple[NewsArticle, ...]: ...


class BriefSummarizer(Protocol):
    async def summarize(
        self,
        *,
        ticker: str,
        company_name: str | None = None,
        articles: tuple[NewsArticle, ...] | list[NewsArticle],
        api_key: str,
    ) -> NewsBrief: ...


class BundleCache(Protocol):
    async def load(self, ticker: str) -> NewsBundle | None: ...

    async def store(self, bundle: NewsBundle) -> None: ...


class NewsBundleCache:
    def __init__(
        self,
        client: Any,
        *,
        key_prefix: str = "news",
        ttl_seconds: int = 7200,
    ) -> None:
        self.client = client
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds

    async def load(self, ticker: str) -> NewsBundle | None:
        payload = await self.client.get(self.key_for(ticker))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return NewsBundle.model_validate_json(payload)

    async def store(self, bundle: NewsBundle) -> None:
        await self.client.set(
            self.key_for(bundle.ticker),
            bundle.model_dump_json(),
            ex=self.ttl_seconds,
        )

    def key_for(self, ticker: str) -> str:
        return f"{self.key_prefix}:{ticker.strip().upper()}"


class NewsService:
    def __init__(
        self,
        *,
        search: SearchClient | None = None,
        fetcher: ArticleClient | None = None,
        summarizer: BriefSummarizer | None = None,
        cache: BundleCache | None = None,
        default_api_key: str | None = None,
        max_articles: int = 6,
        logger: Any | None = None,
    ) -> None:
        self.search = search or NewsSearchService()
        self.fetcher = fetcher or ArticleFetcher()
        self.summarizer = summarizer or NewsSummarizer()
        self.cache = cache
        self.default_api_key = default_api_key
        self.max_articles = max_articles
        self.logger = logger or get_logger(__name__)

    async def brief(
        self,
        ticker: str,
        *,
        company_name: str | None = None,
        api_key: str | None = None,
        refresh: bool = False,
    ) -> NewsBrief:
        return (
            await self.bundle(
                ticker,
                company_name=company_name,
                api_key=api_key,
                refresh=refresh,
            )
        ).brief

    async def bundle(
        self,
        ticker: str,
        *,
        company_name: str | None = None,
        api_key: str | None = None,
        refresh: bool = False,
    ) -> NewsBundle:
        normalized = ticker.strip().upper()
        if not normalized:
            raise ValueError("ticker is required")

        if self.cache is not None and not refresh:
            cached = await self.cache.load(normalized)
            if cached is not None:
                return cached

        search_response = await self.search.search_ticker(normalized, company_name=company_name)
        articles = await self.fetcher.fetch_many(
            search_response.all_results,
            limit=self.max_articles,
        )
        used_llm_summary = False

        if not articles:
            brief = _empty_brief(search_response)
        else:
            resolved_api_key = (api_key or self.default_api_key or "").strip()
            if not resolved_api_key:
                raise ValueError("api_key is required when news articles are available")
            brief = await self.summarizer.summarize(
                ticker=normalized,
                company_name=company_name,
                articles=articles,
                api_key=resolved_api_key,
            )
            used_llm_summary = True
            brief = _apply_coverage_policy(
                brief,
                search_response=search_response,
                articles=articles,
            )

        bundle = NewsBundle(
            ticker=normalized,
            company_name=company_name,
            generated_at=datetime.now(tz=UTC),
            search_results=search_response.all_results,
            articles=articles,
            brief=brief,
            used_ir_fallback=bool(search_response.fallback_results),
            used_llm_summary=used_llm_summary,
        )
        if self.cache is not None:
            await self.cache.store(bundle)
        return bundle


def _empty_brief(search_response: SearchResponse) -> NewsBrief:
    note = (
        "Search results were thin and leaned on company IR pages."
        if search_response.fallback_results
        else "Recent company-specific reporting was sparse."
    )
    return NewsBrief(
        bullish_evidence=[],
        bearish_evidence=[],
        neutral_contextual_evidence=[note],
        key_uncertainty=(
            "There was not enough recent, independent coverage to form a strong catalyst view."
        ),
        news_confidence=25,
    )


def _apply_coverage_policy(
    brief: NewsBrief,
    *,
    search_response: SearchResponse,
    articles: tuple[NewsArticle, ...],
) -> NewsBrief:
    confidence_cap = 100
    coverage_note: str | None = None

    if len(articles) == 1:
        confidence_cap = min(confidence_cap, 45)
        coverage_note = "Only one usable article was available, so news confidence is capped."
    elif len(articles) == 2:
        confidence_cap = min(confidence_cap, 60)
        coverage_note = "Only two usable articles were available, so news confidence is capped."

    if search_response.fallback_results and not search_response.primary_results:
        confidence_cap = min(confidence_cap, 50)
        coverage_note = "Coverage leaned entirely on company IR or press-release pages."
    elif search_response.fallback_results:
        confidence_cap = min(confidence_cap, 70)
        coverage_note = "Coverage was thin enough to require company IR fallback results."

    adjusted_confidence = min(brief.news_confidence, confidence_cap)
    neutral_evidence = list(brief.neutral_contextual_evidence)
    if coverage_note is not None and coverage_note not in neutral_evidence:
        neutral_evidence.append(coverage_note)

    return brief.model_copy(
        update={
            "neutral_contextual_evidence": neutral_evidence,
            "news_confidence": adjusted_confidence,
        }
    )


@lru_cache(maxsize=1)
def get_news_service() -> NewsService:
    return NewsService(cache=NewsBundleCache(get_redis_client()))
