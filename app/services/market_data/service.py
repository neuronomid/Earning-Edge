from __future__ import annotations

import asyncio
from collections.abc import Sequence
from decimal import Decimal
from functools import lru_cache
from typing import Any, Protocol

from app.core.logging import get_logger
from app.services.market_data.av_client import AlphaVantageClient
from app.services.market_data.cache import MarketDataCache
from app.services.market_data.indicators import (
    average_volume,
    compute_returns,
    relative_strength,
    volume_vs_average,
)
from app.services.market_data.types import (
    AlphaVantageSnapshot,
    ConfidenceNote,
    MarketSnapshot,
    PriceBar,
    SecuritySnapshot,
)
from app.services.market_data.yf_client import YFinanceClient
from app.services.run_lock import get_redis_client

PRICE_WARNING_DIFF = Decimal("0.02")
PRICE_SEVERE_DIFF = Decimal("0.05")
MARKET_CAP_WARNING_DIFF = Decimal("0.10")
MARKET_CAP_SEVERE_DIFF = Decimal("0.25")

SECTOR_ETF_MAP = {
    "basic materials": "XLB",
    "communication services": "XLC",
    "consumer cyclical": "XLY",
    "consumer defensive": "XLP",
    "energy": "XLE",
    "financial services": "XLF",
    "healthcare": "XLV",
    "industrials": "XLI",
    "real estate": "XLRE",
    "technology": "XLK",
    "technology services": "XLK",
    "utilities": "XLU",
}


class SecuritySource(Protocol):
    async def fetch_security(self, ticker: str) -> SecuritySnapshot: ...


class AlphaVantageSource(Protocol):
    async def fetch_snapshot(self, ticker: str, *, api_key: str) -> AlphaVantageSnapshot | None: ...


class SnapshotCache(Protocol):
    async def load(self, ticker: str) -> MarketSnapshot | None: ...

    async def store(self, snapshot: MarketSnapshot) -> None: ...


class MarketDataUnavailableError(RuntimeError):
    """Raised when phase-5 market data cannot produce a usable snapshot."""


class MarketDataService:
    def __init__(
        self,
        *,
        yfinance_client: SecuritySource | None = None,
        alpha_vantage_client: AlphaVantageSource | None = None,
        cache: SnapshotCache | None = None,
        logger: Any | None = None,
    ) -> None:
        self.yfinance_client = yfinance_client or YFinanceClient()
        self.alpha_vantage_client = alpha_vantage_client or AlphaVantageClient()
        self.cache = cache
        self.logger = logger or get_logger(__name__)

    async def fetch(
        self,
        ticker: str,
        *,
        alpha_vantage_api_key: str | None = None,
        refresh: bool = False,
    ) -> MarketSnapshot:
        normalized = ticker.strip().upper()
        if not normalized:
            raise ValueError("ticker is required")

        if self.cache is not None and not refresh:
            cached = await self.cache.load(normalized)
            if cached is not None:
                return cached

        av_key = (alpha_vantage_api_key or "").strip()
        yf_result, av_result = await asyncio.gather(
            self._load_yfinance(normalized),
            self._load_alpha_vantage(normalized, api_key=av_key),
        )

        if yf_result is None and av_result is None:
            raise MarketDataUnavailableError(
                f"No market data available for {normalized} from yfinance or Alpha Vantage"
            )

        stock_history, price_source = _select_history(yf_result, av_result)
        if not stock_history:
            raise MarketDataUnavailableError(f"No price history available for {normalized}")

        company_name, sector, market_cap, overview_source = _select_overview(yf_result, av_result)
        current_price = _select_current_price(yf_result, av_result, price_source=price_source)
        sector_etf = sector_to_etf(sector)

        benchmark_histories = await self._load_benchmarks(sector_etf)
        stock_returns = compute_returns(stock_history)
        spy_returns = compute_returns(benchmark_histories["SPY"])
        qqq_returns = compute_returns(benchmark_histories["QQQ"])
        sector_history = benchmark_histories.get(sector_etf or "")
        sector_returns = None if sector_history is None else compute_returns(sector_history)

        notes: list[ConfidenceNote] = []
        if price_source == "alphavantage":
            notes.append(
                ConfidenceNote(
                    source="alphavantage",
                    field="price_history",
                    detail=(
                        "Used Alpha Vantage price history because yfinance history "
                        "was unavailable."
                    ),
                    severity="warning",
                    score_delta=-5,
                )
            )

        notes.extend(_missing_benchmark_notes(sector_etf, benchmark_histories))
        notes.extend(self._conflict_notes(normalized, yf_result, av_result))

        snapshot = MarketSnapshot(
            ticker=normalized,
            as_of_date=stock_history[-1].date,
            company_name=company_name,
            sector=sector,
            sector_etf=sector_etf,
            market_cap=market_cap,
            current_price=current_price,
            latest_volume=stock_history[-1].volume,
            average_volume_20d=average_volume(stock_history),
            volume_vs_average_20d=volume_vs_average(stock_history),
            stock_returns=stock_returns,
            spy_returns=spy_returns,
            qqq_returns=qqq_returns,
            sector_returns=sector_returns,
            relative_strength_vs_spy=relative_strength(stock_returns, spy_returns),
            relative_strength_vs_qqq=relative_strength(stock_returns, qqq_returns),
            relative_strength_vs_sector=(
                None
                if sector_returns is None
                else relative_strength(stock_returns, sector_returns)
            ),
            av_news_sentiment=None if av_result is None else av_result.news_sentiment,
            price_source=price_source,
            overview_source=overview_source,
            sources=_compose_sources(yf_result, av_result),
            confidence_adjustment=sum(note.score_delta for note in notes),
            confidence_notes=tuple(notes),
        )

        if self.cache is not None:
            await self.cache.store(snapshot)
        return snapshot

    async def _load_yfinance(self, ticker: str) -> SecuritySnapshot | None:
        try:
            return await self.yfinance_client.fetch_security(ticker)
        except Exception as exc:
            self.logger.warning("market_data_yfinance_failed", ticker=ticker, error=str(exc))
            return None

    async def _load_alpha_vantage(
        self,
        ticker: str,
        *,
        api_key: str,
    ) -> AlphaVantageSnapshot | None:
        if not api_key:
            return None
        try:
            return await self.alpha_vantage_client.fetch_snapshot(ticker, api_key=api_key)
        except Exception as exc:
            self.logger.warning("market_data_alpha_vantage_failed", ticker=ticker, error=str(exc))
            return None

    async def _load_benchmarks(self, sector_etf: str | None) -> dict[str, tuple[Any, ...]]:
        tickers = ["SPY", "QQQ"]
        if sector_etf is not None:
            tickers.append(sector_etf)

        results = await asyncio.gather(
            *(self._load_yfinance(symbol) for symbol in tickers),
        )
        benchmark_histories: dict[str, tuple[Any, ...]] = {}
        for symbol, result in zip(tickers, results, strict=True):
            benchmark_histories[symbol] = () if result is None else result.history
        return benchmark_histories

    def _conflict_notes(
        self,
        ticker: str,
        yf_snapshot: SecuritySnapshot | None,
        av_snapshot: AlphaVantageSnapshot | None,
    ) -> Sequence[ConfidenceNote]:
        if yf_snapshot is None or av_snapshot is None:
            return ()

        notes: list[ConfidenceNote] = []
        price_note = _price_conflict_note(ticker, yf_snapshot, av_snapshot)
        if price_note is not None:
            notes.append(price_note)

        market_cap_note = _market_cap_conflict_note(ticker, yf_snapshot, av_snapshot)
        if market_cap_note is not None:
            notes.append(market_cap_note)
        return notes


