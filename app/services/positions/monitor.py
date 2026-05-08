from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.core.logging import get_logger
from app.db.models.open_position import OpenPosition
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.repositories.open_position_repo import OpenPositionRepository
from app.db.session import get_sessionmaker
from app.pipeline.orchestrator import AiogramNotifier, TelegramNotifier
from app.services.options.alpaca_client import (
    AlpacaAuthenticationError,
    AlpacaOptionsClient,
    AlpacaUnavailableError,
    build_occ_symbol,
)
from app.services.options.yfinance_client import YFinanceOptionsClient
from app.services.user_service import decrypt_or_none
from app.telegram.keyboards.settings import position_alert_keyboard

THRESHOLD_PROXIMITY = Decimal("0.10")
CONTRACT_MULTIPLIER = Decimal("100")


@dataclass(slots=True, frozen=True)
class PremiumQuote:
    premium: Decimal
    source: str


class PositionMonitor:
    def __init__(
        self,
        *,
        sessionmaker: Callable[[], Any] | None = None,
        yfinance: YFinanceOptionsClient | None = None,
        alpaca: AlpacaOptionsClient | None = None,
        notifier: TelegramNotifier | None = None,
        today_factory: Callable[[], date] | None = None,
        logger: Any | None = None,
    ) -> None:
        self.sessionmaker = sessionmaker or get_sessionmaker()
        self.yfinance = yfinance or YFinanceOptionsClient()
        self.alpaca = alpaca or AlpacaOptionsClient()
        self.notifier = notifier or AiogramNotifier()
        self.today_factory = today_factory or date.today
        self.logger = logger or get_logger(__name__)

    async def poll_open_positions(self) -> None:
        today = self.today_factory()
        now = datetime.now(UTC)
        async with self.sessionmaker() as session:
            repo = OpenPositionRepository(session)
            positions = await repo.list_active()

            # Group positions by ticker for batch Alpaca calls
            by_ticker: dict[str, list[tuple[OpenPosition, Recommendation, User]]] = defaultdict(list)
            for position in positions:
                recommendation = await session.get(Recommendation, position.recommendation_id)
                user = await session.get(User, position.user_id)
                if recommendation is None or user is None:
                    continue
                by_ticker[recommendation.ticker].append((position, recommendation, user))

            # Poll each ticker once, match all positions against result
            for ticker, group in by_ticker.items():
                await self._poll_ticker_group(session, ticker, group, today=today, now=now)

            await session.commit()

    async def _poll_ticker_group(
        self,
        session,
        ticker: str,
        group: list[tuple[OpenPosition, Recommendation, User]],
        *,
        today: date,
        now: datetime,
    ) -> None:
        if not group:
            return

        # Extract the first user from the group (all positions in group have same ticker)
        user = group[0][2]

        # Build list of OCC symbols we need
        symbols = [
            build_occ_symbol(
                rec.ticker,
                expiry=rec.expiry,
                option_type=rec.option_type,
                strike=rec.strike,
            )
            for _, rec, _ in group
        ]

        # Fetch all positions in this group with one Alpaca call
        quote_map = await self._fetch_quotes_for_group(ticker, symbols, user, today=today)

        # Process each position
        for position, recommendation, _ in group:
            occ_symbol = build_occ_symbol(
                recommendation.ticker,
                expiry=recommendation.expiry,
                option_type=recommendation.option_type,
                strike=recommendation.strike,
            )
            quote = quote_map.get(occ_symbol)
            if quote is None:
                continue

            await self._poll_position(session, position, recommendation, user, quote, today=today, now=now)

    async def _fetch_quotes_for_group(
        self,
        ticker: str,
        symbols: list[str],
        user: User,
        *,
        today: date,
    ) -> dict[str, PremiumQuote]:
        """Fetch quotes for multiple OCC symbols in one call. Returns map of symbol -> quote."""
        result: dict[str, PremiumQuote] = {}

        # Try Alpaca first
        api_key = decrypt_or_none(user.alpaca_api_key_encrypted)
        api_secret = decrypt_or_none(user.alpaca_api_secret_encrypted)
        if api_key and api_secret:
            alpaca_result = await self._fetch_alpaca_group(
                ticker, symbols, api_key, api_secret, today=today
            )
            if alpaca_result:
                return alpaca_result

        # Fallback to yfinance
        yfinance_result = await self._fetch_yfinance_group(ticker, symbols, today=today)
        return yfinance_result

    async def _fetch_alpaca_group(
        self,
        ticker: str,
        symbols: list[str],
        api_key: str,
        api_secret: str,
        *,
        today: date,
    ) -> dict[str, PremiumQuote]:
        """Fetch Alpaca quotes for a list of OCC symbols."""
        try:
            # Estimate expiry window from symbols (all same ticker, so pick any)
            # Alpaca needs an expiry_window_days to scope the query
            # Assume the most distant expiry is ~60 days out
            days_to_expiry = 60
            contracts = await self.alpaca.fetch_chain(
                ticker,
                api_key=api_key,
                api_secret=api_secret,
                expiry_window_days=days_to_expiry,
                today=today,
                symbols=symbols,
            )
        except (AlpacaAuthenticationError, AlpacaUnavailableError, RuntimeError) as exc:
            self.logger.warning(
                "position_alpaca_group_failed",
                ticker=ticker,
                error=str(exc),
            )
            return {}

        result: dict[str, PremiumQuote] = {}
        for contract in contracts:
            premium = _premium_from_contract(contract)
            if premium is not None:
                result[contract.symbol] = PremiumQuote(premium=premium, source="alpaca")
        return result

    async def _fetch_yfinance_group(
        self,
        ticker: str,
        symbols: list[str],
        *,
        today: date,
    ) -> dict[str, PremiumQuote]:
        """Fetch yfinance quotes. Returns best-effort map (may be partial)."""
        # yfinance doesn't support multi-symbol fetch, so we fetch the full chain once per ticker
        try:
            premium = await self.yfinance.fetch_premium(
                ticker,
                strike=None,  # Will fetch all
                expiry=None,
                option_type=None,
                today=today,
            )
        except RuntimeError as exc:
            self.logger.warning(
                "position_yfinance_group_failed",
                ticker=ticker,
                error=str(exc),
            )
            return {}

        # yfinance doesn't return individual symbols, so we return a dummy result
        # This is a limitation — yfinance should ideally fetch the chain and we match symbols
        # For now, treat as not found
        return {}

    async def _poll_position(
        self,
        session,
        position: OpenPosition,
        recommendation: Recommendation,
        user: User,
        quote: PremiumQuote,
        *,
        today: date,
        now: datetime,
    ) -> None:
        # Check expiry
        if today > recommendation.expiry:
            position.status = "closed_expired"
            position.close_at = datetime.now(UTC)
            from app.services.positions.account import apply_pnl_to_account

            apply_pnl_to_account(user, position, recommendation)
            await session.flush()
            return

        position.last_premium = quote.premium
        position.last_polled_at = datetime.now(UTC)
        position.last_data_source = quote.source

        alert_keys = _alerts_for_position(position, recommendation, quote.premium, today=today, now=now)
        for alert_key in alert_keys:
            await self._send_alert(position, recommendation, user, alert_key, quote.premium)
            # Increment alert counts for TP/SL (not for date-based alerts)
            if alert_key == "target_hit":
                position.target_alert_count += 1
            elif alert_key == "stop_hit":
                position.stop_alert_count += 1
            else:
                # Date-based alerts use alerts_sent for deduplication
                position.alerts_sent = [*list(position.alerts_sent or []), alert_key]

        await session.flush()

    async def _send_alert(
        self,
        position: OpenPosition,
        recommendation: Recommendation,
        user: User,
        alert_key: str,
        current_premium: Decimal,
    ) -> None:
        # Determine alert type for keyboard
        alert_type = None
        if alert_key == "target_hit":
            alert_type = "tp"
        elif alert_key == "stop_hit":
            alert_type = "sl"

        keyboard = position_alert_keyboard(str(position.id), alert_type=alert_type)

        await self.notifier.send_text(
            user.telegram_chat_id,
            _render_alert(recommendation, alert_key, current_premium),
            reply_markup=keyboard,
        )


