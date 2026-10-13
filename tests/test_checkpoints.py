"""A failed run resumes from its last finished stage instead of starting over."""

import json
from unittest.mock import MagicMock

import pytest

import tailor
import resume_tailor.pipeline as pipeline_module
from models import HolisticReview, RequirementProxyPlan, WorkRewriteResponse
from resume_tailor.checkpoints import CHECKPOINT_DIR
from resume_tailor.runtime import ModelUnavailableError
from tests.test_holistic_review import Stub
from tests.test_tailor import master

JD = "Hiring Python engineer"


class OutageAt(Stub):
    """Answers like ``Stub`` until ``failing`` is reached, then every model is down."""

    def __init__(self, failing=None, bridge=False):
        super().__init__(bridge=bridge)
        self.failing = failing

    def __call__(self, template, response_model, **context):
        if response_model is self.failing:
            self.calls.append((template, response_model, context))
            raise ModelUnavailableError(
                template, [("gemini-3.1-flash-lite", "503 UNAVAILABLE")]
            )
        return super().__call__(template, response_model, **context)


def run(monkeypatch, out_dir, stub, jd=JD, resume=False, bridge=False):
    pipeline = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite",
        call_interval=0,
        provider=MagicMock(),
        bridge_skills=bridge,
    )
    monkeypatch.setattr(pipeline, "_call_once", stub)
    return pipeline.run(master(), jd, out_dir, no_pdf=True, resume=resume)


def models_called(stub):
    return [model for _, model, _ in stub.calls]


@pytest.fixture(autouse=True)
def fake_render(monkeypatch):
    monkeypatch.setattr(pipeline_module, "render", MagicMock())


@pytest.mark.parametrize("bridge", [False, True])
def test_resume_reruns_only_the_failed_stage_and_matches_a_clean_run(
    monkeypatch, tmp_path, bridge
):
    clean_dir, failed_dir = tmp_path / "clean", tmp_path / "failed"
    assert run(monkeypatch, clean_dir, OutageAt(bridge=bridge), bridge=bridge) == 0

    with pytest.raises(ModelUnavailableError):
        run(monkeypatch, failed_dir, OutageAt(HolisticReview, bridge), bridge=bridge)
    assert not (failed_dir / "tailored.json").exists()

    resumed = OutageAt(bridge=bridge)
    assert run(monkeypatch, failed_dir, resumed, resume=True, bridge=bridge) == 0
    assert models_called(resumed) == [HolisticReview]
    for name in ("tailored.json", "match_report.json"):
        assert json.loads((failed_dir / name).read_text()) == json.loads(
            (clean_dir / name).read_text()
        )
    assert not (failed_dir / CHECKPOINT_DIR).exists()


def test_resume_after_mid_run_failure_reuses_only_finished_stages(
    monkeypatch, tmp_path
):
    with pytest.raises(ModelUnavailableError):
        run(monkeypatch, tmp_path, OutageAt(WorkRewriteResponse))

    resumed = OutageAt()
    assert run(monkeypatch, tmp_path, resumed, resume=True) == 0
    called = models_called(resumed)
    assert called[0] is WorkRewriteResponse
    assert called[-1] is HolisticReview


def test_fresh_run_ignores_checkpoints(monkeypatch, tmp_path):
    with pytest.raises(ModelUnavailableError):
        run(monkeypatch, tmp_path, OutageAt(HolisticReview))

    fresh = OutageAt()
    assert run(monkeypatch, tmp_path, fresh) == 0
    assert len(models_called(fresh)) > 1


def test_changed_job_description_invalidates_checkpoints(monkeypatch, tmp_path):
    with pytest.raises(ModelUnavailableError):
        run(monkeypatch, tmp_path, OutageAt(HolisticReview))

    edited = OutageAt()
    assert run(monkeypatch, tmp_path, edited, jd=JD + " with SQL", resume=True) == 0
    assert len(models_called(edited)) > 1


def test_resume_without_checkpoints_runs_everything(monkeypatch, tmp_path):
    stub = OutageAt(bridge=True)
    assert run(monkeypatch, tmp_path, stub, resume=True, bridge=True) == 0
    assert RequirementProxyPlan in models_called(stub)
    assert models_called(stub)[-1] is HolisticReview
