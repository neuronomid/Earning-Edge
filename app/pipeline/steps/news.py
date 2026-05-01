from __future__ import annotations

from typing import Protocol

from app.services.candidate_models import CandidateRecord
from app.services.news.service import NewsService, get_news_service
from app.services.news.types import NewsBundle


class NewsStep(Protocol):
    async def execute(
        self,
        record: CandidateRecord,
        *,
        openrouter_api_key: str,
    ) -> NewsBundle: ...


class NewsBriefStep:
    def __init__(self, service: NewsService | None = None) -> None:
        self.service = service or get_news_service()

    async def execute(
        self,
        record: CandidateRecord,
        *,
        openrouter_api_key: str,
    ) -> NewsBundle:
        return await self.service.bundle(
            record.ticker,
            company_name=record.company_name,
            api_key=openrouter_api_key,
        )
