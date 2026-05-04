from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.candidate_repo import CandidateRepository
from app.db.repositories.contract_repo import OptionContractRepository
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.db.repositories.run_repo import WorkflowRunRepository
from app.db.repositories.user_repo import UserRepository
from app.llm.schemas import ChosenContract, StructuredDecision
from app.pipeline.orchestrator import PipelineOrchestrator
from app.scoring.types import (
    CandidateEvaluation,
    ContractScoreResult,
    DataConfidenceResult,
    DirectionResult,
    HardVeto,
    OptionContractInput,
    StrategySelection,
    UserContext,
)
from app.services.recommendation_alternatives import AlternativeRecommendationService
from app.services.candidate_models import CandidateBatch, CandidateRecord
from app.services.logging_service import LoggingService
from app.services.market_data.types import MarketSnapshot, ReturnMetrics
from app.services.news.types import NewsBrief, NewsBundle
from app.services.sizing import BROKER_MARGIN_DEPENDENT_TEXT
from app.services.sizing_types import SizingResult
from app.telegram.templates.main_recommendation import render_main_recommendation


@dataclass(slots=True)
class RecordedMessage:
    chat_id: str
    text: str
    reply_markup: object | None


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[RecordedMessage] = []

    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        reply_markup: object | None = None,
    ) -> str:
        self.calls.append(RecordedMessage(chat_id=chat_id, text=text, reply_markup=reply_markup))
        return str(len(self.calls))


@dataclass(slots=True)
class FakeCandidateStep:
    batch: CandidateBatch

    async def execute(self) -> CandidateBatch:
        return self.batch


@dataclass(slots=True)
class FakeMarketDataStep:
    snapshots: dict[str, MarketSnapshot]

    async def execute(
        self,
        record: CandidateRecord,
        *,
        alpha_vantage_api_key: str | None,
    ) -> MarketSnapshot:
        del alpha_vantage_api_key
        return self.snapshots[record.ticker]


@dataclass(slots=True)
class FakeNewsStep:
    bundles: dict[str, NewsBundle]

    async def execute(
        self,
        record: CandidateRecord,
        *,
        openrouter_api_key: str,
    ) -> NewsBundle:
        del openrouter_api_key
        return self.bundles[record.ticker]


@dataclass(slots=True)
class FakeOptionsStep:
    chains: dict[str, tuple[OptionContractInput, ...]]

    async def execute(
        self,
        record: CandidateRecord,
        *,
        alpaca_api_key: str | None,
        alpaca_api_secret: str | None,
        strategy_permission: str,
    ) -> tuple[OptionContractInput, ...]:
        del alpaca_api_key, alpaca_api_secret, strategy_permission
        return self.chains.get(record.ticker, ())


@dataclass(slots=True)
class ScoringPlan:
    action: str
    final_score: int
    direction: str
    direction_score: int
    contract_score: int | None = None
    confidence_score: int = 88
    reasoning: tuple[str, ...] = ("Momentum and contract quality lined up.",)


@dataclass(slots=True)
class FakeScoringStep:
    plans: dict[str, ScoringPlan]

    async def execute(
        self,
        candidate,
        user: UserContext,
    ) -> CandidateEvaluation:
        del user
        plan = self.plans[candidate.ticker]
        chosen = None
        considered = ()
        if candidate.option_chain and plan.contract_score is not None:
            chosen = ContractScoreResult(
                strategy=candidate.option_chain[0].strategy,
                contract=candidate.option_chain[0],
                base_score=plan.contract_score,
                score=plan.contract_score,
                factors=(),
                penalties=(),
                vetoes=(),
                breakeven=Decimal("104.50"),
                breakeven_move_percent=Decimal("0.04"),
                liquidity_score=82,
                expiry_days_after_earnings=7,
                reasons=(f"{candidate.ticker} contract screened best.",),
            )
            rejected = tuple(
                ContractScoreResult(
                    strategy=contract.strategy,
                    contract=contract,
                    base_score=max(plan.contract_score - 10, 0),
                    score=0,
                    factors=(),
                    penalties=(),
                    vetoes=(
                        HardVeto(
                            "fixture_rejection",
                            "Fixture rejected this contract for spread quality.",
                        ),
                    ),
                    breakeven=Decimal("109.00"),
                    breakeven_move_percent=Decimal("0.07"),
                    liquidity_score=42,
                    expiry_days_after_earnings=7,
                    reasons=(f"{candidate.ticker} backup contract was rejected.",),
                )
                for contract in candidate.option_chain[1:]
            )
            considered = (chosen, *rejected)

        return CandidateEvaluation(
            ticker=candidate.ticker,
            direction=DirectionResult(
                classification=plan.direction,  # type: ignore[arg-type]
                bias=Decimal("0.70"),
                score=plan.direction_score,
                factors=(),
                reasons=plan.reasoning,
            ),
            confidence=DataConfidenceResult(
                score=plan.confidence_score,
                label="good",
                blockers=(),
                notes=("Pricing came from fixture data.",),
            ),
            strategy_selection=StrategySelection(
                allowed_strategies=tuple(
                    contract.strategy for contract in candidate.option_chain
                ),
                preferred_order=tuple(
                    contract.strategy for contract in candidate.option_chain
                ),
                reason="Fixture strategy order.",
            ),
            considered_contracts=considered,
            chosen_contract=chosen,
            final_score=plan.final_score,
            action=plan.action,  # type: ignore[arg-type]
            reasons=plan.reasoning,
        )


