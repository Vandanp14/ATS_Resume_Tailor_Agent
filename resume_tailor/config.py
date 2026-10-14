"""Model and provider configuration facade."""

from enum import StrEnum

from prompt import (
    DEFAULT_MODEL,
    FALLBACK_MODELS,
    FREELLM_MODEL_PREFIX,
    FREELLMAPI_API_KEY,
    FREELLMAPI_BASE_URL,
    FREELLMAPI_MODEL,
    GEMINI_API_KEY,
    MODEL_PARAMETERS,
    MODEL_PROVIDER_MAPPING,
    OPENROUTER_MODEL_PREFIX,
    PLANNING_MODELS,
)


class ProviderMode(StrEnum):
    """Which providers a run uses, in the order they are tried."""

    GEMINI = "gemini"
    FREELLM = "freellm"
    FREELLM_GEMINI = "freellm_gemini"
    GEMINI_FREELLM = "gemini_freellm"


def resolve_chains(
    mode: ProviderMode | str = ProviderMode.GEMINI,
    freellm_model: str | None = None,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """(model, planning_models, fallback_models) for a provider mode.

    ``gemini`` is the configured .env chain, unchanged. FreeLLMAPI modes use one
    proxy model (default ``auto``, which fails over across upstreams itself).
    """

    mode = ProviderMode(mode)
    free = FREELLM_MODEL_PREFIX + (freellm_model or FREELLMAPI_MODEL)
    if mode is ProviderMode.FREELLM:
        return free, (), ()
    if mode is ProviderMode.FREELLM_GEMINI:
        return free, (free, *PLANNING_MODELS), (DEFAULT_MODEL, *FALLBACK_MODELS)
    if mode is ProviderMode.GEMINI_FREELLM:
        return DEFAULT_MODEL, PLANNING_MODELS, (*FALLBACK_MODELS, free)
    return DEFAULT_MODEL, PLANNING_MODELS, FALLBACK_MODELS


__all__ = [
    "DEFAULT_MODEL",
    "FALLBACK_MODELS",
    "FREELLMAPI_API_KEY",
    "FREELLMAPI_BASE_URL",
    "FREELLMAPI_MODEL",
    "FREELLM_MODEL_PREFIX",
    "GEMINI_API_KEY",
    "MODEL_PARAMETERS",
    "MODEL_PROVIDER_MAPPING",
    "OPENROUTER_MODEL_PREFIX",
    "PLANNING_MODELS",
    "ProviderMode",
    "resolve_chains",
]
