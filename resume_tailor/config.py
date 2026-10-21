"""Model and provider configuration facade."""

from dataclasses import dataclass
from enum import StrEnum

from prompt import (
    DEFAULT_MODEL,
    FALLBACK_MODELS,
    FIX_MODELS,
    FREELLM_MODEL_PREFIX,
    FREELLMAPI_API_KEY,
    FREELLMAPI_BASE_URL,
    FREELLMAPI_MODEL,
    GEMINI_API_KEY,
    MODEL_PARAMETERS,
    MODEL_PROVIDER_MAPPING,
    OPENROUTER_MODEL_PREFIX,
    PLANNING_MODELS,
    WRITING_MODELS,
    model_rpm,
)


class ProviderMode(StrEnum):
    """Which providers a run uses, in the order they are tried."""

    GEMINI = "gemini"
    FREELLM = "freellm"
    FREELLM_GEMINI = "freellm_gemini"
    GEMINI_FREELLM = "gemini_freellm"


@dataclass(frozen=True)
class ModelChains:
    """Lead model plus the model chain for each kind of stage."""

    model: str
    planning: tuple[str, ...]
    writing: tuple[str, ...]
    fixes: tuple[str, ...]
    fallback: tuple[str, ...]

    def pipeline_kwargs(self) -> dict[str, object]:
        return {
            "model": self.model,
            "planning_models": self.planning,
            "writing_models": self.writing,
            "fix_models": self.fixes,
            "fallback_models": self.fallback,
        }


def resolve_chains(
    mode: ProviderMode | str = ProviderMode.GEMINI,
    freellm_model: str | None = None,
) -> ModelChains:
    """Model chains for a provider mode.

    ``gemini`` is the configured .env chains, unchanged. FreeLLMAPI modes use one
    proxy model (default ``auto``, which fails over across upstreams itself).
    Every pipeline chain ends with the lead model and the fallback list, so a
    proxy appended to ``fallback`` already trails every chain.
    """

    mode = ProviderMode(mode)
    free = FREELLM_MODEL_PREFIX + (freellm_model or FREELLMAPI_MODEL)
    if mode is ProviderMode.FREELLM:
        return ModelChains(free, (), (), (), ())
    if mode is ProviderMode.FREELLM_GEMINI:
        return ModelChains(
            free,
            (free, *PLANNING_MODELS),
            (free, *WRITING_MODELS),
            (free, *FIX_MODELS),
            (DEFAULT_MODEL, *FALLBACK_MODELS),
        )
    if mode is ProviderMode.GEMINI_FREELLM:
        return ModelChains(
            DEFAULT_MODEL,
            PLANNING_MODELS,
            WRITING_MODELS,
            FIX_MODELS,
            (*FALLBACK_MODELS, free),
        )
    return ModelChains(
        DEFAULT_MODEL, PLANNING_MODELS, WRITING_MODELS, FIX_MODELS, FALLBACK_MODELS
    )


__all__ = [
    "DEFAULT_MODEL",
    "FALLBACK_MODELS",
    "FIX_MODELS",
    "FREELLMAPI_API_KEY",
    "FREELLMAPI_BASE_URL",
    "FREELLMAPI_MODEL",
    "FREELLM_MODEL_PREFIX",
    "GEMINI_API_KEY",
    "MODEL_PARAMETERS",
    "MODEL_PROVIDER_MAPPING",
    "ModelChains",
    "OPENROUTER_MODEL_PREFIX",
    "PLANNING_MODELS",
    "ProviderMode",
    "WRITING_MODELS",
    "model_rpm",
    "resolve_chains",
]
