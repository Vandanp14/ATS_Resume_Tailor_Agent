"""Command-line parsing and output configuration."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .batch import run_batch, run_single
from .config import DEFAULT_MODEL, ProviderMode
from .progress import build_progress_reporter
from .runtime import DEFAULT_CALL_INTERVAL


def _common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--provider",
        choices=[mode.value.replace("_", "-") for mode in ProviderMode],
        default=None,
        help=(
            "provider chain: gemini (the .env chain), freellm (local FreeLLMAPI "
            "proxy only), freellm-gemini (proxy first, Gemini fallback), or "
            "gemini-freellm (Gemini first, proxy fallback); overrides --model"
        ),
    )
    parser.add_argument(
        "--freellm-model",
        default=None,
        help="FreeLLMAPI model id for --provider freellm* (default FREELLMAPI_MODEL or auto)",
    )
    parser.add_argument("--call-interval", type=float, default=DEFAULT_CALL_INTERVAL)
    parser.add_argument("--no-pdf", action="store_true")
    parser.add_argument(
        "--bridge-skills",
        action="store_true",
        help="add up to four JD-grounded skills in a labeled transferable group",
    )
    parser.add_argument(
        "--college",
        action="store_true",
        help=(
            "college/university staff posting: target each minimum and preferred "
            "qualification line, allow two pages, and add a summary"
        ),
    )
    parser.add_argument(
        "--research-company",
        action="store_true",
        help=(
            "when the parsed JD has thin signal, research the company's tech "
            "stack and hiring signals via grounded Gemini web search to guide "
            "selection and tone (Gemini only; no effect on an already-detailed JD)"
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "reuse the stages a failed run already finished in the same output "
            "directory instead of starting over"
        ),
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "--verbose",
        action="store_true",
        help="show retries, pacing waits, fit iterations, and model details",
    )
    verbosity.add_argument(
        "--quiet",
        action="store_true",
        help="show only failures and the final aggregate result",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the legacy single-JD parser (kept as a public CLI seam)."""
    parser = argparse.ArgumentParser(
        description="Build a job-specific one-page resume from a JSON Resume master."
    )
    parser.add_argument("master", nargs="?", type=Path)
    parser.add_argument("jd", nargs="?", type=Path)
    parser.add_argument("-o", "--out-dir", type=Path)
    _common_flags(parser)
    return parser


def build_batch_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tailor.py batch", description="Tailor every JD text file in a directory."
    )
    parser.add_argument("--master", type=Path, default=Path("master.json"))
    parser.add_argument("--jd-dir", type=Path, default=Path("jds"))
    parser.add_argument("--out-dir", type=Path, default=Path("output"))
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    parser.add_argument("--force", action="store_true")
    _common_flags(parser)
    return parser


def configure_logging(verbose: bool = False) -> None:
    """Keep third-party INFO chatter out of application-owned progress output."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    for logger_name in ("httpx", "httpcore", "google_genai"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and raw_args[0] == "batch":
        args = build_batch_parser().parse_args(raw_args[1:])
        batch_mode = True
    else:
        args = build_parser().parse_args(raw_args)
        batch_mode = False
        if args.master is None or args.jd is None or args.out_dir is None:
            build_parser().error("single mode requires MASTER JD -o OUT_DIR")

    configure_logging(args.verbose)
    reporter = build_progress_reporter(verbose=args.verbose, quiet=args.quiet)
    try:
        return run_batch(args, reporter) if batch_mode else run_single(args, reporter)
    finally:
        reporter.close()
