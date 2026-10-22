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
    assert 'id="view-new"' in index and 'id="job-form"' in index
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
    assert "360px 320px" not in app_css


def test_static_served_at_root(make_app):
    app, _ = make_app(static_dir=str(REPO_ROOT / "static"))
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.get("/")
    assert response.status_code == 200
    assert "ATS Resume Tailor" in response.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/app.css").status_code == 200


# -- skill check ---------------------------------------------------------------


def _master_file(client):
    import json

    return json.loads((client.output_dir.parent / "master.json").read_text(encoding="utf-8"))


def test_skill_check_returns_chips_and_id(web_client):
    response = web_client.post("/api/skill-check", json={"jd_text": "Need Figma and Siteimprove."})
    assert response.status_code == 200
    body = response.json()
    assert re.fullmatch(r"[0-9a-f]{32}", body["check_id"])
    assert [chip["term"] for chip in body["chips"]] == ["Figma", "Siteimprove"]
    assert body["remembered_confirmed"] == []


def test_answers_endpoint_updates_master_file(web_client):
    check = web_client.post("/api/skill-check", json={"jd_text": "Need Figma."}).json()
    response = web_client.post(
        f"/api/skill-check/{check['check_id']}/answers",
        json={"confirmed": ["Figma"], "declined": ["Siteimprove"]},
    )
    assert response.status_code == 204
    saved = _master_file(web_client)
    assert {"name": "Confirmed Skills", "keywords": ["Figma"]} in saved["skills"]
    assert saved["skill_check"]["declined"] == ["Siteimprove"]
    again = web_client.post("/api/skill-check", json={"jd_text": "Need Figma."}).json()
    assert again["chips"] == []
    assert again["remembered_confirmed"] == ["Figma"]


def test_put_skill_answers_replaces_lists(web_client):
    web_client.put("/api/skill-answers", json={"confirmed": ["Figma"], "declined": ["Azure"]})
    assert web_client.get("/api/skill-answers").json() == {
        "confirmed": ["Figma"],
        "declined": ["Azure"],
    }
    response = web_client.put("/api/skill-answers", json={"confirmed": ["Azure"], "declined": []})
    assert response.status_code == 204
    assert web_client.get("/api/skill-answers").json() == {"confirmed": ["Azure"], "declined": []}


def test_job_with_skill_check_copies_checkpoints_and_resumes(web_client):
    import json

    jd = "We need a Python engineer with Figma."
    check = web_client.post("/api/skill-check", json={"jd_text": jd}).json()
    response = create_job(web_client, str(uuid.uuid4()), jd_text=jd, skill_check_id=check["check_id"])
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    job_dir = web_client.output_dir / job_id
    assert (job_dir / "checkpoints" / "jd_parse.json").is_file()
    request = json.loads(
        (web_client.output_dir.parent / ".resume-tailor" / "requests" / f"{job_id}.json").read_text()
    )
    assert request["resume"] is True
    assert wait_for(web_client, job_id)["state"] == "completed"


