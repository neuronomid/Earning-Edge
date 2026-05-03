from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.llm.schemas import StructuredDecision
from app.scoring.types import CandidateContext, CandidateEvaluation, ContractScoreResult
from app.services.candidate_models import CandidateBatch, CandidateRecord
from app.services.news.types import NewsBundle
from app.services.sizing_types import SizingResult

DecisionEngine = Literal["heuristic", "llm", "heuristic_fallback", "llm_blocked"]


@dataclass(slots=True, frozen=True)
class PipelineCandidate:
    record: CandidateRecord
    context: CandidateContext
    evaluation: CandidateEvaluation
    news_bundle: NewsBundle
    sizing: SizingResult | None


@dataclass(slots=True, frozen=True)
class DecisionTrace:
    engine: DecisionEngine
    heavy_model_used: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class DecisionStepResult:
    decision: StructuredDecision
    trace: DecisionTrace


@dataclass(slots=True, frozen=True)
class PipelineOutcome:
    batch: CandidateBatch
    decision: StructuredDecision
    candidates: tuple[PipelineCandidate, ...]
    selected: PipelineCandidate | None
    selected_contract: ContractScoreResult | None = None
    decision_trace: DecisionTrace = field(
        default_factory=lambda: DecisionTrace(engine="heuristic")
    )

    @property
    def final_contract(self) -> ContractScoreResult | None:
        if self.selected_contract is not None:
            return self.selected_contract
        if self.selected is None:
            return None
        return self.selected.evaluation.chosen_contract
