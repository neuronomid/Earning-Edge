from __future__ import annotations

from typing import Protocol

from app.services.candidate_models import CandidateBatch
from app.services.multi_strategy_service import (
    MultiStrategyCandidateService,
    get_multi_strategy_service,
)


class CandidateStep(Protocol):
    async def execute(self) -> CandidateBatch: ...


class CandidateSelectionStep:
    def __init__(self, service: MultiStrategyCandidateService | None = None) -> None:
        self.service = service or get_multi_strategy_service()

    async def execute(self) -> CandidateBatch:
        return await self.service.get_candidates()
