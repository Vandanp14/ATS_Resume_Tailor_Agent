"""FastAPI application factory, routes, app-wide event stream, and security headers."""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from queue import Empty
from typing import Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..config import DEFAULT_MODEL
from ..pipeline import TailorPipeline
from ..runtime import DEFAULT_CALL_INTERVAL, load_master
from models import JSONResume
from .jobs import Job, JobState, QueueRegistry, RecoveryRequestError
from .models import (
    ARTIFACT_ALLOWLIST,
    CALLS_FILE,
    DEFAULT_MAX_CALLS_PER_MINUTE,
    DEFAULT_MAX_INPUT_TOKENS_PER_MINUTE,
    DEFAULT_MAX_REQUESTS_PER_DAY,
    CreateJobRequest,
    CreateJobResponse,
    BulletReviewRequest,
    BulletReviewResponse,
    FitRecoveryRequest,
    FitRecoveryResponse,
    JobDetail,
    JobEntry,
    JobOptions,
    JobSource,
    MetaResponse,
    ProblemDetails,
    QueueSnapshot,
    RecoverySubmissionResponse,
    TrackerSnapshot,
    job_fingerprint,
)
from .reporter import EventHub
from .scheduler import GeminiScheduler, ScheduledProvider, inactive_tracker
from .access import AccessSettings, Sessions
from .review import ReviewDecision, read_review
from .io import atomic_write_text

LOGGER = __import__("logging").getLogger("resume_tailor.web")

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "frame-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'"
    ),
}
_MEDIA = {
    "resume.pdf": "application/pdf",
    "resume.tex": "application/x-tex",
    "tailored.json": "application/json",
    "match_report.json": "application/json",
    "diagnostic_report.json": "application/json",
}
_EVENT_KINDS = {
    "queue_changed",
    "job_started",
    "stage_started",
    "stage_completed",
    "stage_retry",
    "stage_detail",
    "stage_warning",
    "job_completed",
    "job_failed",
    "job_action_required",
    "job_recovery_queued",
    "job_recovery_started",
    "tracker_changed",
}


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    password: str = Field(min_length=1, max_length=256)


@dataclass
class WebSettings:
    master_path: Path
    output_dir: Path
    pdf_dir: Path
    state_dir: Path
    model: str
    call_interval: float
    max_calls_per_minute: int
    max_input_tokens_per_minute: int
    max_requests_per_day: int
    static_dir: Path
    access: AccessSettings = AccessSettings()


def _problem(
    status: int,
    title: str,
    detail: str,
    instance: str | None = None,
    errors: list[dict[str, object]] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ProblemDetails(
            title=title, status=status, detail=detail, instance=instance, errors=errors
        ).as_json(),
        headers={"Cache-Control": "no-store"},
        media_type="application/problem+json",
    )


def _is_gemini(model: str) -> bool:
    return str(model).startswith("gemini")


