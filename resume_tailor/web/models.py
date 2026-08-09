"""Strict models for the local web adapter: API, persistence, queue, tracker, events.

Adapter-owned only; the tailoring core consumes none of these.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
EVENT_FILE = "web_events.jsonl"
JOB_FILE = "web_job.json"
QUEUE_DIR_NAME = "queue"
QUEUE_STATE_FILE = "queue_state.json"
CALLS_FILE = "gemini_calls.jsonl"
FIFO_WINDOW_SECONDS = 60
INTERRUPTED_MESSAGE = "Interrupted by server restart; the run did not finish."
PDF_EXPORT_WARNING = (
    "The PDF library copy could not be created; the original PDF remains available from this job."
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def iso_now() -> float:
    return datetime.now(timezone.utc).timestamp()


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


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
    no_pdf: bool = False

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
            raise ValueError("Paste the job description you want to tailor this resume for.")
        return trimmed


class JobOptions(BaseModel):
    bridge_skills: bool = False
    no_pdf: bool = False


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


class QueuePayload(BaseModel):
    """Private queued request beneath the state directory; includes JD text."""

    model_config = ConfigDict(extra="forbid")

    company: str
    role: str
    jd_text: str
    bridge_skills: bool = False
    no_pdf: bool = False
    created_at: str = Field(default_factory=utc_now_iso)
    idempotency_key: str | None = None
    request_fingerprint: str | None = None


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
    seed = (request.company, request.role, request.jd_text, options.bridge_skills, options.no_pdf)
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
