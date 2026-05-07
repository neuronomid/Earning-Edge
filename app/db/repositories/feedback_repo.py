from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select

from app.db.models.feedback_event import FeedbackEvent
from app.db.repositories._base import BaseRepository


class FeedbackEventRepository(BaseRepository[FeedbackEvent]):
    model = FeedbackEvent

    async def list_for_recommendation(
        self, recommendation_id: UUID
    ) -> list[FeedbackEvent]:
        result = await self.session.execute(
            select(FeedbackEvent).where(
                FeedbackEvent.recommendation_id == recommendation_id
            )
        )
        return list(result.scalars().all())

    async def delete_for_recommendation_user(
        self, recommendation_id: UUID, user_id: UUID
    ) -> None:
        await self.session.execute(
            delete(FeedbackEvent).where(
                FeedbackEvent.recommendation_id == recommendation_id,
                FeedbackEvent.user_id == user_id,
            )
        )
