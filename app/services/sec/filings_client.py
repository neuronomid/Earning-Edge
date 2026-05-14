from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol

import httpx

from app.core.logging import get_logger

_SEC_FULLTEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


@dataclass(slots=True, frozen=True)
class FilingHeader:
    cik: str
    filer_name: str | None
    accession: str
    form_type: Literal["SC 13D", "SC 13D/A"]
    filing_date: date
    primary_doc: str
    subject_ticker: str | None = None
    subject_name: str | None = None

    @property
    def primary_doc_url(self) -> str:
        numeric_accession = self.accession.replace("-", "")
        numeric_cik = str(int(self.cik))
        return f"{_SEC_ARCHIVES_BASE}/{numeric_cik}/{numeric_accession}/{self.primary_doc}"


class CacheClient(Protocol):
    async def get(self, key: str) -> str | bytes | None: ...

    async def set(self, key: str, value: str, *, ex: int) -> Any: ...


Sleeper = Callable[[float], Awaitable[None]]


class SECFilingsClient:
    def __init__(
        self,
        *,
        user_agent: str,
        throttle_rps: int = 8,
        timeout: float = 10.0,
        max_retries: int = 3,
        cache: CacheClient | None = None,
        cache_ttl_seconds: int = 86400,
        client: httpx.AsyncClient | None = None,
        sleeper: Sleeper | None = None,
        today_provider: Callable[[], date] | None = None,
        logger: Any | None = None,
    ) -> None:
        if not user_agent or "@" not in user_agent:
            raise ValueError("SEC requires a User-Agent with a contact email.")
        self.user_agent = user_agent
        self.cache = cache
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_retries = max(1, max_retries)
        self._semaphore = asyncio.Semaphore(max(1, throttle_rps))
        self._cool_down_seconds = 1.0 / max(1, throttle_rps)
        self._sleeper: Sleeper = sleeper or asyncio.sleep
        self._today_provider = today_provider or (lambda: datetime.now(tz=UTC).date())
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
        )
        self.logger = logger or get_logger(__name__)
        self._ticker_to_cik: dict[str, str] | None = None
        self._cik_to_ticker: dict[str, str] | None = None
        self._mapping_loaded_at: date | None = None

    async def close(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def fetch_recent_filings(
        self,
        *,
        form_type: Literal["SC 13D", "SC 13D/A"],
        lookback_days: int,
    ) -> tuple[FilingHeader, ...]:
        today = self._today_provider()
        start = today - timedelta(days=lookback_days)
        params = {
            "q": "",
            "forms": form_type,
            "dateRange": "custom",
            "startdt": start.isoformat(),
            "enddt": today.isoformat(),
        }
        payload = await self._request_json(_SEC_FULLTEXT_SEARCH_URL, params=params)
        if not isinstance(payload, dict):
            return ()
        hits = payload.get("hits", {})
        if not isinstance(hits, dict):
            return ()
        rows = hits.get("hits", [])
        if not isinstance(rows, list):
            return ()
        headers: list[FilingHeader] = []
        for row in rows:
            header = _filing_header_from_hit(row, form_type=form_type)
            if header is None:
                continue
            headers.append(header)
        return tuple(headers)

    async def fetch_filing_document(self, accession: str, primary_doc: str, *, cik: str) -> str:
        cache_key = f"sec:filing:{accession}"
        if self.cache is not None:
            cached = await self.cache.get(cache_key)
            if cached is not None:
                return cached.decode("utf-8") if isinstance(cached, bytes) else cached

        numeric_accession = accession.replace("-", "")
        numeric_cik = str(int(cik))
        url = f"{_SEC_ARCHIVES_BASE}/{numeric_cik}/{numeric_accession}/{primary_doc}"
        text = await self._request_text(url) or ""
        if self.cache is not None and text:
            try:
                await self.cache.set(cache_key, text, ex=self.cache_ttl_seconds)
            except Exception as exc:
                self.logger.warning("sec_filing_cache_store_failed", error=str(exc))
        return text

    async def resolve_ticker(self, cik: str) -> str | None:
        await self._ensure_ticker_mapping()
        if self._cik_to_ticker is None:
            return None
        try:
            normalized = f"{int(cik):010d}"
        except ValueError:
            return None
        return self._cik_to_ticker.get(normalized)

    async def _ensure_ticker_mapping(self) -> None:
        today = self._today_provider()
        if self._ticker_to_cik is not None and self._mapping_loaded_at == today:
            return
        payload = await self._request_json(_SEC_TICKERS_URL)
        if not isinstance(payload, dict):
            return
        ticker_to_cik: dict[str, str] = {}
        cik_to_ticker: dict[str, str] = {}
        for row in payload.values():
            if not isinstance(row, dict):
                continue
            ticker = row.get("ticker")
            cik_str = row.get("cik_str")
            if not isinstance(ticker, str) or cik_str is None:
                continue
            try:
                normalized = f"{int(cik_str):010d}"
            except ValueError:
                continue
            symbol = ticker.upper()
            ticker_to_cik[symbol] = normalized
            cik_to_ticker[normalized] = symbol
        self._ticker_to_cik = ticker_to_cik
        self._cik_to_ticker = cik_to_ticker
        self._mapping_loaded_at = today

    async def _request_text(self, url: str, *, params: dict[str, str] | None = None) -> str | None:
        response = await self._request(url, params=params)
        if response is None:
            return None
        return response.text

    async def _request_json(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        response = await self._request(url, params=params)
        if response is None:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    async def _request(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> httpx.Response | None:
        backoff = 1.0
        last_status: int | None = None
        for attempt in range(self.max_retries):
            async with self._semaphore:
                response: httpx.Response | None
                try:
                    response = await self._client.get(url, params=params)
                except httpx.HTTPError as exc:
                    self.logger.warning(
                        "sec_request_error", url=url, attempt=attempt, error=str(exc)
                    )
                    response = None
                if self._cool_down_seconds > 0:
                    await self._sleeper(self._cool_down_seconds)
            if response is not None:
                last_status = response.status_code
                if response.status_code == 429:
                    self.logger.warning(
                        "sec_rate_limited",
                        url=url,
                        attempt=attempt,
                        retry_after=response.headers.get("Retry-After"),
                    )
                    response = None
                else:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPError as exc:
                        self.logger.warning(
                            "sec_http_status_error",
                            url=url,
                            status=response.status_code,
                            attempt=attempt,
                            error=str(exc),
                        )
                        response = None
            if response is not None:
                return response
            if attempt + 1 >= self.max_retries:
                break
            jitter = random.uniform(0, backoff / 2)  # noqa: S311 - non-cryptographic jitter
            await self._sleeper(backoff + jitter)
            backoff *= 2
        self.logger.warning("sec_request_giving_up", url=url, last_status=last_status)
        return None


def _filing_header_from_hit(
    row: Any,
    *,
    form_type: Literal["SC 13D", "SC 13D/A"],
) -> FilingHeader | None:
    if not isinstance(row, dict):
        return None
    source = row.get("_source")
    if not isinstance(source, dict):
        return None
    reported_form = _text(source.get("form"))
    if reported_form is None or reported_form.upper() != form_type.upper():
        return None
    file_date = _parse_date(_text(source.get("file_date")))
    if file_date is None:
        return None

    raw_accession = _text(row.get("_id")) or _text(source.get("adsh"))
    if raw_accession is None:
        return None
    accession = _normalize_accession(raw_accession)
    if accession is None:
        return None

    ciks = source.get("ciks")
    cik_value: str | None = None
    if isinstance(ciks, list) and ciks:
        cik_value = _text(ciks[0])
    if cik_value is None:
        return None
    try:
        cik = f"{int(cik_value):010d}"
    except ValueError:
        return None

    names = source.get("display_names")
    filer_name: str | None = None
    subject_name: str | None = None
    if isinstance(names, list) and names:
        filer_name = _text(names[0])
        if len(names) > 1:
            subject_name = _text(names[1])

    primary_doc = (
        _text(source.get("primary_doc")) or _text(source.get("file_name")) or "primary.txt"
    )
    tickers = source.get("tickers")
    subject_ticker = _text(tickers[0]) if isinstance(tickers, list) and tickers else None

    return FilingHeader(
        cik=cik,
        filer_name=filer_name,
        accession=accession,
        form_type=form_type,
        filing_date=file_date,
        primary_doc=primary_doc,
        subject_ticker=subject_ticker.upper() if subject_ticker else None,
        subject_name=subject_name,
    )


def _normalize_accession(value: str) -> str | None:
    text = value.split(":", 1)[0].strip()
    if not text:
        return None
    if "-" in text:
        return text
    # 18-character compact form → 0000000000-00-000000
    digits = text.replace("-", "")
    if len(digits) != 18 or not digits.isdigit():
        return text
    return f"{digits[0:10]}-{digits[10:12]}-{digits[12:18]}"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
