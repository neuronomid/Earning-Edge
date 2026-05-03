from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SearchResult(_FrozenModel):
    query: str
    title: str
    url: str
    snippet: str = ""
    source: str | None = None
    published_at: datetime | None = None
    is_ir_fallback: bool = False


class SearchResponse(_FrozenModel):
    ticker: str
    company_name: str | None = None
    primary_results: tuple[SearchResult, ...] = ()
    fallback_results: tuple[SearchResult, ...] = ()

    @property
    def all_results(self) -> tuple[SearchResult, ...]:
        return self.primary_results + self.fallback_results


class NewsArticle(_FrozenModel):
    title: str
    url: str
    snippet: str = ""
    content: str
    source: str | None = None
    published_at: datetime | None = None
    is_ir_fallback: bool = False


class NewsBrief(_FrozenModel):
    bullish_evidence: list[str] = Field(default_factory=list)
    bearish_evidence: list[str] = Field(default_factory=list)
    neutral_contextual_evidence: list[str] = Field(default_factory=list)
    key_uncertainty: str
    news_confidence: int = Field(ge=0, le=100)


class NewsBundle(_FrozenModel):
    ticker: str
    company_name: str | None = None
    generated_at: datetime
    search_results: tuple[SearchResult, ...] = ()
    articles: tuple[NewsArticle, ...] = ()
    brief: NewsBrief
    used_ir_fallback: bool = False
    used_llm_summary: bool = False
