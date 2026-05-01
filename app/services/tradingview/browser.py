from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

from app.services.candidate_models import CandidateRecord
from app.services.tradingview.parser import (
    canonicalize_header,
    normalize_text,
    parse_aria_snapshot,
    parse_compact_decimal,
    parse_compact_int,
    parse_date_value,
    parse_percent,
)

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Locator, Page


class TradingViewBrowserError(RuntimeError):
    """Raised when the TradingView screener could not be prepared."""


class TradingViewAuthRequiredError(TradingViewBrowserError):
    """Raised when TradingView prompts for auth and no usable credentials exist."""


@dataclass(slots=True, frozen=True)
class TradingViewTableSnapshot:
    accessible_rows: tuple[CandidateRecord, ...]
    table_html: str | None


class TradingViewBrowserClient:
    URL = "https://www.tradingview.com/screener/"

    def __init__(
        self,
        *,
        email: str = "",
        password: str = "",
        headless: bool = False,
        timeout_ms: int = 30000,
        storage_state_path: str | None = None,
    ) -> None:
        self.email = email
        self.password = password
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.storage_state_path = Path(storage_state_path) if storage_state_path else None

    async def capture_table_snapshot(self, *, limit: int = 5) -> TradingViewTableSnapshot:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            context = await self._new_context(browser)
            page = await context.new_page()
            page.set_default_timeout(self.timeout_ms)

            try:
                await self._load_screener(page)
                await self._apply_next_week_filter(page)
                await self._sort_market_cap_desc(page, limit=limit)
                await self._maybe_add_earnings_date_column(page)
                accessible_rows = await self._extract_accessibility_rows(page, limit=limit)
                table_html = await self._table_html(page)
                return TradingViewTableSnapshot(
                    accessible_rows=tuple(accessible_rows),
                    table_html=table_html,
                )
            finally:
                await context.close()
                await browser.close()

    async def _new_context(self, browser: Browser) -> BrowserContext:
        if self.storage_state_path is not None and self.storage_state_path.exists():
            return await browser.new_context(storage_state=str(self.storage_state_path))
        return await browser.new_context()

    async def _load_screener(self, page: Page) -> None:
        await page.goto(self.URL, wait_until="domcontentloaded")
        await self._wait_for_table(page)

    async def _apply_next_week_filter(self, page: Page) -> None:
        await page.get_by_role("button", name="Upcoming earnings date").click()
        option = page.get_by_role("option", name="Next week")
        await option.wait_for(state="visible", timeout=self.timeout_ms)
        await option.click()
        await page.wait_for_timeout(800)

        if await self._signin_dialog_visible(page):
            await self._sign_in(page)
            await self._load_screener(page)
            await page.get_by_role("button", name="Upcoming earnings date").click()
            option = page.get_by_role("option", name="Next week")
            await option.wait_for(state="visible", timeout=self.timeout_ms)
            await option.click()
            await page.wait_for_timeout(800)

        await self._wait_for_table(page)

    async def _sort_market_cap_desc(self, page: Page, *, limit: int) -> None:
        sort_button = (await self._screener_table(page)).get_by_role("button", name="Change sort")
        if await sort_button.count() == 0:
            return

        for _ in range(3):
            rows = await self._extract_accessibility_rows(page, limit=limit)
            if _market_caps_desc(rows):
                return
            await sort_button.first.click()
            await page.wait_for_timeout(1000)

    async def _maybe_add_earnings_date_column(self, page: Page) -> None:
        headers = await self._header_aliases(page)
        if "earnings_date" in headers:
            return

        try:
            await page.get_by_role("button", name="Column setup").click()
            dialog = page.get_by_role("dialog").last
            if await dialog.get_by_role("combobox").count() > 0:
                search = dialog.get_by_role("combobox").first
                await search.fill("Upcoming earnings date")
                await page.wait_for_timeout(300)
            choice = dialog.locator("text=Upcoming earnings date").last
            if await choice.count() > 0:
                await choice.click()
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
        except Exception:
            return

    async def _extract_accessibility_rows(self, page: Page, *, limit: int) -> list[CandidateRecord]:
        table = await self._screener_table(page)
        aria_rows = parse_aria_snapshot(await table.aria_snapshot(), limit=limit)
        if len(aria_rows) >= limit:
            return aria_rows

        headers = await self._header_aliases(page)
        rows = table.get_by_role("row")
        row_count = await rows.count()

        parsed_rows: list[CandidateRecord] = []
        for row_index in range(1, row_count):
            row = rows.nth(row_index)
            cells = row.get_by_role("cell")
            if await cells.count() == 0:
                continue

            ticker, company_name = await self._symbol_fields(cells, headers)
            if ticker == "":
                continue

            parsed_rows.append(
                CandidateRecord(
                    ticker=ticker,
                    company_name=company_name,
                    market_cap=await self._cell_decimal(cells, headers, "market_cap"),
                    earnings_date=await self._cell_date(cells, headers, "earnings_date"),
                    current_price=await self._cell_decimal(cells, headers, "price"),
                    daily_change_percent=await self._cell_percent(cells, headers, "change_pct"),
                    volume=await self._cell_int(cells, headers, "volume"),
                    sector=await self._cell_text(cells, headers, "sector"),
                    sources=("tradingview",),
                )
            )
            if len(parsed_rows) >= limit:
                break
        return parsed_rows

    async def _header_aliases(self, page: Page) -> list[str | None]:
        table = await self._screener_table(page)
        headers = table.get_by_role("columnheader")
        aliases: list[str | None] = []
        for index in range(await headers.count()):
            text = await headers.nth(index).inner_text()
            aliases.append(canonicalize_header(text))
        return aliases

    async def _symbol_fields(
        self,
        cells: Locator,
        headers: list[str | None],
    ) -> tuple[str, str | None]:
        index = _header_index(headers, "symbol")
        if index is None:
            return "", None

        symbol_cell = cells.nth(index)
        links = symbol_cell.get_by_role("link")
        link_count = await links.count()
        if link_count >= 1:
            ticker = normalize_text(await links.nth(0).inner_text()).upper()
            company = (
                normalize_text(await links.nth(1).inner_text()) if link_count >= 2 else None
            )
            return ticker, company

        text = normalize_text(await symbol_cell.inner_text())
        if text == "":
            return "", None
        parts = text.split(" ", 1)
        ticker = parts[0].upper()
        company = parts[1] if len(parts) > 1 else None
        return ticker, company

    async def _cell_text(
        self,
        cells: Locator,
        headers: list[str | None],
        alias: str,
    ) -> str | None:
        index = _header_index(headers, alias)
        if index is None or index >= await cells.count():
            return None
        text = normalize_text(await cells.nth(index).inner_text())
        return text or None

    async def _cell_decimal(
        self,
        cells: Locator,
        headers: list[str | None],
        alias: str,
    ) -> Decimal | None:
        text = await self._cell_text(cells, headers, alias)
        return None if text is None else parse_compact_decimal(text)

    async def _cell_int(
        self,
        cells: Locator,
        headers: list[str | None],
        alias: str,
    ) -> int | None:
        text = await self._cell_text(cells, headers, alias)
        return None if text is None else parse_compact_int(text)

    async def _cell_percent(
        self,
        cells: Locator,
        headers: list[str | None],
        alias: str,
    ) -> Decimal | None:
        text = await self._cell_text(cells, headers, alias)
        return None if text is None else parse_percent(text)

    async def _cell_date(
        self,
        cells: Locator,
        headers: list[str | None],
        alias: str,
    ) -> date | None:
        text = await self._cell_text(cells, headers, alias)
        return None if text is None else parse_date_value(text)

    async def _table_html(self, page: Page) -> str | None:
        table = await self._screener_table(page)
        await table.wait_for(state="visible", timeout=self.timeout_ms)
        html = await table.evaluate("(node) => node.outerHTML")
        return str(html)

    async def _wait_for_table(self, page: Page) -> None:
        table = await self._screener_table(page)
        try:
            await table.wait_for(state="visible", timeout=self.timeout_ms)
        except Exception as exc:
            raise TradingViewBrowserError(
                "TradingView screener table never became visible"
            ) from exc

    async def _screener_table(self, page: Page) -> Locator:
        header = page.get_by_role(
            "columnheader",
            name=re.compile("Market cap", re.IGNORECASE),
        ).first
        await header.wait_for(state="visible", timeout=self.timeout_ms)
        return header.locator("xpath=ancestor::table[1]")

    async def _signin_dialog_visible(self, page: Page) -> bool:
        email_button = page.get_by_role("button", name="Email")
        sign_in_text = page.get_by_text("Sign in", exact=True)
        return await email_button.count() > 0 and await sign_in_text.count() > 0

    async def _sign_in(self, page: Page) -> None:
        if self.email == "" or self.password == "":
            raise TradingViewAuthRequiredError(
                "TradingView requested sign-in but no credentials were configured"
            )

        email_button = page.get_by_role("button", name="Email")
        await email_button.click()

        email_input = page.locator(
            "input[type='email'], input[name='email'], input[name='username'], "
            "input[name='id_username'], input[id='id_username']"
        ).first
        password_input = page.locator(
            "input[type='password'], input[name='id_password'], input[id='id_password']"
        ).first

        await email_input.wait_for(state="visible", timeout=self.timeout_ms)
        await email_input.fill(self.email)
        await password_input.fill(self.password)

        submit = page.locator(
            "button[type='submit'], button:has-text('Sign in'), button:has-text('Log in')"
        ).first
        await submit.click()
        await page.wait_for_timeout(2500)

        if await self._signin_dialog_visible(page):
            raise TradingViewAuthRequiredError("TradingView sign-in did not complete successfully")

        if self.storage_state_path is not None:
            self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
            await page.context.storage_state(path=str(self.storage_state_path))


def _header_index(headers: list[str | None], alias: str) -> int | None:
    for index, header in enumerate(headers):
        if header == alias:
            return index
    return None


def _market_caps_desc(rows: list[CandidateRecord]) -> bool:
    comparable = [row.market_cap for row in rows if row.market_cap is not None]
    if len(comparable) < 2:
        return True
    return all(left >= right for left, right in pairwise(comparable))
