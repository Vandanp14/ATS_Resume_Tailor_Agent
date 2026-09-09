"""Unit and integration-boundary tests for the work-first orchestrator."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import tailor
from models import (
    CandidateSelection,
    EvidenceAssignment,
    EvidencePlan,
    HolisticReview,
    ImpactInference,
    JDProfile,
    JSONResume,
    ProjectRewriteItem,
    ProjectRewriteResponse,
    STARBullet,
    ScoredSkill,
    SelectionCandidate,
    TailoredSkills,
    TransferableSkill,
    TransferableSkillPlan,
    TRANSFERABLE_SKILL_GROUP,
    WorkRewriteItem,
    WorkRewriteResponse,
)
from pipeline_core import (
    ContractError,
    PipelineComponents,
    SelectedEvidence,
    assemble_scored,
    master_fact_index,
    project_evidence,
    technologies_in_experience,
    validate_evidence_plan,
    validate_skills,
    validate_transferable_skill_plan,
    validate_work_response,
    work_bullet_targets,
    work_evidence,
)


MASTER_DATA = {
    "basics": {
        "name": "Jordan Doe",
        "email": "jordan@example.com",
        "url": "https://jordan.dev",
        "summary": "This master-only summary must never be rendered.",
        "profiles": [{"network": "GitHub", "url": "https://github.com/jordan"}],
    },
    "work": [
        {
            "name": "Acme",
            "position": "Engineer",
            "url": "https://acme.example",
            "startDate": "2025-01",
            "endDate": "Present",
            "summary": "Built internal backend systems.",
            "highlights": [
                "Built an API for operations.",
                "Automated a manual workflow.",
                "Integrated PostgreSQL services.",
                "Collaborated with product partners.",
            ],
        },
        {
            "name": "Beta",
            "position": "Developer",
            "startDate": "2024-01",
            "endDate": "2024-12",
            "highlights": [
                "Built a JavaScript reporting interface.",
                "Added accessible reusable components.",
                "Integrated REST APIs.",
            ],
        },
        {
            "name": "Gamma",
            "position": "Analyst",
            "startDate": "2023-01",
            "endDate": "2023-12",
            "highlights": [
                "Developed Python data pipelines.",
                "Reduced reporting time by 40%.",
                "Documented shared data definitions.",
            ],
        },
    ],
    "education": [{"institution": "State U", "studyType": "BS", "endDate": "2026-12"}],
    "skills": [
        {"name": "Languages", "keywords": ["Java", "JavaScript", "Python"]},
        {"name": "Data", "keywords": ["PostgreSQL"]},
    ],
    "projects": [
        {
            "name": "Automation",
            "url": "https://github.com/jordan/automation",
            "technologies": ["Python"],
            "description": "Automated a grading workflow.",
            "highlights": [
                "Reduced grading from three hours to 15 minutes.",
                "Generated reports for more than 60 students.",
            ],
        },
        {
            "name": "Transit",
            "url": "https://github.com/jordan/transit",
            "technologies": ["React"],
            "description": "Tracked live transit data.",
            "highlights": [
                "Built a responsive transit interface.",
                "Integrated live REST API data.",
            ],
        },
    ],
}


def master() -> JSONResume:
    return JSONResume.model_validate(MASTER_DATA)


def selected_evidence(resume: JSONResume | None = None) -> SelectedEvidence:
    resume = resume or master()
    work = work_evidence(resume)
    for index, source in enumerate(work):
        source["selection_relevance"] = 100 - index
    projects = project_evidence(resume)
    for index, source in enumerate(projects):
        source["selection_relevance"] = 90 - index
    return SelectedEvidence(tuple(work[:3]), tuple(projects[:2]))


def evidence_plan(selected: SelectedEvidence | None = None) -> EvidencePlan:
    selected = selected or selected_evidence()
    assignments = []
    serial = 0
    for destination, count in work_bullet_targets(selected.work).items():
        destination_index = int(destination.removeprefix("work[").removesuffix("]"))
        for bullet_index in range(count):
            serial += 1
            source_id = f"{destination}.highlights[{bullet_index % 3}]"
            inferred = None
            if serial == 1:
                source_id = "projects[0].highlights[0]"
                inferred = ImpactInference(
                    inference_id="impact-1",
                    destination_work_id=destination,
                    source_fact_ids=[source_id],
                    inference_basis="A repetitive three-hour workflow supports a conservative automation gain.",
                    baseline="the manual three-hour workflow runtime",
                    final_claim="reduced processing time by 35% against the manual baseline",
                )
            assignments.append(
                EvidenceAssignment(
                    assignment_id=f"allocation-{serial}",
                    destination_work_id=destination,
                    source_fact_ids=[source_id],
                    matched_requirements=["software delivery"],
                    intended_accomplishment=(
                        f"Distinct accomplishment {destination_index}-{bullet_index}"
                    ),
                    inferred_impact=inferred,
                )
            )
    return EvidencePlan(assignments=assignments)


def star_for_assignment(assignment: EvidenceAssignment) -> STARBullet:
    inference = assignment.inferred_impact
    claim = (
        inference.final_claim if inference else "enabled a reliable downstream workflow"
    )
    text = "Automated a repetitive operations workflow with Python, " f"{claim}."
    return STARBullet(
        evidence_assignment_id=assignment.assignment_id,
        situation_task="A repetitive operations workflow required reliable processing.",
        action="Automated the workflow with Python and structured validation.",
        result=claim,
        text=text,
        relevance=90,
        source_ids=assignment.source_fact_ids,
        impact_type="inferred" if inference else "qualitative",
        impact_claim=claim,
    )


def work_item(
    source: dict,
    plan: EvidencePlan | None = None,
    text: str | None = None,
) -> WorkRewriteItem:
    plan = plan or evidence_plan()
    assignments = [
        assignment
        for assignment in plan.assignments
        if assignment.destination_work_id == source["source_id"]
    ]
    bullets = [star_for_assignment(assignment) for assignment in assignments]
    if text:
        bullets[0].text = text
    return WorkRewriteItem(
        source_id=source["source_id"],
        relevance=source.get("selection_relevance", 90),
        bullets=bullets,
    )


def project_item(source: dict) -> ProjectRewriteItem:
    facts = source["source_facts"]["highlights"]
    return ProjectRewriteItem(
        source_id=source["source_id"],
        description="Tailored source-local description.",
        relevance=source.get("selection_relevance", 80),
        bullets=[
            STARBullet(
                evidence_assignment_id=None,
                situation_task="The project required a useful end-to-end capability.",
                action=f"Implemented project capability {index + 1}.",
                result="Delivered a concrete downstream workflow.",
                text=f"Implemented project capability {index + 1}, enabling a concrete downstream workflow.",
                relevance=80 - index,
                source_ids=[facts[index]["source_id"]],
                impact_type="qualitative",
                impact_claim="enabled a concrete downstream workflow",
            )
            for index in range(2)
        ],
    )


def components(resume: JSONResume | None = None) -> PipelineComponents:
    resume = resume or master()
    selected = selected_evidence(resume)
    plan = evidence_plan(selected)
    return PipelineComponents(
        skills=TailoredSkills(
            skills=[ScoredSkill(name="Languages", keywords=["Python"], relevance=90)]
        ),
        work=tuple(work_item(source, plan) for source in selected.work),
        projects=tuple(project_item(source) for source in selected.projects),
        selected=selected,
        evidence_plan=plan,
    )


def pipeline() -> tailor.TailorPipeline:
    return tailor.TailorPipeline(
        model="gemini-3.1-flash-lite", call_interval=0, provider=MagicMock()
    )


def test_selector_requires_exact_count_and_orders_by_relevance(monkeypatch):
    instance = pipeline()
    evidence = work_evidence(master())

    def fake(*args, **kwargs):
        return CandidateSelection(
            candidates=[
                SelectionCandidate(
                    source_id=item["source_id"],
                    relevance=[70, 95, 80][index],
                    selected=True,
                )
                for index, item in enumerate(evidence)
            ]
        )

    monkeypatch.setattr(instance, "_call_once", fake)
    selected = instance._select("select_work", "work", "{}", evidence, 3)
    assert [item["source_id"] for item in selected] == ["work[1]", "work[2]", "work[0]"]
    assert work_bullet_targets(selected) == {"work[1]": 4, "work[2]": 3, "work[0]": 3}


def test_jd_text_is_fenced_and_reaches_the_parser_prompt():
    messages = pipeline()._messages(
        "jd_parse", jd_text="Hiring a Java backend engineer."
    )
    prompt = messages[-1]["content"]
    assert "<<<JOB_DESCRIPTION>>>" in prompt
    assert "Hiring a Java backend engineer." in prompt
    assert "<<<END_JOB_DESCRIPTION>>>" in prompt
    assert "untrusted data" in messages[0]["content"]


def test_cross_entry_assignment_is_accepted_but_unassigned_and_unknown_are_rejected():
    resume = master()
    selected = selected_evidence(resume)
    plan = evidence_plan(selected)
    facts = master_fact_index(resume)
    validate_evidence_plan(plan, selected.work, facts)
    response = WorkRewriteResponse(
        work=[work_item(source, plan) for source in selected.work]
    )
    validate_work_response(response, selected.work, plan, facts)

    bad = response.model_copy(deep=True)
    bad.work[0].bullets[0].source_ids = ["projects[1].highlights[0]"]
    with pytest.raises(ContractError, match="outside allocation"):
        validate_work_response(bad, selected.work, plan, facts)

    bad_plan = plan.model_copy(deep=True)
    bad_plan.assignments[0].source_fact_ids = ["projects[99].highlights[0]"]
    with pytest.raises(ContractError, match="nonexistent"):
        validate_evidence_plan(bad_plan, selected.work, facts)


def test_star_and_impact_contract_accepts_plausible_unplanned_inference():
    resume = master()
    selected = selected_evidence(resume)
    plan = evidence_plan(selected)
    facts = master_fact_index(resume)
    item = work_item(selected.work[1], plan)
    item.bullets[0].impact_type = "inferred"
    item.bullets[0].impact_claim = "increased throughput by 20%"
    item.bullets[0].text += " Increased throughput by 20%."
    validate_work_response(
        WorkRewriteResponse(
            work=[
                work_item(selected.work[0], plan),
                item,
                work_item(selected.work[2], plan),
            ]
        ),
        selected.work,
        plan,
        facts,
    )


def test_star_and_impact_contract_rejects_contradicting_declared_inference():
    resume = master()
    selected = selected_evidence(resume)
    plan = evidence_plan(selected)
    facts = master_fact_index(resume)
    item = work_item(selected.work[0], plan)
    item.bullets[0].impact_claim = "reduced processing time by 99%"
    item.bullets[0].text += " Reduced processing time by 99%."
    with pytest.raises(ContractError, match="contradicts"):
        validate_work_response(
            WorkRewriteResponse(
                work=[
                    item,
                    work_item(selected.work[1], plan),
                    work_item(selected.work[2], plan),
                ]
            ),
            selected.work,
            plan,
            facts,
        )


def test_protected_fields_and_summary_omission_survive_cross_entry_synthesis():
    resume = master()
    built = assemble_scored(resume, components(resume))
    assert built.basics.email == MASTER_DATA["basics"]["email"]
    assert built.basics.summary is None
    assert built.education[0].model_dump(mode="json") == resume.education[0].model_dump(
        mode="json"
    )
    assert built.work[0].name == "Acme" and built.work[0].position == "Engineer"
    assert built.projects[0].url == MASTER_DATA["projects"][0]["url"]
    assert built.projects[0].technologies == ["Python"]
    assert [len(item.highlights) for item in built.work] == [4, 3, 3]
    assert [len(item.highlights) for item in built.projects] == [2, 2]


def test_skills_are_limited_to_five_groups():
    resume = master()
    with pytest.raises(ValueError):
        TailoredSkills(
            skills=[
                ScoredSkill(name=f"G{i}", keywords=["Python"], relevance=50)
                for i in range(6)
            ]
        )


def test_transferable_skill_plan_accepts_jd_grounded_adjacent_skill():
    resume = master()
    facts = master_fact_index(resume)
    jd = JDProfile(
        role="Frontend Engineer",
        must_have_skills=["React"],
        nice_to_have_skills=["Figma"],
        keywords=[],
    )
    plan = TransferableSkillPlan(
        skills=[
            TransferableSkill(
                keyword="Figma",
                requirement_type="nice_to_have",
                category="tool",
                source_fact_ids=["work[1].highlights[1]"],
                transfer_basis="Accessible component design is adjacent UI evidence.",
                relevance=80,
            )
        ]
    )
    validate_transferable_skill_plan(plan, jd, resume, facts)

    skills = TailoredSkills(
        skills=[
            ScoredSkill(name="Languages", keywords=["Python"], relevance=90),
            ScoredSkill(
                name=TRANSFERABLE_SKILL_GROUP,
                keywords=["Figma"],
                relevance=80,
            ),
        ]
    )
    validate_skills(skills, resume, plan)
    bridged = replace(components(resume), skills=skills, transferable_skill_plan=plan)
    bridged.work[0].bullets[0].text += " Used Figma before implementation."
    bridged.work[0].bullets[0].action += " Designed the interface in Figma."
    assemble_scored(resume, bridged)


def test_transferable_skill_plan_rejects_existing_non_jd_and_non_skill_claims():
    resume = master()
    facts = master_fact_index(resume)
    jd = JDProfile(
        role="Engineer",
        must_have_skills=["Python"],
        nice_to_have_skills=["Figma", "CPA certification"],
        keywords=[],
    )

    def item(keyword: str) -> TransferableSkillPlan:
        return TransferableSkillPlan(
            skills=[
                TransferableSkill(
                    keyword=keyword,
                    requirement_type="nice_to_have",
                    category="domain_skill" if "CPA" in keyword else "tool",
                    source_fact_ids=["work[1].highlights[1]"],
                    transfer_basis="Claimed adjacent evidence.",
                    relevance=70,
                )
            ]
        )

    with pytest.raises(ContractError, match="already_in_master"):
        existing = item("Python")
        existing.skills[0].requirement_type = "must_have"
        validate_transferable_skill_plan(existing, jd, resume, facts)
    with pytest.raises(ContractError, match="absent_from_jd"):
        validate_transferable_skill_plan(item("Sketch"), jd, resume, facts)
    with pytest.raises(ContractError, match="non_skill_requirement"):
        validate_transferable_skill_plan(item("CPA certification"), jd, resume, facts)


def test_transferable_skills_require_exact_group_and_plan_order():
    resume = master()
    plan = TransferableSkillPlan(
        skills=[
            TransferableSkill(
                keyword="Figma",
                requirement_type="nice_to_have",
                category="tool",
                source_fact_ids=["work[1].highlights[1]"],
                transfer_basis="Adjacent interface work.",
                relevance=80,
            ),
            TransferableSkill(
                keyword="Sketch",
                requirement_type="nice_to_have",
                category="tool",
                source_fact_ids=["work[1].highlights[1]"],
                transfer_basis="Adjacent interface work.",
                relevance=70,
            ),
        ]
    )
    misplaced = TailoredSkills(
        skills=[ScoredSkill(name="Design", keywords=["Sketch", "Figma"], relevance=80)]
    )
    with pytest.raises(ContractError, match="misplaced_bridges"):
        validate_skills(misplaced, resume, plan)
    with pytest.raises(ContractError, match="absent_from_master"):
        validate_skills(
            TailoredSkills(
                skills=[
                    ScoredSkill(name="Cloud", keywords=["Kubernetes"], relevance=90)
                ]
            ),
            resume,
        )


def test_failure_diagnostic_contains_exact_stage_context(monkeypatch, tmp_path):
    instance = pipeline()
    monkeypatch.setattr(
        instance,
        "_parse_jd",
        MagicMock(
            side_effect=tailor.StageFailure(
                "jd_parse", 2, [], {"bad": True}, "role missing"
            )
        ),
    )
    with pytest.raises(tailor.StageFailure):
        instance.run(master(), "JD", tmp_path, no_pdf=True)
    diagnostic = json.loads((tmp_path / "diagnostic_report.json").read_text())
    assert diagnostic["stage"] == "jd_parse"
    assert diagnostic["parsed_response"] == {"bad": True}
    assert not (tmp_path / ".done").exists()
    assert not (tmp_path / "tailored.json").exists()


def test_stale_artifacts_are_cleared_before_failed_rerun(monkeypatch, tmp_path):
    for name in tailor.FINAL_ARTIFACTS:
        (tmp_path / name).write_text("stale")
    instance = pipeline()
    monkeypatch.setattr(
        instance,
        "_parse_jd",
        MagicMock(side_effect=tailor.StageFailure("jd_parse", 1, [], None, "bad")),
    )
    with pytest.raises(tailor.StageFailure):
        instance.run(master(), "JD", tmp_path, no_pdf=True)
    assert not (tmp_path / ".done").exists()
    assert not (tmp_path / "resume.pdf").exists()
    assert (tmp_path / "diagnostic_report.json").exists()


def test_text_done_marker_never_skips_pdf_run(tmp_path):
    out = tmp_path / "job"
    out.mkdir()
    (out / ".done").write_text("done")
    (out / "tailored.json").write_text("{}")
    assert tailor._done_satisfies(out, no_pdf=False) is False
    (out / ".done").write_text(json.dumps({"pdf": False}))
    assert tailor._done_satisfies(out, no_pdf=False) is False
    (out / "resume.pdf").write_bytes(b"pdf")
    (out / ".done").write_text(json.dumps({"pdf": True}))
    assert tailor._done_satisfies(out, no_pdf=False) is True


def test_batch_parser_preserves_zero_argument_command_defaults():
    args = tailor._build_batch_parser().parse_args([])
    assert args.master == Path("master.json")
    assert args.jd_dir == Path("jds")
    assert args.out_dir == Path("output")
    assert args.bridge_skills is False


def test_batch_parser_accepts_transferable_skill_opt_in():
    args = tailor._build_batch_parser().parse_args(["--bridge-skills"])
    assert args.bridge_skills is True


def _inference(**overrides) -> ImpactInference:
    fields = {
        "inference_id": "impact-1",
        "destination_work_id": "work[0]",
        "source_fact_ids": ["projects[0].highlights[0]"],
        "inference_basis": "A repetitive three-hour workflow supports a conservative gain.",
        "baseline": "the manual three-hour workflow runtime",
        "final_claim": "reduced processing time by 35% against the manual baseline",
    }
    fields.update(overrides)
    return ImpactInference(**fields)


def _plan_with(inference: ImpactInference, selected: SelectedEvidence) -> EvidencePlan:
    plan = evidence_plan(selected)
    plan.assignments[0].inferred_impact = inference
    return plan


@pytest.mark.parametrize(
    ("claim", "match"),
    [
        # A bare percentage is unfalsifiable: nothing says what it is measured
        # against, which is what made the reviewed output read as fabricated.
        ("reduced processing time by 35%", "baseline"),
        # False precision on a number that is, by construction, an estimate.
        (
            "reduced processing time by 36.5% against the manual baseline",
            "false precision",
        ),
        # Self-congratulatory absolutes carry no information.
        (
            "held query time at 37 ms against the SLA with zero tuning required",
            "qualifiers",
        ),
    ],
)
def test_inferred_metric_contract_rejects_undefendable_numbers(claim, match):
    resume = master()
    selected = selected_evidence(resume)
    plan = _plan_with(_inference(final_claim=claim), selected)
    with pytest.raises(ContractError, match=match):
        validate_evidence_plan(plan, selected.work, master_fact_index(resume))


@pytest.mark.parametrize(
    "claim",
    [
        "reduced processing time by 35% against the manual baseline",
        "cut the nightly export from 40 minutes to 12",
        "held worst-case query time at 37 ms, within the 50 ms budget",
        "resolved 18 of the 22 open reconciliation defects",
    ],
)
def test_inferred_metric_contract_accepts_baselined_round_numbers(claim):
    resume = master()
    selected = selected_evidence(resume)
    plan = _plan_with(_inference(final_claim=claim), selected)
    validate_evidence_plan(plan, selected.work, master_fact_index(resume))


def test_experience_technologies_surface_tools_named_only_in_bullets():
    resume = master()
    resume.work[0].highlights.append(
        "Shipped a Phoenix/LiveView dashboard backed by RabbitMQ and Node.js."
    )
    found = technologies_in_experience(resume)
    # Named in a bullet, absent from the skills groups: these are exactly the
    # keywords the QA report found hidden from ATS matching.
    assert {"Phoenix/LiveView", "RabbitMQ", "Node.js", "REST"} <= set(found)
    # Already in MASTER_SKILLS, so the skills stage does not need them back.
    assert "PostgreSQL" not in found
    # Ordinary prose must not be mined as a tool name.
    assert not {"Built", "Shipped", "Integrated", "Collaborated"} & set(found)


def test_skills_may_surface_a_technology_named_only_in_experience_text():
    resume = master()
    resume.work[0].highlights.append("Migrated queue traffic onto RabbitMQ.")
    skills = TailoredSkills(
        skills=[
            ScoredSkill(
                name="Languages",
                level=None,
                keywords=["Python", "Java"],
                relevance=90,
            ),
            ScoredSkill(
                name="Infrastructure",
                level=None,
                keywords=["RabbitMQ"],
                relevance=70,
            ),
        ]
    )
    validate_skills(skills, resume)

    unmined = TailoredSkills(
        skills=[
            ScoredSkill(
                name="Infrastructure", level=None, keywords=["Kafka"], relevance=70
            )
        ]
    )
    with pytest.raises(ContractError, match="absent_from_master"):
        validate_skills(unmined, resume)
