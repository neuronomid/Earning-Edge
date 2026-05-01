from __future__ import annotations

from typing import Protocol

from app.services.candidate_models import CandidateBatch
from app.services.candidate_service import CandidateService, get_candidate_service


class CandidateStep(Protocol):
    async def execute(self) -> CandidateBatch: ...


class CandidateSelectionStep:
    def __init__(self, service: CandidateService | None = None) -> None:
        self.service = service or get_candidate_service()

    async def execute(self) -> CandidateBatch:
        return await self.service.get_top_five()
