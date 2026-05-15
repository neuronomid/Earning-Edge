from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from app.core.logging import get_logger
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.services.market_data.service import (
    MarketDataService,
    MarketDataUnavailableError,
    get_market_data_service,
)
from app.services.options.alpaca_client import (
    AlpacaAuthenticationError,
    AlpacaOptionsClient,
    AlpacaUnavailableError,
    build_occ_symbol,
)
from app.services.options.types import OptionContract
from app.services.options.yfinance_client import YFinanceOptionsClient
from app.services.user_service import decrypt_or_none


@dataclass(frozen=True, slots=True)
class PositionQuoteSnapshot:
    ticker: str
    option_type: str
    position_side: str
    strike: Decimal
    expiry: date
    underlying_price: Decimal | None
    option_bid: Decimal | None
    option_ask: Decimal | None
    option_mid: Decimal | None
    liquidation_premium: Decimal | None
    implied_volatility: Decimal | None
    delta: Decimal | None
    gamma: Decimal | None
    theta: Decimal | None
    vega: Decimal | None
    source: str
    status: Literal["complete", "partial", "unavailable"]
    notes: tuple[str, ...] = ()


class PositionSnapshotService:
    def __init__(
        self,
        *,
        alpaca: AlpacaOptionsClient | None = None,
        yfinance: YFinanceOptionsClient | None = None,
        market_data: MarketDataService | None = None,
    ) -> None:
        self.alpaca = alpaca or AlpacaOptionsClient()
        self.yfinance = yfinance or YFinanceOptionsClient()
        self.market_data = market_data or get_market_data_service()
        self.logger = get_logger(__name__)

    async def fetch_current(
        self,
        *,
        user: User,
        recommendation: Recommendation,
        today: date | None = None,
    ) -> PositionQuoteSnapshot:
        today = today or date.today()
        notes: list[str] = []
        underlying_price = await self._fetch_underlying(user, recommendation, notes)

        alpaca_contract = await self._fetch_alpaca_contract(user, recommendation, today, notes)
        if alpaca_contract is not None:
            return _snapshot_from_contract(
                recommendation=recommendation,
                contract=alpaca_contract,
                underlying_price=underlying_price,
                notes=tuple(notes),
            )

        yf_contract = await self._fetch_yfinance_contract(recommendation, today, notes)
        if yf_contract is not None:
            return _snapshot_from_contract(
                recommendation=recommendation,
                contract=yf_contract,
                underlying_price=underlying_price,
                notes=tuple(notes),
            )

        return _unavailable_snapshot(
            recommendation,
            underlying_price=underlying_price,
            notes=tuple(notes or ["option_contract_unavailable"]),
        )

    async def _fetch_underlying(
        self,
        user: User,
        recommendation: Recommendation,
        notes: list[str],
    ) -> Decimal | None:
        api_key = decrypt_or_none(user.alpha_vantage_api_key_encrypted)
        try:
            snapshot = await self.market_data.fetch(
                recommendation.ticker,
                alpha_vantage_api_key=api_key,
                refresh=True,
            )
        except (MarketDataUnavailableError, RuntimeError, ValueError) as exc:
            notes.append(f"underlying_unavailable:{exc}")
            return None
        return snapshot.current_price

    async def _fetch_alpaca_contract(
        self,
        user: User,
        recommendation: Recommendation,
        today: date,
        notes: list[str],
    ) -> OptionContract | None:
        api_key = decrypt_or_none(user.alpaca_api_key_encrypted)
        api_secret = decrypt_or_none(user.alpaca_api_secret_encrypted)
        if not api_key or not api_secret:
            notes.append("alpaca_credentials_missing")
            return None

        occ_symbol = build_occ_symbol(
            recommendation.ticker,
            expiry=recommendation.expiry,
            option_type=recommendation.option_type,
            strike=recommendation.strike,
        )
        try:
            contracts = await self.alpaca.fetch_chain(
                recommendation.ticker,
                api_key=api_key,
                api_secret=api_secret,
                expiry_window_days=max((recommendation.expiry - today).days, 1),
                today=today,
                symbols=[occ_symbol],
            )
        except (AlpacaAuthenticationError, AlpacaUnavailableError, RuntimeError) as exc:
            notes.append(f"alpaca_unavailable:{exc}")
            return None
        contract = _match_contract(contracts, recommendation, expected_symbol=occ_symbol)
        if contract is None:
            notes.append("alpaca_contract_not_found")
        return contract

    async def _fetch_yfinance_contract(
        self,
        recommendation: Recommendation,
        today: date,
        notes: list[str],
    ) -> OptionContract | None:
        try:
            contracts = await self.yfinance.fetch_chain(
                recommendation.ticker,
                expiry_window_days=max((recommendation.expiry - today).days, 1),
                today=today,
            )
        except RuntimeError as exc:
            notes.append(f"yfinance_unavailable:{exc}")
            return None
        contract = _match_contract(contracts, recommendation)
        if contract is None:
            notes.append("yfinance_contract_not_found")
        return contract


