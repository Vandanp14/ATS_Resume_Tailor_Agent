"""Deterministic assembly and validation for the tailoring pipeline.

This module owns source identity, global evidence allocation, STAR completeness,
impact traceability, protected fields, and output cardinality. It deliberately
contains no provider, prompt, retry, CLI, or file-I/O code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Callable, Iterable, Mapping, Sequence, TypeVar

from models import (
    CandidateSelection,
    EvidenceAssignment,
    EvidencePlan,
    HolisticReview,
    JDProfile,
    JSONResume,
    ProjectRewriteItem,
    ProjectRewriteResponse,
    ScoredBullet,
    ScoredProject,
    ScoredSkill,
    ScoredWork,
    STARBullet,
    TailoredSkills,
    TransferableSkillPlan,
    TRANSFERABLE_SKILL_GROUP,
    TruthViolation,
    WorkRewriteItem,
    WorkRewriteResponse,
)
from render import ScoredResume


WORK_BULLET_COUNTS = (4, 3, 3)
PROJECT_BULLET_COUNT = 2
MAX_SKILL_GROUPS = 5
RESEARCH_THIN_JD_SIGNAL_THRESHOLD = 12

_NUMBER_RE = re.compile(r"(?<![A-Za-z])(?:\$?\d[\d,]*(?:\.\d+)?%?|\d+x)\b", re.I)
_HEDGED_METRIC_RE = re.compile(
    r"\b(?:about|approx(?:imately)?|around|estimated?|nearly|roughly)\b|"
    r"\d\s*(?:-|–|—|to)\s*\d",
    re.I,
)
_NON_SKILL_REQUIREMENT_RE = re.compile(
    r"\b(?:years?\s+of\s+experience|degree|certif(?:icate|ication|ied)|"
    r"licen[cs]e[ds]?|clearance|citizenship|citizen|work\s+authori[sz]ation|"
    r"visa|location|onsite|on-site|availability)\b",
    re.I,
)


class ContractError(ValueError):
    """A deterministic stage contract was violated."""


@dataclass(frozen=True)
class SelectedEvidence:
    work: tuple[dict, ...]
    projects: tuple[dict, ...]


@dataclass(frozen=True)
class PipelineComponents:
    skills: TailoredSkills | None
    work: tuple[WorkRewriteItem, ...]
    projects: tuple[ProjectRewriteItem, ...]
    selected: SelectedEvidence
    evidence_plan: EvidencePlan
    transferable_skill_plan: TransferableSkillPlan = field(
        default_factory=lambda: TransferableSkillPlan(skills=[])
    )


_T = TypeVar("_T")


def _fact(source_id: str, text: str | None, kind: str, entry_id: str) -> dict | None:
    if not text:
        return None
    return {
        "source_id": source_id,
        "text": text,
        "kind": kind,
        "entry_id": entry_id,
    }


def jd_signal_strength(jd: JDProfile) -> int:
    """Count of explicit requirement/keyword terms a parsed JD actually named."""
    return len(jd.must_have_skills) + len(jd.nice_to_have_skills) + len(jd.keywords)


def jd_signal_is_thin(
    jd: JDProfile, threshold: int = RESEARCH_THIN_JD_SIGNAL_THRESHOLD
) -> bool:
    """True when a JD names too few explicit requirements to tailor against well."""
    return jd_signal_strength(jd) <= threshold


def work_evidence(master: JSONResume) -> list[dict]:
    result: list[dict] = []
    for index, work in enumerate(master.work or []):
        source_id = f"work[{index}]"
        item = work.model_dump(mode="json", exclude_unset=True)
        summary = _fact(f"{source_id}.summary", work.summary, "summary", source_id)
        highlights = [
            _fact(
                f"{source_id}.highlights[{bullet_index}]",
                text,
                "highlight",
                source_id,
            )
            for bullet_index, text in enumerate(work.highlights or [])
        ]
        item.update(
            {
                "source_id": source_id,
                "source_facts": {
                    "summary": summary,
                    "highlights": [fact for fact in highlights if fact],
                },
            }
        )
        result.append(item)
    return result


def project_evidence(master: JSONResume) -> list[dict]:
    result: list[dict] = []
    for index, project in enumerate(master.projects or []):
        source_id = f"projects[{index}]"
        item = project.model_dump(mode="json", exclude_unset=True)
        description = _fact(
            f"{source_id}.description", project.description, "description", source_id
        )
        highlights = [
            _fact(
                f"{source_id}.highlights[{bullet_index}]",
                text,
                "highlight",
                source_id,
            )
            for bullet_index, text in enumerate(project.highlights or [])
        ]
        technologies = [
            _fact(
                f"{source_id}.technologies[{technology_index}]",
                text,
                "technology",
                source_id,
            )
            for technology_index, text in enumerate(project.technologies or [])
        ]
        skills = [
            _fact(
                f"{source_id}.skills[{skill_index}]",
                text,
                "skill",
                source_id,
            )
            for skill_index, text in enumerate(project.skills or [])
        ]
        item.update(
            {
                "source_id": source_id,
                "source_facts": {
                    "description": description,
                    "highlights": [fact for fact in highlights if fact],
                    "technologies": [fact for fact in technologies if fact],
                    "skills": [fact for fact in skills if fact],
                },
            }
        )
        result.append(item)
    return result


def skill_evidence(master: JSONResume) -> list[dict]:
    result: list[dict] = []
    for index, skill in enumerate(master.skills or []):
        source_id = f"skills[{index}]"
        facts = [
            _fact(
                f"{source_id}.keywords[{keyword_index}]",
                keyword,
                "skill",
                source_id,
            )
            for keyword_index, keyword in enumerate(skill.keywords or [])
        ]
        result.append(
            {
                **skill.model_dump(mode="json", exclude_unset=True),
                "source_id": source_id,
                "source_facts": [fact for fact in facts if fact],
            }
        )
    return result


def _iter_source_facts(value: object) -> Iterable[dict]:
    if isinstance(value, dict):
        if {"source_id", "text", "entry_id"} <= value.keys():
            yield value
            return
        for nested in value.values():
            yield from _iter_source_facts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_source_facts(nested)


def master_fact_index(master: JSONResume) -> dict[str, dict]:
    evidence = work_evidence(master) + project_evidence(master) + skill_evidence(master)
    facts: dict[str, dict] = {}
    for entry in evidence:
        for fact in _iter_source_facts(entry.get("source_facts")):
            source_id = fact["source_id"]
            if source_id in facts:
                raise ContractError(f"duplicate master fact source_id: {source_id}")
            facts[source_id] = fact
    return facts


def global_evidence_payload(master: JSONResume) -> dict[str, list[dict]]:
    return {
        "work": work_evidence(master),
        "projects": project_evidence(master),
        "skills": skill_evidence(master),
    }


def merge_unique_by_source(
    values: Iterable[_T], source_id: Callable[[_T], str]
) -> tuple[dict[str, _T], set[str]]:
    merged: dict[str, _T] = {}
    duplicates: set[str] = set()
    for value in values:
        identifier = source_id(value)
        if identifier in merged:
            duplicates.add(identifier)
        else:
            merged[identifier] = value
    for identifier in duplicates:
        merged.pop(identifier, None)
    return merged, duplicates


def validate_selection(
    response: CandidateSelection, expected_ids: Sequence[str]
) -> dict[str, object]:
    expected = set(expected_ids)
    returned, duplicates = merge_unique_by_source(
        response.candidates, lambda item: item.source_id
    )
    unknown = set(returned) - expected
    missing = expected - set(returned)
    if unknown or duplicates or missing:
        raise ContractError(
            "selection source IDs invalid: "
            f"unknown={sorted(unknown)}, duplicate={sorted(duplicates)}, "
            f"missing={sorted(missing)}"
        )
    return returned


def choose_selected(
    candidates: Mapping[str, object], evidence: Sequence[dict], cap: int
) -> list[dict]:
    order = {item["source_id"]: index for index, item in enumerate(evidence)}
    chosen = [candidate for candidate in candidates.values() if candidate.selected]
    chosen.sort(key=lambda item: (-item.relevance, order[item.source_id]))
    required = min(cap, len(evidence))
    if len(chosen) != required:
        raise ContractError(
            f"selector must choose exactly {required} of {len(evidence)} candidates; "
            f"received {len(chosen)}"
        )
    by_id = {item["source_id"]: item for item in evidence}
    return [
        {
            **by_id[candidate.source_id],
            "selection_relevance": candidate.relevance,
            "selection_matched_requirements": candidate.matched_requirements,
        }
        for candidate in chosen
    ]


def work_bullet_targets(sources: Sequence[dict]) -> dict[str, int]:
    return {
        source["source_id"]: WORK_BULLET_COUNTS[index]
        for index, source in enumerate(sources)
    }


def _duplicate_values(values: Sequence[str]) -> list[str]:
    return sorted({value for value in values if values.count(value) > 1})


def _validate_inference(assignment: EvidenceAssignment) -> None:
    inference = assignment.inferred_impact
    if inference is None:
        return
    if inference.destination_work_id != assignment.destination_work_id:
        raise ContractError(
            f"{assignment.assignment_id} inference destination contradicts assignment"
        )
    if set(inference.source_fact_ids) != set(assignment.source_fact_ids):
        raise ContractError(
            f"{assignment.assignment_id} inference provenance contradicts assignment"
        )
    if not _NUMBER_RE.search(inference.final_claim):
        raise ContractError(
            f"{assignment.assignment_id} inferred impact must contain an exact number"
        )
    if _HEDGED_METRIC_RE.search(inference.final_claim):
        raise ContractError(
            f"{assignment.assignment_id} inferred impact must be a point estimate "
            "without hedging or ranges"
        )


def validate_evidence_plan(
    plan: EvidencePlan,
    selected_work: Sequence[dict],
    fact_index: Mapping[str, dict],
) -> None:
    targets = work_bullet_targets(selected_work)
    destination_ids = set(targets)
    assignment_ids = [item.assignment_id for item in plan.assignments]
    inference_ids = [
        item.inferred_impact.inference_id
        for item in plan.assignments
        if item.inferred_impact is not None
    ]
    errors: list[str] = []
    if duplicates := _duplicate_values(assignment_ids):
        errors.append(f"duplicate assignment IDs={duplicates}")
    if duplicates := _duplicate_values(inference_ids):
        errors.append(f"duplicate inference IDs={duplicates}")

    counts = {destination_id: 0 for destination_id in destination_ids}
    for assignment in plan.assignments:
        if assignment.destination_work_id not in destination_ids:
            errors.append(
                f"{assignment.assignment_id} has unknown destination "
                f"{assignment.destination_work_id}"
            )
            continue
        counts[assignment.destination_work_id] += 1
        unknown = set(assignment.source_fact_ids) - set(fact_index)
        if unknown:
            errors.append(
                f"{assignment.assignment_id} has nonexistent fact IDs={sorted(unknown)}"
            )
        if duplicates := _duplicate_values(assignment.source_fact_ids):
            errors.append(f"{assignment.assignment_id} repeats fact IDs={duplicates}")
        try:
            _validate_inference(assignment)
        except ContractError as exc:
            errors.append(str(exc))
    for destination_id, target in targets.items():
        if counts[destination_id] != target:
            errors.append(
                f"{destination_id} requires {target} assignments; "
                f"received {counts[destination_id]}"
            )
    if errors:
        raise ContractError("evidence plan invalid: " + "; ".join(errors))


def _assignments_by_destination(
    plan: EvidencePlan,
) -> dict[str, dict[str, EvidenceAssignment]]:
    result: dict[str, dict[str, EvidenceAssignment]] = {}
    for assignment in plan.assignments:
        result.setdefault(assignment.destination_work_id, {})[
            assignment.assignment_id
        ] = assignment
    return result


def _number_tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in _NUMBER_RE.finditer(text)}


def validate_concise_bullet(
    original: ScoredBullet,
    replacement_text: str,
    *,
    max_words: int,
    fact_index: Mapping[str, dict],
    assignment: EvidenceAssignment | None,
    section: str,
) -> None:
    """Validate an emergency text-only rewrite against immutable evidence."""
    original_words = original.text.split()
    replacement_words = replacement_text.split()
    if len(replacement_words) >= len(original_words):
        raise ContractError(f"{section} concision is not strictly shorter")
    if len(replacement_words) > max_words:
        raise ContractError(f"{section} concision exceeds the {max_words}-word target")
    original_numbers = _number_tokens(original.text)
    replacement_numbers = _number_tokens(replacement_text)
    if replacement_numbers != original_numbers:
        raise ContractError(
            f"{section} concision changed numeric evidence: "
            f"expected={sorted(original_numbers)}, actual={sorted(replacement_numbers)}"
        )
    bullet = STARBullet(
        evidence_assignment_id=original.evidence_assignment_id,
        situation_task=original.situation_task or "Preserved from validated bullet.",
        action=original.action or "Preserved from validated bullet.",
        result=original.result or "Preserved from validated bullet.",
        text=replacement_text,
        relevance=original.relevance,
        source_ids=original.source_ids,
        impact_type=original.impact_type or "qualitative",
        impact_claim=original.impact_claim or "Preserved qualitative impact.",
    )
    _validate_star_bullet(bullet, fact_index, assignment, section)


def _validate_star_bullet(
    bullet: object,
    fact_index: Mapping[str, dict],
    assignment: EvidenceAssignment | None,
    section: str,
) -> None:
    unknown = set(bullet.source_ids) - set(fact_index)
    if unknown:
        raise ContractError(f"{section} has nonexistent provenance: {sorted(unknown)}")
    if duplicates := _duplicate_values(bullet.source_ids):
        raise ContractError(f"{section} repeats provenance: {duplicates}")

    if assignment is None:
        if bullet.evidence_assignment_id is not None:
            raise ContractError(f"{section} has an unassigned evidence allocation")
    else:
        invalid = set(bullet.source_ids) - set(assignment.source_fact_ids)
        if invalid:
            raise ContractError(
                f"{section} uses provenance outside allocation "
                f"{assignment.assignment_id}: {sorted(invalid)}"
            )
        inference = assignment.inferred_impact
        if inference is not None:
            if bullet.impact_type != "inferred":
                raise ContractError(
                    f"{section} must mark planned impact {inference.inference_id} inferred"
                )
            if bullet.impact_claim.casefold() != inference.final_claim.casefold():
                raise ContractError(
                    f"{section} inferred impact claim contradicts "
                    f"{inference.inference_id}"
                )
            missing_numbers = _number_tokens(inference.final_claim) - _number_tokens(
                bullet.text
            )
            if missing_numbers:
                raise ContractError(
                    f"{section} text omits inferred number(s): {sorted(missing_numbers)}"
                )

    if bullet.impact_type == "verified":
        source_text = " ".join(
            fact_index[source_id]["text"] for source_id in bullet.source_ids
        )
        if not _NUMBER_RE.search(source_text):
            raise ContractError(
                f"{section} marks impact verified but its source facts contain no number"
            )


def validate_work_item(
    item: WorkRewriteItem,
    source: dict,
    plan: EvidencePlan,
    fact_index: Mapping[str, dict],
    transferable_plan: TransferableSkillPlan | None = None,
) -> None:
    if item.source_id != source["source_id"]:
        raise ContractError(f"unknown work source_id: {item.source_id}")
    assignments = _assignments_by_destination(plan).get(item.source_id, {})
    if len(item.bullets) != len(assignments):
        raise ContractError(
            f"{item.source_id} requires {len(assignments)} bullets; "
            f"received {len(item.bullets)}"
        )
    used: list[str] = []
    for index, bullet in enumerate(item.bullets):
        assignment_id = bullet.evidence_assignment_id
        assignment = assignments.get(assignment_id or "")
        if assignment is None:
            raise ContractError(
                f"{item.source_id} bullet {index} references unassigned allocation "
                f"{assignment_id!r}"
            )
        used.append(assignment.assignment_id)
        _validate_star_bullet(
            bullet,
            fact_index,
            assignment,
            f"{item.source_id} bullet {index}",
        )
    if duplicates := _duplicate_values(used):
        raise ContractError(
            f"{item.source_id} reuses evidence assignments: {duplicates}"
        )
    unused = set(assignments) - set(used)
    if unused:
        raise ContractError(
            f"{item.source_id} omits evidence assignments: {sorted(unused)}"
        )


def _project_provenance(source: dict) -> set[str]:
    return {
        fact["source_id"] for fact in _iter_source_facts(source.get("source_facts"))
    }


def validate_project_item(
    item: ProjectRewriteItem,
    source: dict,
    fact_index: Mapping[str, dict],
    transferable_plan: TransferableSkillPlan | None = None,
) -> None:
    if item.source_id != source["source_id"]:
        raise ContractError(f"unknown project source_id: {item.source_id}")
    if len(item.bullets) != PROJECT_BULLET_COUNT:
        raise ContractError(
            f"{item.source_id} requires {PROJECT_BULLET_COUNT} bullets; "
            f"received {len(item.bullets)}"
        )
    valid = _project_provenance(source)
    for index, bullet in enumerate(item.bullets):
        invalid = set(bullet.source_ids) - valid
        if invalid:
            raise ContractError(
                f"{item.source_id} bullet {index} has non-local provenance: "
                f"{sorted(invalid)}"
            )
        _validate_star_bullet(
            bullet, fact_index, None, f"{item.source_id} bullet {index}"
        )


def validate_work_response(
    response: WorkRewriteResponse,
    sources: Sequence[dict],
    plan: EvidencePlan,
    fact_index: Mapping[str, dict],
    transferable_plan: TransferableSkillPlan | None = None,
) -> dict[str, WorkRewriteItem]:
    expected = {source["source_id"]: source for source in sources}
    returned, duplicates = merge_unique_by_source(
        response.work, lambda item: item.source_id
    )
    unknown = set(returned) - set(expected)
    missing = set(expected) - set(returned)
    errors: list[str] = []
    if unknown:
        errors.append(f"unknown={sorted(unknown)}")
    if duplicates:
        errors.append(f"duplicate={sorted(duplicates)}")
    if missing:
        errors.append(f"missing={sorted(missing)}")
    for source_id in set(returned) & set(expected):
        try:
            validate_work_item(
                returned[source_id],
                expected[source_id],
                plan,
                fact_index,
                transferable_plan,
            )
        except ContractError as exc:
            errors.append(str(exc))
    if errors:
        raise ContractError("work rewrite invalid: " + "; ".join(errors))
    return returned


def validate_project_response(
    response: ProjectRewriteResponse,
    sources: Sequence[dict],
    fact_index: Mapping[str, dict],
    transferable_plan: TransferableSkillPlan | None = None,
) -> dict[str, ProjectRewriteItem]:
    expected = {source["source_id"]: source for source in sources}
    returned, duplicates = merge_unique_by_source(
        response.projects, lambda item: item.source_id
    )
    unknown = set(returned) - set(expected)
    missing = set(expected) - set(returned)
    errors: list[str] = []
    if unknown:
        errors.append(f"unknown={sorted(unknown)}")
    if duplicates:
        errors.append(f"duplicate={sorted(duplicates)}")
    if missing:
        errors.append(f"missing={sorted(missing)}")
    for source_id in set(returned) & set(expected):
        try:
            validate_project_item(
                returned[source_id],
                expected[source_id],
                fact_index,
                transferable_plan,
            )
        except ContractError as exc:
            errors.append(str(exc))
    if errors:
        raise ContractError("project rewrite invalid: " + "; ".join(errors))
    return returned


def _normalized_skill(value: str) -> str:
    return " ".join(value.split()).casefold()


def validate_transferable_skill_plan(
    plan: TransferableSkillPlan,
    jd: JDProfile,
    master: JSONResume,
    fact_index: Mapping[str, dict],
) -> None:
    master_keywords = {
        _normalized_skill(keyword)
        for group in master.skills or []
        for keyword in group.keywords or []
    }
    jd_terms = {
        term
        for term in (
            *jd.must_have_skills,
            *jd.nice_to_have_skills,
            *(keyword.term for keyword in jd.keywords),
        )
    }
    normalized_jd = {_normalized_skill(term): term for term in jd_terms}
    returned = [_normalized_skill(item.keyword) for item in plan.skills]
    errors: list[str] = []
    if duplicates := _duplicate_values(returned):
        errors.append(f"duplicate={duplicates}")
    for item in plan.skills:
        normalized = _normalized_skill(item.keyword)
        if _NON_SKILL_REQUIREMENT_RE.search(item.keyword):
            errors.append(f"non_skill_requirement={item.keyword}")
        if normalized in master_keywords:
            errors.append(f"already_in_master={item.keyword}")
        canonical = normalized_jd.get(normalized)
        if canonical is None:
            errors.append(f"absent_from_jd={item.keyword}")
        elif item.keyword != canonical:
            errors.append(f"not_byte_exact_jd={item.keyword!r}; expected={canonical!r}")
        unknown_sources = set(item.source_fact_ids) - set(fact_index)
        if unknown_sources:
            errors.append(
                f"{item.keyword} nonexistent_sources={sorted(unknown_sources)}"
            )
        if duplicates := _duplicate_values(item.source_fact_ids):
            errors.append(f"{item.keyword} duplicate_sources={duplicates}")
        if (
            item.requirement_type == "must_have"
            and item.keyword not in jd.must_have_skills
        ):
            errors.append(f"{item.keyword} requirement_type_mismatch=must_have")
        if (
            item.requirement_type == "nice_to_have"
            and item.keyword not in jd.nice_to_have_skills
        ):
            errors.append(f"{item.keyword} requirement_type_mismatch=nice_to_have")
        if item.requirement_type == "weighted_keyword" and item.keyword not in {
            keyword.term for keyword in jd.keywords
        }:
            errors.append(f"{item.keyword} requirement_type_mismatch=weighted_keyword")
    if errors:
        raise ContractError("transferable skill plan invalid: " + "; ".join(errors))


def validate_skills(
    skills: TailoredSkills,
    master: JSONResume,
    transferable_plan: TransferableSkillPlan | None = None,
    jd_keywords: Iterable[str] | None = None,
) -> None:
    transferable_plan = transferable_plan or TransferableSkillPlan(skills=[])
    allowed = {
        keyword for group in master.skills or [] for keyword in group.keywords or []
    }
    if jd_keywords:
        allowed.update(jd_keywords)
    bridge_keywords = [item.keyword for item in transferable_plan.skills]
    bridge_group = [
        group for group in skills.skills if group.name == TRANSFERABLE_SKILL_GROUP
    ]
    returned = [keyword for group in skills.skills for keyword in group.keywords]
    unknown = sorted(set(returned) - allowed - set(bridge_keywords))
    duplicates = _duplicate_values(returned)
    empty_groups = [group.name for group in skills.skills if not group.keywords]
    too_many = len(skills.skills) > MAX_SKILL_GROUPS
    bridge_group_keywords = bridge_group[0].keywords if len(bridge_group) == 1 else []
    misplaced_bridges = sorted(
        keyword
        for group in skills.skills
        if group.name != TRANSFERABLE_SKILL_GROUP
        for keyword in group.keywords
        if keyword in bridge_keywords
    )
    unexpected_bridge_group = bool(bridge_group) and not bridge_keywords
    bridge_mismatch = bridge_group_keywords != bridge_keywords
    invalid_bridge_group_count = len(bridge_group) != (1 if bridge_keywords else 0)
    if (
        unknown
        or duplicates
        or empty_groups
        or too_many
        or misplaced_bridges
        or unexpected_bridge_group
        or bridge_mismatch
        or invalid_bridge_group_count
    ):
        raise ContractError(
            f"skills invalid: absent_from_master={unknown}, duplicates={duplicates}, "
            f"empty_groups={empty_groups}, max_groups={MAX_SKILL_GROUPS}, "
            f"misplaced_bridges={misplaced_bridges}, "
            f"bridge_group_mismatch={bridge_mismatch}, "
            f"bridge_group_count={len(bridge_group)}"
        )


def _protected_source_fields(source: dict, generated: set[str]) -> dict:
    internal = {key for key in source if key.startswith("selection_")}
    return {
        key: value
        for key, value in source.items()
        if key not in generated | {"source_id", "source_facts"} | internal
    }


def assemble_scored(
    master: JSONResume,
    components: PipelineComponents,
    jd_keywords: Iterable[str] | None = None,
) -> ScoredResume:
    if components.skills:
        validate_skills(
            components.skills,
            master,
            components.transferable_skill_plan,
            jd_keywords=jd_keywords,
        )
    facts = master_fact_index(master)
    validate_evidence_plan(components.evidence_plan, components.selected.work, facts)
    work_sources = {item["source_id"]: item for item in components.selected.work}
    project_sources = {item["source_id"]: item for item in components.selected.projects}

    work: list[ScoredWork] = []
    for rewrite in components.work:
        source = work_sources.get(rewrite.source_id)
        if source is None:
            raise ContractError(f"unknown work source_id: {rewrite.source_id}")
        validate_work_item(
            rewrite,
            source,
            components.evidence_plan,
            facts,
            components.transferable_skill_plan,
        )
        work.append(
            ScoredWork.model_validate(
                {
                    **_protected_source_fields(source, {"summary", "highlights"}),
                    "source_id": rewrite.source_id,
                    "summary": rewrite.summary,
                    "relevance": rewrite.relevance,
                    "highlights": [
                        ScoredBullet(
                            text=bullet.text,
                            relevance=bullet.relevance,
                            source_ids=bullet.source_ids,
                            evidence_assignment_id=bullet.evidence_assignment_id,
                            situation_task=bullet.situation_task,
                            action=bullet.action,
                            result=bullet.result,
                            impact_type=bullet.impact_type,
                            impact_claim=bullet.impact_claim,
                        )
                        for bullet in rewrite.bullets
                    ],
                }
            )
        )

    projects: list[ScoredProject] = []
    for rewrite in components.projects:
        source = project_sources.get(rewrite.source_id)
        if source is None:
            raise ContractError(f"unknown project source_id: {rewrite.source_id}")
        validate_project_item(
            rewrite, source, facts, components.transferable_skill_plan
        )
        projects.append(
            ScoredProject.model_validate(
                {
                    **_protected_source_fields(source, {"description", "highlights"}),
                    "source_id": rewrite.source_id,
                    "description": rewrite.description,
                    "highlights": [
                        ScoredBullet(
                            text=bullet.text,
                            relevance=bullet.relevance,
                            source_ids=bullet.source_ids,
                            evidence_assignment_id=bullet.evidence_assignment_id,
                            situation_task=bullet.situation_task,
                            action=bullet.action,
                            result=bullet.result,
                            impact_type=bullet.impact_type,
                            impact_claim=bullet.impact_claim,
                        )
                        for bullet in rewrite.bullets
                    ],
                    "relevance": rewrite.relevance,
                    "source_ids": [
                        source_id
                        for bullet in rewrite.bullets
                        for source_id in bullet.source_ids
                    ],
                }
            )
        )

    basics = None
    if master.basics:
        basics_payload = master.basics.model_dump(
            mode="json", exclude={"summary"}, exclude_unset=True
        )
        basics = type(master.basics).model_validate(basics_payload)
    payload = master.model_dump(mode="json", exclude_unset=True)
    payload.update(
        {
            "basics": basics,
            "work": work or None,
            "skills": list(components.skills.skills) if components.skills else None,
            "projects": projects or None,
        }
    )
    scored = ScoredResume.model_validate(payload)
    validate_scored_resume(master, scored, components.selected)
    return scored


def _basics_without_summary(basics: object) -> dict | None:
    if basics is None:
        return None
    return basics.model_dump(mode="json", exclude={"summary"})


def validate_scored_resume(
    master: JSONResume, resume: ScoredResume, selected: SelectedEvidence
) -> None:
    if _basics_without_summary(resume.basics) != _basics_without_summary(master.basics):
        raise ContractError("contact/profile fields changed")
    if resume.basics and resume.basics.summary is not None:
        raise ContractError("tailored output must omit basics.summary")
    if [item.model_dump(mode="json") for item in resume.education or []] != [
        item.model_dump(mode="json") for item in master.education or []
    ]:
        raise ContractError("education fields changed")

    expected_work_ids = [item["source_id"] for item in selected.work]
    actual_work_ids = [item.source_id for item in resume.work or []]
    if actual_work_ids != expected_work_ids:
        raise ContractError(
            f"assembled work entries changed: expected={expected_work_ids}, "
            f"actual={actual_work_ids}"
        )
    targets = work_bullet_targets(selected.work)
    work_sources = {item["source_id"]: item for item in selected.work}
    for item in resume.work or []:
        source = work_sources[item.source_id]
        for field in ("name", "position", "url", "startDate", "endDate"):
            if getattr(item, field) != source.get(field):
                raise ContractError(
                    f"protected work field changed: {item.source_id}.{field}"
                )
        if len(item.highlights or []) != targets[item.source_id]:
            raise ContractError(
                f"protected work bullet target changed: {item.source_id}"
            )

    expected_project_ids = [item["source_id"] for item in selected.projects]
    actual_project_ids = [item.source_id for item in resume.projects or []]
    if actual_project_ids != expected_project_ids:
        raise ContractError(
            f"assembled project entries changed: expected={expected_project_ids}, "
            f"actual={actual_project_ids}"
        )
    project_sources = {item["source_id"]: item for item in selected.projects}
    for item in resume.projects or []:
        source = project_sources[item.source_id]
        for field in ("name", "startDate", "endDate", "url", "technologies", "skills"):
            if getattr(item, field) != source.get(field):
                raise ContractError(
                    f"protected project field changed: {item.source_id}.{field}"
                )
        if len(item.highlights or []) != PROJECT_BULLET_COUNT:
            raise ContractError(
                f"protected project bullet target changed: {item.source_id}"
            )


def cross_entry_attributions(
    plan: EvidencePlan, fact_index: Mapping[str, dict]
) -> list[dict]:
    attributions: list[dict] = []
    for assignment in plan.assignments:
        cross_source_ids = [
            source_id
            for source_id in assignment.source_fact_ids
            if fact_index[source_id]["entry_id"] != assignment.destination_work_id
        ]
        if cross_source_ids:
            attributions.append(
                {
                    "assignment_id": assignment.assignment_id,
                    "destination_work_id": assignment.destination_work_id,
                    "source_fact_ids": cross_source_ids,
                    "intended_accomplishment": assignment.intended_accomplishment,
                }
            )
    return attributions


def inferred_metrics(plan: EvidencePlan) -> list[dict]:
    return [
        {
            "assignment_id": assignment.assignment_id,
            **assignment.inferred_impact.model_dump(mode="json"),
        }
        for assignment in plan.assignments
        if assignment.inferred_impact is not None
    ]


def transferable_skill_injections(
    plan: TransferableSkillPlan,
) -> list[dict]:
    return [
        {
            **item.model_dump(mode="json"),
            "final_group": TRANSFERABLE_SKILL_GROUP,
        }
        for item in plan.skills
    ]


def _dedupe_skill_keywords(skills: TailoredSkills) -> TailoredSkills:
    """Drop keywords repeated across groups, keeping the first occurrence."""
    seen: set[str] = set()
    groups: list[ScoredSkill] = []
    for group in skills.skills:
        kept: list[str] = []
        for keyword in group.keywords:
            if keyword not in seen:
                seen.add(keyword)
                kept.append(keyword)
        groups.append(group.model_copy(update={"keywords": kept}))
    return skills.model_copy(update={"skills": groups})


def apply_review_edits(
    review: HolisticReview,
    master: JSONResume,
    components: PipelineComponents,
    jd_keywords: Iterable[str] | None = None,
) -> tuple[PipelineComponents, list[str]]:
    """Apply each independently valid named edit; return rejection messages."""
    edits = review.section_edits
    if edits is None:
        return components, []
    updated = components
    rejected: list[str] = []
    facts = master_fact_index(master)
    if edits.skills is not None:
        try:
            deduped = _dedupe_skill_keywords(edits.skills)
            validate_skills(
                deduped,
                master,
                updated.transferable_skill_plan,
                jd_keywords=jd_keywords,
            )
            updated = replace(updated, skills=deduped)
        except ContractError as exc:
            rejected.append(f"skills edit rejected: {exc}")
    if edits.work is not None:
        try:
            mapped = validate_work_response(
                edits.work,
                updated.selected.work,
                updated.evidence_plan,
                facts,
                updated.transferable_skill_plan,
            )
            ordered = tuple(mapped[item["source_id"]] for item in updated.selected.work)
            updated = replace(updated, work=ordered)
        except ContractError as exc:
            rejected.append(f"work edit rejected: {exc}")
    if edits.projects is not None:
        try:
            mapped = validate_project_response(
                edits.projects,
                updated.selected.projects,
                facts,
                updated.transferable_skill_plan,
            )
            ordered = tuple(
                mapped[item["source_id"]] for item in updated.selected.projects
            )
            updated = replace(updated, projects=ordered)
        except ContractError as exc:
            rejected.append(f"projects edit rejected: {exc}")
    return updated, rejected


def partition_review_truth_violations(
    review: HolisticReview, final_resume: ScoredResume
) -> tuple[list[TruthViolation], list[TruthViolation]]:
    """Separate reviewer findings that remain after valid section edits.

    The review contract requires ``claim`` to quote the unsupported claim. A
    finding is resolved only when that quoted text no longer occurs in the
    post-edit section. This prevents an accepted corrective edit from leaving a
    stale violation that incorrectly blocks publication.
    """

    payload = final_resume.model_dump(mode="json", exclude_none=True)
    aliases = {
        "project": "projects",
        "experience": "work",
        "employment": "work",
        "skill": "skills",
    }

    def strings(value: object) -> Iterable[str]:
        if isinstance(value, str):
            yield value
        elif isinstance(value, Mapping):
            for nested in value.values():
                yield from strings(nested)
        elif isinstance(value, Sequence):
            for nested in value:
                yield from strings(nested)

    unresolved: list[TruthViolation] = []
    resolved: list[TruthViolation] = []
    for violation in review.truth_violations:
        section = aliases.get(
            violation.section.casefold(), violation.section.casefold()
        )
        section_payload = payload.get(section, payload)
        claim = " ".join(violation.claim.split()).casefold()
        remains = any(
            claim in " ".join(value.split()).casefold()
            for value in strings(section_payload)
        )
        (unresolved if remains else resolved).append(violation)
    return unresolved, resolved


BANNED_OPENER_PHRASES = (
    "responsible for",
    "worked on",
    "helped with",
    "participated in",
)
RESTRICTED_VERBS = (
    "led",
    "owned",
    "architected",
    "optimized",
    "scaled",
    "automated",
    "streamlined",
    "launched",
    "deployed",
    "transformed",
    "drove",
    "spearheaded",
)
REPETITION_LIMIT = 3


def scan_bullet_style(final_resume: ScoredResume) -> list[str]:
    """Return warn-only bullet-style findings (never blocks the run).

    Mirrors the bullet guide's writing rules: banned weak openers, restricted
    ownership/impact verbs, and three or more bullets opening with the same
    verb. Findings are advisory; the holistic reviewer owns semantic judgment.
    """

    findings: list[str] = []

    def first_word(text: str) -> str:
        return text.split(maxsplit=1)[0].rstrip(",:;.?!()").casefold()

    def scan_section(
        bullets: Iterable[str], section: str, owner: Callable[[int], str]
    ) -> None:
        opener_counts: dict[str, int] = {}
        for index, text in enumerate(bullets):
            lowered = text.casefold()
            for phrase in BANNED_OPENER_PHRASES:
                if re.search(rf"^\s*{re.escape(phrase)}\b", lowered):
                    findings.append(
                        f"{owner(index)} opens with {phrase!r}: {text[:90]!r}"
                    )
                    break
            else:
                word = first_word(text)
                if not word:
                    continue
                opener_counts[word] = opener_counts.get(word, 0) + 1
                if word in RESTRICTED_VERBS:
                    findings.append(
                        f"{owner(index)} opens with restricted verb "
                        f"{word!r} (needs supporting evidence): {text[:90]!r}"
                    )
        for word, count in opener_counts.items():
            if count >= REPETITION_LIMIT:
                findings.append(
                    f"{section} opens {count} bullets with the same verb "
                    f"{word!r}; vary the openers"
                )

    for index, item in enumerate(final_resume.work or []):
        scan_section(
            (bullet.text for bullet in item.highlights or []),
            f"Work[{index}]",
            lambda i, n=index: f"Work[{n}] bullet {i + 1}",
        )
    for index, item in enumerate(final_resume.projects or []):
        scan_section(
            (bullet.text for bullet in item.highlights or []),
            f"Projects[{index}]",
            lambda i, n=index: f"Projects[{n}] bullet {i + 1}",
        )
    return findings
