"""Durable per-job journals and the process-wide event hub."""

from __future__ import annotations

from resume_tailor.progress import JobContext, ProgressEvent, ProgressEventKind, Stage
from resume_tailor.web.models import StreamEvent, TrackerSnapshot, WebEvent
from resume_tailor.web.reporter import EventHub, EventJournal, WebProgressReporter


def reporter(tmp_path):
    journal = EventJournal(tmp_path / "events.jsonl")
    hub = EventHub()
    return journal, hub, WebProgressReporter(journal, hub, "j1")


def test_journal_persistence_replay_and_duplicate_suppression(tmp_path):
    path = tmp_path / "events.jsonl"
    journal = EventJournal(path)
    first = WebEvent(id=0, kind="job_started", job_id="j1")
    second = WebEvent(id=1, kind="stage_started", job_id="j1", stage="Preflight")
    assert journal.append(first) is True
    assert journal.append(second) is True
    assert journal.append(second) is False

    reloaded = EventJournal(path)
    assert [event.id for event in reloaded.replay()] == [0, 1]
    assert [event.id for event in reloaded.replay(after_id=0)] == [1]


def test_reporter_maps_stage_context_and_publishes_live(tmp_path):
    journal, hub, web = reporter(tmp_path)
    subscriber = hub.subscribe()
    job = JobContext(name="j1")
    web.emit(ProgressEvent(ProgressEventKind.STAGE_STARTED, job=job, stage=Stage.REWRITE_WORK))
    web.emit(ProgressEvent(ProgressEventKind.STAGE_DETAIL, job=job, message="swapped verbs"))
    records = journal.replay()
    detail = next(event for event in records if event.kind == "stage_detail")
    assert detail.stage == "Rewrite work"
    assert detail.message == "swapped verbs"
    assert subscriber.queue.get_nowait().kind == "stage_started"
    assert subscriber.queue.get_nowait().kind == "stage_detail"


def test_job_boundary_is_durable_and_monotonic(tmp_path):
    journal, _hub, web = reporter(tmp_path)
    web.write_job_boundary("job_started")
    web.write_job_boundary("job_completed", elapsed=1.25)
    assert [(event.id, event.kind) for event in journal.replay()] == [
        (0, "job_started"),
        (1, "job_completed"),
    ]


def test_hub_detach_stops_delivery():
    hub = EventHub()
    subscriber = hub.subscribe()
    hub.publish(StreamEvent(id=hub.next_id(), kind="queue_changed"))
    assert subscriber.queue.get_nowait().kind == "queue_changed"
    hub.detach(subscriber)
    hub.publish(StreamEvent(id=hub.next_id(), kind="queue_changed"))
    assert subscriber.queue.empty()


def test_tracker_snapshot_uses_app_wide_event_kind():
    hub = EventHub()
    subscriber = hub.subscribe()
    hub.publish_snapshot(TrackerSnapshot(requests_in_minute=4))
    event = subscriber.queue.get_nowait()
    assert event.kind == "tracker_changed"
    assert event.data["requests_in_minute"] == 4
