"""Model configuration for the resume tailoring pipeline."""

import os
from dotenv import load_dotenv
from models import ModelProvider

# Load environment variables
load_dotenv()

# Constants
DEFAULT_MODEL_NAME = "gemma3:4b"
DEFAULT_PROVIDER = ModelProvider.OLLAMA

# Get model and provider from environment or use defaults
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", DEFAULT_MODEL_NAME)
PROVIDER = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER.value)

# Validate provider
if PROVIDER not in [p.value for p in ModelProvider]:
    PROVIDER = DEFAULT_PROVIDER.value

# Model-specific parameters
MODEL_PARAMETERS = {
    # Ollama models
    "qwen3:1.7b": {"temperature": 0.0, "top_p": 0.9},
    "gemma3:1b": {"temperature": 0.0, "top_p": 0.9},
    "qwen3:4b": {"temperature": 0.1, "top_p": 0.4},
    "gemma3:4b": {"temperature": 0.1, "top_p": 0.9},
    "gemma3:12b": {"temperature": 0.1, "top_p": 0.9},
    "mistral:7b": {"temperature": 0.1, "top_p": 0.9},
    # Google Gemini models
    "gemini-2.0-flash": {"temperature": 0.1, "top_p": 0.9},
    "gemini-2.0-flash-lite": {"temperature": 0.1, "top_p": 0.9},
    "gemini-2.5-pro": {"temperature": 0.1, "top_p": 0.9},
    "gemini-2.5-flash": {"temperature": 0.1, "top_p": 0.9},
    "gemini-2.5-flash-lite": {"temperature": 0.1, "top_p": 0.9},
    "gemini-3.5-flash": {"temperature": 0.1, "top_p": 0.9},
    "gemini-3.5-flash-lite": {"temperature": 0.1, "top_p": 0.9},
    "gemini-3.1-flash-lite": {"temperature": 0.1, "top_p": 0.9},
    "gemini-3.1-pro-preview": {"temperature": 0.1, "top_p": 0.9},
    "gemini-3-flash-preview": {"temperature": 0.1, "top_p": 0.9},
    "gemini-3.6-flash": {"temperature": 0.1, "top_p": 0.9},
    "gemini-3.7-flash": {"temperature": 0.1, "top_p": 0.9},
    "gemini-3.8-flash": {"temperature": 0.1, "top_p": 0.9},
    "gemini-flash-latest": {"temperature": 0.1, "top_p": 0.9},
    "gemini-flash-lite-latest": {"temperature": 0.1, "top_p": 0.9},
}

# Model provider mapping
# Maps model names to their provider
MODEL_PROVIDER_MAPPING = {
    # Ollama models
    "qwen3:1.7b": ModelProvider.OLLAMA,
    "gemma3:1b": ModelProvider.OLLAMA,
    "qwen3:4b": ModelProvider.OLLAMA,
    "gemma3:4b": ModelProvider.OLLAMA,
    "gemma3:12b": ModelProvider.OLLAMA,
    "mistral:7b": ModelProvider.OLLAMA,
    # Google Gemini models
    "gemini-2.0-flash": ModelProvider.GEMINI,
    "gemini-2.0-flash-lite": ModelProvider.GEMINI,
    "gemini-2.5-flash": ModelProvider.GEMINI,
    "gemini-2.5-flash-lite": ModelProvider.GEMINI,
    "gemini-2.5-pro": ModelProvider.GEMINI,
    "gemini-3.5-flash": ModelProvider.GEMINI,
    "gemini-3.5-flash-lite": ModelProvider.GEMINI,
    "gemini-3.1-flash-lite": ModelProvider.GEMINI,
    "gemini-3.1-pro-preview": ModelProvider.GEMINI,
    "gemini-3-flash-preview": ModelProvider.GEMINI,
    "gemini-3.6-flash": ModelProvider.GEMINI,
    "gemini-3.7-flash": ModelProvider.GEMINI,
    "gemini-3.8-flash": ModelProvider.GEMINI,
    "gemini-flash-latest": ModelProvider.GEMINI,
    "gemini-flash-lite-latest": ModelProvider.GEMINI,
}


def _model_list(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


# Reasoning-heavy stages (requirement coverage, selection, evidence planning,
# holistic review) try these models first, in order, before DEFAULT_MODEL.
# Set PLANNING_MODELS= (empty) to run every stage on DEFAULT_MODEL.
PLANNING_MODELS = _model_list("PLANNING_MODELS", "gemini-3.8-flash,gemini-3.5-flash")
# Tried after DEFAULT_MODEL when it is overloaded, rate-limited, or retired.
FALLBACK_MODELS = _model_list("FALLBACK_MODELS", "gemini-3.5-flash-lite")

# Per-request Gemini timeout. Planning prompts carry the whole master fact bank
# and thinking models can take well over 30 s on them.
GEMINI_TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS", "120000"))

# Get API keys from environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# OpenRouter (OpenAI-compatible). Any model id prefixed "openrouter/" routes
# here, e.g. DEFAULT_MODEL=openrouter/deepseek/deepseek-v4.1-flash, and can be
# mixed with Gemini models in PLANNING_MODELS / FALLBACK_MODELS.
OPENROUTER_MODEL_PREFIX = "openrouter/"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_TIMEOUT_MS = int(os.getenv("OPENROUTER_TIMEOUT_MS", "120000"))

# FreeLLMAPI (local OpenAI-compatible proxy over many free upstreams, e.g. the
# tashfeenahmed/freellmapi Docker image). Model ids prefixed "freellm/" route
# here; the web UI picks it per run (FreeLLMAPI only, or mixed with Gemini).
FREELLM_MODEL_PREFIX = "freellm/"
FREELLMAPI_API_KEY = os.getenv("FREELLMAPI_API_KEY", "")
FREELLMAPI_BASE_URL = os.getenv("FREELLMAPI_BASE_URL", "http://localhost:3001/v1")
# "auto" can land on an upstream that hangs without erroring; the timeout is
# what moves a mixed chain on to Gemini.
FREELLMAPI_TIMEOUT_MS = int(os.getenv("FREELLMAPI_TIMEOUT_MS", "120000"))
FREELLMAPI_MODEL = os.getenv("FREELLMAPI_MODEL", "auto")
