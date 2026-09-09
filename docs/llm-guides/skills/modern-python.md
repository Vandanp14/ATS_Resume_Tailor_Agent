<!-- Source: vandan-llm-toolkit skills/modern-python/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Modern Python

A weak model writes Python from a blended 3.6–3.9 mental model: `typing.List`, `os.path.join`, `requirements.txt`, `setup.py`, `unittest.TestCase`, `%` formatting, `@validator`. It fluent-fails — the code runs, but it reads as legacy and drifts from the toolchain actually installed. This skill is a currency-discipline layer, not a tutorial. It replaces training-era habits with the current idiom deterministically, so the output is correct-by-construction regardless of which model runs it. Do not "use your judgment" on style — apply the tables below.


## 1. Version lock first

Resolve the installed Python major **before** applying anything here — features are version-gated. Follow the resolve-first procedure in the **version-grounded-coding** skill (read its SKILL.md); the one-liner is `uv run python -V` (or `python -V`). Record the target and never emit a feature the resolved interpreter cannot run.

As of this writing the current stable series is **Python 3.14** (3.15 in beta/pre-release); resolve the actual installed version at runtime rather than trusting this line. A realistic floor for new projects is **3.11+**; **3.10** is the conservative floor. Feature gates:

| Feature | Minimum |
|---|---|
| Built-in generics `list[int]`, union `str \| None` | 3.10+ (3.9 needs `from __future__ import annotations`) |
| `match`/`case` pattern matching | 3.10+ |
| `asyncio.TaskGroup`, `asyncio.timeout()` | 3.11+ |
| PEP 695 `def f[T]`, `class Box[T]`, `type X = ...` | 3.12+ |
| t-strings `t'...'`, parenless `except A, B`, officially-supported free-threading | 3.14+ |


## 2. Idiom table — stale → current

The core artifact. Left is what a weak model emits from training data; right is what to write. Never ship a left-column form.

| Stale (do not emit) | Current |
|---|---|
| `from typing import List, Dict, Optional, Union` | built-in `list[int]`, `dict[str, int]`, `str \| None`, `A \| B` |
| `TypeVar` / `Generic` / `TypeAlias` boilerplate | PEP 695 `def f[T](...)`, `class Box[T]`, `type V = list[float]` (3.12+) |
| `os.path.join(a, b)`, `os.path.exists(p)`, `open(str)` | `Path(a) / b`, `p.exists()`, `p.read_text()` |
| `"%s" % x`, `"{}".format(x)` | f-string `f"{x}"` (t-string for SQL/HTML/shell escaping, 3.14+) |
| manual index loop appending to a list | comprehension where it reads clearer |
| nested `d.get("a", {}).get("b")` dispatch | `match`/`case` where it earns the space |
| `print()` debugging | `logging` (`logger = logging.getLogger(__name__)`) |
| `requirements.txt` + `pip install` + manual venv | `pyproject.toml` + `uv add` / `uv sync` (uv.lock) |
| `setup.py` / `setup.cfg` | `pyproject.toml` `[project]` + `[build-system]` |
| bare `except:` | `except Exception:` or specific types |
| `unittest.TestCase` in new code | plain pytest functions with `assert` |
| Pydantic v1 `@validator` / `class Config` / `.dict()` / `parse_obj` | v2 `@field_validator` / `model_config = ConfigDict(...)` / `model_dump` / `model_validate` |
| `asyncio.gather(*tasks)` for a task group | `async with asyncio.TaskGroup() as tg:` |
| mutable default arg `def f(x=[])` | `def f(x=None)` then init inside |
| hand-written `__init__` boilerplate | `@dataclass` |


## 3. Failure catalog

Specific defects weak models produce in this ecosystem, each with the fix. Treat every one as a hard ban.

- **Mutable default argument** (`def f(x=[])`, `d={}`) — the default is shared across calls and accumulates state. Use `None` and initialize inside the body.
- **Bare `except:`** — swallows `KeyboardInterrupt` and `SystemExit`, hiding real failures. Catch `except Exception:` or the specific type; never pass silently.
- **`requirements.txt` drift** — unpinned or hand-maintained deps diverge from what is installed. Use `uv add` so `pyproject.toml` + `uv.lock` stay authoritative; commit the lockfile.
- **Star imports** (`from module import *`) — pollute the namespace and defeat the linter and type checker. Import names explicitly.
- **Type comments** (`x = []  # type: list[int]`) — a Python 2 relic. Use annotations: `x: list[int] = []`.
- **`unittest` boilerplate in new code** — `TestCase`, `setUp`, `self.assertEqual`. Write plain functions with `assert` and fixtures.
- **Making everything `async`** — async is contagious and pointless for CPU-bound work. Reserve it for high-concurrency I/O; see the reference for the when-NOT rule.
- **Pydantic left unconstrained** — models silently accept unknown keys and coerce loosely. Set `ConfigDict(extra="forbid", strict=True)` at trust boundaries.


## 4. Config and commands

The full canonical `pyproject.toml` (uv build backend, ruff, pytest) and src layout live in **references/setup-and-typing.md** — copy it verbatim. The uv-era command set:

| Task | Command |
|---|---|
| Scaffold a project | `uv init my-project` |
| Add a dependency (+lock) | `uv add httpx` |
| Add dev dependencies | `uv add --dev pytest ruff ty` |
| Run in the managed env | `uv run pytest` |
| Materialize env from lock | `uv sync` |
| Refresh the lockfile | `uv lock --upgrade` |
| Lint + format | `ruff check --fix . && ruff format .` |
| Type-check | `uvx mypy .` (stable) or `uvx ty check` (fast, beta) |


## 5. Which reference to read

Read the row you are on, just-in-time — not both upfront.

| You are… | Read |
|---|---|
| Setting up a project, writing type hints, or choosing dataclass vs TypedDict vs Pydantic | [references/setup-and-typing.md](references/setup-and-typing.md) |
| Writing idiomatic code, async, or tests | [references/idioms-and-testing.md](references/idioms-and-testing.md) |


## 6. Closing gate

Do not report Python work done until every box holds:

- [ ] Installed major resolved; no feature used beyond the target version.
- [ ] No `typing.List/Dict/Optional/Union` — built-in generics and `|` unions only.
- [ ] No `os.path` — `pathlib`. No `%`/`.format` — f-strings.
- [ ] New project uses `pyproject.toml` + `uv.lock`; no `requirements.txt` or `setup.py`.
- [ ] No bare `except`, no mutable default args, no star imports, no type comments.
- [ ] Untrusted boundary data validated with Pydantic v2; trusted internal state uses `dataclass`/`TypedDict` per the decision table.
- [ ] Tests are pytest functions; `ruff check` and `ruff format` clean; type checker clean.

Boundary validation here is a currency convention, not the security gate — for input-validation *security* (injection, mass assignment, SSRF) apply **secure-by-default**.
