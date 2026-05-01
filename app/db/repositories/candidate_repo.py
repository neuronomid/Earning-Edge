from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.db.models.candidate import Candidate
from app.db.repositories._base import BaseRepository


class CandidateRepository(BaseRepository[Candidate]):
    model = Candidate

    async def list_for_run(self, run_id: UUID) -> list[Candidate]:
        result = await self.session.execute(
            select(Candidate).where(Candidate.run_id == run_id)
        )
        return list(result.scalars().all())
