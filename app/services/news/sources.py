from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.news.types import NewsArticle

_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
_DEFAULT_SEC_USER_AGENT = "Earning-Edge/1.0 (contact: ops@example.com)"
_SEC_ACCEPTED_FORMS = {"8-K", "10-Q", "10-K", "10-Q/A", "10-K/A", "4"}


class FinnhubNewsSource:
    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(
        self,
        api_key: str = "",
        *,
        client: httpx.AsyncClient | None = None,
        lookback_days: int = 120,
        today_provider: Callable[[], date] | None = None,
        logger: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.client = client
        self.lookback_days = lookback_days
        self.today_provider = today_provider or date.today
        self.logger = logger or get_logger(__name__)

    async def fetch_ticker(
        self,
        ticker: str,
        *,
        company_name: str | None = None,
    ) -> tuple[NewsArticle, ...]:
        del company_name
        normalized = ticker.strip().upper()
        if not normalized or not self.api_key.strip():
            return ()

        end = self.today_provider()
        start = end - timedelta(days=self.lookback_days)
        payload = await self._request_json(
            "/company-news",
            params={
                "symbol": normalized,
                "from": start.isoformat(),
                "to": end.isoformat(),
            },
        )
        if not isinstance(payload, list):
            return ()

        articles: list[NewsArticle] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            title = _to_text(row.get("headline"))
            url = _to_text(row.get("url"))
            if title is None or url is None:
                continue
            summary = _to_text(row.get("summary")) or ""
            published_at = _parse_unix_timestamp(row.get("datetime"))
            content = _compose_finnhub_content(title, summary)
            articles.append(
                NewsArticle(
                    title=title,
                    url=url,
                    snippet=summary[:400],
                    content=content,
                    source=_to_text(row.get("source")) or "Finnhub",
                    published_at=published_at,
                    is_ir_fallback=False,
                )
            )
        return tuple(articles)

    async def _request_json(self, path: str, *, params: dict[str, str]) -> Any:
        async with self._client() as client:
            response = await client.get(path, params={**params, "token": self.api_key})
            response.raise_for_status()
            return response.json()

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self.client is not None:
            yield self.client
            return

        async with httpx.AsyncClient(base_url=self.BASE_URL, timeout=20.0) as client:
            yield client


class SecEdgarNewsSource:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        user_agent: str = _DEFAULT_SEC_USER_AGENT,
        today_provider: Callable[[], date] | None = None,
        logger: Any | None = None,
    ) -> None:
        self.client = client
        self.user_agent = user_agent.strip() or _DEFAULT_SEC_USER_AGENT
        self.today_provider = today_provider or date.today
        self.logger = logger or get_logger(__name__)
        self._ticker_to_cik: dict[str, str] | None = None

    async def fetch_ticker(
        self,
        ticker: str,
        *,
        company_name: str | None = None,
    ) -> tuple[NewsArticle, ...]:
        normalized = ticker.strip().upper()
        if not normalized:
            return ()

        cik = await self._resolve_cik(normalized)
        if cik is None:
            return ()

        payload = await self._request_json(_SEC_SUBMISSIONS_URL.format(cik=cik))
        if not isinstance(payload, dict):
            return ()

        company_label = _to_text(payload.get("name")) or company_name or normalized
        recent = payload.get("filings", {}).get("recent", {})
        if not isinstance(recent, dict):
            return ()

        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        accessions = recent.get("accessionNumber", [])
        documents = recent.get("primaryDocument", [])
        count = min(
            len(forms),
            len(filing_dates),
            len(report_dates),
            len(accessions),
            len(documents),
        )

        start_of_year = date(self.today_provider().year, 1, 1)
        articles: list[NewsArticle] = []
        for index in range(count):
            form = _to_text(forms[index])
            filing_date = _parse_date(filing_dates[index])
            if form is None or filing_date is None:
                continue
            if form not in _SEC_ACCEPTED_FORMS or filing_date < start_of_year:
                continue
            accession = _to_text(accessions[index])
            primary_document = _to_text(documents[index])
            if accession is None or primary_document is None:
                continue
            report_date = _parse_date(report_dates[index])
            url = _sec_document_url(cik, accession, primary_document)
            title = f"{company_label} {form} filed on {filing_date.isoformat()}"
            content = _compose_sec_content(
                company_label=company_label,
                form=form,
                filing_date=filing_date,
                report_date=report_date,
            )
            articles.append(
                NewsArticle(
                    title=title,
                    url=url,
                    snippet=content,
                    content=content,
                    source="SEC EDGAR",
                    published_at=datetime.combine(filing_date, datetime.min.time(), tzinfo=UTC),
                    is_ir_fallback=False,
                )
            )
        return tuple(articles)

    async def _resolve_cik(self, ticker: str) -> str | None:
        if self._ticker_to_cik is None:
            payload = await self._request_json(_SEC_TICKERS_URL)
            mapping: dict[str, str] = {}
            if isinstance(payload, dict):
                for row in payload.values():
                    if not isinstance(row, dict):
                        continue
                    symbol = _to_text(row.get("ticker"))
                    cik_str = row.get("cik_str")
                    if symbol is None or cik_str is None:
                        continue
                    mapping[symbol.upper()] = f"{int(cik_str):010d}"
            self._ticker_to_cik = mapping
        return None if self._ticker_to_cik is None else self._ticker_to_cik.get(ticker)

    async def _request_json(self, url: str) -> Any:
        async with self._client() as client:
            response = await client.get(url, headers={"User-Agent": self.user_agent})
            response.raise_for_status()
            return response.json()

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self.client is not None:
            yield self.client
            return

        async with httpx.AsyncClient(timeout=20.0) as client:
            yield client


def _compose_finnhub_content(title: str, summary: str) -> str:
    if not summary:
        return title
    return f"{title}\n\n{summary}".strip()


def _compose_sec_content(
    *,
    company_label: str,
    form: str,
    filing_date: date,
    report_date: date | None,
) -> str:
    report_note = (
        f" Related report date: {report_date.isoformat()}."
        if report_date is not None
        else ""
    )
    return (
        f"{company_label} filed {form} with the SEC on {filing_date.isoformat()}."
        f"{report_note} Treat this as official filing evidence rather than market commentary."
    )


def _parse_unix_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _sec_document_url(cik: str, accession: str, primary_document: str) -> str:
    numeric_accession = accession.replace("-", "")
    numeric_cik = str(int(cik))
    return f"{_SEC_ARCHIVES_BASE}/{numeric_cik}/{numeric_accession}/{primary_document}"


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
