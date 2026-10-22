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
    RequirementProxyPlan,
    ScoredBullet,
    ScoredProject,
    ScoredSkill,
    ScoredWork,
    STARBullet,
    TailoredSkills,
    TransferableSkill,
    TransferableSkillPlan,
    TRANSFERABLE_SKILL_GROUP,
    TruthViolation,
    WorkRewriteItem,
    WorkRewriteResponse,
)
from keyword_coverage import (
    assignment_entry_ids,
    candidate_requirement_cover,
    find_terms,
    mentions,
    normalize_term,
    title_matches,
)
from render import ScoredResume


# Work bullets on one page, shared by evidence strength (see work_bullet_targets).
WORK_BULLET_BUDGET = 10
MIN_WORK_BULLETS = 2
MAX_WORK_BULLETS = 5
# An entry may borrow facts from projects or other roles, so even a thin entry
# can carry this many bullets.
THIN_ENTRY_BULLET_CAP = 3
PROJECT_BULLET_COUNT = 2
MAX_SKILL_GROUPS = 5
RESEARCH_THIN_JD_SIGNAL_THRESHOLD = 12

_NUMBER_RE = re.compile(r"(?<![A-Za-z])(?:\$?\d[\d,]*(?:\.\d+)?%?|\d+x)\b", re.I)
_BASELINE_RE = re.compile(
    r"\b(?:of|out of|from|to|against|within|under|over|per|versus|vs\.?|"
    r"baseline|budget|threshold|target|sla|quota|cap|limit)\b",
    re.I,
)
_DECIMAL_METRIC_RE = re.compile(r"(?<![A-Za-z])\d[\d,]*\.\d")
ABSOLUTE_QUALIFIERS = (
    "zero ",
    "no tuning required",
    "no issues",
    "never fails",
    "flawless",
    "seamless",
    "effortless",
    "100% uptime",
    "fully automated end-to-end",
)
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
    # JD technologies the master never states; no bullet may claim them.
    forbidden_terms: tuple[str, ...] = ()


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


def review_master(
    master: JSONResume,
    selected: SelectedEvidence,
    cited_fact_ids: Iterable[str] = (),
) -> JSONResume:
    """The master the final reviewer needs: selected and cited entries only.

    Unselected roles and projects only bloat the review prompt, but a bullet
    may cite a fact from an unselected entry (cross-entry evidence), so every
    cited entry stays. Other sections are kept whole.
    """
    keep = {item["source_id"] for item in (*selected.work, *selected.projects)}
    keep.update(fact_id.split(".", 1)[0] for fact_id in cited_fact_ids)
    return master.model_copy(
        update={
            "work": [
                item
                for index, item in enumerate(master.work or [])
                if f"work[{index}]" in keep
            ]
            or None,
            "projects": [
                item
                for index, item in enumerate(master.projects or [])
                if f"projects[{index}]" in keep
            ]
            or None,
        }
    )


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


# A technology named only inside a bullet clause is invisible to keyword
# matching, so the skills stage is allowed to surface it. Mining free text for
# tool names is only safe with a tight shape filter: these patterns match names
# that carry an internal capital, a digit, a dot, a slash, or a symbol
# (PostgreSQL, LiveView, RabbitMQ, FastAPI, Node.js, CI/CD, gRPC, S3, C#), which
# ordinary prose words and sentence-initial verbs do not.
_TECH_SHAPE_RE = re.compile(
    r"""
    (?<![\w/.#+-])
    (?:
        [A-Za-z][a-z0-9]*[A-Z][A-Za-z0-9]*        # PostgreSQL, LiveView, gRPC
      | [A-Z][A-Za-z0-9]*\.[A-Za-z][A-Za-z0-9.]* # Node.js, Vue.js
      | [A-Z]{2,}[0-9]*                           # SQL, AWS, S3, K8S
      | [A-Z][A-Za-z]+\+\+                       # C++
      | [A-Z][A-Za-z]*\#                          # C#
      | [A-Z][A-Za-z]+/[A-Z][A-Za-z]+             # CI/CD, Phoenix/LiveView
    )
    (?![\w#+-])
    """,
    re.X,
)
# Shape-matching tokens that are prose or document furniture, not tools.
_TECH_SHAPE_STOPWORDS = frozenset(
    {
        "A",
        "AN",
        "AND",
        "AS",
        "AT",
        "BY",
        "FOR",
        "I",
        "IN",
        "IT",
        "OF",
        "ON",
        "OR",
        "STAR",
        "THE",
        # Resume furniture that matches the tech shape but names no tool.
        "GPA",
        "KPI",
        "KPIS",
        "RSVP",
        "CEO",
        "CTO",
        "COO",
        "VP",
        "HR",
        "NYC",
        "USA",
        "USD",
        "PHD",
        "BS",
        "MS",
        "BSC",
        "MSC",
        "AM",
        "PM",
        "TO",
        "US",
        "VS",
        "WITH",
    }
)


def technologies_in_experience(master: JSONResume) -> list[str]:
    """Return technology names that appear in experience/project text.

    The skills section is scored on keyword completeness, but a tool mentioned
    only inside a work highlight lives nowhere the skills stage may draw from.
    This widens that source: structured project technologies first, then names
    mined from free text by shape.
    """

    found: dict[str, None] = {}

    def add(value: str | None) -> None:
        if value and (cleaned := value.strip(" .,;:()[]")):
            found.setdefault(cleaned, None)

    def mine(text: str | None) -> None:
        for match in _TECH_SHAPE_RE.finditer(text or ""):
            token = match.group(0)
            if token.upper() not in _TECH_SHAPE_STOPWORDS:
                add(token)

    for project in master.projects or []:
        for value in (project.technologies or []) + (project.skills or []):
            add(value)
        mine(project.description)
        for highlight in project.highlights or []:
            mine(highlight)
    for role in master.work or []:
        mine(role.summary)
        for highlight in role.highlights or []:
            mine(highlight)

    already_listed = {
        keyword.casefold()
        for group in master.skills or []
        for keyword in group.keywords or []
    }
    return [name for name in found if name.casefold() not in already_listed]


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


def master_fact_index(
    master: JSONResume, *, evidence: Mapping[str, list[dict]] | None = None
) -> dict[str, dict]:
    if evidence is None:
        evidence = global_evidence_payload(master)
    facts: dict[str, dict] = {}
    for entries in evidence.values():
        for entry in entries:
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


