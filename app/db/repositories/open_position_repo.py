from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select

from app.db.models.open_position import OpenPosition
from app.db.models.recommendation import Recommendation
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

    async def list_active_with_recommendations_for_user(
        self,
        user_id: UUID,
    ) -> list[tuple[OpenPosition, Recommendation]]:
        result = await self.session.execute(
            select(OpenPosition, Recommendation)
            .join(Recommendation, Recommendation.id == OpenPosition.recommendation_id)
            .where(OpenPosition.user_id == user_id, OpenPosition.status == "active")
            .order_by(OpenPosition.created_at.asc(), OpenPosition.id.asc())
        )
        return [(position, recommendation) for position, recommendation in result.all()]

    async def list_active_with_recommendations(
        self,
    ) -> list[tuple[OpenPosition, Recommendation]]:
        result = await self.session.execute(
            select(OpenPosition, Recommendation)
            .join(Recommendation, Recommendation.id == OpenPosition.recommendation_id)
            .where(OpenPosition.status == "active")
            .order_by(OpenPosition.created_at.asc(), OpenPosition.id.asc())
        )
        return [(position, recommendation) for position, recommendation in result.all()]

    async def list_closed_with_recommendations_for_user(
        self,
        user_id: UUID,
    ) -> list[tuple[OpenPosition, Recommendation]]:
        result = await self.session.execute(
            select(OpenPosition, Recommendation)
            .join(Recommendation, Recommendation.id == OpenPosition.recommendation_id)
            .where(OpenPosition.user_id == user_id, OpenPosition.status != "active")
            .order_by(OpenPosition.entry_at.asc(), OpenPosition.id.asc())
        )
        return [(position, recommendation) for position, recommendation in result.all()]

    async def get_for_user_with_recommendation(
        self,
        user_id: UUID,
        position_id: UUID,
    ) -> tuple[OpenPosition, Recommendation] | None:
        result = await self.session.execute(
            select(OpenPosition, Recommendation)
            .join(Recommendation, Recommendation.id == OpenPosition.recommendation_id)
            .where(OpenPosition.id == position_id, OpenPosition.user_id == user_id)
        )
        row = result.first()
        if row is None:
            return None
        position, recommendation = row
        return position, recommendation

    async def expire_past_due_for_user(self, user_id: UUID, today: date) -> int:
        from app.db.models.user import User as UserModel
        from app.services.positions.account import apply_pnl_to_account

        expired_q = (
            select(OpenPosition, Recommendation)
            .join(Recommendation, Recommendation.id == OpenPosition.recommendation_id)
            .where(
                OpenPosition.user_id == user_id,
                OpenPosition.status == "active",
                Recommendation.expiry < today,
            )
        )
        rows = list((await self.session.execute(expired_q)).all())
        if not rows:
            return 0
        user = await self.session.get(UserModel, user_id)
        if user is None:
            return 0
        now = datetime.now(UTC)
        for position, recommendation in rows:
            position.status = "closed_expired"
            position.close_at = now
            apply_pnl_to_account(user, position, recommendation)
        await self.session.flush()
        return len(rows)

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
