from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.candidate_models import CandidateRecord
from app.services.parsing import parse_compact_decimal, parse_compact_int, parse_percent

if TYPE_CHECKING:
    from playwright.async_api import Page


class FinvizBrowserError(RuntimeError):
    """Raised when the Finviz screener table could not be loaded."""


class FinvizBrowserClient:
    URL = "https://finviz.com/screener?v=111&f=earningsdate_nextweek,geo_usa&o=-marketcap"
    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = 30000,
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms

    async def capture_snapshot(self, *, limit: int = 5) -> list[CandidateRecord]:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent=self._USER_AGENT,
                viewport={"width": 1600, "height": 900},
            )
            page = await context.new_page()
            page.set_default_timeout(self.timeout_ms)
            try:
                await self._load_screener(page)
                return await self._extract_rows(page, limit=limit)
            finally:
                await context.close()
                await browser.close()

    async def _load_screener(self, page: Page) -> None:
        await page.goto(self.URL, wait_until="domcontentloaded")
        table = page.locator("table.styled-table-new")
        try:
            await table.wait_for(state="visible", timeout=self.timeout_ms)
        except Exception as exc:
            raise FinvizBrowserError(
                "Finviz screener table never became visible"
            ) from exc
        await page.wait_for_timeout(500)

    async def _extract_rows(self, page: Page, *, limit: int) -> list[CandidateRecord]:
        raw_rows: list[list[str]] = await page.evaluate(
            """(limit) => {
                const table = document.querySelector('table.styled-table-new');
                if (!table) return [];
                const rows = Array.from(table.querySelectorAll('tr')).slice(1, limit + 1);
                return rows.map(row =>
                    Array.from(row.querySelectorAll('td')).map(c => c.textContent.trim())
                );
            }""",
            limit,
        )

        records: list[CandidateRecord] = []
        for index, cells in enumerate(raw_rows, start=1):
            if len(cells) < 11:
                continue
            ticker = cells[1].strip().upper()
            if not ticker:
                continue
            records.append(
                CandidateRecord(
                    ticker=ticker,
                    company_name=cells[2] or None,
                    sector=cells[3] or None,
                    market_cap=parse_compact_decimal(cells[6]),
                    screener_rank=index,
                    current_price=parse_compact_decimal(cells[8]),
                    daily_change_percent=parse_percent(cells[9]),
                    volume=parse_compact_int(cells[10]),
                    earnings_date=None,
                    sources=("finviz",),
                )
            )
        return records[:limit]
