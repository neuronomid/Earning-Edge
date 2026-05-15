"""25-candidate balanced fixture used by the end-to-end Phase 5 tests.

The fixture synthesises five candidates per strategy source (one strong, four
average) so that the orchestrator can run the full multi-strategy pipeline
deterministically without external services. Each ticker has a matching
``MarketSnapshot``, ``NewsBundle``, and option chain. Stubbed pipeline steps
expose those by-ticker lookups so the orchestrator's ``evaluate_batch`` and
``run`` paths can be exercised end-to-end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from app.scoring.types import OptionContractInput
from app.services.candidate_models import (
    CandidateBatch,
    CandidateRecord,
    StrategyEventSignal,
    StrategySource,
)
from app.services.market_data.types import MarketSnapshot, ReturnMetrics
from app.services.news.types import NewsArticle, NewsBrief, NewsBundle
from app.services.strategy_catalog import build_strategy_report

VALUATION_DATE = date(2026, 5, 1)
EARNINGS_DATE = date(2026, 5, 8)
EXPIRY_DATE = date(2026, 5, 22)
NEWS_GENERATED_AT = datetime(2026, 5, 1, 15, 55, tzinfo=UTC)

STRATEGIES: tuple[StrategySource, ...] = (
    "catalyst_confluence",
    "coiled_setup",
    "pead_continuation",
    "sector_relative_strength",
    "activist_13d_followthrough",
)


# Ticker scheme: <strategy prefix><1..5>. Index 1 is the "strong" candidate.
_TICKER_PREFIX: dict[StrategySource, str] = {
    "catalyst_confluence": "AAA",
    "coiled_setup": "BBB",
    "pead_continuation": "CCC",
    "sector_relative_strength": "DDD",
    "activist_13d_followthrough": "EEE",
}


def _ticker(strategy: StrategySource, index: int) -> str:
    return f"{_TICKER_PREFIX[strategy]}{index}"


def _is_strong(index: int) -> bool:
    return index == 1


def _strength(index: int) -> str:
    return "strong" if _is_strong(index) else "average"


@dataclass(slots=True, frozen=True)
class BalancedCandidateFixture:
    record: CandidateRecord
    market_snapshot: MarketSnapshot
    option_chain: tuple[OptionContractInput, ...]
    news_bundle: NewsBundle


def _market_snapshot(*, ticker: str, sector: str, strength: str) -> MarketSnapshot:
    profile = {
        "strong": ("0.025", "0.07", "0.11", "0.16", "0.05", "1.65", "0.04"),
        "average": ("0.005", "0.015", "0.025", "0.04", "0.005", "1.05", "0.01"),
    }[strength]
    one_day, five_day, twenty_day, fifty_day, relative_strength, volume_ratio, sector_5d = profile
    return MarketSnapshot(
        ticker=ticker,
        as_of_date=VALUATION_DATE,
        company_name=f"{ticker} Inc.",
        sector=sector,
        sector_etf="XLI" if sector == "Industrials" else "XLY",
        market_cap=Decimal("4500000000"),
        current_price=Decimal("100"),
        latest_volume=1_500_000,
        average_volume_20d=Decimal("1100000"),
        volume_vs_average_20d=Decimal(volume_ratio),
        stock_returns=ReturnMetrics(
            Decimal(one_day),
            Decimal(five_day),
            Decimal(twenty_day),
            Decimal(fifty_day),
        ),
        spy_returns=ReturnMetrics(
            Decimal("0.004"),
            Decimal("0.018"),
            Decimal("0.035"),
            Decimal("0.055"),
        ),
        qqq_returns=ReturnMetrics(
            Decimal("0.004"),
            Decimal("0.02"),
            Decimal("0.04"),
            Decimal("0.06"),
        ),
        sector_returns=ReturnMetrics(
            Decimal("0.006"),
            Decimal(sector_5d),
            Decimal("0.07"),
            Decimal("0.11"),
        ),
        relative_strength_vs_spy=Decimal(relative_strength),
        relative_strength_vs_qqq=Decimal(relative_strength),
        relative_strength_vs_sector=Decimal(relative_strength),
        av_news_sentiment=None,
        price_source="fixture",
        overview_source="fixture",
        sources=("fixture",),
    )


def _option_chain(ticker: str) -> tuple[OptionContractInput, ...]:
    return (
        OptionContractInput(
            ticker=ticker,
            option_type="call",
            position_side="long",
            strike=Decimal("100"),
            expiry=EXPIRY_DATE,
            bid=Decimal("2.30"),
            ask=Decimal("2.45"),
            mid=Decimal("2.375"),
            volume=420,
            open_interest=2200,
            implied_volatility=Decimal("0.38"),
            delta=Decimal("0.52"),
            gamma=Decimal("0.04"),
            theta=Decimal("-0.05"),
            vega=Decimal("0.12"),
            underlying_price=Decimal("100"),
            source="fixture",
        ),
        OptionContractInput(
            ticker=ticker,
            option_type="put",
            position_side="long",
            strike=Decimal("100"),
            expiry=EXPIRY_DATE,
            bid=Decimal("2.10"),
            ask=Decimal("2.25"),
            mid=Decimal("2.175"),
            volume=240,
            open_interest=1600,
            implied_volatility=Decimal("0.40"),
            delta=Decimal("-0.48"),
            gamma=Decimal("0.04"),
            theta=Decimal("-0.05"),
            vega=Decimal("0.12"),
            underlying_price=Decimal("100"),
            source="fixture",
        ),
    )


def _news_bundle(ticker: str, *, strategy: StrategySource, strength: str) -> NewsBundle:
    headline = "stayed constructive into the print" if strength == "strong" else "remained mixed"
    article = NewsArticle(
        title=f"{ticker} {headline}",
        url=f"https://example.com/{ticker.lower()}",
        snippet=f"{ticker} {headline}.",
        content=(
            f"{ticker} reflects the {strategy.replace('_', ' ')} thesis with sector context "
            f"that {headline}."
        ),
        source="example.com",
        published_at=NEWS_GENERATED_AT,
    )
    return NewsBundle(
        ticker=ticker,
        company_name=f"{ticker} Inc.",
        generated_at=NEWS_GENERATED_AT,
        search_results=(),
        articles=(article,),
        brief=NewsBrief(
            neutral_contextual_evidence=[f"{ticker} sector context held."],
            key_uncertainty="Synthetic balanced-pool fixture.",
            summary=f"{ticker} {headline}.",
            key_facts=[f"{ticker} {headline}."],
        ),
        used_ir_fallback=False,
        used_llm_summary=False,
    )


def _earnings_date_for(strategy: StrategySource) -> date | None:
    if strategy in {"coiled_setup", "sector_relative_strength", "activist_13d_followthrough"}:
        return None
    return EARNINGS_DATE


def _event_signal(*, strategy: StrategySource, strong: bool) -> StrategyEventSignal | None:
    if strategy == "catalyst_confluence":
        # Catalyst confluence does not populate an event signal — its scoring
        # row weights event-signal at 0.
        return None
    score = 92 if strong else 35
    return StrategyEventSignal(
        score=score,
        is_supportive=True,
        detail=f"{strategy} synthetic event score {score}",
    )


def _build_record(strategy: StrategySource, index: int) -> CandidateRecord:
    ticker = _ticker(strategy, index)
    strong = _is_strong(index)
    return CandidateRecord(
        ticker=ticker,
        company_name=f"{ticker} Inc.",
        market_cap=Decimal("4500000000"),
        earnings_date=_earnings_date_for(strategy),
        current_price=Decimal("100"),
        screener_rank=index,
        daily_change_percent=Decimal("0.025") if strong else Decimal("0.005"),
        volume=1_500_000,
        sector="Industrials" if strategy != "pead_continuation" else "Consumer Discretionary",
        sources=("finviz",) if strategy != "activist_13d_followthrough" else ("sec_edgar",),
        strategy_source=strategy,
        event_signal=_event_signal(strategy=strategy, strong=strong),
    )


def _build_fixture(strategy: StrategySource, index: int) -> BalancedCandidateFixture:
    record = _build_record(strategy, index)
    strength = _strength(index)
    snapshot = _market_snapshot(
        ticker=record.ticker,
        sector=record.sector or "Industrials",
        strength=strength,
    )
    return BalancedCandidateFixture(
        record=record,
        market_snapshot=snapshot,
        option_chain=_option_chain(record.ticker),
        news_bundle=_news_bundle(record.ticker, strategy=strategy, strength=strength),
    )


def build_balanced_fixtures() -> tuple[BalancedCandidateFixture, ...]:
    """Five candidates per strategy, 25 total. Index 1 of each is "strong"."""
    fixtures: list[BalancedCandidateFixture] = []
    for strategy in STRATEGIES:
        for index in range(1, 6):
            fixtures.append(_build_fixture(strategy, index))
    return tuple(fixtures)


def build_balanced_batch(
    *,
    successes: tuple[StrategySource, ...] = STRATEGIES,
) -> CandidateBatch:
    """Build a 25-row ``CandidateBatch`` with one ``StrategyRunReport`` per arm.

    Arms not in ``successes`` produce zero rows and an ``empty`` report so the
    fixture can be reused for partial-success scenarios.
    """
    records: list[CandidateRecord] = []
    reports = []
    for strategy in STRATEGIES:
        if strategy in successes:
            arm_rows = [_build_record(strategy, index) for index in range(1, 6)]
            records.extend(arm_rows)
            reports.append(
                build_strategy_report(
                    strategy,
                    status="success",
                    raw_row_count=len(arm_rows),
                    candidate_count=len(arm_rows),
                    finviz_candidate_count=(
                        0 if strategy == "activist_13d_followthrough" else len(arm_rows)
                    ),
                    backup_candidate_count=(
                        len(arm_rows) if strategy == "activist_13d_followthrough" else 0
                    ),
                )
            )
        else:
            reports.append(
                build_strategy_report(
                    strategy,
                    status="empty",
                    raw_row_count=0,
                    candidate_count=0,
                )
            )
    return CandidateBatch(
        candidates=tuple(records),
        screener_status="success" if len(successes) == len(STRATEGIES) else "partial",
        fallback_used=False,
        strategy_reports=tuple(reports),
    )


@dataclass(slots=True)
class BalancedFixtureIndex:
    """Lookups keyed by ticker for the stub pipeline steps."""

    fixtures: tuple[BalancedCandidateFixture, ...]
    market_snapshots: dict[str, MarketSnapshot] = field(default_factory=dict)
    option_chains: dict[str, tuple[OptionContractInput, ...]] = field(default_factory=dict)
    news_bundles: dict[str, NewsBundle] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for fixture in self.fixtures:
            ticker = fixture.record.ticker
            self.market_snapshots[ticker] = fixture.market_snapshot
            self.option_chains[ticker] = fixture.option_chain
            self.news_bundles[ticker] = fixture.news_bundle


def build_balanced_index(
    *,
    successes: tuple[StrategySource, ...] = STRATEGIES,
) -> BalancedFixtureIndex:
    fixtures = tuple(
        fixture
        for fixture in build_balanced_fixtures()
        if fixture.record.strategy_source in successes
    )
    return BalancedFixtureIndex(fixtures=fixtures)


class BalancedMarketDataStep:
    def __init__(self, index: BalancedFixtureIndex) -> None:
        self._index = index

    async def execute(
        self,
        record: CandidateRecord,
        *,
        alpha_vantage_api_key: str | None,
    ) -> MarketSnapshot:
        del alpha_vantage_api_key
        return self._index.market_snapshots[record.ticker]


class BalancedNewsStep:
    def __init__(self, index: BalancedFixtureIndex) -> None:
        self._index = index

    async def execute(
        self,
        record: CandidateRecord,
        *,
        openrouter_api_key: str,
        reference_dt: datetime | None = None,
    ) -> NewsBundle:
        del openrouter_api_key, reference_dt
        return self._index.news_bundles[record.ticker]


class BalancedOptionsStep:
    def __init__(self, index: BalancedFixtureIndex) -> None:
        self._index = index

    async def execute(
        self,
        record: CandidateRecord,
        *,
        alpaca_api_key: str | None,
        alpaca_api_secret: str | None,
        strategy_permission: str,
    ) -> tuple[OptionContractInput, ...]:
        del alpaca_api_key, alpaca_api_secret, strategy_permission
        return self._index.option_chains[record.ticker]