class FakeSizingStep:
    async def execute(
        self,
        user: UserContext,
        contract: OptionContractInput,
    ) -> SizingResult:
        del user
        if contract.position_side == "short":
            return SizingResult(
                quantity=1,
                max_loss_text=BROKER_MARGIN_DEPENDENT_TEXT,
                account_risk_pct=Decimal("0.02"),
                broker_verification_required=True,
                watch_only=False,
            )
        return SizingResult(
            quantity=2,
            max_loss_text="$125.00 max loss per contract",
            account_risk_pct=Decimal("0.02"),
            broker_verification_required=False,
            watch_only=False,
        )


@dataclass(slots=True)
class SpyDecisionStep:
    decision: StructuredDecision
    calls: list[tuple[str, ...]]

    async def execute(
        self,
        candidates,
        user: UserContext,
        *,
        openrouter_api_key: str,
    ):
        del user, openrouter_api_key
        self.calls.append(tuple(candidate.record.ticker for candidate in candidates))
        return SimpleNamespace(
            decision=self.decision,
            trace=SimpleNamespace(
                engine="llm",
                heavy_model_used="anthropic/claude-opus-4.7",
                notes=(),
            ),
        )


async def _make_user(session: AsyncSession, telegram_chat_id: str = "12345") -> User:
    crypto.reset_cache()
    user = await UserRepository(session).add(
        User(
            telegram_chat_id=telegram_chat_id,
            account_size=Decimal("20000.00"),
            risk_profile="Balanced",
            broker="IBKR",
            timezone_label="ET",
            timezone_iana="America/Toronto",
            strategy_permission="long_and_short",
            max_contracts=3,
            openrouter_api_key_encrypted=crypto.encrypt("sk-or-test"),
            alpaca_api_key_encrypted=crypto.encrypt("alpaca-key"),
            alpaca_api_secret_encrypted=crypto.encrypt("alpaca-secret"),
        )
    )
    await session.flush()
    return user


async def _make_run(
    session: AsyncSession,
    user: User,
    *,
    trigger_type: str = "manual",
) -> WorkflowRun:
    run = await WorkflowRunRepository(session).add(
        WorkflowRun(user_id=user.id, trigger_type=trigger_type, status="running")
    )
    await session.flush()
    return run


async def _contract_count(session: AsyncSession, run_id) -> int:
    candidates = await CandidateRepository(session).list_for_run(run_id)
    repo = OptionContractRepository(session)
    return sum(len(await repo.list_for_candidate(candidate.id)) for candidate in candidates)


def _batch() -> CandidateBatch:
    records = tuple(
        CandidateRecord(
            ticker=ticker,
            company_name=f"{ticker} Corp.",
            market_cap=Decimal(str(market_cap)),
            earnings_date=date(2026, 5, 8),
            current_price=Decimal(str(price)),
            sector="Technology",
            sources=("fixture",),
        )
        for ticker, market_cap, price in [
            ("AMD", 900, 102),
            ("AAPL", 850, 190),
            ("MSFT", 820, 420),
            ("NFLX", 610, 810),
            ("JPM", 580, 240),
        ]
    )
    return CandidateBatch(
        candidates=records,
        screener_status="success",
        fallback_used=False,
        warning_text=None,
    )


