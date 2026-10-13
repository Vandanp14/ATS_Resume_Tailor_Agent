"""OpenRouter adapter, mixed-provider routing, pacing, and fallback ordering."""

import json
from unittest.mock import MagicMock

import httpx
import pytest

import llm_utils
import resume_tailor.pipeline as pipeline_module
import tailor
from llm_utils import (
    ModelRouter,
    OpenRouterError,
    OpenRouterProvider,
    is_model_unavailable,
    is_persistent_unavailability,
)
from models import ModelProvider, RequirementProxyPlan
from resume_tailor.runtime import RatePacer
from tests.test_requirement_coverage import ApiError, _ok_plan_response


def openrouter(handler) -> OpenRouterProvider:
    client = httpx.Client(
        base_url="https://openrouter.test/api/v1",
        transport=httpx.MockTransport(handler),
    )
    return OpenRouterProvider("key", client=client)


def test_openrouter_sends_schema_and_returns_chat_shaped_content():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"proxies": []}'}}],
                "usage": {"prompt_tokens": 42},
            },
        )

    result = openrouter(handler).chat(
        model="openrouter/deepseek/deepseek-v4.1-flash",
        messages=[{"role": "user", "content": "hi"}],
        options={"temperature": 0.0, "max_output_tokens": 100},
        format=RequirementProxyPlan,
    )
    assert result["message"]["content"] == '{"proxies": []}'
    assert result["usage"] == {"input_tokens": 42}
    assert seen["model"] == "deepseek/deepseek-v4.1-flash"
    assert seen["max_tokens"] == 100
    assert seen["response_format"]["type"] == "json_schema"
    assert "proxies" in seen["response_format"]["json_schema"]["schema"]["properties"]
    assert seen["provider"] == {"require_parameters": True}


@pytest.mark.parametrize(
    ("status", "body", "fallback", "persistent"),
    [
        (503, {"error": {"message": "overloaded"}}, True, False),
        (429, {"error": {"message": "rate limited"}}, True, True),
        (402, {"error": {"message": "insufficient credits"}}, True, True),
        (
            404,
            {"error": {"message": "no endpoints support response_format"}},
            True,
            True,
        ),
        (401, {"error": {"message": "bad key"}}, False, False),
    ],
)
def test_openrouter_errors_map_onto_fallback_rules(status, body, fallback, persistent):
    provider = openrouter(lambda request: httpx.Response(status, json=body))
    with pytest.raises(OpenRouterError) as caught:
        provider.chat(
            model="openrouter/x", messages=[], options={"transport_attempts": 1}
        )
    assert caught.value.code == status
    assert is_model_unavailable(caught.value) is fallback
    assert is_persistent_unavailability(caught.value) is persistent


def test_openrouter_error_inside_200_and_empty_content_fall_back():
    provider = openrouter(
        lambda request: httpx.Response(
            200, json={"error": {"code": 503, "message": "upstream down"}}
        )
    )
    with pytest.raises(OpenRouterError) as caught:
        provider.chat(
            model="openrouter/x", messages=[], options={"transport_attempts": 1}
        )
    assert caught.value.code == 503

    empty = openrouter(
        lambda request: httpx.Response(200, json={"choices": [{"message": {}}]})
    )
    with pytest.raises(OpenRouterError) as caught:
        empty.chat(model="openrouter/x", messages=[], options={"transport_attempts": 1})
    assert is_model_unavailable(caught.value)


def test_openrouter_timeout_is_a_fallback_error():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(OpenRouterError) as caught:
        openrouter(handler).chat(
            model="openrouter/x", messages=[], options={"transport_attempts": 1}
        )
    assert caught.value.code == 504


def test_router_sends_each_model_to_its_own_provider(monkeypatch):
    built = {}

    def fake_init(model, **callbacks):
        kind = llm_utils.provider_kind(model)
        built[kind] = MagicMock(name=kind.value)
        built[kind].chat.return_value = {"message": {"content": kind.value}}
        built[kind].callbacks = callbacks
        return built[kind]

    monkeypatch.setattr(llm_utils, "initialize_llm_provider", fake_init)
    router = ModelRouter("openrouter/deepseek/deepseek-v4.1-flash", attempt_callback=1)
    assert set(built) == {ModelProvider.OPENROUTER}
    assert (
        router.chat(model="gemini-3.1-flash-lite", messages=[])["message"]["content"]
        == "gemini"
    )
    assert router.chat(model="openrouter/a", messages=[])["message"]["content"] == (
        "openrouter"
    )
    assert built[ModelProvider.GEMINI].chat.call_count == 1
    assert built[ModelProvider.OPENROUTER].chat.call_count == 1


