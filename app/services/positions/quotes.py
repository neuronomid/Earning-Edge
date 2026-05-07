from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.logging import get_logger
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.services.options.alpaca_client import (
    AlpacaAuthenticationError,
    AlpacaOptionsClient,
    AlpacaUnavailableError,
    build_occ_symbol,
)
from app.services.options.types import OptionContract
from app.services.options.yfinance_client import YFinanceOptionsClient
from app.services.user_service import decrypt_or_none

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BidAskQuote:
    bid: Decimal | None
    ask: Decimal | None
    source: str


async def fetch_bid_ask(
    *,
    user: User,
    recommendation: Recommendation,
    today: date | None = None,
    alpaca: AlpacaOptionsClient | None = None,
    yfinance: YFinanceOptionsClient | None = None,
) -> BidAskQuote | None:
    today = today or date.today()
    alpaca = alpaca or AlpacaOptionsClient()
    yfinance = yfinance or YFinanceOptionsClient()

    quote = await _fetch_alpaca_quote(alpaca, recommendation, user, today=today)
    if quote is not None:
        return quote
    return await _fetch_yfinance_quote(yfinance, recommendation, today=today)


async def _fetch_alpaca_quote(
    alpaca: AlpacaOptionsClient,
    recommendation: Recommendation,
    user: User,
    *,
    today: date,
) -> BidAskQuote | None:
    api_key = decrypt_or_none(user.alpaca_api_key_encrypted)
    api_secret = decrypt_or_none(user.alpaca_api_secret_encrypted)
    if not api_key or not api_secret:
        return None
    days_to_expiry = max((recommendation.expiry - today).days, 1)
    try:
        contracts = await alpaca.fetch_chain(
            recommendation.ticker,
            api_key=api_key,
            api_secret=api_secret,
            expiry_window_days=days_to_expiry,
            today=today,
        )
    except (AlpacaAuthenticationError, AlpacaUnavailableError, RuntimeError) as exc:
        logger.warning(
            "positions_alpaca_quote_failed",
            ticker=recommendation.ticker,
            error=str(exc),
        )
        return None
    contract = _match_contract(
        contracts,
        ticker=recommendation.ticker,
        option_type=recommendation.option_type,
        strike=recommendation.strike,
        expiry=recommendation.expiry,
    )
    if contract is None:
        return None
    return BidAskQuote(bid=contract.bid, ask=contract.ask, source="alpaca")


async def _fetch_yfinance_quote(
    yfinance: YFinanceOptionsClient,
    recommendation: Recommendation,
    *,
    today: date,
) -> BidAskQuote | None:
    days_to_expiry = max((recommendation.expiry - today).days, 1)
    try:
        contracts = await yfinance.fetch_chain(
            recommendation.ticker,
            expiry_window_days=days_to_expiry,
            today=today,
        )
    except RuntimeError as exc:
        logger.warning(
            "positions_yfinance_quote_failed",
            ticker=recommendation.ticker,
            error=str(exc),
        )
        return None
    contract = _match_contract(
        contracts,
        ticker=recommendation.ticker,
        option_type=recommendation.option_type,
        strike=recommendation.strike,
        expiry=recommendation.expiry,
    )
    if contract is None:
        return None
    return BidAskQuote(bid=contract.bid, ask=contract.ask, source="yfinance")


def _match_contract(
    contracts: tuple[OptionContract, ...],
    *,
    ticker: str,
    option_type: str,
    strike: Decimal,
    expiry: date,
) -> OptionContract | None:
    expected_symbol = build_occ_symbol(
        ticker,
        expiry=expiry,
        option_type=option_type,
        strike=strike,
    )
    for contract in contracts:
        if contract.symbol == expected_symbol:
            return contract
    target_strike = Decimal(str(strike))
    target_type = option_type.lower()
    for contract in contracts:
        if (
            contract.option_type == target_type
            and contract.expiry == expiry
            and contract.strike == target_strike
        ):
            return contract
    return None
