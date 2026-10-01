"""Typed progress events and terminal reporters.

Pipeline code emits semantic events through :class:`ProgressReporter`. Terminal
rendering stays here, so orchestration remains usable from tests and libraries.
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, TextIO


class Stage(StrEnum):
    PREFLIGHT = "Preflight"
    PARSE_JD = "Parse job description"
    RESEARCH_COMPANY_STACK = "Research company tech stack"
    RESEARCH_COMPANY_SIGNALS = "Research company hiring signals"
    MAP_REQUIREMENTS = "Map requirement coverage"
    SELECT_WORK = "Select work"
    SELECT_PROJECTS = "Select projects"
    PLAN_EVIDENCE = "Plan evidence"
    TAILOR_SKILLS = "Tailor skills"
    REWRITE_WORK = "Rewrite work"
    REWRITE_PROJECTS = "Rewrite projects"
    ASSEMBLE = "Assemble draft"
    HOLISTIC_REVIEW = "Holistic review"
    VALIDATE_REVIEW = "Validate review edits"
    RENDER = "Render and fit one page"
    EMERGENCY_CONCISION = "Emergency bullet concision"
    CONCISION_AUDIT = "Audit emergency concision"
    WRITE_ARTIFACTS = "Write artifacts"


class ProgressEventKind(StrEnum):
    BATCH_STARTED = "batch_started"
    JOB_STARTED = "job_started"
    JOB_SKIPPED = "job_skipped"
    STAGE_STARTED = "stage_started"
    STAGE_RETRY = "stage_retry"
    STAGE_DETAIL = "stage_detail"
    STAGE_WARNING = "stage_warning"
    STAGE_COMPLETED = "stage_completed"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    BATCH_COMPLETED = "batch_completed"


@dataclass(frozen=True, slots=True)
class JobContext:
    """Stable identity for one job in a batch."""

    name: str
    index: int = 1
    total: int = 1
    output_dir: Path | None = None

    @property
    def label(self) -> str:
        return f"[{self.index}/{self.total}] {self.name}"


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    kind: ProgressEventKind
    job: JobContext | None = None
    stage: Stage | None = None
    message: str | None = None
    elapsed_seconds: float | None = None
    attempt: int | None = None
    max_attempts: int | None = None
    counts: dict[str, int] = field(default_factory=dict)
    output_paths: tuple[Path, ...] = ()
    verbose_only: bool = False


class ProgressReporter(Protocol):
    """Consumer for semantic pipeline progress events."""

    verbose: bool

    def emit(self, event: ProgressEvent) -> None: ...

    def close(self) -> None: ...


class NullProgressReporter:
    verbose = False

    def emit(self, event: ProgressEvent) -> None:
        del event

    def close(self) -> None:
        return


class ProgressTracker:
    """Small timing facade used by pipeline and provider code."""

    def __init__(
        self,
        reporter: ProgressReporter | None = None,
        job: JobContext | None = None,
    ) -> None:
        self.reporter = reporter or NullProgressReporter()
        self.job = job

    @contextmanager
    def stage(self, stage: Stage):
        started = time.monotonic()
        self.reporter.emit(
            ProgressEvent(ProgressEventKind.STAGE_STARTED, job=self.job, stage=stage)
        )
        try:
            yield
        except Exception:
            raise
        else:
            self.reporter.emit(
                ProgressEvent(
                    ProgressEventKind.STAGE_COMPLETED,
                    job=self.job,
                    stage=stage,
                    elapsed_seconds=time.monotonic() - started,
                )
            )

    def retry(
        self,
        stage: Stage,
        *,
        attempt: int,
        max_attempts: int,
        message: str,
    ) -> None:
        self.reporter.emit(
            ProgressEvent(
                ProgressEventKind.STAGE_RETRY,
                job=self.job,
                stage=stage,
                attempt=attempt,
                max_attempts=max_attempts,
                message=message,
            )
        )

    def detail(self, message: str, *, verbose_only: bool = True) -> None:
        self.reporter.emit(
            ProgressEvent(
                ProgressEventKind.STAGE_DETAIL,
                job=self.job,
                message=message,
                verbose_only=verbose_only,
            )
        )

    def warn(self, message: str) -> None:
        self.reporter.emit(
            ProgressEvent(
                ProgressEventKind.STAGE_WARNING,
                job=self.job,
                message=message,
            )
        )


class PlainProgressReporter:
    """Stable line-oriented output for CI and redirected streams."""

    def __init__(
        self,
        *,
        stream: TextIO = sys.stdout,
        verbose: bool = False,
        quiet: bool = False,
    ) -> None:
        self.stream = stream
        self.verbose = verbose
        self.quiet = quiet

    @staticmethod
    def _duration(event: ProgressEvent) -> str:
        return (
            f" ({event.elapsed_seconds:.1f}s)"
            if event.elapsed_seconds is not None
            else ""
        )

    def _write(self, message: str) -> None:
        print(message, file=self.stream, flush=True)

    def emit(self, event: ProgressEvent) -> None:
        if event.verbose_only and not self.verbose:
            return
        if self.quiet and event.kind not in {
            ProgressEventKind.JOB_FAILED,
            ProgressEventKind.BATCH_COMPLETED,
        }:
            return

        prefix = f"{event.job.label} · " if event.job else ""
        duration = self._duration(event)
        match event.kind:
            case ProgressEventKind.BATCH_STARTED:
                self._write(event.message or "Starting batch")
            case ProgressEventKind.JOB_STARTED:
                self._write(f"{event.job.label} · Started")
            case ProgressEventKind.JOB_SKIPPED:
                self._write(
                    f"{event.job.label} · Skipped ({event.message or 'complete'})"
                )
            case ProgressEventKind.STAGE_STARTED:
                self._write(f"{prefix}→ {event.stage.value}")
            case ProgressEventKind.STAGE_RETRY:
                attempt = f"attempt {event.attempt}/{event.max_attempts}"
                detail = f": {event.message}" if event.message else ""
                self._write(f"{prefix}↻ {event.stage.value} · {attempt}{detail}")
            case ProgressEventKind.STAGE_DETAIL:
                self._write(f"{prefix}  {event.message}")
            case ProgressEventKind.STAGE_WARNING:
                self._write(f"{prefix}⚠ {event.message}")
            case ProgressEventKind.STAGE_COMPLETED:
                self._write(f"{prefix}✓ {event.stage.value}{duration}")
            case ProgressEventKind.JOB_COMPLETED:
                self._write(f"{event.job.label} · Completed{duration}")
            case ProgressEventKind.JOB_FAILED:
                self._write(f"{event.job.label} · Failed: {event.message}")
            case ProgressEventKind.BATCH_COMPLETED:
                self._write(_batch_summary(event, include_paths=not self.quiet))

    def close(self) -> None:
        return


def _batch_summary(event: ProgressEvent, *, include_paths: bool) -> str:
    counts = event.counts
    summary = (
        "Batch finished · "
        f"{counts.get('completed', 0)} completed · "
        f"{counts.get('skipped', 0)} skipped · "
        f"{counts.get('failed', 0)} failed"
    )
    if event.elapsed_seconds is not None:
        summary += f" · {event.elapsed_seconds:.1f}s"
    if event.message:
        summary += f"\n{event.message}"
    if include_paths and event.output_paths:
        summary += "\nOutputs:\n" + "\n".join(
            f"  - {path}" for path in event.output_paths
        )
    return summary


class RichProgressReporter:
    """One live stage row plus durable job and stage completion lines."""

    def __init__(self, *, verbose: bool = False, stream: TextIO = sys.stdout) -> None:
        from rich.console import Console
        from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

        self.verbose = verbose
        self.console = Console(file=stream)
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
        )
        self._progress.start()
        self._task_id: int | None = None

    def _stop_stage(self) -> None:
        if self._task_id is not None:
            self._progress.remove_task(self._task_id)
            self._task_id = None
            self._progress.refresh()

    def emit(self, event: ProgressEvent) -> None:
        if event.verbose_only and not self.verbose:
            return
        job = event.job.label if event.job else ""
        duration = (
            f" [dim]({event.elapsed_seconds:.1f}s)[/]"
            if event.elapsed_seconds is not None
            else ""
        )
        match event.kind:
            case ProgressEventKind.BATCH_STARTED:
                self.console.print(f"[bold]{event.message or 'Starting batch'}[/]")
            case ProgressEventKind.JOB_STARTED:
                self.console.print(f"\n[bold blue]{job}[/] [dim]Started[/]")
            case ProgressEventKind.JOB_SKIPPED:
                self.console.print(f"[yellow]○[/] {job} · Skipped [dim](complete)[/]")
            case ProgressEventKind.STAGE_STARTED:
                self._stop_stage()
                self._task_id = self._progress.add_task(
                    f"{job} · {event.stage.value}", total=None
                )
            case ProgressEventKind.STAGE_RETRY:
                self.console.print(
                    f"[yellow]↻[/] {job} · {event.stage.value} · "
                    f"attempt {event.attempt}/{event.max_attempts}: {event.message}"
                )
            case ProgressEventKind.STAGE_DETAIL:
                self.console.print(f"[dim]{job} · {event.message}[/]")
            case ProgressEventKind.STAGE_WARNING:
                self.console.print(f"[yellow]⚠[/] {job} · {event.message}")
            case ProgressEventKind.STAGE_COMPLETED:
                self._stop_stage()
                self.console.print(f"[green]✓[/] {job} · {event.stage.value}{duration}")
            case ProgressEventKind.JOB_COMPLETED:
                self._stop_stage()
                self.console.print(f"[bold green]✓ {job} · Completed[/]{duration}")
            case ProgressEventKind.JOB_FAILED:
                self._stop_stage()
                self.console.print(f"[bold red]✗ {job} · Failed:[/] {event.message}")
            case ProgressEventKind.BATCH_COMPLETED:
                self._stop_stage()
                self.console.print("\n" + _batch_summary(event, include_paths=True))

    def close(self) -> None:
        self._stop_stage()
        self._progress.stop()


def build_progress_reporter(
    *, verbose: bool = False, quiet: bool = False, stream: TextIO = sys.stdout
) -> ProgressReporter:
    """Select the interactive or deterministic reporter for the output stream."""
    if quiet or not stream.isatty():
        return PlainProgressReporter(stream=stream, verbose=verbose, quiet=quiet)
    return RichProgressReporter(verbose=verbose, stream=stream)
