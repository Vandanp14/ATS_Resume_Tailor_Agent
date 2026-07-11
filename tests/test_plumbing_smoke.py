"""Smoke tests for the copied LLM plumbing.

Covers `call_llm_with_retry` (success / retry-and-recover / exhaustion),
the JSON-extraction helper, provider selection guardrails, and the Gemini
schema converter — the last exercised against this project's OWN new response
models (nested Optional[List[SubModel]] via ScoredWork -> ScoredBullet), which
is the exact shape google-generativeai's built-in converter mishandles.
"""

import json

import pytest
from unittest.mock import MagicMock
from pydantic import BaseModel

from models import (
    OllamaProvider,
    JDProfile,
    TailoredWork,
    TailoredSkills,
    TailoredProjects,
    MatchReport,
    _pydantic_to_gemini_schema,
)
from llm_utils import (
    extract_json_from_response,
    LLMExtractionError,
    call_llm_with_retry,
    initialize_llm_provider,
)


# --- JSON extraction helper -------------------------------------------------


def test_extract_json_strips_lowercase_fence():
    assert extract_json_from_response('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_json_strips_think_block():
    assert extract_json_from_response('<think>reasoning</think>{"a": 1}') == '{"a": 1}'


def test_extract_json_picks_json_block_when_first_fenced_block_is_prose():
    text = '```\nlet me think\n```\n```json\n{"score": 5}\n```'
    assert json.loads(extract_json_from_response(text)) == {"score": 5}


# --- call_llm_with_retry ----------------------------------------------------


class _Dummy(BaseModel):
    value: int


def _mock_provider(*responses):
    provider = MagicMock(spec=OllamaProvider)
    provider.chat.side_effect = [
        {"message": {"role": "assistant", "content": r}} for r in responses
    ]
    return provider


def test_call_llm_with_retry_succeeds_first_try():
    provider = _mock_provider('{"value": 5}')
    result = call_llm_with_retry(
        provider, "gemma3:4b", [{"role": "user", "content": "x"}], _Dummy
    )
    assert result.value == 5
    assert provider.chat.call_count == 1


def test_call_llm_with_retry_recovers_after_invalid_json():
    provider = _mock_provider("not json at all", '{"value": 7}')
    result = call_llm_with_retry(
        provider, "gemma3:4b", [{"role": "user", "content": "x"}], _Dummy
    )
    assert result.value == 7
    assert provider.chat.call_count == 2
    # The retry must append the bad assistant turn + a correction user turn.
    second_call_messages = provider.chat.call_args_list[1].kwargs["messages"]
    assert len(second_call_messages) == 3
    assert "invalid" in second_call_messages[-1]["content"].lower()


def test_call_llm_with_retry_recovers_after_failed_validation():
    provider = _mock_provider('{"value": "not-an-int"}', '{"value": 9}')
    result = call_llm_with_retry(
        provider, "gemma3:4b", [{"role": "user", "content": "x"}], _Dummy
    )
    assert result.value == 9


def test_call_llm_with_retry_raises_after_exhausting_retries():
    provider = _mock_provider("bad", "still bad", "still bad again")
    with pytest.raises(LLMExtractionError) as exc_info:
        call_llm_with_retry(
            provider,
            "gemma3:4b",
            [{"role": "user", "content": "x"}],
            _Dummy,
            max_retries=2,
        )
    assert provider.chat.call_count == 3  # 1 initial + 2 retries
    assert exc_info.value.raw_response == "still bad again"


def test_call_llm_with_retry_retries_after_provider_value_error():
    # On Gemini, a blocked/truncated response makes response.text raise
    # ValueError from inside provider.chat — that must hit the same retry path.
    provider = MagicMock(spec=OllamaProvider)
    provider.chat.side_effect = [
        ValueError("response.text requires a valid Part (blocked or truncated)"),
        {"message": {"role": "assistant", "content": '{"value": 11}'}},
    ]
    result = call_llm_with_retry(
        provider, "gemma3:4b", [{"role": "user", "content": "x"}], _Dummy
    )
    assert result.value == 11
    assert provider.chat.call_count == 2
    correction = provider.chat.call_args_list[1].kwargs["messages"][-1]["content"]
    assert "empty or was cut off" in correction


def test_call_llm_with_retry_builds_ollama_format_as_json_schema():
    provider = _mock_provider('{"value": 1}')
    call_llm_with_retry(
        provider, "gemma3:4b", [{"role": "user", "content": "x"}], _Dummy
    )
    assert (
        provider.chat.call_args_list[0].kwargs["format"] == _Dummy.model_json_schema()
    )


# --- provider selection guardrails -----------------------------------------


def test_initialize_llm_provider_rejects_unmapped_gemini_model():
    with pytest.raises(ValueError, match="gemini-9-nonexistent"):
        initialize_llm_provider("gemini-9-nonexistent")


def test_initialize_llm_provider_defaults_unknown_ollama_style_names():
    assert isinstance(
        initialize_llm_provider("some-custom-local-model:latest"), OllamaProvider
    )


# --- Gemini schema converter against this project's new models --------------


NEW_RESPONSE_MODELS = [
    JDProfile,
    TailoredWork,
    TailoredSkills,
    TailoredProjects,
    MatchReport,
]


@pytest.mark.parametrize("model", NEW_RESPONSE_MODELS)
def test_new_models_convert_to_valid_proto_schema(model):
    from google.generativeai import protos

    schema = _pydantic_to_gemini_schema(model)
    # Must not raise: this is the exact failure the SDK's own converter hits.
    assert protos.Schema(schema) is not None
    dumped = json.dumps(schema)
    assert "$ref" not in dumped
    assert "$defs" not in dumped


def test_scored_work_schema_preserves_nested_bullet_fields():
    # ScoredWork.highlights is Optional[List[ScoredBullet]] — the nested
    # sub-model $ref must resolve and its field names must survive.
    schema = _pydantic_to_gemini_schema(TailoredWork)
    work_items = schema["properties"]["work"]["items"]
    assert "relevance" in work_items["properties"]
    assert "position" in work_items["properties"]  # inherited from Work
    bullet_items = work_items["properties"]["highlights"]["items"]
    assert "text" in bullet_items["properties"]
    assert "relevance" in bullet_items["properties"]


def test_jdprofile_schema_marks_required_lists():
    schema = _pydantic_to_gemini_schema(JDProfile)
    assert "role" in schema["required"]
    assert "must_have_skills" in schema["required"]
    # Optional scalars are nullable, never required.
    assert "seniority" not in schema.get("required", [])
    assert schema["properties"]["seniority"]["nullable"] is True