SELECTED_FLAG_BONUS = 15
TITLE_MATCH_BONUS = 20
COVERAGE_GAIN_SCALE = 80


_CURRENT_END_DATES = frozenset({"", "present", "current", "now"})


def is_current(entry: Mapping) -> bool:
    """True for a role with no end date or an end date like "Present"."""
    end = entry.get("endDate")
    return end is None or str(end).strip().casefold() in _CURRENT_END_DATES


def _date_key(value: object) -> str:
    """Sortable YYYY-MM key; "2024" sorts as "2024-00", missing sorts first."""
    text = str(value or "").strip()
    if not text[:4].isdigit():
        return ""
    month = text[5:7] if len(text) >= 7 and text[5:7].isdigit() else "00"
    return f"{text[:4]}-{month}"


def _recency(entry: Mapping) -> tuple[int, str, str]:
    return (
        1 if is_current(entry) else 0,
        _date_key(entry.get("endDate")),
        _date_key(entry.get("startDate")),
    )


def current_role_id(evidence: Sequence[dict]) -> str | None:
    """The current role, else the most recently ended one."""
    if not evidence:
        return None
    return max(evidence, key=_recency)["source_id"]


def chronological(entries: Sequence[dict]) -> list[dict]:
    """Current roles first, then by end date and start date, newest first."""
    return sorted(entries, key=_recency, reverse=True)


def choose_selected(
    candidates: Mapping[str, object],
    evidence: Sequence[dict],
    cap: int,
    requirements: Sequence[dict] | None = None,
    fact_index: Mapping[str, dict] | None = None,
    jd: JDProfile | None = None,
    pin_current: bool = False,
) -> list[dict]:
    """Pick the selected entries.

    Without a requirement map this enforces the model's own ``selected`` flags.
    With one, the set is chosen in code: a greedy pass that scores each
    candidate by model relevance, the model's selected flag, a title match
    against the target role, and the weighted JD requirements it would newly
    cover (directly or through validated proxy evidence). Complementary
    coverage therefore beats several entries proving the same requirement.

    ``pin_current`` (work only) always keeps the current role and returns the
    set in reverse-chronological order: recruiters read the newest role first.
    """

    order = {item["source_id"]: index for index, item in enumerate(evidence)}
    by_id = {item["source_id"]: item for item in evidence}
    required = min(cap, len(evidence))
    pinned = current_role_id(evidence) if pin_current else None
    if requirements is None:
        chosen = [candidate for candidate in candidates.values() if candidate.selected]
        chosen.sort(key=lambda item: (-item.relevance, order[item.source_id]))
        if len(chosen) != required:
            raise ContractError(
                f"selector must choose exactly {required} of {len(evidence)} "
                f"candidates; received {len(chosen)}"
            )
        if pinned is not None and pinned in candidates:
            if all(item.source_id != pinned for item in chosen):
                chosen[-1] = candidates[pinned]
            rank = {item["source_id"]: position for position, item in enumerate(chronological(evidence))}
            chosen.sort(key=lambda item: rank[item.source_id])
        return [
            {
                **by_id[candidate.source_id],
                "selection_relevance": candidate.relevance,
                "selection_matched_requirements": candidate.matched_requirements,
            }
            for candidate in chosen
        ]

    importance = {item["id"]: item.get("importance", item["weight"]) for item in requirements}
    total = sum(importance.values()) or 1
    deterministic = candidate_requirement_cover(requirements, fact_index or {})
    cover: dict[str, set[str]] = {}
    base: dict[str, float] = {}
    title_bonus: dict[str, int] = {}
    for source_id, candidate in candidates.items():
        cover[source_id] = deterministic.get(source_id, set()) | (
            set(candidate.covered_requirement_ids) & importance.keys()
        )
        title_bonus[source_id] = (
            TITLE_MATCH_BONUS
            if jd is not None and title_matches(by_id[source_id].get("position"), jd)
            else 0
        )
        base[source_id] = (
            candidate.relevance
            + (SELECTED_FLAG_BONUS if candidate.selected else 0)
            + title_bonus[source_id]
        )
    covered: set[str] = set()
    remaining = set(candidates)
    picked: list[str] = []
    if pinned is not None and pinned in remaining and required:
        picked.append(pinned)
        covered |= cover[pinned]
        remaining.discard(pinned)
    while remaining and len(picked) < required:

        def score(source_id: str) -> tuple[float, int]:
            gain = sum(importance[rid] for rid in cover[source_id] - covered)
            return (
                base[source_id] + COVERAGE_GAIN_SCALE * gain / total,
                -order[source_id],
            )

        best = max(remaining, key=score)
        picked.append(best)
        covered |= cover[best]
        remaining.discard(best)
    if len(picked) != required:
        raise ContractError(
            f"selector returned {len(candidates)} candidates; {required} required"
        )
    if pinned is not None:
        rank = {item["source_id"]: position for position, item in enumerate(chronological(evidence))}
        picked.sort(key=lambda source_id: rank[source_id])
    else:
        picked.sort(
            key=lambda source_id: (
                -(candidates[source_id].relevance + title_bonus[source_id]),
                order[source_id],
            )
        )
    return [
        {
            **by_id[source_id],
            "selection_relevance": candidates[source_id].relevance,
            "selection_matched_requirements": candidates[source_id].matched_requirements,
            "selection_covered_requirement_ids": sorted(cover[source_id]),
            "selection_title_match": bool(title_bonus[source_id]),
        }
        for source_id in picked
    ]


def _bullet_strength(source: Mapping) -> float:
    return float(source.get("selection_relevance") or 0) + 10 * len(
        source.get("selection_covered_requirement_ids") or []
    )


def _bullet_cap(source: Mapping) -> int:
    facts = source.get("source_facts") or {}
    highlights = len(facts.get("highlights") or []) if isinstance(facts, Mapping) else 0
    return min(MAX_WORK_BULLETS, max(highlights, THIN_ENTRY_BULLET_CAP))


