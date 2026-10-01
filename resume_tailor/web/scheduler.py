"""Process-wide Gemini pacing and observable web-app quota usage.

The scheduler records every outbound attempt before it is forwarded, including
transport retries. RPM uses a rolling 60-second window, TPM uses observed input
tokens returned by Gemini, and RPD resets at midnight America/Los_Angeles.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

from llm_utils import ChatProvider

from .io import atomic_write_text
from .models import (
    DEFAULT_MAX_INPUT_TOKENS_PER_MINUTE,
    DEFAULT_MAX_REQUESTS_PER_DAY,
    FIFO_WINDOW_SECONDS,
    TrackerSnapshot,
)

PACIFIC = ZoneInfo("America/Los_Angeles")


class _Hub(Protocol):
    def publish_snapshot(self, tracker: TrackerSnapshot) -> None: ...


@dataclass
class UsageRecord:
    attempt_id: str
    attempted_at: float
    input_tokens: int | None = None


def _iso(timestamp: float) -> str:
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _timestamp(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _pacific_day_bounds(now: float) -> tuple[float, float]:
    local = datetime.fromtimestamp(now, tz=PACIFIC)
    start_date = local.date()
    next_date: date = start_date + timedelta(days=1)
    start = datetime.combine(start_date, datetime_time.min, tzinfo=PACIFIC)
    end = datetime.combine(next_date, datetime_time.min, tzinfo=PACIFIC)
    return start.timestamp(), end.timestamp()


class GeminiScheduler:
    """Pace web-app Gemini attempts across pipelines and SDK retries."""

    def __init__(
        self,
        min_interval: float,
        max_per_minute: int,
        calls_path: Path | None = None,
        clock: Callable[[], float] = time.time,
        hub: _Hub | None = None,
        *,
        max_input_tokens_per_minute: int = DEFAULT_MAX_INPUT_TOKENS_PER_MINUTE,
        max_requests_per_day: int = DEFAULT_MAX_REQUESTS_PER_DAY,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = max(float(min_interval), 0.0)
        self.max_per_minute = max(int(max_per_minute), 1)
        self.max_input_tokens_per_minute = max(int(max_input_tokens_per_minute), 1)
        self.max_requests_per_day = max(int(max_requests_per_day), 1)
        self.window_seconds = FIFO_WINDOW_SECONDS
        self.hub = hub
        self._calls_path = Path(calls_path) if calls_path else None
        self._clock = clock
        self._sleeper = sleeper
        self._mutex = threading.Lock()
        self._records: list[UsageRecord] = []
        self._paused = False
        self._load()

    # Persistence

    def _load(self) -> None:
        if not self._calls_path or not self._calls_path.is_file():
            return
        records: list[UsageRecord] = []
        for index, line in enumerate(
            self._calls_path.read_text(encoding="utf-8").splitlines()
        ):
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = raw
            if isinstance(payload, dict):
                stamp = _timestamp(payload.get("attempted_at"))
                attempt_id = payload.get("attempt_id")
                tokens = payload.get("input_tokens")
                if stamp is None or not isinstance(attempt_id, str):
                    continue
                input_tokens = tokens if isinstance(tokens, int) and tokens >= 0 else None
                records.append(UsageRecord(attempt_id, stamp, input_tokens))
                continue
            stamp = _timestamp(payload)
            if stamp is not None:
                records.append(UsageRecord(f"legacy-{index}-{int(stamp * 1000)}", stamp))
        self._records = sorted(records, key=lambda record: record.attempted_at)
        self._prune(self._clock())

    def _persist(self) -> None:
        if not self._calls_path:
            return
        lines = []
        for record in self._records:
            payload: dict[str, object] = {
                "attempt_id": record.attempt_id,
                "attempted_at": _iso(record.attempted_at),
            }
            if record.input_tokens is not None:
                payload["input_tokens"] = record.input_tokens
            lines.append(json.dumps(payload, separators=(",", ":")))
        atomic_write_text(self._calls_path, "\n".join(lines) + ("\n" if lines else ""))

    def _prune(self, now: float) -> None:
        day_start, _ = _pacific_day_bounds(now)
        cutoff = min(now - self.window_seconds, day_start)
        self._records = [record for record in self._records if record.attempted_at > cutoff]

    # Limit calculations

    def _recent(self, now: float) -> list[UsageRecord]:
        cutoff = now - self.window_seconds
        return [record for record in self._records if record.attempted_at > cutoff]

    def _today(self, now: float) -> list[UsageRecord]:
        start, _ = _pacific_day_bounds(now)
        return [record for record in self._records if record.attempted_at >= start]

    def _next_allowed_under_lock(self, now: float) -> tuple[float | None, str | None]:
        candidates: list[tuple[float, str]] = []
        recent = self._recent(now)
        if recent and self.min_interval > 0:
            candidates.append((recent[-1].attempted_at + self.min_interval, "interval"))

        if len(recent) >= self.max_per_minute:
            expiry_index = len(recent) - self.max_per_minute
            candidates.append(
                (recent[expiry_index].attempted_at + self.window_seconds, "rpm")
            )

        observed_tokens = sum(record.input_tokens or 0 for record in recent)
        if observed_tokens >= self.max_input_tokens_per_minute:
            removed = 0
            for record in recent:
                removed += record.input_tokens or 0
                if observed_tokens - removed < self.max_input_tokens_per_minute:
                    candidates.append(
                        (record.attempted_at + self.window_seconds, "tpm")
                    )
                    break

        today = self._today(now)
        if len(today) >= self.max_requests_per_day:
            _, reset = _pacific_day_bounds(now)
            candidates.append((reset, "rpd"))

        future = [candidate for candidate in candidates if candidate[0] > now]
        if not future:
            return None, None
        return max(future, key=lambda candidate: candidate[0])

    def next_allowed_at(self) -> float | None:
        with self._mutex:
            now = self._clock()
            self._prune(now)
            return self._next_allowed_under_lock(now)[0]

    # Pacing and response usage

    def wait(self) -> str:
        """Wait for all known limits, record an attempt, and return its id."""
        published_key: tuple[float | None, str | None] | None = None
        while True:
            with self._mutex:
                now = self._clock()
                self._prune(now)
                next_allowed, reason = self._next_allowed_under_lock(now)
                snapshot = self._snapshot_under_lock(now)
            remaining = (next_allowed - now) if next_allowed is not None else 0.0
            if remaining <= 0:
                break
            key = (next_allowed, reason)
            if self.hub is not None and key != published_key:
                self.hub.publish_snapshot(snapshot)
                published_key = key
            self._sleeper(min(remaining, 1.0))

        attempt_id = str(uuid.uuid4())
        with self._mutex:
            self._records.append(UsageRecord(attempt_id, self._clock()))
            self._records.sort(key=lambda record: record.attempted_at)
            self._prune(self._clock())
            self._persist()
            snapshot = self._snapshot_under_lock(self._clock())
        if self.hub is not None:
            self.hub.publish_snapshot(snapshot)
        return attempt_id

    def record_usage(self, attempt_id: str | None, input_tokens: int | None) -> None:
        if not attempt_id:
            return
        normalized = input_tokens if isinstance(input_tokens, int) and input_tokens >= 0 else None
        with self._mutex:
            record = next(
                (item for item in self._records if item.attempt_id == attempt_id), None
            )
            if record is None:
                return
            record.input_tokens = normalized
            self._prune(self._clock())
            self._persist()
            snapshot = self._snapshot_under_lock(self._clock())
        if self.hub is not None:
            self.hub.publish_snapshot(snapshot)

    def set_paused(self, paused: bool) -> None:
        with self._mutex:
            self._paused = bool(paused)

    # Snapshot

    def _snapshot_under_lock(self, now: float) -> TrackerSnapshot:
        recent = self._recent(now)
        today = self._today(now)
        next_allowed, reason = self._next_allowed_under_lock(now)
        _, reset = _pacific_day_bounds(now)
        waiting = next_allowed is not None and next_allowed > now
        return TrackerSnapshot(
            provider="gemini",
            active=True,
            window_seconds=self.window_seconds,
            requests_in_minute=len(recent),
            requests_per_minute_limit=self.max_per_minute,
            input_tokens_in_minute=sum(record.input_tokens or 0 for record in recent),
            tokens_per_minute_limit=self.max_input_tokens_per_minute,
            requests_today=len(today),
            requests_per_day_limit=self.max_requests_per_day,
            token_usage_complete=all(record.input_tokens is not None for record in recent),
            minimum_interval_seconds=self.min_interval,
            next_allowed_at=_iso(next_allowed) if next_allowed is not None else None,
            day_resets_at=_iso(reset),
            wait_reason=reason if waiting else None,
            state="paused" if self._paused else ("waiting" if waiting else "ready"),
        )

    def snapshot(self) -> TrackerSnapshot:
        with self._mutex:
            now = self._clock()
            self._prune(now)
            return self._snapshot_under_lock(now)


def inactive_tracker(provider_name: str) -> TrackerSnapshot:
    return TrackerSnapshot(provider=provider_name, active=False, state="ready")


class ScheduledProvider:
    """Lazy ChatProvider wrapper around the process-wide scheduler."""

    # Wraps the real Gemini client, so the pipeline may route each call to
    # any model in its fallback chain.
    supports_model_chain = True

    def __init__(
        self,
        scheduler: GeminiScheduler,
        provider_factory: Callable[[], ChatProvider],
        *,
        provider_tracks_attempts: bool = False,
    ) -> None:
        self._scheduler = scheduler
        self._provider_factory = provider_factory
        self._provider_tracks_attempts = provider_tracks_attempts
        self._provider: ChatProvider | None = None

    def chat(self, *args: object, **kwargs: object) -> object:
        if self._provider is None:
            self._provider = self._provider_factory()
        if self._provider_tracks_attempts:
            return self._provider.chat(*args, **kwargs)
        attempt_id = self._scheduler.wait()
        result = self._provider.chat(*args, **kwargs)
        self._scheduler.record_usage(attempt_id, _input_tokens(result))
        return result


def _input_tokens(result: object) -> int | None:
    if not isinstance(result, dict):
        return None
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return None
    value = usage.get("input_tokens")
    return value if isinstance(value, int) and value >= 0 else None
