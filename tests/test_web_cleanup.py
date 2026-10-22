"""Cleanup API: inventory and deletion of finished jobs and legacy output folders."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.conftest import create_job, fake_factory, wait_for


def _finished(client, **extra):
    job_id = create_job(client, str(uuid.uuid4()), **extra).json()["job_id"]
    wait_for(client, job_id)
    return job_id


def _client(make_app, **behavior):
    app, output_dir = make_app(pipeline_factory=fake_factory(**behavior))
    return TestClient(app, base_url="http://127.0.0.1"), output_dir, app


def test_inventory_lists_finished_jobs_and_legacy_folders_with_sizes(make_app):
    client, output_dir, _ = _client(make_app)
    with client:
        job_id = _finished(client)
        legacy = output_dir / "old-run"
        legacy.mkdir()
        (legacy / "resume.pdf").write_bytes(b"x" * 100)
        body = client.get("/api/cleanup").json()
    jobs = {item["id"]: item for item in body["jobs"]}
    assert jobs[job_id]["label"] == "Example Corp, Python Engineer"
    assert jobs[job_id]["bytes"] > 0
    old = {item["id"]: item for item in body["legacy"]}["old-run"]
    assert old["bytes"] == 100
    assert job_id not in {item["id"] for item in body["legacy"]}


def test_delete_removes_folder_pdf_copy_and_saved_request(make_app, tmp_path):
    client, output_dir, _ = _client(make_app)
    with client:
        job_id = _finished(client)
        pdf_copies = list((tmp_path / "resumepdfs").glob("*.pdf"))
        request_file = tmp_path / ".resume-tailor" / "requests" / f"{job_id}.json"
        request_file.write_text("{}", encoding="utf-8")
        assert (output_dir / job_id).is_dir() and pdf_copies
        result = client.post("/api/cleanup", json={"job_ids": [job_id]}).json()
        assert result["deleted_jobs"] == [job_id]
        assert result["freed_bytes"] > 0
        assert not (output_dir / job_id).exists()
        assert not list((tmp_path / "resumepdfs").glob("*.pdf"))
        assert not request_file.exists()
        listed = client.get("/api/jobs").json()
        assert job_id not in str(listed)
        assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_delete_legacy_folders_only_when_asked(make_app):
    client, output_dir, _ = _client(make_app)
    with client:
        legacy = output_dir / "old-run"
        legacy.mkdir()
        (legacy / "a.txt").write_text("hi", encoding="utf-8")
        first = client.post("/api/cleanup", json={}).json()
        assert first["deleted_legacy"] == [] and legacy.exists()
        second = client.post("/api/cleanup", json={"legacy_ids": ["old-run"]}).json()
        assert "old-run" in second["deleted_legacy"]
        assert not legacy.exists()


def test_running_or_queued_jobs_are_skipped_with_reason(make_app):
    client, output_dir, _ = _client(make_app, wait=1.0)
    with client:
        running = create_job(client, str(uuid.uuid4())).json()["job_id"]
        wait_for(client, running, states=("running",))
        queued = create_job(client, str(uuid.uuid4()), jd_text="Another posting.").json()["job_id"]
        result = client.post(
            "/api/cleanup", json={"job_ids": [running, queued]}
        )
        assert result.status_code == 200
        body = result.json()
        assert {item["id"] for item in body["skipped"]} == {running, queued}
        assert all(item["label"] for item in body["skipped"])
        assert body["deleted_jobs"] == []
        assert (output_dir / running).is_dir() and (output_dir / queued).is_dir()
        wait_for(client, running)
        wait_for(client, queued)


def test_symlinked_or_outside_paths_are_never_deleted(make_app, tmp_path):
    client, output_dir, _ = _client(make_app)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    with client:
        (output_dir / "evil").symlink_to(outside, target_is_directory=True)
        body = client.post("/api/cleanup", json={"legacy_ids": ["evil"]}).json()
        assert "evil" in {item["id"] for item in body["skipped"]}
        assert "evil" not in body["deleted_legacy"]
        assert (outside / "keep.txt").exists()
        assert (output_dir / "evil").is_symlink()
        # Traversal-looking ids are unknown, never resolved against the disk.
        body = client.post("/api/cleanup", json={"job_ids": ["../outside"]}).json()
        assert [item["id"] for item in body["skipped"]] == ["../outside"]
        assert outside.exists()


def test_unknown_ids_are_skipped_not_errors(make_app):
    client, _, _ = _client(make_app)
    with client:
        response = client.post("/api/cleanup", json={"job_ids": ["nope"]})
        assert response.status_code == 200
        body = response.json()
        assert [item["id"] for item in body["skipped"]] == ["nope"]
        assert body["deleted_jobs"] == [] and body["freed_bytes"] == 0


def test_symlinked_pdf_copy_is_reported_and_left_alone(make_app, tmp_path):
    client, output_dir, _ = _client(make_app)
    with client:
        job_id = _finished(client)
        pdf = next((tmp_path / "resumepdfs").glob("*.pdf"))
        target = tmp_path / "precious.pdf"
        target.write_bytes(b"keep")
        pdf.unlink()
        pdf.symlink_to(target)
        body = client.post("/api/cleanup", json={"job_ids": [job_id]}).json()
        assert body["deleted_jobs"] == [job_id]
        assert any(
            item["id"] == job_id and item["label"].startswith("Symlink, not deleted")
            for item in body["skipped"]
        )
        assert pdf.is_symlink() and target.read_bytes() == b"keep"


def test_failed_folder_removal_is_skipped_not_deleted(make_app, monkeypatch):
    client, output_dir, _ = _client(make_app)
    with client:
        job_id = _finished(client)

        def boom(*args, **kwargs):
            raise OSError("denied")

        monkeypatch.setattr("shutil.rmtree", boom)
        body = client.post("/api/cleanup", json={"job_ids": [job_id]}).json()
        assert body["deleted_jobs"] == []
        assert body["freed_bytes"] == 0
        assert [item["id"] for item in body["skipped"]] == [job_id]
        assert (output_dir / job_id).is_dir()
        assert client.get(f"/api/jobs/{job_id}").status_code == 200


def test_job_whose_folder_was_removed_by_hand_can_still_be_deleted(make_app, tmp_path):
    import shutil

    client, output_dir, _ = _client(make_app)
    with client:
        job_id = _finished(client)
        shutil.rmtree(output_dir / job_id)
        result = client.post("/api/cleanup", json={"job_ids": [job_id]}).json()
        assert result["deleted_jobs"] == [job_id]
        assert not list((tmp_path / "resumepdfs").glob("*.pdf"))
        assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_only_the_confirmed_old_folders_are_deleted(make_app):
    client, output_dir, _ = _client(make_app)
    with client:
        shown = output_dir / "old-run"
        shown.mkdir()
        appeared_later = output_dir / "new-cli-run"
        appeared_later.mkdir()
        body = client.post(
            "/api/cleanup", json={"legacy_ids": ["old-run", "../outside", "missing"]}
        ).json()
        assert body["deleted_legacy"] == ["old-run"]
        assert not shown.exists()
        assert appeared_later.is_dir()


def test_resume_cannot_requeue_a_job_while_it_is_being_deleted(make_app, tmp_path, monkeypatch):
    import shutil

    from resume_tailor.web.jobs import RecoveryRequestError

    client, output_dir, app = _client(make_app, exit_code=1)
    registry = app.state.registry
    with client:
        job_id = _finished(client)
        assert (tmp_path / ".resume-tailor" / "requests" / f"{job_id}.json").is_file()
        assert client.get(f"/api/jobs/{job_id}").json()["job"]["state"] == "failed"
        job = registry._jobs[job_id]
        real_rmtree = shutil.rmtree
        attempts = []

        def rmtree_then_resume(path, *args, **kwargs):
            # Another tab presses Resume run while the folder is being removed.
            try:
                registry.enqueue_resume(job)
                attempts.append("queued")
            except RecoveryRequestError as error:
                attempts.append(error.status)
            real_rmtree(path, *args, **kwargs)

        monkeypatch.setattr("shutil.rmtree", rmtree_then_resume)
        body = client.post("/api/cleanup", json={"job_ids": [job_id]}).json()
        assert body["deleted_jobs"] == [job_id]
        assert attempts and attempts[0] != "queued"
        assert job not in registry._waiting