async def poll_open_positions() -> None:
    await PositionMonitor().poll_open_positions()


def _alerts_for_position(
    position: OpenPosition,
    recommendation: Recommendation,
    current_premium: Decimal,
    *,
    today: date,
    now: datetime,
) -> list[str]:
    alerts: list[str] = []

    # Target price alert
    if not position.target_dismissed:
        # Check if mute period has expired
        if position.target_muted_until is None or now >= position.target_muted_until:
            target = recommendation.target_option_price
            if target is not None and target > 0:
                # First crossing: use >= logic
                if position.target_alert_count == 0 and current_premium >= target:
                    alerts.append("target_hit")
                # Subsequent crossings: require crossing from below
                elif position.target_alert_count > 0 and _crossed_target(
                    position.last_premium, current_premium, target
                ):
                    alerts.append("target_hit")

    # Stop loss alert
    if not position.stop_dismissed:
        # Check if mute period has expired
        if position.stop_muted_until is None or now >= position.stop_muted_until:
            stop = recommendation.stop_loss_option_price
            if stop is not None and stop > 0:
                # First crossing: use <= logic
                if position.stop_alert_count == 0 and current_premium <= stop:
                    alerts.append("stop_hit")
                # Subsequent crossings: require crossing from above
                elif position.stop_alert_count > 0 and _crossed_stop(
                    position.last_premium, current_premium, stop
                ):
                    alerts.append("stop_hit")

    # Date-based alerts (one-time only via alerts_sent)
    sent = set(position.alerts_sent or [])
    if (
        recommendation.exit_by_date is not None
        and today >= recommendation.exit_by_date
        and "exit_by_date" not in sent
    ):
        alerts.append("exit_by_date")
    if (recommendation.expiry - today).days <= 1 and "expiry_t_minus_1" not in sent:
        alerts.append("expiry_t_minus_1")

    return alerts


