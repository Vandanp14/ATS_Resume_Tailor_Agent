import json
from unittest.mock import MagicMock

import pytest

import tailor
import resume_tailor.pipeline as pipeline_module
from models import (
    CandidateSelection,
    EvidencePlan,
    HolisticReview,
    JDProfile,
    ProjectRewriteResponse,
    RequirementProxy,
    RequirementProxyPlan,
    ScoredSkill,
    SectionEdits,
    SelectionCandidate,
    TailoredSkills,
    TransferableSkill,
    TransferableSkillPlan,
    TRANSFERABLE_SKILL_GROUP,
    WorkRewriteResponse,
)
from tests.test_progress import CapturingReporter
from tests.test_tailor import (
    components,
    evidence_plan,
    master,
    project_item,
    selected_evidence,
    work_item,
)
from pipeline_core import apply_review_edits
from render import RenderError
from resume_tailor.progress import ProgressEventKind


class Stub:
    def __init__(self, review=None, bridge=False):
        self.calls = []
        self.review = review or HolisticReview(
            coverage_pct=90,
            missing_must_haves=[],
            weak_sections=[],
            truth_violations=[],
            recommendations=[],
        )
        self.selected = selected_evidence()
        self.plan = evidence_plan(self.selected)
        self.bridge = bridge
        self.proxy_plan = RequirementProxyPlan(
            proxies=(
                [
                    RequirementProxy(
                        requirement="Figma",
                        requirement_type="nice_to_have",
                        category="tool",
                        proximity="analogous_workflow",
                        proxy_terms=["reusable components"],
                        source_fact_ids=["work[1].highlights[1]"],
                        transfer_basis="Accessible component design is adjacent UI evidence.",
                        relevance=80,
                        list_as_transferable_skill=True,
                    )
                ]
                if bridge
                else []
            )
        )

    def __call__(self, template, response_model, **context):
        self.calls.append((template, response_model, context))
        if response_model is JDProfile:
            return JDProfile(
                role="Engineer",
                must_have_skills=["Python"],
                nice_to_have_skills=["Figma"] if self.bridge else [],
                keywords=[],
            )
        if response_model is CandidateSelection:
            candidates = json.loads(context["candidates_json"])
            return CandidateSelection(
                candidates=[
                    SelectionCandidate(
                        source_id=item["source_id"],
                        relevance=100 - index,
                        selected=True,
                    )
                    for index, item in enumerate(candidates)
                ]
            )
        if response_model is EvidencePlan:
            return self.plan
        if response_model is RequirementProxyPlan:
            return self.proxy_plan
        if response_model is TailoredSkills:
            return TailoredSkills(
                skills=[
                    ScoredSkill(name="Languages", keywords=["Python"], relevance=90),
                    *(
                        [
                            ScoredSkill(
                                name=TRANSFERABLE_SKILL_GROUP,
                                keywords=["Figma"],
                                relevance=80,
                            )
                        ]
                        if self.bridge
                        else []
                    ),
                ]
            )
        if response_model is WorkRewriteResponse:
            sources = json.loads(context["selected_work_json"])
            return WorkRewriteResponse(
                work=[work_item(source, self.plan) for source in sources]
            )
        if response_model is ProjectRewriteResponse:
            sources = json.loads(context["selected_projects_json"])
            return ProjectRewriteResponse(
                projects=[project_item(source) for source in sources]
            )
        if response_model is HolisticReview:
            return self.review
        raise AssertionError(response_model)


def run(monkeypatch, tmp_path, review=None, real_render=False, bridge=False):
    pipeline = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite",
        call_interval=0,
        provider=MagicMock(),
        bridge_skills=bridge,
    )
    stub = Stub(review, bridge=bridge)
    monkeypatch.setattr(pipeline, "_call_once", stub)
    if not real_render:
        monkeypatch.setattr(pipeline_module, "render", MagicMock())
    return pipeline.run(master(), "Hiring Python engineer", tmp_path, no_pdf=True), stub


