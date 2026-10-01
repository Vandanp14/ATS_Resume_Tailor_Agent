"""Bounded structured-output calls for Ollama and the supported Google SDK."""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from models import ModelProvider
from prompt import GEMINI_API_KEY, GEMINI_TIMEOUT_MS, MODEL_PROVIDER_MAPPING


class ChatProvider(Protocol):
    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]: ...


class LLMExtractionError(RuntimeError):
    def __init__(self, message: str, raw_response: str = "", attempts: int = 0):
        super().__init__(message)
        self.raw_response = raw_response
        self.attempts = attempts


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
_THINK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def extract_json_from_response(response_text: str) -> str:
    """Extract the first parseable JSON object from common model wrappers."""
    text = _THINK_RE.sub("", response_text).strip()
    candidates = [match.group(1).strip() for match in _FENCE_RE.finditer(text)]
    candidates.append(text)
    for candidate in candidates:
        start, end = candidate.find("{"), candidate.rfind("}")
        payload = (
            candidate[start : end + 1] if start >= 0 and end > start else candidate
        )
        try:
            json.loads(payload)
        except (TypeError, ValueError):
            continue
        return payload
    return text.removeprefix("```json").removeprefix("```").strip()


class OllamaProvider:
    def __init__(self) -> None:
        try:
            import ollama
        except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
            raise RuntimeError(
                "Install the 'ollama' package to use a local model."
            ) from exc
        self.client = ollama

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if kwargs.get("grounding"):
            raise RuntimeError(
                "OllamaProvider does not support Gemini web-search grounding; "
                "the caller must gate grounded calls behind an active Gemini provider."
            )
        params: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "options": {**(options or {}), "num_ctx": 32768},
        }
        if kwargs.get("format") is not None:
            schema = kwargs["format"]
            params["format"] = (
                schema.model_json_schema() if isinstance(schema, type) else schema
            )
        return self.client.chat(**params)


class GeminiProvider:
    """Adapter over ``google-genai`` with a stable chat-shaped interface."""

    def __init__(
        self,
        api_key: str,
        timeout_ms: int = 30_000,
        progress_callback: Callable[[str], None] | None = None,
        attempt_callback: Callable[[], str | None] | None = None,
        usage_callback: Callable[[str | None, int | None], None] | None = None,
    ) -> None:
        from google import genai
        from google.genai import types

        self._types = types
        self._progress_callback = progress_callback
        self._attempt_callback = attempt_callback
        self._usage_callback = usage_callback
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=timeout_ms,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        code = getattr(exc, "code", None)
        status = getattr(exc, "status_code", None)
        message = str(exc).lower()
        return (
            code in {429, 500, 503, 504}
            or status in {429, 500, 503, 504}
            or any(
                token in message
                for token in (
                    "resource_exhausted",
                    "service unavailable",
                    "deadline exceeded",
                )
            )
        )

    @staticmethod
    def _retry_after(exc: Exception) -> float | None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", {})
        raw = headers.get("retry-after") if headers else None
        try:
            return max(float(raw), 0.0) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        types = self._types
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        contents = [
            types.Content(
                role="model" if message["role"] == "assistant" else "user",
                parts=[types.Part.from_text(text=message["content"])],
            )
            for message in messages
            if message["role"] != "system"
        ]
        grounding = bool(kwargs.get("grounding"))
        schema = kwargs.get("format")
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            schema = schema.model_json_schema()
        config = types.GenerateContentConfig(
            system_instruction="\n\n".join(system_parts) or None,
            temperature=(options or {}).get("temperature"),
            top_p=(options or {}).get("top_p"),
            max_output_tokens=(options or {}).get("max_output_tokens", 8192),
            # Gemini's search-grounding tool and forced-JSON schema decoding are
            # mutually exclusive; grounded calls rely on prompt-level JSON
            # instructions plus extract_json_from_response() instead.
            response_mime_type=(
                None if grounding else ("application/json" if schema is not None else None)
            ),
            response_json_schema=None if grounding else schema,
            tools=[types.Tool(google_search=types.GoogleSearch())] if grounding else None,
        )
        for attempt in range(3):
            try:
                attempt_id = self._attempt_callback() if self._attempt_callback else None
                response = self.client.models.generate_content(
                    model=model, contents=contents, config=config
                )
                usage = getattr(response, "usage_metadata", None)
                input_tokens = getattr(usage, "prompt_token_count", None)
                if self._usage_callback:
                    self._usage_callback(attempt_id, input_tokens)
                if not response.text:
                    raise ValueError("Gemini returned no text content")
                return {"message": {"role": "assistant", "content": response.text}}
            except Exception as exc:
                if attempt == 2 or not self._retryable(exc):
                    raise
                retry_after = self._retry_after(exc)
                delay = (
                    retry_after
                    if retry_after is not None
                    else random.uniform(0, min(20.0, 0.2 * (2**attempt)))
                )
                if self._progress_callback:
                    self._progress_callback(
                        f"Gemini transport retry {attempt + 2}/3 after {delay:.1f}s: {exc}"
                    )
                time.sleep(delay)
        raise AssertionError("unreachable")