def _snapshot(record: CandidateRecord) -> MarketSnapshot:
    return MarketSnapshot(
        ticker=record.ticker,
        as_of_date=date(2026, 5, 1),
        company_name=record.company_name,
        sector=record.sector,
        sector_etf="XLK",
        market_cap=record.market_cap,
        current_price=record.current_price,
        latest_volume=1_000_000,
        average_volume_20d=Decimal("900000"),
        volume_vs_average_20d=Decimal("1.10"),
        stock_returns=ReturnMetrics(
            one_day=Decimal("0.01"),
            five_day=Decimal("0.04"),
            twenty_day=Decimal("0.07"),
            fifty_day=Decimal("0.10"),
        ),
        spy_returns=ReturnMetrics(
            one_day=Decimal("0.003"),
            five_day=Decimal("0.01"),
            twenty_day=Decimal("0.03"),
            fifty_day=Decimal("0.05"),
        ),
        qqq_returns=ReturnMetrics(
            one_day=Decimal("0.004"),
            five_day=Decimal("0.015"),
            twenty_day=Decimal("0.04"),
            fifty_day=Decimal("0.06"),
        ),
        sector_returns=ReturnMetrics(
            one_day=Decimal("0.002"),
            five_day=Decimal("0.02"),
            twenty_day=Decimal("0.04"),
            fifty_day=Decimal("0.06"),
        ),
        relative_strength_vs_spy=Decimal("0.03"),
        relative_strength_vs_qqq=Decimal("0.02"),
        relative_strength_vs_sector=Decimal("0.01"),
        av_news_sentiment=None,
        price_source="fixture",
        overview_source="fixture",
        sources=("fixture",),
        confidence_adjustment=0,
        confidence_notes=(),
    )


def _bundle(record: CandidateRecord) -> NewsBundle:
    return NewsBundle(
        ticker=record.ticker,
        company_name=record.company_name,
        generated_at=datetime.now(tz=UTC),
        search_results=(),
        articles=(),
        brief=NewsBrief(
            bullish_evidence=[f"{record.ticker} had supportive setup notes."],
            bearish_evidence=[],
            neutral_contextual_evidence=["Sector context stayed constructive."],
            key_uncertainty="Guidance tone still matters.",
            news_confidence=72,
        ),
        used_ir_fallback=False,
    )


def _long_call(ticker: str, *, strike: str) -> OptionContractInput:
    return OptionContractInput(
        ticker=ticker,
        option_type="call",
        position_side="long",
        strike=Decimal(strike),
        expiry=date(2026, 5, 16),
        bid=Decimal("1.10"),
        ask=Decimal("1.25"),
        volume=120,
        open_interest=320,
        implied_volatility=Decimal("0.44"),
        delta=Decimal("0.52"),
        source="fixture",
    )


