"""
Utility functions for LLM providers.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, ValidationError
from models import ModelProvider, OllamaProvider, GeminiProvider
from prompt import MODEL_PROVIDER_MAPPING, GEMINI_API_KEY

logger = logging.getLogger(__name__)


class LLMExtractionError(Exception):
    """Raised when an LLM response cannot be parsed as JSON or fails schema validation."""

    def __init__(self, message: str, raw_response: str):
        super().__init__(message)
        self.raw_response = raw_response


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
_GREEDY_FENCE_RE = re.compile(r"```(?:json)?\s*(.*)\s*```", re.IGNORECASE | re.DOTALL)
_LEADING_FENCE_RE = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)


def _brace_slice(text: str) -> Optional[str]:
    """Return the substring from the first '{' to the last '}', or None."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _parses_as_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (ValueError, TypeError):
        return False


def extract_json_from_response(response_text: str) -> str:
    """
    Extract JSON content from a raw LLM response, stripping <think> blocks
    and markdown code fences (any casing, with or without leading/trailing prose).

    Handles weak-model quirks: multiple fenced blocks (prose reasoning fenced
    separately from the JSON), JSON payloads whose string values contain
    internal ``` sequences, and unclosed fences from truncated output.
    """
    response_text = response_text.strip()

    if "<think>" in response_text:
        think_start = response_text.find("<think>")
        think_end = response_text.find("</think>")
        if think_start != -1 and think_end != -1:
            response_text = response_text[:think_start] + response_text[think_end + 8 :]
        response_text = response_text.strip()

    # Collect fenced-block candidates: every non-greedy (shortest) block, plus
    # a greedy first-fence-to-LAST-fence candidate that survives internal ```
    # sequences inside JSON string values.
    candidates = [m.group(1).strip() for m in _FENCE_RE.finditer(response_text)]
    greedy_match = _GREEDY_FENCE_RE.search(response_text)
    if greedy_match:
        greedy_candidate = greedy_match.group(1).strip()
        if greedy_candidate not in candidates:
            candidates.append(greedy_candidate)

    if candidates:
        # Prefer the first candidate that is itself a JSON object.
        for candidate in candidates:
            if candidate.startswith("{") and _parses_as_json(candidate):
                return candidate
        # Next best: a candidate containing a parseable {...} slice.
        for candidate in candidates:
            sliced = _brace_slice(candidate)
            if sliced is not None and _parses_as_json(sliced):
                return candidate
        # Fences exist but none holds usable JSON — scan the whole original
        # text for a parseable object (the JSON may sit outside the fences).
        whole = _brace_slice(response_text)
        if whole is not None and _parses_as_json(whole):
            return whole
        return candidates[0]

    # No complete fenced block (e.g. a weaker model truncated its output before
    # closing the fence). Fall back to stripping a bare leading fence marker so
    # we still degrade gracefully instead of returning the marker verbatim.
    leading_match = _LEADING_FENCE_RE.match(response_text)
    if leading_match:
        return response_text[leading_match.end() :].strip()

    return response_text


def initialize_llm_provider(model_name: str) -> Any:
    """
    Initialize the appropriate LLM provider based on the model name.

    Args:
        model_name: The name of the model to use

    Returns:
        An initialized LLM provider (either OllamaProvider or GeminiProvider)

    Raises:
        ValueError: if model_name looks like a Gemini model but isn't in
            MODEL_PROVIDER_MAPPING (prevents silently routing a mistyped or
            newly-released Gemini model name to Ollama).
    """
    model_provider = MODEL_PROVIDER_MAPPING.get(model_name)

    if model_provider is None:
        if model_name.startswith("gemini-"):
            raise ValueError(
                f"Unrecognized Gemini model '{model_name}' — add it to "
                "MODEL_PROVIDER_MAPPING and MODEL_PARAMETERS in prompt.py "
                "before using it. Refusing to silently fall back to Ollama."
            )
        model_provider = ModelProvider.OLLAMA

    if model_provider == ModelProvider.GEMINI:
        if not GEMINI_API_KEY:
            logger.warning("⚠️ Gemini API key not found. Falling back to Ollama.")
            return OllamaProvider()
        logger.info(f"🔄 Using Google Gemini API provider with model {model_name}")
        return GeminiProvider(api_key=GEMINI_API_KEY)

    logger.info(f"🔄 Using Ollama provider with model {model_name}")
    return OllamaProvider()


def call_llm_with_retry(
    provider: Any,
    model: str,
    messages: List[Dict[str, str]],
    response_model: Type[BaseModel],
    options: Optional[Dict[str, Any]] = None,
    max_retries: int = 2,
) -> BaseModel:
    """
    Call an LLM provider, parse and validate the JSON response against
    response_model, and re-prompt with the validation error on failure.

    Raises LLMExtractionError after max_retries failed attempts.
    """
    chat_format = (
        response_model.model_json_schema()
        if isinstance(provider, OllamaProvider)
        else response_model
    )

    current_messages = list(messages)
    last_raw = ""
    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        chat_kwargs = {"model": model, "messages": current_messages, "format": chat_format}
        if options is not None:
            chat_kwargs["options"] = options

        raw_text = ""
        try:
            # The provider call itself must sit inside the try: on Gemini a
            # truncated (finish_reason=MAX_TOKENS) or safety-blocked response
            # makes the SDK's response.text accessor raise ValueError, and a
            # malformed provider payload raises KeyError — both must get the
            # same retry-then-LLMExtractionError treatment as bad JSON.
            response = provider.chat(**chat_kwargs)
            raw_text = response["message"]["content"]
            last_raw = raw_text

            cleaned = extract_json_from_response(raw_text)
            json_start = cleaned.find("{")
            json_end = cleaned.rfind("}")
            if json_start != -1 and json_end != -1:
                cleaned = cleaned[json_start : json_end + 1]
            parsed = json.loads(cleaned)
            return response_model(**parsed)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError, KeyError) as e:
            last_error = e
            if attempt < max_retries:
                if raw_text:
                    correction = (
                        f"Your previous response was invalid: {e}. "
                        "Return ONLY the corrected JSON, matching the schema exactly, "
                        "with no extra commentary."
                    )
                else:
                    # Provider-side failure (empty, blocked, or cut-off
                    # response) — there is no raw text to echo back, so use an
                    # empty assistant turn and phrase the correction for it.
                    correction = (
                        "Your previous response was empty or was cut off. "
                        "Return ONLY the complete JSON, matching the schema exactly, "
                        "with no extra commentary."
                    )
                current_messages = current_messages + [
                    {"role": "assistant", "content": raw_text},
                    {"role": "user", "content": correction},
                ]
                continue

    raise LLMExtractionError(
        f"Failed to get valid JSON after {max_retries + 1} attempts: {last_error}",
        raw_response=last_raw,
    ) from last_error