def _snapshot_from_contract(
    *,
    recommendation: Recommendation,
    contract: OptionContract,
    underlying_price: Decimal | None,
    notes: tuple[str, ...],
) -> PositionQuoteSnapshot:
    liquidation, premium_notes = _liquidation_premium(contract, recommendation.position_side)
    all_notes = (*notes, *premium_notes)
    status: Literal["complete", "partial", "unavailable"]
    if liquidation is None:
        status = "unavailable"
    elif underlying_price is None or premium_notes:
        status = "partial"
    else:
        status = "complete"
    return PositionQuoteSnapshot(
        ticker=recommendation.ticker,
        option_type=recommendation.option_type,
        position_side=recommendation.position_side,
        strike=recommendation.strike,
        expiry=recommendation.expiry,
        underlying_price=underlying_price,
        option_bid=contract.bid,
        option_ask=contract.ask,
        option_mid=contract.mid,
        liquidation_premium=liquidation,
        implied_volatility=contract.implied_volatility,
        delta=contract.delta,
        gamma=contract.gamma,
        theta=contract.theta,
        vega=contract.vega,
        source=contract.source,
        status=status,
        notes=all_notes,
    )


def _unavailable_snapshot(
    recommendation: Recommendation,
    *,
    underlying_price: Decimal | None,
    notes: tuple[str, ...],
) -> PositionQuoteSnapshot:
    return PositionQuoteSnapshot(
        ticker=recommendation.ticker,
        option_type=recommendation.option_type,
        position_side=recommendation.position_side,
        strike=recommendation.strike,
        expiry=recommendation.expiry,
        underlying_price=underlying_price,
        option_bid=None,
        option_ask=None,
        option_mid=None,
        liquidation_premium=None,
        implied_volatility=None,
        delta=None,
        gamma=None,
        theta=None,
        vega=None,
        source="none",
        status="unavailable",
        notes=notes,
    )


def _liquidation_premium(
    contract: OptionContract,
    position_side: str,
) -> tuple[Decimal | None, tuple[str, ...]]:
    if position_side.lower() == "short":
        if contract.ask is not None:
            return contract.ask, ()
        fallback = contract.mid or contract.last_trade_price or contract.bid
        return fallback, ("short_liquidation_ask_missing",) if fallback is not None else ()
    if contract.bid is not None:
        return contract.bid, ()
    fallback = contract.mid or contract.last_trade_price or contract.ask
    return fallback, ("long_liquidation_bid_missing",) if fallback is not None else ()


def _match_contract(
    contracts: tuple[OptionContract, ...],
    recommendation: Recommendation,
    *,
    expected_symbol: str | None = None,
) -> OptionContract | None:
    symbol = expected_symbol or build_occ_symbol(
        recommendation.ticker,
        expiry=recommendation.expiry,
        option_type=recommendation.option_type,
        strike=recommendation.strike,
    )
    for contract in contracts:
        if contract.symbol == symbol:
            return contract
    target_strike = Decimal(str(recommendation.strike))
    target_type = recommendation.option_type.lower()
    for contract in contracts:
        if (
            contract.option_type == target_type
            and contract.expiry == recommendation.expiry
            and contract.strike == target_strike
        ):
            return contract
    return None
