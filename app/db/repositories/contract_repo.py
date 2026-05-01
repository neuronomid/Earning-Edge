from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.db.models.option_contract import OptionContract
from app.db.repositories._base import BaseRepository


class OptionContractRepository(BaseRepository[OptionContract]):
    model = OptionContract

    async def list_for_candidate(self, candidate_id: UUID) -> list[OptionContract]:
        result = await self.session.execute(
            select(OptionContract).where(OptionContract.candidate_id == candidate_id)
        )
        return list(result.scalars().all())
