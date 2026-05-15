from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func, select

from app.db.models.position_revalidation import PositionRevalidation
from app.db.repositories._base import BaseRepository


class PositionRevalidationRepository(BaseRepository[PositionRevalidation]):
    model = PositionRevalidation

    async def list_for_position(
        self,
        position_id: UUID,
        *,
        limit: int = 5,
    ) -> list[PositionRevalidation]:
        result = await self.session.execute(
            select(PositionRevalidation)
            .where(PositionRevalidation.open_position_id == position_id)
            .order_by(
                PositionRevalidation.fired_at.desc(),
                PositionRevalidation.id.desc(),
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_recent_auto(
        self,
        position_id: UUID,
        *,
        since: datetime,
    ) -> list[PositionRevalidation]:
        result = await self.session.execute(
            select(PositionRevalidation)
            .where(
                PositionRevalidation.open_position_id == position_id,
                PositionRevalidation.trigger == "auto",
                PositionRevalidation.fired_at >= since,
            )
            .order_by(PositionRevalidation.fired_at.desc())
        )
        return list(result.scalars().all())

    async def count_auto_for_session(
        self,
        position_id: UUID,
        *,
        session_date: date,
    ) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(PositionRevalidation)
            .where(
                PositionRevalidation.open_position_id == position_id,
                PositionRevalidation.trigger == "auto",
                PositionRevalidation.market_session_date == session_date,
            )
        )
        return int(result.scalar_one())

    async def already_handled_codes(
        self,
        position_id: UUID,
        *,
        trigger_codes: Sequence[str],
        since: datetime,
    ) -> bool:
        if not trigger_codes:
            return False
        recent = await self.list_recent_auto(position_id, since=since)
        if not recent:
            return False
        requested = set(trigger_codes)
        handled: set[str] = set()
        for row in recent:
            handled.update(str(code) for code in row.trigger_codes_json or [])
        return requested.issubset(handled)