@pytest.mark.asyncio
async def test_pipeline_persists_recommendation_and_sends_card(
    db_session: AsyncSession,
    tmp_path,
) -> None:
    batch = _batch()
    notifier = FakeNotifier()
    orchestrator = PipelineOrchestrator(
        candidate_step=FakeCandidateStep(batch),
        market_data_step=FakeMarketDataStep(
            {record.ticker: _snapshot(record) for record in batch.candidates}
        ),
        news_step=FakeNewsStep({record.ticker: _bundle(record) for record in batch.candidates}),
        options_step=FakeOptionsStep(
            {
                "AMD": (
                    _long_call("AMD", strike="104"),
                    _long_call("AMD", strike="108"),
                ),
                "AAPL": (_long_call("AAPL", strike="195"),),
            }
        ),
        scoring_step=FakeScoringStep(
            {
                "AMD": ScoringPlan(
                    action="recommend",
                    final_score=82,
                    direction="bullish",
                    direction_score=80,
                    contract_score=84,
                    reasoning=("AMD had the strongest momentum and the cleanest contract.",),
                ),
                "AAPL": ScoringPlan(
                    action="watchlist",
                    final_score=64,
                    direction="bullish",
                    direction_score=70,
                    contract_score=66,
                ),
                "MSFT": ScoringPlan(
                    action="no_trade",
                    final_score=55,
                    direction="neutral",
                    direction_score=52,
                ),
                "NFLX": ScoringPlan(
                    action="no_trade",
                    final_score=48,
                    direction="bearish",
                    direction_score=50,
                ),
                "JPM": ScoringPlan(
                    action="no_trade",
                    final_score=44,
                    direction="neutral",
                    direction_score=46,
                ),
            }
        ),
        sizing_step=FakeSizingStep(),
        notifier=notifier,
        logging_service=LoggingService(archive_root=tmp_path / "runs"),
    )
    user = await _make_user(db_session)
    run = await _make_run(db_session, user)

    outcome = await orchestrator.run(db_session, run)
    await db_session.commit()

    recommendations = await RecommendationRepository(db_session).list_recent_for_user(user.id)
    candidates = await CandidateRepository(db_session).list_for_run(run.id)

    assert outcome.decision.action == "recommend"
    assert run.status == "success"
    assert run.final_recommendation_id is not None
    assert len(recommendations) == 1
    assert recommendations[0].ticker == "AMD"
    assert recommendations[0].telegram_message_id == "3"
    assert len(candidates) == 5
    assert run.run_summary_json is not None
    assert run.recommendation_card_json is not None
    assert run.telegram_message_text == notifier.calls[2].text
    assert run.recommendation_card_json["selected_ticker"] == "AMD"
    assert run.recommendation_card_json["telegram_message"] == notifier.calls[2].text
    assert run.run_summary_json["contracts_considered_count"] == 3
    assert run.run_summary_json["rejected_contract_count"] == 1
    assert run.option_contracts_json is not None
    assert any(
        contract["rejection_reason"] == "Fixture rejected this contract for spread quality."
        for contract in run.option_contracts_json
    )
    assert notifier.calls[0].text == "🧠 Starting a fresh earnings-options scan now."
    assert notifier.calls[1].text == "✅ Scan complete. Here is the strongest setup I found."
    assert "<b>Weekly Earnings Options Signal</b>" in notifier.calls[2].text
    assert notifier.calls[2].reply_markup is not None


@pytest.mark.asyncio
async def test_pipeline_watchlist_path_sets_zero_quantity(
    db_session: AsyncSession,
) -> None:
    batch = _batch()
    notifier = FakeNotifier()
    orchestrator = PipelineOrchestrator(
        candidate_step=FakeCandidateStep(batch),
        market_data_step=FakeMarketDataStep(
            {record.ticker: _snapshot(record) for record in batch.candidates}
        ),
        news_step=FakeNewsStep({record.ticker: _bundle(record) for record in batch.candidates}),
        options_step=FakeOptionsStep({"AMD": (_long_call("AMD", strike="104"),)}),
        scoring_step=FakeScoringStep(
            {
                "AMD": ScoringPlan(
                    action="watchlist",
                    final_score=63,
                    direction="bullish",
                    direction_score=68,
                    contract_score=65,
                ),
                "AAPL": ScoringPlan("no_trade", 52, "neutral", 54),
                "MSFT": ScoringPlan("no_trade", 51, "neutral", 53),
                "NFLX": ScoringPlan("no_trade", 49, "bearish", 50),
                "JPM": ScoringPlan("no_trade", 45, "neutral", 47),
            }
        ),
        sizing_step=FakeSizingStep(),
        notifier=notifier,
    )
    user = await _make_user(db_session, telegram_chat_id="22345")
    run = await _make_run(db_session, user)

    outcome = await orchestrator.run(db_session, run)
    await db_session.commit()

    recommendation = (await RecommendationRepository(db_session).list_recent_for_user(user.id))[0]

    assert outcome.decision.action == "watchlist"
    assert recommendation.suggested_quantity == 0
    assert run.status == "success"
    assert "watching, but not sizing yet" in notifier.calls[1].text
    assert "Watchlist only" in notifier.calls[2].text


