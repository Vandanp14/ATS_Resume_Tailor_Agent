"""Salvaging exhausted rewrites and the user-directed bullet review pause."""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import resume_tailor.pipeline as pipeline_module
import tailor
from models import (
    ProjectRewriteResponse,
    ScoredBullet,
    ScoredWork,
    WorkRewriteItem,
    WorkRewriteResponse,
)
from pipeline_core import (
    master_fact_index,
    salvage_project_item,
    salvage_work_item,
    validate_work_item,
)
from render import ScoredResume
from resume_tailor.bullet_review import (
    BULLET_REVIEW_FILENAME,
    BulletReviewSelectionError,
    apply_bullet_review,
    load_bullet_review,
    persist_bullet_review,
)
from resume_tailor.pipeline import TailorPipeline
from tests.conftest import create_job, wait_for
from tests.test_holistic_review import Stub
from tests.test_tailor import (
    evidence_plan,
    master,
    project_item,
    selected_evidence,
    work_item,
)


def _setup():
    resume = master()
    selected = selected_evidence(resume)
    plan = evidence_plan(selected)
    return resume, selected, plan, master_fact_index(resume)


def test_salvage_keeps_valid_bullets_and_flags_fixed_ones():
    _resume, selected, plan, facts = _setup()
    source = selected.work[1]
    item = work_item(source, plan)
    item.bullets[0].text = "Built reporting services in Kotlin and JavaScript for operations teams."
    missing = item.bullets.pop()  # the model "forgot" one bullet
    salvaged, flags = salvage_work_item(item, source, plan, facts, ("Kotlin",))

    validate_work_item(salvaged, source, plan, facts, None, ("Kotlin",))
    assert len(salvaged.bullets) == len(item.bullets) + 1
    assert "Kotlin" not in salvaged.bullets[0].text
    edited, absent = flags
    assert edited["safe_kind"] == "edited" and edited["can_keep"] is True
    assert edited["original_text"].startswith("Built reporting services in Kotlin")
    assert "Names 'Kotlin'" in edited["issues"][0]
    assert absent["original_text"] is None and absent["can_keep"] is False
    assert absent["assignment_id"] == missing.evidence_assignment_id
    assert absent["safe_kind"] == "source_fact"


def test_salvage_with_no_model_output_writes_every_bullet_from_facts():
    _resume, selected, plan, facts = _setup()
    salvaged, flags = salvage_work_item(None, selected.work[0], plan, facts)
    assert len(salvaged.bullets) == 4 and len(flags) == 4
    assert all(bullet.text in {f["text"] for f in facts.values()} or bullet.text.endswith(".") for bullet in salvaged.bullets)
    # The inferred metric on allocation-1 is dropped once its bullet is verbatim fact text.
    assert plan.assignments[0].inferred_impact is None


def test_project_salvage_fills_two_local_bullets():
    _resume, selected, _plan, facts = _setup()
    source = selected.projects[0]
    item = project_item(source)
    item.bullets = item.bullets[:1]
    salvaged, flags = salvage_project_item(item, source, facts)
    assert len(salvaged.bullets) == 2
    assert len(flags) == 1 and flags[0]["original_text"] is None


class SalvageStub(Stub):
    """Rewrite stage that keeps claiming a technology the master never states."""

    def __call__(self, template, response_model, **context):
        if response_model is WorkRewriteResponse:
            self.calls.append((template, response_model, context))
            sources = json.loads(context["selected_work_json"])
            items = [work_item(source, self.plan) for source in sources]
            items[0].bullets[1].text = "Automated a manual workflow in Figma and Python for operations."
            return WorkRewriteResponse(work=items)
        return super().__call__(template, response_model, **context)


def _run(monkeypatch, tmp_path, *, allow_review: bool) -> tuple[int, TailorPipeline]:
    pipeline = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite",
        call_interval=0,
        provider=MagicMock(),
        bridge_skills=True,
        allow_fit_recovery=allow_review,
    )
    monkeypatch.setattr(pipeline, "_call_once", SalvageStub(bridge=True))
    monkeypatch.setattr(pipeline_module, "render", MagicMock())
    result = pipeline.run(master(), "Hiring Python engineer", tmp_path, no_pdf=True)
    return result, pipeline


def test_web_run_pauses_for_review_instead_of_failing(monkeypatch, tmp_path):
    result, _ = _run(monkeypatch, tmp_path, allow_review=True)
    assert result == 2
    bundle = load_bullet_review(tmp_path)
    assert len(bundle.flags) == 1
    flag = bundle.flags[0]
    assert flag.can_keep and "Figma" in flag.original_text and "Figma" not in flag.safe_text
    assert bundle.pending_report["pipeline_status"] == "review_required"
    assert not (tmp_path / "tailored.json").exists()


def test_cli_run_keeps_safe_versions_and_reports_them(monkeypatch, tmp_path):
    result, _ = _run(monkeypatch, tmp_path, allow_review=False)
    assert result == 0
    report = json.loads((tmp_path / "match_report.json").read_text())
    assert len(report["auto_safe_fixes"]) == 1
    tailored = json.dumps(json.loads((tmp_path / "tailored.json").read_text())["work"])
    assert "Figma" not in tailored
    assert not (tmp_path / BULLET_REVIEW_FILENAME).exists()


