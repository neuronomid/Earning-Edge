from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.models.open_position import OpenPosition
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.repositories.open_position_repo import OpenPositionRepository
from app.db.repositories.position_plan_override_repo import PositionPlanOverrideRepository
from app.db.session import get_sessionmaker
from app.pipeline.orchestrator import AiogramNotifier, TelegramNotifier
from app.services.market_hours import current_market_session, is_market_open
from app.services.options.alpaca_client import (
    AlpacaAuthenticationError,
    AlpacaOptionsClient,
    AlpacaUnavailableError,
    build_occ_symbol,
)
from app.services.options.yfinance_client import YFinanceOptionsClient
from app.services.positions.drift import evaluate_position_drift
from app.services.positions.plans import ActivePositionPlan, active_position_plan
from app.services.positions.snapshots import PositionSnapshotService
from app.services.positions.thesis_builder import PositionThesisBuilder
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
        market_open_checker: Callable[[], bool] | None = None,
        snapshot_service: PositionSnapshotService | None = None,
        settings: Settings | None = None,
        validation_enabled: bool | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.sessionmaker = sessionmaker or get_sessionmaker()
        self.yfinance = yfinance or YFinanceOptionsClient()
        self.alpaca = alpaca or AlpacaOptionsClient()
        self.notifier = notifier or AiogramNotifier()
        self.today_factory = today_factory or date.today
        self.logger = logger or get_logger(__name__)
        self.market_open_checker = market_open_checker or is_market_open
        self.snapshot_service = snapshot_service or PositionSnapshotService()
        self.validation_enabled = (
            self.settings.position_validation_monitor_enabled and self.settings.app_env != "test"
            if validation_enabled is None
            else validation_enabled
        )

    async def poll_open_positions(self) -> None:
        if not self.market_open_checker():
            self.logger.info("position_monitor_market_closed")
            return

        today = self.today_factory()
        now = datetime.now(UTC)
        async with self.sessionmaker() as session:
            repo = OpenPositionRepository(session)
            positions = await repo.list_active()

            # Group positions by ticker for batch Alpaca calls
            by_ticker: dict[str, list[tuple[OpenPosition, Recommendation, User]]] = defaultdict(
                list
            )
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
        session: Any,
        ticker: str,
        group: list[tuple[OpenPosition, Recommendation, User]],
        *,
        today: date,
        now: datetime,
    ) -> None:
        if not group:
            return

        # Close expired positions first so they don't depend on a live quote being
        # available (yfinance/alpaca may return nothing for an expired symbol).
        live_group: list[tuple[OpenPosition, Recommendation, User]] = []
        for position, recommendation, user in group:
            if today > recommendation.expiry:
                await self._close_expired_position(session, position, recommendation, user)
            else:
                live_group.append((position, recommendation, user))

        if not live_group:
            return

        overrides = await PositionPlanOverrideRepository(session).latest_for_positions(
            tuple(position.id for position, _, _ in live_group)
        )
        user = live_group[0][2]
        quote_map = await self._fetch_quotes_for_group(ticker, live_group, user, today=today)

        for position, recommendation, _ in live_group:
            occ_symbol = build_occ_symbol(
                recommendation.ticker,
                expiry=recommendation.expiry,
                option_type=recommendation.option_type,
                strike=recommendation.strike,
            )
            quote = quote_map.get(occ_symbol)
            if quote is None:
                continue

            plan = active_position_plan(recommendation, overrides.get(position.id))
            await self._poll_position(
                session,
                position,
                recommendation,
                user,
                quote,
                plan,
                today=today,
                now=now,
            )

    async def _close_expired_position(
        self,
        session: Any,
        position: OpenPosition,
        recommendation: Recommendation,
        user: User,
    ) -> None:
        position.status = "closed_expired"
        position.close_at = datetime.now(UTC)
        from app.services.positions.account import apply_pnl_to_account

        apply_pnl_to_account(user, position, recommendation)
        await session.flush()

    async def _fetch_quotes_for_group(
        self,
        ticker: str,
        group: list[tuple[OpenPosition, Recommendation, User]],
        user: User,
        *,
        today: date,
    ) -> dict[str, PremiumQuote]:
        """Fetch quotes for each position in the group. Returns OCC symbol -> quote."""
        api_key = decrypt_or_none(user.alpaca_api_key_encrypted)
        api_secret = decrypt_or_none(user.alpaca_api_secret_encrypted)
        if api_key and api_secret:
            alpaca_result = await self._fetch_alpaca_group(
                ticker, group, api_key, api_secret, today=today
            )
            if alpaca_result:
                return alpaca_result

        return await self._fetch_yfinance_group(ticker, group, today=today)

    async def _fetch_alpaca_group(
        self,
        ticker: str,
        group: list[tuple[OpenPosition, Recommendation, User]],
        api_key: str,
        api_secret: str,
        *,
        today: date,
    ) -> dict[str, PremiumQuote]:
        """Fetch Alpaca quotes for the positions in the group."""
        symbols = [
            build_occ_symbol(
                rec.ticker,
                expiry=rec.expiry,
                option_type=rec.option_type,
                strike=rec.strike,
            )
            for _, rec, _ in group
        ]
        max_expiry = max(rec.expiry for _, rec, _ in group)
        days_to_expiry = max((max_expiry - today).days, 1)
        try:
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
            if premium is not None and contract.symbol is not None:
                result[contract.symbol] = PremiumQuote(premium=premium, source="alpaca")
        return result

    async def _fetch_yfinance_group(
        self,
        ticker: str,
        group: list[tuple[OpenPosition, Recommendation, User]],
        *,
        today: date,
    ) -> dict[str, PremiumQuote]:
        """Fetch yfinance quotes per position. yfinance has no batch chain API."""
        result: dict[str, PremiumQuote] = {}
        for _, rec, _ in group:
            occ_symbol = build_occ_symbol(
                rec.ticker,
                expiry=rec.expiry,
                option_type=rec.option_type,
                strike=rec.strike,
            )
            try:
                premium = await self.yfinance.fetch_premium(
                    ticker,
                    strike=rec.strike,
                    expiry=rec.expiry,
                    option_type=rec.option_type,
                    today=today,
                )
            except RuntimeError as exc:
                self.logger.warning(
                    "position_yfinance_group_failed",
                    ticker=ticker,
                    error=str(exc),
                )
                continue
            if premium is not None:
                result[occ_symbol] = PremiumQuote(premium=premium, source="yfinance")
        return result

    async def _poll_position(
        self,
        session: Any,
        position: OpenPosition,
        recommendation: Recommendation,
        user: User,
        quote: PremiumQuote,
        plan: ActivePositionPlan,
        *,
        today: date,
        now: datetime,
    ) -> None:
        alert_keys = _alerts_for_position(
            position,
            recommendation,
            quote.premium,
            plan=plan,
            today=today,
            now=now,
        )
        position.last_premium = quote.premium
        position.last_polled_at = datetime.now(UTC)
        position.last_data_source = quote.source
        for alert_key in alert_keys:
            await self._send_alert(
                position,
                recommendation,
                user,
                alert_key,
                quote.premium,
                plan,
            )
            # Increment alert counts for TP/SL (not for date-based alerts)
            if alert_key == "target_hit":
                position.target_alert_count += 1
            elif alert_key == "stop_hit":
                position.stop_alert_count += 1
            else:
                # Date-based alerts use alerts_sent for deduplication
                position.alerts_sent = [*list(position.alerts_sent or []), alert_key]

        await session.flush()
        await self._maybe_evaluate_validation_drift(
            session,
            position,
            recommendation,
            user,
            plan,
            now=now,
        )

    async def _maybe_evaluate_validation_drift(
        self,
        session: Any,
        position: OpenPosition,
        recommendation: Recommendation,
        user: User,
        plan: ActivePositionPlan,
        *,
        now: datetime,
    ) -> None:
        if not self.validation_enabled:
            return
        market_session = current_market_session(now)
        if market_session is None:
            return
        try:
            thesis = await PositionThesisBuilder(session).ensure_thesis_for_position(
                position=position,
                recommendation=recommendation,
                user=user,
                entry_snapshot=None,
                backfilled=True,
            )
            current = await self.snapshot_service.fetch_current(
                user=user,
                recommendation=recommendation,
                today=market_session.session_date,
            )
            drift = evaluate_position_drift(
                thesis=thesis,
                current=current,
                session=market_session,
                new_headlines=(),
                plan=plan,
            )
        except Exception as exc:
            self.logger.warning(
                "position_drift_evaluation_failed",
                position_id=str(position.id),
                ticker=recommendation.ticker,
                error=str(exc),
            )
            return

        trigger_codes = drift.auto_trigger_codes
        if not trigger_codes:
            return
        if self.settings.position_validation_shadow_mode:
            self.logger.info(
                "position_drift_shadow",
                position_id=str(position.id),
                ticker=recommendation.ticker,
                fired_codes=list(trigger_codes),
                snapshot=drift.snapshot,
            )
            return

        from app.services.positions.revalidation_service import RevalidationService

        result = await RevalidationService(
            sessionmaker=self.sessionmaker,
            snapshot_service=self.snapshot_service,
            notifier=self.notifier,
            settings=self.settings,
        ).validate_position_auto(
            position_id=position.id,
            trigger_codes=trigger_codes,
            drift_snapshot=drift.snapshot,
        )
        self.logger.info(
            "position_validation_auto_result",
            position_id=str(position.id),
            ticker=recommendation.ticker,
            status=result.status,
        )

    async def _send_alert(
        self,
        position: OpenPosition,
        recommendation: Recommendation,
        user: User,
        alert_key: str,
        current_premium: Decimal,
        plan: ActivePositionPlan,
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
            _render_alert(recommendation, alert_key, current_premium, plan=plan),
            reply_markup=keyboard,
        )


