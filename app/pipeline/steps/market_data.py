from __future__ import annotations

from typing import Protocol

from app.services.candidate_models import CandidateRecord
from app.services.market_data.service import MarketDataService, get_market_data_service
from app.services.market_data.types import MarketSnapshot


class MarketDataStep(Protocol):
    async def execute(
        self,
        record: CandidateRecord,
        *,
        alpha_vantage_api_key: str | None,
    ) -> MarketSnapshot: ...


class MarketDataFetchStep:
    def __init__(self, service: MarketDataService | None = None) -> None:
        self.service = service or get_market_data_service()

    async def execute(
        self,
        record: CandidateRecord,
        *,
        alpha_vantage_api_key: str | None,
    ) -> MarketSnapshot:
        return await self.service.fetch(
            record.ticker,
            alpha_vantage_api_key=alpha_vantage_api_key,
        )
