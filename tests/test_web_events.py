"""Durable per-job journals and the process-wide event hub."""

from __future__ import annotations

import asyncio
import threading
from queue import Empty

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
    assert reloaded.append(second) is False


def test_journal_failed_write_can_be_retried(tmp_path):
    path = tmp_path / "missing" / "events.jsonl"
    journal = EventJournal(path)
    event = WebEvent(id=0, kind="job_started", job_id="j1")
    assert journal.append(event) is False
    path.parent.mkdir()
    assert journal.append(event) is True
    assert journal.replay() == [event]


def test_full_subscriber_drops_oldest_without_blocking_other_subscribers():
    hub = EventHub()
    slow = hub.subscribe()
    for index in range(slow.queue.maxsize):
        hub.publish(StreamEvent(id=index, kind="queue_changed"))
    fast = hub.subscribe()
    latest = StreamEvent(id=slow.queue.maxsize, kind="queue_changed")
    publisher = threading.Thread(target=hub.publish, args=(latest,), daemon=True)
    publisher.start()
    publisher.join(timeout=2)
    assert not publisher.is_alive(), "A full subscriber queue blocked publishing"
    assert fast.queue.get_nowait() == latest
    retained = [slow.queue.get_nowait().id for _ in range(slow.queue.maxsize)]
    assert retained == list(range(1, latest.id + 1))


def test_event_stream_survives_idle_timeout_and_detaches(make_app, monkeypatch):
    app, _ = make_app()
    endpoint = next(
        route.endpoint for route in app.routes if route.path == "/api/events"
    )
    latest = StreamEvent(id=7, kind="queue_changed")
    calls = 0
    detached = []
    original_detach = EventHub.detach

    async def receive(_get, _block, _timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise Empty
        return latest

    def detach(hub, subscriber):
        original_detach(hub, subscriber)
        detached.append(subscriber)

    monkeypatch.setattr(asyncio, "to_thread", receive)
    monkeypatch.setattr(EventHub, "detach", detach)

    async def consume():
        stream = endpoint()
        try:
            event = await anext(stream)
            assert event.id == "7"
            assert event.event == "queue_changed"
        finally:
            await stream.aclose()

    asyncio.run(consume())
    assert calls == 2
    assert len(detached) == 1 and detached[0].closed


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
