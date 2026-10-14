"""FreeLLMAPI provider, provider-mode chains, and the per-run web picker."""

import json
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

import resume_tailor.web.app as web_app
import tailor
from llm_utils import (
    ChatAPIError,
    FreeLLMProvider,
    is_model_unavailable,
    is_persistent_unavailability,
    provider_kind,
)
from models import ModelProvider, RequirementProxyPlan
from resume_tailor.config import (
    DEFAULT_MODEL,
    FALLBACK_MODELS,
    PLANNING_MODELS,
    ProviderMode,
    resolve_chains,
)
from resume_tailor.web.providers import ProviderCatalog
from tests.conftest import create_job, fake_factory, wait_for
from tests.test_requirement_coverage import _ok_plan_response


def freellm(handler) -> FreeLLMProvider:
    client = httpx.Client(
        base_url="http://proxy.test/v1", transport=httpx.MockTransport(handler)
    )
    return FreeLLMProvider("key", client=client)


# -- provider -----------------------------------------------------------------


def test_freellm_prefix_routes_to_its_own_provider():
    assert provider_kind("freellm/auto") is ModelProvider.FREELLM


def test_freellm_sends_schema_in_prompt_and_response_format():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"proxies": []}'}}],
                "usage": {"prompt_tokens": 7},
            },
        )

    messages = [{"role": "user", "content": "hi"}]
    result = freellm(handler).chat(
        model="freellm/auto", messages=messages, format=RequirementProxyPlan
    )
    assert result["message"]["content"] == '{"proxies": []}'
    assert result["usage"] == {"input_tokens": 7}
    assert seen["model"] == "auto"
    assert "provider" not in seen
    assert seen["response_format"]["type"] == "json_schema"
    assert seen["messages"][0] == {"role": "user", "content": "hi"}
    assert seen["messages"][-1]["role"] == "system"
    assert '"proxies"' in seen["messages"][-1]["content"]
    assert messages == [{"role": "user", "content": "hi"}]  # caller list untouched


def test_freellm_offline_container_is_a_fallback_error():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ChatAPIError) as caught:
        freellm(handler).chat(
            model="freellm/auto", messages=[], options={"transport_attempts": 1}
        )
    assert caught.value.code == 503
    assert is_model_unavailable(caught.value)


def test_freellm_bad_key_skips_the_proxy_instead_of_stopping_the_run():
    provider = freellm(
        lambda request: httpx.Response(401, json={"error": {"message": "bad key"}})
    )
    with pytest.raises(ChatAPIError) as caught:
        provider.chat(model="freellm/auto", messages=[], options={"transport_attempts": 1})
    assert is_model_unavailable(caught.value)
    assert is_persistent_unavailability(caught.value)
    # A Gemini/OpenRouter auth error still stops the run.
    assert not is_model_unavailable(ChatAPIError(401, "bad key"))


def test_freellm_led_chain_falls_back_to_gemini_when_proxy_is_down():
    provider = MagicMock()
    provider.supports_model_chain = True
    seen = []

    def chat(model, messages, options=None, **kwargs):
        seen.append(model)
        if model.startswith("freellm/"):
            raise ChatAPIError(503, "connection failed", provider_scoped=False)
        return _ok_plan_response()

    provider.chat.side_effect = chat
    model, planning, fallback = resolve_chains("freellm_gemini", "auto")
    pipeline = tailor.TailorPipeline(
        model=model,
        call_interval=0,
        provider=provider,
        planning_models=planning,
        fallback_models=fallback,
    )
    pipeline._call_once("tailor_skills", RequirementProxyPlan)
    assert seen[0] == "freellm/auto"
    assert seen[1] == DEFAULT_MODEL
    assert pipeline.grounding_model is not None


# -- chain resolution ---------------------------------------------------------