@pytest.mark.asyncio
async def test_pipeline_no_trade_path_marks_run_no_trade(
    db_session: AsyncSession,
) -> None:
    batch = _batch()
    notifier = FakeNotifier()
    orchestrator = PipelineOrchestrator(
        candidate_step=FakeCandidateStep(batch),
        market_data_step=FakeMarketDataStep(
            {record.ticker: _snapshot(record) for record in batch.candidates}
        ),
        news_step=FakeNewsStep({record.ticker: _bundle(record) for record in batch.candidates}),
        options_step=FakeOptionsStep({}),
        scoring_step=FakeScoringStep(
            {
                "AMD": ScoringPlan("no_trade", 58, "neutral", 56),
                "AAPL": ScoringPlan("no_trade", 57, "neutral", 55),
                "MSFT": ScoringPlan("no_trade", 54, "neutral", 52),
                "NFLX": ScoringPlan("no_trade", 50, "bearish", 49),
                "JPM": ScoringPlan("no_trade", 46, "neutral", 45),
            }
        ),
        sizing_step=FakeSizingStep(),
        notifier=notifier,
    )
    user = await _make_user(db_session, telegram_chat_id="32345")
    run = await _make_run(db_session, user)

    outcome = await orchestrator.run(db_session, run)
    await db_session.commit()

    recommendations = await RecommendationRepository(db_session).list_recent_for_user(user.id)

    assert outcome.decision.action == "no_trade"
    assert run.status == "no_trade"
    assert recommendations == []
    assert "No trade looks strong enough this time" in notifier.calls[1].text
    assert "<b>Weekly Earnings Options Scan Complete</b>" in notifier.calls[2].text
    assert "1. AMD" in notifier.calls[2].text


@pytest.mark.asyncio
async def test_alternative_service_reuses_candidate_universe_and_persists_watchlist(
    db_session: AsyncSession,
) -> None:
    batch = _batch()
    primary_orchestrator = PipelineOrchestrator(
        candidate_step=FakeCandidateStep(batch),
        market_data_step=FakeMarketDataStep(
            {record.ticker: _snapshot(record) for record in batch.candidates}
        ),
        news_step=FakeNewsStep({record.ticker: _bundle(record) for record in batch.candidates}),
        options_step=FakeOptionsStep(
            {
                "AMD": (_long_call("AMD", strike="104"),),
                "AAPL": (_long_call("AAPL", strike="195"),),
                "MSFT": (_long_call("MSFT", strike="425"),),
            }
        ),
        scoring_step=FakeScoringStep(
            {
                "AMD": ScoringPlan("recommend", 82, "bullish", 80, 84),
                "AAPL": ScoringPlan("watchlist", 64, "bullish", 70, 67),
                "MSFT": ScoringPlan("watchlist", 61, "bullish", 66, 63),
                "NFLX": ScoringPlan("no_trade", 54, "neutral", 52),
                "JPM": ScoringPlan("no_trade", 49, "neutral", 47),
            }
        ),
        sizing_step=FakeSizingStep(),
        notifier=FakeNotifier(),
    )
    user = await _make_user(db_session, telegram_chat_id="52345")
    run = await _make_run(db_session, user)
    await primary_orchestrator.run(db_session, run)
    await db_session.commit()

    original = (await RecommendationRepository(db_session).list_recent_for_user(user.id))[0]
    candidate_count_before = len(await CandidateRepository(db_session).list_for_run(run.id))
    contract_count_before = await _contract_count(db_session, run.id)
    run_count_before = len(await WorkflowRunRepository(db_session).list_recent_for_user(user.id))

    decision_step = SpyDecisionStep(
        decision=StructuredDecision(
            action="watchlist",
            chosen_ticker="AAPL",
            chosen_contract=ChosenContract(
                ticker="AAPL",
                option_type="call",
                position_side="long",
                strike=Decimal("195"),
                expiry=date(2026, 5, 16),
                rationale="AAPL became the strongest remaining setup.",
            ),
            direction_score=70,
            contract_score=67,
            final_score=64,
            reasoning="AAPL was the best remaining setup, but only at watchlist strength.",
            key_evidence=["AAPL still had the cleanest remaining profile."],
            key_concerns=["It stayed just below the full recommendation bar."],
            watchlist_tickers=["AAPL", "MSFT", "NFLX"],
        ),
        calls=[],
    )
    alternative_orchestrator = PipelineOrchestrator(
        market_data_step=FakeMarketDataStep(
            {record.ticker: _snapshot(record) for record in batch.candidates}
        ),
        news_step=FakeNewsStep({record.ticker: _bundle(record) for record in batch.candidates}),
        options_step=FakeOptionsStep(
            {
                "AAPL": (_long_call("AAPL", strike="195"),),
                "MSFT": (_long_call("MSFT", strike="425"),),
            }
        ),
        scoring_step=FakeScoringStep(
            {
                "AAPL": ScoringPlan("watchlist", 64, "bullish", 70, 67),
                "MSFT": ScoringPlan("watchlist", 61, "bullish", 66, 63),
                "NFLX": ScoringPlan("no_trade", 54, "neutral", 52),
                "JPM": ScoringPlan("no_trade", 49, "neutral", 47),
            }
        ),
        sizing_step=FakeSizingStep(),
        decision_step=decision_step,
        notifier=FakeNotifier(),
    )
    service = AlternativeRecommendationService(
        db_session,
        orchestrator=alternative_orchestrator,
    )

    result = await service.get_next_alternative(cursor=original, user=user)
    await db_session.commit()

    assert result.status == "recommendation"
    assert result.recommendation is not None
    assert result.recommendation.parent_recommendation_id == original.id
    assert result.recommendation.ticker == "AAPL"
    assert result.recommendation.suggested_quantity == 0
    assert decision_step.calls == [("AAPL", "MSFT", "NFLX", "JPM")]
    assert len(await WorkflowRunRepository(db_session).list_recent_for_user(user.id)) == run_count_before
    assert len(await CandidateRepository(db_session).list_for_run(run.id)) == candidate_count_before
    assert await _contract_count(db_session, run.id) == contract_count_before


