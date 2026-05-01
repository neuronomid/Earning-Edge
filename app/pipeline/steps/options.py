from __future__ import annotations

from typing import Protocol

from app.scoring.types import OptionContractInput
from app.services.candidate_models import CandidateRecord


class OptionsStep(Protocol):
    async def execute(
        self,
        record: CandidateRecord,
        *,
        alpaca_api_key: str | None,
        alpaca_api_secret: str | None,
        strategy_permission: str,
    ) -> tuple[OptionContractInput, ...]: ...


class NullOptionsStep:
    """Phase-11 placeholder until the phase-6 options service is wired in."""

    async def execute(
        self,
        record: CandidateRecord,
        *,
        alpaca_api_key: str | None,
        alpaca_api_secret: str | None,
        strategy_permission: str,
    ) -> tuple[OptionContractInput, ...]:
        del record, alpaca_api_key, alpaca_api_secret, strategy_permission
        return ()