def sector_to_etf(sector: str | None) -> str | None:
    if sector is None:
        return None
    normalized = sector.strip().lower()
    if normalized in SECTOR_ETF_MAP:
        return SECTOR_ETF_MAP[normalized]
    for candidate, etf in SECTOR_ETF_MAP.items():
        if candidate in normalized:
            return etf
    return None


def _select_history(
    yf_snapshot: SecuritySnapshot | None,
    av_snapshot: AlphaVantageSnapshot | None,
) -> tuple[tuple[PriceBar, ...], str]:
    if yf_snapshot is not None and yf_snapshot.history:
        return yf_snapshot.history, "yfinance"
    if av_snapshot is not None and av_snapshot.history:
        return av_snapshot.history, "alphavantage"
    return (), "unknown"


def _select_overview(
    yf_snapshot: SecuritySnapshot | None,
    av_snapshot: AlphaVantageSnapshot | None,
) -> tuple[str | None, str | None, Decimal | None, str]:
    sources: list[str] = []

    company_name = None
    if yf_snapshot is not None and yf_snapshot.company_name is not None:
        company_name = yf_snapshot.company_name
        sources.append("yfinance")
    elif av_snapshot is not None:
        company_name = av_snapshot.company_name
        if company_name is not None:
            sources.append("alphavantage")

    sector = None
    if yf_snapshot is not None and yf_snapshot.sector is not None:
        sector = yf_snapshot.sector
        if "yfinance" not in sources:
            sources.append("yfinance")
    elif av_snapshot is not None:
        sector = av_snapshot.sector
        if sector is not None and "alphavantage" not in sources:
            sources.append("alphavantage")

    market_cap = None
    if yf_snapshot is not None and yf_snapshot.market_cap is not None:
        market_cap = yf_snapshot.market_cap
        if "yfinance" not in sources:
            sources.append("yfinance")
    elif av_snapshot is not None:
        market_cap = av_snapshot.market_cap
        if market_cap is not None and "alphavantage" not in sources:
            sources.append("alphavantage")

    return company_name, sector, market_cap, _compose_source_label(sources)


