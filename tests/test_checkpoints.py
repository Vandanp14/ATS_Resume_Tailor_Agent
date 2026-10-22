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


# -- stage-scoped fingerprints: answering skills keeps the parse and the map --


def _answered_master_json(confirmed=(), declined=()):
    from resume_tailor.skill_answers import apply_answers

    return apply_answers(master(), list(confirmed), list(declined)).model_dump_json()


def test_jd_parse_checkpoint_survives_master_change(tmp_path):
    from resume_tailor.checkpoints import CheckpointStore, stage_fingerprint

    def store(master_json):
        return CheckpointStore(
            tmp_path, lambda name: stage_fingerprint(name, master_json=master_json, jd_text=JD)
        )

    store(master().model_dump_json()).save("jd_parse", {"role": "x"})
    edited = master().model_copy(update={"basics": None}).model_dump_json()
    assert store(edited).load("jd_parse") == {"payload": {"role": "x"}}
    other_jd = CheckpointStore(
        tmp_path, lambda name: stage_fingerprint(name, master_json=edited, jd_text="Other")
    )
    assert other_jd.load("jd_parse") is None


def test_requirement_map_survives_only_answer_changes(tmp_path):
    from resume_tailor.checkpoints import CheckpointStore, stage_fingerprint

    def store(master_json):
        return CheckpointStore(
            tmp_path, lambda name: stage_fingerprint(name, master_json=master_json, jd_text=JD)
        )

    store(master().model_dump_json()).save("requirement_map", {"proxy_plan": {}})
    answered = _answered_master_json(["Figma"], ["Siteimprove"])
    assert store(answered).has("requirement_map")
    store(master().model_dump_json()).save("select_work", [])
    assert not store(answered).has("select_work")
    changed = master()
    changed.work[0].highlights = ["Rewrote the billing service."]
    assert not store(changed.model_dump_json()).has("requirement_map")


def test_restored_map_marks_confirmed_skill_direct():
    from keyword_coverage import requirement_map, restore_requirements
    from models import JDProfile, KeywordWeight, RequirementProxy
    from pipeline_core import master_fact_index
    from resume_tailor.skill_answers import apply_answers

    jd = JDProfile(
        role="Web Developer",
        must_have_skills=["Figma"],
        nice_to_have_skills=[],
        keywords=[KeywordWeight(term="Figma", weight=5, category="tool", evidence_span="Figma")],
    )
    before = master_fact_index(master())
    fact_id = next(iter(before))
    plan = RequirementProxyPlan(
        proxies=[
            RequirementProxy(
                requirement="Figma",
                requirement_type="must_have",
                category="tool",
                proximity="analogous_workflow",
                proxy_terms=["React"],
                source_fact_ids=[fact_id],
                transfer_basis="UI design work",
                relevance=60,
                list_as_transferable_skill=False,
            )
        ]
    )
    assert requirement_map(jd, before)[0]["status"] == "missing"
    after = master_fact_index(apply_answers(master(), ["Figma"], []))
    requirements, kept = restore_requirements(jd, after, plan)
    assert requirements[0]["status"] == "direct"
    assert "proxy_terms" not in requirements[0]
    assert kept.proxies == []
    still_missing, kept = restore_requirements(jd, before, plan)
    assert still_missing[0]["status"] == "proxy"
    assert len(kept.proxies) == 1


def test_old_version_checkpoint_ignored(tmp_path):
    from resume_tailor.checkpoints import CHECKPOINT_VERSION, CheckpointStore, stage_fingerprint

    assert CHECKPOINT_VERSION == 2
    store = CheckpointStore(
        tmp_path, lambda name: stage_fingerprint(name, master_json="{}", jd_text=JD)
    )
    path = tmp_path / CHECKPOINT_DIR / "jd_parse.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"fingerprint": "v1-hash", "payload": {}}), encoding="utf-8")
    assert store.load("jd_parse") is None


def test_restored_proxies_are_revalidated_against_current_facts():
    from models import JDProfile, KeywordWeight, RequirementProxy
    from pipeline_core import master_fact_index
    from resume_tailor.skill_answers import apply_answers, replace_answers

    jd = JDProfile(
        role="Designer",
        must_have_skills=["Sketch"],
        nice_to_have_skills=[],
        keywords=[KeywordWeight(term="Sketch", weight=5, category="tool", evidence_span="Sketch")],
    )
    confirmed = apply_answers(master(), ["Figma"], [])
    facts = master_fact_index(confirmed)
    figma_fact = next(fid for fid, fact in facts.items() if fact["text"] == "Figma")
    plan = RequirementProxyPlan(
        proxies=[
            RequirementProxy(
                requirement="Sketch",
                requirement_type="must_have",
                category="tool",
                proximity="same_family",
                proxy_terms=["Figma"],
                source_fact_ids=[figma_fact],
                transfer_basis="Both are UI design tools.",
                relevance=80,
                list_as_transferable_skill=True,
            )
        ]
    )
    pipeline = tailor.TailorPipeline(model="gemini-3.1-flash-lite", call_interval=0, provider=MagicMock())
    kept_requirements, kept = pipeline._restore_requirement_map(jd, facts, plan.model_copy(deep=True))
    assert len(kept.proxies) == 1 and kept_requirements[0]["status"] == "proxy"
    declined = replace_answers(confirmed, [], ["Figma"])
    requirements, kept = pipeline._restore_requirement_map(
        jd, master_fact_index(declined), plan.model_copy(deep=True)
    )
    assert kept.proxies == []
    assert requirements[0]["status"] == "missing"
