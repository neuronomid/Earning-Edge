from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.scoring.confidence import compute_data_confidence
from app.scoring.contract import score_contract
from app.scoring.direction import score_direction
from app.scoring.expiry import is_valid_expiry, score_expiry_fit
from app.scoring.final import score_candidate
from app.scoring.penalties import collect_soft_penalties
from app.scoring.strategy_select import select_allowed_strategies
from app.scoring.types import CandidateContext, OptionContractInput, SourceConflict, UserContext
from app.scoring.vetoes import evaluate_hard_vetoes
from app.services.market_data.types import MarketSnapshot, ReturnMetrics
from app.services.news.types import NewsBrief


@pytest.mark.parametrize(
    ("candidate", "confidence_score", "expected_classification", "expected_score"),
    [
        (
            None,
            82,
            "bullish",
            98,
        ),
        (
            "bearish",
            80,
            "bearish",
            89,
        ),
        (
            "mixed",
            72,
            "neutral",
            54,
        ),
    ],
)
def test_direction_score_golden_table(
    candidate: str | None,
    confidence_score: int,
    expected_classification: str,
    expected_score: int,
) -> None:
    if candidate is None:
        context = _strong_bullish_candidate()
    elif candidate == "bearish":
        context = _strong_bearish_candidate()
    else:
        context = _mixed_candidate()

    result = score_direction(context, data_confidence_score=confidence_score)

    assert result.classification == expected_classification
    assert result.score == expected_score


def test_contract_score_golden_table_for_long_call() -> None:
    candidate = _strong_bullish_candidate(with_options=True)
    user = _user(account_size="20000")
    direction = score_direction(candidate, data_confidence_score=83)

    result = score_contract(candidate, user, candidate.option_chain[0], direction)

    assert result.strategy == "long_call"
    assert result.base_score == 97
    assert result.score == 97
    assert result.penalties == ()
    assert result.vetoes == ()


def test_contract_score_golden_table_for_short_put() -> None:
    contract = OptionContractInput(
        ticker="XYZ",
        option_type="put",
        position_side="short",
        strike=Decimal("95"),
        expiry=date(2026, 5, 9),
        bid=Decimal("1.50"),
        ask=Decimal("1.65"),
        volume=60,
        open_interest=250,
        implied_volatility=Decimal("0.68"),
        delta=Decimal("0.24"),
    )
    candidate = CandidateContext(
        ticker="XYZ",
        company_name="XYZ Inc.",
        earnings_date=date(2026, 5, 8),
        earnings_timing="BMO",
        market_snapshot=_market_snapshot(
            ticker="XYZ",
            company_name="XYZ Inc.",
            one_day="0.02",
            five_day="0.06",
            twenty_day="0.09",
            fifty_day="0.12",
            volume_ratio="1.20",
            relative_strength="0.04",
            sector_five_day="0.03",
        ),
        news_brief=_news_brief(bullish=2, bearish=0, confidence=78),
        option_chain=(contract,),
        expected_move_percent=Decimal("0.06"),
        previous_earnings_move_percent=Decimal("0.09"),
    )
    user = _user(account_size="50000", strategy_permission="short")
    direction = score_direction(candidate, data_confidence_score=84)

    result = score_contract(candidate, user, contract, direction)

    assert result.strategy == "short_put"
    assert result.base_score == 84
    assert result.score == 84
    assert result.penalties == ()
    assert result.vetoes == ()


@pytest.mark.parametrize(
    ("earnings_timing", "expiry", "expected_valid", "expected_fit"),
    [
        ("BMO", date(2026, 5, 8), True, 8),
        ("AMC", date(2026, 5, 8), False, 0),
        ("BMO", date(2026, 6, 15), False, 0),
    ],
)
def test_expiry_rule_for_bmo_and_amc(
    earnings_timing: str,
    expiry: date,
    expected_valid: bool,
    expected_fit: int,
) -> None:
    valid = is_valid_expiry(expiry, date(2026, 5, 8), earnings_timing)  # type: ignore[arg-type]
    fit = score_expiry_fit(
        expiry,
        date(2026, 5, 8),
        earnings_timing,  # type: ignore[arg-type]
        "long_call",
        "Balanced",
    )

    assert valid is expected_valid
    assert fit == expected_fit