def work_bullet_targets(sources: Sequence[dict]) -> dict[str, int]:
    """Bullets per selected work entry, by evidence strength rather than rank.

    Every entry starts at its floor; the rest of the budget goes one bullet at
    a time to the entry with the most strength per bullet already given. The
    current role then gets at least as many bullets as any other entry.
    """

    ids = [source["source_id"] for source in sources]
    # A college run annotates its larger budget on every selected entry, so all
    # callers that only see the entries agree on the same targets.
    budget = next(
        (int(source["selection_bullet_budget"]) for source in sources if source.get("selection_bullet_budget")),
        WORK_BULLET_BUDGET,
    )
    caps = {source["source_id"]: _bullet_cap(source) for source in sources}
    strength = {
        source["source_id"]: max(_bullet_strength(source), 1.0) for source in sources
    }
    counts = {source_id: min(MIN_WORK_BULLETS, caps[source_id]) for source_id in ids}
    while sum(counts.values()) < budget:
        open_ids = [source_id for source_id in ids if counts[source_id] < caps[source_id]]
        if not open_ids:
            break
        best = max(
            open_ids,
            key=lambda source_id: (
                strength[source_id] / counts[source_id],
                -ids.index(source_id),
            ),
        )
        counts[best] += 1
    for source in sources:
        if not is_current(source):
            continue
        current = source["source_id"]
        while True:
            others = [source_id for source_id in ids if source_id != current]
            if not others or counts[current] >= caps[current]:
                break
            largest = max(others, key=lambda source_id: counts[source_id])
            if counts[current] >= counts[largest]:
                break
            counts[largest] -= 1
            counts[current] += 1
        break
    return counts


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
    if not _BASELINE_RE.search(inference.final_claim):
        raise ContractError(
            f"{assignment.assignment_id} inferred impact states a number with no "
            "baseline. Carry the denominator into the claim itself: 'X of Y', "
            "'from A to B', 'against a Z threshold'"
        )
    if _DECIMAL_METRIC_RE.search(inference.final_claim):
        raise ContractError(
            f"{assignment.assignment_id} inferred impact uses false precision. An "
            "estimated metric must be a round number the candidate can defend"
        )
    lowered = inference.final_claim.casefold()
    if found := [word for word in ABSOLUTE_QUALIFIERS if word in lowered]:
        raise ContractError(
            f"{assignment.assignment_id} inferred impact uses absolute or "
            f"self-congratulatory qualifiers {found}"
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


# Phrases that justify a skill gap inside a bullet instead of stating work.
# "Applied Java, aligning with modern JVM environments" tells the reader the
# writer was reaching for a keyword the candidate lacks.
_GAP_JUSTIFICATION_RE = re.compile(
    r"\b(?:mirroring|aligning with|aligned with|matching|reflecting|similar to|"
    r"analogous to|akin to|comparable to|transferable to)\b[^.;]{0,40}?"
    r"\b(?:architectures?|paradigms?|patterns|environments?|ecosystems?|"
    r"languages?|stacks?|principles)\b"
    r"|\b(?:and|or) (?:related|similar|other|adjacent) [\w-]+(?: [\w-]+)? "
    r"(?:languages|frameworks|tools|platforms|technologies)\b",
    re.I,
)


def _bullet_evidence_text(
    source_ids: Iterable[str], fact_index: Mapping[str, dict]
) -> str:
    """Cited fact text plus the technology lists of the cited entries.

    A project's technologies apply to every bullet about that project, so a
    bullet citing only a project highlight may still name its listed stack.
    """

    source_ids = [fact_id for fact_id in source_ids if fact_id in fact_index]
    entries = {fact_index[fact_id]["entry_id"] for fact_id in source_ids}
    texts = [fact_index[fact_id]["text"] for fact_id in source_ids]
    texts.extend(
        fact["text"]
        for fact in fact_index.values()
        if fact["kind"] == "technology" and fact["entry_id"] in entries
    )
    return "\n".join(texts)


def _reject_forbidden_terms(
    item: WorkRewriteItem | ProjectRewriteItem,
    forbidden_terms: Sequence[str],
    summary: str | None,
    tech_requirements: Sequence[tuple[str, Sequence[str]]] = (),
    fact_index: Mapping[str, dict] | None = None,
) -> None:
    """Reject technology claims a bullet's evidence does not support.

    A missing JD technology may live only in the labeled transferable group,
    and a stated JD technology may appear in a bullet only when that bullet's
    own source facts mention it ("SQL" evidence never becomes "PostgreSQL").
    """

    texts = [summary or ""]
    for bullet in item.bullets:
        texts.extend(
            (bullet.text, bullet.situation_task, bullet.action, bullet.result)
        )
    justified = sorted(
        {match.group(0).lower() for text in texts for match in _GAP_JUSTIFICATION_RE.finditer(text)}
    )
    if justified:
        raise ContractError(
            f"{item.source_id} justifies a skill gap inside a bullet {justified}. "
            "State the real work, technology, and result only; never explain how "
            "it resembles the job's requirement"
        )
    found = sorted({term for text in texts for term in find_terms(text, forbidden_terms)})
    if found:
        raise ContractError(
            f"{item.source_id} claims technologies absent from the master: {found}. "
            "Name the real adjacent technology from the evidence instead; the "
            "missing JD term may appear only in the transferable skills group"
        )
    if not tech_requirements or fact_index is None:
        return
    unsupported: list[str] = []
    for index, bullet in enumerate(item.bullets):
        cited = _bullet_evidence_text(bullet.source_ids, fact_index)
        bullet_text = " ".join(
            (bullet.text, bullet.situation_task, bullet.action, bullet.result)
        )
        for term, variants in tech_requirements:
            if mentions(bullet_text, variants) and not mentions(cited, variants):
                unsupported.append(f"bullet {index}: {term}")
    if unsupported:
        raise ContractError(
            f"{item.source_id} names technologies its source facts do not mention "
            f"{unsupported}. Use only the technology the cited facts name"
        )


def repair_allocation_provenance(
    item: WorkRewriteItem, plan: EvidencePlan
) -> list[str]:
    """Pin each bullet's source_ids to its own evidence allocation.

    A weak model often cites a real master fact the planner did not assign to
    that bullet. That is bookkeeping, not a new claim, so the stray IDs are
    dropped (falling back to the full allocation when none remain) instead of
    failing the rewrite. Returns one note per repaired bullet.
    """

    assignments = _assignments_by_destination(plan).get(item.source_id, {})
    notes: list[str] = []
    for index, bullet in enumerate(item.bullets):
        assignment = assignments.get(bullet.evidence_assignment_id or "")
        if assignment is None:
            continue
        allowed = set(assignment.source_fact_ids)
        stray = [fact_id for fact_id in bullet.source_ids if fact_id not in allowed]
        if not stray:
            continue
        kept = list(
            dict.fromkeys(f for f in bullet.source_ids if f in allowed)
        ) or list(assignment.source_fact_ids)
        bullet.source_ids = kept
        notes.append(
            f"{item.source_id} bullet {index}: dropped citations outside "
            f"{assignment.assignment_id} {stray}"
        )
    return notes


def validate_work_item(
    item: WorkRewriteItem,
    source: dict,
    plan: EvidencePlan,
    fact_index: Mapping[str, dict],
    transferable_plan: TransferableSkillPlan | None = None,
    forbidden_terms: Sequence[str] = (),
    tech_requirements: Sequence[tuple[str, Sequence[str]]] = (),
) -> None:
    if item.source_id != source["source_id"]:
        raise ContractError(f"unknown work source_id: {item.source_id}")
    _reject_forbidden_terms(
        item, forbidden_terms, item.summary, tech_requirements, fact_index
    )
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
    forbidden_terms: Sequence[str] = (),
    tech_requirements: Sequence[tuple[str, Sequence[str]]] = (),
) -> None:
    if item.source_id != source["source_id"]:
        raise ContractError(f"unknown project source_id: {item.source_id}")
    _reject_forbidden_terms(
        item, forbidden_terms, item.description, tech_requirements, fact_index
    )
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
    forbidden_terms: Sequence[str] = (),
    tech_requirements: Sequence[tuple[str, Sequence[str]]] = (),
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
                forbidden_terms,
                tech_requirements,
            )
        except ContractError as exc:
            errors.append(str(exc))
    if errors:
        raise ContractError("work rewrite invalid: " + "; ".join(errors))
    return returned


