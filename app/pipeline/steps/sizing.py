from __future__ import annotations

from typing import Protocol

from app.scoring.types import OptionContractInput, UserContext
from app.services.sizing import size
from app.services.sizing_types import SizingResult


class SizingStep(Protocol):
    async def execute(
        self,
        user: UserContext,
        contract: OptionContractInput,
    ) -> SizingResult: ...


class PositionSizingStep:
    async def execute(
        self,
        user: UserContext,
        contract: OptionContractInput,
    ) -> SizingResult:
        return size(user, contract)
