from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.scoring.types import CandidateContext, DirectionResult, OptionContractInput
from app.services.exit_target import ExitTargetService
from app.services.market_data.types import MarketSnapshot, ReturnMetrics
from app.services.news.types import NewsBrief


def _context(*, current_price: str, expected_move_percent: str | None = "0.08") -> CandidateContext:
    return CandidateContext(
        ticker="AMD",
        company_name="AMD Corp.",
        earnings_date=date(2026, 5, 8),
        earnings_timing="AMC",
        market_snapshot=MarketSnapshot(
            ticker="AMD",
            as_of_date=date(2026, 5, 5),
            company_name="AMD Corp.",
            sector="Technology",
            sector_etf="XLK",
            market_cap=Decimal("1000"),
            current_price=Decimal(current_price),
            latest_volume=1_000_000,
            average_volume_20d=Decimal("900000"),
            volume_vs_average_20d=Decimal("1.10"),
            stock_returns=ReturnMetrics(None, None, None, None),
            spy_returns=ReturnMetrics(None, None, None, None),
            qqq_returns=ReturnMetrics(None, None, None, None),
            sector_returns=None,
            relative_strength_vs_spy=None,
            relative_strength_vs_qqq=None,
            relative_strength_vs_sector=None,
            av_news_sentiment=None,
            price_source="fixture",
            overview_source="fixture",
            sources=("fixture",),
        ),
        news_brief=NewsBrief(
            neutral_contextual_evidence=[],
            key_uncertainty="None",
        ),
        option_chain=(),
        expected_move_percent=None
        if expected_move_percent is None
        else Decimal(expected_move_percent),
    )


def _direction(score: int = 80) -> DirectionResult:
    return DirectionResult(
        classification="bullish",
        bias=Decimal("0.70"),
        score=score,
        factors=(),
        reasons=("Momentum stayed constructive.",),
    )


def test_exit_target_service_uses_full_greeks_when_available() -> None:
    service = ExitTargetService()
    contract = OptionContractInput(
        ticker="AMD",
        option_type="call",
        position_side="long",
        strike=Decimal("104"),
        expiry=date(2026, 5, 16),
        bid=Decimal("1.10"),
        ask=Decimal("1.30"),
        mid=Decimal("1.20"),
        implied_volatility=Decimal("0.44"),
        delta=Decimal("0.52"),
        gamma=Decimal("0.05"),
        theta=Decimal("-0.04"),
        vega=Decimal("0.10"),
    )

    target = service.build(_context(current_price="100"), contract, _direction())

    assert target is not None
    assert target.target_method == "full_greeks"
    assert target.target_stock_price > Decimal("100")
    assert target.target_option_price > Decimal("1.20")
    assert target.stop_loss_option_price == Decimal("0.65")
    assert target.exit_by_date == date(2026, 5, 8)


def test_exit_target_service_falls_back_to_delta_without_full_greeks() -> None:
    service = ExitTargetService()
    contract = OptionContractInput(
        ticker="AMD",
        option_type="call",
        position_side="long",
        strike=Decimal("104"),
        expiry=date(2026, 5, 16),
        bid=Decimal("1.10"),
        ask=Decimal("1.30"),
        mid=Decimal("1.20"),
        implied_volatility=Decimal("0.44"),
        delta=Decimal("0.52"),
    )

    target = service.build(_context(current_price="100"), contract, _direction())

    assert target is not None
    assert target.target_method == "delta_fallback"
    assert target.target_option_price > Decimal("1.20")


def test_exit_target_service_adds_short_put_buyback_target_and_stop() -> None:
    service = ExitTargetService()
    contract = OptionContractInput(
        ticker="AMD",
        option_type="put",
        position_side="short",
        strike=Decimal("96"),
        expiry=date(2026, 5, 16),
        bid=Decimal("1.20"),
        ask=Decimal("1.35"),
        mid=Decimal("1.28"),
    )

    target = service.build(_context(current_price="100"), contract, _direction())

    assert target is not None
    assert target.target_stock_price is None
    assert target.target_option_price == Decimal("0.60")
    assert target.stop_loss_option_price == Decimal("3.60")
    assert target.target_gain_percent == Decimal("50.00")
    assert target.target_method == "short_premium"


def test_exit_target_service_adds_short_call_underlying_stop() -> None:
    service = ExitTargetService()
    contract = OptionContractInput(
        ticker="AMD",
        option_type="call",
        position_side="short",
        strike=Decimal("105"),
        expiry=date(2026, 5, 16),
        bid=Decimal("1.00"),
        ask=Decimal("1.20"),
        mid=Decimal("1.10"),
        delta=Decimal("0.30"),
    )

    target = service.build(_context(current_price="100"), contract, _direction())

    assert target is not None
    assert target.target_option_price == Decimal("0.50")
    assert target.underlying_stop_price == Decimal("107.10")
    assert target.stop_loss_option_price == Decimal("3.23")
    assert target.target_method == "short_call_underlying"
