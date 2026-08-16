"""Queue web API, artifacts, security boundary, and static-shell tests."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import create_job, fake_factory, wait_for

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_meta_reports_identity_directories_and_quota(make_app):
    app, _ = make_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    meta = client.get("/api/meta").json()
    assert meta["ready"] is True
    assert meta["master_name"] == "Test User"
    assert meta["master_email"] == "test@example.com"
    assert meta["pdf_available"] is True
    assert meta["active_job_id"] is None
    assert meta["directory_labels"]["pdf_dir"].endswith("resumepdfs")
    assert meta["tracker"]["requests_per_minute_limit"] == 15
    assert meta["tracker"]["tokens_per_minute_limit"] == 250_000
    assert meta["tracker"]["requests_per_day_limit"] == 500


def test_meta_without_tectonic(make_app):
    app, _ = make_app(pdf_available=False)
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/api/meta").json()["pdf_available"] is False


def test_create_valid_job_and_safe_detail(web_client):
    response = create_job(web_client, str(uuid.uuid4()))
    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"job_id", "state", "queue_position", "status_url", "events_url"}
    status = wait_for(web_client, body["job_id"])
    assert status["state"] == "completed"
    assert status["company"] == "Example Corp"
    assert status["role"] == "Python Engineer"
    assert "jd_text" not in status
    assert (web_client.output_dir / body["job_id"] / "web_job.json").is_file()


def test_cli_history_job_can_open_detail(make_app, tmp_path):
    cli_dir = tmp_path / "output" / "cisco"
    cli_dir.mkdir(parents=True)
    (cli_dir / "resume.pdf").write_bytes(b"%PDF-1.4 fake")
    app, _ = make_app()
    client = TestClient(app, base_url="http://127.0.0.1")

    response = client.get("/api/jobs/cisco")

    assert response.status_code == 200
    assert response.json()["job"]["source"] == "cli"


def test_create_validation_uses_problem_documents(web_client):
    for payload in (
        {"company": "", "role": "Engineer", "jd_text": "Job"},
        {"company": "Corp", "role": "", "jd_text": "Job"},
        {"company": "Corp", "role": "Engineer", "jd_text": "  \n"},
        {"company": "x" * 81, "role": "Engineer", "jd_text": "Job"},
        {"company": "Corp", "role": "Engineer", "jd_text": "x" * 100_001},
    ):
        response = web_client.post(
            "/api/jobs",
            json=payload,
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")


def test_unknown_body_field_and_idempotency_key_rejected(web_client):
    response = web_client.post(
        "/api/jobs",
        json={"company": "Corp", "role": "Engineer", "jd_text": "Job", "admin": True},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 422
    assert any(error["loc"] == "body.admin" for error in response.json()["errors"])
    assert create_job(web_client, "not-a-uuid").status_code == 422
    assert web_client.post(
        "/api/jobs",
        json={"company": "Corp", "role": "Engineer", "jd_text": "Job"},
    ).status_code == 422


def test_idempotent_replay_and_body_mismatch(web_client):
    key = str(uuid.uuid4())
    first = create_job(web_client, key, jd_text="Role A")
    wait_for(web_client, first.json()["job_id"])
    replay = create_job(web_client, key, jd_text="Role A")
    mismatch = create_job(web_client, key, jd_text="Role B")
    assert replay.status_code == 202
    assert replay.json()["job_id"] == first.json()["job_id"]
    assert mismatch.status_code == 422


def test_queue_accepts_multiple_jobs_fifo_and_removes_waiting(make_app):
    app, _ = make_app(pipeline_factory=fake_factory(wait=0.15))
    client = TestClient(app, base_url="http://127.0.0.1")
    client.post("/api/queue/pause", json={})
    responses = [create_job(client, str(uuid.uuid4()), role=f"Role {index}") for index in range(3)]
    assert [response.status_code for response in responses] == [202, 202, 202]
    snapshot = client.get("/api/queue").json()
    assert [entry["queue_position"] for entry in snapshot["waiting"]] == [1, 2, 3]
    assert [entry["role"] for entry in snapshot["waiting"]] == ["Role 0", "Role 1", "Role 2"]
    removed = responses[1].json()["job_id"]
    assert client.delete(f"/api/jobs/{removed}").status_code == 204
    assert [entry["role"] for entry in client.get("/api/queue").json()["waiting"]] == ["Role 0", "Role 2"]


def test_pause_does_not_interrupt_active_job(make_app):
    app, _ = make_app(pipeline_factory=fake_factory(wait=0.15))
    client = TestClient(app, base_url="http://127.0.0.1")
    first = create_job(client, str(uuid.uuid4())).json()["job_id"]
    client.post("/api/queue/pause", json={})
    status = wait_for(client, first)
    assert status["state"] == "completed"
    assert client.get("/api/queue").json()["state"] == "paused"


def test_worker_failures_are_safe_and_next_job_can_run(make_app):
    app, _ = make_app(pipeline_factory=fake_factory(throw=RuntimeError("safe browser message")))
    client = TestClient(app, base_url="http://127.0.0.1")
    first = create_job(client, str(uuid.uuid4())).json()["job_id"]
    assert wait_for(client, first)["message"] == "safe browser message"
    second = create_job(client, str(uuid.uuid4())).json()["job_id"]
    assert second != first
    assert wait_for(client, second)["state"] == "failed"


def test_nonzero_pipeline_exit_and_diagnostics_are_retained(make_app):
    app, _ = make_app(pipeline_factory=fake_factory(exit_code=1, write_diagnostic=True))
    client = TestClient(app, base_url="http://127.0.0.1")
    job_id = create_job(client, str(uuid.uuid4())).json()["job_id"]
    status = wait_for(client, job_id)
    assert status["state"] == "failed"
    assert "unresolved findings" in status["message"].lower()
    assert "diagnostic_report.json" in status["artifacts"]


def test_missing_tectonic_requires_explicit_skip_pdf(make_app):
    app, _ = make_app(pdf_available=False)
    client = TestClient(app, base_url="http://127.0.0.1")
    response = create_job(client, str(uuid.uuid4()))
    assert response.status_code == 422
    assert "Tectonic" in response.json()["detail"]
    assert create_job(client, str(uuid.uuid4()), no_pdf=True).status_code == 202


def test_artifacts_are_allowlisted_and_pdf_can_render_inline(web_client):
    job_id = create_job(web_client, str(uuid.uuid4())).json()["job_id"]
    wait_for(web_client, job_id)
    inline = web_client.get(f"/api/jobs/{job_id}/files/resume.pdf?download=0")
    download = web_client.get(f"/api/jobs/{job_id}/files/resume.pdf")
    assert inline.status_code == download.status_code == 200
    assert inline.headers["content-disposition"].startswith("inline")
    assert download.headers["content-disposition"].startswith("attachment")
    assert web_client.get(f"/api/jobs/{job_id}/files/passwords.txt").status_code == 404
    assert web_client.get(f"/api/jobs/{job_id}/files/%2e%2e%2f.env").status_code == 404


def test_completed_pdf_is_copied_to_one_library(make_app):
    app, _ = make_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    job_id = create_job(client, str(uuid.uuid4()), company="Acme/West", role="Platform Engineer").json()["job_id"]
    status = wait_for(client, job_id)
    assert status["pdf_library_name"].startswith("Acme West - Platform Engineer - ")
    pdf_dir = Path(client.get("/api/meta").json()["directory_labels"]["pdf_dir"])
    assert (pdf_dir / status["pdf_library_name"]).is_file()


def test_unknown_jobs_and_excluded_scoring_routes_are_404(web_client):
    unknown = str(uuid.uuid4())
    assert web_client.get("/api/jobs/not-a-uuid").status_code == 404
    assert web_client.get(f"/api/jobs/{unknown}").status_code == 404
    assert web_client.post(f"/api/jobs/{unknown}/score", json={}).status_code in {404, 405}


def test_security_boundary_and_headers(web_client):
    assert web_client.get("/api/meta", headers={"Host": "evil.example.com"}).status_code == 400
    response = web_client.post(
        "/api/jobs",
        json={"company": "Corp", "role": "Engineer", "jd_text": "Job"},
        headers={"Idempotency-Key": str(uuid.uuid4()), "Origin": "http://evil.example.com"},
    )
    assert response.status_code == 403
    response = web_client.get("/api/meta")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"


def test_static_shell_contract():
    index = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert '<dialog class="new-job-dialog"' in index
    assert 'for="company"' in index and 'for="role"' in index and 'for="jd-text"' in index
    assert 'id="jd-help"' in index and 'id="jd-error"' in index
    assert 'role="tablist"' in index and 'role="tabpanel"' in index
    assert 'class="skip-link"' in index
    assert 'aria-live' in index and 'role="alert"' in index
    assert not re.search(r"<script(?![\s>]*src=)", index)
    assert "style=" not in index

    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in app_js
    assert "insertAdjacentHTML" not in app_js
    assert "document.write" not in app_js
    assert "EventSource" in app_js and "Idempotency-Key" in app_js

    app_css = (REPO_ROOT / "static" / "app.css").read_text(encoding="utf-8")
    assert ":focus-visible" in app_css
    assert "prefers-reduced-motion" in app_css
    assert "100dvh" in app_css
    assert "grid-template-columns: 280px minmax(0, 1fr)" in app_css
    assert "360px 320px" not in app_css


def test_static_served_at_root(make_app):
    app, _ = make_app(static_dir=str(REPO_ROOT / "static"))
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.get("/")
    assert response.status_code == 200
    assert "ATS Resume Tailor" in response.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/app.css").status_code == 200