def _select_current_price(
    yf_snapshot: SecuritySnapshot | None,
    av_snapshot: AlphaVantageSnapshot | None,
    *,
    price_source: str,
) -> Decimal | None:
    if price_source == "yfinance" and yf_snapshot is not None:
        return yf_snapshot.current_price or _latest_close(yf_snapshot.history)
    if price_source == "alphavantage" and av_snapshot is not None:
        return _latest_close(av_snapshot.history)
    return None


def _compose_sources(
    yf_snapshot: SecuritySnapshot | None,
    av_snapshot: AlphaVantageSnapshot | None,
) -> tuple[str, ...]:
    sources: list[str] = []
    if yf_snapshot is not None:
        sources.append("yfinance")
    if av_snapshot is not None:
        sources.append("alphavantage")
    return tuple(sources)


def _compose_source_label(sources: Sequence[str]) -> str:
    unique = tuple(dict.fromkeys(sources))
    if not unique:
        return "unknown"
    if len(unique) == 1:
        return unique[0]
    return "mixed"


def _missing_benchmark_notes(
    sector_etf: str | None,
    benchmark_histories: dict[str, tuple[Any, ...]],
) -> list[ConfidenceNote]:
    notes: list[ConfidenceNote] = []
    for symbol in ("SPY", "QQQ"):
        if benchmark_histories.get(symbol):
            continue
        notes.append(
            ConfidenceNote(
                source="yfinance",
                field=f"{symbol.lower()}_history",
                detail=f"{symbol} benchmark history was unavailable.",
                severity="warning",
                score_delta=-3,
            )
        )

    if sector_etf is not None and not benchmark_histories.get(sector_etf):
        notes.append(
            ConfidenceNote(
                source="yfinance",
                field="sector_history",
                detail=f"{sector_etf} sector ETF history was unavailable.",
                severity="warning",
                score_delta=-3,
            )
        )
    return notes


def _price_conflict_note(
    ticker: str,
    yf_snapshot: SecuritySnapshot,
    av_snapshot: AlphaVantageSnapshot,
) -> ConfidenceNote | None:
    yf_price = yf_snapshot.current_price or _latest_close(yf_snapshot.history)
    av_price = _latest_close(av_snapshot.history)
    if yf_price is None or av_price is None or min(yf_price, av_price) <= 0:
        return None

    diff_ratio = abs(yf_price - av_price) / min(yf_price, av_price)
    if diff_ratio < PRICE_WARNING_DIFF:
        return None

    severity = "warning"
    score_delta = -5
    if diff_ratio >= PRICE_SEVERE_DIFF:
        severity = "critical"
        score_delta = -15

    detail = (
        f"Price cross-check conflict for {ticker}: yfinance={yf_price} "
        f"vs Alpha Vantage={av_price}."
    )
    get_logger(__name__).warning(
        "market_data_conflict",
        ticker=ticker,
        field="current_price",
        yfinance=str(yf_price),
        alphavantage=str(av_price),
        relative_difference=str(diff_ratio),
        severity=severity,
    )
    return ConfidenceNote(
        source="alphavantage",
        field="current_price",
        detail=detail,
        severity=severity,
        score_delta=score_delta,
    )


def _market_cap_conflict_note(
    ticker: str,
    yf_snapshot: SecuritySnapshot,
    av_snapshot: AlphaVantageSnapshot,
) -> ConfidenceNote | None:
    yf_market_cap = yf_snapshot.market_cap
    av_market_cap = av_snapshot.market_cap
    if yf_market_cap is None or av_market_cap is None or min(yf_market_cap, av_market_cap) <= 0:
        return None

    diff_ratio = abs(yf_market_cap - av_market_cap) / min(yf_market_cap, av_market_cap)
    if diff_ratio < MARKET_CAP_WARNING_DIFF:
        return None

    severity = "warning"
    score_delta = -3
    if diff_ratio >= MARKET_CAP_SEVERE_DIFF:
        severity = "critical"
        score_delta = -10

    detail = (
        f"Market cap cross-check conflict for {ticker}: yfinance={yf_market_cap} "
        f"vs Alpha Vantage={av_market_cap}."
    )
    get_logger(__name__).warning(
        "market_data_conflict",
        ticker=ticker,
        field="market_cap",
        yfinance=str(yf_market_cap),
        alphavantage=str(av_market_cap),
        relative_difference=str(diff_ratio),
        severity=severity,
    )
    return ConfidenceNote(
        source="alphavantage",
        field="market_cap",
        detail=detail,
        severity=severity,
        score_delta=score_delta,
    )


def _latest_close(history: tuple[PriceBar, ...]) -> Decimal | None:
    if not history:
        return None
    return history[-1].close


@lru_cache(maxsize=1)
def get_market_data_service() -> MarketDataService:
    return MarketDataService(
        yfinance_client=YFinanceClient(),
        alpha_vantage_client=AlphaVantageClient(),
        cache=MarketDataCache(get_redis_client()),
    )
