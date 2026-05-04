from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any, Protocol

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models.candidate import Candidate
from app.db.models.option_contract import OptionContract
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.candidate_repo import CandidateRepository
from app.db.repositories.contract_repo import OptionContractRepository
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.db.repositories.user_repo import UserRepository
from app.llm.types import LLMAuthenticationError
from app.pipeline.steps.candidates import CandidateSelectionStep, CandidateStep
from app.pipeline.steps.decide import (
    DecisionStep,
    get_default_decision_step,
    resolve_selected_contract,
)
from app.pipeline.steps.market_data import MarketDataFetchStep, MarketDataStep
from app.pipeline.steps.news import NewsBriefStep, NewsStep
from app.pipeline.steps.options import OptionsFetchStep, OptionsStep
from app.pipeline.steps.scoring import CandidateScoringStep, ScoringStep
from app.pipeline.steps.sizing import PositionSizingStep, SizingStep
from app.pipeline.types import PipelineCandidate, PipelineOutcome
from app.scoring.types import (
    CandidateContext,
    UserContext,
    breakeven_price,
    option_mid,
    option_premium,
    spread_percent,
)
from app.services.candidate_models import CandidateBatch, CandidateRecord
from app.services.logging_service import LoggingService, get_logging_service
from app.services.market_data.types import ConfidenceNote, MarketSnapshot, ReturnMetrics
from app.services.news.types import NewsBrief, NewsBundle
from app.services.sizing import BROKER_MARGIN_DEPENDENT_TEXT, SizingError, SizingPermissionError
from app.services.sizing_types import SizingResult
from app.services.user_service import decrypt_or_none
from app.telegram.handlers._common import enforce_tone
from app.telegram.keyboards.settings import recommendation_keyboard
from app.telegram.templates.main_recommendation import render_main_recommendation
from app.telegram.templates.no_trade import render_no_trade
from app.telegram.templates.status import render_scan_started, render_weekly_scan_ready

ZERO = Decimal("0")


class TelegramNotifier(Protocol):
    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        reply_markup: Any | None = None,
    ) -> str | None: ...


@dataclass(slots=True, frozen=True)
class _UserSecrets:
    openrouter_api_key: str
    alpha_vantage_api_key: str | None
    alpaca_api_key: str | None
    alpaca_api_secret: str | None


class AiogramNotifier:
    def __init__(self, bot_factory: Callable[[], Bot] | None = None) -> None:
        self.bot_factory = bot_factory or _build_runtime_bot

    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        reply_markup: Any | None = None,
    ) -> str | None:
        enforce_tone(text)
        bot = self.bot_factory()
        try:
            delivered = await bot.send_message(
                chat_id=int(chat_id) if chat_id.isdigit() else chat_id,
                text=text,
                reply_markup=reply_markup,
            )
            return str(delivered.message_id)
        finally:
            await bot.session.close()


