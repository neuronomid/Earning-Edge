from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NewsCoverage = Literal["none", "sparse", "adequate", "rich"]


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
    neutral_contextual_evidence: list[str] = Field(default_factory=list)
    key_uncertainty: str
    summary: str = ""
    key_facts: list[str] = Field(default_factory=list)
    quoted_statements: list[str] = Field(default_factory=list)
    named_actions: list[str] = Field(default_factory=list)


class NewsBundle(_FrozenModel):
    ticker: str
    company_name: str | None = None
    generated_at: datetime
    search_results: tuple[SearchResult, ...] = ()
    articles: tuple[NewsArticle, ...] = ()
    brief: NewsBrief
    used_ir_fallback: bool = False
    used_llm_summary: bool = False
    news_coverage: NewsCoverage = "adequate"
    stale_news: bool = False