# -- Salvage: finish a rewrite deterministically instead of failing the run ----

# Textual issues a user may knowingly accept ("Keep as written"); structural
# ones (missing bullet, bad provenance, broken impact bookkeeping) may not.
_TEXTUAL_ISSUE_PREFIXES = ("Names ", "Explains ")


def _clean_after_removal(text: str) -> str:
    """Tidy punctuation and joiners left behind after cutting a phrase out."""

    for pattern, replacement in (
        (r"\(\s*\)", ""),
        (r"\s+(?:and|or|&)\s+(?=[,.;:)]|$)", ""),
        (r"\b(and|or)\s+(?:and|or)\b", r"\1"),
        (r"\b(using|with|in|via|on)\s+(?:and|or)\s+", r"\1 "),
        (r"\b(?:using|with|in|via|on)\s+(?=[,.;:)]|$)", ""),
        (r"\b(\w[\w.+#-]*), (and|or) (\w[\w.+#-]*)([.;]|$)", r"\1 \2 \3\4"),
        (r",\s*(?=[,.;:)]|$)", ""),
        (r"\s{2,}", " "),
        (r"\s+([,.;:)])", r"\1"),
    ):
        text = re.sub(pattern, replacement, text)
    text = text.strip(" ,;:")
    if text and text[-1] not in ".!?":
        text += "."
    return text[:1].upper() + text[1:]


def _remove_phrases(text: str, forbidden_terms: Sequence[str]) -> str:
    # Cut a gap-justification clause together with its leading comma.
    text = re.sub(
        r",?\s*(?:" + _GAP_JUSTIFICATION_RE.pattern + r")[^,.;]*",
        "",
        text,
        flags=re.I,
    )
    for term in find_terms(text, forbidden_terms):
        text = re.sub(
            r"(?:\s*,\s*|\s+(?:and|or|&)\s+)?(?<![A-Za-z0-9+#.\-])"
            + re.escape(term)
            + r"(?![A-Za-z0-9+#\-])",
            "",
            text,
            count=0,
        )
    return _clean_after_removal(text)


def _bullet_issues(
    bullet: STARBullet,
    fact_index: Mapping[str, dict],
    assignment: EvidenceAssignment | None,
    forbidden_terms: Sequence[str],
    local_fact_ids: set[str] | None = None,
) -> list[str]:
    """Human-readable problems with one bullet; textual ones first."""

    issues: list[str] = []
    texts = " ".join((bullet.text, bullet.situation_task, bullet.action, bullet.result))
    for term in find_terms(texts, forbidden_terms):
        issues.append(f"Names '{term}', which your master resume never states.")
    if match := _GAP_JUSTIFICATION_RE.search(texts):
        issues.append(f"Explains a skill gap instead of stating work: '{match.group(0)}'.")
    if local_fact_ids is not None and (stray := set(bullet.source_ids) - local_fact_ids):
        issues.append(f"Cites facts from outside this project: {sorted(stray)}.")
    try:
        _validate_star_bullet(bullet, fact_index, assignment, "bullet")
    except ContractError as exc:
        issues.append(str(exc).removeprefix("bullet ").capitalize())
    return issues


def _fact_bullet(
    fact_ids: Sequence[str], fact_index: Mapping[str, dict], relevance: int
) -> STARBullet:
    """A bullet written verbatim from master facts: true by construction."""

    known = [fact_id for fact_id in fact_ids if fact_id in fact_index]
    prose = [f for f in known if fact_index[f]["kind"] not in {"skill", "technology"}]
    chosen = (prose or known)[:1]
    text = _clean_after_removal(fact_index[chosen[0]]["text"]) if chosen else "."
    verified = bool(_NUMBER_RE.search(text))
    return STARBullet(
        evidence_assignment_id=None,
        situation_task=text,
        action=text,
        result=text,
        text=text,
        relevance=relevance,
        source_ids=chosen,
        impact_type="verified" if verified else "qualitative",
        impact_claim=text,
    )


def _review_flag(
    *,
    section: str,
    source_id: str,
    label: str,
    issues: Sequence[str],
    original: STARBullet | None,
    safe: STARBullet,
    assignment_id: str | None,
    safe_kind: str,
) -> dict:
    textual_only = bool(issues) and all(
        issue.startswith(_TEXTUAL_ISSUE_PREFIXES) for issue in issues
    )
    return {
        "section": section,
        "source_id": source_id,
        "label": label,
        "assignment_id": assignment_id,
        "issues": list(issues),
        "original_text": original.text if original else None,
        "safe_text": safe.text,
        "safe_kind": safe_kind,
        "can_keep": original is not None and textual_only,
        "source_fact_ids": list(safe.source_ids),
    }


