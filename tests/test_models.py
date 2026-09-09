"""Schema tests for the compact work-first pipeline contracts."""

import pytest
from pydantic import ValidationError

from models import (
    EvidencePlan,
    HolisticReview,
    ProjectRewriteResponse,
    SectionEdits,
    STARBullet,
    TailoredSkills,
    TransferableSkillPlan,
    WorkRewriteResponse,
)


def test_work_generation_schema_excludes_protected_identity_fields():
    properties = WorkRewriteResponse.model_json_schema()["$defs"]["WorkRewriteItem"][
        "properties"
    ]
    assert set(properties) == {"source_id", "summary", "relevance", "bullets"}
    assert not {"name", "position", "url", "startDate", "endDate"} & set(properties)


def test_star_bullet_requires_complete_star_and_impact_metadata():
    required = set(STARBullet.model_json_schema()["required"])
    assert required == {
        "evidence_assignment_id",
        "situation_task",
        "action",
        "result",
        "text",
        "relevance",
        "source_ids",
        "impact_type",
        "impact_claim",
    }
    with pytest.raises(ValidationError):
        STARBullet.model_validate(
            {
                "evidence_assignment_id": "a1",
                "text": "Incomplete bullet",
                "relevance": 90,
                "source_ids": ["work[0].highlights[0]"],
            }
        )


def test_evidence_plan_schema_carries_traceable_inference():
    plan = EvidencePlan.model_validate(
        {
            "assignments": [
                {
                    "assignment_id": "a1",
                    "destination_work_id": "work[0]",
                    "source_fact_ids": ["projects[0].highlights[0]"],
                    "matched_requirements": ["automation"],
                    "intended_accomplishment": "Show automation impact.",
                    "inferred_impact": {
                        "inference_id": "i1",
                        "destination_work_id": "work[0]",
                        "source_fact_ids": ["projects[0].highlights[0]"],
                        "inference_basis": "Manual workflow was repetitive.",
                        "baseline": "the manual workflow runtime",
                        "final_claim": "reduced processing time by 35% against the manual baseline",
                    },
                }
            ]
        }
    )
    assert plan.assignments[0].inferred_impact.baseline
    assert plan.assignments[0].inferred_impact.final_claim.endswith("baseline")


def test_project_generation_schema_excludes_protected_fields():
    properties = ProjectRewriteResponse.model_json_schema()["$defs"][
        "ProjectRewriteItem"
    ]["properties"]
    assert set(properties) == {"source_id", "description", "relevance", "bullets"}
    assert not {"name", "url", "startDate", "endDate", "technologies"} & set(properties)


def test_skill_groups_are_schema_limited_to_five():
    with pytest.raises(ValidationError):
        TailoredSkills.model_validate(
            {
                "skills": [
                    {"name": f"G{i}", "keywords": ["Python"], "relevance": 90}
                    for i in range(6)
                ]
            }
        )


def test_transferable_skill_plan_is_strict_and_limited_to_four():
    payload = {
        "skills": [
            {
                "keyword": f"Tool {index}",
                "requirement_type": "nice_to_have",
                "category": "tool",
                "source_fact_ids": ["work[0].highlights[0]"],
                "transfer_basis": "Adjacent demonstrated workflow.",
                "relevance": 70,
            }
            for index in range(5)
        ]
    }
    with pytest.raises(ValidationError):
        TransferableSkillPlan.model_validate(payload)

    payload["skills"] = payload["skills"][:1]
    payload["skills"][0]["unexpected"] = True
    with pytest.raises(ValidationError):
        TransferableSkillPlan.model_validate(payload)


def test_review_edits_have_no_summary_field():
    assert "summary" not in SectionEdits.model_json_schema()["properties"]
    with pytest.raises(ValidationError):
        SectionEdits.model_validate({"summary": {"summary": "Visible summary"}})


def test_holistic_review_is_the_public_report_contract():
    review = HolisticReview(
        coverage_pct=90,
        missing_must_haves=[],
        weak_sections=[],
        truth_violations=[],
        recommendations=["Lead with backend evidence."],
    )
    assert review.coverage_pct == 90
