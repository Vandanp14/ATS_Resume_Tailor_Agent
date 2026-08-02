"""Typed data contracts for the resume tailoring pipeline.

JSON Resume models describe persisted output.  The compact stage models contain
only values an LLM is allowed to choose; protected identity fields never appear
in generation schemas.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TRANSFERABLE_SKILL_GROUP = "Transferable / Adjacent Tools"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ModelProvider(str, Enum):
    OLLAMA = "ollama"
    GEMINI = "gemini"


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


# Compact LLM contracts -------------------------------------------------------


class KeywordWeight(StrictModel):
    term: str = Field(min_length=1)
    weight: int = Field(ge=1, le=5)


class JDProfile(StrictModel):
    role: str = Field(min_length=1)
    seniority: str | None = None
    domain: str | None = None
    must_have_skills: list[str]
    nice_to_have_skills: list[str]
    keywords: list[KeywordWeight]


class SelectionCandidate(StrictModel):
    source_id: str = Field(min_length=1)
    relevance: int = Field(ge=0, le=100)
    selected: bool
    matched_requirements: list[str] = Field(default_factory=list)
    reason: str | None = None


class CandidateSelection(StrictModel):
    candidates: list[SelectionCandidate]


class ImpactInference(StrictModel):
    inference_id: str = Field(min_length=1)
    destination_work_id: str = Field(min_length=1)
    source_fact_ids: list[str] = Field(min_length=1)
    inference_basis: str = Field(min_length=1)
    final_claim: str = Field(min_length=1)


class EvidenceAssignment(StrictModel):
    assignment_id: str = Field(min_length=1)
    destination_work_id: str = Field(min_length=1)
    source_fact_ids: list[str] = Field(min_length=1)
    matched_requirements: list[str] = Field(min_length=1)
    intended_accomplishment: str = Field(min_length=1)
    inferred_impact: ImpactInference | None


class EvidencePlan(StrictModel):
    assignments: list[EvidenceAssignment] = Field(min_length=1)


class TransferableSkill(StrictModel):
    keyword: str = Field(min_length=1)
    requirement_type: Literal["must_have", "nice_to_have", "weighted_keyword"]
    category: Literal[
        "tool", "framework", "language", "platform", "methodology", "domain_skill"
    ]
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
    relevance: int = Field(ge=0, le=100)
    source_id: str | None = None
    source_ids: list[str] = Field(default_factory=list)


def strip_relevance_skill(scored: ScoredSkill) -> Skill:
    return Skill(name=scored.name, level=None, keywords=scored.keywords)


def strip_relevance_work(scored: ScoredWork) -> Work:
    payload = scored.model_dump(mode="json", exclude_unset=True)
    payload.pop("relevance", None)
    payload.pop("source_id", None)
    payload["highlights"] = [bullet.text for bullet in scored.highlights or []]
    return Work.model_validate(payload)


def strip_relevance_project(scored: ScoredProject) -> Project:
    payload = scored.model_dump(mode="json", exclude_unset=True)
    payload.pop("relevance", None)
    payload.pop("source_id", None)
    payload.pop("source_ids", None)
    return Project.model_validate(payload)
