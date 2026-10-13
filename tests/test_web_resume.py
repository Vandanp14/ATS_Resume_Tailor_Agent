"""Resuming a failed web run reuses its saved request and passes resume=True."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.conftest import FakePipe, create_job, wait_for


def test_failed_run_resumes_with_saved_request(make_app):
    calls = []

    class Pipe(FakePipe):
        def run(self, master, jd_text, out_dir, no_pdf, job, resume=False):
            calls.append((jd_text, resume))
            if not resume:
                raise RuntimeError("Gemini API unavailable for every configured model")
            return super().run(master, jd_text, out_dir, no_pdf, job)

    app, _ = make_app(pipeline_factory=Pipe)
    client = TestClient(app, base_url="http://127.0.0.1")
    job_id = create_job(client, str(uuid.uuid4()), jd_text="Need Go dev.").json()[
        "job_id"
    ]
    assert wait_for(client, job_id)["state"] == "failed"

    response = client.post(f"/api/jobs/{job_id}/resume")
    assert response.status_code == 202
    assert response.json()["job_id"] == job_id
    assert wait_for(client, job_id)["state"] == "completed"
    assert calls == [("Need Go dev.", False), ("Need Go dev.", True)]


def test_only_failed_runs_can_be_resumed(make_app):
    app, _ = make_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    job_id = create_job(client, str(uuid.uuid4())).json()["job_id"]
    assert wait_for(client, job_id)["state"] == "completed"
    assert client.post(f"/api/jobs/{job_id}/resume").status_code == 409
    assert client.post("/api/jobs/does-not-exist/resume").status_code == 404