@pytest.mark.parametrize(
    ("candidate", "contract", "user", "expected_code"),
    [
        (
            lambda: replace(
                _strong_bullish_candidate(with_options=True),
                verified_earnings_date=False,
            ),
            lambda: _strong_bullish_candidate(with_options=True).option_chain[0],
            lambda: _user(account_size="20000"),
            "earnings_unverified",
        ),
        (
            lambda: _strong_bullish_candidate(with_options=True, earnings_timing="AMC"),
            lambda: replace(
                _strong_bullish_candidate(with_options=True).option_chain[0],
                expiry=date(2026, 5, 8),
            ),
            lambda: _user(account_size="20000"),
            "invalid_expiry",
        ),
        (
            lambda: _strong_bullish_candidate(with_options=True),
            lambda: replace(_strong_bullish_candidate(with_options=True).option_chain[0], ask=None),
            lambda: _user(account_size="20000"),
            "missing_ask",
        ),
        (
            lambda: _strong_bullish_candidate(with_options=True),
            lambda: replace(
                _strong_bullish_candidate(with_options=True).option_chain[0],
                volume=0,
                open_interest=0,
            ),
            lambda: _user(account_size="20000"),
            "dead_contract",
        ),
        (
            lambda: _strong_bullish_candidate(with_options=True),
            lambda: replace(
                _strong_bullish_candidate(with_options=True).option_chain[0],
                is_stale=True,
            ),
            lambda: _user(account_size="20000"),
            "stale_contract",
        ),
        (
            lambda: _strong_bullish_candidate(with_options=True),
            lambda: replace(
                _strong_bullish_candidate(with_options=True).option_chain[1],
                bid=Decimal("1.50"),
                ask=Decimal("1.65"),
            ),
            lambda: _user(account_size="50000", strategy_permission="long"),
            "short_disabled",
        ),
    ],
)
def test_hard_veto_matrix(
    candidate: Callable[[], CandidateContext],
    contract: Callable[[], OptionContractInput],
    user: Callable[[], UserContext],
    expected_code: str,
) -> None:
    candidate_context = candidate()
    chosen_contract = contract()
    user_context = user()

    vetoes = evaluate_hard_vetoes(candidate_context, user_context, chosen_contract)

    assert expected_code in {veto.code for veto in vetoes}


def test_soft_penalty_stacking_accumulates() -> None:
    contract = OptionContractInput(
        ticker="XYZ",
        option_type="call",
        position_side="long",
        strike=Decimal("110"),
        expiry=date(2026, 5, 30),
        bid=Decimal("0.60"),
        ask=Decimal("0.90"),
        volume=10,
        open_interest=80,
        implied_volatility=Decimal("0.82"),
        delta=Decimal("0.18"),
    )
    candidate = CandidateContext(
        ticker="XYZ",
        company_name="XYZ Inc.",
        earnings_date=date(2026, 5, 8),
        earnings_timing="BMO",
        market_snapshot=_market_snapshot(
            ticker="XYZ",
            company_name="XYZ Inc.",
            one_day="0.01",
            five_day="0.04",
            twenty_day="0.06",
            fifty_day="0.08",
            volume_ratio="1.05",
            relative_strength="0.03",
            sector_five_day="-0.02",
        ),
        news_brief=_news_brief(bullish=1, bearish=1, confidence=58),
        option_chain=(contract,),
        expected_move_percent=Decimal("0.08"),
        previous_earnings_move_percent=Decimal("0.03"),
    )
    user = _user(account_size="25000")
    direction = score_direction(candidate, data_confidence_score=76)

    penalties = collect_soft_penalties(candidate, user, contract, direction)

    assert [penalty.code for penalty in penalties] == [
        "mixed_news",
        "weak_sector_trend",
        "light_volume",
        "moderate_spread",
        "elevated_iv",
        "inconsistent_history",
    ]
    assert sum(penalty.score_delta for penalty in penalties) == -41


