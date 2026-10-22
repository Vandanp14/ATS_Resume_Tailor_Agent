"""Typed data contracts for the resume tailoring pipeline.

JSON Resume models describe persisted output.  The compact stage models contain
only values an LLM is allowed to choose; protected identity fields never appear
in generation schemas.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


TRANSFERABLE_SKILL_GROUP = "Transferable / Adjacent Tools"
# Skills the user confirmed in the pre-run skill check; ordinary skill facts.
CONFIRMED_SKILL_GROUP = "Confirmed Skills"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ModelProvider(str, Enum):
    OLLAMA = "ollama"
    GEMINI = "gemini"
    OPENROUTER = "openrouter"
    FREELLM = "freellm"


# JSON Resume -----------------------------------------------------------------


class Location(BaseModel):
    address: str | None = None
    postalCode: str | None = None
    city: str | None = None
    countryCode: str | None = None
    region: str | None = None


class Profile(BaseModel):
    network: str | None = None
    username: str | None = None
    url: str


class Basics(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    url: str | None = None
    summary: str | None = None
    location: Location | None = None
    profiles: list[Profile] | None = None


class Work(BaseModel):
    name: str | None = None
    location: str | None = None
    position: str | None = None
    url: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    summary: str | None = None
    highlights: list[str] | None = None


class Volunteer(BaseModel):
    organization: str | None = None
    position: str | None = None
    url: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    summary: str | None = None
    highlights: list[str] | None = None


class Education(BaseModel):
    institution: str | None = None
    url: str | None = None
    area: str | None = None
    studyType: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    score: str | None = None
    courses: list[str] | None = None


class Award(BaseModel):
    title: str | None = None
    date: str | None = None
    awarder: str | None = None
    summary: str | None = None


class Certificate(BaseModel):
    name: str | None = None
    date: str | None = None
    issuer: str | None = None
    url: str | None = None


class Publication(BaseModel):
    name: str | None = None
    publisher: str | None = None
    releaseDate: str | None = None
    url: str | None = None
    summary: str | None = None


class Skill(BaseModel):
    name: str | None = None
    level: str | None = None
    keywords: list[str] | None = None


class Language(BaseModel):
    language: str | None = None
    fluency: str | None = None


class Interest(BaseModel):
    name: str | None = None
    keywords: list[str] | None = None


class Reference(BaseModel):
    name: str | None = None
    reference: str | None = None


class Project(BaseModel):
    name: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    description: str | None = None
    highlights: list[str] | None = None
    url: str | None = None
    technologies: list[str] | None = None
    skills: list[str] | None = None


class SkillCheckAnswers(BaseModel):
    """Skill-check terms the user said they do not know; never asked again."""

    declined: list[str] = Field(default_factory=list)


class SkillChip(BaseModel):
    """A posting technology the master resume lacks, offered for confirmation."""

    term: str
    status: Literal["proxy", "missing"]
    evidence_span: str | None = None
    close_to: list[str] = Field(default_factory=list)


class SkillCheckResult(BaseModel):
    chips: list[SkillChip]
    remembered_confirmed: list[str]
    remembered_declined: list[str]


class JSONResume(BaseModel):
    basics: Basics | None = None
    work: list[Work] | None = None
    volunteer: list[Volunteer] | None = None
    education: list[Education] | None = None
    awards: list[Award] | None = None
    certificates: list[Certificate] | None = None
    publications: list[Publication] | None = None
    skills: list[Skill] | None = None
    languages: list[Language] | None = None
    interests: list[Interest] | None = None
    references: list[Reference] | None = None
    projects: list[Project] | None = None
    skill_check: SkillCheckAnswers | None = None


# Compact LLM contracts -------------------------------------------------------


KeywordCategory = Literal[
    "language",
    "framework",
    "tool",
    "platform",
    "methodology",
    "domain_skill",
    "soft_skill",
    "responsibility",
    "other",
]
SkillCategory = Literal[
    "tool", "framework", "language", "platform", "methodology", "domain_skill"
]
RequirementType = Literal["must_have", "nice_to_have", "weighted_keyword"]


class KeywordWeight(StrictModel):
    term: str = Field(min_length=1)
    weight: int = Field(ge=1, le=5)
    aliases: list[str] = Field(default_factory=list)
    category: KeywordCategory | None = None
    evidence_span: str | None = None


class JDProfile(StrictModel):
    role: str = Field(min_length=1)
    seniority: str | None = None
    domain: str | None = None
    company_name: str | None = None
    must_have_skills: list[str]
    nice_to_have_skills: list[str]
    keywords: list[KeywordWeight]
    title_aliases: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)


# Company research (grounded web search; unconstrained decoding — see llm_utils
# .GeminiProvider.chat's `grounding` branch) ------------------------------------


class CompanySourceRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str = Field(min_length=1)
    title: str | None = None


class StackSignal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    term: str = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]
    source_snippet: str | None = None


class CompanyStackResearch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    company_name: str
    found: bool
    inferred_stack: list[StackSignal] = Field(default_factory=list)
    sources: list[CompanySourceRef] = Field(default_factory=list)
    notes: str | None = None


class HiringSignalItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phrase: str = Field(min_length=1)
    theme: Literal[
        "ownership",
        "velocity",
        "craft_quality",
        "collaboration",
        "customer_obsession",
        "other",
    ]
    source_snippet: str | None = None


class CompanyHiringSignals(BaseModel):
    model_config = ConfigDict(extra="ignore")

    company_name: str
    found: bool
    signals: list[HiringSignalItem] = Field(default_factory=list)
    sources: list[CompanySourceRef] = Field(default_factory=list)
    notes: str | None = None


class SelectionCandidate(StrictModel):
    source_id: str = Field(min_length=1)
    relevance: int = Field(ge=0, le=100)
    selected: bool
    matched_requirements: list[str] = Field(default_factory=list)
    covered_requirement_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


class CandidateSelection(StrictModel):
    candidates: list[SelectionCandidate]


class ImpactInference(StrictModel):
    inference_id: str = Field(min_length=1)
    destination_work_id: str = Field(min_length=1)
    source_fact_ids: list[str] = Field(min_length=1)
    inference_basis: str = Field(min_length=1)
    baseline: str = Field(min_length=1)
    final_claim: str = Field(min_length=1)


class EvidenceAssignment(StrictModel):
    assignment_id: str = Field(min_length=1)
    destination_work_id: str = Field(min_length=1)
    source_fact_ids: list[str] = Field(min_length=1)
    matched_requirements: list[str] = Field(min_length=1)
    intended_accomplishment: str = Field(min_length=1)
    inferred_impact: ImpactInference | None
    target_terms: list[str] = Field(default_factory=list)


class EvidencePlan(StrictModel):
    assignments: list[EvidenceAssignment] = Field(min_length=1)


class RequirementProxy(StrictModel):
    """Closest real master evidence for a JD requirement the master lacks."""

    requirement: str = Field(min_length=1)
    requirement_type: RequirementType
    category: SkillCategory
    proximity: Literal["same_family", "same_paradigm", "analogous_workflow"]
    proxy_terms: list[str] = Field(min_length=1)
    source_fact_ids: list[str] = Field(min_length=1)
    transfer_basis: str = Field(min_length=1)
    relevance: int = Field(ge=0, le=100)
    list_as_transferable_skill: bool


class RequirementProxyPlan(StrictModel):
    proxies: list[RequirementProxy] = Field(max_length=8)


class TransferableSkill(StrictModel):
    keyword: str = Field(min_length=1)
    requirement_type: RequirementType
    category: SkillCategory
    source_fact_ids: list[str] = Field(min_length=1)
    transfer_basis: str = Field(min_length=1)
    relevance: int = Field(ge=0, le=100)


class TransferableSkillPlan(StrictModel):
    skills: list[TransferableSkill] = Field(max_length=4)


class ScoredSkill(StrictModel):
    name: str = Field(min_length=1)
    keywords: list[str] = Field(min_length=1)
    relevance: int = Field(ge=0, le=100)
    level: None = None


class TailoredSkills(StrictModel):
    skills: list[ScoredSkill] = Field(min_length=1, max_length=5)


class STARBullet(StrictModel):
    evidence_assignment_id: str | None
    situation_task: str = Field(min_length=1)
    action: str = Field(min_length=1)
    result: str = Field(min_length=1)
    text: str = Field(min_length=1)
    relevance: int = Field(ge=0, le=100)
    source_ids: list[str] = Field(min_length=1)
    impact_type: Literal["verified", "inferred", "qualitative"]
    impact_claim: str = Field(min_length=1)


WorkRewriteBullet = STARBullet
ProjectRewriteBullet = STARBullet


class WorkRewriteItem(StrictModel):
    source_id: str = Field(min_length=1)
    summary: str | None = None
    relevance: int = Field(ge=0, le=100)
    bullets: list[STARBullet] = Field(min_length=1)


class WorkRewriteResponse(StrictModel):
    work: list[WorkRewriteItem]


class ProjectRewriteItem(StrictModel):
    source_id: str = Field(min_length=1)
    description: str | None = None
    relevance: int = Field(ge=0, le=100)
    bullets: list[STARBullet] = Field(min_length=1)


class ProjectRewriteResponse(StrictModel):
    projects: list[ProjectRewriteItem]


class TruthViolation(StrictModel):
    section: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class SectionEdits(StrictModel):
    skills: TailoredSkills | None = None
    work: WorkRewriteResponse | None = None
    projects: ProjectRewriteResponse | None = None


class HolisticReview(StrictModel):
    coverage_pct: float = Field(ge=0, le=100)
    missing_must_haves: list[str]
    weak_sections: list[str]
    truth_violations: list[TruthViolation]
    recommendations: list[str] = Field(default_factory=list)
    notes: str | None = None
    section_edits: SectionEdits | None = None


# Public report name retained because the artifact is match_report.json.
MatchReport = HolisticReview


class BulletConcision(StrictModel):
    """One schema-constrained emergency rewrite returned by the model."""

    text: str = Field(min_length=1)


class ConcisionAuditItem(StrictModel):
    candidate_id: str = Field(min_length=1)
    supported: bool
    reason: str = Field(min_length=1)


class ConcisionAudit(StrictModel):
    items: list[ConcisionAuditItem] = Field(min_length=1)


# Renderer-only scored forms --------------------------------------------------


class ScoredBullet(BaseModel):
    text: str
    relevance: int = Field(ge=0, le=100)
    source_ids: list[str] = Field(default_factory=list)
    evidence_assignment_id: str | None = None
    situation_task: str | None = None
    action: str | None = None
    result: str | None = None
    impact_type: Literal["verified", "inferred", "qualitative"] | None = None
    impact_claim: str | None = None


class ScoredWork(Work):
    relevance: int = Field(ge=0, le=100)
    source_id: str | None = None
    highlights: list[ScoredBullet] | None = None


class ScoredProject(Project):
    highlights: list[ScoredBullet] | None = None
    relevance: int = Field(ge=0, le=100)
    source_id: str | None = None
    source_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_highlights(cls, value: object) -> object:
        """Accept historical string fixtures while storing one scored shape."""
        if not isinstance(value, dict):
            return value
        highlights = value.get("highlights")
        if not isinstance(highlights, list):
            return value
        relevance = value.get("relevance", 0)
        payload = dict(value)
        payload["highlights"] = [
            {"text": item, "relevance": relevance} if isinstance(item, str) else item
            for item in highlights
        ]
        return payload


def strip_relevance_skill(scored: ScoredSkill) -> Skill:
    return Skill(name=scored.name, level=None, keywords=scored.keywords)


def strip_relevance_work(scored: ScoredWork) -> Work:
    payload = scored.model_dump(
        mode="json",
        exclude_unset=True,
        exclude={"relevance", "source_id", "highlights"},
    )
    payload["highlights"] = [bullet.text for bullet in scored.highlights or []]
    return Work.model_validate(payload)


def strip_relevance_project(scored: ScoredProject) -> Project:
    payload = scored.model_dump(
        mode="json",
        exclude_unset=True,
        exclude={"relevance", "source_id", "source_ids", "highlights"},
    )
    payload["highlights"] = [bullet.text for bullet in scored.highlights or []]
    return Project.model_validate(payload)
