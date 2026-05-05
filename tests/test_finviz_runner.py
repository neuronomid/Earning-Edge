from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from app.services.candidate_models import CandidateRecord
from app.services.finviz.query import FinvizQuery
from app.services.finviz.runner import FinvizAllVariantsFailedError, FinvizQueryRunner

pytestmark = pytest.mark.asyncio


@dataclass
class FakeBrowser:
    rows_by_url: dict[str, list[CandidateRecord]] = field(default_factory=dict)
    error_by_url: dict[str, Exception] = field(default_factory=dict)
    seen_urls: list[str] = field(default_factory=list)

    async def capture_snapshot(
        self,
        query: FinvizQuery,
        *,
        limit: int = 5,
    ) -> list[CandidateRecord]:
        url = query.to_url()
        self.seen_urls.append(url)
        if url in self.error_by_url:
            raise self.error_by_url[url]
        return self.rows_by_url.get(url, [])[:limit]


def _row(ticker: str, *, rank: int, market_cap: str = "1000") -> CandidateRecord:
    return CandidateRecord(
        ticker=ticker,
        company_name=f"{ticker} Co",
        market_cap=Decimal(market_cap),
        earnings_date=None,
        current_price=Decimal("100"),
        screener_rank=rank,
        sources=("finviz",),
    )


async def test_run_with_swap_dedupes_by_ticker_keeping_best_rank() -> None:
    base = FinvizQuery(filters=("cap_midover", "x_a"), sort="-x")
    url_a = base.with_filter_replaced("x_", "x_a").to_url()
    url_b = base.with_filter_replaced("x_", "x_b").to_url()
    browser = FakeBrowser(
        rows_by_url={
            url_a: [_row("AAA", rank=1), _row("BBB", rank=2)],
            url_b: [_row("AAA", rank=5), _row("CCC", rank=1)],
        }
    )
    runner = FinvizQueryRunner(browser)

    rows = await runner.run_with_swap(
        base,
        swap_prefix="x_",
        swap_values=("x_a", "x_b"),
        limit=5,
        strategy_source="catalyst_confluence",
    )

    tickers = [row.ticker for row in rows]
    assert "AAA" in tickers
    assert tickers.count("AAA") == 1
    assert {"AAA", "BBB", "CCC"} <= set(tickers)


async def test_run_with_swap_stamps_strategy_source() -> None:
    base = FinvizQuery(filters=("x_a",), sort="-x")
    url = base.with_filter_replaced("x_", "x_a").to_url()
    browser = FakeBrowser(rows_by_url={url: [_row("AAA", rank=1)]})
    runner = FinvizQueryRunner(browser)

    rows = await runner.run_with_swap(
        base,
        swap_prefix="x_",
        swap_values=("x_a",),
        limit=5,
        strategy_source="coiled_setup",
    )

    assert all(row.strategy_source == "coiled_setup" for row in rows)


async def test_run_with_swap_continues_when_one_variant_fails() -> None:
    base = FinvizQuery(filters=("x_a",), sort="-x")
    url_a = base.with_filter_replaced("x_", "x_a").to_url()
    url_b = base.with_filter_replaced("x_", "x_b").to_url()
    browser = FakeBrowser(
        rows_by_url={url_a: [_row("AAA", rank=1)]},
        error_by_url={url_b: RuntimeError("Finviz blew up")},
    )
    runner = FinvizQueryRunner(browser)

    rows = await runner.run_with_swap(
        base,
        swap_prefix="x_",
        swap_values=("x_a", "x_b"),
        limit=5,
        strategy_source="catalyst_confluence",
    )

    assert [row.ticker for row in rows] == ["AAA"]


async def test_run_with_swap_re_ranks_starting_at_one() -> None:
    base = FinvizQuery(filters=("x_a",), sort="-x")
    url_a = base.with_filter_replaced("x_", "x_a").to_url()
    url_b = base.with_filter_replaced("x_", "x_b").to_url()
    browser = FakeBrowser(
        rows_by_url={
            url_a: [_row("AAA", rank=3)],
            url_b: [_row("BBB", rank=2)],
        }
    )
    runner = FinvizQueryRunner(browser)

    rows = await runner.run_with_swap(
        base,
        swap_prefix="x_",
        swap_values=("x_a", "x_b"),
        limit=5,
        strategy_source="catalyst_confluence",
    )
    assert [row.screener_rank for row in rows] == [1, 2]


async def test_run_with_swap_uses_cache_when_present() -> None:
    base = FinvizQuery(filters=("x_a",), sort="-x")
    cache_store: dict[tuple[str, str], list[CandidateRecord]] = {}

    class FakeCache:
        async def load(self, strategy_source, query):
            return cache_store.get((strategy_source, query.stable_hash()))

        async def store(self, strategy_source, query, rows):
            cache_store[(strategy_source, query.stable_hash())] = rows

    cached_rows = [_row("ZZZ", rank=1)]
    cache = FakeCache()
    cache_store[("catalyst_confluence", base.with_filter_replaced("x_", "x_a").stable_hash())] = (
        cached_rows
    )

    browser = FakeBrowser()
    runner = FinvizQueryRunner(browser, cache=cache)

    rows = await runner.run_with_swap(
        base,
        swap_prefix="x_",
        swap_values=("x_a",),
        limit=5,
        strategy_source="catalyst_confluence",
    )

    assert browser.seen_urls == []
    assert [row.ticker for row in rows] == ["ZZZ"]


async def test_run_with_swap_raises_when_all_variants_fail() -> None:
    base = FinvizQuery(filters=("x_a",), sort="-x")
    url_a = base.with_filter_replaced("x_", "x_a").to_url()
    url_b = base.with_filter_replaced("x_", "x_b").to_url()
    browser = FakeBrowser(
        error_by_url={
            url_a: RuntimeError("Finviz blew up a"),
            url_b: RuntimeError("Finviz blew up b"),
        }
    )
    runner = FinvizQueryRunner(browser)

    with pytest.raises(FinvizAllVariantsFailedError):
        await runner.run_with_swap(
            base,
            swap_prefix="x_",
            swap_values=("x_a", "x_b"),
            limit=5,
            strategy_source="catalyst_confluence",
        )