def test_confidence_override_blocks_recommendation_despite_high_score() -> None:
    candidate = _strong_bullish_candidate(with_options=True)
    user = _user(account_size="20000", openrouter_ok=False)

    result = score_candidate(candidate, user)

    assert result.final_score == 98
    assert result.confidence.score == 100
    assert result.action == "no_trade"
    assert result.confidence.blockers == ("OpenRouter API key is unavailable or invalid.",)


def test_strategy_mapping_and_final_output_choose_one_contract() -> None:
    candidate = _strong_bullish_candidate(with_options=True)
    user = _user(account_size="20000")

    selection = select_allowed_strategies(
        "bullish",
        user.strategy_permission,
        direction_score=98,
        option_chain=candidate.option_chain,
    )
    result = score_candidate(candidate, user)

    assert selection.allowed_strategies == ("long_call", "short_put")
    assert result.chosen_contract is not None
    assert result.chosen_contract.strategy == "long_call"
    assert {contract.strategy for contract in result.considered_contracts} == {
        "long_call",
        "short_put",
    }
    assert result.action == "recommend"


def test_data_confidence_logs_source_conflict_without_forcing_blocker() -> None:
    candidate = replace(
        _strong_bullish_candidate(with_options=True),
        source_conflicts=(
            SourceConflict(
                field="market_cap",
                severity="moderate",
                detail="TradingView and the backup overview disagreed on market cap.",
            ),
        ),
    )
    user = _user(account_size="20000")

    result = compute_data_confidence(
        candidate,
        user,
        selected_contract=candidate.option_chain[0],
        require_selected_contract=True,
    )

    assert result.score == 96
    assert result.blockers == ()
    assert any("market_cap" in note for note in result.notes)


def _strong_bullish_candidate(
    *,
    with_options: bool = False,
    earnings_timing: str = "BMO",
) -> CandidateContext:
    option_chain: tuple[OptionContractInput, ...] = ()
    if with_options:
        option_chain = (
            OptionContractInput(
                ticker="ABC",
                option_type="call",
                position_side="long",
                strike=Decimal("102"),
                expiry=date(2026, 5, 16),
                bid=Decimal("1.20"),
                ask=Decimal("1.30"),
                volume=120,
                open_interest=300,
                implied_volatility=Decimal("0.42"),
                delta=Decimal("0.55"),
            ),
            OptionContractInput(
                ticker="ABC",
                option_type="put",
                position_side="short",
                strike=Decimal("95"),
                expiry=date(2026, 5, 9),
                bid=Decimal("1.40"),
                ask=Decimal("1.55"),
                volume=80,
                open_interest=240,
                implied_volatility=Decimal("0.65"),
                delta=Decimal("0.28"),
            ),
        )

    return CandidateContext(
        ticker="ABC",
        company_name="ABC Inc.",
        earnings_date=date(2026, 5, 8),
        earnings_timing=earnings_timing,  # type: ignore[arg-type]
        market_snapshot=_market_snapshot(
            ticker="ABC",
            company_name="ABC Inc.",
            one_day="0.02",
            five_day="0.06",
            twenty_day="0.10",
            fifty_day="0.18",
            volume_ratio="1.40",
            relative_strength="0.05",
            sector_five_day="0.04",
        ),
        news_brief=_news_brief(bullish=2, bearish=0, confidence=80),
        option_chain=option_chain,
        expected_move_percent=Decimal("0.07"),
        previous_earnings_move_percent=Decimal("0.09"),
    )


