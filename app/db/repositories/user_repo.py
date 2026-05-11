from __future__ import annotations

from sqlalchemy import func, select

from app.db.models.user import User
from app.db.repositories._base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_telegram_chat_id(self, telegram_chat_id: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.telegram_chat_id == telegram_chat_id)
        )
        return result.scalar_one_or_none()

    async def get_by_dashboard_username(self, username: str) -> User | None:
        result = await self.session.execute(
            select(User).where(func.lower(User.dashboard_username) == username.lower())
        )
        return result.scalar_one_or_none()
