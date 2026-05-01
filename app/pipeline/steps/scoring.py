from __future__ import annotations

from typing import Protocol

from app.scoring.final import score_candidate
from app.scoring.types import CandidateContext, CandidateEvaluation, UserContext


class ScoringStep(Protocol):
    async def execute(
        self,
        candidate: CandidateContext,
        user: UserContext,
    ) -> CandidateEvaluation: ...


class CandidateScoringStep:
    async def execute(
        self,
        candidate: CandidateContext,
        user: UserContext,
    ) -> CandidateEvaluation:
        return score_candidate(candidate, user)
