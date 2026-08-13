"""Shared fixtures for the web adapter suite."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from resume_tailor.pipeline import TailorPipeline
from resume_tailor.progress import Stage
from resume_tailor.web.app import webapp_factory

MINIMAL_MASTER = {"basics": {"name": "Test User", "email": "test@example.com"}}


class FakePipe(TailorPipeline):
    """Deterministic pipeline stub; behavior configured via class attributes."""

    wait: float = 0.0
    exit_code: int = 0
    throw: Exception | None = None
    write_tex: bool = False
    write_diagnostic: bool = False

    def run(self, master, jd_text, out_dir, no_pdf, job):
        if self.wait:
            time.sleep(self.wait)
        if self.throw:
            raise self.throw
        self.tracker.job = job
        with self.tracker.stage(Stage.PREFLIGHT):
            self.tracker.detail("preflight complete")
        with self.tracker.stage(Stage.PARSE_JD):
            self.tracker.detail("keywords extracted")
        (out_dir / "tailored.json").write_text(
            json.dumps({"basics": {"name": "Test User"}}), encoding="utf-8"
        )
        (out_dir / "resume.pdf").write_bytes(b"%PDF-1.4 fake")
        (out_dir / ".done").write_text(json.dumps({"no_pdf": no_pdf}), encoding="utf-8")
        if self.write_tex:
            (out_dir / "resume.tex").write_text(
                "\\documentclass{article}", encoding="utf-8"
            )
        if self.write_diagnostic:
            (out_dir / "diagnostic_report.json").write_text(
                json.dumps({"stage": "rejected", "reason": "needs truth fix"}),
                encoding="utf-8",
            )
        return self.exit_code


def fake_factory(**behavior):
    """Class-attribute configuration produces a fresh stub class per test."""

    class Pipe(FakePipe):
        pass

    for key, value in behavior.items():
        setattr(Pipe, key, value)
    return Pipe


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    master_path = tmp_path / "master.json"
    master_path.write_text(json.dumps(MINIMAL_MASTER), encoding="utf-8")
    output_dir = tmp_path / "output"

    def build(
        *,
        pipeline_factory=None,
        static_dir=None,
        pdf_available: bool = True,
        call_interval: float = 0.01,
        score_timeout: float = 5.0,
        recovery_handler=None,
    ):
        if not pdf_available:

            def which(name: str):
                return None if name == "tectonic" else "/usr/bin/which"

            monkeypatch.setattr("shutil.which", which)
        static = Path(static_dir) if static_dir is not None else (output_dir / "static")
        static.mkdir(parents=True, exist_ok=True)
        app = webapp_factory(
            master_path=master_path,
            output_dir=output_dir,
            pdf_dir=tmp_path / "resumepdfs",
            state_dir=tmp_path / ".resume-tailor",
            call_interval=call_interval,
            score_timeout=score_timeout,
            pipeline_factory=pipeline_factory or FakePipe,
            static_dir=static,
            recovery_handler=recovery_handler,
        )
        return app, output_dir

    return build


@pytest.fixture
def web_client(make_app):
    """Client bound to a default app, with the output root available for seeding."""

    from fastapi.testclient import TestClient

    app, output_dir = make_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    client.output_dir = output_dir
    return client


def create_job(client, key: str, jd_text: str = "We need a Python engineer.", **extra):
    payload = {
        "company": "Example Corp",
        "role": "Python Engineer",
        "jd_text": jd_text,
        **extra,
    }
    return client.post("/api/jobs", json=payload, headers={"Idempotency-Key": key})


def wait_for(
    client,
    job_id: str,
    states: tuple[str, ...] = ("completed", "failed"),
    timeout: float = 10.0,
):
    import time as _time

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()["job"]
        if status["state"] in states:
            return status
        _time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not reach a terminal state in {timeout}s")
