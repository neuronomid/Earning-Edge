from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.db.models.position_thesis import PositionThesis
from app.db.repositories._base import BaseRepository


class PositionThesisRepository(BaseRepository[PositionThesis]):
    model = PositionThesis

    async def get_for_position(self, position_id: UUID) -> PositionThesis | None:
        result = await self.session.execute(
            select(PositionThesis).where(PositionThesis.open_position_id == position_id)
        )
        return result.scalar_one_or_none()

    async def latest_for_user(self, user_id: UUID, *, limit: int = 20) -> list[PositionThesis]:
        result = await self.session.execute(
            select(PositionThesis)
            .where(PositionThesis.user_id == user_id)
            .order_by(PositionThesis.created_at.desc(), PositionThesis.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