class PipelineOrchestrator:
    def __init__(
        self,
        *,
        candidate_step: CandidateStep | None = None,
        market_data_step: MarketDataStep | None = None,
        news_step: NewsStep | None = None,
        options_step: OptionsStep | None = None,
        scoring_step: ScoringStep | None = None,
        sizing_step: SizingStep | None = None,
        decision_step: DecisionStep | None = None,
        notifier: TelegramNotifier | None = None,
        logging_service: LoggingService | None = None,
        logger: Any | None = None,
    ) -> None:
        settings = get_settings()
        self.candidate_step = candidate_step or CandidateSelectionStep()
        self.market_data_step = market_data_step or MarketDataFetchStep()
        self.news_step = news_step or NewsBriefStep()
        self.options_step = options_step or OptionsFetchStep()
        self.scoring_step = scoring_step or CandidateScoringStep()
        self.sizing_step = sizing_step or PositionSizingStep()
        self.decision_step = decision_step or get_default_decision_step(settings=settings)
        self.notifier = notifier or AiogramNotifier()
        self.logger = logger or get_logger(__name__)
        self.logging_service = logging_service or get_logging_service()

    async def run(self, session: AsyncSession, run: WorkflowRun) -> PipelineOutcome:
        user = await UserRepository(session).get(run.user_id)
        if user is None:
            raise LookupError(f"Workflow user {run.user_id} was not found")

        if run.trigger_type == "manual":
            await self.notifier.send_text(user.telegram_chat_id, render_scan_started())

        batch = await self.candidate_step.execute()
        run.screener_status = batch.screener_status
        run.selected_candidate_count = len(batch.candidates)
        outcome = await self.evaluate_batch(batch, user)
        recommendation = await self._persist(session, run, user, outcome)
        telegram_message = await self._notify_user(user, run.trigger_type, outcome, recommendation)
        self.logging_service.capture_run(
            run=run,
            user=user,
            outcome=outcome,
            recommendation=recommendation,
            telegram_message=telegram_message,
        )
        return outcome

    async def evaluate_batch(
        self,
        batch: CandidateBatch,
        user: User,
    ) -> PipelineOutcome:
        secrets = _decrypt_user_secrets(user)
        user_context = _build_user_context(
            user,
            has_valid_openrouter_api_key=bool(secrets.openrouter_api_key),
        )
        candidates = [
            await self._analyze_candidate(record, user, user_context, secrets)
            for record in batch.candidates
        ]
        decision_result = await self.decision_step.execute(
            candidates,
            user_context,
            openrouter_api_key=secrets.openrouter_api_key,
        )
        selected = _select_candidate(candidates, decision_result.decision.chosen_ticker)
        selected_contract = _select_contract(
            selected,
            decision_result.decision.chosen_contract,
        )
        return PipelineOutcome(
            batch=batch,
            decision=decision_result.decision,
            candidates=tuple(candidates),
            selected=selected,
            selected_contract=selected_contract,
            decision_trace=decision_result.trace,
        )

    async def _analyze_candidate(
        self,
        record: CandidateRecord,
        user: User,
        user_context: UserContext,
        secrets: _UserSecrets,
    ) -> PipelineCandidate:
        calculation_errors: list[str] = []
        effective_user_context = user_context

        try:
            market_snapshot = await self.market_data_step.execute(
                record,
                alpha_vantage_api_key=secrets.alpha_vantage_api_key,
            )
        except Exception as exc:
            calculation_errors.append(f"Market data fallback used: {exc}")
            market_snapshot = _fallback_market_snapshot(record, error=str(exc))

        try:
            news_bundle = await self.news_step.execute(
                record,
                openrouter_api_key=secrets.openrouter_api_key,
            )
        except LLMAuthenticationError as exc:
            calculation_errors.append(f"News fallback used: {exc}")
            news_bundle = _fallback_news_bundle(record, error=str(exc))
            effective_user_context = replace(
                user_context,
                has_valid_openrouter_api_key=False,
            )
        except Exception as exc:
            calculation_errors.append(f"News fallback used: {exc}")
            news_bundle = _fallback_news_bundle(record, error=str(exc))

        try:
            option_chain = await self.options_step.execute(
                record,
                alpaca_api_key=secrets.alpaca_api_key,
                alpaca_api_secret=secrets.alpaca_api_secret,
                strategy_permission=user.strategy_permission,
            )
        except Exception as exc:
            calculation_errors.append(f"Option chain unavailable: {exc}")
            option_chain = ()

        context = CandidateContext(
            ticker=record.ticker,
            company_name=record.company_name or market_snapshot.company_name or record.ticker,
            earnings_date=record.earnings_date or datetime.now(UTC).date(),
            earnings_timing="unknown",
            market_snapshot=market_snapshot,
            news_brief=news_bundle.brief,
            option_chain=option_chain,
            verified_earnings_date=record.earnings_date_verified,
            identity_verified=bool(
                record.ticker and (record.company_name or market_snapshot.company_name)
            ),
            source_conflicts=(),
            calculation_errors=tuple(calculation_errors),
        )
        evaluation = await self.scoring_step.execute(context, effective_user_context)
        sizing = await self._size_candidate(effective_user_context, evaluation)
        return PipelineCandidate(
            record=record,
            context=context,
            evaluation=evaluation,
            news_bundle=news_bundle,
            sizing=sizing,
        )

    async def _size_candidate(
        self,
        user_context: UserContext,
        evaluation,
    ) -> SizingResult | None:
        if evaluation.chosen_contract is None:
            return None
        return await self._size_contract(user_context, evaluation.chosen_contract.contract)

    async def _size_contract(
        self,
        user_context: UserContext,
        contract,
    ) -> SizingResult | None:
        try:
            return await self.sizing_step.execute(user_context, contract)
        except (SizingError, SizingPermissionError) as exc:
            self.logger.warning("pipeline_sizing_failed", ticker=contract.ticker, error=str(exc))
            return _fallback_sizing(contract.position_side)

    async def _persist(
        self,
        session: AsyncSession,
        run: WorkflowRun,
        user: User,
        outcome: PipelineOutcome,
    ) -> Recommendation | None:
        candidate_repo = CandidateRepository(session)
        contract_repo = OptionContractRepository(session)
        selected_ticker = outcome.selected.record.ticker if outcome.selected is not None else None

        for item in outcome.candidates:
            candidate_row = await candidate_repo.add(
                Candidate(
                    run_id=run.id,
                    ticker=item.record.ticker,
                    company_name=item.context.company_name,
                    market_cap=item.record.market_cap
                    or item.context.market_snapshot.market_cap
                    or ZERO,
                    earnings_date=item.context.earnings_date,
                    earnings_timing=item.context.earnings_timing,
                    current_price=item.context.market_snapshot.current_price
                    or item.record.current_price
                    or ZERO,
                    direction_classification=item.evaluation.direction.classification,
                    candidate_direction_score=item.evaluation.direction.score,
                    best_strategy=(
                        None
                        if item.evaluation.chosen_contract is None
                        else item.evaluation.chosen_contract.strategy
                    ),
                    final_opportunity_score=item.evaluation.final_score,
                    data_confidence_score=item.evaluation.confidence.score,
                    selected_for_final=item.record.ticker == selected_ticker,
                )
            )

            for contract in item.evaluation.considered_contracts:
                spread = spread_percent(contract.contract)
                await contract_repo.add(
                    OptionContract(
                        candidate_id=candidate_row.id,
                        ticker=contract.contract.ticker,
                        option_type=contract.contract.option_type,
                        position_side=contract.contract.position_side,
                        strike=contract.contract.strike,
                        expiry=contract.contract.expiry,
                        bid=contract.contract.bid or ZERO,
                        ask=contract.contract.ask or ZERO,
                        mid=option_mid(contract.contract) or ZERO,
                        volume=contract.contract.volume,
                        open_interest=contract.contract.open_interest,
                        implied_volatility=contract.contract.implied_volatility,
                        delta=contract.contract.delta,
                        breakeven=contract.breakeven or breakeven_price(contract.contract) or ZERO,
                        spread_percent=ZERO if spread is None else spread * Decimal("100"),
                        liquidity_score=contract.liquidity_score,
                        contract_opportunity_score=contract.score,
                        passed_hard_filters=not contract.vetoes,
                        rejection_reason=(
                            None
                            if not contract.vetoes
                            else "; ".join(veto.reason for veto in contract.vetoes)
                        ),
                    )
                )

        recommendation = await self.persist_recommendation(
            session,
            run,
            user,
            outcome,
            update_run=True,
        )
        if recommendation is None and run.finished_at is None:
            run.finished_at = datetime.now(UTC)
        return recommendation

    async def persist_recommendation(
        self,
        session: AsyncSession,
        run: WorkflowRun,
        user: User,
        outcome: PipelineOutcome,
        *,
        parent_recommendation_id=None,
        update_run: bool,
    ) -> Recommendation | None:
        recommendation_repo = RecommendationRepository(session)
        if outcome.decision.action == "no_trade" or outcome.selected is None:
            if update_run:
                run.status = "no_trade"
                run.finished_at = datetime.now(UTC)
                run.final_recommendation_id = None
            return None

        chosen_contract = outcome.final_contract
        if chosen_contract is None:
            if update_run:
                run.status = "no_trade"
                run.finished_at = datetime.now(UTC)
                run.final_recommendation_id = None
            return None

        user_context = _build_user_context(
            user,
            has_valid_openrouter_api_key=bool(_decrypt_user_secrets(user).openrouter_api_key),
        )
        sizing = outcome.selected.sizing
        if sizing is None or outcome.selected.evaluation.chosen_contract != chosen_contract:
            sizing = await self._size_contract(user_context, chosen_contract.contract)
        sizing = sizing or _fallback_sizing(chosen_contract.contract.position_side)
        quantity = 0 if outcome.decision.action == "watchlist" else sizing.quantity
        confidence_score = (
            outcome.decision.final_score
            if outcome.decision.final_score is not None
            else outcome.selected.evaluation.final_score
        )
        recommendation = await recommendation_repo.add(
            Recommendation(
                user_id=user.id,
                run_id=run.id,
                parent_recommendation_id=parent_recommendation_id,
                ticker=outcome.selected.record.ticker,
                company_name=outcome.selected.context.company_name,
                strategy=chosen_contract.strategy,
                option_type=chosen_contract.contract.option_type,
                position_side=chosen_contract.contract.position_side,
                strike=chosen_contract.contract.strike,
                expiry=chosen_contract.contract.expiry,
                suggested_entry=option_premium(chosen_contract.contract),
                suggested_quantity=quantity,
                estimated_max_loss=sizing.max_loss_text,
                account_risk_percent=sizing.account_risk_pct * Decimal("100"),
                confidence_score=confidence_score,
                risk_level=_risk_level(chosen_contract, confidence_score),
                reasoning_summary=outcome.decision.reasoning,
                key_evidence_json=outcome.decision.key_evidence,
                key_concerns_json=outcome.decision.key_concerns,
            )
        )
        recommendation.earnings_date = outcome.selected.context.earnings_date
        if update_run:
            run.status = "success"
            run.finished_at = datetime.now(UTC)
            run.final_recommendation_id = recommendation.id
        return recommendation

    async def _notify_user(
        self,
        user: User,
        trigger_type: str,
        outcome: PipelineOutcome,
        recommendation: Recommendation | None,
    ) -> str:
        if recommendation is None:
            await self.notifier.send_text(
                user.telegram_chat_id,
                render_weekly_scan_ready(
                    trigger_type=trigger_type,
                    action="no_trade",
                ),
            )
            final_message = render_no_trade(
                reason=outcome.decision.reasoning,
                watchlist_tickers=outcome.decision.watchlist_tickers,
                warning_text=outcome.batch.warning_text,
            )
            await self.notifier.send_text(
                user.telegram_chat_id,
                final_message,
            )
            return final_message

        action = outcome.decision.action
        if outcome.selected is not None:
            recommendation.earnings_date = outcome.selected.context.earnings_date
        final_message = render_main_recommendation(
            recommendation,
            warning_text=outcome.batch.warning_text,
            watchlist_only=action == "watchlist",
        )
        await self.notifier.send_text(
            user.telegram_chat_id,
            render_weekly_scan_ready(trigger_type=trigger_type, action=action),
        )
        message_id = await self.notifier.send_text(
            user.telegram_chat_id,
            final_message,
            reply_markup=recommendation_keyboard(str(recommendation.id)),
        )
        recommendation.telegram_message_id = message_id
        return final_message


