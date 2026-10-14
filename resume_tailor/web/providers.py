"""Provider availability for the run form: Gemini chain + live FreeLLMAPI catalog."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from ..config import (
    DEFAULT_MODEL,
    FALLBACK_MODELS,
    FREELLMAPI_API_KEY,
    FREELLMAPI_BASE_URL,
    FREELLMAPI_MODEL,
    GEMINI_API_KEY,
    PLANNING_MODELS,
)

CATALOG_TTL_SECONDS = 60.0
CATALOG_TIMEOUT_SECONDS = 2.0


class GeminiStatus(BaseModel):
    configured: bool
    default_model: str
    planning_models: list[str] = Field(default_factory=list)
    fallback_models: list[str] = Field(default_factory=list)


class FreeLLMModel(BaseModel):
    id: str
    name: str | None = None
    context_window: int | None = None


class FreeLLMStatus(BaseModel):
    configured: bool
    reachable: bool
    default_model: str
    models: list[FreeLLMModel] = Field(default_factory=list)
    error: str | None = None


class ProvidersResponse(BaseModel):
    gemini: GeminiStatus
    freellm: FreeLLMStatus


def _fetch_catalog(api_key: str, base_url: str) -> list[dict[str, Any]]:
    import httpx

    response = httpx.get(
        base_url.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=CATALOG_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json().get("data")
    if not isinstance(data, list):
        raise ValueError("unexpected /models response")
    return data


class ProviderCatalog:
    """Caches the FreeLLMAPI model list; the key never leaves the server."""

    def __init__(
        self,
        api_key: str = FREELLMAPI_API_KEY,
        base_url: str = FREELLMAPI_BASE_URL,
        fetch: Callable[[str, str], list[dict[str, Any]]] = _fetch_catalog,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: tuple[float, FreeLLMStatus] | None = None

    def _freellm(self) -> FreeLLMStatus:
        if not self._api_key:
            return FreeLLMStatus(
                configured=False,
                reachable=False,
                default_model=FREELLMAPI_MODEL,
                error="FREELLMAPI_API_KEY is not set in .env.",
            )
        try:
            raw = self._fetch(self._api_key, self._base_url)
        except Exception as exc:  # noqa: BLE001 - any failure means "offline"
            return FreeLLMStatus(
                configured=True,
                reachable=False,
                default_model=FREELLMAPI_MODEL,
                error=" ".join(str(exc).split())[:200] or type(exc).__name__,
            )
        models = [
            FreeLLMModel(
                id=str(item["id"]),
                name=item.get("name") if isinstance(item.get("name"), str) else None,
                context_window=item.get("context_window")
                if isinstance(item.get("context_window"), int)
                else None,
            )
            for item in raw
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item.get("available", True) is not False
        ]
        return FreeLLMStatus(
            configured=True,
            reachable=True,
            default_model=FREELLMAPI_MODEL,
            models=models,
        )

    def snapshot(self) -> ProvidersResponse:
        with self._lock:
            now = self._clock()
            if self._cached is None or now - self._cached[0] >= CATALOG_TTL_SECONDS:
                self._cached = (now, self._freellm())
            freellm = self._cached[1]
        return ProvidersResponse(
            gemini=GeminiStatus(
                configured=bool(GEMINI_API_KEY),
                default_model=DEFAULT_MODEL,
                planning_models=list(PLANNING_MODELS),
                fallback_models=list(FALLBACK_MODELS),
            ),
            freellm=freellm,
        )
