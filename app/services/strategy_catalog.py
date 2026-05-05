from __future__ import annotations

from dataclasses import dataclass

from app.services.candidate_models import StrategyRunReport, StrategyRunStatus, StrategySource
from app.services.finviz.strategies import (
    STRATEGY_A_BASE,
    STRATEGY_A_EARNINGS_PREFIX,
    STRATEGY_A_EARNINGS_VALUES,
    STRATEGY_B_BASE,
    STRATEGY_B_VARIANT_PREFIX,
    STRATEGY_B_VARIANT_VALUES,
)


@dataclass(slots=True, frozen=True)
class StrategyDefinition:
    strategy_source: StrategySource
    strategy_label: str
    strategy_slug: str
    provider: str
    filter_codes: tuple[str, ...]
    criteria_summary: str
    sort_summary: str
    query_urls: tuple[str, ...]


_CATALYST_DEFINITION = StrategyDefinition(
    strategy_source="catalyst_confluence",
    strategy_label="Strategy A - Catalyst Confluence",
    strategy_slug="strategy_a",
    provider="finviz",
    filter_codes=STRATEGY_A_BASE.filters,
    criteria_summary=(
        "USA-listed companies reporting earnings next week, sorted by market cap. "
        "This deliberately broad Finviz screen preserves the top five visible rows; "
        "optionability, liquidity, trend, news, fundamentals, and contract quality "
        "are validated downstream."
    ),
    sort_summary="Market Cap descending",
    query_urls=tuple(
        STRATEGY_A_BASE.with_filter_replaced(STRATEGY_A_EARNINGS_PREFIX, value).to_url()
        for value in STRATEGY_A_EARNINGS_VALUES
    ),
)

_COILED_DEFINITION = StrategyDefinition(
    strategy_source="coiled_setup",
    strategy_label="Strategy B - Coiled Setup",
    strategy_slug="strategy_b",
    provider="finviz",
    filter_codes=STRATEGY_B_BASE.filters,
    criteria_summary=(
        "USA optionable stocks over $20 with market cap above $2B, 3M average "
        "volume above 1M, beta above 1, price above the 50/200-day SMAs, within "
        "20% of the 52-week high, and RSI 40-70. This keeps the structure-driven "
        "pool liquid and tradeable without over-filtering it to zero."
    ),
    sort_summary="Relative Volume descending",
    query_urls=tuple(
        STRATEGY_B_BASE.with_filter_replaced(STRATEGY_B_VARIANT_PREFIX, value).to_url()
        for value in STRATEGY_B_VARIANT_VALUES
    ),
)

_DEFINITIONS: dict[StrategySource, StrategyDefinition] = {
    _CATALYST_DEFINITION.strategy_source: _CATALYST_DEFINITION,
    _COILED_DEFINITION.strategy_source: _COILED_DEFINITION,
}


def get_strategy_definition(strategy_source: StrategySource) -> StrategyDefinition:
    return _DEFINITIONS[strategy_source]


def build_strategy_report(
    strategy_source: StrategySource,
    *,
    status: StrategyRunStatus,
    raw_row_count: int,
    candidate_count: int,
    finviz_candidate_count: int = 0,
    backup_candidate_count: int = 0,
    fallback_used: bool = False,
    warning_text: str | None = None,
    error: str | None = None,
) -> StrategyRunReport:
    definition = get_strategy_definition(strategy_source)
    return StrategyRunReport(
        strategy_source=strategy_source,
        strategy_label=definition.strategy_label,
        provider=definition.provider,
        status=status,
        raw_row_count=raw_row_count,
        candidate_count=candidate_count,
        finviz_candidate_count=finviz_candidate_count,
        backup_candidate_count=backup_candidate_count,
        fallback_used=fallback_used,
        query_urls=definition.query_urls,
        filter_codes=definition.filter_codes,
        criteria_summary=definition.criteria_summary,
        sort_summary=definition.sort_summary,
        warning_text=warning_text,
        error=error,
    )


def all_strategy_definitions() -> tuple[StrategyDefinition, ...]:
    return tuple(_DEFINITIONS.values())
