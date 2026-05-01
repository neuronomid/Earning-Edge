"""API-key validator tests (PRD §7.1)."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.services.api_key_validators import (
    AlpacaValidator,
    AlphaVantageValidator,
    OpenRouterValidator,
)

pytestmark = pytest.mark.asyncio


# ---------- OpenRouter ----------


@respx.mock
async def test_openrouter_validates_on_200() -> None:
    respx.get(OpenRouterValidator.URL).mock(
        return_value=httpx.Response(200, json={"data": {"label": "ok"}})
    )
    result = await OpenRouterValidator().validate("sk-or-test")
    assert result.ok is True


@respx.mock
async def test_openrouter_rejects_on_401() -> None:
    respx.get(OpenRouterValidator.URL).mock(return_value=httpx.Response(401, json={}))
    result = await OpenRouterValidator().validate("sk-or-bad")
    assert result.ok is False
    assert "unauthor" in result.detail.lower()


async def test_openrouter_rejects_empty_key() -> None:
    result = await OpenRouterValidator().validate("")
    assert result.ok is False


@respx.mock
async def test_openrouter_handles_network_error() -> None:
    respx.get(OpenRouterValidator.URL).mock(side_effect=httpx.ConnectError("boom"))
    result = await OpenRouterValidator().validate("sk-or-test")
    assert result.ok is False
    assert "network" in result.detail.lower()


# ---------- Alpaca ----------


@respx.mock
async def test_alpaca_validates_on_200() -> None:
    respx.get(AlpacaValidator.URL).mock(
        return_value=httpx.Response(200, json={"id": "x", "status": "ACTIVE"})
    )
    result = await AlpacaValidator().validate("AKEY", "ASEC")
    assert result.ok is True


@respx.mock
async def test_alpaca_rejects_on_403() -> None:
    respx.get(AlpacaValidator.URL).mock(return_value=httpx.Response(403, json={}))
    result = await AlpacaValidator().validate("AKEY", "ASEC")
    assert result.ok is False


async def test_alpaca_rejects_missing_secret() -> None:
    result = await AlpacaValidator().validate("AKEY", "")
    assert result.ok is False


@respx.mock
async def test_alpaca_handles_network_error() -> None:
    respx.get(AlpacaValidator.URL).mock(side_effect=httpx.ConnectError("boom"))
    result = await AlpacaValidator().validate("AKEY", "ASEC")
    assert result.ok is False
    assert "network" in result.detail.lower()


# ---------- Alpha Vantage ----------


@respx.mock
async def test_av_validates_on_global_quote() -> None:
    respx.get(AlphaVantageValidator.URL).mock(
        return_value=httpx.Response(200, json={"Global Quote": {"01. symbol": "IBM"}})
    )
    result = await AlphaVantageValidator().validate("AVKEY")
    assert result.ok is True


@respx.mock
async def test_av_treats_rate_limit_note_as_valid() -> None:
    respx.get(AlphaVantageValidator.URL).mock(
        return_value=httpx.Response(200, json={"Note": "rate limited"})
    )
    result = await AlphaVantageValidator().validate("AVKEY")
    assert result.ok is True


@respx.mock
async def test_av_rejects_on_error_message() -> None:
    respx.get(AlphaVantageValidator.URL).mock(
        return_value=httpx.Response(200, json={"Error Message": "Invalid API call"})
    )
    result = await AlphaVantageValidator().validate("AVKEY")
    assert result.ok is False


@respx.mock
async def test_av_rejects_unknown_payload() -> None:
    respx.get(AlphaVantageValidator.URL).mock(
        return_value=httpx.Response(200, json={"weird": "payload"})
    )
    result = await AlphaVantageValidator().validate("AVKEY")
    assert result.ok is False


async def test_av_rejects_empty_key() -> None:
    result = await AlphaVantageValidator().validate(" ")
    assert result.ok is False


@respx.mock
async def test_av_rejects_non_json_payload() -> None:
    respx.get(AlphaVantageValidator.URL).mock(
        return_value=httpx.Response(200, text="not-json")
    )
    result = await AlphaVantageValidator().validate("AVKEY")
    assert result.ok is False
    assert "non-json" in result.detail.lower()


@respx.mock
async def test_av_rejects_http_error_status() -> None:
    respx.get(AlphaVantageValidator.URL).mock(return_value=httpx.Response(503, json={}))
    result = await AlphaVantageValidator().validate("AVKEY")
    assert result.ok is False
    assert "http 503" in result.detail.lower()
