"""Strict models for the local web adapter: API, persistence, queue, tracker, events.

Adapter-owned only; the tailoring core consumes none of these.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_JD_LENGTH = 100_000
MAX_NAME_LENGTH = 80
DEFAULT_MAX_CALLS_PER_MINUTE = 15
DEFAULT_MAX_INPUT_TOKENS_PER_MINUTE = 250_000
DEFAULT_MAX_REQUESTS_PER_DAY = 500
ARTIFACT_ALLOWLIST = (
    "resume.pdf",
    "resume.tex",
    "tailored.json",
    "match_report.json",
    "diagnostic_report.json",
)
FIT_RECOVERY_IDEMPOTENCY_FILE = ".fit_recovery_idempotency.json"
EVENT_FILE = "web_events.jsonl"
JOB_FILE = "web_job.json"
QUEUE_DIR_NAME = "queue"
QUEUE_STATE_FILE = "queue_state.json"
CALLS_FILE = "gemini_calls.jsonl"
FIFO_WINDOW_SECONDS = 60
INTERRUPTED_MESSAGE = "Interrupted by server restart; the run did not finish."
PDF_EXPORT_WARNING = "The PDF library copy could not be created; the original PDF remains available from this job."


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def iso_now() -> float:
    return datetime.now(timezone.utc).timestamp()


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    ACTION_REQUIRED = "action_required"
    COMPLETED = "completed"
    FAILED = "failed"


# Values of resume_tailor.config.ProviderMode; a Literal so strict request
# validation accepts the JSON string.
ProviderModeName = Literal["gemini", "freellm", "freellm_gemini", "gemini_freellm"]
FREELLM_MODEL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,119}$"


class JobSource(StrEnum):
    WEB = "web"
    CLI = "cli"


class CreateJobRequest(BaseModel):
    """Validated ``POST /api/jobs`` body; never persisted verbatim."""

    model_config = ConfigDict(extra="forbid", strict=True)

    company: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    role: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    jd_text: str = Field(min_length=1, max_length=MAX_JD_LENGTH)
    bridge_skills: bool = False
    research_company: bool = False
    no_pdf: bool = False
    provider_mode: ProviderModeName = "gemini"
    freellm_model: str | None = Field(default=None, pattern=FREELLM_MODEL_PATTERN)

    @model_validator(mode="after")
    def _research_needs_gemini(self) -> "CreateJobRequest":
        if self.research_company and self.provider_mode == "freellm":
            raise ValueError(
                "Company research uses Gemini web search; pick a mode that includes Gemini."
            )
        return self

    @field_validator("company", "role")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("Company and role must name the position.")
        return trimmed

    @field_validator("jd_text")
    @classmethod
    def _jd_not_blank(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError(
                "Paste the job description you want to tailor this resume for."
            )
        return trimmed


class JobOptions(BaseModel):
    bridge_skills: bool = False
    research_company: bool = False
    no_pdf: bool = False
    provider_mode: ProviderModeName = "gemini"
    freellm_model: str | None = None


class PersistedJob(BaseModel):
    """Contents of ``web_job.json``; never stores the raw JD."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    source: JobSource = JobSource.WEB
    state: JobState = JobState.QUEUED
    company: str
    role: str
    options: JobOptions = Field(default_factory=JobOptions)
    created_at: str = Field(default_factory=utc_now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    current_stage: str | None = None
    message: str | None = None
    idempotency_key: str | None = None
    request_fingerprint: str | None = None
    pdf_library_name: str | None = None
    export_warning: str | None = None
    action_kind: Literal["fit_recovery", "bullet_review"] | None = None


class QueuePayload(BaseModel):
    """Private queued request beneath the state directory; includes JD text."""

    model_config = ConfigDict(extra="forbid")

    company: str
    role: str
    jd_text: str
    bridge_skills: bool = False
    research_company: bool = False
    no_pdf: bool = False
    provider_mode: ProviderModeName = "gemini"
    freellm_model: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    idempotency_key: str | None = None
    request_fingerprint: str | None = None
    # Set by "Resume run": reuse the stages a failed run already finished.
    resume: bool = False


class RecoveryQueuePayload(BaseModel):
    """Private queued request for one user-approved fit recovery pass."""

    model_config = ConfigDict(extra="forbid", strict=True)

    operation: Literal["fit_recovery", "bullet_review"] = "fit_recovery"
    revision: int = Field(ge=1)
    candidate_ids: list[str] = Field(min_length=1, max_length=100)
    decisions: dict[str, Literal["keep", "safe", "regenerate"]] = Field(
        default_factory=dict
    )
    created_at: str = Field(default_factory=utc_now_iso)
    idempotency_key: str
    request_fingerprint: str

    @field_validator("candidate_ids")
    @classmethod
    def _candidate_ids_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("Candidate IDs must be unique.")
        return values


class FitRecoveryRequest(BaseModel):
    """Validated user choice for ``POST .../fit-recovery``."""

    model_config = ConfigDict(extra="forbid", strict=True)

    revision: int = Field(ge=1)
    candidate_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("candidate_ids")
    @classmethod
    def _candidate_ids_are_unique_and_bounded(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 200 for value in values):
            raise ValueError(
                "Candidate IDs must be non-empty and no longer than 200 characters."
            )
        if len(values) != len(set(values)):
            raise ValueError("Candidate IDs must be unique.")
        return values


class FitRecoveryCandidate(BaseModel):
    """Safe removal candidate returned to the browser; no private locator data."""

    model_config = ConfigDict(extra="forbid", strict=True)

    candidate_id: str
    kind: str
    group: str
    label: str
    text: str
    relevance: int | float | None = None
    estimated_lines: int = Field(ge=1)
    recommendation: Literal["recommended", "consider", "keep_if_possible"]
    reason: str


class FitRecoveryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    revision: int = Field(ge=1)
    page_count: int = Field(ge=2)
    concision_attempts: int = Field(ge=0)
    candidates: list[FitRecoveryCandidate] = Field(min_length=1)
    recommended_candidate_ids: list[str]

    @model_validator(mode="after")
    def _recommendations_are_issued(self) -> "FitRecoveryResponse":
        issued = {candidate.candidate_id for candidate in self.candidates}
        if len(issued) != len(self.candidates):
            raise ValueError("Recovery candidates must have unique IDs.")
        if not set(self.recommended_candidate_ids).issubset(issued):
            raise ValueError("Recommended candidate IDs must be issued candidates.")
        return self


class BulletReviewRequest(BaseModel):
    """Validated user choices for ``POST .../bullet-review``."""

    model_config = ConfigDict(extra="forbid", strict=True)

    revision: int = Field(ge=1)
    decisions: dict[str, Literal["keep", "safe", "regenerate"]] = Field(
        min_length=1, max_length=100
    )

    @field_validator("decisions")
    @classmethod
    def _flag_ids_are_bounded(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not key or len(key) > 200 for key in values):
            raise ValueError("Review item IDs must be 1-200 characters.")
        return values


class BulletReviewItem(BaseModel):
    """One flagged bullet as shown to the browser; no private state."""

    model_config = ConfigDict(extra="forbid", strict=True)

    flag_id: str
    section: str
    label: str
    issues: list[str]
    original_text: str | None = None
    safe_text: str
    safe_kind: str
    can_keep: bool
    source_facts: list[str] = Field(default_factory=list)


class BulletReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    revision: int = Field(ge=1)
    items: list[BulletReviewItem] = Field(min_length=1)


class RecoverySubmissionResponse(BaseModel):
    job_id: str
    state: str = JobState.QUEUED.value
    queue_position: int
    status_url: str
    events_url: str = "/api/events"


class RecoveryIdempotencyRecord(BaseModel):
    """Private persisted result for one recovery POST idempotency key."""

    model_config = ConfigDict(extra="forbid", strict=True)

    key: str
    request_fingerprint: str
    status: Literal["in_progress", "completed"] = "in_progress"
    response_status: int = 202
    response_body: dict[str, object] | None = None
    created_at: str = Field(default_factory=utc_now_iso)


class RecoveryIdempotencyStore(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    records: list[RecoveryIdempotencyRecord] = Field(default_factory=list)


class WebEvent(BaseModel):
    """One durable job event line in ``web_events.jsonl``."""

    model_config = ConfigDict(extra="forbid")

    id: int
    kind: str
    job_id: str
    stage: str | None = None
    message: str | None = None
    elapsed_seconds: float | None = None
    attempt: int | None = None
    max_attempts: int | None = None
    verbose_only: bool = False
    created_at: str = Field(default_factory=utc_now_iso)


class StreamEvent(BaseModel):
    """One application SSE record; ids are monotonic for the server process."""

    model_config = ConfigDict(extra="forbid")

    id: int
    kind: str
    job_id: str | None = None
    stage: str | None = None
    message: str | None = None
    elapsed_seconds: float | None = None
    attempt: int | None = None
    max_attempts: int | None = None
    verbose_only: bool = False
    data: dict[str, object] | None = None
    created_at: str = Field(default_factory=utc_now_iso)


class ProblemDetails(BaseModel):
    """RFC 9457 problem document plus optional validation ``errors`` extension."""

    model_config = ConfigDict(extra="forbid")

    title: str
    status: int
    detail: str
    type: str = "about:blank"
    instance: str | None = None
    errors: list[dict[str, object]] | None = None

    def as_json(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude_none=True)


class TrackerSnapshot(BaseModel):
    """Process-local Gemini usage and pacing snapshot."""

    model_config = ConfigDict(extra="forbid")

    provider: str = "gemini"
    active: bool = True
    window_seconds: int = FIFO_WINDOW_SECONDS
    requests_in_minute: int = 0
    requests_per_minute_limit: int = DEFAULT_MAX_CALLS_PER_MINUTE
    input_tokens_in_minute: int = 0
    tokens_per_minute_limit: int = DEFAULT_MAX_INPUT_TOKENS_PER_MINUTE
    requests_today: int = 0
    requests_per_day_limit: int = DEFAULT_MAX_REQUESTS_PER_DAY
    token_usage_complete: bool = True
    minimum_interval_seconds: float = 4.5
    next_allowed_at: str | None = None
    day_resets_at: str | None = None
    wait_reason: Literal["interval", "rpm", "tpm", "rpd"] | None = None
    state: Literal["ready", "waiting", "paused"] = "ready"


class QueuedEntry(BaseModel):
    job_id: str
    company: str
    role: str
    source: str = JobSource.WEB.value
    queue_position: int
    created_at: str


class QueueSnapshot(BaseModel):
    """Safe queue view: never includes JD text."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["running", "paused"]
    active_job_id: str | None = None
    queue_count: int = 0
    waiting: list[QueuedEntry] = Field(default_factory=list)
    tracker: TrackerSnapshot


class JobEntry(BaseModel):
    """Safe job row for list/detail APIs; never includes JD text."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    company: str
    role: str
    source: str = JobSource.WEB.value
    state: str
    options: JobOptions = Field(default_factory=JobOptions)
    queue_position: int | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_seconds: float | None = None
    current_stage: str | None = None
    message: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    pdf_library_name: str | None = None
    export_warning: str | None = None
    action_kind: str | None = None
    active: bool = False


class JobDetail(BaseModel):
    job: JobEntry
    events: list[WebEvent] = Field(default_factory=list)


class CreateJobResponse(BaseModel):
    job_id: str
    state: str = JobState.QUEUED.value
    queue_position: int
    status_url: str
    events_url: str = "/api/events"


class MetaResponse(BaseModel):
    ready: bool = True
    auth_required: bool = False
    master_name: str | None = None
    master_email: str | None = None
    model: str | None = None
    provider: str | None = None
    pdf_available: bool = True
    queue_state: str = "running"
    active_job_id: str | None = None
    directory_labels: dict[str, str] = Field(default_factory=dict)
    tracker: TrackerSnapshot


def new_job_id() -> str:
    return str(uuid.uuid4())


def job_fingerprint(request: CreateJobRequest, options: JobOptions) -> str:
    """Stable identity for idempotent replay of an identical creation request."""
    seed = (
        request.company,
        request.role,
        request.jd_text,
        options.bridge_skills,
        options.research_company,
        options.no_pdf,
    )
    if options.provider_mode != "gemini":
        # Appended only when set, so Gemini-run fingerprints stay as before.
        seed += (options.provider_mode, options.freellm_model)
    return uuid.uuid5(uuid.NAMESPACE_URL, repr(seed)).hex


def job_fingerprint_for_review(request: BulletReviewRequest) -> str:
    """Stable identity for an idempotent bullet-review submission."""
    seed = ("bullet_review", request.revision, tuple(sorted(request.decisions.items())))
    return uuid.uuid5(uuid.NAMESPACE_URL, repr(seed)).hex


def job_fingerprint_for_recovery(request: FitRecoveryRequest) -> str:
    """Stable identity for an idempotent recovery selection (order-insensitive)."""
    seed = (request.revision, tuple(sorted(request.candidate_ids)))
    return uuid.uuid5(uuid.NAMESPACE_URL, repr(seed)).hex


def sanitize_filename_component(value: str) -> str:
    """PDF-library filename component: no separators, controls, or trailing dots."""
    cleaned = re.sub(r"[\x00-\x1f\x7f/\\:]+", " ", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(" .")
    return cleaned or "Untitled"


def pdf_library_name(company: str, role: str, job_id: str, when: str) -> str:
    """``<Company> - <Role> - <YYYY-MM-DD> - <job-id-first-8>.pdf`` (collision-safe)."""
    date_part = when[:10]
    return (
        f"{sanitize_filename_component(company)} - {sanitize_filename_component(role)}"
        f" - {date_part} - {job_id[:8]}.pdf"
    )
