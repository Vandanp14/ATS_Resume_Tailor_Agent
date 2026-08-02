"""Evidence extraction and provenance validation facade."""

from pipeline_core import (
    ContractError,
    SelectedEvidence,
    choose_selected,
    global_evidence_payload,
    master_fact_index,
    project_evidence,
    validate_evidence_plan,
    validate_project_item,
    validate_skills,
    validate_transferable_skill_plan,
    validate_work_item,
    work_bullet_targets,
    work_evidence,
)

__all__ = [
    "ContractError",
    "SelectedEvidence",
    "choose_selected",
    "global_evidence_payload",
    "master_fact_index",
    "project_evidence",
    "validate_evidence_plan",
    "validate_project_item",
    "validate_skills",
    "validate_transferable_skill_plan",
    "validate_work_item",
    "work_bullet_targets",
    "work_evidence",
]
