"""Application-tracker API, persistence, CSV, and event regressions."""

from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from resume_tailor.web.models import StreamEvent
from resume_tailor.web.reporter import EventHub
from tests.conftest import create_job


CSV_COLUMNS = [
    "job_id",
    "company",
    "role",
    "application_status",
    "applied_on",
    "job_url",
    "notes",
    "tracking_updated_at",
    "tailoring_state",
    "created_at",
    "finished_at",
    "resume_available",
]


def _create_paused_job(client: TestClient, **overrides: str) -> str:
    assert client.post("/api/queue/pause", json={}).status_code == 200
    response = create_job(client, str(uuid.uuid4()), **overrides)
    assert response.status_code == 202
    return response.json()["job_id"]


def _application_payload(**overrides: object) -> dict[str, object]:
    return {
        "status": "applied",
        "applied_on": "2026-08-13",
        "job_url": "https://example.com/jobs/123",
        "notes": "Submitted through the company portal.",
        "revision": 0,
        **overrides,
    }


def test_legacy_jobs_are_unavailable_and_excluded_with_cli_runs(make_app):
    _unused_app, output_dir = make_app()
    legacy_job_id = str(uuid.uuid4())
    legacy_dir = output_dir / legacy_job_id
    legacy_dir.mkdir()
    legacy_metadata = {
        "job_id": legacy_job_id,
        "source": "web",
        "state": "completed",
        "company": "Legacy Corp",
        "role": "Platform Engineer",
        "options": {},
        "created_at": "2026-08-12T14:00:00Z",
        "finished_at": "2026-08-12T14:05:00Z",
    }
    persisted_text = json.dumps(legacy_metadata, indent=2)
    metadata_path = legacy_dir / "web_job.json"
    metadata_path.write_text(persisted_text, encoding="utf-8")

    cli_dir = output_dir / "cli-only-run"
    cli_dir.mkdir()
    (cli_dir / "resume.pdf").write_bytes(b"%PDF-1.4 fake")

    app, _ = make_app()
    client = TestClient(app, base_url="http://127.0.0.1")

    response = client.get("/api/applications")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "summary": {"total": 0, "applied": 0, "not_applied": 0},
        "items": [],
    }

    legacy_detail = client.get(f"/api/jobs/{legacy_job_id}")
    assert legacy_detail.status_code == 200
    legacy_job = legacy_detail.json()["job"]
    assert legacy_job["application_tracking_available"] is False
    assert legacy_job["application"] == {
        "status": "not_applied",
        "applied_on": None,
        "job_url": None,
        "notes": "",
        "updated_at": None,
        "revision": 0,
    }
    unavailable = client.put(
        f"/api/jobs/{legacy_job_id}/application",
        json=_application_payload(),
    )
    assert unavailable.status_code == 409

    state_dir = Path(client.get("/api/meta").json()["directory_labels"]["state_dir"])
    with (state_dir / "applications.csv").open(newline="", encoding="utf-8") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert csv_rows == []
    assert metadata_path.read_text(encoding="utf-8") == persisted_text


def test_put_uses_json_body_conflicts_and_allows_identical_replay(make_app):
    app, output_dir = make_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    job_id = _create_paused_job(client)
    payload = _application_payload(
        job_url="  https://example.com/jobs/123  ",
        notes="  Submitted through the company portal.  ",
    )

    response = client.put(f"/api/jobs/{job_id}/application", json=payload)
    assert response.status_code == 200
    first = response.json()
    assert first["application"]["job_url"] == "https://example.com/jobs/123"
    assert first["application"]["notes"] == "Submitted through the company portal."
    assert first["application"]["revision"] == 1
    assert first["application"]["updated_at"] is not None

    persisted = json.loads(
        (output_dir / job_id / "web_job.json").read_text(encoding="utf-8")
    )
    assert persisted["application_tracking_available"] is True
    assert persisted["application"] == first["application"]
    detail_job = client.get(f"/api/jobs/{job_id}").json()["job"]
    assert detail_job["application_tracking_available"] is True
    assert detail_job["application"] == first["application"]

    replay = client.put(f"/api/jobs/{job_id}/application", json=payload)
    assert replay.status_code == 200
    assert replay.json()["application"] == first["application"]

    conflict = client.put(
        f"/api/jobs/{job_id}/application",
        json=_application_payload(notes="A different stale edit."),
    )
    assert conflict.status_code == 409
    assert conflict.headers["content-type"].startswith("application/problem+json")

    invalid_shape = client.put(
        f"/api/jobs/{job_id}/application",
        json=_application_payload(revision=1, unexpected=True),
    )
    assert invalid_shape.status_code == 422


def test_applied_without_date_uses_server_local_calendar_date(make_app):
    app, _ = make_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    job_id = _create_paused_job(client)

    response = client.put(
        f"/api/jobs/{job_id}/application",
        json=_application_payload(applied_on=None),
    )

    assert response.status_code == 200
    assert (
        response.json()["application"]["applied_on"]
        == datetime.now().astimezone().date().isoformat()
    )


def test_csv_uses_configured_state_dir_rfc4180_and_formula_neutralization(make_app):
    app, _ = make_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    company = "=SUM(1,2)"
    role = 'Senior "Platform", Engineer'
    job_id = _create_paused_job(client, company=company, role=role)
    notes = '=CMD("quoted, value")\nFollow-up next week.'
    payload = _application_payload(
        job_url="https://example.com/jobs/123?team=core,platform",
        notes=notes,
    )
    assert (
        client.put(f"/api/jobs/{job_id}/application", json=payload).status_code == 200
    )

    state_dir = client.get("/api/meta").json()["directory_labels"]["state_dir"]
    csv_path = Path(state_dir) / "applications.csv"
    assert csv_path.is_file()

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == CSV_COLUMNS
    assert len(rows) == 1
    assert rows[0]["job_id"] == job_id
    assert rows[0]["company"] == f"'{company}"
    assert rows[0]["role"] == role
    assert rows[0]["job_url"] == payload["job_url"]
    assert rows[0]["notes"] == f"'{notes}"
    assert rows[0]["application_status"] == "applied"
    assert rows[0]["resume_available"] == "false"

    download = client.get("/api/applications.csv")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/csv")
    assert download.content == csv_path.read_bytes()


def test_successful_update_publishes_one_application_sse_event(make_app, monkeypatch):
    published: list[StreamEvent] = []
    original_publish = EventHub.publish

    def capture_publish(self: EventHub, event: StreamEvent) -> None:
        published.append(event)
        original_publish(self, event)

    monkeypatch.setattr(EventHub, "publish", capture_publish)
    app, _ = make_app()
    client = TestClient(app, base_url="http://127.0.0.1")
    job_id = _create_paused_job(client)
    payload = _application_payload()

    assert (
        client.put(f"/api/jobs/{job_id}/application", json=payload).status_code == 200
    )
    application_events = [
        event for event in published if event.kind == "job_application_updated"
    ]
    assert len(application_events) == 1
    assert application_events[0].job_id == job_id
    assert application_events[0].data["job_id"] == job_id
    assert application_events[0].data["application"]["revision"] == 1

    assert (
        client.put(f"/api/jobs/{job_id}/application", json=payload).status_code == 200
    )
    assert (
        len([event for event in published if event.kind == "job_application_updated"])
        == 1
    )
