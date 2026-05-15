from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.news.fetcher import ArticleFetcher
from app.services.news.search import NewsSearchService
from app.services.news.sources import FinnhubNewsSource, SecEdgarNewsSource
from app.services.news.summarizer import NewsSummarizer, SummarizeOutcome
from app.services.news.types import (
    NewsArticle,
    NewsBrief,
    NewsBriefStatus,
    NewsBundle,
    NewsCoverage,
    SearchResponse,
)
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


class StructuredSource(Protocol):
    async def fetch_ticker(
        self,
        ticker: str,
        *,
        company_name: str | None = None,
        as_of_date: date | None = None,
    ) -> tuple[NewsArticle, ...]: ...


class BriefSummarizer(Protocol):
    async def summarize(
        self,
        *,
        ticker: str,
        company_name: str | None = None,
        articles: tuple[NewsArticle, ...] | list[NewsArticle],
        api_key: str,
    ) -> "SummarizeOutcome": ...


class BundleCache(Protocol):
    async def load(self, key: str) -> NewsBundle | None: ...

    async def store(self, key: str, bundle: NewsBundle) -> None: ...


_NEWS_BUNDLE_CACHE_VERSION = "v3"


def article_set_hash(articles: Sequence[NewsArticle]) -> str:
    """Stable hash of (url, published_at) over the given articles, sort-independent."""
    payload = "\n".join(
        f"{a.url}|{a.published_at.isoformat() if a.published_at is not None else ''}"
        for a in sorted(articles, key=lambda x: x.url)
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class NewsBundleCache:
    def __init__(
        self,
        client: Any,
        *,
        key_prefix: str = "news_brief",
        ttl_seconds: int | None = None,
        version: str = _NEWS_BUNDLE_CACHE_VERSION,
    ) -> None:
        self.client = client
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds
        self.version = version

    async def load(self, key: str) -> NewsBundle | None:
        payload = await self.client.get(key)
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return NewsBundle.model_validate_json(payload)

    async def store(self, key: str, bundle: NewsBundle) -> None:
        # ex=None is "no expiry" in redis-py; honors hashing-driven invalidation.
        await self.client.set(key, bundle.model_dump_json(), ex=self.ttl_seconds)

    def key_for(
        self,
        ticker: str,
        article_hash: str,
        prompt_version: str,
        schema_version: str,
    ) -> str:
        return (
            f"{self.key_prefix}:{prompt_version}:{schema_version}:"
            f"{ticker.strip().upper()}:{article_hash}"
        )


class NewsService:
    def __init__(
        self,
        *,
        structured_sources: tuple[StructuredSource, ...] | list[StructuredSource] | None = None,
        search: SearchClient | None = None,
        fetcher: ArticleClient | None = None,
        summarizer: BriefSummarizer | None = None,
        cache: BundleCache | None = None,
        default_api_key: str | None = None,
        max_articles: int = 8,
        min_structured_articles: int = 3,
        logger: Any | None = None,
    ) -> None:
        settings = get_settings()
        self.structured_sources = tuple(
            structured_sources
            if structured_sources is not None
            else (
                FinnhubNewsSource(
                    api_key=settings.finnhub_api_key,
                    lookback_days=settings.finnhub_news_lookback_days,
                ),
                SecEdgarNewsSource(user_agent=settings.sec_edgar_user_agent),
            )
        )
        self.search = search or NewsSearchService()
        self.fetcher = fetcher or ArticleFetcher()
        self.summarizer = summarizer or NewsSummarizer()
        self.cache = cache
        self.default_api_key = default_api_key
        self.max_articles = max_articles
        self.min_structured_articles = min_structured_articles
        self.logger = logger or get_logger(__name__)

    async def brief(
        self,
        ticker: str,
        *,
        company_name: str | None = None,
        api_key: str | None = None,
        refresh: bool = False,
        reference_dt: datetime | None = None,
    ) -> NewsBrief:
        return (
            await self.bundle(
                ticker,
                company_name=company_name,
                api_key=api_key,
                refresh=refresh,
                reference_dt=reference_dt,
            )
        ).brief

    async def bundle(
        self,
        ticker: str,
        *,
        company_name: str | None = None,
        api_key: str | None = None,
        refresh: bool = False,
        reference_dt: datetime | None = None,
    ) -> NewsBundle:
        normalized = ticker.strip().upper()
        if not normalized:
            raise ValueError("ticker is required")

        effective_reference_dt = reference_dt or datetime.now(tz=UTC)
        settings = get_settings()

        articles, search_response = await self._collect_articles(
            normalized,
            company_name=company_name,
            reference_dt=effective_reference_dt,
        )

        cache_key: str | None = None
        if self.cache is not None:
            cache_key = self.cache.key_for(
                normalized,
                article_set_hash(articles),
                settings.news_prompt_version,
                settings.news_brief_schema_version,
            )
            if not refresh:
                cached = await self.cache.load(cache_key)
                if cached is not None:
                    self.logger.info(
                        "news_bundle_cache_hit",
                        ticker=normalized,
                        article_count=len(cached.articles),
                        cache_key=cache_key,
                    )
                    return cached
                self.logger.info(
                    "news_bundle_cache_miss",
                    ticker=normalized,
                    cache_key=cache_key,
                )

        used_llm_summary = False
        brief_status: NewsBriefStatus = "skipped"
        if not articles:
            brief = _empty_brief(search_response)
            brief_status = "unavailable"
        else:
            resolved_api_key = (api_key or self.default_api_key or "").strip()
            if not resolved_api_key:
                raise ValueError("api_key is required when news articles are available")
            outcome = await self.summarizer.summarize(
                ticker=normalized,
                company_name=company_name,
                articles=articles,
                api_key=resolved_api_key,
            )
            brief = outcome.brief
            brief_status = outcome.status
            used_llm_summary = brief_status == "ok"

        # news_coverage reflects article evidence we actually fetched. It is
        # purely deterministic — do not coerce it to "none" just because the
        # summary model failed. Article presence is the truth for downstream
        # blackout gates; brief_status carries the summary-quality signal
        # separately.
        news_coverage = _compute_news_coverage(articles)
        stale_news = _compute_stale_news(articles, reference_dt=effective_reference_dt)

        bundle = NewsBundle(
            ticker=normalized,
            company_name=company_name,
            generated_at=effective_reference_dt,
            search_results=search_response.all_results,
            articles=articles,
            brief=brief,
            used_ir_fallback=bool(search_response.fallback_results),
            used_llm_summary=used_llm_summary,
            news_coverage=news_coverage,
            stale_news=stale_news,
            brief_status=brief_status,
        )
        self.logger.info(
            "news_bundle_built",
            ticker=normalized,
            article_count=len(articles),
            search_result_count=len(search_response.all_results),
            used_ir_fallback=bundle.used_ir_fallback,
            used_llm_summary=used_llm_summary,
        )
        if self.cache is not None and cache_key is not None:
            await self.cache.store(cache_key, bundle)
        return bundle

    async def _collect_articles(
        self,
        ticker: str,
        *,
        company_name: str | None,
        reference_dt: datetime,
    ) -> tuple[tuple[NewsArticle, ...], SearchResponse]:
        structured = await self._load_structured_articles(
            ticker,
            company_name=company_name,
            reference_dt=reference_dt,
        )
        if len(structured) >= self.min_structured_articles:
            return structured[: self.max_articles], SearchResponse(
                ticker=ticker,
                company_name=company_name,
            )

        fallback_articles, search_response = await self._load_fallback_articles(
            ticker,
            company_name=company_name,
        )
        merged = _rank_and_dedupe_articles(
            (*structured, *fallback_articles),
            ticker=ticker,
            company_name=company_name,
            reference_dt=reference_dt,
        )
        return merged[: self.max_articles], search_response

    async def _load_structured_articles(
        self,
        ticker: str,
        *,
        company_name: str | None,
        reference_dt: datetime,
    ) -> tuple[NewsArticle, ...]:
        fetched = await self._gather_structured_articles(
            ticker,
            company_name=company_name,
            reference_dt=reference_dt,
        )
        return _rank_and_dedupe_articles(
            fetched,
            ticker=ticker,
            company_name=company_name,
            reference_dt=reference_dt,
        )

    async def _gather_structured_articles(
        self,
        ticker: str,
        *,
        company_name: str | None,
        reference_dt: datetime,
    ) -> tuple[NewsArticle, ...]:
        if not self.structured_sources:
            return ()
        as_of = reference_dt.date()
        collected = await asyncio.gather(
            *[
                source.fetch_ticker(
                    ticker, company_name=company_name, as_of_date=as_of
                )
                for source in self.structured_sources
            ],
            return_exceptions=True,
        )
        articles: list[NewsArticle] = []
        per_source_counts: dict[str, int] = {}
        for source, payload in zip(self.structured_sources, collected, strict=True):
            source_name = type(source).__name__
            if isinstance(payload, BaseException):
                self.logger.warning(
                    "structured_news_source_failed",
                    ticker=ticker,
                    source=source_name,
                    error=str(payload),
                )
                per_source_counts[source_name] = -1
                continue
            per_source_counts[source_name] = len(payload)
            articles.extend(payload)
        self.logger.info(
            "structured_news_collected",
            ticker=ticker,
            per_source_counts=per_source_counts,
            total_articles=len(articles),
        )
        return tuple(articles)

    async def _load_fallback_articles(
        self,
        ticker: str,
        *,
        company_name: str | None,
    ) -> tuple[tuple[NewsArticle, ...], SearchResponse]:
        try:
            fallback_response = await self.search.search_ticker(
                ticker,
                company_name=company_name,
            )
        except Exception as exc:
            self.logger.warning(
                "news_fallback_search_failed",
                ticker=ticker,
                error=str(exc),
            )
            return (), SearchResponse(ticker=ticker, company_name=company_name)

        return (
            await self.fetcher.fetch_many(
                fallback_response.all_results,
                limit=self.max_articles,
            ),
            fallback_response,
        )


def _empty_brief(search_response: SearchResponse) -> NewsBrief:
    note = (
        "Search results were thin and leaned on company IR pages."
        if search_response.fallback_results
        else "Recent company-specific reporting was sparse."
    )
    return NewsBrief(
        neutral_contextual_evidence=[note],
        key_uncertainty=(
            "There was not enough recent, independent coverage to form a strong catalyst view."
        ),
    )


@lru_cache(maxsize=1)
def get_news_service() -> NewsService:
    return NewsService(cache=NewsBundleCache(get_redis_client()))


_STALE_NEWS_THRESHOLD_DAYS = 14


def _compute_news_coverage(articles: tuple[NewsArticle, ...]) -> NewsCoverage:
    if not articles:
        return "none"
    if len(articles) <= 2:
        return "sparse"
    distinct_sources = {(a.source or "").strip().lower() for a in articles if a.source}
    distinct_sources.discard("")
    if len(distinct_sources) >= 3:
        return "rich"
    return "adequate"


def _compute_stale_news(
    articles: tuple[NewsArticle, ...], *, reference_dt: datetime
) -> bool:
    published = [a.published_at for a in articles if a.published_at is not None]
    if not published:
        return False
    most_recent = max(published)
    return (reference_dt - most_recent).days > _STALE_NEWS_THRESHOLD_DAYS


def _rank_and_dedupe_articles(
    articles: tuple[NewsArticle, ...] | list[NewsArticle],
    *,
    ticker: str,
    company_name: str | None,
    reference_dt: datetime,
) -> tuple[NewsArticle, ...]:
    ranked = sorted(
        articles,
        key=lambda article: _article_sort_key(
            article,
            ticker=ticker,
            company_name=company_name,
            reference_dt=reference_dt,
        ),
    )
    deduped: list[NewsArticle] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for article in ranked:
        dedupe_key = _article_dedupe_key(article)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        deduped.append(article)
    return tuple(deduped)


def _article_sort_key(
    article: NewsArticle,
    *,
    ticker: str,
    company_name: str | None,
    reference_dt: datetime,
) -> tuple[int, int, str, str, str]:
    published_at = article.published_at or datetime(1970, 1, 1, tzinfo=UTC)
    return (
        -_article_priority(
            article,
            ticker=ticker,
            company_name=company_name,
            reference_dt=reference_dt,
        ),
        -int(published_at.timestamp()),
        (article.source or "").lower(),
        _normalized_url(article.url),
        article.title.lower(),
    )


def _article_priority(
    article: NewsArticle,
    *,
    ticker: str,
    company_name: str | None,
    reference_dt: datetime,
) -> int:
    title = article.title.lower()
    summary = f"{article.snippet} {article.content[:400]}".lower()
    title_direct = _contains_company_reference(title, ticker=ticker, company_name=company_name)
    summary_direct = _contains_company_reference(summary, ticker=ticker, company_name=company_name)

    score = 0
    if title_direct:
        score += 90
    elif summary_direct:
        score += 55
    else:
        score -= 35

    score += _recency_score(article.published_at, reference_dt=reference_dt)
    score += _source_quality_score(article)
    if _is_thesis_changing(article):
        score += 35
    if article.is_ir_fallback:
        score -= 15
    return score


def _recency_score(published_at: datetime | None, *, reference_dt: datetime) -> int:
    if published_at is None:
        return 0
    age_days = max((reference_dt - published_at).days, 0)
    if age_days <= 7:
        return 80
    if age_days <= 30:
        return 45
    if age_days <= 120:
        return 15
    return 0


def _source_quality_score(article: NewsArticle) -> int:
    source = (article.source or "").lower()
    url = article.url.lower()
    if "sec edgar" in source or "sec.gov" in url:
        return 45
    if any(token in source for token in ("reuters", "cnbc", "bloomberg", "wsj", "marketwatch")):
        return 25
    if article.is_ir_fallback:
        return 10
    return 18


def _is_thesis_changing(article: NewsArticle) -> bool:
    haystack = f"{article.title} {article.snippet} {article.content[:400]}".lower()
    terms = (
        "earnings",
        "guidance",
        "acquisition",
        "merger",
        "lawsuit",
        "investigation",
        "downgrade",
        "upgrade",
        "target",
        "launch",
        "restructuring",
        "contract",
        "customer",
        "buyback",
        "dividend",
        "silicon one",
    )
    return any(term in haystack for term in terms)


def _contains_company_reference(
    text: str,
    *,
    ticker: str,
    company_name: str | None,
) -> bool:
    normalized_ticker = ticker.strip().lower()
    if normalized_ticker and normalized_ticker in text.split():
        return True
    if normalized_ticker and f"({normalized_ticker})" in text:
        return True

    for token in _company_tokens(company_name):
        if token in text:
            return True
    return False


def _company_tokens(company_name: str | None) -> tuple[str, ...]:
    if not company_name:
        return ()
    raw = company_name.lower()
    cleaned = "".join(char if char.isalnum() or char.isspace() else " " for char in raw)
    blocked = {
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "company",
        "co",
        "systems",
        "group",
        "holdings",
        "limited",
        "ltd",
        "plc",
    }
    tokens = [
        token
        for token in cleaned.split()
        if len(token) >= 4 and token not in blocked
    ]
    return tuple(tokens)


def _article_dedupe_key(article: NewsArticle) -> tuple[str, str, str]:
    published = (
        article.published_at.astimezone(UTC).isoformat()
        if article.published_at is not None
        else ""
    )
    normalized_url = _normalized_url(article.url)
    return (
        normalized_url,
        article.title.strip().lower(),
        published,
    )


def _normalized_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return url.strip().lower()
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _is_sec_article(article: NewsArticle) -> bool:
    source = (article.source or "").lower()
    return "sec edgar" in source or "sec.gov" in article.url.lower()
