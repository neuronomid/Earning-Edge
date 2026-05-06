from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models.candidate import Candidate
from app.db.models.option_contract import OptionContract
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.repositories.candidate_repo import CandidateRepository
from app.db.repositories.contract_repo import OptionContractRepository
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.pipeline.steps.decide import (
    DecisionStep,
    get_default_decision_step,
    resolve_selected_contract,
)
from app.pipeline.steps.market_data import MarketDataFetchStep, MarketDataStep
from app.pipeline.steps.news import NewsBriefStep, NewsStep
from app.pipeline.types import PipelineCandidate
from app.scoring.final import combine_scores
from app.scoring.types import (
    CandidateContext,
    CandidateEvaluation,
    ContractScoreResult,
    DataConfidenceResult,
    DirectionResult,
    ExitTarget,
    HardVeto,
    OptionContractInput,
    StrategySelection,
    UserContext,
    option_premium,
)
from app.services.market_data.types import ConfidenceNote, MarketSnapshot, ReturnMetrics
from app.services.news.types import NewsBrief, NewsBundle
from app.services.sizing import (
    BROKER_MARGIN_DEPENDENT_TEXT,
    SizingError,
    SizingPermissionError,
    size,
)
from app.services.sizing_types import SizingResult
from app.services.user_service import decrypt_or_none

ZERO = Decimal("0")
FINALIST_LIMIT = 4


@dataclass(slots=True, frozen=True)
class AlternativeRecommendationResult:
    recommendation: Recommendation | None
    watchlist_only: bool = False
    rank_position: int | None = None
    message: str | None = None
    terminal: bool = False


class AlternativeRecommendationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        decision_step: DecisionStep | None = None,
        market_data_step: MarketDataStep | None = None,
        news_step: NewsStep | None = None,
    ) -> None:
        settings = get_settings()
        self.session = session
        self.candidates = CandidateRepository(session)
        self.contracts = OptionContractRepository(session)
        self.recommendations = RecommendationRepository(session)
        self.decision_step = decision_step or get_default_decision_step(settings=settings)
        self.market_data_step = market_data_step or MarketDataFetchStep()
        self.news_step = news_step or NewsBriefStep()
        self.app_env = settings.app_env

    async def build_next(
        self,
        *,
        user: User,
        current_recommendation: Recommendation,
    ) -> AlternativeRecommendationResult:
        shown = {
            recommendation.ticker
            for recommendation in await self.recommendations.list_for_run(
                current_recommendation.run_id
            )
        }
        next_rank_position = len(shown) + 1
        ranked = sorted(
            await self.candidates.list_for_run(current_recommendation.run_id),
            key=lambda candidate: (
                candidate.final_opportunity_score,
                candidate.data_confidence_score,
                candidate.candidate_direction_score,
            ),
            reverse=True,
        )[:FINALIST_LIMIT]

        for candidate in ranked:
            if candidate.ticker in shown:
                continue
            pipeline_candidate = await self._pipeline_candidate(candidate, user)
            if pipeline_candidate is None:
                shown.add(candidate.ticker)
                continue
            result = await self._decide_and_persist(
                user=user,
                current_recommendation=current_recommendation,
                candidate=pipeline_candidate,
                rank_position=next_rank_position,
            )
            if result.recommendation is not None or result.terminal:
                return result
            shown.add(candidate.ticker)

        return AlternativeRecommendationResult(
            recommendation=None,
            message="No additional qualified alternatives are available for this run.",
        )

    async def _pipeline_candidate(
        self,
        candidate: Candidate,
        user: User,
    ) -> PipelineCandidate | None:
        contracts = await self.contracts.list_for_candidate(candidate.id)
        scored_contracts = tuple(
            sorted(
                (_contract_score(contract) for contract in contracts),
                key=lambda result: (
                    result.is_viable,
                    result.score,
                    result.liquidity_score,
                ),
                reverse=True,
            )
        )
        chosen = next((contract for contract in scored_contracts if contract.is_viable), None)
        if chosen is None:
            return None

        record = _candidate_record(candidate)
        market_snapshot = await self._market_snapshot(candidate, record, user)
        news_bundle = await self._news_bundle(candidate, record, user)
        context = _candidate_context(candidate, scored_contracts, market_snapshot, news_bundle)
        evaluation = _candidate_evaluation(candidate, scored_contracts, chosen)
        return PipelineCandidate(
            record=record,
            context=context,
            evaluation=evaluation,
            news_bundle=news_bundle,
            sizing=None,
        )

    async def _market_snapshot(
        self,
        candidate: Candidate,
        record,
        user: User,
    ) -> MarketSnapshot:
        if self.app_env == "test":
            return _stored_market_snapshot(candidate)

        try:
            return await self.market_data_step.execute(
                record,
                alpha_vantage_api_key=decrypt_or_none(user.alpha_vantage_api_key_encrypted),
            )
        except Exception as exc:
            return _stored_market_snapshot(candidate, error=str(exc))

    async def _news_bundle(
        self,
        candidate: Candidate,
        record,
        user: User,
    ) -> NewsBundle:
        if self.app_env == "test":
            return _stored_news_bundle(candidate)

        try:
            return await self.news_step.execute(
                record,
                openrouter_api_key=decrypt_or_none(user.openrouter_api_key_encrypted) or "",
            )
        except Exception as exc:
            return _stored_news_bundle(candidate, error=str(exc))

    async def _decide_and_persist(
        self,
        *,
        user: User,
        current_recommendation: Recommendation,
        candidate: PipelineCandidate,
        rank_position: int,
    ) -> AlternativeRecommendationResult:
        user_context = _user_context(user)
        decision_result = await self.decision_step.execute(
            [candidate],
            user_context,
            openrouter_api_key=decrypt_or_none(user.openrouter_api_key_encrypted) or "",
        )
        decision = decision_result.decision
        if decision_result.trace.engine == "llm_blocked":
            return AlternativeRecommendationResult(
                recommendation=None,
                message=decision.reasoning,
                terminal=True,
            )
        if decision.action == "no_trade":
            return AlternativeRecommendationResult(
                recommendation=None,
            )

        selected_contract = resolve_selected_contract(candidate, decision.chosen_contract)
        if selected_contract is None:
            selected_contract = candidate.evaluation.chosen_contract
        if selected_contract is None:
            return AlternativeRecommendationResult(
                recommendation=None,
                message=f"{candidate.record.ticker} did not have a viable stored contract.",
            )

        sizing = _size_or_fallback(user_context, selected_contract.contract)
        quantity = 0 if decision.action == "watchlist" else sizing.quantity
        confidence_score = (
            decision.final_score
            if decision.final_score is not None
            else combine_scores(candidate.evaluation.direction.score, selected_contract.score)
        )
        exit_target = selected_contract.exit_target
        recommendation = await self.recommendations.add(
            Recommendation(
                user_id=user.id,
                run_id=current_recommendation.run_id,
                ticker=candidate.record.ticker,
                company_name=candidate.context.company_name,
                strategy=selected_contract.strategy,
                option_type=selected_contract.contract.option_type,
                position_side=selected_contract.contract.position_side,
                strike=selected_contract.contract.strike,
                expiry=selected_contract.contract.expiry,
                suggested_entry=option_premium(selected_contract.contract),
                target_stock_price=(
                    None if exit_target is None else exit_target.target_stock_price
                ),
                target_option_price=(
                    None if exit_target is None else exit_target.target_option_price
                ),
                target_gain_percent=(
                    None if exit_target is None else exit_target.target_gain_percent
                ),
                stop_loss_option_price=(
                    None if exit_target is None else exit_target.stop_loss_option_price
                ),
                exit_by_date=None if exit_target is None else exit_target.exit_by_date,
                expected_holding_days=(
                    None if exit_target is None else exit_target.expected_holding_days
                ),
                target_method=None if exit_target is None else exit_target.target_method,
                suggested_quantity=quantity,
                estimated_max_loss=sizing.max_loss_text,
                account_risk_percent=sizing.account_risk_pct * Decimal("100"),
                confidence_score=confidence_score,
                risk_level=_risk_level(selected_contract, confidence_score),
                reasoning_summary=decision.reasoning,
                key_evidence_json=decision.key_evidence,
                key_concerns_json=decision.key_concerns,
            )
        )
        recommendation.earnings_date = candidate.context.earnings_date
        return AlternativeRecommendationResult(
            recommendation=recommendation,
            watchlist_only=decision.action == "watchlist",
            rank_position=rank_position,
        )


