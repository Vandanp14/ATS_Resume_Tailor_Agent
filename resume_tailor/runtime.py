"""Runtime errors, request pacing, and artifact helpers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel

from llm_utils import ChatProvider
from models import JSONResume

from .progress import ProgressTracker


DEFAULT_CALL_INTERVAL = 4.5
QUOTA_EXIT_CODE = 75
MAX_SELECTED_WORK = 3
MAX_SELECTED_PROJECTS = 2
PROJECT_REWRITE_BATCH_SIZE = 5
FINAL_ARTIFACTS = (
    ".fit_recovery.json",
    ".bullet_review.json",
    ".done",
    "tailored.json",
    "match_report.json",
    "diagnostic_report.json",
    "resume.tex",
    "resume.pdf",
)


class StageFailure(RuntimeError):
    def __init__(
        self,
        stage: str,
        attempts: int,
        selected_ids: Sequence[str],
        parsed_response: object,
        error: Exception | str,
    ) -> None:
        self.stage = stage
        self.attempts = attempts
        self.selected_ids = list(selected_ids)
        self.parsed_response = parsed_response
        self.schema_error = str(error)
        super().__init__(f"{stage} failed after {attempts} attempt(s): {error}")

    def diagnostic(self) -> dict[str, object]:
        parsed = self.parsed_response
        if isinstance(parsed, BaseModel):
            parsed = parsed.model_dump(mode="json")
        return {
            "stage": self.stage,
            "attempts": self.attempts,
            "selected_ids": self.selected_ids,
            "parsed_response": parsed,
            "schema_error": self.schema_error,
        }


class ModelUnavailableError(StageFailure):
    """Every model in a stage's chain failed at the API; the run is cancelled.

    ``failures`` holds (model, API error text) in the order tried, so the user
    sees exactly what Gemini returned instead of a generic failure.
    """

    def __init__(self, stage: str, failures: Sequence[tuple[str, str]]) -> None:
        self.failures = list(failures)
        summary = "; ".join(f"{model} -> {error}" for model, error in self.failures)
        super().__init__(
            stage,
            len(self.failures),
            [],
            None,
            "Gemini API unavailable for every configured model; tailoring "
            f"stopped. {summary}",
        )

    @property
    def quota_exhausted(self) -> bool:
        return bool(self.failures) and all(
            "429" in error or "resource_exhausted" in error.lower()
            for _, error in self.failures
        )

    def diagnostic(self) -> dict[str, object]:
        payload = super().diagnostic()
        payload["model_failures"] = [
            {"model": model, "error": error} for model, error in self.failures
        ]
        return payload


class RatePacer:
    def __init__(
        self, min_interval: float, tracker: ProgressTracker | None = None
    ) -> None:
        self.min_interval = max(float(min_interval), 0.0)
        self._next_allowed: float | None = None
        self._tracker = tracker

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        if self._next_allowed is not None and now < self._next_allowed:
            delay = self._next_allowed - now
            if self._tracker:
                self._tracker.detail(f"Rate-limit pacing: waiting {delay:.1f}s")
            time.sleep(delay)
        self._next_allowed = time.monotonic() + self.min_interval


class PacedProvider:
    def __init__(self, provider: ChatProvider, pacer: RatePacer) -> None:
        self._provider = provider
        self._pacer = pacer

    def chat(self, *args: Any, **kwargs: Any) -> Any:
        self._pacer.wait()
        return self._provider.chat(*args, **kwargs)


def clear_artifacts(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in FINAL_ARTIFACTS:
        path = out_dir / name
        if path.is_file() or path.is_symlink():
            path.unlink()


def write_json(path: Path, payload: object) -> None:
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json", exclude_unset=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_master(path: Path) -> JSONResume:
    return JSONResume.model_validate_json(path.read_text(encoding="utf-8"))


def done_satisfies(out_dir: Path, no_pdf: bool) -> bool:
    marker = out_dir / ".done"
    if not marker.is_file() or not (out_dir / "tailored.json").is_file():
        return False
    try:
        state = json.loads(marker.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(state, dict):
        return False
    if no_pdf:
        return True
    return bool(state.get("pdf")) and (out_dir / "resume.pdf").is_file()