def create_app(
    settings: WebSettings,
    registry: QueueRegistry,
    master: JSONResume,
    hub: EventHub,
    scheduler: GeminiScheduler | None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app):
        yield
        registry.stop()
        if registry._worker is not None:
            await asyncio.to_thread(registry._worker.join, 20)

    app = FastAPI(
        title="ATS Resume Tailor Agent",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    sessions = Sessions(settings.access)
    login_lock = asyncio.Lock()
    app.state.registry = registry
    app.state.sessions = sessions
    pdf_available = registry.pdf_available
    basics = master.basics
    tracker = lambda: (
        scheduler.snapshot()
        if scheduler is not None
        else inactive_tracker(settings.model)
    )

    @app.middleware("http")
    async def host_origin_guard(request: Request, call_next):
        path = request.url.path
        host = request.headers.get("host", "")
        if path != "/healthz":
            if not settings.access.host_allowed(host):
                return _problem(
                    400, "Bad Request", "Unrecognized host.", instance=request.url.path
                )
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                origin = request.headers.get("origin")
                if not settings.access.origin_allowed(origin, host):
                    return _problem(403, "Forbidden", "Cross-origin request rejected.")
                content_type = request.headers.get("content-type", "")
                if content_type and "application/json" not in content_type:
                    return _problem(
                        415,
                        "Unsupported Media Type",
                        "API writes require application/json.",
                    )
                size = 0
                chunks = []
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 512_000:
                        return _problem(
                            413,
                            "Request too large",
                            "Reduce the request size and retry.",
                        )
                    chunks.append(chunk)
                request._body = b"".join(chunks)
        public = {
            "/healthz",
            "/login",
            "/login.js",
            "/app.css",
            "/ui.css",
            "/api/auth/login",
        }
        if settings.access.password_digest and path not in public:
            if not sessions.valid(request.cookies.get(settings.access.cookie_name, "")):
                if path.startswith("/api"):
                    return _problem(
                        401,
                        "Sign in required",
                        "Sign in to your workspace to continue.",
                    )
                return RedirectResponse("/login", status_code=303)
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for key, value in _HEADERS.items():
            response.headers.setdefault(key, value)
        response.headers["Cache-Control"] = "no-store"
        if settings.access.public_origin:
            response.headers["Strict-Transport-Security"] = "max-age=63072000"
        return response

    @app.get("/login")
    async def login_page():
        if not settings.access.password_digest:
            return RedirectResponse("/", status_code=303)
        return FileResponse(settings.static_dir / "login.html")

    @app.post("/api/auth/login")
    async def login(body: LoginRequest):
        if login_lock.locked() or not sessions.allowed_attempt():
            response = _problem(429, "Too many attempts", "Try again in one minute.")
            response.headers["Retry-After"] = "60"
            return response
        async with login_lock:
            verified = await asyncio.to_thread(sessions.verify, body.password)
        if not verified:
            return _problem(401, "Sign in failed", "The password was not recognized.")
        response = JSONResponse({"ready": True})
        response.set_cookie(
            settings.access.cookie_name,
            sessions.issue(),
            max_age=sessions.lifetime,
            secure=bool(settings.access.public_origin),
            httponly=True,
            samesite="strict",
        )
        return response

    @app.post("/api/auth/logout")
    async def logout(request: Request):
        sessions.tokens.pop(request.cookies.get(settings.access.cookie_name, ""), None)
        response = JSONResponse({"ready": False})
        response.delete_cookie(
            settings.access.cookie_name,
            secure=bool(settings.access.public_origin),
            httponly=True,
            samesite="strict",
        )
        return response

    @app.get("/healthz")
    async def health():
        ready = (
            registry._worker is not None
            and registry._worker.is_alive()
            and not registry._stopping
            and (pdf_available or not settings.access.public_origin)
            and all(
                os.access(path, os.W_OK)
                for path in (settings.output_dir, settings.pdf_dir, settings.state_dir)
            )
        )
        return JSONResponse({"ready": ready}, status_code=200 if ready else 503)

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "loc": ".".join(str(p) for p in error["loc"]),
                "message": str(error["msg"]),
            }
            for error in exc.errors()
        ]
        return _problem(
            422,
            "Unprocessable Entity",
            "Request validation failed.",
            instance=str(_request.url.path),
            errors=errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return _problem(
            exc.status_code,
            "Error",
            exc.detail if isinstance(exc.detail, str) else str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("Unhandled web error for %s", request.url.path)
        return _problem(
            500,
            "Internal Server Error",
            "An internal error occurred.",
            instance=str(request.url.path),
        )

    def job_or_404(job_id: str) -> Job:
        try:
            uuid.UUID(job_id)
        except ValueError:
            raise HTTPException(404, f"Unknown job: {job_id}")
        job = registry.get(job_id)
        if job is None:
            raise HTTPException(404, f"Unknown job: {job_id}")
        return job

    def queue_snapshot() -> QueueSnapshot:
        return registry.snapshot(tracker=tracker())

    # -- meta ------------------------------------------------------------------

    @app.get("/api/meta", response_model=MetaResponse)
    async def meta() -> MetaResponse:
        return MetaResponse(
            ready=True,
            auth_required=bool(settings.access.password_digest),
            master_name=basics.name if basics else None,
            master_email=basics.email if basics else None,
            model=settings.model,
            provider="gemini" if _is_gemini(settings.model) else settings.model,
            pdf_available=pdf_available,
            queue_state="paused" if registry.is_paused() else "running",
            active_job_id=registry.active_job_id(),
            directory_labels={
                "output_dir": str(registry.output_dir),
                "pdf_dir": str(registry.pdf_dir),
                "state_dir": str(registry.state_dir),
            },
            tracker=tracker(),
        )

    # -- jobs ------------------------------------------------------------------

    @app.post("/api/jobs", status_code=202)
    async def create_job(
        body: CreateJobRequest,
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            key = str(uuid.UUID(idempotency_key))
        except ValueError:
            raise HTTPException(422, "Idempotency-Key must be a UUID.")
        if not pdf_available and not body.no_pdf:
            raise HTTPException(
                422,
                "Tectonic is not installed; set no_pdf=true to run without PDF output.",
            )
        fingerprint = job_fingerprint(
            body,
            JobOptions(
                bridge_skills=body.bridge_skills,
                research_company=body.research_company,
                no_pdf=body.no_pdf,
            ),
        )
        existing = registry.find_idempotent(key)
        if existing is not None:
            if not registry.matches_fingerprint(existing, fingerprint):
                raise HTTPException(
                    422, "Idempotency-Key was used with a different request."
                )
            return created(existing.persisted.job_id)
        try:
            job = registry.enqueue(body, idempotency_key=key)
        except RecoveryRequestError as exc:
            raise HTTPException(exc.status, exc.detail) from exc
        return created(job.persisted.job_id, position=registry.queue_position(job) or 0)

    @app.get("/api/jobs", response_model=list[JobEntry])
    async def list_jobs() -> list[JobEntry]:
        return [registry.entry(job) for job in registry.items()]

    @app.get("/api/jobs/{job_id}", response_model=JobDetail)
    async def job_detail(job: Job = Depends(job_or_404)) -> JobDetail:
        return JobDetail(job=registry.entry(job), events=job.journal.replay())

    @app.get("/api/jobs/{job_id}/request", response_model=CreateJobRequest)
    async def original_request(job: Job = Depends(job_or_404)):
        from .models import QueuePayload

        path = registry.requests_dir / f"{job.persisted.job_id}.json"
        if not path.is_file() or path.is_symlink():
            raise HTTPException(
                404,
                "This older run has no saved job description. Paste the description into a new tailoring.",
            )
        payload = QueuePayload.model_validate_json(path.read_text(encoding="utf-8"))
        return CreateJobRequest(
            **{name: getattr(payload, name) for name in CreateJobRequest.model_fields}
        )

    @app.get("/api/jobs/{job_id}/review")
    async def review(job: Job = Depends(job_or_404)):
        try:
            return read_review(job.directory)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(
                409,
                "The report could not be read. Download the report or retry the run.",
            ) from exc

    @app.put("/api/jobs/{job_id}/review")
    async def save_review(body: ReviewDecision, job: Job = Depends(job_or_404)):
        current = await review(job)
        if job.persisted.state not in {
            JobState.COMPLETED,
            JobState.FAILED,
            JobState.ACTION_REQUIRED,
        }:
            raise HTTPException(409, "Wait for this run to finish before reviewing.")
        if current["revision"] != body.revision:
            raise HTTPException(
                409, "The report changed. Reload it before saving your review."
            )
        allowed = {item["id"] for item in current["claims"]}
        if not set(body.reviewed_ids) <= allowed or len(set(body.reviewed_ids)) != len(
            body.reviewed_ids
        ):
            raise HTTPException(422, "Select only claims in the current report.")
        atomic_write_text(
            job.directory / "review_decision.json", body.model_dump_json(), mode=0o600
        )
        return {"reviewed_ids": body.reviewed_ids}

    @app.get("/api/jobs/{job_id}/fit-recovery", response_model=FitRecoveryResponse)
    async def get_fit_recovery(job: Job = Depends(job_or_404)) -> FitRecoveryResponse:
        try:
            return registry.recovery(job)
        except RecoveryRequestError as exc:
            raise HTTPException(exc.status, exc.detail) from exc

    @app.post(
        "/api/jobs/{job_id}/fit-recovery",
        status_code=202,
        response_model=RecoverySubmissionResponse,
    )
    async def submit_fit_recovery(
        body: FitRecoveryRequest,
        job: Job = Depends(job_or_404),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            key = str(uuid.UUID(idempotency_key))
        except ValueError:
            raise HTTPException(422, "Idempotency-Key must be a UUID.")
        try:
            response, _replayed = registry.enqueue_recovery(job, body, key)
        except RecoveryRequestError as exc:
            raise HTTPException(exc.status, exc.detail) from exc
        return JSONResponse(
            status_code=202,
            content=response.model_dump(mode="json"),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/jobs/{job_id}/bullet-review", response_model=BulletReviewResponse)
    async def get_bullet_review(job: Job = Depends(job_or_404)) -> BulletReviewResponse:
        try:
            return registry.bullet_review(job)
        except RecoveryRequestError as exc:
            raise HTTPException(exc.status, exc.detail) from exc

    @app.post(
        "/api/jobs/{job_id}/bullet-review",
        status_code=202,
        response_model=RecoverySubmissionResponse,
    )
    async def submit_bullet_review(
        body: BulletReviewRequest,
        job: Job = Depends(job_or_404),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        try:
            key = str(uuid.UUID(idempotency_key))
        except ValueError:
            raise HTTPException(422, "Idempotency-Key must be a UUID.")
        try:
            response, _replayed = registry.enqueue_bullet_review(job, body, key)
        except RecoveryRequestError as exc:
            raise HTTPException(exc.status, exc.detail) from exc
        return JSONResponse(
            status_code=202,
            content=response.model_dump(mode="json"),
            headers={"Cache-Control": "no-store"},
        )

    @app.delete("/api/jobs/{job_id}", status_code=204)
    async def delete_job(job: Job = Depends(job_or_404)) -> Response:
        if job.persisted.state != JobState.QUEUED:
            raise HTTPException(409, "Only queued jobs can be removed.")
        registry.remove_queued(job)
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    # -- queue -----------------------------------------------------------------

    @app.get("/api/queue", response_model=QueueSnapshot)
    async def queue() -> QueueSnapshot:
        return queue_snapshot()

    @app.post("/api/queue/pause", response_model=QueueSnapshot)
    async def pause() -> QueueSnapshot:
        registry.pause()
        return queue_snapshot()

    @app.post("/api/queue/resume", response_model=QueueSnapshot)
    async def resume() -> QueueSnapshot:
        registry.resume()
        return queue_snapshot()

    # -- app-wide event stream -------------------------------------------------

    @app.get("/api/events", response_class=EventSourceResponse)
    async def events():
        subscriber = hub.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.to_thread(subscriber.queue.get, True, 1.0)
                except Empty:
                    continue
                yield ServerSentEvent(
                    data=event.model_dump(mode="json", exclude_none=True),
                    event=event.kind,
                    id=str(event.id),
                )
        finally:
            hub.detach(subscriber)

    # -- artifacts -------------------------------------------------------------

    @app.get("/api/jobs/{job_id}/files/{artifact}")
    async def artifact(
        job: Job = Depends(job_or_404), artifact: str = "", download: int = 1
    ) -> Response:
        if artifact not in ARTIFACT_ALLOWLIST:
            raise HTTPException(404, f"Unknown artifact: {artifact}")
        path = job.directory / artifact
        if not path.is_file():
            raise HTTPException(404, f"Artifact not available yet: {artifact}")
        return FileResponse(
            path,
            media_type=_MEDIA.get(artifact, "application/octet-stream"),
            filename=artifact,
            content_disposition_type=(
                "inline" if artifact == "resume.pdf" and download == 0 else "attachment"
            ),
            headers={"Cache-Control": "no-store"},
        )

    app.mount(
        "/", StaticFiles(directory=str(settings.static_dir), html=True), name="static"
    )
    return app


def created(job_id: str, position: int = 0) -> JSONResponse:
    return JSONResponse(
        status_code=202,
        content=CreateJobResponse(
            job_id=job_id,
            queue_position=position,
            status_url=f"/api/jobs/{job_id}",
            events_url="/api/events",
        ).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def webapp_factory(
    *,
    master_path: Path = Path("master.json"),
    output_dir: Path = Path("output"),
    pdf_dir: Path = Path("resumepdfs"),
    state_dir: Path = Path(".resume-tailor"),
    model: str = DEFAULT_MODEL,
    call_interval: float = DEFAULT_CALL_INTERVAL,
    max_calls_per_minute: int = DEFAULT_MAX_CALLS_PER_MINUTE,
    max_input_tokens_per_minute: int = DEFAULT_MAX_INPUT_TOKENS_PER_MINUTE,
    max_requests_per_day: int = DEFAULT_MAX_REQUESTS_PER_DAY,
    static_dir: Path | None = None,
    pipeline_factory: Callable[..., TailorPipeline] = TailorPipeline,
    recovery_handler: Callable[[Path, list[str]], int] | None = None,
    score_timeout: float | None = None,
    access: AccessSettings | None = None,
) -> FastAPI:
    """Assemble settings + shared scheduler + registry + app for entrypoint and tests."""
    del score_timeout  # Accepted for compatibility with the pre-queue web test harness.
    call_interval = max(float(call_interval), 0.0)
    max_calls_per_minute = max(int(max_calls_per_minute), 1)
    max_input_tokens_per_minute = max(int(max_input_tokens_per_minute), 1)
    max_requests_per_day = max(int(max_requests_per_day), 1)
    master_path = Path(master_path)
    try:
        master = load_master(master_path)
    except Exception as exc:
        raise RuntimeError(
            f"Could not load master resume at {master_path}: {exc}"
        ) from exc
    static = (
        Path(static_dir)
        if static_dir is not None
        else Path(__file__).resolve().parent.parent.parent / "static"
    )
    settings = WebSettings(
        master_path=master_path,
        output_dir=Path(output_dir),
        pdf_dir=Path(pdf_dir),
        state_dir=Path(state_dir),
        model=model,
        call_interval=call_interval,
        max_calls_per_minute=max_calls_per_minute,
        max_input_tokens_per_minute=max_input_tokens_per_minute,
        max_requests_per_day=max_requests_per_day,
        static_dir=static,
        access=access or AccessSettings(),
    )
    hub = EventHub()
    provider: ScheduledProvider | None = None
    scheduler: GeminiScheduler | None = None
    if _is_gemini(model):
        from llm_utils import initialize_llm_provider

        scheduler = GeminiScheduler(
            call_interval,
            max_calls_per_minute,
            calls_path=Path(state_dir) / CALLS_FILE,
            hub=hub,
            max_input_tokens_per_minute=max_input_tokens_per_minute,
            max_requests_per_day=max_requests_per_day,
        )
        provider = ScheduledProvider(
            scheduler,
            lambda: initialize_llm_provider(
                model,
                progress_callback=None,
                attempt_callback=scheduler.wait,
                usage_callback=scheduler.record_usage,
            ),
            provider_tracks_attempts=True,
        )
    registry = QueueRegistry(
        output_dir=settings.output_dir,
        pdf_dir=settings.pdf_dir,
        state_dir=settings.state_dir,
        pipeline_factory=pipeline_factory,
        master_path=master_path,
        master_name=master.basics.name if master.basics else None,
        model=model,
        call_interval=call_interval,
        max_calls_per_minute=max_calls_per_minute,
        pdf_available=shutil.which("tectonic") is not None,
        hub=hub,
        provider=provider,
        scheduler=scheduler,
        recovery_handler=recovery_handler,
    )
    return create_app(settings, registry, master, hub, scheduler)
