from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import crypto
from app.db.models.user import User
from app.db.repositories.user_repo import UserRepository
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
from app.services.candidate_models import CandidateBatch, CandidateRecord
from app.services.market_data.types import ConfidenceNote, MarketSnapshot, ReturnMetrics
from app.services.news.types import NewsBrief, NewsBundle
from app.services.sizing import BROKER_MARGIN_DEPENDENT_TEXT
from app.services.sizing_types import SizingResult

DEFAULT_EARNINGS_DATE = date(2026, 5, 8)
DEFAULT_AS_OF_DATE = date(2026, 5, 1)
DEFAULT_BATCH_ROWS = (
    ("AMD", 900, 102),
    ("AAPL", 850, 190),
    ("MSFT", 820, 420),
    ("NFLX", 610, 810),
    ("JPM", 580, 240),
)


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
        self.calls.append(
            RecordedMessage(chat_id=chat_id, text=text, reply_markup=reply_markup)
        )
        return str(len(self.calls))


@dataclass(slots=True)
class StaticCandidateStep:
    batch: CandidateBatch

    async def execute(self) -> CandidateBatch:
        return self.batch


@dataclass(slots=True)
class StaticMarketDataStep:
    snapshots: dict[str, MarketSnapshot | Exception]

    async def execute(
        self,
        record: CandidateRecord,
        *,
        alpha_vantage_api_key: str | None,
    ) -> MarketSnapshot:
        del alpha_vantage_api_key
        payload = self.snapshots[record.ticker]
        if isinstance(payload, Exception):
            raise payload
        return payload


@dataclass(slots=True)
class StaticNewsStep:
    bundles: dict[str, NewsBundle | Exception]

    async def execute(
        self,
        record: CandidateRecord,
        *,
        openrouter_api_key: str,
    ) -> NewsBundle:
        del openrouter_api_key
        payload = self.bundles[record.ticker]
        if isinstance(payload, Exception):
            raise payload
        return payload


@dataclass(slots=True)
class StaticOptionsStep:
    chains: dict[str, tuple[OptionContractInput, ...] | Exception]

    async def execute(
        self,
        record: CandidateRecord,
        *,
        alpaca_api_key: str | None,
        alpaca_api_secret: str | None,
        strategy_permission: str,
    ) -> tuple[OptionContractInput, ...]:
        del alpaca_api_key, alpaca_api_secret, strategy_permission
        payload = self.chains.get(record.ticker, ())
        if isinstance(payload, Exception):
            raise payload
        return payload


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, name: str, value: str, *, ex: int, nx: bool) -> bool:
        del ex
        if nx and name in self.store:
            return False
        self.store[name] = value
        return True

    async def get(self, name: str) -> str | None:
        return self.store.get(name)

    async def delete(self, name: str) -> int:
        return 1 if self.store.pop(name, None) is not None else 0

    async def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        del script, numkeys
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


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


async def make_user(
    session: AsyncSession,
    *,
    telegram_chat_id: str,
    account_size: str = "20000.00",
    risk_profile: str = "Balanced",
    strategy_permission: str = "long_and_short",
    openrouter_api_key: str = "sk-or-test",
    alpaca_api_key: str | None = "alpaca-key",
    alpaca_api_secret: str | None = "alpaca-secret",
    alpha_vantage_api_key: str | None = None,
) -> User:
    crypto.reset_cache()
    return await UserRepository(session).add(
        User(
            telegram_chat_id=telegram_chat_id,
            account_size=Decimal(account_size),
            risk_profile=risk_profile,
            broker="IBKR",
            timezone_label="ET",
            timezone_iana="America/Toronto",
            strategy_permission=strategy_permission,
            max_contracts=3,
            openrouter_api_key_encrypted=crypto.encrypt(openrouter_api_key)
            if openrouter_api_key
            else None,
            alpaca_api_key_encrypted=crypto.encrypt(alpaca_api_key)
            if alpaca_api_key
            else None,
            alpaca_api_secret_encrypted=crypto.encrypt(alpaca_api_secret)
            if alpaca_api_secret
            else None,
            alpha_vantage_api_key_encrypted=crypto.encrypt(alpha_vantage_api_key)
            if alpha_vantage_api_key
            else None,
        )
    )


def sessionmaker_from(session: AsyncSession) -> async_sessionmaker[AsyncSession]:
    bind = session.bind
    assert bind is not None
    return async_sessionmaker(bind=bind, expire_on_commit=False, class_=AsyncSession)