def _strong_bearish_candidate() -> CandidateContext:
    return CandidateContext(
        ticker="ABC",
        company_name="ABC Inc.",
        earnings_date=date(2026, 5, 8),
        earnings_timing="AMC",
        market_snapshot=_market_snapshot(
            ticker="ABC",
            company_name="ABC Inc.",
            one_day="-0.03",
            five_day="-0.07",
            twenty_day="-0.12",
            fifty_day="-0.18",
            volume_ratio="1.30",
            relative_strength="-0.06",
            sector_five_day="-0.05",
        ),
        news_brief=_news_brief(bullish=0, bearish=3, confidence=78),
        expected_move_percent=Decimal("0.08"),
        previous_earnings_move_percent=Decimal("-0.10"),
    )


def _mixed_candidate() -> CandidateContext:
    return CandidateContext(
        ticker="ABC",
        company_name="ABC Inc.",
        earnings_date=date(2026, 5, 8),
        earnings_timing="unknown",
        market_snapshot=_market_snapshot(
            ticker="ABC",
            company_name="ABC Inc.",
            one_day="0.01",
            five_day="0.00",
            twenty_day="-0.01",
            fifty_day="0.01",
            volume_ratio="0.95",
            relative_strength="0.00",
            sector_five_day="0.00",
        ),
        news_brief=_news_brief(bullish=1, bearish=1, confidence=52),
        expected_move_percent=Decimal("0.05"),
        previous_earnings_move_percent=Decimal("0.01"),
    )


def _user(
    *,
    account_size: str,
    strategy_permission: str = "long_and_short",
    openrouter_ok: bool = True,
) -> UserContext:
    return UserContext(
        account_size=Decimal(account_size),
        risk_profile="Balanced",
        strategy_permission=strategy_permission,  # type: ignore[arg-type]
        max_contracts=3,
        has_valid_openrouter_api_key=openrouter_ok,
    )


def _market_snapshot(
    *,
    ticker: str,
    company_name: str,
    one_day: str,
    five_day: str,
    twenty_day: str,
    fifty_day: str,
    volume_ratio: str,
    relative_strength: str,
    sector_five_day: str,
) -> MarketSnapshot:
    return MarketSnapshot(
        ticker=ticker,
        as_of_date=date(2026, 5, 1),
        company_name=company_name,
        sector="Technology",
        sector_etf="XLK",
        market_cap=Decimal("1000000000"),
        current_price=Decimal("100"),
        latest_volume=1_400_000,
        average_volume_20d=Decimal("1000000"),
        volume_vs_average_20d=Decimal(volume_ratio),
        stock_returns=ReturnMetrics(
            one_day=Decimal(one_day),
            five_day=Decimal(five_day),
            twenty_day=Decimal(twenty_day),
            fifty_day=Decimal(fifty_day),
        ),
        spy_returns=ReturnMetrics(
            one_day=Decimal("0.005"),
            five_day=Decimal("0.02"),
            twenty_day=Decimal("0.04"),
            fifty_day=Decimal("0.06"),
        ),
        qqq_returns=ReturnMetrics(
            one_day=Decimal("0.006"),
            five_day=Decimal("0.025"),
            twenty_day=Decimal("0.05"),
            fifty_day=Decimal("0.08"),
        ),
        sector_returns=ReturnMetrics(
            one_day=Decimal("0.01"),
            five_day=Decimal(sector_five_day),
            twenty_day=Decimal("0.08"),
            fifty_day=Decimal("0.12"),
        ),
        relative_strength_vs_spy=Decimal(relative_strength),
        relative_strength_vs_qqq=Decimal(relative_strength),
        relative_strength_vs_sector=Decimal(relative_strength),
        av_news_sentiment=None,
        price_source="yfinance",
        overview_source="yfinance",
        sources=("yfinance",),
        confidence_adjustment=0,
        confidence_notes=(),
    )


def _news_brief(*, bullish: int, bearish: int, confidence: int) -> NewsBrief:
    return NewsBrief(
        bullish_evidence=[f"bullish-{index}" for index in range(bullish)],
        bearish_evidence=[f"bearish-{index}" for index in range(bearish)],
        neutral_contextual_evidence=["sector context"],
        key_uncertainty="Guidance still matters.",
        news_confidence=confidence,
    )
