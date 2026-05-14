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
    STRATEGY_C_BASE,
    STRATEGY_C_EARNINGS_PREFIX,
    STRATEGY_C_EARNINGS_VALUES,
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

_PEAD_DEFINITION = StrategyDefinition(
    strategy_source="pead_continuation",
    strategy_label="Strategy C - PEAD Continuation",
    strategy_slug="strategy_c",
    provider="finviz",
    filter_codes=STRATEGY_C_BASE.filters,
    criteria_summary=(
        "USA optionable stocks over $10 with 500K+ average volume that reported "
        "earnings recently and are trading up today. PEAD keeps only positive "
        "earnings surprises with confirmed day-1 reaction, non-tech sector, and "
        "market cap between $300M and $10B."
    ),
    sort_summary="Daily Change descending, then PEAD composite score",
    query_urls=tuple(
        STRATEGY_C_BASE.with_filter_replaced(STRATEGY_C_EARNINGS_PREFIX, value).to_url()
        for value in STRATEGY_C_EARNINGS_VALUES
    ),
)

_SECTOR_RS_DEFINITION = StrategyDefinition(
    strategy_source="sector_relative_strength",
    strategy_label="Strategy D - Sector Relative Strength",
    strategy_slug="strategy_d",
    provider="finviz+yfinance",
    filter_codes=(),
    criteria_summary=(
        "Non-tech sector relative-strength candidates from the leading sector ETF, "
        "gated by four-week sector return and SMA-50 trend before running a dynamic "
        "public Finviz sector screener."
    ),
    sort_summary="Sector ETF 4-week return, then stock 4-week performance descending",
    query_urls=(),
)

_ACTIVIST_13D_DEFINITION = StrategyDefinition(
    strategy_source="activist_13d_followthrough",
    strategy_label="Strategy E - Activist 13D Follow-Through",
    strategy_slug="strategy_e",
    provider="sec_edgar",
    filter_codes=(),
    criteria_summary=(
        "Recent activist Schedule 13D and 13D/A filings parsed from SEC EDGAR, "
        "gated on Item 4 active-intent language and an optionable USA universe "
        "(price >= $15, average volume >= 750k, market cap >= $500M). Ranked by "
        "a deterministic event score blending stake size, recency, filer "
        "reputation, relative volume, and price confirmation."
    ),
    sort_summary="Event score descending (stake, intent, recency, filer quality)",
    query_urls=(
        "https://efts.sec.gov/LATEST/search-index?q=&forms=SC+13D",
        "https://efts.sec.gov/LATEST/search-index?q=&forms=SC+13D%2FA",
    ),
)

_DEFINITIONS: dict[StrategySource, StrategyDefinition] = {
    _CATALYST_DEFINITION.strategy_source: _CATALYST_DEFINITION,
    _PEAD_DEFINITION.strategy_source: _PEAD_DEFINITION,
    _COILED_DEFINITION.strategy_source: _COILED_DEFINITION,
    _SECTOR_RS_DEFINITION.strategy_source: _SECTOR_RS_DEFINITION,
    _ACTIVIST_13D_DEFINITION.strategy_source: _ACTIVIST_13D_DEFINITION,
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
    query_urls: tuple[str, ...] | None = None,
    filter_codes: tuple[str, ...] | None = None,
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
        query_urls=definition.query_urls if query_urls is None else query_urls,
        filter_codes=definition.filter_codes if filter_codes is None else filter_codes,
        criteria_summary=definition.criteria_summary,
        sort_summary=definition.sort_summary,
        warning_text=warning_text,
        error=error,
    )


def all_strategy_definitions() -> tuple[StrategyDefinition, ...]:
    return tuple(_DEFINITIONS.values())
