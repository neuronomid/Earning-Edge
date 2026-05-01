"""Lightweight API-key validators (PRD §7.1).

Each validator runs a single cheap, read-only request against the provider and
returns `ValidationResult`. The bot uses these to fail fast during onboarding
before persisting an unusable key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


@dataclass(slots=True, frozen=True)
class ValidationResult:
    ok: bool
    detail: str = ""


class ApiKeyValidator(Protocol):
    async def validate(self, *args: str) -> ValidationResult: ...


class OpenRouterValidator:
    """Validates an OpenRouter key by hitting GET /api/v1/auth/key."""

    URL = "https://openrouter.ai/api/v1/auth/key"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def validate(self, api_key: str) -> ValidationResult:
        if not api_key or not api_key.strip():
            return ValidationResult(False, "Empty API key.")

        headers = {"Authorization": f"Bearer {api_key.strip()}"}
        try:
            if self._client is not None:
                resp = await self._client.get(self.URL, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                    resp = await client.get(self.URL, headers=headers)
        except httpx.HTTPError as exc:
            return ValidationResult(False, f"Network error: {exc}")

        if resp.status_code == 200:
            return ValidationResult(True, "OpenRouter key accepted.")
        if resp.status_code in (401, 403):
            return ValidationResult(False, "OpenRouter rejected the key (unauthorized).")
        return ValidationResult(
            False, f"Unexpected response from OpenRouter: HTTP {resp.status_code}."
        )


class AlpacaValidator:
    """Validates Alpaca creds by hitting GET /v2/account on the paper endpoint.

    Paper is used because (a) it works for any live account too via the data API,
    and (b) we never touch trading endpoints. PRD §6.2 only needs read access.
    """

    URL = "https://paper-api.alpaca.markets/v2/account"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def validate(self, api_key: str, api_secret: str) -> ValidationResult:
        if not api_key or not api_secret:
            return ValidationResult(False, "Both Alpaca key and secret are required.")
        headers = {
            "APCA-API-KEY-ID": api_key.strip(),
            "APCA-API-SECRET-KEY": api_secret.strip(),
        }
        try:
            if self._client is not None:
                resp = await self._client.get(self.URL, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                    resp = await client.get(self.URL, headers=headers)
        except httpx.HTTPError as exc:
            return ValidationResult(False, f"Network error: {exc}")

        if resp.status_code == 200:
            return ValidationResult(True, "Alpaca credentials accepted.")
        if resp.status_code in (401, 403):
            return ValidationResult(False, "Alpaca rejected the credentials.")
        return ValidationResult(False, f"Unexpected response from Alpaca: HTTP {resp.status_code}.")


class AlphaVantageValidator:
    """Validates an Alpha Vantage key with a tiny GLOBAL_QUOTE call."""

    URL = "https://www.alphavantage.co/query"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def validate(self, api_key: str) -> ValidationResult:
        if not api_key or not api_key.strip():
            return ValidationResult(False, "Empty API key.")
        params = {"function": "GLOBAL_QUOTE", "symbol": "IBM", "apikey": api_key.strip()}
        try:
            if self._client is not None:
                resp = await self._client.get(self.URL, params=params)
            else:
                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                    resp = await client.get(self.URL, params=params)
        except httpx.HTTPError as exc:
            return ValidationResult(False, f"Network error: {exc}")

        if resp.status_code != 200:
            return ValidationResult(
                False, f"Unexpected response from Alpha Vantage: HTTP {resp.status_code}."
            )
        try:
            payload = resp.json()
        except ValueError:
            return ValidationResult(False, "Alpha Vantage returned a non-JSON response.")

        # AV always returns 200; the failure modes are in the payload body.
        if "Error Message" in payload:
            return ValidationResult(False, "Alpha Vantage rejected the key.")
        if "Note" in payload or "Information" in payload:
            # Rate-limit / informational message; the key is still valid.
            return ValidationResult(True, "Alpha Vantage key accepted (rate-limited reply).")
        if "Global Quote" in payload:
            return ValidationResult(True, "Alpha Vantage key accepted.")
        return ValidationResult(False, "Alpha Vantage returned an unrecognized payload shape.")
