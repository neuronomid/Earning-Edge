from __future__ import annotations

# FastAPI's dependency/query marker style intentionally uses calls in defaults.
# ruff: noqa: B008
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.feedback_event import FeedbackEvent
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.feedback_repo import FeedbackEventRepository
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.db.repositories.run_repo import WorkflowRunRepository
from app.db.session import get_session
from app.services.alternative_recommendation_service import AlternativeRecommendationService
from app.services.api_key_validators import (
    AlpacaValidator,
    AlphaVantageValidator,
    OpenRouterValidator,
)
from app.services.market_data.alpaca_stock_client import AlpacaStockClient
from app.services.options.alpaca_client import AlpacaOptionsClient
from app.services.options.yfinance_client import YFinanceOptionsClient
from app.services.user_service import (
    TIMEZONE_DISPLAY,
    RiskProfile,
    StrategyPermission,
    TimezoneLabel,
    UserService,
    decrypt_or_none,
)
from app.telegram.handlers.recommendation import _render_note, _render_risk, _render_why
from app.telegram.templates.main_recommendation import render_main_recommendation

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
log = get_logger("dashboard_api")


class OpenRouterKeyPayload(BaseModel):
    api_key: str = Field(alias="apiKey", min_length=1)


class AlpacaCredentialsPayload(BaseModel):
    api_key: str = Field(alias="apiKey", min_length=1)
    api_secret: str = Field(alias="apiSecret", min_length=1)


class AlphaVantageKeyPayload(BaseModel):
    api_key: str = Field(alias="apiKey", min_length=1)


class DashboardAuthPayload(BaseModel):
    username: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=4, max_length=128)


class DashboardSettingsPayload(BaseModel):
    account_size: Decimal | None = Field(default=None, alias="accountSize", gt=0)
    risk_profile: RiskProfile | None = Field(default=None, alias="riskProfile")
    timezone_label: TimezoneLabel | None = Field(default=None, alias="timezoneLabel")
    broker: str | None = Field(default=None, min_length=1, max_length=64)
    strategy_permission: StrategyPermission | None = Field(
        default=None,
        alias="strategyPermission",
    )
    max_contracts: int | None = Field(default=None, alias="maxContracts", ge=1, le=100)


