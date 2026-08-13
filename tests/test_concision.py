"""Emergency concision activates only at deterministic fit exhaustion."""

from types import SimpleNamespace

import pytest

from models import (
    BulletConcision,
    ConcisionAudit,
    ConcisionAuditItem,
    ScoredBullet,
    ScoredProject,
    ScoredWork,
)
from pipeline_core import ContractError
from render import ScoredResume
from resume_tailor.pipeline import _ConcisionController
from resume_tailor.progress import ProgressTracker


class _Pipeline:
    allow_fit_recovery = False

    def __init__(self, replacement: str):
        self.replacement = replacement
        self.tracker = ProgressTracker()
        self.calls = []

    def _simple_stage(
        self, template, response_model, selected_ids=(), validator=None, **context
    ):
        self.calls.append((template, list(selected_ids), context))
        if response_model is BulletConcision:
            result = BulletConcision(text=self.replacement)
        elif response_model is ConcisionAudit:
            result = ConcisionAudit(
                items=[
                    ConcisionAuditItem(
                        candidate_id=item,
                        supported=True,
                        reason="Meaning and evidence are preserved.",
                    )
                    for item in selected_ids
                ]
            )
        else:  # pragma: no cover - test double contract
            raise AssertionError(response_model)
        if validator:
            validator(result)
        return result


def _resume() -> ScoredResume:
    return ScoredResume(
        work=[
            ScoredWork(
                name="Acme",
                relevance=50,
                highlights=[
                    ScoredBullet(
                        text=(
                            "Built Python services for internal reporting teams and "
                            "improved processing throughput by 40% across workflows."
                        ),
                        relevance=10,
                        source_ids=["work-fact"],
                        impact_type="verified",
                        impact_claim="improved processing throughput by 40%",
                    )
                ],
            )
        ],
        projects=[
            ScoredProject(
                name="Reports",
                relevance=50,
                highlights=[
                    ScoredBullet(
                        text=(
                            "Built Python reporting services for multiple internal "
                            "operations teams and reduced recurring processing time "
                            "by 40% across critical monthly workflows."
                        ),
                        relevance=10,
                        source_ids=["project-fact"],
                        impact_type="verified",
                        impact_claim="reduced recurring processing time by 40%",
                    )
                ],
            )
        ],
    )


def _facts():
    return {
        "work-fact": {"text": "Improved processing throughput by 40%."},
        "project-fact": {"text": "Reduced recurring processing time by 40%."},
    }


def test_concision_chooses_longest_bullet_for_relevance_tie_and_audits():
    pipeline = _Pipeline(
        "Built Python reporting services, reducing recurring processing time 40% "
        "across critical monthly workflows."
    )
    controller = _ConcisionController(
        pipeline, _facts(), SimpleNamespace(assignments=[])
    )
    resume = _resume()

    action = controller(resume, 2, ())
    controller.audit()

    assert "projects:0:0" in action
    assert resume.work[0].highlights[0].text.startswith("Built Python services")
    assert resume.projects[0].highlights[0].text == pipeline.replacement
    assert [call[0] for call in pipeline.calls] == [
        "concise_bullet",
        "audit_concision",
    ]
    assert controller.log[0]["original_words"] > controller.log[0]["final_words"]


def test_concision_rejects_changed_numeric_evidence():
    pipeline = _Pipeline(
        "Built Python reporting services for critical monthly workflows."
    )
    controller = _ConcisionController(
        pipeline, _facts(), SimpleNamespace(assignments=[])
    )

    with pytest.raises(ContractError, match="changed numeric evidence"):
        controller(_resume(), 2, ())
