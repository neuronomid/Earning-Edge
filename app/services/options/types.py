from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.scoring.types import OptionContractInput, OptionType, PositionSide


@dataclass(slots=True, frozen=True)
class OptionContract:
    ticker: str
    option_type: OptionType
    strike: Decimal
    expiry: date
    bid: Decimal | None = None
    ask: Decimal | None = None
    mid: Decimal | None = None
    last_trade_price: Decimal | None = None
    volume: int | None = None
    open_interest: int | None = None
    implied_volatility: Decimal | None = None
    delta: Decimal | None = None
    gamma: Decimal | None = None
    theta: Decimal | None = None
    vega: Decimal | None = None
    rho: Decimal | None = None
    spread_absolute: Decimal | None = None
    spread_percent: Decimal | None = None
    source: str = "unknown"
    symbol: str | None = None
    quote_timestamp: date | None = None
    is_tradable: bool = True
    is_stale: bool = False

    def with_position_side(self, position_side: PositionSide) -> OptionContractInput:
        return OptionContractInput(
            ticker=self.ticker,
            option_type=self.option_type,
            position_side=position_side,
            strike=self.strike,
            expiry=self.expiry,
            bid=self.bid,
            ask=self.ask,
            mid=self.mid,
            volume=self.volume,
            open_interest=self.open_interest,
            implied_volatility=self.implied_volatility,
            delta=self.delta,
            theta=self.theta,
            source=self.source,
            quote_timestamp=self.quote_timestamp,
            is_tradable=self.is_tradable,
            is_stale=self.is_stale,
        )


@dataclass(slots=True, frozen=True)
class OptionsChain:
    as_of_date: date | None
    contracts: tuple[OptionContract, ...]
    sources: tuple[str, ...]
    fallback_used: bool = False
    confidence_notes: tuple[str, ...] = ()
