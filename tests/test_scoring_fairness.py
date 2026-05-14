from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from app.pipeline.orchestrator import _select_decision_finalists
from app.pipeline.types import PipelineCandidate
from app.scoring.confidence import _V2_CONFIDENCE, compute_data_confidence
from app.scoring.direction import _V2_WEIGHTS_BY_STRATEGY, score_direction
from app.scoring.final import score_candidate
from app.scoring.penalties import collect_soft_penalties
from app.scoring.types import CandidateContext, OptionContractInput, StrategySource, UserContext
from app.services.candidate_models import CandidateRecord, StrategyEventSignal
from app.services.market_data.types import MarketSnapshot, ReturnMetrics
from app.services.news.types import NewsBrief, NewsBundle

VALUATION_DATE = date(2026, 5, 1)
EARNINGS_DATE = date(2026, 5, 8)
STRATEGIES: tuple[StrategySource, ...] = (
    "catalyst_confluence",
    "coiled_setup",
    "pead_continuation",
    "sector_relative_strength",
    "activist_13d_followthrough",
)


def test_max_direction_score_equal_across_strategies() -> None:
    scores = {
        strategy: score_direction(
            _candidate(strategy, event_score=100),
            data_confidence_score=97,
        ).score
        for strategy in STRATEGIES
    }

    assert max(scores.values()) - min(scores.values()) <= 2


def test_max_confidence_score_equal_across_strategies() -> None:
    user = _user()
    scores = {}
    for strategy in STRATEGIES:
        candidate = _candidate(strategy, event_score=100)
        scores[strategy] = compute_data_confidence(
            candidate,
            user,
            selected_contract=candidate.option_chain[0],
            require_selected_contract=True,
        ).score

    assert max(scores.values()) - min(scores.values()) <= 2


def test_balanced_pool_no_strategy_monopoly() -> None:
    candidates = [
        _pipeline_candidate(strategy, ticker=f"{strategy[:3].upper()}S", event_score=100)
        for strategy in STRATEGIES
    ]
    candidates.extend(
        _pipeline_candidate(
            strategy,
            ticker=f"{strategy[:3].upper()}{index}",
            event_score=35,
            strength="average",
        )
        for strategy in STRATEGIES
        for index in range(1, 5)
    )

    finalists = _select_decision_finalists(candidates)

    assert len({item.context.strategy_source for item in finalists}) >= 3


def test_weak_event_signal_does_not_make_c_uncompetitive() -> None:
    candidate = _candidate(
        "pead_continuation",
        event_score=50,
        strength="average",
        previous_earnings_move_percent=Decimal("0.05"),
    )

    result = score_candidate(candidate, _user())

    assert result.final_score >= 60


def test_d_with_strong_sector_signal_beats_a_with_average_earnings() -> None:
    sector_rs = score_candidate(
        _candidate(
            "sector_relative_strength",
            event_score=95,
            strength="strong",
            earnings_date=None,
            previous_earnings_move_percent=None,
        ),
        _user(),
    )
    average_catalyst = score_candidate(
        _candidate(
            "catalyst_confluence",
            event_score=None,
            strength="average",
            previous_earnings_move_percent=Decimal("0.05"),
        ),
        _user(),
    )

    assert sector_rs.final_score > average_catalyst.final_score


def test_e_with_fresh_active_13d_beats_a_with_no_surprise() -> None:
    activist = score_candidate(
        _candidate(
            "activist_13d_followthrough",
            event_score=95,
            strength="strong",
            earnings_date=None,
            previous_earnings_move_percent=None,
        ),
        _user(),
    )
    no_surprise_catalyst = score_candidate(
        _candidate(
            "catalyst_confluence",
            event_score=None,
            strength="soft",
            previous_earnings_move_percent=Decimal("0.00"),
        ),
        _user(),
    )

    assert activist.final_score > no_surprise_catalyst.final_score


def test_no_strategy_gets_double_credit() -> None:
    assert {
        strategy: sum(weights.values()) for strategy, weights in _V2_WEIGHTS_BY_STRATEGY.items()
    } == dict.fromkeys(STRATEGIES, 85)
    assert {
        strategy: round(
            weights.identity
            + weights.earnings
            + weights.event
            + weights.market
            + weights.options
            + weights.cross_source
            + weights.calculation,
            2,
        )
        for strategy, weights in _V2_CONFIDENCE.items()
    } == dict.fromkeys(STRATEGIES, 0.97)

    for strategy in STRATEGIES:
        candidate = _candidate(strategy, event_score=100)
        confidence = compute_data_confidence(
            candidate,
            _user(),
            selected_contract=candidate.option_chain[0],
            require_selected_contract=True,
        )
        direction = score_direction(candidate, data_confidence_score=confidence.score)

        assert direction.score <= 85
        assert confidence.score <= 97


def test_inconsistent_history_penalty_only_fires_for_strategy_a() -> None:
    user = _user()
    seen_codes = {}
    for strategy in STRATEGIES:
        candidate = _candidate(
            strategy,
            event_score=80,
            previous_earnings_move_percent=Decimal("0.02"),
        )
        direction = score_direction(candidate, data_confidence_score=85)
        penalties = collect_soft_penalties(candidate, user, candidate.option_chain[0], direction)
        seen_codes[strategy] = {penalty.code for penalty in penalties}

    assert "inconsistent_history" in seen_codes["catalyst_confluence"]
    for strategy in STRATEGIES[1:]:
        assert "inconsistent_history" not in seen_codes[strategy]