def test_resolve_chains_per_mode():
    assert resolve_chains("gemini") == (DEFAULT_MODEL, PLANNING_MODELS, FALLBACK_MODELS)
    assert resolve_chains(ProviderMode.FREELLM, "llama-4-scout") == (
        "freellm/llama-4-scout",
        (),
        (),
    )
    model, planning, fallback = resolve_chains("freellm_gemini", "auto")
    assert model == "freellm/auto"
    assert planning == ("freellm/auto", *PLANNING_MODELS)
    assert fallback == (DEFAULT_MODEL, *FALLBACK_MODELS)
    model, planning, fallback = resolve_chains("gemini_freellm", "auto")
    assert model == DEFAULT_MODEL
    assert planning == PLANNING_MODELS
    assert fallback == (*FALLBACK_MODELS, "freellm/auto")


# -- web ----------------------------------------------------------------------


def _recording_factory():
    seen: list[dict] = []

    class Pipe(fake_factory()):
        def __init__(self, **kwargs):
            seen.append(kwargs)
            super().__init__(**kwargs)

    return Pipe, seen


def test_job_runs_with_chosen_provider_chain(make_app):
    pipe, seen = _recording_factory()
    app, _ = make_app(pipeline_factory=pipe)
    client = TestClient(app, base_url="http://127.0.0.1")
    response = create_job(
        client,
        "00000000-0000-4000-8000-000000000001",
        provider_mode="freellm_gemini",
        freellm_model="llama-4-scout",
    )
    assert response.status_code == 202, response.text
    job = wait_for(client, response.json()["job_id"])
    assert job["state"] == "completed"
    assert job["options"]["provider_mode"] == "freellm_gemini"
    assert job["options"]["freellm_model"] == "llama-4-scout"
    assert seen[0]["model"] == "freellm/llama-4-scout"
    assert seen[0]["fallback_models"][0] == DEFAULT_MODEL


def test_gemini_mode_keeps_the_app_model_only(make_app):
    pipe, seen = _recording_factory()
    app, _ = make_app(pipeline_factory=pipe)
    client = TestClient(app, base_url="http://127.0.0.1")
    response = create_job(client, "00000000-0000-4000-8000-000000000002")
    job = wait_for(client, response.json()["job_id"])
    assert job["options"]["provider_mode"] == "gemini"
    assert "fallback_models" not in seen[0]


def test_research_is_rejected_for_freellm_only(web_client):
    response = create_job(
        web_client,
        "00000000-0000-4000-8000-000000000003",
        provider_mode="freellm",
        research_company=True,
    )
    assert response.status_code == 422


def test_bad_freellm_model_id_is_rejected(web_client):
    response = create_job(
        web_client,
        "00000000-0000-4000-8000-000000000004",
        provider_mode="freellm",
        freellm_model="../etc passwd",
    )
    assert response.status_code == 422


def test_providers_endpoint_lists_available_models(make_app, monkeypatch):
    calls = []

    def fetch(key, base):
        calls.append(key)
        return [
            {"id": "auto", "name": "Auto", "context_window": 1000, "available": True},
            {"id": "gone", "available": False},
        ]

    monkeypatch.setattr(
        web_app, "ProviderCatalog", lambda: ProviderCatalog(api_key="sk-secret-proxy-key", fetch=fetch)
    )
    app, _ = make_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    body = client.get("/api/providers").json()
    assert body["freellm"]["reachable"] is True
    assert [m["id"] for m in body["freellm"]["models"]] == ["auto"]
    assert "sk-secret-proxy-key" not in json.dumps(body)
    client.get("/api/providers")
    assert len(calls) == 1  # cached


def test_providers_offline_and_unconfigured():
    def down(key, base):
        raise httpx.ConnectError("refused")

    offline = ProviderCatalog(api_key="k", fetch=down).snapshot().freellm
    assert offline.configured and not offline.reachable and offline.error
    missing = ProviderCatalog(api_key="").snapshot().freellm
    assert not missing.configured and not missing.reachable
