"""Progress events, output modes, and batch coordination tests."""

from __future__ import annotations

import argparse
import logging
from io import StringIO
from pathlib import Path

from resume_tailor import batch
from resume_tailor.cli import configure_logging
from resume_tailor.progress import (
    JobContext,
    PlainProgressReporter,
    ProgressEvent,
    ProgressEventKind,
    ProgressTracker,
    Stage,
    RichProgressReporter,
    build_progress_reporter,
)


class CapturingReporter:
    def __init__(self, *, verbose: bool = False) -> None:
        self.verbose = verbose
        self.events: list[ProgressEvent] = []

    def emit(self, event: ProgressEvent) -> None:
        self.events.append(event)

    def close(self) -> None:
        return


def test_plain_reporter_renders_stable_non_ansi_stage_lines():
    stream = StringIO()
    reporter = PlainProgressReporter(stream=stream)
    job = JobContext("intuit", 2, 3)

    reporter.emit(ProgressEvent(ProgressEventKind.JOB_STARTED, job=job))
    reporter.emit(
        ProgressEvent(
            ProgressEventKind.STAGE_STARTED, job=job, stage=Stage.PLAN_EVIDENCE
        )
    )
    reporter.emit(
        ProgressEvent(
            ProgressEventKind.STAGE_COMPLETED,
            job=job,
            stage=Stage.PLAN_EVIDENCE,
            elapsed_seconds=2.34,
        )
    )

    output = stream.getvalue()
    assert "[2/3] intuit · Started" in output
    assert "→ Plan evidence" in output
    assert "✓ Plan evidence (2.3s)" in output
    assert "\x1b[" not in output


def test_quiet_reporter_only_emits_failures_and_final_summary():
    stream = StringIO()
    reporter = PlainProgressReporter(stream=stream, quiet=True)
    job = JobContext("intuit")
    reporter.emit(ProgressEvent(ProgressEventKind.JOB_STARTED, job=job))
    reporter.emit(
        ProgressEvent(ProgressEventKind.JOB_FAILED, job=job, message="review rejected")
    )
    reporter.emit(
        ProgressEvent(
            ProgressEventKind.BATCH_COMPLETED,
            counts={"completed": 0, "skipped": 0, "failed": 1},
        )
    )

    output = stream.getvalue()
    assert "Started" not in output
    assert "review rejected" in output
    assert "1 failed" in output
    assert "Outputs:" not in output


def test_tracker_warn_emits_stage_warning_visible_by_default():
    reporter = CapturingReporter()
    tracker = ProgressTracker(reporter, job=JobContext("intuit"))
    tracker.warn("Reviewer edit rejected: skills edit rejected: x")
    assert reporter.events[0].kind == ProgressEventKind.STAGE_WARNING
    assert reporter.events[0].message.startswith("Reviewer edit rejected")
    assert reporter.events[0].verbose_only is False


def test_plain_reporter_renders_warnings_without_verbose():
    stream = StringIO()
    reporter = PlainProgressReporter(stream=stream)
    job = JobContext("intuit", 1, 2)
    reporter.emit(
        ProgressEvent(
            ProgressEventKind.STAGE_WARNING,
            job=job,
            message="Reviewer edit rejected: x",
        )
    )
    output = stream.getvalue()
    assert "[1/2] intuit · ⚠ Reviewer edit rejected: x" in output


def test_rich_reporter_renders_warning_lines():
    class TerminalBuffer(StringIO):
        def isatty(self):
            return True

    stream = TerminalBuffer()
    reporter = RichProgressReporter(stream=stream)
    job = JobContext("intuit")
    reporter.emit(
        ProgressEvent(
            ProgressEventKind.STAGE_WARNING,
            job=job,
            message="Reviewer edit rejected: x",
        )
    )
    reporter.close()
    output = stream.getvalue()
    assert "⚠" in output
    assert "Reviewer edit rejected: x" in output


def test_reporter_factory_uses_plain_output_for_redirected_stream():
    reporter = build_progress_reporter(stream=StringIO())
    assert isinstance(reporter, PlainProgressReporter)


def test_rich_reporter_cleans_up_live_terminal_state():
    class TerminalBuffer(StringIO):
        def isatty(self):
            return True

    stream = TerminalBuffer()
    reporter = build_progress_reporter(stream=stream)
    assert isinstance(reporter, RichProgressReporter)
    job = JobContext("intuit")
    reporter.emit(
        ProgressEvent(ProgressEventKind.STAGE_STARTED, job=job, stage=Stage.PARSE_JD)
    )
    reporter.emit(
        ProgressEvent(
            ProgressEventKind.STAGE_COMPLETED,
            job=job,
            stage=Stage.PARSE_JD,
            elapsed_seconds=0.1,
        )
    )
    reporter.close()

    assert reporter._task_id is None
    assert "Parse job description" in stream.getvalue()
    assert "\x1b[?25h" in stream.getvalue()


def test_logging_suppresses_sdk_info_noise():
    configure_logging(verbose=True)
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
    assert logging.getLogger("google_genai").level == logging.WARNING


def test_batch_emits_job_positions_paths_and_aggregate_summary(tmp_path, monkeypatch):
    jd_dir = tmp_path / "jds"
    jd_dir.mkdir()
    (jd_dir / "alpha.txt").write_text("alpha", encoding="utf-8")
    (jd_dir / "beta.txt").write_text("beta", encoding="utf-8")
    out_dir = tmp_path / "output"

    class FakePipeline:
        def run(self, master, jd_text, job_out, no_pdf=False, job=None):
            assert master is sentinel
            assert jd_text in {"alpha", "beta"}
            assert no_pdf is True
            assert job_out == job.output_dir
            return 0

    sentinel = object()
    monkeypatch.setattr(batch, "load_master", lambda _path: sentinel)
    monkeypatch.setattr(
        batch, "pipeline_from_args", lambda _args, _reporter: FakePipeline()
    )
    args = argparse.Namespace(
        master=Path("master.json"),
        jd_dir=jd_dir,
        out_dir=out_dir,
        model="gemini-3.1-flash-lite",
        call_interval=0.0,
        delay_seconds=0.0,
        force=True,
        no_pdf=True,
    )
    reporter = CapturingReporter()

    assert batch.run_batch(args, reporter) == 0
    started = [
        event
        for event in reporter.events
        if event.kind == ProgressEventKind.JOB_STARTED
    ]
    assert [
        (event.job.index, event.job.total, event.job.name) for event in started
    ] == [
        (1, 2, "alpha"),
        (2, 2, "beta"),
    ]
    summary = reporter.events[-1]
    assert summary.kind == ProgressEventKind.BATCH_COMPLETED
    assert summary.counts == {"completed": 2, "skipped": 0, "failed": 0}
    assert summary.output_paths == (out_dir / "alpha", out_dir / "beta")
