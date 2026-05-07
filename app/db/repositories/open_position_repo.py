from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.db.models.open_position import OpenPosition
from app.db.repositories._base import BaseRepository


class OpenPositionRepository(BaseRepository[OpenPosition]):
    model = OpenPosition

    async def list_active(self) -> list[OpenPosition]:
        result = await self.session.execute(
            select(OpenPosition)
            .where(OpenPosition.status == "active")
            .order_by(OpenPosition.created_at.asc(), OpenPosition.id.asc())
        )
        return list(result.scalars().all())

    async def list_active_for_user(self, user_id: UUID) -> list[OpenPosition]:
        result = await self.session.execute(
            select(OpenPosition)
            .where(OpenPosition.user_id == user_id, OpenPosition.status == "active")
            .order_by(OpenPosition.created_at.asc(), OpenPosition.id.asc())
        )
        return list(result.scalars().all())

    async def get_active_for_user(
        self,
        user_id: UUID,
        position_id: UUID,
    ) -> OpenPosition | None:
        result = await self.session.execute(
            select(OpenPosition).where(
                OpenPosition.id == position_id,
                OpenPosition.user_id == user_id,
                OpenPosition.status == "active",
            )
        )
        return result.scalar_one_or_none()

    async def get_for_user(self, user_id: UUID, position_id: UUID) -> OpenPosition | None:
        result = await self.session.execute(
            select(OpenPosition).where(
                OpenPosition.id == position_id,
                OpenPosition.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_active_for_recommendation(
        self,
        recommendation_id: UUID,
    ) -> OpenPosition | None:
        result = await self.session.execute(
            select(OpenPosition).where(
                OpenPosition.recommendation_id == recommendation_id,
                OpenPosition.status == "active",
            )
        )
        return result.scalar_one_or_none()
