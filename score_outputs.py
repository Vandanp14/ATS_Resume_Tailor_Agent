#!/usr/bin/env python
"""Batch re-score every generated tailored resume against the hiring-agent rubric.

This is a standalone companion to ``tailor.py``: instead of tailoring, it walks an
``--output-dir`` tree, finds every subdirectory that contains a ``tailored.json``,
converts each back into resume text, and runs the *sibling* hiring-agent's
``ResumeEvaluator`` over it — printing per-category scores, a total, and a final
ranking so you can compare runs at a glance.

    python score_outputs.py [--output-dir output/] \
        [--hiring-agent-path ~/Desktop/hackerank_ats/hiring-agent] [--jd-dir jds/]

Cross-repo mechanics (identical to ``tailor.py --ats-score`` — see its
``_run_ats_score``):

* The hiring-agent ships its own ``models`` / ``llm_utils`` / ``prompt`` /
  ``prompts`` modules that collide with ours in ``sys.modules``, and its
  ``TemplateManager`` loads templates *relative to the CWD*. So we resolve paths
  first, snapshot and evict the conflicting modules, ``chdir`` into the checkout,
  import fresh, and restore everything in a ``finally`` — set up ONCE for the whole
  batch (one evaluator, one chdir) rather than per resume.
* Evaluation uses the hiring-agent's own ``.env`` / ``GEMINI_API_KEY``. Every
  evaluation is a live LLM call, so a :class:`RatePacer` enforces the same free-tier
  minimum interval (default 4.5 s) between resumes that ``tailor.py`` uses.
* ``google.api_core.exceptions.ResourceExhausted`` (true quota exhaustion) aborts
  the batch: we print which resumes scored and which remain, and exit ``75``
  (``EX_TEMPFAIL`` — "transient; wait and re-run").

The pacer, conflicting-module predicate, and constants are imported from ``tailor.py``
when it imports cleanly; if it does not (e.g. it is mid-edit), minimal inline
replicas are used so ``--help`` and scoring still work.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Reuse tailor.py's proven helpers when importable; otherwise replicate them.
# tailor.py has no LLM side effects at import time (it only loads models/prompt/
# llm_utils, which just read the .env defaults), so importing it here is cheap and
# keeps --help LLM-free. The guard tolerates tailor.py being momentarily unwritable
# while a concurrent editor touches it.
# ---------------------------------------------------------------------------

try:  # pragma: no cover - import shape only
    from tailor import (  # type: ignore
        RatePacer,
        _is_conflicting_module,
        DEFAULT_CALL_INTERVAL,
        DEFAULT_HIRING_AGENT_PATH,
        QUOTA_EXIT_CODE,
        ResourceExhausted,
    )
except Exception:  # pragma: no cover - defensive fallback
    DEFAULT_CALL_INTERVAL = 4.5
    DEFAULT_HIRING_AGENT_PATH = "~/Desktop/hackerank_ats/hiring-agent"
    QUOTA_EXIT_CODE = 75  # EX_TEMPFAIL

    try:
        from google.api_core.exceptions import ResourceExhausted  # type: ignore
    except Exception:

        class ResourceExhausted(Exception):  # type: ignore[no-redef]
            """Fallback stand-in when google-api-core is not importable."""

    class RatePacer:  # type: ignore[no-redef]
        """Minimum-interval throttle applied immediately before every LLM call.

        Mirrors ``tailor.RatePacer``: consecutive calls are at least
        ``min_interval`` seconds apart; ``min_interval <= 0`` disables throttling.
        """

        def __init__(self, min_interval: float):
            self.min_interval = float(min_interval)
            self._next_allowed: Optional[float] = None

        def wait(self) -> None:
            if self.min_interval <= 0:
                return
            now = time.monotonic()
            if self._next_allowed is not None and now < self._next_allowed:
                time.sleep(self._next_allowed - now)
            self._next_allowed = time.monotonic() + self.min_interval

    def _is_conflicting_module(name: str) -> bool:  # type: ignore[no-redef]
        """Module names this repo and the hiring-agent BOTH define (different code)."""
        return name in ("models", "llm_utils", "prompt", "prompts") or name.startswith(
            "prompts."
        )


DEFAULT_OUTPUT_DIR = "output"
DEFAULT_JD_DIR = "jds"

# Categories reported by the hiring-agent evaluator, in display order. Each maps to
# a CategoryScore with ``.score`` and ``.max`` on ``result.scores``.
_CATEGORIES: Tuple[Tuple[str, str, int], ...] = (
    ("open_source", "OpenSrc", 8),
    ("self_projects", "SelfProj", 9),
    ("production", "Prod", 7),
    ("technical_skills", "TechSkl", 8),
)


# ---------------------------------------------------------------------------
# Scoring result container
# ---------------------------------------------------------------------------


class _Scored:
    """Flattened per-resume score, decoupled from the hiring-agent's model objects.

    We extract plain floats *inside* the cross-repo context and hold only those, so
    nothing here keeps a reference to the hiring-agent's pydantic classes after the
    module swap is torn down.
    """

    __slots__ = ("name", "categories", "bonus", "deductions", "total")

    def __init__(self, name: str, result: Any):
        scores = result.scores
        self.name = name
        self.categories: Dict[str, float] = {}
        subtotal = 0.0
        for attr, _label, _default_max in _CATEGORIES:
            cat = getattr(scores, attr)
            self.categories[attr] = float(cat.score)
            subtotal += float(cat.score)
        self.bonus = float(result.bonus_points.total)
        self.deductions = float(result.deductions.total)
        self.total = subtotal + self.bonus - self.deductions


# ---------------------------------------------------------------------------
# Output-dir discovery
# ---------------------------------------------------------------------------


def _find_tailored(output_dir: Path) -> List[Tuple[str, Path]]:
    """Return sorted ``(name, tailored.json path)`` for subdirs that have one.

    Subdirectories lacking ``tailored.json`` are skipped with a one-line warning.
    """
    found: List[Tuple[str, Path]] = []
    for sub in sorted(p for p in output_dir.iterdir() if p.is_dir()):
        tailored = sub / "tailored.json"
        if tailored.is_file():
            found.append((sub.name, tailored))
        else:
            print(
                f"[skip] {sub.name}: no tailored.json — skipping.", file=sys.stderr
            )
    return found


# ---------------------------------------------------------------------------
# Table / ranking output
# ---------------------------------------------------------------------------


def _print_table(scored: List[_Scored]) -> None:
    if not scored:
        return
    name_w = max(6, min(28, max(len(s.name) for s in scored)))
    header = (
        f"{'Resume':<{name_w}} "
        f"{'OpenSrc':>8} {'SelfProj':>9} {'Prod':>7} {'TechSkl':>8} "
        f"{'Bonus':>7} {'Deduct':>7} {'TOTAL':>8}"
    )
    print("\n=== Re-scored resumes (hiring-agent rubric) ===")
    print(header)
    print("-" * len(header))
    for s in scored:
        name = s.name if len(s.name) <= name_w else s.name[: name_w - 1] + "…"
        print(
            f"{name:<{name_w}} "
            f"{s.categories['open_source']:>8.1f} "
            f"{s.categories['self_projects']:>9.1f} "
            f"{s.categories['production']:>7.1f} "
            f"{s.categories['technical_skills']:>8.1f} "
            f"{s.bonus:>7.1f} "
            f"{-s.deductions:>7.1f} "
            f"{s.total:>8.1f}"
        )


def _print_ranking(scored: List[_Scored]) -> None:
    if not scored:
        return
    ranked = sorted(scored, key=lambda s: s.total, reverse=True)
    print("\n=== Ranking (best total first) ===")
    width = max(len(s.name) for s in ranked)
    for i, s in enumerate(ranked, start=1):
        print(f"  {i:>2}. {s.name:<{width}}  TOTAL = {s.total:>6.1f}")


# ---------------------------------------------------------------------------
# Batch scoring inside the cross-repo context
# ---------------------------------------------------------------------------


def _score_all(
    resumes: List[Tuple[str, Path]],
    ha_dir: Path,
    pacer: RatePacer,
) -> Tuple[List[_Scored], List[str], List[str], bool]:
    """Score every resume against the hiring-agent evaluator.

    Sets up the module-swap / chdir context ONCE (one evaluator for the whole
    batch), mirroring ``tailor._run_ats_score``. Returns
    ``(scored, failed, remaining, quota_hit)`` where ``remaining`` is populated only
    when ``quota_hit`` is True (the resumes that never got scored).
    """
    scored: List[_Scored] = []
    failed: List[str] = []
    remaining: List[str] = []
    quota_hit = False

    original_cwd = os.getcwd()
    original_path = list(sys.path)
    saved_modules = {
        name: mod
        for name, mod in list(sys.modules.items())
        if _is_conflicting_module(name)
    }
    try:
        for name in saved_modules:
            del sys.modules[name]
        sys.path.insert(0, str(ha_dir))
        os.chdir(ha_dir)

        import importlib

        ha_models = importlib.import_module("models")
        ha_transform = importlib.import_module("transform")
        ha_evaluator = importlib.import_module("evaluator")

        evaluator = ha_evaluator.ResumeEvaluator()

        total = len(resumes)
        for index, (name, path) in enumerate(resumes):
            try:
                resume_dict = json.loads(path.read_text(encoding="utf-8"))
                ha_resume = ha_models.JSONResume(**resume_dict)
                resume_text = ha_transform.convert_json_resume_to_text(ha_resume)
            except Exception as exc:  # malformed tailored.json — skip, keep going
                print(
                    f"[{index + 1}/{total}] {name}: could not load/convert "
                    f"({exc}); skipping.",
                    file=sys.stderr,
                )
                failed.append(name)
                continue

            pacer.wait()
            try:
                result = evaluator.evaluate_resume(resume_text)
            except ResourceExhausted:
                # True quota exhaustion: stop now, report what's left.
                quota_hit = True
                remaining = [n for n, _ in resumes[index:]]
                break
            except Exception as exc:  # transient/parse error on one resume
                print(
                    f"[{index + 1}/{total}] {name}: evaluation failed ({exc}); "
                    "skipping.",
                    file=sys.stderr,
                )
                failed.append(name)
                continue

            s = _Scored(name, result)
            scored.append(s)
            print(f"[{index + 1}/{total}] {name}: TOTAL = {s.total:.1f}")
    finally:
        os.chdir(original_cwd)
        sys.path[:] = original_path
        for extra in [
            n
            for n in list(sys.modules)
            if _is_conflicting_module(n) and n not in saved_modules
        ]:
            del sys.modules[extra]
        sys.modules.update(saved_modules)

    return scored, failed, remaining, quota_hit


def _print_quota_exhausted(scored: List[_Scored], remaining: List[str]) -> None:
    done = [s.name for s in scored]
    print("\n=== Gemini quota exhausted ===", file=sys.stderr)
    print(
        f"Scored ({len(done)}): {', '.join(done) or '(none)'}", file=sys.stderr
    )
    print(
        f"Remaining ({len(remaining)}): {', '.join(remaining) or '(none)'}",
        file=sys.stderr,
    )
    print(
        "Gemini quota exhausted — wait and re-run the same command to score the "
        "remaining resumes.",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="score_outputs.py",
        description=(
            "Re-score every generated tailored resume (output/*/tailored.json) "
            "against the sibling hiring-agent evaluator and print a ranking."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        dest="output_dir",
        help="Directory whose subfolders hold tailored.json (default: %(default)s)",
    )
    parser.add_argument(
        "--hiring-agent-path",
        default=DEFAULT_HIRING_AGENT_PATH,
        dest="hiring_agent_path",
        help="hiring-agent checkout providing the evaluator (default: %(default)s)",
    )
    parser.add_argument(
        "--jd-dir",
        default=DEFAULT_JD_DIR,
        dest="jd_dir",
        help="Job-description folder (informational; used to note missing JDs) "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--call-interval",
        type=float,
        default=DEFAULT_CALL_INTERVAL,
        dest="call_interval",
        help="Free-tier pacer: minimum seconds between evaluations; 0 disables "
        "(default: %(default)s)",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_dir():
        print(f"error: output directory not found: {output_dir}", file=sys.stderr)
        return 2

    ha_dir = Path(args.hiring_agent_path).expanduser().resolve()
    if not (ha_dir / "evaluator.py").is_file():
        print(
            f"error: hiring-agent evaluator not found at {ha_dir}.\n"
            "  Point --hiring-agent-path at your hiring-agent checkout.",
            file=sys.stderr,
        )
        return 2

    jd_dir = Path(args.jd_dir).expanduser()
    if not jd_dir.is_dir():
        print(
            f"[note] JD directory {jd_dir} not found; scoring proceeds without it.",
            file=sys.stderr,
        )

    resumes = _find_tailored(output_dir)
    if not resumes:
        print(
            f"No tailored.json files found under {output_dir}. Nothing to score."
        )
        return 0

    print(
        f"Scoring {len(resumes)} resume(s) from {output_dir} against {ha_dir} "
        f"(pacer: {args.call_interval:g}s) ..."
    )
    pacer = RatePacer(args.call_interval)
    scored, failed, remaining, quota_hit = _score_all(resumes, ha_dir, pacer)

    _print_table(scored)
    _print_ranking(scored)
    if failed:
        print(f"\n[warn] {len(failed)} resume(s) could not be scored: {failed}")

    if quota_hit:
        _print_quota_exhausted(scored, remaining)
        return QUOTA_EXIT_CODE

    print(f"\nDone: scored {len(scored)} resume(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
