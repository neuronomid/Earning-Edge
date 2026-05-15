from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from app.services.sec.filings_client import SECFilingsClient

pytestmark = pytest.mark.asyncio


class InMemoryCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.sets: list[tuple[str, str, int]] = []

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.store[key] = value
        self.sets.append((key, value, ex))


def _build_search_payload(
    *,
    accession: str = "0001234567-25-000123",
    cik: str = "0000111111",
    form: str = "SC 13D",
    file_date: str = "2026-05-12",
    primary_doc: str = "primary.htm",
    filer_name: str = "Activist LP",
) -> dict[str, Any]:
    return {
        "hits": {
            "hits": [
                {
                    "_id": accession,
                    "_source": {
                        "ciks": [cik],
                        "display_names": [filer_name],
                        "form": form,
                        "file_date": file_date,
                        "primary_doc": primary_doc,
                    },
                }
            ]
        }
    }


async def test_user_agent_required_and_throttled() -> None:
    with pytest.raises(ValueError, match="contact email"):
        SECFilingsClient(user_agent="missing-contact")
    with pytest.raises(ValueError, match="contact email"):
        SECFilingsClient(user_agent="")


async def test_recovers_from_429_with_backoff() -> None:
    attempts: list[int] = []
    payload = _build_search_payload()

    def _handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        sleeps: list[float] = []

        async def _sleep(seconds: float) -> None:
            sleeps.append(seconds)

        client = SECFilingsClient(
            user_agent="EarningEdge ops@example.com",
            client=http_client,
            sleeper=_sleep,
            today_provider=lambda: date(2026, 5, 14),
        )

        headers = await client.fetch_recent_filings(form_type="SC 13D", lookback_days=5)

    assert len(attempts) == 2
    assert any(s >= 1.0 for s in sleeps), "expected backoff sleep before retry"
    assert headers[0].accession == "0001234567-25-000123"


async def test_caches_filing_by_accession() -> None:
    calls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="<html>filing body</html>")

    transport = httpx.MockTransport(_handler)
    cache = InMemoryCache()
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = SECFilingsClient(
            user_agent="EarningEdge ops@example.com",
            client=http_client,
            sleeper=_no_sleep,
            cache=cache,
            cache_ttl_seconds=3600,
        )

        first = await client.fetch_filing_document(
            "0001234567-25-000123", "primary.htm", cik="0000111111"
        )
        second = await client.fetch_filing_document(
            "0001234567-25-000123", "primary.htm", cik="0000111111"
        )

    assert first == "<html>filing body</html>"
    assert second == first
    assert len(calls) == 1, "second call should be served from cache"
    assert ("sec:filing:0001234567-25-000123", first, 3600) in cache.sets


async def _no_sleep(_seconds: float) -> None:
    return None