def _safe_variant(
    bullet: STARBullet,
    fact_index: Mapping[str, dict],
    assignment: EvidenceAssignment | None,
    forbidden_terms: Sequence[str],
    local_fact_ids: set[str] | None,
) -> STARBullet | None:
    """The same bullet with flagged terms or filler cut out, if that is valid."""

    fields = {
        name: _remove_phrases(getattr(bullet, name), forbidden_terms)
        for name in ("text", "situation_task", "action", "result")
    }
    if fields["text"] == bullet.text or len(fields["text"].split()) < 6:
        return None
    candidate = bullet.model_copy(update=fields)
    if _bullet_issues(candidate, fact_index, assignment, forbidden_terms, local_fact_ids):
        return None
    return candidate


def bullet_text_problems(
    text: str,
    facts_text: str,
    forbidden_terms: Sequence[str],
    tech_requirements: Sequence[tuple[str, Sequence[str]]] = (),
    allowed_numbers_text: str = "",
) -> list[str]:
    """Truth problems in a single regenerated bullet, checked against its facts."""

    problems: list[str] = []
    if found := find_terms(text, forbidden_terms):
        problems.append(f"names technologies the master never states: {found}")
    if match := _GAP_JUSTIFICATION_RE.search(text):
        problems.append(f"explains a skill gap: {match.group(0)!r}")
    unsupported = [
        term
        for term, variants in tech_requirements
        if mentions(text, variants) and not mentions(facts_text, variants)
    ]
    if unsupported:
        problems.append(f"names technologies its facts never mention: {unsupported}")
    invented = _number_tokens(text) - _number_tokens(f"{facts_text} {allowed_numbers_text}")
    if invented:
        problems.append(f"states numbers its facts never give: {sorted(invented)}")
    words = len(text.split())
    if not 8 <= words <= 45:
        problems.append(f"must be 8-45 words; got {words}")
    return problems


def salvage_work_item(
    candidate: WorkRewriteItem | None,
    source: dict,
    plan: EvidencePlan,
    fact_index: Mapping[str, dict],
    forbidden_terms: Sequence[str] = (),
) -> tuple[WorkRewriteItem, list[dict]]:
    """Build a valid rewrite for one role from the model's last attempt.

    Valid bullets are kept. A flawed bullet becomes its safe variant (the
    flagged term or phrase cut out) or, failing that, a bullet written from
    its allocated master fact. Every replacement is returned as a review flag
    so the user can choose. The plan's inferred impact is dropped for an
    assignment whose bullet falls back to verbatim fact text.
    """

    source_id = source["source_id"]
    label = " · ".join(v for v in (source.get("position"), source.get("name")) if v)
    assignments = list(_assignments_by_destination(plan).get(source_id, {}).values())
    if candidate is not None:
        repair_allocation_provenance(candidate, plan)
    written: dict[str, STARBullet] = {}
    for bullet in candidate.bullets if candidate else []:
        written.setdefault(bullet.evidence_assignment_id or "", bullet)
    bullets: list[STARBullet] = []
    flags: list[dict] = []
    for assignment in assignments:
        bullet = written.get(assignment.assignment_id)
        issues = (
            _bullet_issues(bullet, fact_index, assignment, forbidden_terms)
            if bullet
            else ["The model did not write this bullet."]
        )
        if not issues:
            bullets.append(bullet)
            continue
        safe = (
            _safe_variant(bullet, fact_index, assignment, forbidden_terms, None)
            if bullet
            else None
        )
        safe_kind = "edited"
        if safe is None:
            safe_kind = "source_fact"
            assignment.inferred_impact = None
            safe = _fact_bullet(
                assignment.source_fact_ids, fact_index, bullet.relevance if bullet else 50
            ).model_copy(update={"evidence_assignment_id": assignment.assignment_id})
        bullets.append(safe)
        flags.append(
            _review_flag(
                section="work",
                source_id=source_id,
                label=label,
                issues=issues,
                original=bullet,
                safe=safe,
                assignment_id=assignment.assignment_id,
                safe_kind=safe_kind,
            )
        )
    summary = candidate.summary if candidate else None
    if summary and (find_terms(summary, forbidden_terms) or _GAP_JUSTIFICATION_RE.search(summary)):
        summary = None
    item = WorkRewriteItem(
        source_id=source_id,
        summary=summary,
        relevance=candidate.relevance if candidate else int(source.get("selection_relevance") or 50),
        bullets=bullets,
    )
    validate_work_item(item, source, plan, fact_index, None, forbidden_terms)
    return item, flags


def salvage_project_item(
    candidate: ProjectRewriteItem | None,
    source: dict,
    fact_index: Mapping[str, dict],
    forbidden_terms: Sequence[str] = (),
) -> tuple[ProjectRewriteItem, list[dict]]:
    """Project counterpart of :func:`salvage_work_item` (two local bullets)."""

    source_id = source["source_id"]
    label = source.get("name") or source_id
    local = _project_provenance(source)
    kept: list[STARBullet] = []
    flags: list[dict] = []
    for bullet in candidate.bullets if candidate else []:
        if len(kept) == PROJECT_BULLET_COUNT:
            break
        bullet = bullet.model_copy(update={"evidence_assignment_id": None})
        issues = _bullet_issues(bullet, fact_index, None, forbidden_terms, local)
        if not issues:
            kept.append(bullet)
            continue
        safe = _safe_variant(bullet, fact_index, None, forbidden_terms, local)
        safe_kind = "edited"
        if safe is None:
            safe_kind = "source_fact"
            unused = [f for f in bullet.source_ids if f in local] or sorted(local)
            safe = _fact_bullet(unused, fact_index, bullet.relevance)
        kept.append(safe)
        flags.append(
            _review_flag(
                section="projects", source_id=source_id, label=label, issues=issues,
                original=bullet, safe=safe, assignment_id=None, safe_kind=safe_kind,
            )
        )
    facts_by_kind = source.get("source_facts") or {}
    highlight_ids = [
        fact["source_id"] for fact in facts_by_kind.get("highlights", [])
    ] + ([facts_by_kind["description"]["source_id"]] if facts_by_kind.get("description") else [])
    used = {f for bullet in kept for f in bullet.source_ids}
    for fact_id in highlight_ids:
        if len(kept) == PROJECT_BULLET_COUNT:
            break
        if fact_id in used:
            continue
        safe = _fact_bullet([fact_id], fact_index, 50)
        kept.append(safe)
        used.add(fact_id)
        flags.append(
            _review_flag(
                section="projects", source_id=source_id, label=label,
                issues=["The model did not write this bullet."], original=None,
                safe=safe, assignment_id=None, safe_kind="source_fact",
            )
        )
    description = candidate.description if candidate else source.get("description")
    if description and (
        find_terms(description, forbidden_terms) or _GAP_JUSTIFICATION_RE.search(description)
    ):
        description = source.get("description")
    item = ProjectRewriteItem(
        source_id=source_id,
        description=description,
        relevance=candidate.relevance if candidate else int(source.get("selection_relevance") or 50),
        bullets=kept,
    )
    validate_project_item(item, source, fact_index, None, forbidden_terms)
    return item, flags