@pytest.mark.asyncio
async def test_alternative_service_second_click_returns_third_best_option(
    db_session: AsyncSession,
) -> None:
    batch = _batch()
    primary_orchestrator = PipelineOrchestrator(
        candidate_step=FakeCandidateStep(batch),
        market_data_step=FakeMarketDataStep(
            {record.ticker: _snapshot(record) for record in batch.candidates}
        ),
        news_step=FakeNewsStep({record.ticker: _bundle(record) for record in batch.candidates}),
        options_step=FakeOptionsStep(
            {
                "AMD": (_long_call("AMD", strike="104"),),
                "AAPL": (_long_call("AAPL", strike="195"),),
                "MSFT": (_long_call("MSFT", strike="425"),),
            }
        ),
        scoring_step=FakeScoringStep(
            {
                "AMD": ScoringPlan("recommend", 82, "bullish", 80, 84),
                "AAPL": ScoringPlan("watchlist", 64, "bullish", 70, 67),
                "MSFT": ScoringPlan("watchlist", 62, "bullish", 68, 65),
                "NFLX": ScoringPlan("no_trade", 54, "neutral", 52),
                "JPM": ScoringPlan("no_trade", 49, "neutral", 47),
            }
        ),
        sizing_step=FakeSizingStep(),
        notifier=FakeNotifier(),
    )
    user = await _make_user(db_session, telegram_chat_id="62345")
    run = await _make_run(db_session, user)
    await primary_orchestrator.run(db_session, run)
    await db_session.commit()

    parent = (await RecommendationRepository(db_session).list_recent_for_user(user.id))[0]

    first_decision = SpyDecisionStep(
        decision=StructuredDecision(
            action="watchlist",
            chosen_ticker="AAPL",
            chosen_contract=ChosenContract(
                ticker="AAPL",
                option_type="call",
                position_side="long",
                strike=Decimal("195"),
                expiry=date(2026, 5, 16),
                rationale="AAPL was the strongest remaining setup.",
            ),
            direction_score=70,
            contract_score=67,
            final_score=64,
            reasoning="AAPL was the next best setup.",
            key_evidence=["AAPL still held up best."],
            key_concerns=["It stayed in watchlist territory."],
            watchlist_tickers=["AAPL", "MSFT"],
        ),
        calls=[],
    )
    first_service = AlternativeRecommendationService(
        db_session,
        orchestrator=PipelineOrchestrator(
            market_data_step=FakeMarketDataStep(
                {record.ticker: _snapshot(record) for record in batch.candidates}
            ),
            news_step=FakeNewsStep(
                {record.ticker: _bundle(record) for record in batch.candidates}
            ),
            options_step=FakeOptionsStep(
                {
                    "AAPL": (_long_call("AAPL", strike="195"),),
                    "MSFT": (_long_call("MSFT", strike="425"),),
                }
            ),
            scoring_step=FakeScoringStep(
                {
                    "AAPL": ScoringPlan("watchlist", 64, "bullish", 70, 67),
                    "MSFT": ScoringPlan("watchlist", 62, "bullish", 68, 65),
                    "NFLX": ScoringPlan("no_trade", 54, "neutral", 52),
                    "JPM": ScoringPlan("no_trade", 49, "neutral", 47),
                }
            ),
            sizing_step=FakeSizingStep(),
            decision_step=first_decision,
            notifier=FakeNotifier(),
        ),
    )
    first_result = await first_service.get_next_alternative(cursor=parent, user=user)
    await db_session.commit()
    assert first_result.recommendation is not None

    second_decision = SpyDecisionStep(
        decision=StructuredDecision(
            action="watchlist",
            chosen_ticker="MSFT",
            chosen_contract=ChosenContract(
                ticker="MSFT",
                option_type="call",
                position_side="long",
                strike=Decimal("425"),
                expiry=date(2026, 5, 16),
                rationale="MSFT was the strongest remaining setup after AAPL was removed.",
            ),
            direction_score=68,
            contract_score=65,
            final_score=62,
            reasoning="MSFT became the third-best setup once AMD and AAPL were excluded.",
            key_evidence=["MSFT held up best among the names left."],
            key_concerns=["It remained a watchlist setup only."],
            watchlist_tickers=["MSFT", "NFLX"],
        ),
        calls=[],
    )
    second_service = AlternativeRecommendationService(
        db_session,
        orchestrator=PipelineOrchestrator(
            market_data_step=FakeMarketDataStep(
                {record.ticker: _snapshot(record) for record in batch.candidates}
            ),
            news_step=FakeNewsStep(
                {record.ticker: _bundle(record) for record in batch.candidates}
            ),
            options_step=FakeOptionsStep({"MSFT": (_long_call("MSFT", strike="425"),)}),
            scoring_step=FakeScoringStep(
                {
                    "MSFT": ScoringPlan("watchlist", 62, "bullish", 68, 65),
                    "NFLX": ScoringPlan("no_trade", 54, "neutral", 52),
                    "JPM": ScoringPlan("no_trade", 49, "neutral", 47),
                }
            ),
            sizing_step=FakeSizingStep(),
            decision_step=second_decision,
            notifier=FakeNotifier(),
        ),
    )
    second_result = await second_service.get_next_alternative(
        cursor=first_result.recommendation,
        user=user,
    )
    await db_session.commit()

    assert second_result.status == "recommendation"
    assert second_result.recommendation is not None
    assert second_result.recommendation.ticker == "MSFT"
    assert second_result.recommendation.parent_recommendation_id == first_result.recommendation.id
    assert second_decision.calls == [("MSFT", "NFLX", "JPM")]