_UNAVAILABLE_CODES = {400, 404, 429, 500, 502, 503, 504}
_UNAVAILABLE_TOKENS = (
    "resource_exhausted",
    "unavailable",
    "high demand",
    "overloaded",
    "deadline exceeded",
    "timed out",
    "timeout",
    "not_found",
    "no longer available",
)
_PERSISTENT_CODES = {404, 429}


def is_model_unavailable(exc: BaseException) -> bool:
    """True for API failures another model may not share.

    Covers overload (503), per-model quota (429), server errors, retired
    models (404), and model-specific request rejections (400, e.g. a schema
    feature one model lacks). Auth errors (401/403) are excluded: those fail
    identically on every model and must stop the run at once.
    """

    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code in _UNAVAILABLE_CODES
    if isinstance(exc, (LLMExtractionError, json.JSONDecodeError, KeyError, TypeError)):
        return False
    message = str(exc).lower()
    return any(token in message for token in _UNAVAILABLE_TOKENS)


def is_persistent_unavailability(exc: BaseException) -> bool:
    """Retired model (404) or exhausted quota (429): it will not recover this run."""

    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    message = str(exc).lower()
    return code in _PERSISTENT_CODES or "resource_exhausted" in message


def describe_api_error(exc: BaseException) -> str:
    """Short, user-facing summary of what the provider API returned."""

    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    status = getattr(exc, "status", None)
    message = getattr(exc, "message", None) or str(exc)
    message = " ".join(str(message).split())[:220]
    prefix = " ".join(str(part) for part in (code, status) if part)
    return f"{prefix}: {message}" if prefix else message


def initialize_llm_provider(
    model_name: str,
    progress_callback: Callable[[str], None] | None = None,
    attempt_callback: Callable[[], str | None] | None = None,
    usage_callback: Callable[[str | None, int | None], None] | None = None,
) -> ChatProvider:
    provider = MODEL_PROVIDER_MAPPING.get(model_name)
    if provider is None:
        if model_name.startswith("gemini-"):
            raise ValueError(
                f"Unrecognized Gemini model '{model_name}'; refusing fallback."
            )
        provider = ModelProvider.OLLAMA
    if provider == ModelProvider.GEMINI:
        if not GEMINI_API_KEY:
            raise RuntimeError("Gemini selected but GEMINI_API_KEY is not configured.")
        return GeminiProvider(
            GEMINI_API_KEY,
            timeout_ms=GEMINI_TIMEOUT_MS,
            progress_callback=progress_callback,
            attempt_callback=attempt_callback,
            usage_callback=usage_callback,
        )
    return OllamaProvider()


def _is_ollama(provider: Any) -> bool:
    seen: set[int] = set()
    current = provider
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OllamaProvider):
            return True
        current = vars(current).get("_provider")
    return False


def call_llm_with_retry(
    provider: ChatProvider,
    model: str,
    messages: list[dict[str, str]],
    response_model: type[BaseModel],
    options: dict[str, Any] | None = None,
    max_retries: int = 1,
    grounding: bool = False,
) -> BaseModel:
    """Make one structured call and at most one schema-correction call."""
    current_messages = list(messages)
    last_raw = ""
    last_error: Exception = ValueError("no response")
    for attempt in range(max_retries + 1):
        try:
            response = provider.chat(
                model=model,
                messages=current_messages,
                options=options,
                format=(
                    response_model.model_json_schema()
                    if _is_ollama(provider)
                    else response_model
                ),
                grounding=grounding,
            )
            last_raw = response["message"]["content"]
            payload = json.loads(extract_json_from_response(last_raw))
            return response_model.model_validate(payload)
        except (
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            ValidationError,
        ) as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            current_messages = list(messages) + [
                {
                    "role": "user",
                    "content": (
                        "The prior response did not match the required schema: "
                        f"{exc}. Return one complete JSON object matching the schema; "
                        "include every requested item and no commentary."
                    ),
                }
            ]
    raise LLMExtractionError(
        f"Structured response failed after {max_retries + 1} attempts: {last_error}",
        raw_response=last_raw,
        attempts=max_retries + 1,
    )
