"""Shared execution policy for schema-validated model stages."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from pydantic import BaseModel

from .evidence import ContractError
from .llm import LLMExtractionError
from .progress import ProgressTracker, Stage
from .runtime import StageFailure


class StageExecutor:
    """Apply the pipeline's bounded correction policy to a typed stage call."""

    def __init__(self, tracker: ProgressTracker) -> None:
        self.tracker = tracker

    def run[ResultT: BaseModel](
        self,
        *,
        name: str,
        stage: Stage,
        operation: Callable[[int, Exception | None], ResultT],
        selected_ids: Sequence[str] = (),
        validator: Callable[[ResultT], None] | None = None,
        max_attempts: int = 2,
    ) -> ResultT:
        last: object = None
        last_error: Exception = ValueError("no response")
        for attempt in range(1, max_attempts + 1):
            try:
                result = operation(attempt, last_error if attempt > 1 else None)
                last = result
                if validator:
                    validator(result)
                return result
            except (LLMExtractionError, ContractError) as exc:
                last = exc.raw_response if isinstance(exc, LLMExtractionError) else last
                last_error = exc
                if attempt < max_attempts:
                    self.tracker.retry(
                        stage,
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                        message=str(exc),
                    )
        raise StageFailure(name, max_attempts, selected_ids, last, last_error)
