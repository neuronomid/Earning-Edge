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