def make_batch(
    *,
    rows: tuple[tuple[str, int, int], ...] = DEFAULT_BATCH_ROWS,
    screener_status: str = "success",
    fallback_used: bool = False,
    warning_text: str | None = None,
) -> CandidateBatch:
    records = tuple(
        make_record(ticker=ticker, market_cap=market_cap, current_price=price)
        for ticker, market_cap, price in rows
    )
    return CandidateBatch(
        candidates=records,
        screener_status=screener_status,  # type: ignore[arg-type]
        fallback_used=fallback_used,
        warning_text=warning_text,
    )


def make_record(
    *,
    ticker: str,
    market_cap: int,
    current_price: int | Decimal,
    company_name: str | None = None,
    earnings_date: date = DEFAULT_EARNINGS_DATE,
) -> CandidateRecord:
    return CandidateRecord(
        ticker=ticker,
        company_name=company_name or f"{ticker} Corp.",
        market_cap=Decimal(str(market_cap)),
        earnings_date=earnings_date,
        current_price=Decimal(str(current_price)),
        sector="Technology",
        sources=("fixture",),
    )


def make_snapshot(
    record: CandidateRecord,
    *,
    current_price: Decimal | None | object = ...,
    one_day: str = "0.01",
    five_day: str = "0.04",
    twenty_day: str = "0.07",
    fifty_day: str = "0.10",
    volume_ratio: str = "1.10",
    relative_strength_vs_spy: str = "0.03",
    relative_strength_vs_qqq: str = "0.02",
    relative_strength_vs_sector: str = "0.01",
    sector_five_day: str = "0.02",
    confidence_adjustment: int = 0,
    confidence_notes: tuple[ConfidenceNote, ...] = (),
) -> MarketSnapshot:
    resolved_price = (
        record.current_price if current_price is ... else current_price
    )
    return MarketSnapshot(
        ticker=record.ticker,
        as_of_date=DEFAULT_AS_OF_DATE,
        company_name=record.company_name,
        sector=record.sector,
        sector_etf="XLK",
        market_cap=record.market_cap,
        current_price=resolved_price,
        latest_volume=1_000_000,
        average_volume_20d=Decimal("900000"),
        volume_vs_average_20d=Decimal(volume_ratio),
        stock_returns=ReturnMetrics(
            one_day=Decimal(one_day),
            five_day=Decimal(five_day),
            twenty_day=Decimal(twenty_day),
            fifty_day=Decimal(fifty_day),
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
            five_day=Decimal(sector_five_day),
            twenty_day=Decimal("0.04"),
            fifty_day=Decimal("0.06"),
        ),
        relative_strength_vs_spy=Decimal(relative_strength_vs_spy),
        relative_strength_vs_qqq=Decimal(relative_strength_vs_qqq),
        relative_strength_vs_sector=Decimal(relative_strength_vs_sector),
        av_news_sentiment=None,
        price_source="fixture",
        overview_source="fixture",
        sources=("fixture",),
        confidence_adjustment=confidence_adjustment,
        confidence_notes=confidence_notes,
    )


def make_news_bundle(
    record: CandidateRecord,
    *,
    bullish: tuple[str, ...] | None = None,
    bearish: tuple[str, ...] | None = None,
    neutral: tuple[str, ...] | None = None,
    key_uncertainty: str = "Guidance tone still matters.",
    news_confidence: int = 72,
) -> NewsBundle:
    return NewsBundle(
        ticker=record.ticker,
        company_name=record.company_name,
        generated_at=datetime.now(tz=UTC),
        search_results=(),
        articles=(),
        brief=NewsBrief(
            bullish_evidence=list(
                bullish or (f"{record.ticker} had supportive setup notes.",)
            ),
            bearish_evidence=list(bearish or ()),
            neutral_contextual_evidence=list(
                neutral or ("Sector context stayed constructive.",)
            ),
            key_uncertainty=key_uncertainty,
            news_confidence=news_confidence,
        ),
        used_ir_fallback=False,
    )


def make_contract(
    ticker: str,
    *,
    option_type: str,
    position_side: str,
    strike: str,
    expiry: date = date(2026, 5, 16),
    bid: str = "1.10",
    ask: str = "1.25",
    volume: int = 120,
    open_interest: int = 320,
    implied_volatility: str | None = "0.44",
    delta: str | None = "0.52",
    source: str = "fixture",
) -> OptionContractInput:
    return OptionContractInput(
        ticker=ticker,
        option_type=option_type,  # type: ignore[arg-type]
        position_side=position_side,  # type: ignore[arg-type]
        strike=Decimal(strike),
        expiry=expiry,
        bid=Decimal(bid),
        ask=Decimal(ask),
        volume=volume,
        open_interest=open_interest,
        implied_volatility=None if implied_volatility is None else Decimal(implied_volatility),
        delta=None if delta is None else Decimal(delta),
        source=source,
    )