@lru_cache(maxsize=1)
def get_pipeline_orchestrator() -> PipelineOrchestrator:
    return PipelineOrchestrator()


def _decrypt_user_secrets(user: User) -> _UserSecrets:
    return _UserSecrets(
        openrouter_api_key=decrypt_or_none(user.openrouter_api_key_encrypted) or "",
        alpha_vantage_api_key=decrypt_or_none(user.alpha_vantage_api_key_encrypted),
        alpaca_api_key=decrypt_or_none(user.alpaca_api_key_encrypted),
        alpaca_api_secret=decrypt_or_none(user.alpaca_api_secret_encrypted),
    )


def _build_user_context(user: User, *, has_valid_openrouter_api_key: bool) -> UserContext:
    return UserContext(
        account_size=Decimal(str(user.account_size)),
        risk_profile=user.risk_profile,  # type: ignore[arg-type]
        strategy_permission=user.strategy_permission,  # type: ignore[arg-type]
        max_contracts=user.max_contracts,
        max_option_premium=None
        if user.max_option_premium is None
        else Decimal(str(user.max_option_premium)),
        custom_risk_percent=None
        if user.custom_risk_percent is None
        else Decimal(str(user.custom_risk_percent)),
        has_valid_openrouter_api_key=has_valid_openrouter_api_key,
    )


