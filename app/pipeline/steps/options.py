from __future__ import annotations

from typing import Protocol

from app.scoring.types import OptionContractInput
from app.services.candidate_models import CandidateRecord
from app.services.options import OptionsService, get_options_service


class OptionsStep(Protocol):
    async def execute(
        self,
        record: CandidateRecord,
        *,
        alpaca_api_key: str | None,
        alpaca_api_secret: str | None,
        strategy_permission: str,
    ) -> tuple[OptionContractInput, ...]: ...


class OptionsFetchStep:
    def __init__(self, service: OptionsService | None = None) -> None:
        self.service = service or get_options_service()

    async def execute(
        self,
        record: CandidateRecord,
        *,
        alpaca_api_key: str | None,
        alpaca_api_secret: str | None,
        strategy_permission: str,
    ) -> tuple[OptionContractInput, ...]:
        return await self.service.get_chain(
            record.ticker,
            alpaca_api_key=alpaca_api_key,
            alpaca_api_secret=alpaca_api_secret,
            strategy_permission=strategy_permission,  # type: ignore[arg-type]
            earnings_date=record.earnings_date,
        )


class NullOptionsStep:
    """Test-only placeholder that forces an empty option chain."""

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
