"""OpenRouter-backed LLM router (PRD §7).

Two routes — and only two — exposed to the rest of the app:

- ``summarize`` → lightweight model (Gemini 3.1 Flash) for browsing / news /
  message drafting (PRD §7.3).
- ``decide``   → heavy reasoning model (Claude Opus 4.7 Thinking) for the
  final trade decision (PRD §7.2, §7.4).

The §7.4 separation rule is enforced at call-time: ``decide`` cannot be invoked
against the lightweight model. Misconfigured deployments raise ``ValueError``
on the first call.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.llm.telemetry import CallTelemetry, TelemetrySink, parse_usage
from app.llm.types import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMUnavailableError,
    LLMValidationError,
)

DEFAULT_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
CHAT_COMPLETIONS_PATH = "/chat/completions"

T = TypeVar("T", bound=BaseModel)


class _RetryableHTTPError(RuntimeError):
    """Internal marker so tenacity retries 5xx/429 without leaking httpx types."""


class LLMRouter:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = 3,
        telemetry_sink: TelemetrySink | None = None,
        app_referer: str = "https://github.com/neuronomid/earning-edge",
        app_title: str = "Earning Edge",
        logger: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self.max_attempts = max_attempts
        self._telemetry_sink = telemetry_sink
        self._app_referer = app_referer
        self._app_title = app_title
        self.logger = logger or get_logger(__name__)

    # ---------- public surface ----------

    @property
    def heavy_model(self) -> str:
        return self.settings.market_analysis_model

    @property
    def light_model(self) -> str:
        return self.settings.lightweight_model

    async def summarize(
        self,
        *,
        api_key: str,
        system: str,
        user: str,
        max_tokens: int = 1024,
        temperature: float = 0.3,
    ) -> str:
        """Run the lightweight model. Returns plain text (PRD §7.3)."""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        payload = await self._call_completion(
            api_key=api_key,
            model=self.light_model,
            messages=messages,
            role="summarize",
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=None,
        )
        return _extract_text(payload)

    async def decide(
        self,
        *,
        api_key: str,
        structured_input: BaseModel,
        response_schema: type[T],
        system_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ) -> T:
        """Run the heavy model and parse the response into ``response_schema``.

        Enforces PRD §7.4: never runs against the lightweight model.
        """
        self._assert_decide_route(self.heavy_model)

        schema_json = json.dumps(response_schema.model_json_schema(), separators=(",", ":"))
        input_json = structured_input.model_dump_json()
        user_msg = (
            "STRUCTURED_INPUT (JSON):\n"
            f"{input_json}\n\n"
            "RESPONSE SCHEMA (must match exactly, JSON only, no prose):\n"
            f"{schema_json}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

        payload = await self._call_completion(
            api_key=api_key,
            model=self.heavy_model,
            messages=messages,
            role="decide",
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
            reasoning=self._heavy_reasoning_param(),
        )
        text = _extract_text(payload)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMValidationError(
                f"Heavy model returned non-JSON: {exc}",
                raw_response=text,
            ) from exc
        try:
            return response_schema.model_validate(parsed)
        except ValidationError as exc:
            raise LLMValidationError(
                f"Heavy model output failed schema validation: {exc}",
                raw_response=text,
            ) from exc

    # ---------- internals ----------

    def _assert_decide_route(self, model: str) -> None:
        if model == self.light_model:
            raise ValueError(
                "decide() cannot run against the lightweight model "
                f"(PRD §7.4). model={model!r} matches LIGHTWEIGHT_MODEL."
            )

    def _heavy_reasoning_param(self) -> dict[str, Any] | None:
        # PRD §7.2: heavy reasoning runs Claude Opus 4.7 in thinking mode.
        # OpenRouter does not accept a "-thinking" model suffix; thinking is
        # opted into via the unified `reasoning` parameter.
        effort = getattr(self.settings, "market_analysis_reasoning_effort", "medium")
        if effort == "off":
            return None
        return {"effort": effort, "exclude": True}

    async def _call_completion(
        self,
        *,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        role: str,
        max_tokens: int,
        temperature: float,
        response_format: dict[str, Any] | None,
        reasoning: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not api_key or not api_key.strip():
            raise LLMAuthenticationError("OpenRouter API key is empty.")

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "usage": {"include": True},
        }
        if response_format is not None:
            body["response_format"] = response_format
        if reasoning is not None:
            body["reasoning"] = reasoning

        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
            "HTTP-Referer": self._app_referer,
            "X-Title": self._app_title,
        }

        url = OPENROUTER_BASE_URL + CHAT_COMPLETIONS_PATH
        started = time.monotonic()

        if self._client is not None:
            payload = await self._post_with_retry(self._client, url, body, headers)
        else:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                payload = await self._post_with_retry(client, url, body, headers)

        duration_ms = int((time.monotonic() - started) * 1000)
        self._record_telemetry(role, model, payload, duration_ms)
        return payload

    async def _post_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        body: dict[str, Any],
        headers: Mapping[str, str],
    ) -> dict[str, Any]:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.max_attempts),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=4.0),
                retry=retry_if_exception_type((_RetryableHTTPError, httpx.HTTPError)),
                reraise=True,
            ):
                with attempt:
                    response = await client.post(url, json=body, headers=headers)
                    self._raise_for_status(response)
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise LLMError(f"OpenRouter returned non-JSON body: {exc}") from exc
        except _RetryableHTTPError as exc:
            raise LLMUnavailableError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(f"OpenRouter network error: {exc}") from exc
        # Unreachable: AsyncRetrying always returns or raises.
        raise LLMUnavailableError("OpenRouter exhausted retries with no response.")

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status == 200:
            return
        if status in (401, 403):
            raise LLMAuthenticationError(
                f"OpenRouter rejected the API key (HTTP {status}). "
                "Update the OpenRouter key in Telegram settings."
            )
        if status == 429:
            # Surface as retryable so AsyncRetrying gets a chance, then bubble as
            # rate-limit if the final attempt also fails.
            if response.headers.get("x-ratelimit-final") == "true":
                raise LLMRateLimitError("OpenRouter rate-limited the request.")
            raise _RetryableHTTPError(f"HTTP 429 from OpenRouter: {response.text[:200]}")
        if 500 <= status < 600:
            raise _RetryableHTTPError(f"HTTP {status} from OpenRouter: {response.text[:200]}")
        # 4xx other than auth/rate-limit — surface as a hard error.
        raise LLMError(f"OpenRouter returned HTTP {status}: {response.text[:200]}")

    def _record_telemetry(
        self,
        role: str,
        model: str,
        payload: dict[str, Any],
        duration_ms: int,
    ) -> None:
        prompt, completion, total, cost = parse_usage(payload)
        telem = CallTelemetry(
            role=role,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            estimated_cost_usd=cost,
            duration_ms=duration_ms,
        )
        self.logger.info(
            "llm_call",
            role=role,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            cost_usd=str(cost) if cost is not None else None,
            duration_ms=duration_ms,
        )
        if self._telemetry_sink is not None:
            self._telemetry_sink(telem)


def _extract_text(payload: Mapping[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not isinstance(choices, list) or not choices:
        raise LLMError("OpenRouter response missing 'choices'.")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise LLMError("OpenRouter response 'choices[0]' malformed.")
    message = first.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    # Some providers return a list of segments; concatenate text parts.
    if isinstance(content, list):
        out: list[str] = []
        for part in content:
            if isinstance(part, Mapping) and isinstance(part.get("text"), str):
                out.append(part["text"])
        if out:
            return "".join(out)
    raise LLMError("OpenRouter response 'message.content' missing or unsupported shape.")