@pytest.mark.asyncio
async def test_alternative_service_no_trade_does_not_persist_recommendation(
    db_session: AsyncSession,
) -> None:
    batch = _batch()
    primary_orchestrator = PipelineOrchestrator(
        candidate_step=FakeCandidateStep(batch),
        market_data_step=FakeMarketDataStep(
            {record.ticker: _snapshot(record) for record in batch.candidates}
        ),
        news_step=FakeNewsStep({record.ticker: _bundle(record) for record in batch.candidates}),
        options_step=FakeOptionsStep({"AMD": (_long_call("AMD", strike="104"),)}),
        scoring_step=FakeScoringStep(
            {
                "AMD": ScoringPlan("recommend", 82, "bullish", 80, 84),
                "AAPL": ScoringPlan("no_trade", 57, "neutral", 55),
                "MSFT": ScoringPlan("no_trade", 56, "neutral", 54),
                "NFLX": ScoringPlan("no_trade", 54, "neutral", 52),
                "JPM": ScoringPlan("no_trade", 49, "neutral", 47),
            }
        ),
        sizing_step=FakeSizingStep(),
        notifier=FakeNotifier(),
    )
    user = await _make_user(db_session, telegram_chat_id="72345")
    run = await _make_run(db_session, user)
    await primary_orchestrator.run(db_session, run)
    await db_session.commit()

    parent = (await RecommendationRepository(db_session).list_recent_for_user(user.id))[0]
    rec_count_before = len(await RecommendationRepository(db_session).list_recent_for_user(user.id))

    no_trade_decision = SpyDecisionStep(
        decision=StructuredDecision(
            action="no_trade",
            chosen_ticker=None,
            chosen_contract=None,
            final_score=58,
            reasoning="Nothing else cleared the alternative trade bar.",
            key_evidence=[],
            key_concerns=["The remaining setups were too weak."],
            watchlist_tickers=["AAPL", "MSFT"],
        ),
        calls=[],
    )
    service = AlternativeRecommendationService(
        db_session,
        orchestrator=PipelineOrchestrator(
            market_data_step=FakeMarketDataStep(
                {record.ticker: _snapshot(record) for record in batch.candidates}
            ),
            news_step=FakeNewsStep(
                {record.ticker: _bundle(record) for record in batch.candidates}
            ),
            options_step=FakeOptionsStep({}),
            scoring_step=FakeScoringStep(
                {
                    "AAPL": ScoringPlan("no_trade", 57, "neutral", 55),
                    "MSFT": ScoringPlan("no_trade", 56, "neutral", 54),
                    "NFLX": ScoringPlan("no_trade", 54, "neutral", 52),
                    "JPM": ScoringPlan("no_trade", 49, "neutral", 47),
                }
            ),
            sizing_step=FakeSizingStep(),
            decision_step=no_trade_decision,
            notifier=FakeNotifier(),
        ),
    )

    result = await service.get_next_alternative(cursor=parent, user=user)
    await db_session.commit()

    assert result.status == "no_trade"
    assert result.recommendation is None
    assert len(await RecommendationRepository(db_session).list_recent_for_user(user.id)) == rec_count_before


