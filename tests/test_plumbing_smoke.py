"""Provider and structured-output plumbing tests."""

import importlib.util
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

import llm_utils
from llm_utils import (
    LLMExtractionError,
    call_llm_with_retry,
    extract_json_from_response,
)


class Result(BaseModel):
    value: int


def test_json_extraction_handles_fences_and_think_blocks():
    raw = '<think>ignore</think>```json\n{"value": 3}\n```'
    assert extract_json_from_response(raw) == '{"value": 3}'


def test_structured_call_allows_one_correction():
    provider = MagicMock()
    provider.chat.side_effect = [
        {"message": {"content": "bad"}},
        {"message": {"content": '{"value": 7}'}},
    ]
    assert (
        call_llm_with_retry(
            provider, "m", [{"role": "user", "content": "x"}], Result
        ).value
        == 7
    )
    assert provider.chat.call_count == 2


def test_structured_call_is_bounded():
    provider = MagicMock()
    provider.chat.return_value = {"message": {"content": "bad"}}
    with pytest.raises(LLMExtractionError) as caught:
        call_llm_with_retry(provider, "m", [], Result)
    assert caught.value.attempts == 2
    assert provider.chat.call_count == 2


def test_unmapped_gemini_never_falls_back():
    with pytest.raises(ValueError, match="refusing fallback"):
        llm_utils.initialize_llm_provider("gemini-does-not-exist")


def test_missing_gemini_key_never_falls_back(monkeypatch):
    monkeypatch.setattr(llm_utils, "GEMINI_API_KEY", "")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        llm_utils.initialize_llm_provider("gemini-3.1-flash-lite")


def test_supported_sdk_is_installed_and_deprecated_sdk_is_not_imported():
    assert importlib.util.find_spec("google.genai") is not None
    assert "google.generativeai" not in __import__("sys").modules


def test_gemini_provider_uses_typed_client_without_exposing_key(monkeypatch):
    from google import genai

    client = MagicMock()
    monkeypatch.setattr(genai, "Client", MagicMock(return_value=client))
    provider = llm_utils.GeminiProvider("secret-value")
    assert provider.client is client
    assert "secret-value" not in repr(provider.__dict__)
    http_options = genai.Client.call_args.kwargs["http_options"]
    assert http_options.timeout == 30_000
    assert http_options.retry_options.attempts == 1


def test_gemini_provider_reports_every_attempt_and_response_usage(monkeypatch):
    from google import genai

    response = MagicMock()
    response.text = '{"value": 1}'
    response.usage_metadata.prompt_token_count = 4321
    client = MagicMock()
    client.models.generate_content.return_value = response
    monkeypatch.setattr(genai, "Client", MagicMock(return_value=client))
    attempts = []
    usage = []
    provider = llm_utils.GeminiProvider(
        "secret-value",
        attempt_callback=lambda: attempts.append("attempt-1") or "attempt-1",
        usage_callback=lambda attempt_id, tokens: usage.append((attempt_id, tokens)),
    )

    result = provider.chat("gemini-3.1-flash-lite", [{"role": "user", "content": "x"}])

    assert result["message"]["content"] == '{"value": 1}'
    assert attempts == ["attempt-1"]
    assert usage == [("attempt-1", 4321)]
