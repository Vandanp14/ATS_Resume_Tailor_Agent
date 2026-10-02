"""Progress-event serialization, durable per-job journals, and the app-wide stream.

The pipeline's ``ProgressReporter`` protocol is adapted into persistent ``WebEvent``
records (``web_events.jsonl``) per job and, simultaneously, into one process-wide
``StreamEvent`` stream (``/api/events``). The event hub owns the monotonic stream
ids; journals keep their own ordered ids for replay.
"""

from __future__ import annotations

import itertools
import queue
import threading
from pathlib import Path
from typing import Callable

from ..progress import ProgressEvent, ProgressEventKind, ProgressReporter
from .models import StreamEvent, TrackerSnapshot, WebEvent, utc_now_iso

TERMINAL_KINDS = {ProgressEventKind.JOB_COMPLETED, ProgressEventKind.JOB_FAILED}


class EventJournal:
    """Append-only, replayable event store for one job."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._mutex = threading.Lock()
        self._events: list[WebEvent] = []
        if path.is_file():
            self._load()
        self._event_ids = {event.id for event in self._events}

    def _load(self) -> None:
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    self._events.append(WebEvent.model_validate_json(line))
                except Exception:
                    continue
        except OSError:
            pass

    def append(self, event: WebEvent) -> bool:
        """Persist and index; False for a duplicate id."""
        with self._mutex:
            if event.id in self._event_ids:
                return False
            try:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(event.model_dump_json() + "\n")
            except OSError:
                return False
            self._events.append(event)
            self._event_ids.add(event.id)
            return True

    def replay(self, after_id: int | None = None) -> list[WebEvent]:
        with self._mutex:
            if after_id is None or after_id < 0:
                return list(self._events)
            return [event for event in self._events if event.id > after_id]

    def next_id(self) -> int:
        with self._mutex:
            return len(self._events)


class _Subscriber:
    def __init__(self) -> None:
        self.queue: queue.Queue[StreamEvent] = queue.Queue(maxsize=2048)
        self.closed = False


class EventHub:
    """One application stream: monotonic ids, thread-safe fan-out, snapshots."""

    def __init__(self) -> None:
        self._counter = itertools.count()
        self._mutex = threading.Lock()
        self._subscribers: list[_Subscriber] = []

    def next_id(self) -> int:
        return next(self._counter)

    def publish(self, event: StreamEvent) -> None:
        with self._mutex:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            if subscriber.closed:
                continue
            try:
                subscriber.queue.put_nowait(event)
            except queue.Full:
                try:
                    subscriber.queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    subscriber.queue.put_nowait(event)
                except queue.Full:
                    pass

    def publish_snapshot(self, tracker: TrackerSnapshot) -> None:
        self.publish(
            StreamEvent(
                id=self.next_id(),
                kind="tracker_changed",
                data=tracker.model_dump(mode="json"),
            )
        )

    def subscribe(self) -> _Subscriber:
        subscriber = _Subscriber()
        with self._mutex:
            self._subscribers.append(subscriber)
        return subscriber

    def detach(self, subscriber: _Subscriber) -> None:
        subscriber.closed = True
        with self._mutex:
            try:
                self._subscribers.remove(subscriber)
            except ValueError:
                pass


class WebProgressReporter(ProgressReporter):
    """Pipeline reporter writing durable job events and notifying the hub."""

    verbose = True

    def __init__(
        self,
        journal: EventJournal,
        hub: EventHub,
        job_id: str,
        on_stage: Callable[[str, str | None], None] | None = None,
    ) -> None:
        self._journal = journal
        self._hub = hub
        self.job_id = job_id
        self.on_stage = on_stage
        self._mutex = threading.Lock()
        self._active_stage: str | None = None

    @property
    def active_stage(self) -> str | None:
        with self._mutex:
            return self._active_stage

    def emit(self, event: ProgressEvent) -> None:
        kind = event.kind.value
        stage = event.stage.value if event.stage else None
        if event.kind == ProgressEventKind.STAGE_STARTED:
            self._active_stage = stage
            if self.on_stage is not None:
                self.on_stage(self.job_id, stage)
        elif event.kind in {ProgressEventKind.STAGE_COMPLETED, ProgressEventKind.JOB_FAILED}:
            self._active_stage = None
        if stage is None and event.kind in {
            ProgressEventKind.STAGE_DETAIL,
            ProgressEventKind.STAGE_WARNING,
            ProgressEventKind.STAGE_RETRY,
        }:
            stage = self._active_stage
        web = WebEvent(
            id=self._journal.next_id(),
            kind=kind,
            job_id=self.job_id,
            stage=stage,
            message=event.message,
            elapsed_seconds=event.elapsed_seconds,
            attempt=event.attempt,
            max_attempts=event.max_attempts,
            verbose_only=event.verbose_only,
            created_at=utc_now_iso(),
        )
        if self._journal.append(web):
            self._hub.publish(
                StreamEvent(
                    id=self._hub.next_id(),
                    kind=kind,
                    job_id=self.job_id,
                    stage=stage,
                    message=event.message,
                    elapsed_seconds=event.elapsed_seconds,
                    attempt=event.attempt,
                    max_attempts=event.max_attempts,
                    verbose_only=event.verbose_only,
                    created_at=web.created_at,
                )
            )

    def write_job_boundary(self, kind: str, message: str | None = None, elapsed: float | None = None) -> WebEvent:
        """Persist ``job_started``/``job_completed``/``job_failed`` boundary records."""
        event = WebEvent(
            id=self._journal.next_id(),
            kind=kind,
            job_id=self.job_id,
            message=message,
            elapsed_seconds=elapsed,
            created_at=utc_now_iso(),
        )
        if self._journal.append(event):
            self._hub.publish(
                StreamEvent(
                    id=self._hub.next_id(),
                    kind=kind,
                    job_id=self.job_id,
                    message=message,
                    elapsed_seconds=elapsed,
                    created_at=event.created_at,
                )
            )
        return event