async def poll_open_positions() -> None:
    await PositionMonitor().poll_open_positions()


def _alerts_for_position(
    position: OpenPosition,
    recommendation: Recommendation,
    current_premium: Decimal,
    *,
    plan: ActivePositionPlan | None = None,
    today: date,
    now: datetime,
) -> list[str]:
    alerts: list[str] = []
    plan = plan or active_position_plan(recommendation)

    # Target price alert
    if not position.target_dismissed:
        # Check if mute period has expired
        if position.target_muted_until is None or now >= position.target_muted_until:
            target = plan.target_option_price
            if target is not None and target > 0:
                if position.target_alert_count == 0 and _target_reached(
                    recommendation,
                    current_premium,
                    target,
                ):
                    alerts.append("target_hit")
                elif position.target_alert_count > 0 and _crossed_target(
                    recommendation,
                    position.last_premium,
                    current_premium,
                    target,
                ):
                    alerts.append("target_hit")

    # Stop loss alert
    if not position.stop_dismissed:
        # Check if mute period has expired
        if position.stop_muted_until is None or now >= position.stop_muted_until:
            stop = plan.stop_loss_option_price
            if stop is not None and stop > 0:
                if position.stop_alert_count == 0 and _stop_reached(
                    recommendation,
                    current_premium,
                    stop,
                ):
                    alerts.append("stop_hit")
                elif position.stop_alert_count > 0 and _crossed_stop(
                    recommendation,
                    position.last_premium,
                    current_premium,
                    stop,
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


def _target_reached(
    recommendation: Recommendation,
    current: Decimal,
    threshold: Decimal,
) -> bool:
    if recommendation.position_side == "short":
        return current <= threshold
    return current >= threshold


def _stop_reached(
    recommendation: Recommendation,
    current: Decimal,
    threshold: Decimal,
) -> bool:
    if recommendation.position_side == "short":
        return current >= threshold
    return current <= threshold


def _crossed_target(
    recommendation: Recommendation,
    previous: Decimal | None,
    current: Decimal,
    threshold: Decimal | None,
) -> bool:
    if previous is None or threshold is None:
        return False
    if recommendation.position_side == "short":
        return previous > threshold >= current
    return previous < threshold <= current


def _crossed_stop(
    recommendation: Recommendation,
    previous: Decimal | None,
    current: Decimal,
    threshold: Decimal | None,
) -> bool:
    if previous is None or threshold is None:
        return False
    if recommendation.position_side == "short":
        return previous < threshold <= current
    return previous > threshold >= current


def _premium_from_contract(contract: Any) -> Decimal | None:
    """Extract the best available premium from a contract."""
    premium = contract.mid or contract.last_trade_price or contract.ask or contract.bid
    return premium if isinstance(premium, Decimal) else None


def _render_alert(
    recommendation: Recommendation,
    alert_key: str,
    current_premium: Decimal,
    *,
    plan: ActivePositionPlan | None = None,
) -> str:
    plan = plan or active_position_plan(recommendation)
    header = f"<b>{recommendation.ticker} position alert</b>"
    current = f"Current option premium: ${current_premium:.2f}"
    if alert_key == "target_hit":
        target_label = (
            "Target buyback level has been reached."
            if recommendation.position_side == "short"
            else "Target price has been reached."
        )
        return "\n".join(
            [
                header,
                "",
                target_label,
                current,
                f"Target: ${plan.target_option_price:.2f}",
                "",
                "Review the position and choose Sold, Mute, or Okay.",
            ]
        )
    if alert_key == "stop_hit":
        stop_lines = [
            header,
            "",
            "Stop level has been reached.",
            current,
            f"Stop: ${plan.stop_loss_option_price:.2f}",
        ]
        if plan.underlying_stop_price is not None:
            stop_lines.append(f"Underlying stop alert: ${plan.underlying_stop_price:.2f}")
        stop_lines.extend(
            [
                "",
                "Review the position and choose Sold, Mute, or Okay.",
            ]
        )
        return "\n".join(stop_lines)
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
