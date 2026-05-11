from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.user import User
from app.db.session import get_session
from app.services.market_data.alpaca_stream_manager import (
    AlpacaStreamCredentials,
    get_alpaca_stream_manager,
    parse_stream_positions,
)
from app.services.user_service import UserService, decrypt_or_none

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
log = get_logger("dashboard_live_market_data")


@router.websocket("/live-market-data")
async def live_market_data_socket(
    websocket: WebSocket,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    await websocket.accept()
    manager = get_alpaca_stream_manager()
    client_id, queue = await manager.connect_client()
    sender = asyncio.create_task(_send_loop(websocket, queue))
    try:
        await websocket.send_json({"type": "connected", "clientId": client_id})
        while True:
            payload = await websocket.receive_json()
            message_type = payload.get("type")
            if message_type == "subscribe":
                user = await _resolve_dashboard_user(
                    session,
                    payload.get("dashboardUserId") or payload.get("userId"),
                )
                if user is None:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "Dashboard user was not found for live market data.",
                        }
                    )
                    continue
                api_key = decrypt_or_none(user.alpaca_api_key_encrypted)
                api_secret = decrypt_or_none(user.alpaca_api_secret_encrypted)
                if not api_key or not api_secret:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "Alpaca credentials are not saved for this dashboard user.",
                        }
                    )
                    continue

                positions = parse_stream_positions(payload)
                credentials = AlpacaStreamCredentials(
                    user_id=str(user.id),
                    api_key=api_key,
                    api_secret=api_secret,
                    stock_feed=str(payload.get("stockFeed") or "iex").lower(),
                    option_feed=str(payload.get("optionFeed") or "indicative").lower(),
                )
                await manager.subscribe(client_id, credentials, positions)
                await websocket.send_json(
                    {
                        "type": "subscribed",
                        "positionIds": [position.position_id for position in positions],
                        "stockSource": f"alpaca_{credentials.stock_feed}_stream",
                        "optionSource": "alpaca_option_stream",
                    }
                )
            elif message_type == "unsubscribe":
                await manager.unsubscribe_positions(
                    client_id,
                    [str(item) for item in payload.get("positionIds") or []],
                )
            elif message_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
        await manager.disconnect_client(client_id)


async def _send_loop(
    websocket: WebSocket,
    queue: asyncio.Queue[dict[str, Any]],
) -> None:
    while True:
        event = await queue.get()
        await websocket.send_json(event)


async def _resolve_dashboard_user(session: AsyncSession, value: object) -> User | None:
    raw = str(value or "").strip()
    if raw:
        try:
            user = await session.get(User, UUID(raw))
            return user if user and user.is_active else None
        except ValueError:
            pass
        by_username = await UserService(session).get_by_dashboard_username(raw)
        if by_username is not None:
            return by_username
        by_chat = await UserService(session).get_by_chat_id(raw)
        if by_chat is not None:
            return by_chat

    result = await session.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.updated_at.desc())
    )
    return result.scalars().first()