def _fallback_market_snapshot(record: CandidateRecord, *, error: str) -> MarketSnapshot:
    return MarketSnapshot(
        ticker=record.ticker,
        as_of_date=record.earnings_date,
        company_name=record.company_name,
        sector=record.sector,
        sector_etf=None,
        market_cap=record.market_cap,
        current_price=record.current_price,
        latest_volume=record.volume,
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
        price_source="candidate_fallback",
        overview_source="candidate_fallback",
        sources=("candidate_selection",),
        confidence_adjustment=-20,
        confidence_notes=(
            ConfidenceNote(
                source="pipeline",
                field="market_data",
                detail=error,
                severity="warning",
                score_delta=-20,
            ),
        ),
    )


def _fallback_news_bundle(record: CandidateRecord, *, error: str) -> NewsBundle:
    return NewsBundle(
        ticker=record.ticker,
        company_name=record.company_name,
        generated_at=datetime.now(tz=UTC),
        search_results=(),
        articles=(),
        brief=NewsBrief(
            bullish_evidence=[],
            bearish_evidence=[],
            neutral_contextual_evidence=["Recent coverage was unavailable during this run."],
            key_uncertainty=error,
            news_confidence=25,
        ),
        used_ir_fallback=False,
        used_llm_summary=False,
    )


def _fallback_sizing(position_side: str) -> SizingResult:
    return SizingResult(
        quantity=0,
        max_loss_text=(
            BROKER_MARGIN_DEPENDENT_TEXT if position_side == "short" else "Sizing unavailable."
        ),
        account_risk_pct=ZERO,
        broker_verification_required=True,
        watch_only=True,
    )


def _select_candidate(
    candidates: list[PipelineCandidate],
    chosen_ticker: str | None,
) -> PipelineCandidate | None:
    if chosen_ticker is None:
        return None
    for item in candidates:
        if item.record.ticker == chosen_ticker:
            return item
    return None


def _select_contract(
    candidate: PipelineCandidate | None,
    chosen_contract,
):
    if candidate is None:
        return None
    return resolve_selected_contract(candidate, chosen_contract)


def _risk_level(contract, final_score: int) -> str:
    if contract.contract.position_side == "short":
        return "High"
    if final_score >= 78:
        return "High"
    return "Moderate"


def _build_runtime_bot() -> Bot:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Create a bot via @BotFather and add the token to .env."
        )
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