def test_evidence_planner_replaces_summary_and_reviewer_runs_exactly_once(
    monkeypatch, tmp_path
):
    result, stub = run(monkeypatch, tmp_path, real_render=True)
    assert result == 0
    models = [model for _, model, _ in stub.calls]
    assert models.count(EvidencePlan) == 1
    assert models.count(RequirementProxyPlan) == 0
    assert models.count(HolisticReview) == 1
    assert models[-1] is HolisticReview
    assert all(model.__name__ != "TailoredSummary" for model in models)

    plan_context = next(
        context for _, model, context in stub.calls if model is EvidencePlan
    )
    global_evidence = json.loads(plan_context["global_evidence_json"])
    destinations = json.loads(plan_context["selected_work_destinations_json"])
    assert set(global_evidence) == {"work", "projects", "skills"}
    assert len(destinations) == 3
    assert [item["required_bullets"] for item in destinations] == [4, 3, 3]

    review_context = stub.calls[-1][2]
    assert "evidence_plan_json" in review_context
    assert "generated_components_json" in review_context

    tailored = json.loads((tmp_path / "tailored.json").read_text())
    report = json.loads((tmp_path / "match_report.json").read_text())
    tex = (tmp_path / "resume.tex").read_text()
    assert "summary" not in tailored["basics"]
    assert "This master-only summary" not in tex
    assert [len(item["highlights"]) for item in tailored["work"]] == [4, 3, 3]
    assert [len(item["highlights"]) for item in tailored["projects"]] == [2, 2]
    assert report["cross_entry_attributions"][0]["destination_work_id"] == "work[0]"
    assert (
        report["inferred_metrics"][0]["final_claim"] == "reduced processing time by 35% against the manual baseline"
    )
    assert "reduced processing time by 35% against the manual baseline" in tailored["work"][0]["highlights"][0]
    assert report["transferable_skill_injections"] == []


def test_opt_in_transferable_skill_stage_is_traced_and_skills_only(
    monkeypatch, tmp_path
):
    result, stub = run(monkeypatch, tmp_path, real_render=True, bridge=True)
    assert result == 0
    models = [model for _, model, _ in stub.calls]
    assert models.count(RequirementProxyPlan) == 1
    bridge_context = next(
        context for _, model, context in stub.calls if model is RequirementProxyPlan
    )
    assert "global_evidence_json" in bridge_context
    assert "Figma" in bridge_context["missing_requirements_json"]

    tailored = json.loads((tmp_path / "tailored.json").read_text())
    report = json.loads((tmp_path / "match_report.json").read_text())
    bridge_group = next(
        group
        for group in tailored["skills"]
        if group["name"] == TRANSFERABLE_SKILL_GROUP
    )
    assert bridge_group["keywords"] == ["Figma"]
    experience = json.dumps(
        {"work": tailored["work"], "projects": tailored["projects"]}
    )
    assert "Figma" not in experience
    assert report["transferable_skill_injections"][0]["keyword"] == "Figma"
    assert (
        report["transferable_skill_injections"][0]["final_group"]
        == TRANSFERABLE_SKILL_GROUP
    )
    review_context = next(
        context for _, model, context in stub.calls if model is HolisticReview
    )
    assert "transferable_skill_plan_json" in review_context


def test_invalid_reviewer_edit_is_skipped_but_run_completes(monkeypatch, tmp_path):
    review = HolisticReview(
        coverage_pct=95,
        missing_must_haves=[],
        weak_sections=[],
        truth_violations=[],
        recommendations=[],
        section_edits=SectionEdits(
            skills=TailoredSkills(
                skills=[
                    ScoredSkill(name="Cloud", keywords=["Kubernetes"], relevance=100)
                ]
            )
        ),
    )
    result, _ = run(monkeypatch, tmp_path, review)
    assert result == 0
    report = json.loads((tmp_path / "match_report.json").read_text())
    assert report["pipeline_status"] == "completed_with_rejected_edits"
    assert "Kubernetes" in report["rejected_section_edits"][0]
    assert (tmp_path / "tailored.json").exists()
    assert (tmp_path / ".done").exists()


def test_rejected_reviewer_edit_emits_terminal_warning(monkeypatch, tmp_path):
    review = HolisticReview(
        coverage_pct=95,
        missing_must_haves=[],
        weak_sections=[],
        truth_violations=[],
        recommendations=[],
        section_edits=SectionEdits(
            skills=TailoredSkills(
                skills=[
                    ScoredSkill(name="Cloud", keywords=["Kubernetes"], relevance=100)
                ]
            )
        ),
    )
    reporter = CapturingReporter()
    pipeline = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite",
        call_interval=0,
        provider=MagicMock(),
        reporter=reporter,
    )
    monkeypatch.setattr(pipeline, "_call_once", Stub(review))
    monkeypatch.setattr(pipeline_module, "render", MagicMock())
    result = pipeline.run(master(), "Hiring Python engineer", tmp_path, no_pdf=True)
    assert result == 0
    warnings = [
        event
        for event in reporter.events
        if event.kind == ProgressEventKind.STAGE_WARNING
        and event.message.startswith("Reviewer edit rejected")
    ]
    assert len(warnings) == 1
    assert "Kubernetes" in warnings[0].message


