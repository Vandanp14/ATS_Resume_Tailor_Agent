"""Model chains by job type and per-model request pacing."""

from __future__ import annotations

import importlib

import pytest

import prompt
import resume_tailor.config as config


@pytest.fixture
def fresh_config(monkeypatch):
    """Reload prompt/config so env-driven defaults are re-read."""

    def load(**env: str):
        for name in ("PLANNING_MODELS", "WRITING_MODELS", "FIX_MODELS", "FALLBACK_MODELS", "MODEL_RPM"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        importlib.reload(prompt)
        return importlib.reload(config)

    yield load
    monkeypatch.undo()
    importlib.reload(prompt)
    importlib.reload(config)


def test_gemini_mode_has_three_chains(fresh_config):
    cfg = fresh_config()
    chains = cfg.resolve_chains("gemini")
    assert chains.model == cfg.DEFAULT_MODEL
    assert chains.planning[0] == "gemini-3.8-flash"
    assert chains.writing[0] == "gemini-3.7-flash"
    assert chains.fixes[0] == "gemini-3.5-flash-lite"
    assert chains.fallback == cfg.FALLBACK_MODELS


def test_mixed_modes_place_proxy(fresh_config):
    cfg = fresh_config()
    lead = cfg.resolve_chains("freellm_gemini", "auto")
    assert lead.model == "freellm/auto"
    assert lead.planning[0] == "freellm/auto"
    assert lead.writing[0] == "freellm/auto"
    assert lead.fixes[0] == "freellm/auto"
    trail = cfg.resolve_chains("gemini_freellm", "auto")
    assert trail.fallback[-1] == "freellm/auto"
    assert "freellm/auto" not in trail.writing
    only = cfg.resolve_chains("freellm", "auto")
    assert (only.planning, only.writing, only.fixes, only.fallback) == ((), (), (), ())


def test_model_rpm_defaults_and_overrides(fresh_config):
    fresh_config()
    assert prompt.model_rpm("gemini-3.7-flash") == 10
    assert prompt.model_rpm("gemini-3.5-flash-lite") == 15
    assert prompt.model_rpm(None) == 10
    fresh_config(MODEL_RPM="gemini-3.7-flash=20")
    assert prompt.model_rpm("gemini-3.7-flash") == 20


class _ChainProvider:
    supports_model_chain = True

    def chat(self, *args, **kwargs):  # pragma: no cover - routing only
        raise AssertionError("not called")


def test_rewrite_templates_use_writing_chain():
    from resume_tailor.pipeline import TailorPipeline

    pipeline = TailorPipeline(
        model="gemini-3.1-flash-lite",
        call_interval=0,
        provider=_ChainProvider(),
        planning_models=["p1"],
        writing_models=["w1"],
        fix_models=["f1"],
        fallback_models=["fb"],
    )
    tail = ("gemini-3.1-flash-lite", "fb")
    assert pipeline._chain_for("tailor_work") == ("w1", *tail)
    assert pipeline._chain_for("tailor_projects")[0] == "w1"
    assert pipeline._chain_for("jd_parse")[0] == "w1"
    assert pipeline._chain_for("concise_bullet") == ("f1", *tail)
    assert pipeline._chain_for("select_work") == ("p1", *tail)
    assert pipeline._chain_for("research_company_stack") == tail


def test_pacer_uses_per_model_interval(monkeypatch):
    from resume_tailor import runtime

    now = [100.0]
    slept: list[float] = []
    monkeypatch.setattr(runtime.time, "monotonic", lambda: now[0])

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(runtime.time, "sleep", sleep)
    pacer = runtime.RatePacer(4.5, interval_for={"a": 6.0, "b": 0.0}.get)
    pacer.wait("a")
    pacer.wait("a")
    assert slept == [pytest.approx(6.0)]
    pacer.wait("b")
    pacer.wait("b")
    assert slept == [pytest.approx(6.0)]
