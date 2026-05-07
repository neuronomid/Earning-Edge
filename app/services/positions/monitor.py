from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

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
        async with self.sessionmaker() as session:
            repo = OpenPositionRepository(session)
            positions = await repo.list_active()
            for position in positions:
                recommendation = await session.get(Recommendation, position.recommendation_id)
                user = await session.get(User, position.user_id)
                if recommendation is None or user is None:
                    continue
                await self._poll_position(session, position, recommendation, user, today=today)
            await session.commit()

    async def _poll_position(
        self,
        session,
        position: OpenPosition,
        recommendation: Recommendation,
        user: User,
        *,
        today: date,
    ) -> None:
        if today > recommendation.expiry:
            position.status = "closed_expired"
            position.close_at = datetime.now(UTC)
            await session.flush()
            return

        quote = await self._fetch_quote(position, recommendation, user, today=today)
        if quote is None:
            return

        position.last_premium = quote.premium
        position.last_polled_at = datetime.now(UTC)
        position.last_data_source = quote.source

        alert_keys = _alerts_for_position(position, recommendation, quote.premium, today=today)
        for alert_key in alert_keys:
            await self._send_alert(position, recommendation, user, alert_key, quote.premium)
            position.alerts_sent = [*list(position.alerts_sent or []), alert_key]

        await session.flush()

    async def _fetch_quote(
        self,
        position: OpenPosition,
        recommendation: Recommendation,
        user: User,
        *,
        today: date,
    ) -> PremiumQuote | None:
        if (recommendation.expiry - today).days <= 1:
            quote = await self._fetch_alpaca(recommendation, user, today=today)
            if quote is not None:
                return quote

        quote = await self._fetch_yfinance(recommendation, today=today)
        if quote is None:
            return await self._fetch_alpaca(recommendation, user, today=today)

        if _should_confirm_with_realtime(position, recommendation, quote.premium):
            confirmed = await self._fetch_alpaca(recommendation, user, today=today)
            if confirmed is not None:
                return confirmed
        return quote

    async def _fetch_yfinance(
        self,
        recommendation: Recommendation,
        *,
        today: date,
    ) -> PremiumQuote | None:
        try:
            premium = await self.yfinance.fetch_premium(
                recommendation.ticker,
                strike=recommendation.strike,
                expiry=recommendation.expiry,
                option_type=recommendation.option_type,
                today=today,
            )
        except RuntimeError as exc:
            self.logger.warning(
                "position_yfinance_premium_failed",
                ticker=recommendation.ticker,
                error=str(exc),
            )
            return None
        return None if premium is None else PremiumQuote(premium=premium, source="yfinance")

    async def _fetch_alpaca(
        self,
        recommendation: Recommendation,
        user: User,
        *,
        today: date,
    ) -> PremiumQuote | None:
        api_key = decrypt_or_none(user.alpaca_api_key_encrypted)
        api_secret = decrypt_or_none(user.alpaca_api_secret_encrypted)
        if not api_key or not api_secret:
            return None
        try:
            premium = await self.alpaca.fetch_premium(
                recommendation.ticker,
                api_key=api_key,
                api_secret=api_secret,
                strike=recommendation.strike,
                expiry=recommendation.expiry,
                option_type=recommendation.option_type,
                today=today,
            )
        except (AlpacaAuthenticationError, AlpacaUnavailableError, RuntimeError) as exc:
            self.logger.warning(
                "position_alpaca_premium_failed",
                ticker=recommendation.ticker,
                error=str(exc),
            )
            return None
        return None if premium is None else PremiumQuote(premium=premium, source="alpaca")

    async def _send_alert(
        self,
        position: OpenPosition,
        recommendation: Recommendation,
        user: User,
        alert_key: str,
        current_premium: Decimal,
    ) -> None:
        await self.notifier.send_text(
            user.telegram_chat_id,
            _render_alert(recommendation, alert_key, current_premium),
            reply_markup=position_alert_keyboard(str(position.id)),
        )


async def poll_open_positions() -> None:
    await PositionMonitor().poll_open_positions()


def _alerts_for_position(
    position: OpenPosition,
    recommendation: Recommendation,
    current_premium: Decimal,
    *,
    today: date,
) -> list[str]:
    sent = set(position.alerts_sent or [])
    alerts: list[str] = []
    if (
        recommendation.target_option_price is not None
        and current_premium >= recommendation.target_option_price
        and "target_hit" not in sent
    ):
        alerts.append("target_hit")
    if (
        recommendation.stop_loss_option_price is not None
        and current_premium <= recommendation.stop_loss_option_price
        and "stop_hit" not in sent
    ):
        alerts.append("stop_hit")
    if (
        recommendation.exit_by_date is not None
        and today >= recommendation.exit_by_date
        and "exit_by_date" not in sent
    ):
        alerts.append("exit_by_date")
    if (recommendation.expiry - today).days <= 1 and "expiry_t_minus_1" not in sent:
        alerts.append("expiry_t_minus_1")
    return alerts


def _should_confirm_with_realtime(
    position: OpenPosition,
    recommendation: Recommendation,
    current_premium: Decimal,
) -> bool:
    return (
        _is_near_threshold(current_premium, recommendation.target_option_price, above=True)
        or _is_near_threshold(current_premium, recommendation.stop_loss_option_price, above=False)
        or _crossed_target(position.last_premium, current_premium, recommendation.target_option_price)
        or _crossed_stop(position.last_premium, current_premium, recommendation.stop_loss_option_price)
    )


def _is_near_threshold(
    current: Decimal,
    threshold: Decimal | None,
    *,
    above: bool,
) -> bool:
    if threshold is None or threshold <= 0:
        return False
    if above:
        return current >= threshold * (Decimal("1") - THRESHOLD_PROXIMITY)
    return current <= threshold * (Decimal("1") + THRESHOLD_PROXIMITY)


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
                "Review the position and choose Sold or Still holding.",
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
                "Review the position and choose Sold or Still holding.",
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