def test_reviewer_cannot_remove_planned_transferable_group(monkeypatch, tmp_path):
    review = HolisticReview(
        coverage_pct=95,
        missing_must_haves=[],
        weak_sections=[],
        truth_violations=[],
        recommendations=[],
        section_edits=SectionEdits(
            skills=TailoredSkills(
                skills=[
                    ScoredSkill(name="Languages", keywords=["Python"], relevance=90)
                ]
            )
        ),
    )
    result, _ = run(monkeypatch, tmp_path, review, bridge=True)
    assert result == 0
    report = json.loads((tmp_path / "match_report.json").read_text())
    assert "bridge_group_mismatch=True" in report["rejected_section_edits"][0]
    assert report["pipeline_status"] == "completed_with_rejected_edits"
    assert (tmp_path / "tailored.json").exists()


def test_reviewer_skills_edit_accepts_jd_grounded_keywords_and_dedupes():
    resume = master()
    parts = components(resume)
    review = HolisticReview(
        coverage_pct=95,
        missing_must_haves=[],
        weak_sections=[],
        truth_violations=[],
        recommendations=[],
        section_edits=SectionEdits(
            skills=TailoredSkills(
                skills=[
                    ScoredSkill(
                        name="Programming",
                        keywords=["Java", "J2EE", "Java"],
                        relevance=95,
                    ),
                    ScoredSkill(
                        name="Languages",
                        keywords=["Java", "Python"],
                        relevance=85,
                    ),
                ]
            )
        ),
    )
    updated, rejected = apply_review_edits(review, resume, parts, jd_keywords=["J2EE"])
    assert rejected == []
    groups = {group.name: group.keywords for group in updated.skills.skills}
    assert groups["Programming"] == ["Java", "J2EE"]
    assert groups["Languages"] == ["Python"]


def test_unresolved_truth_violation_blocks_render_and_done(monkeypatch, tmp_path):
    unsupported_claim = (
        "Automated a repetitive operations workflow with Python, "
        "reduced processing time by 35% against the manual baseline."
    )
    review = HolisticReview.model_validate(
        {
            "coverage_pct": 80,
            "missing_must_haves": [],
            "weak_sections": ["work"],
            "truth_violations": [
                {
                    "section": "work",
                    "claim": unsupported_claim,
                    "reason": "The inference is implausible for the supplied basis.",
                }
            ],
            "recommendations": [],
        }
    )
    result, _ = run(monkeypatch, tmp_path, review)
    assert result == 1
    assert not (tmp_path / "tailored.json").exists()
    assert not (tmp_path / ".done").exists()
    assert (
        json.loads((tmp_path / "match_report.json").read_text())["pipeline_status"]
        == "blocked_truth_violations"
    )


def test_reviewer_correction_moves_stale_violation_to_resolved(monkeypatch, tmp_path):
    selected = selected_evidence()
    plan = evidence_plan(selected)
    replacement = WorkRewriteResponse(
        work=[work_item(source, plan) for source in selected.work]
    )
    old_claim = replacement.work[0].bullets[0].text
    replacement.work[0].bullets[0].text = (
        "Built a validated Python automation, cutting processing time by 35% against the manual baseline."
    )
    review = HolisticReview(
        coverage_pct=90,
        missing_must_haves=[],
        weak_sections=[],
        truth_violations=[
            {
                "section": "work",
                "claim": old_claim,
                "reason": "The original wording overstates the implementation.",
            }
        ],
        recommendations=["Use the supplied grounded replacement."],
        section_edits=SectionEdits(work=replacement),
    )

    result, _ = run(monkeypatch, tmp_path, review)

    assert result == 0
    report = json.loads((tmp_path / "match_report.json").read_text())
    assert report["truth_violations"] == []
    assert report["resolved_truth_violations"][0]["claim"] == old_claim
    assert report["pipeline_status"] == "completed"


def test_one_page_failure_removes_partial_final_artifacts(monkeypatch, tmp_path):
    pipeline = tailor.TailorPipeline(
        model="gemini-3.1-flash-lite", call_interval=0, provider=MagicMock()
    )
    monkeypatch.setattr(pipeline, "_call_once", Stub())
    monkeypatch.setattr(pipeline_module, "ensure_tectonic", MagicMock())

    def fail_fit(_resume, out_dir, progress_callback=None):
        del progress_callback
        (out_dir / "resume.tex").write_text("partial")
        (out_dir / "resume.pdf").write_bytes(b"partial")
        raise RenderError("cannot fit without trimming protected work bullets")

    monkeypatch.setattr(pipeline_module, "fit_to_one_page", fail_fit)
    with pytest.raises(tailor.StageFailure, match="render failed"):
        pipeline.run(master(), "Hiring Python engineer", tmp_path, no_pdf=False)
    assert not (tmp_path / "resume.tex").exists()
    assert not (tmp_path / "resume.pdf").exists()
    assert not (tmp_path / "tailored.json").exists()
    assert (tmp_path / "diagnostic_report.json").exists()
