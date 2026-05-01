from __future__ import annotations

from dataclasses import dataclass

from app.llm.schemas import StructuredDecision
from app.scoring.types import CandidateContext, CandidateEvaluation
from app.services.candidate_models import CandidateBatch, CandidateRecord
from app.services.news.types import NewsBundle
from app.services.sizing_types import SizingResult


@dataclass(slots=True, frozen=True)
class PipelineCandidate:
    record: CandidateRecord
    context: CandidateContext
    evaluation: CandidateEvaluation
    news_bundle: NewsBundle
    sizing: SizingResult | None


@dataclass(slots=True, frozen=True)
class PipelineOutcome:
    batch: CandidateBatch
    decision: StructuredDecision
    candidates: tuple[PipelineCandidate, ...]
    selected: PipelineCandidate | None
