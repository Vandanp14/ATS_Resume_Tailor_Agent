"""Persistent FIFO queue registry, one worker loop, restart hydration, PDF library.

Owns all jobs for one server process. Waiting jobs persist as private request
payloads beneath the state directory; job metadata and journals live in
``output/<job-id>/``. Starts at most one pipeline at a time through a single
long-lived worker loop woken by a condition.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from models import JSONResume

from ..batch import is_quota_error
from ..checkpoints import CHECKPOINT_DIR
from ..config import resolve_chains
from ..pipeline import TailorPipeline
from ..progress import JobContext
from ..runtime import load_master
from ..skill_answers import (
    apply_answers,
    confirmed_terms,
    declined_terms,
    replace_answers,
    save_master,
)
from .io import atomic_write_text, private_directory
from .models import (
    SkillAnswers,
    SkillAnswersResponse,
    SkillCheckRequest,
    SkillCheckResponse,
    ARTIFACT_ALLOWLIST,
    EVENT_FILE,
    FIT_RECOVERY_IDEMPOTENCY_FILE,
    INTERRUPTED_MESSAGE,
    JOB_FILE,
    PDF_EXPORT_WARNING,
    QUEUE_DIR_NAME,
    QUEUE_STATE_FILE,
    CreateJobRequest,
    BulletReviewItem,
    BulletReviewRequest,
    BulletReviewResponse,
    CleanupInventory,
    CleanupItem,
    CleanupRequest,
    CleanupResult,
    FitRecoveryRequest,
    FitRecoveryResponse,
    JobEntry,
    JobOptions,
    JobSource,
    JobState,
    PersistedJob,
    QueuePayload,
    QueueSnapshot,
    QueuedEntry,
    RecoveryIdempotencyRecord,
    RecoveryIdempotencyStore,
    RecoveryQueuePayload,
    RecoverySubmissionResponse,
    StreamEvent,
    TrackerSnapshot,
    job_fingerprint,
    job_fingerprint_for_recovery,
    job_fingerprint_for_review,
    new_job_id,
    pdf_library_name,
    utc_now_iso,
)
from .reporter import EventHub, EventJournal, WebProgressReporter
from .scheduler import GeminiScheduler, ScheduledProvider

LOGGER = logging.getLogger("resume_tailor.web")
SKILL_CHECKS_DIR_NAME = "skill_checks"
SKILL_CHECK_FILE = "check.json"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


MAX_SAFE_MESSAGE = 500
_QUOTA_MESSAGE = "Gemini quota exhausted (429); the queue is paused. Resume the queue when quota is back, then resume this run to pick up where it stopped."


@dataclass
class Job:
    persisted: PersistedJob
    directory: Path
    journal: EventJournal
    reporter: WebProgressReporter
    payload: QueuePayload | RecoveryQueuePayload | None = None


class RecoveryRequestError(ValueError):
    """A safe, expected fit-recovery request conflict."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def load_recovery_response(directory: Path) -> FitRecoveryResponse:
    """Load the core's private recovery bundle and expose only browser-safe fields."""
    from ..fit_recovery import FIT_RECOVERY_FILENAME, load_fit_recovery

    if (directory / FIT_RECOVERY_FILENAME).is_symlink():
        raise ValueError("Recovery bundle must not be a symbolic link.")
    bundle = load_fit_recovery(directory)
    raw = bundle.model_dump(mode="python")
    public = {
        "revision": raw["revision"],
        "page_count": raw["page_count"],
        "concision_attempts": raw["concision_attempts"],
        "candidates": raw["candidates"],
        "recommended_candidate_ids": raw["recommended_candidate_ids"],
    }
    response = FitRecoveryResponse.model_validate(public)
    issued = {candidate.candidate_id for candidate in response.candidates}
    if len(issued) != len(response.candidates):
        raise ValueError("Recovery bundle contains duplicate candidate IDs.")
    if not set(response.recommended_candidate_ids).issubset(issued):
        raise ValueError("Recovery bundle recommends an unknown candidate ID.")
    return response


def load_bullet_review_response(directory: Path) -> BulletReviewResponse:
    """Load the core's private review bundle and expose only browser-safe fields."""
    from ..bullet_review import BULLET_REVIEW_FILENAME, load_bullet_review

    if (directory / BULLET_REVIEW_FILENAME).is_symlink():
        raise ValueError("Review bundle must not be a symbolic link.")
    bundle = load_bullet_review(directory)
    return BulletReviewResponse(
        revision=bundle.revision,
        items=[
            BulletReviewItem(
                flag_id=flag.flag_id,
                section=flag.section,
                label=flag.label,
                issues=list(flag.issues),
                original_text=flag.original_text,
                safe_text=flag.safe_text,
                safe_kind=flag.safe_kind,
                can_keep=flag.can_keep,
                source_facts=list(flag.source_facts),
            )
            for flag in bundle.flags
        ],
    )


def _say(exc: BaseException) -> str:
    return (str(exc).strip() or exc.__class__.__name__)[:MAX_SAFE_MESSAGE]


def _artifacts(directory: Path) -> list[str]:
    return [name for name in ARTIFACT_ALLOWLIST if (directory / name).is_file()]


def _tree_bytes(path: Path) -> int:
    """Total size of regular files under ``path``; symlinks are counted by link, never followed."""
    try:
        if path.is_symlink():
            return 0
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                continue
    return total


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


