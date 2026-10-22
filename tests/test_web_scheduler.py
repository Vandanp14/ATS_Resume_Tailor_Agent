"""Gemini web scheduler: rolling requests, observed tokens, and Pacific day cap."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from resume_tailor.web.scheduler import GeminiScheduler


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


def scheduler(clock: FakeClock, **limits) -> GeminiScheduler:
    return GeminiScheduler(
        min_interval=0,
        max_per_minute=limits.pop("max_per_minute", 15),
        clock=clock.now,
        sleeper=clock.sleep,
        **limits,
    )


def test_request_attempts_use_a_rolling_minute() -> None:
    clock = FakeClock()
    tracker = scheduler(clock, max_per_minute=2)

    tracker.wait()
    tracker.wait()
    assert tracker.snapshot().requests_in_minute == 2

    tracker.wait()
    assert clock.value == 60
    assert tracker.snapshot().requests_in_minute == 1


def test_observed_input_tokens_gate_following_request() -> None:
    clock = FakeClock()
    tracker = scheduler(clock, max_input_tokens_per_minute=250_000)

    attempt_id = tracker.wait()
    tracker.record_usage(attempt_id, 250_000)
    snapshot = tracker.snapshot()
    assert snapshot.input_tokens_in_minute == 250_000
    assert snapshot.wait_reason == "tpm"

    tracker.wait()
    assert clock.value == 60


def test_token_tracker_marks_missing_response_metadata() -> None:
    clock = FakeClock()
    tracker = scheduler(clock)
    tracker.wait()
    assert tracker.snapshot().token_usage_complete is False


def test_daily_limit_resets_at_midnight_pacific() -> None:
    pacific = ZoneInfo("America/Los_Angeles")
    start = datetime(2026, 8, 9, 23, 59, tzinfo=pacific).timestamp()
    clock = FakeClock(start)
    tracker = scheduler(clock, max_requests_per_day=1)

    tracker.wait()
    assert tracker.snapshot().wait_reason == "rpd"
    tracker.wait()
    assert clock.value == datetime(2026, 8, 10, 0, 0, tzinfo=pacific).timestamp()
    assert tracker.snapshot().requests_today == 1


def test_usage_persists_and_old_timestamp_lines_still_load(tmp_path) -> None:
    now = datetime(2026, 8, 9, 12, 0, tzinfo=ZoneInfo("UTC")).timestamp()
    clock = FakeClock(now)
    path = tmp_path / "calls.jsonl"
    path.write_text("2026-08-09T11:59:45Z\n", encoding="utf-8")
    tracker = GeminiScheduler(0, 15, calls_path=path, clock=clock.now, sleeper=clock.sleep)

    attempt_id = tracker.wait()
    tracker.record_usage(attempt_id, 1234)
    reloaded = GeminiScheduler(0, 15, calls_path=path, clock=clock.now, sleeper=clock.sleep)
    snapshot = reloaded.snapshot()
    assert snapshot.requests_in_minute == 2
    assert snapshot.input_tokens_in_minute == 1234
    assert any(json.loads(line)["attempt_id"] == attempt_id for line in path.read_text().splitlines())


# -- per-model metering: free-tier limits are per model ------------------------


def test_models_do_not_block_each_other() -> None:
    clock = FakeClock(1_000.0)
    tracker = scheduler(clock)
    for _ in range(10):
        tracker.wait("gemini-3.8-flash")
    assert clock.sleeps == []
    tracker.wait("gemini-3.7-flash")
    assert clock.sleeps == []
    tracker.wait("gemini-3.8-flash")
    assert sum(clock.sleeps) == 60


def test_rpm_comes_from_model_table() -> None:
    clock = FakeClock(1_000.0)
    tracker = scheduler(clock, max_per_minute=3)
    for _ in range(15):
        tracker.wait("gemini-3.5-flash-lite")
    assert clock.sleeps == []
    tracker.wait("gemini-3.5-flash-lite")
    assert sum(clock.sleeps) == 60


def test_model_is_persisted_and_legacy_records_load(tmp_path) -> None:
    clock = FakeClock(1_000.0)
    path = tmp_path / "calls.jsonl"
    path.write_text(
        json.dumps({"attempt_id": "old", "attempted_at": "1970-01-01T00:16:30Z"}) + "\n",
        encoding="utf-8",
    )
    tracker = GeminiScheduler(
        min_interval=0, max_per_minute=15, calls_path=path, clock=clock.now, sleeper=clock.sleep
    )
    tracker.wait("gemini-3.7-flash")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["model"] == "gemini-3.7-flash"
    assert "model" not in rows[0]
    assert tracker.snapshot().requests_in_minute == 2
