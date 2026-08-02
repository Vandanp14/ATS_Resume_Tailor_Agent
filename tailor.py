#!/usr/bin/env python
"""Compatibility entrypoint for the packaged resume tailoring application."""

from resume_tailor.batch import (
    ResourceExhausted,
    is_quota_error as _is_quota_error,
    pipeline_from_args as _pipeline_from_args,
    run_batch,
    run_single,
)
from resume_tailor.cli import (
    build_batch_parser as _build_batch_parser,
    build_parser,
    main,
)
from resume_tailor.pipeline import TailorPipeline
from resume_tailor.rendering import (
    ensure_tectonic as _ensure_tectonic,
    fit_to_one_page as _fit_to_one_page,
    render as _render_resume,
)
from resume_tailor.runtime import (
    DEFAULT_CALL_INTERVAL,
    FINAL_ARTIFACTS,
    MAX_SELECTED_PROJECTS,
    MAX_SELECTED_WORK,
    PROJECT_REWRITE_BATCH_SIZE,
    QUOTA_EXIT_CODE,
    PacedProvider as _PacedProvider,
    RatePacer,
    StageFailure,
    clear_artifacts as _clear_artifacts,
    done_satisfies as _done_satisfies,
    load_master as _load_master,
    write_json as _write_json,
)

__all__ = [
    "DEFAULT_CALL_INTERVAL",
    "FINAL_ARTIFACTS",
    "MAX_SELECTED_PROJECTS",
    "MAX_SELECTED_WORK",
    "PROJECT_REWRITE_BATCH_SIZE",
    "QUOTA_EXIT_CODE",
    "RatePacer",
    "ResourceExhausted",
    "StageFailure",
    "TailorPipeline",
    "build_parser",
    "main",
    "run_batch",
    "run_single",
]


if __name__ == "__main__":
    raise SystemExit(main())