def _pipeline_candidate(
    strategy: StrategySource,
    *,
    ticker: str,
    event_score: int | None,
    strength: str = "strong",
) -> PipelineCandidate:
    context = _candidate(
        strategy,
        ticker=ticker,
        event_score=event_score,
        strength=strength,
        earnings_date=(
            None
            if strategy
            in {"coiled_setup", "sector_relative_strength", "activist_13d_followthrough"}
            else EARNINGS_DATE
        ),
        previous_earnings_move_percent=(
            None
            if strategy
            in {"coiled_setup", "sector_relative_strength", "activist_13d_followthrough"}
            else Decimal("0.09")
        ),
    )
    record = CandidateRecord(
        ticker=ticker,
        company_name=context.company_name,
        market_cap=context.market_snapshot.market_cap,
        earnings_date=context.earnings_date,
        current_price=context.market_snapshot.current_price,
        strategy_source=strategy,
        event_signal=context.event_signal,
    )
    return PipelineCandidate(
        record=record,
        context=context,
        evaluation=score_candidate(context, _user()),
        news_bundle=_news_bundle(ticker),
        sizing=None,
    )


def _candidate(
    strategy: StrategySource,
    *,
    ticker: str = "AAA",
    event_score: int | None,
    strength: str = "strong",
    earnings_date: date | None = EARNINGS_DATE,
    previous_earnings_move_percent: Decimal | None = Decimal("0.09"),
) -> CandidateContext:
    if strategy in {"coiled_setup", "sector_relative_strength", "activist_13d_followthrough"}:
        earnings_date = None
        previous_earnings_move_percent = None
    event_signal = (
        None
        if event_score is None
        else StrategyEventSignal(
            score=event_score,
            is_supportive=True,
            detail=f"{strategy} synthetic event score {event_score}",
        )
    )
    return CandidateContext(
        ticker=ticker,
        company_name=f"{ticker} Inc.",
        earnings_date=earnings_date,
        earnings_timing="BMO" if earnings_date else "unknown",
        market_snapshot=_market_snapshot(ticker=ticker, strength=strength),
        news_brief=_news_brief(),
        valuation_date=VALUATION_DATE,
        option_chain=(_contract(ticker),),
        strategy_source=strategy,
        event_signal=event_signal,
        verified_earnings_date=True,
        expected_move_percent=Decimal("0.08"),
        previous_earnings_move_percent=previous_earnings_move_percent,
    )


def _contract(ticker: str) -> OptionContractInput:
    return OptionContractInput(
        ticker=ticker,
        option_type="call",
        position_side="long",
        strike=Decimal("101"),
        expiry=date(2026, 5, 23),
        bid=Decimal("1.10"),
        ask=Decimal("1.20"),
        mid=Decimal("1.15"),
        volume=150,
        open_interest=500,
        implied_volatility=Decimal("0.38"),
        delta=Decimal("0.52"),
        gamma=Decimal("0.02"),
        theta=Decimal("-0.03"),
        vega=Decimal("0.05"),
    )


def _market_snapshot(*, ticker: str, strength: str) -> MarketSnapshot:
    values = {
        "strong": ("0.03", "0.08", "0.12", "0.18", "0.06", "1.60", "0.05"),
        "average": ("0.01", "0.025", "0.04", "0.06", "0.01", "1.10", "0.015"),
        "soft": ("0.00", "0.01", "0.02", "0.03", "0.00", "1.00", "0.00"),
    }[strength]
    one_day, five_day, twenty_day, fifty_day, relative_strength, volume_ratio, sector = values
    return MarketSnapshot(
        ticker=ticker,
        as_of_date=VALUATION_DATE,
        company_name=f"{ticker} Inc.",
        sector="Industrials",
        sector_etf="XLI",
        market_cap=Decimal("1000000000"),
        current_price=Decimal("100"),
        latest_volume=1_500_000,
        average_volume_20d=Decimal("1000000"),
        volume_vs_average_20d=Decimal(volume_ratio),
        stock_returns=ReturnMetrics(
            Decimal(one_day),
            Decimal(five_day),
            Decimal(twenty_day),
            Decimal(fifty_day),
        ),
        spy_returns=ReturnMetrics(
            Decimal("0.005"),
            Decimal("0.02"),
            Decimal("0.04"),
            Decimal("0.06"),
        ),
        qqq_returns=ReturnMetrics(
            Decimal("0.004"),
            Decimal("0.018"),
            Decimal("0.035"),
            Decimal("0.055"),
        ),
        sector_returns=ReturnMetrics(
            Decimal("0.01"),
            Decimal(sector),
            Decimal("0.08"),
            Decimal("0.12"),
        ),
        relative_strength_vs_spy=Decimal(relative_strength),
        relative_strength_vs_qqq=Decimal(relative_strength),
        relative_strength_vs_sector=Decimal(relative_strength),
        av_news_sentiment=None,
        price_source="test",
        overview_source="test",
        sources=("test",),
    )


def _user() -> UserContext:
    return UserContext(
        account_size=Decimal("20000"),
        risk_profile="Balanced",
        strategy_permission="long",
    )


def _news_brief() -> NewsBrief:
    return NewsBrief(
        neutral_contextual_evidence=["sector context"],
        key_uncertainty="Synthetic fixture.",
        summary="Synthetic scoring fixture.",
    )


def _news_bundle(ticker: str) -> NewsBundle:
    return NewsBundle(
        ticker=ticker,
        company_name=f"{ticker} Inc.",
        generated_at=datetime(2026, 5, 1, tzinfo=UTC),
        brief=_news_brief(),
    )
