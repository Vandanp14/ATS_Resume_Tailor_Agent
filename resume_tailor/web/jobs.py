"""Persistent FIFO queue registry, one worker loop, restart hydration, PDF library.

Owns all jobs for one server process. Waiting jobs persist as private request
payloads beneath the state directory; job metadata and journals live in
``output/<job-id>/``. Starts at most one pipeline at a time through a single
long-lived worker loop woken by a condition.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..batch import is_quota_error
from ..pipeline import TailorPipeline
from ..progress import JobContext
from ..runtime import load_master
from .io import atomic_write_text, private_directory
from .models import (
    ARTIFACT_ALLOWLIST,
    EVENT_FILE,
    FIT_RECOVERY_IDEMPOTENCY_FILE,
    INTERRUPTED_MESSAGE,
    JOB_FILE,
    PDF_EXPORT_WARNING,
    QUEUE_DIR_NAME,
    QUEUE_STATE_FILE,
    CreateJobRequest,
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
    new_job_id,
    pdf_library_name,
    utc_now_iso,
)
from .reporter import EventHub, EventJournal, WebProgressReporter
from .scheduler import GeminiScheduler, ScheduledProvider

LOGGER = logging.getLogger("resume_tailor.web")
MAX_SAFE_MESSAGE = 500
_QUOTA_MESSAGE = "Gemini quota exhausted (429); the queue is paused. Resume it when the quota is available again."


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


def _say(exc: BaseException) -> str:
    return (str(exc).strip() or exc.__class__.__name__)[:MAX_SAFE_MESSAGE]


def _artifacts(directory: Path) -> list[str]:
    return [name for name in ARTIFACT_ALLOWLIST if (directory / name).is_file()]


def _cli_state(directory: Path) -> JobState | None:
    present = set(_artifacts(directory))
    if present & {"tailored.json", "resume.pdf", "resume.tex"}:
        return JobState.COMPLETED
    if (directory / "diagnostic_report.json").is_file():
        return JobState.FAILED
    return None


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

        for directory in sorted(self.output_dir.iterdir()):
            if not directory.is_dir() or (directory / JOB_FILE).is_file():
                continue
            state = _cli_state(directory)
            if state is not None:
                self._add(
                    directory,
                    PersistedJob(
                        job_id=directory.name,
                        source=JobSource.CLI,
                        state=state,
                        company=directory.name,
                        role="CLI run",
                        created_at=utc_now_iso(),
                    ),
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

    def enqueue(self, request: CreateJobRequest, idempotency_key: str) -> Job:
        options = JobOptions(
            bridge_skills=request.bridge_skills,
            research_company=request.research_company,
            no_pdf=request.no_pdf,
        )
        payload = QueuePayload(
            company=request.company,
            role=request.role,
            jd_text=request.jd_text,
            bridge_skills=request.bridge_skills,
            research_company=request.research_company,
            no_pdf=request.no_pdf,
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
        fingerprint = job_fingerprint_for_recovery(request)
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
                        "Idempotency-Key was used with a different recovery request.",
                    )
                if existing.status == "in_progress":
                    raise RecoveryRequestError(
                        409, "An identical recovery request is already in progress."
                    )
                if existing.response_body is None:
                    raise RecoveryRequestError(
                        409, "The saved recovery response is unavailable."
                    )
                return (
                    RecoverySubmissionResponse.model_validate(existing.response_body),
                    True,
                )
            if job.persisted.state != JobState.ACTION_REQUIRED:
                raise RecoveryRequestError(
                    409, "This job is not waiting for a fit-recovery choice."
                )
            recovery = load_recovery_response(job.directory)
            if request.revision != recovery.revision:
                raise RecoveryRequestError(
                    409,
                    "These fit-recovery options are stale; reload and review the latest revision.",
                )
            issued = {candidate.candidate_id for candidate in recovery.candidates}
            unknown = sorted(set(request.candidate_ids) - issued)
            if unknown:
                raise RecoveryRequestError(
                    422,
                    "One or more candidate IDs were not issued for this recovery revision.",
                )
            payload = RecoveryQueuePayload(
                revision=request.revision,
                candidate_ids=request.candidate_ids,
                idempotency_key=idempotency_key,
                request_fingerprint=fingerprint,
            )
            job.payload = payload
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
            job.reporter.write_job_boundary(
                "job_recovery_queued", message="User-approved removals queued."
            )
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
            master = load_master(self.master_path)
            pipeline = self.pipeline_factory(
                model=self.model,
                call_interval=self.call_interval,
                provider=self.provider,
                reporter=job.reporter,
                bridge_skills=payload.bridge_skills,
                research_company=payload.research_company,
                allow_fit_recovery=True,
            )
            exit_code = pipeline.run(
                master,
                payload.jd_text,
                job.directory,
                no_pdf=payload.no_pdf,
                job=context,
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

    def _run_recovery(
        self, job: Job, payload: RecoveryQueuePayload, started: float
    ) -> None:
        job.reporter.write_job_boundary(
            "job_recovery_started", message="Applying user-approved removals."
        )
        try:
            exit_code = self.recovery_handler(job.directory, payload.candidate_ids)
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
                    "Fit recovery did not produce a valid result.",
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
        try:
            load_recovery_response(job.directory)
        except Exception:
            return False
        elapsed = round(time.monotonic() - started, 2)
        message = "The resume still spans two pages. Review suggested content removals."
        job.reporter.write_job_boundary(
            "job_action_required", message=message, elapsed=elapsed
        )
        job.persisted = job.persisted.model_copy(
            update={
                "state": JobState.ACTION_REQUIRED,
                "finished_at": utc_now_iso(),
                "message": message,
                "current_stage": None,
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