def validate_project_response(
    response: ProjectRewriteResponse,
    sources: Sequence[dict],
    fact_index: Mapping[str, dict],
    transferable_plan: TransferableSkillPlan | None = None,
    forbidden_terms: Sequence[str] = (),
    tech_requirements: Sequence[tuple[str, Sequence[str]]] = (),
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
                forbidden_terms,
                tech_requirements,
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


_KEYWORD_FACT_KINDS = frozenset({"skill", "technology"})


def is_keyword_fact(fact: Mapping | None) -> bool:
    return bool(fact) and fact.get("kind") in _KEYWORD_FACT_KINDS


def _enrich_proxy_facts(proxy: object, fact_index: Mapping[str, dict]) -> None:
    """Attach bullet-capable facts behind keyword-only proxy evidence.

    A project technology ("Clojure") or skill keyword cannot carry a STAR
    bullet. For a technology fact, the project's description and top
    highlight are the work done with it; for any keyword, highlights that name
    a proxy term are added. At most three facts are added.
    """

    cited = list(proxy.source_fact_ids)
    if any(not is_keyword_fact(fact_index.get(fact_id)) for fact_id in cited):
        return
    added: list[str] = []

    def add(fact_id: str) -> None:
        if fact_id not in cited and fact_id not in added and len(added) < 3:
            added.append(fact_id)

    for fact_id, fact in fact_index.items():
        if not is_keyword_fact(fact) and mentions(fact["text"], proxy.proxy_terms):
            add(fact_id)
    for fact_id in cited:
        fact = fact_index[fact_id]
        if fact["kind"] != "technology":
            continue
        entry = fact["entry_id"]
        for suffix in (".description", ".highlights[0]"):
            if f"{entry}{suffix}" in fact_index:
                add(f"{entry}{suffix}")
    proxy.source_fact_ids = cited + added


def validate_requirement_proxy_plan(
    plan: RequirementProxyPlan,
    requirements: Sequence[dict],
    fact_index: Mapping[str, dict],
    repair: bool = False,
) -> list[str]:
    """Validate adjacent-evidence proxies and canonicalize them to the JD map.

    Canonicalization (exact JD spelling and requirement type) is applied in
    place so a weak model's casing drift is repaired instead of retried. Truth
    problems are a proxy for a requirement the master already states, a
    nonexistent fact, or a proxy term its cited facts never mention. They raise
    by default; with ``repair`` the offending terms or proxies are removed in
    place instead, and the returned notes say what was dropped.
    """

    by_term = {normalize_term(item["term"]): item for item in requirements}
    missing_terms = {
        normalize_term(item["term"]) for item in requirements if item["status"] == "missing"
    }
    errors: list[str] = []
    kept = []
    seen: set[str] = set()
    for proxy in plan.proxies:
        problems: list[str] = []
        key = normalize_term(proxy.requirement)
        requirement = by_term.get(key)
        if requirement is None:
            errors.append(f"{proxy.requirement!r} is not a target-profile requirement")
            continue
        if key not in missing_terms:
            errors.append(
                f"{proxy.requirement!r} is already stated in the master; proxies are "
                "only for requirements the master lacks"
            )
            continue
        if key in seen:
            errors.append(f"duplicate proxy for {proxy.requirement!r}")
            continue
        proxy.requirement = requirement["term"]
        proxy.requirement_type = requirement["requirement_type"]
        if _NON_SKILL_REQUIREMENT_RE.search(proxy.requirement):
            errors.append(f"non_skill_requirement={proxy.requirement}")
            continue
        unknown = set(proxy.source_fact_ids) - set(fact_index)
        if unknown:
            problems.append(f"nonexistent_sources={sorted(unknown)}")
            proxy.source_fact_ids = [
                fact_id for fact_id in dict.fromkeys(proxy.source_fact_ids)
                if fact_id in fact_index
            ]
        elif duplicates := _duplicate_values(proxy.source_fact_ids):
            problems.append(f"duplicate_sources={duplicates}")
            proxy.source_fact_ids = list(dict.fromkeys(proxy.source_fact_ids))
        cited_text = "\n".join(
            fact_index[fact_id]["text"] for fact_id in proxy.source_fact_ids
        )
        unsupported = [
            term for term in proxy.proxy_terms if not mentions(cited_text, (term,))
        ]
        if unsupported:
            problems.append(
                f"proxy_terms {unsupported} do not appear in the cited facts "
                f"{proxy.source_fact_ids}; cite the facts that name them"
            )
        leaked = [
            term for term in proxy.proxy_terms if normalize_term(term) in missing_terms
        ]
        if leaked:
            problems.append(
                f"proxy_terms {leaked} are themselves missing from the master"
            )
        proxy.proxy_terms = [
            term
            for term in proxy.proxy_terms
            if term not in unsupported and term not in leaked
        ]
        if problems:
            errors.append(f"{proxy.requirement} " + "; ".join(problems))
        if proxy.proxy_terms and proxy.source_fact_ids:
            _enrich_proxy_facts(proxy, fact_index)
            seen.add(key)
            kept.append(proxy)
    if errors and not repair:
        raise ContractError("requirement proxy plan invalid: " + "; ".join(errors))
    plan.proxies = kept
    return errors


def transferable_plan_from_proxies(
    plan: RequirementProxyPlan, limit: int = 4
) -> TransferableSkillPlan:
    chosen = sorted(
        (proxy for proxy in plan.proxies if proxy.list_as_transferable_skill),
        key=lambda proxy: -proxy.relevance,
    )[:limit]
    return TransferableSkillPlan(
        skills=[
            TransferableSkill(
                keyword=proxy.requirement,
                requirement_type=proxy.requirement_type,
                category=proxy.category,
                source_fact_ids=list(proxy.source_fact_ids),
                transfer_basis=proxy.transfer_basis,
                relevance=proxy.relevance,
            )
            for proxy in chosen
        ]
    )


def sanitize_target_terms(
    plan: EvidencePlan,
    requirements: Sequence[dict],
    forbidden_terms: Sequence[str],
    fact_index: Mapping[str, dict],
) -> list[str]:
    """Keep only target terms the assignment's own facts support.

    Allowed terms are the JD's own spellings of requirements the master states,
    plus validated proxy terms, and each must be mentioned (in any equivalent
    spelling) by one of the assignment's cited facts: "PostgreSQL" is not a
    target for a fact that only says "SQL". Target terms are hints, so every
    bad term, including a technology the master never states, is dropped and
    returned as a note; the bullet validators enforce the truth itself.
    """

    allowed: dict[str, str] = {}
    variants_for: dict[str, list[str]] = {}
    for item in requirements:
        if item["status"] == "direct":
            allowed[normalize_term(item["term"])] = item["term"]
            variants_for[item["term"]] = list(item.get("variants") or [item["term"]])
            for variant in item.get("variants", []):
                allowed.setdefault(normalize_term(variant), item["term"])
        for term in item.get("proxy_terms", []):
            allowed.setdefault(normalize_term(term), term)
            variants_for.setdefault(term, [term])
    forbidden = {normalize_term(term) for term in forbidden_terms}
    dropped: list[str] = []
    for assignment in plan.assignments:
        kept: list[str] = []
        for term in assignment.target_terms:
            key = normalize_term(term)
            if key in forbidden:
                dropped.append(f"{assignment.assignment_id}:{term} (never used)")
            elif key in allowed:
                canonical = allowed[key]
                cited = "\n".join(
                    fact_index[fact_id]["text"]
                    for fact_id in assignment.source_fact_ids
                    if fact_id in fact_index
                )
                if not mentions(cited, variants_for[canonical]):
                    dropped.append(f"{assignment.assignment_id}:{term} (unsupported)")
                elif canonical not in kept:
                    kept.append(canonical)
            else:
                dropped.append(f"{assignment.assignment_id}:{term}")
        assignment.target_terms = kept
    return dropped


def align_inference_provenance(plan: EvidencePlan) -> None:
    """Copy each assignment's destination and facts onto its inferred impact.

    The inference is nested inside its assignment, so differing IDs are
    bookkeeping drift from the model, not a provenance claim worth a retry.
    """

    for assignment in plan.assignments:
        inference = assignment.inferred_impact
        if inference is not None:
            inference.destination_work_id = assignment.destination_work_id
            inference.source_fact_ids = list(assignment.source_fact_ids)


def proxy_coverage_gaps(
    plan: EvidencePlan,
    priority: Sequence[dict],
    selected_projects: Sequence[dict],
    fact_index: Mapping[str, dict],
) -> list[str]:
    """Priority proxies whose evidence reaches neither a work bullet nor a project."""

    project_ids = {item["source_id"] for item in selected_projects}
    gaps: list[str] = []
    for item in priority:
        proxy_facts = set(item.get("proxy_fact_ids", []))
        if all(is_keyword_fact(fact_index.get(fact_id)) for fact_id in proxy_facts):
            # A bare skill keyword cannot carry a STAR bullet; the skills
            # section already surfaces it.
            continue
        in_bullet = any(
            proxy_facts & set(assignment.source_fact_ids)
            for assignment in plan.assignments
        )
        in_project = bool(assignment_entry_ids(proxy_facts, fact_index) & project_ids)
        if not (in_bullet or in_project):
            gaps.append(
                f"{item['term']} ({item['requirement_type']}) is missing from the "
                f"master, and its closest evidence {sorted(proxy_facts)} "
                f"({', '.join(item.get('proxy_terms', []))}) is in no assignment. "
                "Replace the destination's least relevant assignment with one built "
                "on that evidence, naming the real technology."
            )
    return gaps


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
    allowed.update(technologies_in_experience(master))
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
    excluded = generated | {"source_id", "source_facts"}
    return {
        key: value
        for key, value in source.items()
        if key not in excluded and not key.startswith("selection_")
    }


def _scored_bullets(bullets: Sequence[STARBullet]) -> list[ScoredBullet]:
    return [
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
        for bullet in bullets
    ]


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
            components.forbidden_terms,
        )
        work.append(
            ScoredWork.model_validate(
                {
                    **_protected_source_fields(source, {"summary", "highlights"}),
                    "source_id": rewrite.source_id,
                    "summary": rewrite.summary,
                    "relevance": rewrite.relevance,
                    "highlights": _scored_bullets(rewrite.bullets),
                }
            )
        )

    projects: list[ScoredProject] = []
    for rewrite in components.projects:
        source = project_sources.get(rewrite.source_id)
        if source is None:
            raise ContractError(f"unknown project source_id: {rewrite.source_id}")
        validate_project_item(
            rewrite,
            source,
            facts,
            components.transferable_skill_plan,
            components.forbidden_terms,
        )
        projects.append(
            ScoredProject.model_validate(
                {
                    **_protected_source_fields(source, {"description", "highlights"}),
                    "source_id": rewrite.source_id,
                    "description": rewrite.description,
                    "highlights": _scored_bullets(rewrite.bullets),
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
    payload = master.model_dump(
        mode="json",
        exclude_unset=True,
        exclude={"basics", "work", "skills", "projects"},
    )
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
        for field in ("name", "location", "position", "url", "startDate", "endDate"):
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
                updated.forbidden_terms,
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
                updated.forbidden_terms,
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


_ATTRIBUTION_OBJECTION_RE = re.compile(
    r"\battribut|\bbelongs? to\b|\bnot (?:from|for|part of) (?:the|this)\b|"
    r"\bare (?:for|from) a (?:project|different)\b|\bdifferent (?:role|employer|entry)\b",
    re.I,
)


def waive_cross_entry_objections(
    violations: Sequence[TruthViolation],
    final_resume: ScoredResume,
    plan: EvidencePlan,
    fact_index: Mapping[str, dict],
) -> tuple[list[TruthViolation], list[TruthViolation]]:
    """Split out reviewer findings that only object to planned cross-entry moves.

    Cross-entry attribution is pipeline policy, so a finding whose reason is
    attribution and whose quoted claim sits in a bullet built from a
    cross-entry assignment is waived (and reported), not allowed to block.
    """

    cross_ids = {item["assignment_id"] for item in cross_entry_attributions(plan, fact_index)}
    cross_texts = [
        " ".join(bullet.text.split()).casefold()
        for item in final_resume.work or []
        for bullet in item.highlights or []
        if bullet.evidence_assignment_id in cross_ids
    ]
    kept: list[TruthViolation] = []
    waived: list[TruthViolation] = []
    for violation in violations:
        claim = " ".join(violation.claim.split()).casefold()
        if _ATTRIBUTION_OBJECTION_RE.search(violation.reason) and any(
            claim in text for text in cross_texts
        ):
            waived.append(violation)
        else:
            kept.append(violation)
    return kept, waived


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


def _iter_sections(
    final_resume: ScoredResume,
) -> Iterable[tuple[str, Callable[[int], str], list[str]]]:
    """Yield (section label, bullet-owner labeller, bullet texts) per entry."""

    for index, item in enumerate(final_resume.work or []):
        yield (
            f"Work[{index}]",
            lambda i, n=index: f"Work[{n}] bullet {i + 1}",
            [bullet.text for bullet in item.highlights or []],
        )
    for index, item in enumerate(final_resume.projects or []):
        yield (
            f"Projects[{index}]",
            lambda i, n=index: f"Projects[{n}] bullet {i + 1}",
            [bullet.text for bullet in item.highlights or []],
        )


_RESULT_CLAUSE_RE = re.compile(r",\s+\w+ing\b[^,]*[.!?]?\s*$")
_SHAPE_LIMIT = 3
_RESULT_CLAUSE_LIMIT = 2


def scan_bullet_style(final_resume: ScoredResume) -> list[str]:
    """Return warn-only bullet-style findings (never blocks the run).

    Mirrors the bullet guide's writing rules: banned weak openers, restricted
    ownership/impact verbs anywhere in the sentence, repeated opening verbs, and
    the uniform-shape tells the QA report found -- a section where most bullets
    end in a trailing participial result clause reads as generated. Findings are
    advisory; the holistic reviewer owns semantic judgment.
    """

    findings: list[str] = []

    def first_word(text: str) -> str:
        return text.split(maxsplit=1)[0].rstrip(",:;.?!()").casefold()

    for section, owner, bullets in _iter_sections(final_resume):
        opener_counts: dict[str, int] = {}
        result_clauses = 0
        for index, text in enumerate(bullets):
            lowered = text.casefold()
            opened_badly = False
            for phrase in BANNED_OPENER_PHRASES:
                if re.search(rf"^\s*{re.escape(phrase)}\b", lowered):
                    findings.append(
                        f"{owner(index)} opens with {phrase!r}: {text[:90]!r}"
                    )
                    opened_badly = True
                    break
            if not opened_badly:
                word = first_word(text)
                if word:
                    opener_counts[word] = opener_counts.get(word, 0) + 1
            # A restricted verb is a scope claim wherever it sits. Checking only
            # the opening token missed "architected and deployed 5 endpoints".
            for verb in RESTRICTED_VERBS:
                if re.search(rf"\b{verb}\b", lowered):
                    findings.append(
                        f"{owner(index)} uses restricted verb {verb!r} "
                        f"(needs supporting evidence at that scope): {text[:90]!r}"
                    )
            if _RESULT_CLAUSE_RE.search(text):
                result_clauses += 1
        for word, count in opener_counts.items():
            if count >= REPETITION_LIMIT:
                findings.append(
                    f"{section} opens {count} bullets with the same verb "
                    f"{word!r}; vary the openers"
                )
        if result_clauses >= _RESULT_CLAUSE_LIMIT:
            findings.append(
                f"{section} ends {result_clauses} bullets with a trailing "
                "participial result clause (', enabling ...'); vary the structure"
            )
    return findings


def scan_unsupported_technology(
    final_resume: ScoredResume,
    fact_index: Mapping[str, dict],
    tech_requirements: Sequence[tuple[str, Sequence[str]]],
) -> list[str]:
    """Warn-only: bullets naming a JD technology their source facts never name."""

    findings: list[str] = []
    for section, entries in (
        ("Work", final_resume.work or []),
        ("Projects", final_resume.projects or []),
    ):
        for item_index, item in enumerate(entries):
            for bullet_index, bullet in enumerate(item.highlights or []):
                cited = _bullet_evidence_text(bullet.source_ids, fact_index)
                for term, variants in tech_requirements:
                    if mentions(bullet.text, variants) and not mentions(cited, variants):
                        findings.append(
                            f"{section}[{item_index}] bullet {bullet_index + 1} names "
                            f"{term!r}, which its source facts never mention: "
                            f"{bullet.text[:90]!r}"
                        )
    return findings


def scan_metric_quality(final_resume: ScoredResume) -> list[str]:
    """Return warn-only findings about numbers that a reader cannot check.

    Covers the QA report's metric patterns: a figure with no baseline to measure
    it against, decimal precision no one could defend, several counts stacked in
    one sentence, and absolute qualifiers that carry no information.
    """

    findings: list[str] = []
    for _, owner, bullets in _iter_sections(final_resume):
        for index, text in enumerate(bullets):
            lowered = text.casefold()
            numbers = _NUMBER_RE.findall(text)
            has_baseline = bool(_BASELINE_RE.search(text))
            if numbers and not has_baseline:
                findings.append(
                    f"{owner(index)} states {numbers[0]!r} with no baseline or "
                    f"denominator: {text[:90]!r}"
                )
            if _DECIMAL_METRIC_RE.search(text):
                findings.append(
                    f"{owner(index)} uses decimal precision a candidate cannot "
                    f"defend in an interview: {text[:90]!r}"
                )
            if len(numbers) >= 3 or (len(numbers) == 2 and not has_baseline):
                findings.append(
                    f"{owner(index)} stacks {len(numbers)} quantified claims; "
                    f"keep one: {text[:90]!r}"
                )
            if found := [word for word in ABSOLUTE_QUALIFIERS if word in lowered]:
                findings.append(
                    f"{owner(index)} uses absolute qualifiers {found}: {text[:90]!r}"
                )
    return findings
