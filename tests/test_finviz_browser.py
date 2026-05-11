from __future__ import annotations

import pytest

from app.services.finviz.browser import FinvizBrowserClient, FinvizBrowserError

pytestmark = pytest.mark.asyncio


class FakePage:
    pass


async def test_load_screener_with_retry_retries_same_page_once() -> None:
    client = FinvizBrowserClient()
    page = FakePage()
    calls: list[str] = []

    async def fake_load(target_page, *, url: str) -> None:
        assert target_page is page
        calls.append(url)
        if len(calls) == 1:
            raise FinvizBrowserError("first attempt failed")

    client._load_screener = fake_load  # type: ignore[method-assign]

    await client._load_screener_with_retry(page, url="https://finviz.com/screener")

    assert calls == ["https://finviz.com/screener", "https://finviz.com/screener"]


async def test_load_screener_with_retry_raises_after_second_failure() -> None:
    client = FinvizBrowserClient()
    page = FakePage()
    calls: list[str] = []

    async def fake_load(target_page, *, url: str) -> None:
        assert target_page is page
        calls.append(url)
        raise FinvizBrowserError("still failing")

    client._load_screener = fake_load  # type: ignore[method-assign]

    with pytest.raises(FinvizBrowserError):
        await client._load_screener_with_retry(page, url="https://finviz.com/screener")

    assert calls == ["https://finviz.com/screener", "https://finviz.com/screener"]


async def test_capture_snapshot_uses_clean_context_only_after_same_page_retry_fails() -> None:
    client = FinvizBrowserClient()
    calls: list[bool] = []

    class FakeBrowser:
        async def close(self) -> None:
            return None

    class FakePlaywrightContext:
        chromium = None  # type: ignore[assignment]

        async def __aenter__(self):
            class Chromium:
                async def launch(self, *, headless: bool):
                    del headless
                    return FakeBrowser()

            self.chromium = Chromium()
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    async def fake_capture_with_context(
        browser,
        *,
        url: str,
        limit: int,
        retry_page_once: bool,
    ) -> list:
        del browser, url, limit
        calls.append(retry_page_once)
        if retry_page_once:
            raise FinvizBrowserError("first context failed")
        return []

    client._capture_with_context = fake_capture_with_context  # type: ignore[method-assign]

    import sys
    from types import SimpleNamespace

    fake_module = SimpleNamespace(async_playwright=lambda: FakePlaywrightContext())
    original = sys.modules.get("playwright.async_api")
    sys.modules["playwright.async_api"] = fake_module
    try:
        await client.capture_snapshot(
            query=type("Q", (), {"to_url": lambda self: "https://finviz.com"})()
        )
    finally:
        if original is None:
            sys.modules.pop("playwright.async_api", None)
        else:
            sys.modules["playwright.async_api"] = original

    assert calls == [True, False]
