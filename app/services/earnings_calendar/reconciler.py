from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from app.services.candidate_models import CandidateRecord


class CandidateValidationError(RuntimeError):
    """Raised when a candidate fails Phase 4 hard validation checks."""


class CandidateReconciler:
    def reconcile(
        self,
        primary: CandidateRecord,
        backups: Iterable[CandidateRecord | None],
    ) -> CandidateRecord:
        records = [primary, *[record for record in backups if record is not None]]

        ticker = _first_non_blank(record.ticker for record in records)
        if ticker is None:
            raise CandidateValidationError("ticker cannot be verified")

        company_name = _first_non_blank(record.company_name for record in records)
        market_cap = primary.market_cap or _first_non_none(record.market_cap for record in records)
        current_price = primary.current_price or _first_non_none(
            record.current_price for record in records
        )
        daily_change_percent = primary.daily_change_percent or _first_non_none(
            record.daily_change_percent for record in records
        )
        volume = primary.volume or _first_non_none(record.volume for record in records)
        sector = primary.sector or _first_non_blank(record.sector for record in records)

        earnings_date = self._resolve_earnings_date(records)
        notes = list(primary.validation_notes)

        if company_name is None:
            raise CandidateValidationError("company has no usable market data")
        if market_cap is None:
            raise CandidateValidationError("company has no usable market data")
        if current_price is None:
            raise CandidateValidationError("current price is unavailable")

        backup_market_cap = _first_non_none(
            record.market_cap for record in records[1:] if record.market_cap is not None
        )
        if primary.market_cap is not None and backup_market_cap is not None:
            if _relative_difference(primary.market_cap, backup_market_cap) > Decimal("0.05"):
                notes.append("market cap differs across sources; kept TradingView ranking value")

        dates = {record.earnings_date for record in records if record.earnings_date is not None}
        if len(dates) > 1:
            notes.append("earnings date required cross-source verification")

        return CandidateRecord(
            ticker=ticker.upper(),
            company_name=company_name,
            market_cap=market_cap,
            earnings_date=earnings_date,
            current_price=current_price,
            daily_change_percent=daily_change_percent,
            volume=volume,
            sector=sector,
            sources=_merge_sources(records),
            validation_notes=tuple(dict.fromkeys(notes)),
        )

    def _resolve_earnings_date(self, records: list[CandidateRecord]) -> date:
        dates = [record.earnings_date for record in records if record.earnings_date is not None]
        if not dates:
            raise CandidateValidationError("earnings date cannot be verified")

        counts = Counter(dates)
        if len(counts) == 1:
            return dates[0]

        chosen_date, support = counts.most_common(1)[0]
        if support < 2:
            raise CandidateValidationError("earnings date cannot be verified")
        return chosen_date


def _first_non_none[T](values: Iterable[T | None]) -> T | None:
    for value in values:
        if value is not None:
            return value
    return None


def _first_non_blank(values: Iterable[str | None]) -> str | None:
    for value in values:
        if value is not None and value.strip() != "":
            return value
    return None


def _merge_sources(records: Iterable[CandidateRecord]) -> tuple[str, ...]:
    merged: list[str] = []
    for record in records:
        for source in record.sources:
            if source not in merged:
                merged.append(source)
    return tuple(merged)


def _relative_difference(left: Decimal, right: Decimal) -> Decimal:
    baseline = max(abs(left), abs(right), Decimal("1"))
    return abs(left - right) / baseline