def _candidate_record(candidate: Candidate):
    from app.services.candidate_models import CandidateRecord

    return CandidateRecord(
        ticker=candidate.ticker,
        company_name=candidate.company_name,
        market_cap=candidate.market_cap,
        earnings_date=candidate.earnings_date,
        current_price=candidate.current_price,
        sector=None,
        sources=("stored_run",),
        strategy_source=candidate.strategy_source,  # type: ignore[arg-type]
    )


def _candidate_context(
    candidate: Candidate,
    contracts: tuple[ContractScoreResult, ...],
    market_snapshot: MarketSnapshot,
    news_bundle: NewsBundle,
) -> CandidateContext:
    return CandidateContext(
        ticker=candidate.ticker,
        company_name=candidate.company_name,
        earnings_date=candidate.earnings_date,
        earnings_timing=candidate.earnings_timing or "unknown",
        market_snapshot=market_snapshot,
        news_brief=news_bundle.brief,
        option_chain=tuple(contract.contract for contract in contracts),
        verified_earnings_date=True,
        identity_verified=True,
    )


def _candidate_evaluation(
    candidate: Candidate,
    contracts: tuple[ContractScoreResult, ...],
    chosen: ContractScoreResult,
) -> CandidateEvaluation:
    direction = DirectionResult(
        classification=candidate.direction_classification,  # type: ignore[arg-type]
        bias=_direction_bias(candidate.direction_classification),
        score=candidate.candidate_direction_score,
        factors=(),
        reasons=(
            f"{candidate.ticker} stored direction score: "
            f"{candidate.candidate_direction_score}/100.",
        ),
    )
    confidence = DataConfidenceResult(
        score=candidate.data_confidence_score,
        label="stored",
        blockers=(),
        notes=("Alternative generated from the stored run artifacts.",),
    )
    strategies = tuple(dict.fromkeys(contract.strategy for contract in contracts))
    return CandidateEvaluation(
        ticker=candidate.ticker,
        direction=direction,
        confidence=confidence,
        strategy_selection=StrategySelection(
            allowed_strategies=strategies,
            preferred_order=strategies,
            reason="Stored option contracts from the original scan.",
        ),
        considered_contracts=contracts,
        chosen_contract=chosen,
        final_score=candidate.final_opportunity_score,
        action=_stored_action(candidate.final_opportunity_score, confidence, chosen),
        reasons=(
            f"{candidate.ticker} stored final score: "
            f"{candidate.final_opportunity_score}/100.",
        ),
    )


def _contract_score(contract: OptionContract) -> ContractScoreResult:
    option = OptionContractInput(
        ticker=contract.ticker,
        option_type=contract.option_type,  # type: ignore[arg-type]
        position_side=contract.position_side,  # type: ignore[arg-type]
        strike=contract.strike,
        expiry=contract.expiry,
        bid=contract.bid,
        ask=contract.ask,
        mid=contract.mid,
        volume=contract.volume,
        open_interest=contract.open_interest,
        implied_volatility=contract.implied_volatility,
        delta=contract.delta,
        gamma=contract.gamma,
        theta=contract.theta,
        vega=contract.vega,
        source="stored_run",
    )
    vetoes = ()
    if not contract.passed_hard_filters:
        vetoes = (
            HardVeto(
                "stored_rejection",
                contract.rejection_reason or "Stored contract failed hard filters.",
            ),
        )
    return ContractScoreResult(
        strategy=option.strategy,
        contract=option,
        base_score=contract.contract_opportunity_score,
        score=contract.contract_opportunity_score if contract.passed_hard_filters else 0,
        factors=(),
        penalties=(),
        vetoes=vetoes,
        breakeven=contract.breakeven,
        breakeven_move_percent=None,
        liquidity_score=contract.liquidity_score,
        expiry_days_after_earnings=None,
        reasons=(f"Stored contract score: {contract.contract_opportunity_score}/100.",),
        exit_target=(
            None
            if contract.target_method is None
            or contract.target_stock_price is None
            or contract.target_option_price is None
            or contract.stop_loss_option_price is None
            or contract.exit_by_date is None
            or contract.expected_holding_days is None
            else ExitTarget(
                target_stock_price=contract.target_stock_price,
                target_option_price=contract.target_option_price,
                target_gain_percent=contract.target_gain_percent,
                stop_loss_option_price=contract.stop_loss_option_price,
                exit_by_date=contract.exit_by_date,
                expected_holding_days=contract.expected_holding_days,
                target_method=contract.target_method,  # type: ignore[arg-type]
            )
        ),
    )