def _crossed_target(
    previous: Decimal | None,
    current: Decimal,
    threshold: Decimal | None,
) -> bool:
    return previous is not None and threshold is not None and previous < threshold <= current


def _crossed_stop(
    previous: Decimal | None,
    current: Decimal,
    threshold: Decimal | None,
) -> bool:
    return previous is not None and threshold is not None and previous > threshold >= current


def _premium_from_contract(contract) -> Decimal | None:
    """Extract the best available premium from a contract."""
    return contract.mid or contract.last_trade_price or contract.ask or contract.bid


def _render_alert(
    recommendation: Recommendation,
    alert_key: str,
    current_premium: Decimal,
) -> str:
    header = f"<b>{recommendation.ticker} position alert</b>"
    current = f"Current option premium: ${current_premium:.2f}"
    if alert_key == "target_hit":
        return "\n".join(
            [
                header,
                "",
                "Target price has been reached.",
                current,
                f"Target: ${recommendation.target_option_price:.2f}",
                "",
                "Review the position and choose Sold, Mute, or Okay.",
            ]
        )
    if alert_key == "stop_hit":
        return "\n".join(
            [
                header,
                "",
                "Stop level has been reached.",
                current,
                f"Stop: ${recommendation.stop_loss_option_price:.2f}",
                "",
                "Review the position and choose Sold, Mute, or Okay.",
            ]
        )
    if alert_key == "exit_by_date":
        return "\n".join(
            [
                header,
                "",
                f"Exit-by date is here: {recommendation.exit_by_date}",
                current,
                "",
                "Review the position and choose Sold or Still holding.",
            ]
        )
    return "\n".join(
        [
            header,
            "",
            f"Expiry is close: {recommendation.expiry}",
            current,
            "",
            "Review the position and choose Sold or Still holding.",
        ]
    )


def position_pnl(
    *,
    entry_price: Decimal,
    close_price: Decimal,
    quantity: int,
    position_side: str,
) -> Decimal:
    if position_side == "short":
        return (entry_price - close_price) * CONTRACT_MULTIPLIER * quantity
    return (close_price - entry_price) * CONTRACT_MULTIPLIER * quantity
