from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.db.models.recommendation import Recommendation
from app.db.repositories._base import BaseRepository


class RecommendationRepository(BaseRepository[Recommendation]):
    model = Recommendation

    async def list_recent_for_user(
        self, user_id: UUID, limit: int = 20
    ) -> list[Recommendation]:
        result = await self.session.execute(
            select(Recommendation)
            .where(Recommendation.user_id == user_id)
            .order_by(Recommendation.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_child_for_parent(self, parent_recommendation_id: UUID) -> Recommendation | None:
        result = await self.session.execute(
            select(Recommendation)
            .where(Recommendation.parent_recommendation_id == parent_recommendation_id)
            .order_by(Recommendation.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