@router.post("/auth/register")
async def register_dashboard_user(
    payload: DashboardAuthPayload,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        user = await UserService(session).create_dashboard_user(
            payload.username,
            payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await session.commit()
    return {"status": "ok", "message": "Account created.", "user": _serialize_user(user)}


@router.post("/auth/login")
async def login_dashboard_user(
    payload: DashboardAuthPayload,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await UserService(session).authenticate_dashboard_user(
        payload.username,
        payload.password,
    )
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return {"status": "ok", "message": "Signed in.", "user": _serialize_user(user)}


@router.patch("/settings")
async def update_dashboard_settings(
    payload: DashboardSettingsPayload,
    chat_id: str | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await _resolve_user(session, chat_id=chat_id, user_id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No dashboard user was found.")

    service = UserService(session)
    if payload.account_size is not None:
        await service.update_account_size(user, payload.account_size)
    if payload.risk_profile is not None:
        await service.update_risk_profile(user, payload.risk_profile)
    if payload.timezone_label is not None:
        await service.update_timezone(user, payload.timezone_label)
    if payload.broker is not None:
        broker = payload.broker.strip()
        if not broker:
            raise HTTPException(status_code=400, detail="Broker cannot be empty.")
        await service.update_broker(user, broker)
    if payload.strategy_permission is not None:
        await service.update_strategy_permission(user, payload.strategy_permission)
    if payload.max_contracts is not None:
        await service.update_max_contracts(user, payload.max_contracts)

    await session.commit()
    return {"status": "ok", "message": "Settings saved.", "user": _serialize_user(user)}


@router.post("/run-scan")
async def run_scan(
    chat_id: str | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await _resolve_user(session, chat_id=chat_id, user_id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded dashboard user was found.")

    missing = _preflight_missing(user)
    if missing:
        missing_labels = {
            "openrouter": "OpenRouter key (required for LLM analysis)",
            "alpaca": "Alpaca key + secret (required for live option chain data)",
        }
        detail = (
            "Scan cannot run — missing: "
            + "; ".join(missing_labels[k] for k in missing if k in missing_labels)
            + ". Add them in the API Keys section."
        )
        return {
            "outcome": "missing_config",
            "run_id": None,
            "error_message": detail,
            "missing": missing,
        }

    from app.scheduler.jobs import get_workflow_runner

    result = await get_workflow_runner().run_workflow(user.id, trigger_type="manual")
    return {
        "outcome": result.outcome,
        "run_id": str(result.run_id) if result.run_id else None,
        "error_message": result.error_message,
        "missing": [],
    }


def _preflight_missing(user: User) -> list[str]:
    missing: list[str] = []
    openrouter_key = decrypt_or_none(user.openrouter_api_key_encrypted)
    if not openrouter_key or not openrouter_key.strip():
        missing.append("openrouter")
    alpaca_key = decrypt_or_none(user.alpaca_api_key_encrypted)
    alpaca_secret = decrypt_or_none(user.alpaca_api_secret_encrypted)
    if not alpaca_key or not alpaca_secret:
        missing.append("alpaca")
    return missing


class OptionPriceRequest(BaseModel):
    ticker: str
    strike: float
    expiry: str
    option_type: str  # call or put
    position_side: str = "long"  # long or short


def _serialize_option_price_contract(
    *,
    source: str,
    ticker: str,
    strike: Decimal,
    expiry: date,
    option_type: str,
    contract: Any,
    include_delta: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": source,
        "ticker": ticker,
        "strike": float(strike),
        "expiry": expiry.isoformat(),
        "option_type": option_type,
        "bid": _decimal_to_float(contract.bid),
        "ask": _decimal_to_float(contract.ask),
        "mid": _decimal_to_float(contract.mid),
        "last_trade_price": _decimal_to_float(contract.last_trade_price),
        "volume": contract.volume,
        "open_interest": contract.open_interest,
        "implied_volatility": _decimal_to_float(contract.implied_volatility),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if include_delta:
        payload["delta"] = _decimal_to_float(contract.delta)
    return payload


@router.post("/option-price")
async def get_option_price(
    payload: OptionPriceRequest,
    chat_id: str | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Fetch live option price from Alpaca (preferred) or Yahoo Finance fallback."""
    user = await _resolve_user(session, chat_id=chat_id, user_id=user_id)
    alpaca_key = decrypt_or_none(user.alpaca_api_key_encrypted) if user else None
    alpaca_secret = decrypt_or_none(user.alpaca_api_secret_encrypted) if user else None

    ticker = payload.ticker.upper()
    strike = Decimal(str(payload.strike))
    expiry = date.fromisoformat(payload.expiry)
    option_type = payload.option_type.lower()

    # Try Alpaca first
    if alpaca_key and alpaca_secret:
        try:
            client = AlpacaOptionsClient()
            contracts = await client.fetch_chain(
                ticker,
                api_key=alpaca_key,
                api_secret=alpaca_secret,
                expiry_window_days=30,
                today=date.today(),
            )
            for contract in contracts:
                if (
                    contract.option_type == option_type
                    and contract.strike == strike
                    and contract.expiry == expiry
                ):
                    return _serialize_option_price_contract(
                        source="alpaca",
                        ticker=ticker,
                        strike=strike,
                        expiry=expiry,
                        option_type=option_type,
                        contract=contract,
                        include_delta=True,
                    )
        except Exception as exc:
            log.warning(
                "dashboard_option_price_alpaca_fallback",
                ticker=ticker,
                error=str(exc),
            )

    # Fallback to Yahoo Finance
    try:
        client = YFinanceOptionsClient()
        contracts = await client.fetch_chain(
            ticker,
            expiry_window_days=30,
            today=date.today(),
        )
        for contract in contracts:
            if (
                contract.option_type == option_type
                and contract.strike == strike
                and contract.expiry == expiry
            ):
                return _serialize_option_price_contract(
                    source="yfinance",
                    ticker=ticker,
                    strike=strike,
                    expiry=expiry,
                    option_type=option_type,
                    contract=contract,
                )
    except Exception as exc:
        log.warning(
            "dashboard_option_price_yfinance_failed",
            ticker=ticker,
            error=str(exc),
        )

    raise HTTPException(
        status_code=404,
        detail=f"Could not find live price for {ticker} {option_type} {strike} {expiry}.",
    )


@router.get("/stock-price")
async def get_stock_price(
    ticker: str = Query(min_length=1, max_length=10),
    chat_id: str | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    feed: str = Query(default="iex", min_length=2, max_length=32),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Fetch current stock price using Alpaca IEX when available, else yfinance."""
    ticker_upper = ticker.upper()
    fallback_reason: str | None = None
    user = await _resolve_user(session, chat_id=chat_id, user_id=user_id)
    alpaca_key = decrypt_or_none(user.alpaca_api_key_encrypted) if user else None
    alpaca_secret = decrypt_or_none(user.alpaca_api_secret_encrypted) if user else None

    if alpaca_key and alpaca_secret:
        try:
            quote = await AlpacaStockClient(feed=feed).fetch_quote(
                ticker_upper,
                api_key=alpaca_key,
                api_secret=alpaca_secret,
                feed=feed,
            )
            previous_close = await _yfinance_previous_close(ticker_upper)
            change = float(quote.price - previous_close) if previous_close is not None else None
            change_percent = (
                float((quote.price - previous_close) / previous_close * Decimal("100"))
                if previous_close is not None and previous_close != 0
                else None
            )
            data_mode = "DELAYED" if quote.feed == "delayed_sip" else "REAL_TIME"
            return {
                "ticker": quote.symbol,
                "price": float(quote.price),
                "bid": float(quote.bid) if quote.bid is not None else None,
                "ask": float(quote.ask) if quote.ask is not None else None,
                "previousClose": float(previous_close) if previous_close is not None else None,
                "change": change,
                "changePercent": change_percent,
                "timestamp": quote.timestamp or datetime.now(UTC).isoformat(),
                "source": f"alpaca_{quote.feed}",
                "dataMode": data_mode,
            }
        except Exception as exc:
            fallback_reason = str(exc)

    try:
        price, prev_close = await _yfinance_price(ticker_upper)

        if price is None:
            raise HTTPException(status_code=404, detail=f"Price not found for {ticker_upper}")

        change = price - prev_close if prev_close is not None else None
        change_percent = (change / prev_close * 100) if prev_close and prev_close != 0 else None

        return {
            "ticker": ticker_upper,
            "price": price,
            "previousClose": prev_close,
            "change": change,
            "changePercent": change_percent,
            "timestamp": datetime.now(UTC).isoformat(),
            "source": "yfinance",
            "dataMode": "DELAYED",
            "fallbackReason": fallback_reason,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Stock price fetch failed: {exc!s}") from exc


@router.post("/api-keys/openrouter")
async def update_openrouter_key(
    payload: OpenRouterKeyPayload,
    chat_id: str | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    user = await _resolve_user(session, chat_id=chat_id, user_id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded dashboard user was found.")

    result = await OpenRouterValidator().validate(payload.api_key)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.detail)

    await UserService(session).replace_openrouter_key(user, payload.api_key)
    await session.commit()
    return {"status": "ok", "message": "OpenRouter key updated and validated."}


@router.delete("/api-keys/openrouter")
async def remove_openrouter_key(
    chat_id: str | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    user = await _resolve_user(session, chat_id=chat_id, user_id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded dashboard user was found.")

    await UserService(session).replace_openrouter_key(user, None)
    await session.commit()
    return {"status": "ok", "message": "OpenRouter key removed."}


@router.post("/api-keys/alpaca")
async def update_alpaca_credentials(
    payload: AlpacaCredentialsPayload,
    chat_id: str | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    user = await _resolve_user(session, chat_id=chat_id, user_id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded dashboard user was found.")

    result = await AlpacaValidator().validate(payload.api_key, payload.api_secret)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.detail)

    await UserService(session).replace_alpaca_creds(user, payload.api_key, payload.api_secret)
    await session.commit()
    return {"status": "ok", "message": "Alpaca credentials updated and validated."}


@router.delete("/api-keys/alpaca")
async def remove_alpaca_credentials(
    chat_id: str | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    user = await _resolve_user(session, chat_id=chat_id, user_id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded dashboard user was found.")

    await UserService(session).replace_alpaca_creds(user, None, None)
    await session.commit()
    return {"status": "ok", "message": "Alpaca credentials removed."}


@router.post("/api-keys/alpha-vantage")
async def update_alpha_vantage_key(
    payload: AlphaVantageKeyPayload,
    chat_id: str | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    user = await _resolve_user(session, chat_id=chat_id, user_id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded dashboard user was found.")

    result = await AlphaVantageValidator().validate(payload.api_key)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.detail)

    await UserService(session).replace_alpha_vantage_key(user, payload.api_key)
    await session.commit()
    return {"status": "ok", "message": "Alpha Vantage key updated."}


@router.delete("/api-keys/alpha-vantage")
async def remove_alpha_vantage_key(
    chat_id: str | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    user = await _resolve_user(session, chat_id=chat_id, user_id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No onboarded dashboard user was found.")

    await UserService(session).replace_alpha_vantage_key(user, None)
    await session.commit()
    return {"status": "ok", "message": "Alpha Vantage key removed."}


@dataclass(slots=True)
class DashboardContext:
    user: User
    latest_run: WorkflowRun | None
    recommendations: list[Recommendation]
    recent_runs: list[WorkflowRun]
    schedules: list[Any]
    feedback_by_recommendation: dict[str, str]


@router.get("/snapshot")
async def dashboard_snapshot(
    chat_id: str | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    context = await _build_dashboard_context(session, chat_id=chat_id, user_id=user_id)
    if context is None:
        raise HTTPException(status_code=404, detail="No onboarded dashboard user was found.")

    latest_run = context.latest_run
    candidate_cards = _candidate_cards_by_ticker(latest_run)
    recommendation_rank = _recommendation_rank_map(latest_run)

    recommendations = sorted(
        context.recommendations,
        key=lambda item: recommendation_rank.get(item.ticker, 999),
    )

    return {
        "mode": "live",
        "user": _serialize_user(context.user),
        "snapshotDate": _dt(
            latest_run.finished_at if latest_run and latest_run.finished_at else None
        ),
        "warningText": _run_warning_text(latest_run),
        "selectedRecommendationId": None if not recommendations else str(recommendations[0].id),
        "recommendations": [
            _serialize_recommendation(
                item,
                rank=recommendation_rank.get(item.ticker, index),
                warning_text=_run_warning_text(latest_run) if index == 1 else None,
                feedback_action=context.feedback_by_recommendation.get(str(item.id)),
                candidate_card=candidate_cards.get(item.ticker, {}),
                option_contract=_find_option_contract(
                    latest_run,
                    ticker=item.ticker,
                    option_type=item.option_type,
                    position_side=item.position_side,
                    strike=item.strike,
                    expiry=item.expiry,
                ),
                latest_run=latest_run,
            )
            for index, item in enumerate(recommendations, start=1)
        ],
        "candidateUniverse": _serialize_candidate_universe(latest_run),
        "recentRuns": [_serialize_run(item) for item in context.recent_runs],
        "schedules": [_serialize_schedule(item) for item in context.schedules],
        "system": _serialize_system(context.user),
        "telegramMessageText": None if latest_run is None else latest_run.telegram_message_text,
        "pipelineSteps": _serialize_pipeline_steps(latest_run),
    }


@router.get("/recommendations/{recommendation_id}/why")
async def recommendation_why(
    recommendation_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    recommendation = await _require_recommendation(session, recommendation_id)
    return {
        "title": f"Why {recommendation.ticker}",
        "html": _render_why(recommendation),
    }


@router.get("/recommendations/{recommendation_id}/risk")
async def recommendation_risk(
    recommendation_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    recommendation = await _require_recommendation(session, recommendation_id)
    return {
        "title": f"Risk / Sizing for {recommendation.ticker}",
        "html": _render_risk(recommendation),
    }


@router.get("/recommendations/{recommendation_id}/save-note")
async def recommendation_note(
    recommendation_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    recommendation = await _require_recommendation(session, recommendation_id)
    return {
        "title": f"Saved note for {recommendation.ticker}",
        "html": _render_note(recommendation),
    }


@router.post("/recommendations/{recommendation_id}/feedback")
async def recommendation_feedback(
    recommendation_id: UUID,
    payload: dict[str, str],
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    recommendation = await _require_recommendation(session, recommendation_id)
    action = payload.get("action")
    if action not in {"bought", "skipped"}:
        raise HTTPException(status_code=400, detail="Feedback action must be bought or skipped.")

    await FeedbackEventRepository(session).add(
        FeedbackEvent(
            recommendation_id=recommendation.id,
            user_id=recommendation.user_id,
            user_action=action,
        )
    )
    await session.commit()
    return {"status": "ok", "message": "Feedback saved."}


@router.post("/recommendations/{recommendation_id}/alternatives")
async def recommendation_alternative(
    recommendation_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    recommendation = await _require_recommendation(session, recommendation_id)
    user = await session.get(User, recommendation.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="The recommendation user was not found.")

    result = await AlternativeRecommendationService(session).build_next(
        user=user,
        current_recommendation=recommendation,
    )

    if result.recommendation is None:
        await session.commit()
        return {
            "status": "empty",
            "message": result.message
            or "No additional qualified alternatives are available for this run.",
        }

    run = await session.get(WorkflowRun, result.recommendation.run_id)
    option_contract = _find_option_contract(
        run,
        ticker=result.recommendation.ticker,
        option_type=result.recommendation.option_type,
        position_side=result.recommendation.position_side,
        strike=result.recommendation.strike,
        expiry=result.recommendation.expiry,
    )
    candidate_card = _candidate_cards_by_ticker(run).get(result.recommendation.ticker, {})
    warning_text = _run_warning_text(run)

    await session.commit()
    return {
        "status": "ok",
        "message": render_main_recommendation(
            _renderable_recommendation(result.recommendation, candidate_card),
            rank_position=result.rank_position or 2,
            warning_text=warning_text,
            watchlist_only=result.watchlist_only,
        ),
        "recommendation": _serialize_recommendation(
            result.recommendation,
            rank=result.rank_position or 2,
            warning_text=warning_text,
            feedback_action=None,
            candidate_card=candidate_card,
            option_contract=option_contract,
            latest_run=run,
        ),
    }


async def _build_dashboard_context(
    session: AsyncSession,
    *,
    chat_id: str | None,
    user_id: UUID | None,
) -> DashboardContext | None:
    user = await _resolve_user(session, chat_id=chat_id, user_id=user_id)
    if user is None:
        return None

    run_repo = WorkflowRunRepository(session)
    user_service = UserService(session)

    recent_runs = await run_repo.list_recent_for_user(user.id, limit=6)
    latest_run = recent_runs[0] if recent_runs else None
    recommendation_repo = RecommendationRepository(session)
    recommendations = (
        [] if latest_run is None else await recommendation_repo.list_for_run(latest_run.id)
    )
    schedules = await user_service.list_crons_for_user(user)
    feedback_by_recommendation = await _feedback_map(session, recommendations)

    return DashboardContext(
        user=user,
        latest_run=latest_run,
        recommendations=recommendations,
        recent_runs=recent_runs,
        schedules=schedules,
        feedback_by_recommendation=feedback_by_recommendation,
    )


async def _resolve_user(
    session: AsyncSession,
    *,
    chat_id: str | None,
    user_id: UUID | None,
) -> User | None:
    if user_id:
        user = await session.get(User, user_id)
        return user if user and user.is_active else None

    if chat_id:
        return await UserService(session).get_by_chat_id(chat_id)

    result = await session.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.updated_at.desc())
    )
    return result.scalars().first()


async def _feedback_map(
    session: AsyncSession,
    recommendations: list[Recommendation],
) -> dict[str, str]:
    repo = FeedbackEventRepository(session)
    feedback: dict[str, str] = {}
    for recommendation in recommendations:
        rows = await repo.list_for_recommendation(recommendation.id)
        if not rows:
            continue
        latest = max(rows, key=lambda item: item.created_at)
        feedback[str(recommendation.id)] = latest.user_action
    return feedback


async def _require_recommendation(
    session: AsyncSession,
    recommendation_id: UUID,
) -> Recommendation:
    recommendation = await RecommendationRepository(session).get(recommendation_id)
    if recommendation is None:
        raise HTTPException(status_code=404, detail="That recommendation is unavailable.")
    return recommendation


def _serialize_user(user: User) -> dict[str, Any]:
    chat_tail = (
        user.telegram_chat_id[-4:] if len(user.telegram_chat_id) >= 4 else user.telegram_chat_id
    )
    name = user.dashboard_username or f"Trader {chat_tail}"
    return {
        "id": str(user.id),
        "username": user.dashboard_username,
        "name": name,
        "broker": user.broker,
        "timezone": TIMEZONE_DISPLAY.get(user.timezone_label, user.timezone_label),
        "timezoneLabel": user.timezone_label,
        "accountSize": float(user.account_size),
        "riskProfile": user.risk_profile,
        "strategyPermission": user.strategy_permission,
        "maxContracts": user.max_contracts,
    }


def _serialize_system(user: User) -> dict[str, str | None]:
    openrouter_key = decrypt_or_none(user.openrouter_api_key_encrypted)
    alpaca_key = decrypt_or_none(user.alpaca_api_key_encrypted)
    alpaca_secret = decrypt_or_none(user.alpaca_api_secret_encrypted)
    av_key = decrypt_or_none(user.alpha_vantage_api_key_encrypted)
    has_openrouter = bool(openrouter_key)
    has_alpaca = bool(alpaca_key and alpaca_secret)
    return {
        "openRouterStatus": "Configured" if has_openrouter else "Missing",
        "openRouterKeyDisplay": _masked_secret(openrouter_key),
        "alpacaStatus": "Connected" if has_alpaca else "Not connected",
        "alpacaKeyDisplay": _masked_secret(alpaca_key),
        "alpacaSecretDisplay": _masked_secret(alpaca_secret),
        "alphaVantageStatus": "Connected" if av_key else "Not connected",
        "alphaVantageKeyDisplay": _masked_secret(av_key),
        "heavyModel": "anthropic/claude-opus-4.7",
        "lightModel": "google/gemini-3.1-flash-lite-preview",
    }


def _masked_secret(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    suffix = cleaned[-4:] if len(cleaned) > 4 else cleaned
    if cleaned.startswith("sk-"):
        prefix = cleaned[:8]
    elif len(cleaned) > 8:
        prefix = cleaned[:4]
    else:
        prefix = ""
    return f"{prefix}...{suffix}"


def _serialize_recommendation(
    recommendation: Recommendation,
    *,
    rank: int,
    warning_text: str | None,
    feedback_action: str | None,
    candidate_card: dict[str, Any],
    option_contract: dict[str, Any] | None,
    latest_run: WorkflowRun | None,
) -> dict[str, Any]:
    current_price = _floatish(candidate_card.get("current_price")) or 0.0
    suggested_entry = _decimal_to_float(recommendation.suggested_entry) or 0.0
    mark_premium = (
        _floatish(None if option_contract is None else option_contract.get("mid"))
        or suggested_entry
    )
    breakeven = _floatish(
        None if option_contract is None else option_contract.get("breakeven")
    ) or (
        recommendation.strike + Decimal(str(suggested_entry))
        if recommendation.option_type == "call"
        else recommendation.strike - Decimal(str(suggested_entry))
    )
    earnings_date = (
        candidate_card.get("earnings_date")
        or _selected_earnings_date(latest_run, recommendation.ticker)
        or recommendation.expiry.isoformat()
    )
    implied_volatility = _floatish(
        None if option_contract is None else option_contract.get("implied_volatility")
    )
    if implied_volatility is not None and implied_volatility <= 1.5:
        implied_volatility *= 100

    return {
        "id": str(recommendation.id),
        "rank": rank,
        "setupLabel": _setup_label(rank),
        "status": "watchlist" if recommendation.suggested_quantity == 0 else "recommend",
        "ticker": recommendation.ticker,
        "companyName": recommendation.company_name,
        "strategySource": candidate_card.get("strategy_source") or recommendation.strategy,
        "strategyLabel": recommendation.strategy.replace("_", " ").title(),
        "direction": "Bullish" if recommendation.option_type == "call" else "Bearish",
        "optionType": recommendation.option_type.capitalize(),
        "positionSide": recommendation.position_side.capitalize(),
        "strike": _decimal_to_float(recommendation.strike) or 0.0,
        "expiry": recommendation.expiry.isoformat(),
        "earningsDate": earnings_date,
        "earningsTiming": _selected_earnings_timing(latest_run, recommendation.ticker),
        "currentPrice": current_price,
        "contractId": _contract_id(recommendation, option_contract),
        "contractSymbol": None if option_contract is None else option_contract.get("symbol"),
        "bidPrice": _floatish(None if option_contract is None else option_contract.get("bid")),
        "askPrice": _floatish(None if option_contract is None else option_contract.get("ask")),
        "midPrice": mark_premium,
        "lastPrice": _floatish(
            None if option_contract is None else option_contract.get("last_trade_price")
        ),
        "contractSource": str(
            (None if option_contract is None else option_contract.get("source")) or "stored_run"
        ),
        "suggestedEntry": suggested_entry,
        "markPremium": mark_premium,
        "suggestedQuantity": recommendation.suggested_quantity,
        "estimatedMaxLoss": recommendation.estimated_max_loss,
        "accountRiskPercent": _decimal_to_float(recommendation.account_risk_percent) or 0.0,
        "confidenceScore": recommendation.confidence_score,
        "riskLevel": recommendation.risk_level,
        "finalScore": _intish(candidate_card.get("final_opportunity_score"))
        or recommendation.confidence_score,
        "directionScore": _intish(candidate_card.get("candidate_direction_score")) or 0,
        "contractScore": _intish(candidate_card.get("best_contract_score")) or 0,
        "dataConfidence": _intish(candidate_card.get("data_confidence_score")) or 0,
        "delta": _floatish(None if option_contract is None else option_contract.get("delta"))
        or 0.0,
        "impliedVolatility": implied_volatility or 0.0,
        "spreadPercent": _floatish(
            None if option_contract is None else option_contract.get("spread_percent")
        )
        or 0.0,
        "volume": _intish(None if option_contract is None else option_contract.get("volume")) or 0,
        "openInterest": _intish(
            None if option_contract is None else option_contract.get("open_interest")
        )
        or 0,
        "breakeven": _decimal_to_float(breakeven) or 0.0,
        "expectedMove": _expected_move_text(current_price=current_price, breakeven=breakeven),
        "reasonSummary": recommendation.reasoning_summary,
        "keyEvidence": _normalize_string_list(recommendation.key_evidence_json),
        "keyConcerns": _normalize_string_list(recommendation.key_concerns_json),
        "llmDecisionNote": candidate_card.get("reason_selected_or_rejected")
        or "This recommendation came from the stored workflow decision trace.",
        "warningText": warning_text,
        "feedbackAction": feedback_action,
    }


def _serialize_candidate_universe(run: WorkflowRun | None) -> list[dict[str, Any]]:
    cards = run.candidate_cards_json or [] if run is not None else []
    ordered = sorted(
        cards,
        key=lambda item: (
            _intish(item.get("final_opportunity_score")) or 0,
            _intish(item.get("data_confidence_score")) or 0,
        ),
        reverse=True,
    )
    return [
        {
            "ticker": str(card.get("ticker") or ""),
            "companyName": str(card.get("company_name") or card.get("ticker") or ""),
            "strategySource": str(card.get("strategy_source") or "stored_run"),
            "direction": _title_direction(card.get("direction_classification")),
            "finalScore": _intish(card.get("final_opportunity_score")) or 0,
            "directionScore": _intish(card.get("candidate_direction_score")) or 0,
            "dataConfidence": _intish(card.get("data_confidence_score")) or 0,
            "currentPrice": _floatish(card.get("current_price")) or 0.0,
            "earningsDate": card.get("earnings_date"),
            "relativeVolume": 0,
            "optionQuality": str(card.get("best_strategy") or "Review stored contracts"),
            "sector": str(card.get("sector") or "Unknown"),
            "note": str(card.get("reason_selected_or_rejected") or ""),
        }
        for card in ordered
    ]


def _serialize_run(run: WorkflowRun) -> dict[str, Any]:
    summary = run.run_summary_json or {}
    card = run.recommendation_card_json or {}
    watchlist = card.get("watchlist_tickers")
    decision_engine = summary.get("decision_engine") or card.get("decision_engine")
    return {
        "id": str(run.id),
        "startedAt": _dt(run.started_at),
        "triggerType": run.trigger_type,
        "status": run.status,
        "screenerStatus": summary.get("screener_status") or run.screener_status or "unknown",
        "selectedTicker": card.get("selected_ticker"),
        "contractsConsidered": _intish(summary.get("contracts_considered_count")) or 0,
        "finalistsSentToLlm": _intish(summary.get("selected_candidate_count")) or 0,
        "llmTriggered": bool(summary.get("llm_triggered") or card.get("llm_triggered")),
        "decisionEngine": decision_engine,
        "modelUsed": summary.get("model_used_heavy") or card.get("model_used_heavy"),
        "warningText": summary.get("warning_text"),
        "summary": str(
            card.get("decision_reasoning")
            or summary.get("error_message")
            or "No stored summary was captured for this run."
        ),
        "watchlist": watchlist if isinstance(watchlist, list) else [],
    }


def _serialize_schedule(schedule: Any) -> dict[str, Any]:
    return {
        "id": str(schedule.id),
        "weekday": schedule.day_of_week.capitalize(),
        "localTime": schedule.local_time,
        "timezone": TIMEZONE_DISPLAY.get(schedule.timezone_label, schedule.timezone_label),
        "status": "active" if schedule.is_active else "paused",
    }


def _serialize_pipeline_steps(run: WorkflowRun | None) -> list[dict[str, Any]]:
    if run is None:
        return []
    summary = run.run_summary_json or {}
    reports = summary.get("strategy_reports") or []
    steps = [
        {
            "id": f"step-{index}",
            "label": str(
                report.get("strategy_label") or report.get("strategy_source") or "Strategy"
            ),
            "provider": str(report.get("provider") or "Stored run"),
            "status": str(report.get("status") or "unknown"),
            "candidateCount": _intish(report.get("candidate_count")) or 0,
            "fallbackUsed": bool(report.get("fallback_used")),
        }
        for index, report in enumerate(reports, start=1)
    ]
    decision_engine = summary.get("decision_engine")
    if decision_engine is not None:
        candidate_count = _intish(summary.get("selected_candidate_count")) or 0
        if decision_engine == "llm":
            engine_status = "success"
            engine_provider = summary.get("model_used_heavy") or "OpenRouter"
        elif decision_engine in ("heuristic_fallback", "llm_blocked"):
            engine_status = "fallback"
            engine_provider = "heuristic (OpenRouter unavailable)"
        else:
            engine_status = "success"
            engine_provider = "heuristic"
        steps.append(
            {
                "id": "step-llm",
                "label": "LLM Decision",
                "provider": engine_provider,
                "status": engine_status,
                "candidateCount": candidate_count,
                "fallbackUsed": decision_engine != "llm",
            }
        )
    return steps


def _candidate_cards_by_ticker(run: WorkflowRun | None) -> dict[str, dict[str, Any]]:
    if run is None or not run.candidate_cards_json:
        return {}
    cards: dict[str, dict[str, Any]] = {}
    for item in run.candidate_cards_json:
        ticker = str(item.get("ticker") or "").upper()
        if ticker:
            cards[ticker] = item
    return cards


def _find_option_contract(
    run: WorkflowRun | None,
    *,
    ticker: str,
    option_type: str,
    position_side: str,
    strike: Decimal,
    expiry: date,
) -> dict[str, Any] | None:
    if run is None or not run.option_contracts_json:
        return None
    for item in run.option_contracts_json:
        if str(item.get("ticker") or "").upper() != ticker.upper():
            continue
        if str(item.get("option_type") or "") != option_type:
            continue
        if str(item.get("position_side") or "") != position_side:
            continue
        if str(item.get("expiry") or "") != expiry.isoformat():
            continue
        if _floatish(item.get("strike")) != _decimal_to_float(strike):
            continue
        return item
    return None


def _recommendation_rank_map(run: WorkflowRun | None) -> dict[str, int]:
    ordered = _serialize_candidate_universe(run)
    card = {} if run is None else run.recommendation_card_json or {}
    selected_ticker = str(card.get("selected_ticker") or "").upper()
    ranks: dict[str, int] = {}
    next_rank = 1
    if selected_ticker:
        ranks[selected_ticker] = next_rank
        next_rank += 1
    for row in ordered:
        ticker = str(row["ticker"] or "").upper()
        if ticker and ticker not in ranks:
            ranks[ticker] = next_rank
            next_rank += 1
    return ranks


def _selected_earnings_date(run: WorkflowRun | None, ticker: str) -> str | None:
    if run is None:
        return None
    card = run.recommendation_card_json or {}
    if str(card.get("selected_ticker") or "").upper() == ticker.upper():
        value = card.get("earnings_date")
        return None if value is None else str(value)
    candidate = _candidate_cards_by_ticker(run).get(ticker.upper(), {})
    value = candidate.get("earnings_date")
    return None if value is None else str(value)


def _selected_earnings_timing(run: WorkflowRun | None, ticker: str) -> str:
    if run is None:
        return "Unknown"
    card = run.recommendation_card_json or {}
    if str(card.get("selected_ticker") or "").upper() == ticker.upper():
        return str(card.get("earnings_timing") or "Unknown").upper()
    return "Unknown"


def _renderable_recommendation(
    recommendation: Recommendation,
    candidate_card: dict[str, Any],
):
    earnings_date = candidate_card.get("earnings_date")
    if isinstance(earnings_date, str):
        recommendation.earnings_date = date.fromisoformat(earnings_date)
    return recommendation


def _run_warning_text(run: WorkflowRun | None) -> str | None:
    if run is None:
        return None
    summary = run.run_summary_json or {}
    warning = summary.get("warning_text")
    return None if warning is None else str(warning)


def _contract_id(
    recommendation: Recommendation,
    option_contract: dict[str, Any] | None,
) -> str:
    symbol = str(
        (None if option_contract is None else option_contract.get("ticker"))
        or recommendation.ticker
    ).upper()
    option_type = str(
        (None if option_contract is None else option_contract.get("option_type"))
        or recommendation.option_type
    ).upper()
    expiry = str(
        (None if option_contract is None else option_contract.get("expiry"))
        or recommendation.expiry.isoformat()
    )
    strike = (
        _floatish(None if option_contract is None else option_contract.get("strike"))
        or _decimal_to_float(recommendation.strike)
        or 0.0
    )
    return f"{recommendation.id}:{symbol}:{expiry}:{option_type}:{strike:.2f}"


def _setup_label(rank: int) -> str:
    if rank == 2:
        return "2nd best setup"
    if rank == 3:
        return "3rd best setup"
    if rank > 3:
        return f"Alternative setup #{rank}"
    return "Best setup"


def _expected_move_text(*, current_price: float, breakeven: Decimal | float) -> str:
    if current_price <= 0:
        return "N/A"
    gap = abs(float(breakeven) - current_price) / current_price * 100
    return f"{gap:.1f}%"


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        items = value.get("items")
        if isinstance(items, list):
            return [str(item) for item in items]
    return []


def _title_direction(value: Any) -> str:
    raw = str(value or "neutral").lower()
    if raw == "bullish":
        return "Bullish"
    if raw == "bearish":
        return "Bearish"
    return "Neutral"


def _decimal_to_float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _floatish(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _intish(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dt(value) -> str | None:
    return None if value is None else value.isoformat()


async def _yfinance_price(ticker_upper: str) -> tuple[float | None, float | None]:
    import asyncio

    import yfinance as yf  # type: ignore[import-untyped]

    def _fetch_sync() -> tuple[float | None, float | None]:
        t = yf.Ticker(ticker_upper)
        info = t.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regular_market_price", None)
        prev_close = getattr(info, "previous_close", None) or getattr(
            info, "regular_market_previous_close", None
        )
        return (
            float(price) if price is not None else None,
            float(prev_close) if prev_close is not None else None,
        )

    return await asyncio.to_thread(_fetch_sync)


async def _yfinance_previous_close(ticker_upper: str) -> Decimal | None:
    _, previous_close = await _yfinance_price(ticker_upper)
    return None if previous_close is None else Decimal(str(previous_close))
