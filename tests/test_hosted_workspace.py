"""Hosted access, durable queue behavior, and revision-safe human review."""

import json
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_tailor.web.access import AccessSettings, password_hash
from tests.conftest import create_job, wait_for

ORIGIN = "https://resume.example.com"
PASSWORD = "a-test-only-workspace-password"


@pytest.fixture(scope="module")
def access():
    return AccessSettings(ORIGIN, password_hash(PASSWORD))


def test_hosted_access_fails_closed():
    with pytest.raises(RuntimeError):
        AccessSettings(ORIGIN)
    for origin in ("http://resume.example.com", "https://resume.example.com/", "https://user@resume.example.com"):
        with pytest.raises(RuntimeError):
            AccessSettings(origin, "bad")


def test_login_logout_expiry_and_all_private_routes(make_app, access):
    app, _ = make_app(access=access, static_dir=Path(__file__).resolve().parents[1] / "static")
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        for path in ("/api/meta", "/api/jobs", "/api/events", "/api/jobs/anything/files/resume.pdf"):
            assert client.get(path).status_code == 401
        assert client.get("/", follow_redirects=False).headers["location"] == "/login"
        assert client.get("/login").status_code == 200
        assert client.get("/healthz", headers={"Host": "healthcheck.railway.app"}).status_code == 200
        assert client.get("/api/meta", headers={"Host": "evil.example.com"}).status_code == 400
        assert client.post("/api/auth/login", json={"password": PASSWORD}, headers={"Origin": "https://evil.example.com"}).status_code == 403
        response = client.post("/api/auth/login", json={"password": PASSWORD})
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        assert "Max-Age=1800" in cookie
        assert client.get("/api/meta").status_code == 200
        token = client.cookies.get(access.cookie_name)
        app.state.sessions.tokens[token] = time.monotonic() - 1
        assert client.get("/api/meta").status_code == 401
        assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 200
        token = client.cookies.get(access.cookie_name)
        assert client.post("/api/auth/logout", json={}).status_code == 200
        assert token not in app.state.sessions.tokens
        assert client.get("/api/meta").status_code == 401


def test_login_rate_limit_and_body_limit(make_app, access):
    app, _ = make_app(access=access)
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
        for _ in range(5):
            assert client.post("/api/auth/login", json={"password": "incorrect"}).status_code == 401
        response = client.post("/api/auth/login", json={"password": PASSWORD})
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "60"
        assert response.headers["content-type"].startswith("application/problem+json")
        response = client.post("/api/auth/login", json={"password": "x" * 512_001})
        assert response.status_code == 413


def test_waiting_jobs_survive_restart_in_order_and_removed_stay_removed(make_app):
    app, _ = make_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    client.post("/api/queue/pause", json={})
    ids = [create_job(client, str(uuid.uuid4()), role=f"Role {index}").json()["job_id"] for index in range(3)]
    client.delete(f"/api/jobs/{ids[1]}")
    app.state.registry.stop()
    app.state.registry._worker.join(2)
    restarted, _ = make_app()
    with TestClient(restarted, base_url="http://127.0.0.1") as client:
        waiting = client.get("/api/queue").json()["waiting"]
        assert [job["job_id"] for job in waiting] == [ids[0], ids[2]]
        assert client.get(f"/api/jobs/{ids[1]}").status_code == 404
        client.post("/api/queue/resume", json={})
        assert wait_for(client, ids[2])["state"] == "completed"


def test_lost_submission_response_reuses_job_and_request_survives_completion(web_client):
    web_client.post("/api/queue/pause", json={})
    key = str(uuid.uuid4())
    first = create_job(web_client, key)
    replay = create_job(web_client, key)
    assert first.status_code == replay.status_code == 202
    assert first.json()["job_id"] == replay.json()["job_id"]
    job_id = first.json()["job_id"]
    web_client.post("/api/queue/resume", json={})
    wait_for(web_client, job_id)
    request = web_client.get(f"/api/jobs/{job_id}/request").json()
    assert request["jd_text"] == "We need a Python engineer."
    assert "idempotency_key" not in request


def test_review_claims_revision_and_invalid_ids(web_client):
    job_id = create_job(web_client, str(uuid.uuid4())).json()["job_id"]
    wait_for(web_client, job_id)
    path = web_client.output_dir / job_id / "match_report.json"
    report = {"coverage_pct": 80, "missing_must_haves": ["Rust"], "inferred_metrics": [{"final_claim": "Reduced latency by 20%", "inference_basis": "Estimate", "source_fact_ids": ["work[0]"]}]}
    path.write_text(json.dumps(report))
    endpoint = f"/api/jobs/{job_id}/review"
    review = web_client.get(endpoint).json()
    assert review["claims"][0]["kind"] == "Estimated metric"
    body = {"revision": review["revision"], "reviewed_ids": [review["claims"][0]["id"]]}
    assert web_client.put(endpoint, json=body).status_code == 200
    assert web_client.get(endpoint).json()["reviewed_ids"] == body["reviewed_ids"]
    assert web_client.put(endpoint, json={**body, "reviewed_ids": ["invented"]}).status_code == 422
    path.write_text(json.dumps({**report, "notes": "New revision"}))
    assert web_client.put(endpoint, json=body).status_code == 409
    assert web_client.get(endpoint).json()["reviewed_ids"] == []