def _bundle(tmp_path, *, can_keep=True):
    scored = ScoredResume(
        basics={"name": "Test User"},
        work=[
            ScoredWork(
                name="Example Corp",
                position="Engineer",
                source_id="work[0]",
                relevance=60,
                highlights=[ScoredBullet(text="Built reporting services for operations.", relevance=60)],
            )
        ],
    )
    flag = {
        "section": "work",
        "source_id": "work[0]",
        "label": "Engineer · Example Corp",
        "assignment_id": "allocation-1",
        "issues": ["Names 'Kotlin', which your master resume never states."],
        "original_text": "Built reporting services in Kotlin for operations.",
        "safe_text": "Built reporting services for operations.",
        "safe_kind": "edited",
        "can_keep": can_keep,
        "source_fact_ids": ["work[0].highlights[0]"],
    }
    return persist_bullet_review(
        tmp_path,
        scored,
        [flag],
        pending_report={"pipeline_status": "review_required"},
        no_pdf=True,
        jd_profile_json="{}",
        forbidden_terms=["Kotlin"],
        tech_requirements=[],
        fact_index={"work[0].highlights[0]": {"text": "Built reporting services."}},
    )


@pytest.mark.parametrize(
    "choice, expected",
    [
        ("safe", "Built reporting services for operations."),
        ("keep", "Built reporting services in Kotlin for operations."),
        ("regenerate", "Rebuilt the operations reporting service from scratch."),
    ],
)
def test_apply_review_choices_then_render(tmp_path, choice, expected):
    bundle = _bundle(tmp_path)
    result = apply_bullet_review(
        tmp_path,
        {bundle.flags[0].flag_id: choice},
        regenerate=lambda flag, _bundle: "Rebuilt the operations reporting service from scratch.",
    )
    assert result == 0
    tailored = json.loads((tmp_path / "tailored.json").read_text())
    assert tailored["work"][0]["highlights"] == [expected]
    report = json.loads((tmp_path / "match_report.json").read_text())
    assert report["pipeline_status"] == "completed_with_bullet_review"
    assert report["bullet_review_decisions"][0]["choice"] == choice
    assert not (tmp_path / BULLET_REVIEW_FILENAME).exists()


def test_failed_regeneration_falls_back_to_safe(tmp_path):
    bundle = _bundle(tmp_path)
    apply_bullet_review(tmp_path, {bundle.flags[0].flag_id: "regenerate"}, regenerate=lambda *_: None)
    report = json.loads((tmp_path / "match_report.json").read_text())
    assert report["bullet_review_decisions"][0]["outcome"] == "regenerate_failed_used_safe"


def test_keep_is_refused_for_structural_problems(tmp_path):
    bundle = _bundle(tmp_path, can_keep=False)
    with pytest.raises(BulletReviewSelectionError, match="cannot be kept"):
        apply_bullet_review(tmp_path, {bundle.flags[0].flag_id: "keep"})


# Web: pause, review, continue -------------------------------------------------


class ReviewPipe(TailorPipeline):
    def run(self, master, jd_text, out_dir, no_pdf, job):
        assert self.allow_fit_recovery is True
        _bundle(out_dir)
        return 2

    def regenerate_review_bullet(self, flag, bundle):
        return "Rebuilt the operations reporting service from scratch."


def test_web_review_round_trip(make_app):
    app, output_dir = make_app(pipeline_factory=ReviewPipe)
    client = TestClient(app, base_url="http://127.0.0.1")
    job_id = create_job(client, str(uuid.uuid4())).json()["job_id"]
    status = wait_for(client, job_id, states=("action_required",))
    assert status["action_kind"] == "bullet_review"
    assert "1 bullet need" in status["message"]

    review = client.get(f"/api/jobs/{job_id}/bullet-review").json()
    item = review["items"][0]
    assert item["can_keep"] is True and "Kotlin" in item["original_text"]
    assert client.get(f"/api/jobs/{job_id}/fit-recovery").status_code == 409

    bad = client.post(
        f"/api/jobs/{job_id}/bullet-review",
        json={"revision": review["revision"], "decisions": {"nope": "safe"}},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert bad.status_code == 422

    key = str(uuid.uuid4())
    body = {"revision": review["revision"], "decisions": {item["flag_id"]: "regenerate"}}
    accepted = client.post(
        f"/api/jobs/{job_id}/bullet-review", json=body, headers={"Idempotency-Key": key}
    )
    assert accepted.status_code == 202
    done = wait_for(client, job_id, states=("completed", "failed"))
    assert done["state"] == "completed", done
    tailored = json.loads((output_dir / job_id / "tailored.json").read_text())
    assert tailored["work"][0]["highlights"] == [
        "Rebuilt the operations reporting service from scratch."
    ]
    replay = client.post(
        f"/api/jobs/{job_id}/bullet-review", json=body, headers={"Idempotency-Key": key}
    )
    assert replay.status_code == 202