def test_openrouter_led_chain_falls_back_to_gemini():
    provider = MagicMock()
    provider.supports_model_chain = True
    seen = []

    def chat(model, messages, options=None, **kwargs):
        seen.append(model)
        if model.startswith("openrouter/"):
            raise OpenRouterError(402, "insufficient credits")
        return _ok_plan_response()

    provider.chat.side_effect = chat
    pipeline = tailor.TailorPipeline(
        model="openrouter/deepseek/deepseek-v4.1-flash",
        call_interval=0,
        provider=provider,
        planning_models=[],
        fallback_models=["gemini-3.1-flash-lite"],
    )
    assert pipeline.grounding_model == "gemini-3.1-flash-lite"
    for _ in range(2):
        pipeline._call_once("tailor_skills", RequirementProxyPlan)
    # Out of credits sticks for the run: the second stage goes straight to Gemini.
    assert seen == [
        "openrouter/deepseek/deepseek-v4.1-flash",
        "gemini-3.1-flash-lite",
        "gemini-3.1-flash-lite",
    ]


def test_recently_busy_model_is_tried_again_before_the_stage_sleeps(monkeypatch):
    provider = MagicMock()
    seen = []
    busy = {"gemini-3.1-flash-lite"}

    def chat(model, messages, options=None, **kwargs):
        seen.append(model)
        if model in busy:
            raise ApiError(503, "UNAVAILABLE")
        return _ok_plan_response()

    provider.chat.side_effect = chat
    sleeps = []
    monkeypatch.setattr(pipeline_module.time, "sleep", sleeps.append)
    pipeline = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite",
        call_interval=0,
        provider=provider,
        planning_models=[],
        fallback_models=["gemini-3.5-flash-lite"],
    )
    pipeline._call_once("tailor_skills", RequirementProxyPlan)
    # Next stage: the fallback is now busy and the default model is cooling
    # down; it gets one more try instead of a 30 s sleep.
    busy = {"gemini-3.5-flash-lite"}
    seen.clear()
    pipeline._call_once("tailor_skills", RequirementProxyPlan)
    assert seen == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
    assert sleeps == []


def test_pacing_is_per_model(monkeypatch):
    sleeps = []
    clock = iter([0.0, 0.0, 0.1, 0.1, 0.2, 0.2])
    monkeypatch.setattr("resume_tailor.runtime.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("resume_tailor.runtime.time.sleep", sleeps.append)
    pacer = RatePacer(4.0)
    pacer.wait("gemini-a")
    pacer.wait("gemini-b")
    assert sleeps == []
    pacer.wait("gemini-a")
    assert sleeps == [pytest.approx(3.8)]


def test_stack_research_quota_skips_signal_research(monkeypatch, tmp_path):
    from tests.test_holistic_review import Stub
    from tests.test_tailor import master
    from models import JDProfile

    pipeline = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite",
        call_interval=0,
        provider=MagicMock(),
        research_company=True,
    )
    stub = Stub()

    def thin_jd(template, response_model, **context):
        if response_model is JDProfile:
            return JDProfile(
                role="Engineer",
                company_name="Acme",
                must_have_skills=[],
                nice_to_have_skills=[],
                keywords=[],
            )
        return stub(template, response_model, **context)

    monkeypatch.setattr(pipeline, "_call_once", thin_jd)
    monkeypatch.setattr(pipeline_module, "render", MagicMock())
    grounded = []

    def call_llm(provider, model, messages, response_model, **kwargs):
        grounded.append(response_model.__name__)
        raise ApiError(429, "RESOURCE_EXHAUSTED")

    monkeypatch.setattr(pipeline_module, "call_llm_with_retry", call_llm)
    assert pipeline.run(master(), "Acme hiring", tmp_path, no_pdf=True) == 0
    assert grounded == ["CompanyStackResearch"]
