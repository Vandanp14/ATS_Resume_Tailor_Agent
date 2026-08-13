"""Interactive one-page fit recovery API, queue, durability, and idempotency."""

from __future__ import annotations

import threading
import uuid

from fastapi.testclient import TestClient

from models import ScoredBullet, ScoredWork
from render import ScoredResume
from resume_tailor.fit_recovery import load_fit_recovery, persist_fit_recovery
from resume_tailor.pipeline import TailorPipeline
from resume_tailor.runtime import write_json
from tests.conftest import create_job, wait_for


class RecoveryPipe(TailorPipeline):
    """Pipeline stub that deterministically exhausts automatic one-page fitting."""

    def run(self, master, jd_text, out_dir, no_pdf, job):
        del master, jd_text, no_pdf, job
        assert self.allow_fit_recovery is True
        scored = ScoredResume(
            work=[
                ScoredWork(
                    name="Example Corp",
                    position="Engineer",
                    relevance=50,
                    highlights=[
                        ScoredBullet(
                            text="Built a lower-relevance internal reporting workflow.",
                            relevance=42,
                        )
                    ],
                )
            ]
        )
        persist_fit_recovery(
            out_dir,
            scored,
            page_count=2,
            pending_report={"pipeline_status": "action_required"},
            trim_log=["skill group removed"],
            concision_log=[{"candidate_id": "work:0:0"}],
            page_counter=lambda resume: 1 if not resume.work[0].highlights else 2,
        )
        return 2


def _action_job(make_app, *, recovery_handler=None):
    app, output_dir = make_app(
        pipeline_factory=RecoveryPipe,
        recovery_handler=recovery_handler,
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    job_id = create_job(client, str(uuid.uuid4())).json()["job_id"]
    status = wait_for(client, job_id, states=("action_required",))
    return app, client, output_dir, job_id, status


def _complete_recovery(directory, candidate_ids):
    assert candidate_ids
    (directory / ".fit_recovery.json").unlink()
    write_json(directory / "tailored.json", {"basics": {"name": "Test User"}})
    write_json(directory / "match_report.json", {"manual_fit_removals": candidate_ids})
    (directory / "resume.pdf").write_bytes(b"%PDF-1.4 recovered")
    return 0


def test_action_required_exposes_only_safe_recovery_fields(make_app):
    _app, client, output_dir, job_id, status = _action_job(make_app)
    assert status["finished_at"] is not None
    assert status["active"] is False
    assert status["queue_position"] is None

    response = client.get(f"/api/jobs/{job_id}/fit-recovery")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "revision",
        "page_count",
        "concision_attempts",
        "candidates",
        "recommended_candidate_ids",
    }
    assert body["page_count"] == 2
    assert body["concision_attempts"] == 1
    assert set(body["candidates"][0]) == {
        "candidate_id",
        "kind",
        "group",
        "label",
        "text",
        "relevance",
        "estimated_lines",
        "recommendation",
        "reason",
    }
    assert "scored_resume" not in body
    assert ".fit_recovery.json" not in status["artifacts"]
    assert (output_dir / job_id / ".fit_recovery.json").is_file()
    assert client.get(f"/api/jobs/{job_id}/files/.fit_recovery.json").status_code == 404
    kinds = [
        event["kind"] for event in client.get(f"/api/jobs/{job_id}").json()["events"]
    ]
    assert "job_action_required" in kinds