_DELETABLE_STATES = (JobState.COMPLETED, JobState.FAILED, JobState.ACTION_REQUIRED)


def _elapsed(started: str | None, finished: str | None) -> float | None:
    if not started:
        return None
    try:
        start = datetime.fromisoformat(started.replace("Z", "+00:00"))
        end = (
            datetime.fromisoformat((finished or "").replace("Z", "+00:00"))
            if finished
            else datetime.now(timezone.utc)
        )
        return max(0.0, (end - start).total_seconds())
    except ValueError:
        return None


class QueueRegistry:
    """Persistent FIFO queue, one worker loop, restart hydration, and output history."""

    def __init__(
        self,
        output_dir: Path,
        pdf_dir: Path,
        state_dir: Path,
        *,
        pipeline_factory: Callable[..., TailorPipeline],
        master_path: Path,
        master_name: str,
        model: str,
        call_interval: float,
        max_calls_per_minute: int,
        pdf_available: bool,
        hub: EventHub,
        provider: ScheduledProvider | None = None,
        scheduler: GeminiScheduler | None = None,
        recovery_handler: Callable[[Path, list[str]], int] | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.pdf_dir = Path(pdf_dir)
        self.state_dir = Path(state_dir)
        self.queue_dir = private_directory(self.state_dir / QUEUE_DIR_NAME)
        self.requests_dir = private_directory(self.state_dir / "requests")
        self.pipeline_factory = pipeline_factory
        self.master_path = Path(master_path)
        self.master_name = master_name
        self.model = model
        self.call_interval = call_interval
        self.max_calls_per_minute = max_calls_per_minute
        self.pdf_available = pdf_available
        self.hub = hub
        self.provider = provider
        self.scheduler = scheduler
        self.recovery_handler = recovery_handler or self._default_recovery_handler
        self._mutex = threading.Lock()
        self._cond = threading.Condition(self._mutex)
        # Serializes master.json writes (skill answers) against job reads.
        self.master_lock = threading.Lock()
        self.skill_checks_dir = private_directory(self.state_dir / SKILL_CHECKS_DIR_NAME)
        self._stopping = False
        self._worker: threading.Thread | None = None
        self._active: str | None = None
        self._waiting: list[Job] = []
        self._jobs: dict[str, Job] = {}
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self._paused = self._read_paused(self.state_dir / QUEUE_STATE_FILE)
        self._hydrate()
        self._start_worker()
        if scheduler is not None:
            scheduler.set_paused(self._paused)

    # -- lifecycle -------------------------------------------------------------

    def _start_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stopping = False
        self._worker = threading.Thread(
            target=self._worker_loop, name="resume-tailor-queue", daemon=True
        )
        self._worker.start()

    def stop(self) -> None:
        with self._cond:
            self._stopping = True
            self._cond.notify_all()

    # -- persistence helpers ---------------------------------------------------

    def _read_paused(self, path: Path) -> bool:
        if not path.is_file():
            return False
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            return bool(state.get("paused"))
        except (OSError, json.JSONDecodeError):
            return False

    def _persist_paused(self) -> None:
        atomic_write_text(
            self.state_dir / QUEUE_STATE_FILE,
            json.dumps({"paused": self._paused}) + "\n",
        )

    def _queue_payload_path(self, job_id: str) -> Path:
        return self.queue_dir / f"{job_id}.json"

    def _persist_payload(self, job: Job) -> None:
        assert job.payload is not None
        atomic_write_text(
            self._queue_payload_path(job.persisted.job_id),
            job.payload.model_dump_json(indent=1, exclude_none=True),
            mode=0o600,
        )

    def _persist_job(self, job: Job) -> None:
        atomic_write_text(
            job.directory / JOB_FILE,
            job.persisted.model_dump_json(indent=2, exclude_none=True),
        )

    def _recovery_idempotency_path(self, job: Job) -> Path:
        return job.directory / FIT_RECOVERY_IDEMPOTENCY_FILE

    def _load_recovery_idempotency(self, job: Job) -> RecoveryIdempotencyStore:
        path = self._recovery_idempotency_path(job)
        if not path.is_file() or path.is_symlink():
            return RecoveryIdempotencyStore()
        try:
            return RecoveryIdempotencyStore.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise RecoveryRequestError(
                409,
                "Recovery request history is unavailable; reload the job before retrying.",
            ) from exc

    def _persist_recovery_idempotency(
        self, job: Job, store: RecoveryIdempotencyStore
    ) -> None:
        atomic_write_text(
            self._recovery_idempotency_path(job),
            store.model_dump_json(indent=2),
            mode=0o600,
        )

    # -- hydration -------------------------------------------------------------

    def _hydrate(self) -> None:
        known: set[str] = set()
        for directory in sorted(self.output_dir.iterdir()):
            if not directory.is_dir():
                continue
            job_file = directory / JOB_FILE
            if not job_file.is_file():
                continue
            try:
                persisted = PersistedJob.model_validate_json(
                    job_file.read_text(encoding="utf-8")
                )
            except Exception:
                continue
            if persisted.job_id != directory.name:
                continue
            if persisted.state in {JobState.QUEUED, JobState.RUNNING}:
                recovery_payload: RecoveryQueuePayload | None = None
                payload_path = self._queue_payload_path(directory.name)
                if payload_path.is_file() and not payload_path.is_symlink():
                    try:
                        recovery_payload = RecoveryQueuePayload.model_validate_json(
                            payload_path.read_text(encoding="utf-8")
                        )
                    except Exception:
                        recovery_payload = None
                if recovery_payload is not None:
                    persisted = persisted.model_copy(
                        update={
                            "state": JobState.QUEUED,
                            "finished_at": None,
                            "message": None,
                            "current_stage": None,
                        }
                    )
                    known.add(directory.name)
                    job = self._add(directory, persisted)
                    job.payload = recovery_payload
                    self._persist_job(job)
                    self._waiting.append(job)
                    continue
                if persisted.state == JobState.QUEUED and payload_path.is_file():
                    try:
                        payload = QueuePayload.model_validate_json(
                            payload_path.read_text(encoding="utf-8")
                        )
                    except (ValueError, OSError):
                        payload = None
                    if payload is not None:
                        known.add(directory.name)
                        job = self._add(directory, persisted)
                        job.payload = payload
                        self._waiting.append(job)
                        continue
                persisted = persisted.model_copy(
                    update={
                        "state": JobState.FAILED,
                        "finished_at": utc_now_iso(),
                        "message": INTERRUPTED_MESSAGE,
                        "current_stage": None,
                    }
                )
                try:
                    self._queue_payload_path(directory.name).unlink()
                except (FileNotFoundError, OSError):
                    pass
            known.add(directory.name)
            self._add(directory, persisted)

        revived: list[tuple[PersistedJob, QueuePayload]] = []
        for path in sorted(self.queue_dir.glob("*.json"), key=lambda p: p.name):
            if path.is_symlink():
                LOGGER.warning("Rejected queue file %s (symlink)", path.name)
                continue
            if path.stem in known:
                continue
            try:
                payload = QueuePayload.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except Exception as exc:
                LOGGER.warning(
                    "Rejected queue file %s (schema: %s)", path.name, _say(exc)
                )
                continue
            revived.append(
                (
                    PersistedJob(
                        job_id=path.stem,
                        source=JobSource.WEB,
                        state=JobState.QUEUED,
                        company=payload.company,
                        role=payload.role,
                        options=JobOptions(
                            bridge_skills=payload.bridge_skills,
                            research_company=payload.research_company,
                            no_pdf=payload.no_pdf,
                            provider_mode=payload.provider_mode,
                            freellm_model=payload.freellm_model,
                        ),
                        created_at=payload.created_at,
                        idempotency_key=payload.idempotency_key,
                        request_fingerprint=payload.request_fingerprint,
                    ),
                    payload,
                )
            )
        revived.sort(key=lambda pair: (pair[1].created_at, pair[0].job_id))
        for persisted, payload in revived:
            job = self._add(self.output_dir / persisted.job_id, persisted)
            job.payload = payload
            self._ensure_job_file(job)
            self._waiting.append(job)

        self._waiting.sort(
            key=lambda job: (job.persisted.created_at, job.persisted.job_id)
        )

    def _ensure_job_file(self, job: Job) -> None:
        if not (job.directory / JOB_FILE).is_file():
            self._persist_job(job)

    def _add(self, directory: Path, persisted: PersistedJob) -> Job:
        journal = EventJournal(directory / EVENT_FILE)
        job = Job(
            persisted=persisted,
            directory=directory,
            journal=journal,
            reporter=WebProgressReporter(
                journal, self.hub, persisted.job_id, on_stage=self._note_stage
            ),
        )
        self._jobs[persisted.job_id] = job
        return job

    def _note_stage(self, job_id: str, stage: str | None) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.persisted.state != JobState.RUNNING:
            return
        job.persisted = job.persisted.model_copy(update={"current_stage": stage})
        self._persist_job(job)

    # -- queries ---------------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        with self._mutex:
            return self._jobs.get(job_id)

    def items(self) -> list[Job]:
        with self._mutex:
            return sorted(
                self._jobs.values(),
                key=lambda job: job.persisted.created_at,
                reverse=True,
            )

    def artifacts(self, job: Job) -> list[str]:
        return sorted(_artifacts(job.directory))

    def active_job_id(self) -> str | None:
        with self._mutex:
            return self._active

    def is_paused(self) -> bool:
        with self._mutex:
            return self._paused

    def queue_count(self) -> int:
        with self._mutex:
            return len(self._waiting)

    def find_idempotent(self, key: str) -> Job | None:
        with self._mutex:
            return next(
                (
                    job
                    for job in self._jobs.values()
                    if job.persisted.idempotency_key == key
                ),
                None,
            )

    def matches_fingerprint(self, job: Job, fingerprint: str) -> bool:
        return job.persisted.request_fingerprint == fingerprint

    def queue_position(self, job: Job) -> int | None:
        with self._mutex:
            try:
                return self._waiting.index(job) + 1
            except ValueError:
                return None

    def bullet_review(self, job: Job) -> BulletReviewResponse:
        if job.persisted.state != JobState.ACTION_REQUIRED:
            raise RecoveryRequestError(409, "This job is not waiting for a bullet review.")
        try:
            return load_bullet_review_response(job.directory)
        except Exception as exc:
            LOGGER.warning(
                "Could not load bullet review for job %s: %s",
                job.persisted.job_id,
                _say(exc),
            )
            raise RecoveryRequestError(
                409, "Review items are unavailable; reload the job before retrying."
            ) from exc

    def recovery(self, job: Job) -> FitRecoveryResponse:
        if job.persisted.state != JobState.ACTION_REQUIRED:
            raise RecoveryRequestError(
                409, "This job is not waiting for a fit-recovery choice."
            )
        try:
            return load_recovery_response(job.directory)
        except RecoveryRequestError:
            raise
        except Exception as exc:
            LOGGER.warning(
                "Could not load fit recovery for job %s: %s",
                job.persisted.job_id,
                _say(exc),
            )
            raise RecoveryRequestError(
                409,
                "Fit-recovery options are unavailable; reload the job before retrying.",
            ) from exc

    # -- queue mutations -------------------------------------------------------

    # -- skill check -------------------------------------------------------------

    def load_master(self) -> JSONResume:
        with self.master_lock:
            return load_master(self.master_path)

    def run_skill_check(self, request: SkillCheckRequest) -> SkillCheckResponse:
        """Parse + map the JD ahead of a job and list skills to confirm."""
        check_id = uuid.uuid4().hex
        directory = self.skill_checks_dir / check_id
        directory.mkdir(parents=True)
        options = JobOptions(
            provider_mode=request.provider_mode, freellm_model=request.freellm_model
        )
        pipeline = self.pipeline_factory(
            **self._model_kwargs(options),
            call_interval=self.call_interval,
            provider=self.provider,
            **({"college_mode": True} if request.college_mode else {}),
        )
        result = pipeline.check_skills(self.load_master(), request.jd_text, directory)
        atomic_write_text(
            directory / SKILL_CHECK_FILE,
            json.dumps({"jd_sha256": _sha256(request.jd_text)}),
            mode=0o600,
        )
        return SkillCheckResponse(check_id=check_id, **result.model_dump())

    def skill_answers(self) -> SkillAnswersResponse:
        master = self.load_master()
        return SkillAnswersResponse(
            confirmed=confirmed_terms(master), declined=declined_terms(master)
        )

    def save_skill_answers(self, answers: SkillAnswers, *, replace: bool) -> None:
        with self.master_lock:
            master = load_master(self.master_path)
            update = replace_answers if replace else apply_answers
            save_master(update(master, answers.confirmed, answers.declined), self.master_path)

    def _skill_check_checkpoints(self, check_id: str | None, jd_text: str) -> Path | None:
        """The check's checkpoint folder when it exists and matches this JD."""
        if not check_id:
            return None
        directory = self.skill_checks_dir / check_id
        try:
            record = json.loads((directory / SKILL_CHECK_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(record, dict) or record.get("jd_sha256") != _sha256(jd_text):
            return None
        checkpoints = directory / CHECKPOINT_DIR
        return checkpoints if checkpoints.is_dir() else None

    def enqueue(self, request: CreateJobRequest, idempotency_key: str) -> Job:
        options = JobOptions(
            bridge_skills=request.bridge_skills,
            research_company=request.research_company,
            no_pdf=request.no_pdf,
            provider_mode=request.provider_mode,
            freellm_model=request.freellm_model,
            college_mode=request.college_mode,
        )
        payload = QueuePayload(
            company=request.company,
            role=request.role,
            jd_text=request.jd_text,
            bridge_skills=request.bridge_skills,
            research_company=request.research_company,
            no_pdf=request.no_pdf,
            provider_mode=request.provider_mode,
            freellm_model=request.freellm_model,
            college_mode=request.college_mode,
            idempotency_key=idempotency_key,
            request_fingerprint=job_fingerprint(request, options),
        )
        persisted = PersistedJob(
            job_id=new_job_id(),
            source=JobSource.WEB,
            state=JobState.QUEUED,
            company=request.company,
            role=request.role,
            options=options,
            idempotency_key=idempotency_key,
            request_fingerprint=payload.request_fingerprint,
        )
        directory = self.output_dir / persisted.job_id
        reused = self._skill_check_checkpoints(
            getattr(request, "skill_check_id", None), request.jd_text
        )
        if reused is not None:
            target = directory / CHECKPOINT_DIR
            target.mkdir(parents=True, exist_ok=True)
            for source in reused.glob("*.json"):
                shutil.copyfile(source, target / source.name)
            payload.resume = True
        journal = EventJournal(directory / EVENT_FILE)
        job = Job(
            persisted=persisted,
            directory=directory,
            journal=journal,
            reporter=WebProgressReporter(
                journal, self.hub, persisted.job_id, on_stage=self._note_stage
            ),
            payload=payload,
        )
        with self._cond:
            if self._stopping:
                raise RecoveryRequestError(503, "Server is restarting. Retry shortly.")
            if len(self._waiting) >= 100:
                raise RecoveryRequestError(
                    429, "The queue is full. Wait for a job to finish."
                )
            self._persist_payload(job)
            atomic_write_text(
                self.requests_dir / f"{persisted.job_id}.json",
                payload.model_dump_json(),
                mode=0o600,
            )
            self._persist_job(job)
            self._jobs[persisted.job_id] = job
            self._waiting.append(job)
            self._cond.notify_all()
        self._publish_queue_changed()
        return job

    def enqueue_recovery(
        self,
        job: Job,
        request: FitRecoveryRequest,
        idempotency_key: str,
    ) -> tuple[RecoverySubmissionResponse, bool]:
        """Validate and queue one recovery pass; returns ``(response, replayed)``."""

        def build() -> RecoveryQueuePayload:
            recovery = load_recovery_response(job.directory)
            if request.revision != recovery.revision:
                raise RecoveryRequestError(
                    409,
                    "These fit-recovery options are stale; reload and review the latest revision.",
                )
            issued = {candidate.candidate_id for candidate in recovery.candidates}
            if set(request.candidate_ids) - issued:
                raise RecoveryRequestError(
                    422,
                    "One or more candidate IDs were not issued for this recovery revision.",
                )
            return RecoveryQueuePayload(
                revision=request.revision,
                candidate_ids=request.candidate_ids,
                idempotency_key=idempotency_key,
                request_fingerprint=job_fingerprint_for_recovery(request),
            )

        return self._enqueue_user_action(
            job,
            idempotency_key,
            job_fingerprint_for_recovery(request),
            build,
            "User-approved removals queued.",
        )

    def enqueue_bullet_review(
        self,
        job: Job,
        request: BulletReviewRequest,
        idempotency_key: str,
    ) -> tuple[RecoverySubmissionResponse, bool]:
        """Validate and queue the user's per-bullet review choices."""
        fingerprint = job_fingerprint_for_review(request)

        def build() -> RecoveryQueuePayload:
            review = load_bullet_review_response(job.directory)
            if request.revision != review.revision:
                raise RecoveryRequestError(
                    409, "These review items are stale; reload the job."
                )
            items = {item.flag_id: item for item in review.items}
            if set(request.decisions) - set(items):
                raise RecoveryRequestError(
                    422, "One or more review items were not issued for this job."
                )
            for flag_id, choice in request.decisions.items():
                if choice == "keep" and not items[flag_id].can_keep:
                    raise RecoveryRequestError(
                        422, f"'{items[flag_id].label}' cannot be kept as written."
                    )
            return RecoveryQueuePayload(
                operation="bullet_review",
                revision=request.revision,
                candidate_ids=sorted(request.decisions),
                decisions=dict(request.decisions),
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
            )

        return self._enqueue_user_action(
            job, idempotency_key, fingerprint, build, "Bullet review choices queued."
        )

    def enqueue_resume(self, job: Job) -> Job:
        """Queue a failed web run again, reusing the stages it already finished."""
        path = self.requests_dir / f"{job.persisted.job_id}.json"
        with self._cond:
            if job.persisted.state != JobState.FAILED:
                raise RecoveryRequestError(409, "Only a failed run can be resumed.")
            if job.persisted.source != JobSource.WEB or not path.is_file():
                raise RecoveryRequestError(
                    404,
                    "This run has no saved job description to resume from.",
                )
            if self._stopping:
                raise RecoveryRequestError(503, "Server is restarting. Retry shortly.")
            payload = QueuePayload.model_validate_json(path.read_text(encoding="utf-8"))
            job.payload = payload.model_copy(update={"resume": True})
            job.persisted = job.persisted.model_copy(
                update={
                    "state": JobState.QUEUED,
                    "finished_at": None,
                    "current_stage": None,
                    "message": None,
                }
            )
            self._persist_payload(job)
            self._persist_job(job)
            self._waiting.append(job)
            job.reporter.write_job_boundary(
                "job_recovery_queued", message="Resuming from the last finished stage."
            )
            self._cond.notify_all()
        self._publish_queue_changed()
        return job

    def _enqueue_user_action(
        self,
        job: Job,
        idempotency_key: str,
        fingerprint: str,
        build: Callable[[], RecoveryQueuePayload],
        queued_message: str,
    ) -> tuple[RecoverySubmissionResponse, bool]:
        """Shared idempotent queueing for a paused job's user decision."""
        with self._cond:
            store = self._load_recovery_idempotency(job)
            existing = next(
                (record for record in store.records if record.key == idempotency_key),
                None,
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise RecoveryRequestError(
                        422,
                        "Idempotency-Key was used with a different request.",
                    )
                if existing.status == "in_progress":
                    raise RecoveryRequestError(
                        409, "An identical request is already in progress."
                    )
                if existing.response_body is None:
                    raise RecoveryRequestError(
                        409, "The saved response is unavailable."
                    )
                return (
                    RecoverySubmissionResponse.model_validate(existing.response_body),
                    True,
                )
            if job.persisted.state != JobState.ACTION_REQUIRED:
                raise RecoveryRequestError(
                    409, "This job is not waiting for your decision."
                )
            payload = build()
            job.payload = payload
            job.persisted = job.persisted.model_copy(
                update={
                    "state": JobState.QUEUED,
                    "finished_at": None,
                    "current_stage": None,
                    "message": None,
                    "action_kind": None,
                }
            )
            self._persist_payload(job)
            self._persist_job(job)
            self._waiting.append(job)
            response = RecoverySubmissionResponse(
                job_id=job.persisted.job_id,
                queue_position=len(self._waiting),
                status_url=f"/api/jobs/{job.persisted.job_id}",
            )
            store.records.append(
                RecoveryIdempotencyRecord(
                    key=idempotency_key,
                    request_fingerprint=fingerprint,
                    response_body=response.model_dump(mode="json"),
                )
            )
            self._persist_recovery_idempotency(job, store)
            job.reporter.write_job_boundary("job_recovery_queued", message=queued_message)
            self._cond.notify_all()
        self._publish_queue_changed()
        return response, False

    def pause(self) -> None:
        with self._cond:
            if self._paused:
                return
            self._paused = True
            self._persist_paused()
        if self.scheduler is not None:
            self.scheduler.set_paused(True)
        self._publish_queue_changed()

    def resume(self) -> None:
        with self._cond:
            if not self._paused:
                return
            self._paused = False
            self._persist_paused()
            self._cond.notify_all()
        if self.scheduler is not None:
            self.scheduler.set_paused(False)
        self._publish_queue_changed()

    def remove_queued(self, job: Job) -> bool:
        """Remove only a waiting job; returns whether anything was removed."""
        with self._cond:
            if job not in self._waiting:
                return False
            self._waiting.remove(job)
            self._jobs.pop(job.persisted.job_id, None)
            try:
                self._queue_payload_path(job.persisted.job_id).unlink()
            except (FileNotFoundError, OSError):
                return False
            (job.directory / JOB_FILE).unlink(missing_ok=True)
            (self.requests_dir / f"{job.persisted.job_id}.json").unlink(missing_ok=True)
            self._cond.notify_all()
        self._publish_queue_changed()
        return True

    # -- cleanup ---------------------------------------------------------------

    def _pdf_copies(self, job: Job) -> list[Path]:
        """The job's PDF-library copy: its recorded name, else any ``* - <id8>.pdf``."""
        named = job.persisted.pdf_library_name
        if named:
            return [self.pdf_dir / named]
        suffix = f" - {job.persisted.job_id[:8]}"
        try:
            return [p for p in self.pdf_dir.iterdir() if p.stem.endswith(suffix)]
        except OSError:
            return []

    def _legacy_entries(self) -> list[Path]:
        try:
            entries = sorted(self.output_dir.iterdir())
        except OSError:
            return []
        return [
            path
            for path in entries
            if not path.name.startswith(".")
            and (path.is_symlink() or path.is_dir())
            and not (path / JOB_FILE).is_file()
        ]

    def cleanup_inventory(self) -> CleanupInventory:
        with self._mutex:
            finished = [
                job
                for job in self._jobs.values()
                if job.persisted.state in _DELETABLE_STATES
            ]
        finished.sort(key=lambda job: job.persisted.created_at, reverse=True)
        jobs = [
            CleanupItem(
                id=job.persisted.job_id,
                label=f"{job.persisted.company}, {job.persisted.role}",
                bytes=_tree_bytes(job.directory)
                + sum(_tree_bytes(p) for p in self._pdf_copies(job)),
            )
            for job in finished
        ]
        legacy = [
            CleanupItem(id=path.name, label=path.name, bytes=_tree_bytes(path))
            for path in self._legacy_entries()
            if not path.is_symlink()
        ]
        return CleanupInventory(jobs=jobs, legacy=legacy)

    def delete(self, request: CleanupRequest) -> CleanupResult:
        deleted_jobs: list[str] = []
        deleted_legacy: list[str] = []
        skipped: list[CleanupItem] = []
        freed = 0

        def skip(item_id: str, reason: str) -> None:
            skipped.append(CleanupItem(id=item_id, label=reason, bytes=0))

        for job_id in dict.fromkeys(request.job_ids):
            with self._cond:
                job = self._jobs.get(job_id)
                if job is None:
                    skip(job_id, "Not found")
                    continue
                if (
                    job.persisted.state not in _DELETABLE_STATES
                    or job in self._waiting
                    or self._active == job_id
                ):
                    skip(job_id, "Running or queued, can't delete")
                    continue
                directory = job.directory
                if directory.is_symlink() or not _within(directory, self.output_dir):
                    skip(job_id, "Folder is a link or outside the output folder")
                    continue
            removed = self._remove_job_files(job, skipped)
            if removed is None:
                skip(job_id, "Couldn't delete")
                continue
            with self._cond:
                self._jobs.pop(job_id, None)
            freed += removed
            deleted_jobs.append(job_id)

        if request.include_legacy:
            for path in self._legacy_entries():
                if path.is_symlink() or not _within(path, self.output_dir):
                    skip(path.name, "Link or outside the output folder, left alone")
                    continue
                size = _tree_bytes(path)
                try:
                    shutil.rmtree(path)
                except OSError:
                    skip(path.name, "Couldn't delete")
                    continue
                freed += size
                deleted_legacy.append(path.name)

        if deleted_jobs:
            self._publish_queue_changed()
        return CleanupResult(
            deleted_jobs=deleted_jobs,
            deleted_legacy=deleted_legacy,
            skipped=skipped,
            freed_bytes=freed,
        )

    def _remove_job_files(self, job: Job, skipped: list[CleanupItem]) -> int | None:
        """Delete a job's files; None when its folder could not be removed."""
        job_id = job.persisted.job_id
        size = _tree_bytes(job.directory)
        try:
            shutil.rmtree(job.directory)
        except OSError:
            return None
        freed = size
        candidates = [(p, self.pdf_dir) for p in self._pdf_copies(job)] + [
            (self._queue_payload_path(job_id), self.state_dir),
            (self.requests_dir / f"{job_id}.json", self.state_dir),
        ]
        for path, root in candidates:
            if path.is_symlink():
                skipped.append(
                    CleanupItem(
                        id=job_id, label=f"Symlink, not deleted: {path.name}", bytes=0
                    )
                )
                continue
            if not path.is_file() or not _within(path, root):
                continue
            size = _tree_bytes(path)
            try:
                path.unlink()
            except OSError:
                skipped.append(
                    CleanupItem(
                        id=job_id, label=f"Couldn't delete: {path.name}", bytes=0
                    )
                )
                continue
            freed += size
        return freed

    # -- snapshots -------------------------------------------------------------

    def snapshot(self, tracker: TrackerSnapshot | None = None) -> QueueSnapshot:
        with self._mutex:
            waiting = [
                QueuedEntry(
                    job_id=job.persisted.job_id,
                    company=job.persisted.company,
                    role=job.persisted.role,
                    source=job.persisted.source.value,
                    queue_position=index + 1,
                    created_at=job.persisted.created_at,
                )
                for index, job in enumerate(self._waiting)
            ]
            return QueueSnapshot(
                state="paused" if self._paused else "running",
                active_job_id=self._active,
                queue_count=len(self._waiting),
                waiting=waiting,
                tracker=tracker or TrackerSnapshot(active=False),
            )

    def entry(self, job: Job) -> JobEntry:
        persisted = job.persisted
        return JobEntry(
            job_id=persisted.job_id,
            company=persisted.company,
            role=persisted.role,
            source=persisted.source.value,
            state=persisted.state.value,
            options=persisted.options,
            queue_position=self.queue_position(job),
            created_at=persisted.created_at,
            started_at=persisted.started_at,
            finished_at=persisted.finished_at,
            elapsed_seconds=_elapsed(persisted.started_at, persisted.finished_at),
            current_stage=persisted.current_stage,
            message=persisted.message,
            artifacts=self.artifacts(job),
            pdf_library_name=persisted.pdf_library_name,
            export_warning=persisted.export_warning,
            action_kind=persisted.action_kind,
            active=self._active == persisted.job_id,
        )

    # -- worker loop -----------------------------------------------------------

    def _worker_loop(self) -> None:
        while True:
            with self._cond:
                while not self._stopping and not self._can_start():
                    self._cond.wait(timeout=0.5)
                if self._stopping:
                    return
                job = self._waiting.pop(0)
                self._active = job.persisted.job_id
                self._claim(job)
            self._publish_queue_changed()
            try:
                self._run_job(job)
            finally:
                with self._cond:
                    self._active = None
                    self._cond.notify_all()
                self._publish_queue_changed()

    def _can_start(self) -> bool:
        return not self._paused and self._active is None and bool(self._waiting)

    def _claim(self, job: Job) -> None:
        """Transition to running and drop the private queued request."""
        job.persisted = job.persisted.model_copy(
            update={
                "state": JobState.RUNNING,
                "started_at": job.persisted.started_at or utc_now_iso(),
            }
        )
        self._persist_job(job)
        if not isinstance(job.payload, RecoveryQueuePayload):
            try:
                self._queue_payload_path(job.persisted.job_id).unlink()
            except (FileNotFoundError, OSError):
                pass

    def _model_kwargs(self, options: JobOptions) -> dict[str, object]:
        """Model chain for a job's provider mode; Gemini keeps the app's model."""
        if options.provider_mode == "gemini":
            return {"model": self.model}
        return resolve_chains(
            options.provider_mode, options.freellm_model
        ).pipeline_kwargs()

    def _run_job(self, job: Job) -> None:
        context = JobContext(name=job.persisted.job_id, output_dir=job.directory)
        started = time.monotonic()
        job.reporter.write_job_boundary("job_started")
        payload = job.payload
        assert payload is not None
        if isinstance(payload, RecoveryQueuePayload):
            self._run_recovery(job, payload, started)
            return
        try:
            master = self.load_master()
            pipeline = self.pipeline_factory(
                **self._model_kwargs(job.persisted.options),
                call_interval=self.call_interval,
                provider=self.provider,
                reporter=job.reporter,
                bridge_skills=payload.bridge_skills,
                research_company=payload.research_company,
                allow_fit_recovery=True,
                **({"college_mode": True} if payload.college_mode else {}),
            )
            exit_code = pipeline.run(
                master,
                payload.jd_text,
                job.directory,
                no_pdf=payload.no_pdf,
                job=context,
                # Only pass the flag when set, so pipeline stand-ins without it work.
                **({"resume": True} if payload.resume else {}),
            )
        except Exception as exc:
            if self._transition_to_action_required(job, started):
                return
            if is_quota_error(exc):
                self._finish(job, JobState.FAILED, _QUOTA_MESSAGE, started)
                self.pause()
                return
            self._finish(job, JobState.FAILED, _say(exc), started)
            return
        if exit_code != 0:
            if self._transition_to_action_required(job, started):
                return
            self._finish(
                job,
                JobState.FAILED,
                "Tailoring finished with unresolved findings.",
                started,
            )
            return
        if not payload.no_pdf:
            self._copy_to_pdf_library(job)
        self._finish(job, JobState.COMPLETED, None, started)

    @staticmethod
    def _default_recovery_handler(directory: Path, candidate_ids: list[str]) -> int:
        from ..fit_recovery import apply_fit_recovery

        return apply_fit_recovery(directory, candidate_ids)

    def _apply_bullet_review(self, job: Job, payload: RecoveryQueuePayload) -> int:
        from ..bullet_review import apply_bullet_review

        regenerate = None
        if "regenerate" in payload.decisions.values():
            pipeline = self.pipeline_factory(
                **self._model_kwargs(job.persisted.options),
                call_interval=self.call_interval,
                provider=self.provider,
                reporter=job.reporter,
                allow_fit_recovery=True,
            )
            pipeline.tracker.job = JobContext(
                name=job.persisted.job_id, output_dir=job.directory
            )
            pipeline.privacy.protect(load_master(self.master_path))
            regenerate = pipeline.regenerate_review_bullet
        return apply_bullet_review(
            job.directory,
            payload.decisions,
            regenerate=regenerate,
            progress=lambda message: job.reporter.write_job_boundary(
                "job_recovery_started", message=message
            ),
        )

    def _run_recovery(
        self, job: Job, payload: RecoveryQueuePayload, started: float
    ) -> None:
        reviewing = payload.operation == "bullet_review"
        job.reporter.write_job_boundary(
            "job_recovery_started",
            message=(
                "Applying your bullet review choices."
                if reviewing
                else "Applying user-approved removals."
            ),
        )
        try:
            exit_code = (
                self._apply_bullet_review(job, payload)
                if reviewing
                else self.recovery_handler(job.directory, payload.candidate_ids)
            )
            if exit_code == 0:
                if not job.persisted.options.no_pdf:
                    self._copy_to_pdf_library(job)
                self._finish(job, JobState.COMPLETED, None, started)
            elif exit_code == 2 and self._transition_to_action_required(job, started):
                pass
            else:
                self._finish(
                    job,
                    JobState.FAILED,
                    "Applying your choices did not produce a valid result.",
                    started,
                )
        except Exception as exc:
            self._finish(job, JobState.FAILED, _say(exc), started)
        finally:
            self._complete_recovery_idempotency(job, payload.idempotency_key)
            try:
                self._queue_payload_path(job.persisted.job_id).unlink()
            except (FileNotFoundError, OSError):
                pass

    def _transition_to_action_required(self, job: Job, started: float) -> bool:
        from ..bullet_review import BULLET_REVIEW_FILENAME

        if (job.directory / BULLET_REVIEW_FILENAME).is_file():
            try:
                review = load_bullet_review_response(job.directory)
            except Exception:
                return False
            kind = "bullet_review"
            count = len(review.items)
            message = (
                f"{count} bullet{'s' if count != 1 else ''} need your decision "
                "before the resume is rendered."
            )
        else:
            try:
                load_recovery_response(job.directory)
            except Exception:
                return False
            kind = "fit_recovery"
            message = "The resume still spans two pages. Review suggested content removals."
        elapsed = round(time.monotonic() - started, 2)
        job.reporter.write_job_boundary(
            "job_action_required", message=message, elapsed=elapsed
        )
        job.persisted = job.persisted.model_copy(
            update={
                "state": JobState.ACTION_REQUIRED,
                "finished_at": utc_now_iso(),
                "message": message,
                "current_stage": None,
                "action_kind": kind,
            }
        )
        self._persist_job(job)
        return True

    def _complete_recovery_idempotency(self, job: Job, key: str) -> None:
        with self._mutex:
            try:
                store = self._load_recovery_idempotency(job)
            except RecoveryRequestError:
                return
            records = [
                (
                    record.model_copy(update={"status": "completed"})
                    if record.key == key
                    else record
                )
                for record in store.records
            ]
            self._persist_recovery_idempotency(
                job, store.model_copy(update={"records": records})
            )

    def _copy_to_pdf_library(self, job: Job) -> None:
        """Copy, never move, the original PDF. Failures are warnings, not failures."""
        source = job.directory / "resume.pdf"
        if not source.is_file():
            job.persisted = job.persisted.model_copy(
                update={"export_warning": PDF_EXPORT_WARNING}
            )
            return
        target = self.pdf_dir / pdf_library_name(
            job.persisted.company,
            job.persisted.role,
            job.persisted.job_id,
            job.persisted.created_at,
        )
        if target.exists():
            return
        try:
            self.pdf_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        except OSError:
            job.persisted = job.persisted.model_copy(
                update={"export_warning": PDF_EXPORT_WARNING}
            )
            return
        job.persisted = job.persisted.model_copy(
            update={"pdf_library_name": target.name}
        )

    def _finish(
        self, job: Job, state: JobState, message: str | None, started: float
    ) -> None:
        elapsed = round(time.monotonic() - started, 2)
        job.reporter.write_job_boundary(
            "job_completed" if state == JobState.COMPLETED else "job_failed",
            message=message,
            elapsed=elapsed,
        )
        job.persisted = job.persisted.model_copy(
            update={
                "state": state,
                "finished_at": utc_now_iso(),
                "message": message,
                "current_stage": None,
            }
        )
        self._persist_job(job)

    # -- stream ----------------------------------------------------------------

    def _publish_queue_changed(self) -> None:
        tracker = self.scheduler.snapshot() if self.scheduler is not None else None
        self.hub.publish(
            StreamEvent(
                id=self.hub.next_id(),
                kind="queue_changed",
                data=self.snapshot(tracker=tracker).model_dump(mode="json"),
            )
        )