def test_job_with_missing_or_mismatched_check_runs_normally(web_client):
    import json

    check = web_client.post("/api/skill-check", json={"jd_text": "Need Figma."}).json()
    for check_id in (check["check_id"], "0" * 32):
        response = create_job(
            web_client, str(uuid.uuid4()), jd_text="A different posting.", skill_check_id=check_id
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        request = json.loads(
            (web_client.output_dir.parent / ".resume-tailor" / "requests" / f"{job_id}.json").read_text()
        )
        assert request["resume"] is False
        assert not (web_client.output_dir / job_id / "checkpoints").exists()
        assert wait_for(web_client, job_id)["state"] == "completed"


def test_index_has_skill_check_controls():
    index = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for marker in ('id="check-skills-btn"', 'id="skill-chips"', 'id="remembered-skills"', 'id="skip-check-btn"'):
        assert marker in index
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert '"/api/skill-check"' in app_js and '"/api/skill-answers"' in app_js
    assert "aria-pressed" in app_js


def test_skill_answers_work_past_two_hundred_terms(web_client):
    declined = [f"Tool{index}" for index in range(300)]
    response = web_client.put("/api/skill-answers", json={"confirmed": ["Figma"], "declined": declined})
    assert response.status_code == 204
    body = web_client.get("/api/skill-answers")
    assert body.status_code == 200
    assert len(body.json()["declined"]) == 300


def test_legacy_cli_folders_are_not_listed(make_app, tmp_path):
    legacy = tmp_path / "output" / "product_swe_disney"
    legacy.mkdir(parents=True)
    (legacy / "tailored.json").write_text("{}", encoding="utf-8")
    (legacy / "resume.pdf").write_bytes(b"%PDF-1.4")
    app, _ = make_app()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        jobs = client.get("/api/jobs").json()
    assert isinstance(jobs, list)
    assert all(entry["job_id"] != "product_swe_disney" for entry in jobs)


def test_shell_has_views_and_topbar():
    index = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for marker in (
        'class="topbar"', 'id="nav-new"', 'id="nav-history"', 'id="history-count"',
        'id="topbar-running"', 'id="tracker"', 'id="pause-btn"', 'id="logout-btn"',
        'id="view-new"', 'id="view-job"', 'id="view-history"', 'id="more-options"',
        'id="jd-text"', 'id="company"', 'id="role"', 'id="skill-check"', 'id="check-skills-btn"',
        'id="college-mode"', 'id="bridge-skills"', 'id="research-company"', 'id="no-pdf"',
        'class="paper"',
    ):
        assert marker in index, marker
    assert "new-job-dialog" not in index
    assert index.index('src="/view-model.js"') < index.index('src="/app.js"')
    app_css = (REPO_ROOT / "static" / "app.css").read_text(encoding="utf-8")
    for token in ("#F2F2F0", "#0E7C55", "Instrument Sans", "Source Serif 4"):
        assert token in app_css, token
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "function route(" in app_js and "function go(" in app_js


def test_csp_allows_same_origin_fonts(web_client):
    csp = web_client.get("/").headers["content-security-policy"]
    assert "font-src 'self'" in csp
    assert "fonts.googleapis.com" not in csp


def test_job_view_markup():
    index = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for marker in (
        'id="job-title"', 'id="job-track"', 'id="job-steps"', 'id="job-elapsed"', 'id="job-note"',
        'id="job-summary"', 'id="summary-pct"', 'id="summary-all"', 'id="summary-notes"',
        'id="download-pdf"', 'id="delete-job"', 'id="job-details"', 'id="job-paper"',
        'id="fit-recovery-card"', 'id="bullet-review-card"', 'id="resume-job"', 'id="duplicate-job"',
        'id="panel-review"', 'id="panel-files"', 'id="panel-progress"',
    ):
        assert marker in index, marker
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    for marker in ("ViewModel.progressSteps", "ViewModel.summary", "ViewModel.friendlyNote", "That resume no longer exists."):
        assert marker in app_js, marker


def test_history_markup():
    index = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for marker in ('id="history-title"', 'id="history-note"', 'id="history-list"', 'id="select-btn"', 'id="history-empty"'):
        assert marker in index, marker
    for gone in ('id="queue-list"', 'id="recent-list"', 'id="filter-queue"', 'id="filter-recent"'):
        assert gone not in index, gone
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "ViewModel.historyTag" in app_js


def test_delete_flow_markup():
    index = (REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for marker in (
        'id="select-cancel"', 'id="select-all"', 'id="select-legacy"', 'id="delete-selected"',
        '<dialog class="delete-dialog" id="delete-dialog"', 'id="delete-list"', 'id="delete-size"',
        'id="delete-confirm"', 'id="delete-cancel"', 'id="toast" role="status"',
        "Removes each one's PDF, its copy in your PDF library, its report, and its saved job description. This can't be undone.",
    ):
        assert marker in index, marker
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert '"/api/cleanup"' in app_js
    assert "Running, can't delete" in app_js


def test_running_bar_does_not_cover_delete_on_phones():
    css = (REPO_ROOT / "static" / "app.css").read_text(encoding="utf-8")
    assert "body.selecting .topbar-running" in css
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'document.body.classList.toggle("selecting"' in app_js


def test_summary_is_reset_between_jobs():
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    reset = app_js.split("if (state.reviewJobId !== job.job_id) {", 1)[1].split("}", 1)[0]
    assert "renderSummary(null)" in reset
    assert "Loading the summary" in app_js
    assert "Couldn't load the summary" in app_js


def test_skipped_items_are_named_not_ids():
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "function itemName(id)" in app_js
    assert "${itemName(item.id)} (${item.label})" in app_js