def test_recovery_submission_validates_boundary_and_completes(make_app):
    seen: list[list[str]] = []

    def handler(directory, candidate_ids):
        seen.append(candidate_ids)
        return _complete_recovery(directory, candidate_ids)

    _app, client, _output_dir, job_id, _status = _action_job(
        make_app, recovery_handler=handler
    )
    recovery = client.get(f"/api/jobs/{job_id}/fit-recovery").json()
    candidate_id = recovery["candidates"][0]["candidate_id"]
    endpoint = f"/api/jobs/{job_id}/fit-recovery"

    assert (
        client.post(
            endpoint,
            json={"revision": 1, "candidate_ids": []},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        ).status_code
        == 422
    )
    assert (
        client.post(
            endpoint,
            json={"revision": 1, "candidate_ids": [candidate_id, candidate_id]},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        ).status_code
        == 422
    )
    assert (
        client.post(
            endpoint,
            json={"revision": 2, "candidate_ids": [candidate_id]},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        ).status_code
        == 409
    )
    assert (
        client.post(
            endpoint,
            json={"revision": 1, "candidate_ids": ["not-issued"]},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        ).status_code
        == 422
    )
    assert (
        client.post(
            endpoint,
            json={"revision": 1, "candidate_ids": [candidate_id], "admin": True},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        ).status_code
        == 422
    )
    assert (
        client.post(
            endpoint,
            json={"revision": 1, "candidate_ids": [candidate_id]},
            headers={"Idempotency-Key": "bad"},
        ).status_code
        == 422
    )

    response = client.post(
        endpoint,
        json={"revision": 1, "candidate_ids": [candidate_id]},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 202
    status = wait_for(client, job_id)
    assert status["state"] == "completed"
    assert status["started_at"] is not None
    assert seen == [[candidate_id]]
    kinds = [
        event["kind"] for event in client.get(f"/api/jobs/{job_id}").json()["events"]
    ]
    assert "job_recovery_queued" in kinds
    assert "job_recovery_started" in kinds
    assert kinds[-1] == "job_completed"
    assert client.get(endpoint).status_code == 409


def test_recovery_idempotency_conflict_and_completed_replay(make_app):
    entered = threading.Event()
    release = threading.Event()

    def blocking_handler(directory, candidate_ids):
        entered.set()
        assert release.wait(timeout=5)
        return _complete_recovery(directory, candidate_ids)

    _app, client, _output_dir, job_id, _status = _action_job(
        make_app, recovery_handler=blocking_handler
    )
    recovery = client.get(f"/api/jobs/{job_id}/fit-recovery").json()
    candidate_id = recovery["candidates"][0]["candidate_id"]
    endpoint = f"/api/jobs/{job_id}/fit-recovery"
    key = str(uuid.uuid4())
    body = {"revision": 1, "candidate_ids": [candidate_id]}
    first = client.post(endpoint, json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 202
    assert entered.wait(timeout=5)
    duplicate = client.post(endpoint, json=body, headers={"Idempotency-Key": key})
    assert duplicate.status_code == 409
    release.set()
    wait_for(client, job_id)
    replay = client.post(endpoint, json=body, headers={"Idempotency-Key": key})
    assert replay.status_code == 202
    assert replay.json() == first.json()
    mismatch = client.post(
        endpoint,
        json={"revision": 1, "candidate_ids": [candidate_id, "different"]},
        headers={"Idempotency-Key": key},
    )
    assert mismatch.status_code == 422
    assert mismatch.headers["content-type"].startswith("application/problem+json")


def test_insufficient_recovery_returns_new_revision(make_app):
    def still_large(directory, candidate_ids):
        bundle = load_fit_recovery(directory)
        assert candidate_ids
        write_json(
            directory / ".fit_recovery.json",
            bundle.model_copy(update={"revision": bundle.revision + 1}),
        )
        return 2

    _app, client, _output_dir, job_id, _status = _action_job(
        make_app, recovery_handler=still_large
    )
    recovery = client.get(f"/api/jobs/{job_id}/fit-recovery").json()
    response = client.post(
        f"/api/jobs/{job_id}/fit-recovery",
        json={
            "revision": 1,
            "candidate_ids": [recovery["candidates"][0]["candidate_id"]],
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 202
    wait_for(client, job_id, states=("action_required",))
    latest = client.get(f"/api/jobs/{job_id}/fit-recovery").json()
    assert latest["revision"] == 2


def test_action_required_survives_registry_restart(make_app):
    _app, client, _output_dir, job_id, _status = _action_job(make_app)
    expected = client.get(f"/api/jobs/{job_id}/fit-recovery").json()

    restarted_app, _ = make_app(pipeline_factory=RecoveryPipe)
    restarted = TestClient(restarted_app, base_url="http://127.0.0.1")
    status = restarted.get(f"/api/jobs/{job_id}").json()["job"]
    assert status["state"] == "action_required"
    assert restarted.get(f"/api/jobs/{job_id}/fit-recovery").json() == expected


def test_action_required_releases_worker_for_later_jobs(make_app):
    app, _output_dir = make_app(pipeline_factory=RecoveryPipe)
    client = TestClient(app, base_url="http://127.0.0.1")
    first = create_job(client, str(uuid.uuid4())).json()["job_id"]
    assert wait_for(client, first, states=("action_required",))["active"] is False
    second = create_job(client, str(uuid.uuid4()), jd_text="A different role").json()[
        "job_id"
    ]
    assert wait_for(client, second, states=("action_required",))["active"] is False
    assert client.get("/api/queue").json()["active_job_id"] is None


def test_queued_recovery_survives_registry_restart(make_app):
    _app, client, _output_dir, job_id, _status = _action_job(make_app)
    assert client.post("/api/queue/pause", json={}).status_code == 200
    recovery = client.get(f"/api/jobs/{job_id}/fit-recovery").json()
    candidate_id = recovery["candidates"][0]["candidate_id"]
    queued = client.post(
        f"/api/jobs/{job_id}/fit-recovery",
        json={"revision": 1, "candidate_ids": [candidate_id]},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert queued.status_code == 202
    assert client.get(f"/api/jobs/{job_id}").json()["job"]["state"] == "queued"

    restarted_app, _ = make_app(
        pipeline_factory=RecoveryPipe,
        recovery_handler=_complete_recovery,
    )
    restarted = TestClient(restarted_app, base_url="http://127.0.0.1")
    restarted_status = restarted.get(f"/api/jobs/{job_id}").json()["job"]
    assert restarted_status["state"] == "queued"
    assert restarted_status["started_at"] is not None
    assert restarted_status["finished_at"] is None
    restarted.post("/api/queue/resume", json={})
    assert wait_for(restarted, job_id)["state"] == "completed"
