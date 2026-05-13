from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.db.models.position_plan_override import PositionPlanOverride
from app.db.repositories._base import BaseRepository


class PositionPlanOverrideRepository(BaseRepository[PositionPlanOverride]):
    model = PositionPlanOverride

    async def latest_for_position(self, position_id: UUID) -> PositionPlanOverride | None:
        result = await self.session.execute(
            select(PositionPlanOverride)
            .where(PositionPlanOverride.open_position_id == position_id)
            .order_by(
                PositionPlanOverride.created_at.desc(),
                PositionPlanOverride.id.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def latest_for_positions(
        self,
        position_ids: list[UUID] | tuple[UUID, ...],
    ) -> dict[UUID, PositionPlanOverride]:
        if not position_ids:
            return {}
        result = await self.session.execute(
            select(PositionPlanOverride)
            .where(PositionPlanOverride.open_position_id.in_(position_ids))
            .order_by(
                PositionPlanOverride.open_position_id.asc(),
                PositionPlanOverride.created_at.desc(),
                PositionPlanOverride.id.desc(),
            )
        )
        latest: dict[UUID, PositionPlanOverride] = {}
        for override in result.scalars().all():
            latest.setdefault(override.open_position_id, override)
        return latest
