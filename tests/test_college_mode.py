"""College mode: switch, qualification lines, coverage, two pages, summary."""

from __future__ import annotations

import uuid
from pathlib import Path

from tests.conftest import FakePipe, create_job, wait_for

REPO_ROOT = Path(__file__).resolve().parent.parent


# -- Task 1: the switch ----------------------------------------------------------


class RecordingPipe(FakePipe):
    seen: list[bool] = []

    def run(self, master, jd_text, out_dir, no_pdf, job, resume=False):
        RecordingPipe.seen.append(self.college_mode)
        return super().run(master, jd_text, out_dir, no_pdf, job, resume)


def test_college_flag_reaches_pipeline(make_app):
    from fastapi.testclient import TestClient

    RecordingPipe.seen = []
    app, _ = make_app(pipeline_factory=RecordingPipe)
    client = TestClient(app, base_url="http://127.0.0.1")
    job = create_job(client, str(uuid.uuid4()), college_mode=True).json()["job_id"]
    assert wait_for(client, job)["state"] == "completed"
    plain = create_job(client, str(uuid.uuid4()), jd_text="Another posting.").json()["job_id"]
    assert wait_for(client, plain)["state"] == "completed"
    assert RecordingPipe.seen == [True, False]


def test_jd_parse_fingerprint_depends_on_college_mode():
    from resume_tailor.checkpoints import stage_fingerprint

    base = dict(master_json="{}", jd_text="Posting")
    assert stage_fingerprint("jd_parse", **base) != stage_fingerprint(
        "jd_parse", **base, college_mode=True
    )
    assert stage_fingerprint("jd_parse", **base) == stage_fingerprint(
        "jd_parse", **base, college_mode=False, bridge_skills=True
    )


def test_job_fingerprint_unchanged_when_off():
    from resume_tailor.web.models import CreateJobRequest, JobOptions, job_fingerprint

    request = CreateJobRequest(company="A", role="B", jd_text="C")
    seed = ("A", "B", "C", False, False, False)
    assert job_fingerprint(request, JobOptions()) == uuid.uuid5(uuid.NAMESPACE_URL, repr(seed)).hex
    on = CreateJobRequest(company="A", role="B", jd_text="C", college_mode=True)
    assert job_fingerprint(on, JobOptions(college_mode=True)) != job_fingerprint(request, JobOptions())


def test_index_has_college_toggle():
    index = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="college-mode"' in index
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "college_mode" in app_js