def test_main_recommendation_template_matches_prd_structure() -> None:
    recommendation = SimpleNamespace(
        ticker="AMD",
        company_name="AMD Corp.",
        option_type="call",
        position_side="long",
        strike=Decimal("104"),
        expiry=date(2026, 5, 16),
        earnings_date=date(2026, 5, 8),
        suggested_entry=Decimal("1.25"),
        suggested_quantity=2,
        estimated_max_loss="$125.00 max loss per contract",
        account_risk_percent=Decimal("2.00"),
        confidence_score=82,
        risk_level="High",
        reasoning_summary="AMD had the strongest momentum and the cleanest contract.",
        key_concerns_json=["IV crush is still a real risk."],
    )

    text = render_main_recommendation(recommendation)
    ordered_labels = [
        "<b>Weekly Earnings Options Signal</b>",
        "<b>Best setup:</b> AMD",
        "<b>Direction:</b> Bullish",
        "<b>Contract:</b> AMD Call",
        "<b>Strike:</b> $104.00",
        "<b>Expiry:</b> 2026-05-16",
        "<b>Suggested entry:</b> up to $1.25 premium",
        "<b>Suggested quantity:</b> 2 contract(s)",
        "<b>Estimated max loss:</b> $125.00 max loss per contract",
        "<b>Account risk:</b> 2.00%",
        "<b>Earnings date:</b> 2026-05-08",
        "<b>Confidence:</b> 82/100",
        "<b>Risk level:</b> High",
        "<b>Why this setup:</b>",
        "<b>Important warning:</b>",
        "<b>Action:</b>",
    ]

    indexes = [text.index(label) for label in ordered_labels]
    assert indexes == sorted(indexes)


def test_main_recommendation_template_supports_alternative_label() -> None:
    recommendation = SimpleNamespace(
        ticker="AAPL",
        company_name="Apple Inc.",
        option_type="call",
        position_side="long",
        strike=Decimal("195"),
        expiry=date(2026, 5, 16),
        earnings_date=date(2026, 5, 8),
        suggested_entry=Decimal("1.35"),
        suggested_quantity=1,
        estimated_max_loss="$135.00 max loss per contract",
        account_risk_percent=Decimal("2.00"),
        confidence_score=76,
        risk_level="Moderate",
        reasoning_summary="AAPL became the strongest remaining setup.",
        key_concerns_json=["IV crush is still a real risk."],
    )

    text = render_main_recommendation(recommendation, setup_label="Next best setup")

    assert "<b>Next best setup:</b> AAPL" in text


def test_short_option_template_uses_margin_warning() -> None:
    recommendation = SimpleNamespace(
        ticker="TSLA",
        company_name="Tesla Inc.",
        option_type="call",
        position_side="short",
        strike=Decimal("210"),
        expiry=date(2026, 5, 16),
        earnings_date=date(2026, 5, 8),
        suggested_entry=Decimal("2.10"),
        suggested_quantity=1,
        estimated_max_loss="Some stored value that should be overridden",
        account_risk_percent=Decimal("2.00"),
        confidence_score=79,
        risk_level="High",
        reasoning_summary="Short premium stayed rich enough to monitor.",
        key_concerns_json=[],
    )

    text = render_main_recommendation(recommendation)

    assert "<b>Contract:</b> TSLA Short Call" in text
    assert "Undefined for naked short call" in text