def _stored_market_snapshot(candidate: Candidate, *, error: str | None = None) -> MarketSnapshot:
    return MarketSnapshot(
        ticker=candidate.ticker,
        as_of_date=candidate.earnings_date,
        company_name=candidate.company_name,
        sector=None,
        sector_etf=None,
        market_cap=candidate.market_cap,
        current_price=candidate.current_price,
        latest_volume=None,
        average_volume_20d=None,
        volume_vs_average_20d=None,
        stock_returns=ReturnMetrics(None, None, None, None),
        spy_returns=ReturnMetrics(None, None, None, None),
        qqq_returns=ReturnMetrics(None, None, None, None),
        sector_returns=None,
        relative_strength_vs_spy=None,
        relative_strength_vs_qqq=None,
        relative_strength_vs_sector=None,
        av_news_sentiment=None,
        price_source="stored_run",
        overview_source="stored_run",
        sources=("stored_run",),
        confidence_adjustment=0 if error is None else -10,
        confidence_notes=()
        if error is None
        else (
            ConfidenceNote(
                source="alternative",
                field="market_data",
                detail=f"Fresh alternative market data was unavailable: {error}",
                severity="warning",
                score_delta=-10,
            ),
        ),
    )


def _stored_news_bundle(candidate: Candidate, *, error: str | None = None) -> NewsBundle:
    return NewsBundle(
        ticker=candidate.ticker,
        company_name=candidate.company_name,
        generated_at=datetime.now(tz=UTC),
        search_results=(),
        articles=(),
        brief=NewsBrief(
            bullish_evidence=[],
            bearish_evidence=[],
            neutral_contextual_evidence=[
                f"Stored alternative candidate ranked {candidate.final_opportunity_score}/100."
            ],
            key_uncertainty=error or "Fresh news was not re-fetched for this alternative.",
            news_confidence=candidate.data_confidence_score,
        ),
        used_ir_fallback=False,
        used_llm_summary=False,
    )


def _user_context(user: User) -> UserContext:
    return UserContext(
        account_size=user.account_size,
        risk_profile=user.risk_profile,  # type: ignore[arg-type]
        strategy_permission=user.strategy_permission,  # type: ignore[arg-type]
        max_contracts=user.max_contracts,
        has_valid_openrouter_api_key=bool(
            decrypt_or_none(user.openrouter_api_key_encrypted)
        ),
    )


def _size_or_fallback(user: UserContext, contract: OptionContractInput) -> SizingResult:
    try:
        return size(user, contract)
    except (SizingError, SizingPermissionError):
        return SizingResult(
            quantity=0,
            max_loss_text=(
                BROKER_MARGIN_DEPENDENT_TEXT
                if contract.position_side == "short"
                else "Sizing unavailable."
            ),
            account_risk_pct=ZERO,
            broker_verification_required=True,
            watch_only=True,
        )


def _stored_action(
    final_score: int,
    confidence: DataConfidenceResult,
    chosen: ContractScoreResult | None,
) -> str:
    if chosen is None or confidence.blockers or confidence.score < 40:
        return "no_trade"
    if confidence.score < 55:
        return "watchlist" if final_score >= 60 else "no_trade"
    if final_score >= 68:
        return "recommend"
    if final_score >= 60:
        return "watchlist"
    return "no_trade"


def _direction_bias(classification: str) -> Decimal:
    if classification == "bullish":
        return Decimal("0.60")
    if classification == "bearish":
        return Decimal("-0.60")
    return ZERO


def _risk_level(contract: ContractScoreResult, final_score: int) -> str:
    if contract.contract.position_side == "short":
        return "High"
    if final_score >= 78:
        return "High"
    return "Moderate"
