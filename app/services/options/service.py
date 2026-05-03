from __future__ import annotations

from dataclasses import replace
from datetime import date
from functools import lru_cache

from app.core.logging import get_logger
from app.scoring.types import OptionContractInput, StrategyPermission
from app.services.options.alpaca_client import (
    AlpacaAuthenticationError,
    AlpacaOptionsClient,
    AlpacaUnavailableError,
)
from app.services.options.types import OptionContract, OptionsChain
from app.services.options.yfinance_client import YFinanceOptionsClient


class OptionsUnavailableError(RuntimeError):
    """Raised when no usable option chain can be produced for a ticker."""


class OptionsService:
    def __init__(
        self,
        *,
        alpaca: AlpacaOptionsClient | None = None,
        yfinance: YFinanceOptionsClient | None = None,
        logger=None,
    ) -> None:
        self.alpaca = alpaca or AlpacaOptionsClient()
        self.yfinance = yfinance or YFinanceOptionsClient()
        self.logger = logger or get_logger(__name__)
        self._cache: dict[tuple[str, date, str], OptionsChain] = {}

    async def get_chain(
        self,
        ticker: str,
        *,
        alpaca_api_key: str | None,
        alpaca_api_secret: str | None,
        strategy_permission: StrategyPermission,
        earnings_date: date | None = None,
        today: date | None = None,
    ) -> tuple[OptionContractInput, ...]:
        as_of_date = today or date.today()
        use_alpaca = bool(alpaca_api_key and alpaca_api_secret)
        cache_source = "alpaca" if use_alpaca else "yfinance"
        cache_key = (ticker.upper(), as_of_date, cache_source)
        chain = self._cache.get(cache_key)
        if chain is None:
            chain = await self._fetch_chain(
                ticker=ticker,
                alpaca_api_key=alpaca_api_key or "",
                alpaca_api_secret=alpaca_api_secret or "",
                use_alpaca=use_alpaca,
                earnings_date=earnings_date,
                today=as_of_date,
            )
            resolved_source = "alpaca" if "alpaca" in chain.sources else "yfinance"
            self._cache[(ticker.upper(), as_of_date, resolved_source)] = chain

        expanded = _expand_contracts(
            _normalize_ticker(chain.contracts, ticker),
            strategy_permission=strategy_permission,
        )
        if not expanded:
            raise OptionsUnavailableError(
                f"No usable option contracts were available for {ticker}."
            )
        return expanded

    async def _fetch_chain(
        self,
        *,
        ticker: str,
        alpaca_api_key: str,
        alpaca_api_secret: str,
        use_alpaca: bool,
        earnings_date: date | None,
        today: date,
    ) -> OptionsChain:
        expiry_window_days = _expiry_window_days(today=today, earnings_date=earnings_date)
        sources: list[str] = []

        if use_alpaca:
            last_error: Exception | None = None
            for symbol in _ticker_variants(ticker):
                try:
                    contracts = await self.alpaca.fetch_chain(
                        symbol,
                        api_key=alpaca_api_key,
                        api_secret=alpaca_api_secret,
                        expiry_window_days=expiry_window_days,
                        today=today,
                    )
                    if contracts:
                        sources.append("alpaca")
                        self.logger.info(
                            "options_chain_loaded",
                            ticker=ticker,
                            source="alpaca",
                            contract_count=len(contracts),
                        )
                        return OptionsChain(
                            as_of_date=today,
                            contracts=contracts,
                            sources=tuple(sources),
                        )
                except (AlpacaAuthenticationError, AlpacaUnavailableError) as exc:
                    last_error = exc
                    continue

            self.logger.warning(
                "options_chain_alpaca_fallback",
                ticker=ticker,
                error=None if last_error is None else str(last_error),
            )

        for symbol in _ticker_variants(ticker):
            try:
                contracts = await self.yfinance.fetch_chain(
                    symbol,
                    expiry_window_days=expiry_window_days,
                    today=today,
                )
                if contracts:
                    sources.append("yfinance")
                    self.logger.info(
                        "options_chain_loaded",
                        ticker=ticker,
                        source="yfinance",
                        contract_count=len(contracts),
                    )
                    return OptionsChain(
                        as_of_date=today,
                        contracts=contracts,
                        sources=tuple(sources),
                        fallback_used=use_alpaca,
                    )
            except RuntimeError as exc:
                self.logger.warning(
                    "options_chain_yfinance_failed",
                    ticker=ticker,
                    symbol=symbol,
                    error=str(exc),
                )

        raise OptionsUnavailableError(
            f"Alpaca and yfinance both returned no usable chain for {ticker}."
        )


@lru_cache(maxsize=1)
def get_options_service() -> OptionsService:
    return OptionsService()


def _normalize_ticker(
    contracts: tuple[OptionContract, ...],
    ticker: str,
) -> tuple[OptionContract, ...]:
    normalized = ticker.upper()
    return tuple(replace(contract, ticker=normalized) for contract in contracts)


def _expand_contracts(
    contracts: tuple[OptionContract, ...],
    *,
    strategy_permission: StrategyPermission,
) -> tuple[OptionContractInput, ...]:
    sides: tuple[str, ...]
    if strategy_permission == "long":
        sides = ("long",)
    elif strategy_permission == "short":
        sides = ("short",)
    else:
        sides = ("long", "short")

    expanded: list[OptionContractInput] = []
    for contract in sorted(
        contracts,
        key=lambda item: (item.expiry, item.option_type, item.strike),
    ):
        for side in sides:
            expanded.append(contract.with_position_side(side))  # type: ignore[arg-type]
    return tuple(expanded)


def _ticker_variants(ticker: str) -> tuple[str, ...]:
    raw = ticker.upper()
    candidates = [raw]
    if "-" in raw:
        candidates.append(raw.replace("-", "."))
    if "." in raw:
        candidates.append(raw.replace(".", "-"))

    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return tuple(ordered)


def _expiry_window_days(*, today: date, earnings_date: date | None) -> int:
    if earnings_date is None:
        return 45
    days_until_earnings = max((earnings_date - today).days, 0)
    return min(max(days_until_earnings + 30, 21), 60)
