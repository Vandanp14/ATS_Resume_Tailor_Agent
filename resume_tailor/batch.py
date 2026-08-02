"""Single-job and sequential batch coordination."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from render import RenderError

from .pipeline import TailorPipeline
from .progress import (
    JobContext,
    NullProgressReporter,
    ProgressEvent,
    ProgressEventKind,
    ProgressReporter,
)
from .runtime import QUOTA_EXIT_CODE, StageFailure, done_satisfies, load_master


try:  # compatibility with environments that omit the Google SDK
    from google.api_core.exceptions import ResourceExhausted
except Exception:  # pragma: no cover

    class ResourceExhausted(Exception):
        pass


def is_quota_error(exc: Exception) -> bool:
    if isinstance(exc, ResourceExhausted):
        return True
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return code == 429 or "resource_exhausted" in str(exc).lower()


def pipeline_from_args(
    args: argparse.Namespace, reporter: ProgressReporter | None = None
) -> TailorPipeline:
    return TailorPipeline(
        model=args.model,
        call_interval=args.call_interval,
        reporter=reporter,
        bridge_skills=getattr(args, "bridge_skills", False),
    )


def run_single(
    args: argparse.Namespace, reporter: ProgressReporter | None = None
) -> int:
    reporter = reporter or NullProgressReporter()
    job = JobContext(args.jd.stem, output_dir=args.out_dir)
    started = time.monotonic()
    reporter.emit(ProgressEvent(ProgressEventKind.JOB_STARTED, job=job))
    try:
        result = pipeline_from_args(args, reporter).run(
            load_master(args.master),
            args.jd.read_text(encoding="utf-8"),
            args.out_dir,
            no_pdf=args.no_pdf,
            job=job,
        )
    except (StageFailure, RenderError, OSError, ValueError) as exc:
        reporter.emit(
            ProgressEvent(ProgressEventKind.JOB_FAILED, job=job, message=str(exc))
        )
        return 1
    if result:
        reporter.emit(
            ProgressEvent(
                ProgressEventKind.JOB_FAILED,
                job=job,
                message="unresolved truth violation or invalid reviewer edit",
            )
        )
        return result
    reporter.emit(
        ProgressEvent(
            ProgressEventKind.JOB_COMPLETED,
            job=job,
            elapsed_seconds=time.monotonic() - started,
            output_paths=(args.out_dir,),
        )
    )
    return 0


def run_batch(
    args: argparse.Namespace, reporter: ProgressReporter | None = None
) -> int:
    reporter = reporter or NullProgressReporter()
    master = load_master(args.master)
    jobs = sorted(args.jd_dir.glob("*.txt"))
    if not jobs:
        reporter.emit(
            ProgressEvent(
                ProgressEventKind.BATCH_COMPLETED,
                message=f"No job descriptions found in {args.jd_dir}",
                counts={"completed": 0, "skipped": 0, "failed": 1},
            )
        )
        return 1

    batch_started = time.monotonic()
    reporter.emit(
        ProgressEvent(
            ProgressEventKind.BATCH_STARTED,
            message=f"Tailoring {len(jobs)} job description{'s' if len(jobs) != 1 else ''}",
            counts={"total": len(jobs)},
        )
    )
    pipeline = pipeline_from_args(args, reporter)
    failed: list[str] = []
    completed_paths: list[Path] = []
    skipped = 0

    for index, jd_path in enumerate(jobs, start=1):
        out_dir = args.out_dir / jd_path.stem
        job = JobContext(jd_path.stem, index, len(jobs), out_dir)
        if not args.force and done_satisfies(out_dir, args.no_pdf):
            skipped += 1
            reporter.emit(
                ProgressEvent(
                    ProgressEventKind.JOB_SKIPPED,
                    job=job,
                    message="complete",
                )
            )
            continue

        job_started = time.monotonic()
        reporter.emit(ProgressEvent(ProgressEventKind.JOB_STARTED, job=job))
        try:
            result = pipeline.run(
                master,
                jd_path.read_text(encoding="utf-8"),
                out_dir,
                no_pdf=args.no_pdf,
                job=job,
            )
            if result:
                failed.append(jd_path.stem)
                reporter.emit(
                    ProgressEvent(
                        ProgressEventKind.JOB_FAILED,
                        job=job,
                        message="unresolved truth violation or invalid reviewer edit",
                    )
                )
            else:
                completed_paths.append(out_dir)
                reporter.emit(
                    ProgressEvent(
                        ProgressEventKind.JOB_COMPLETED,
                        job=job,
                        elapsed_seconds=time.monotonic() - job_started,
                        output_paths=(out_dir,),
                    )
                )
        except Exception as exc:
            if is_quota_error(exc):
                remaining = [item.stem for item in jobs[index - 1 :]]
                failed.extend(remaining)
                reporter.emit(
                    ProgressEvent(
                        ProgressEventKind.JOB_FAILED,
                        job=job,
                        message=(
                            "Gemini quota exhausted — wait and re-run. Remaining: "
                            + ", ".join(remaining)
                        ),
                    )
                )
                reporter.emit(
                    _summary_event(batch_started, completed_paths, skipped, len(failed))
                )
                return QUOTA_EXIT_CODE
            failed.append(jd_path.stem)
            reporter.emit(
                ProgressEvent(
                    ProgressEventKind.JOB_FAILED,
                    job=job,
                    message=str(exc),
                )
            )
        if args.delay_seconds > 0 and index < len(jobs):
            if reporter.verbose:
                reporter.emit(
                    ProgressEvent(
                        ProgressEventKind.STAGE_DETAIL,
                        job=job,
                        message=f"Inter-job delay: {args.delay_seconds:.1f}s",
                    )
                )
            time.sleep(args.delay_seconds)

    reporter.emit(_summary_event(batch_started, completed_paths, skipped, len(failed)))
    return 1 if failed else 0


def _summary_event(
    started: float,
    completed_paths: list[Path],
    skipped: int,
    failed: int,
) -> ProgressEvent:
    return ProgressEvent(
        ProgressEventKind.BATCH_COMPLETED,
        elapsed_seconds=time.monotonic() - started,
        counts={
            "completed": len(completed_paths),
            "skipped": skipped,
            "failed": failed,
        },
        output_paths=tuple(completed_paths),
    )
