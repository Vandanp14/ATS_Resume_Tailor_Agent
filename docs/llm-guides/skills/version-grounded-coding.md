<!-- Source: vandan-llm-toolkit skills/version-grounded-coding/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Version-Grounded Coding

Library APIs move faster than any model's training data. A method that existed when a model was trained may be renamed, removed, or resignatured in the version actually installed. Writing a call from memory produces code that looks fluent and fails at runtime — or worse, type-checks against a mental model of a version nobody is running. Frontier-quality output does not come from recalling more APIs; it comes from a deterministic pre-write phase that resolves the installed version and reads *that version's* authoritative surface before a single line of dependent code is written.

This discipline is mechanical, not clever. It works regardless of which LLM runs it because it replaces recall with lookup. The rule is absolute: **never write library code from training memory when the installed version's docs, types, or source are on disk.** Read first. Cite what you read. Then write.


## Operating procedure

Execute these four steps in order, before writing any code that touches a dependency. Do not skip a step because the API "looks familiar" — familiarity is exactly the failure mode.

1. **Resolve the exact installed version.** Read the lockfile (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `poetry.lock`, `Cargo.lock`, `go.sum`) as the source of truth, not the manifest range. Cross-check with the manifest (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`) and, when in doubt, the installed artifact itself (`npx <tool> --version`, `pip show <pkg>`, `<bin> --version`). A caret range like `^3.1.0` is not a version — resolve it to the concrete `3.4.2` on disk.

2. **Record the version-lock header at task start.** Before writing code, emit the header (format below) naming every dependency you will touch, its resolved version, and the doc source you will consult. This is a commitment device: it forces the resolution to happen up front and makes a wrong-major error visible immediately.

3. **Locate the authoritative doc for THAT version, in priority order.** Prefer sources closest to the installed bits. Vendored/bundled docs and type definitions beat everything because they are the version on disk (see [references/lookup-recipes.md](references/lookup-recipes.md) for per-ecosystem paths). Never treat a blog or a top web result as authoritative — check which version it targets first, and use it only as a last resort.

4. **Verify each API against that doc or the package's own types/source before calling it.** For every non-trivial import, method, option object, or CLI flag: confirm it exists, confirm its signature, and confirm it is not deprecated in the installed version. Read deprecation and breaking-change notices for the span between your training-era assumption and the installed release — and heed them, using the replacement the notice names.


## Doc source priority

Consult sources in this order. Stop at the highest tier that answers the question; only descend when a tier is genuinely unavailable.

| Tier | Source | Why it ranks here |
|---|---|---|
| 1 | **Vendored docs + type definitions on disk** (`node_modules/<pkg>/dist/docs`, `.d.ts` files, `site-packages/<pkg>`, source) | It *is* the installed version. Cannot be wrong about what shipped. |
| 2 | **Official docs pinned to the resolved version** (versioned URL, `docs.rs/<crate>/<version>`, `pkg.go.dev/<mod>@<version>`) | Authoritative and version-addressable — always pin the version in the URL. |
| 3 | **Changelog + migration guide** for the span between training-era and installed version | Names exactly what was renamed, removed, or deprecated. |
| 4 | **Secondary sources** (blogs, Q&A, tutorials) | Undated, version-ambiguous. Use only when 1–3 fail, and only after confirming the version it targets. |

**Conflict rule:** local installed docs and types (Tier 1) beat any web source, always. If a blog and the installed `.d.ts` disagree, the `.d.ts` wins and the blog is discarded — do not average them.


## Hard bans

- **Never cite or write an API from memory for a fast-moving library when local docs or types exist.** Read the vendored source or `.d.ts` first. Memory is a hypothesis, not a citation.
- **Never mix doc versions in one file.** All APIs in a change must target the single resolved version. No mixing v3 examples with v6 imports, pages-router patterns with app-router files, or React 18 idioms in a React 19 project.
- **Never write dependent code before the version-lock header exists.** No header, no code.
- **Never treat a web result as authoritative without confirming the version it targets.** An undated blog is Tier 4, never Tier 1.
- **Never ignore a deprecation notice present in the installed package.** If the installed version deprecates it, use the named replacement — shipping deprecated calls is a defect.
- **Never trust the manifest range as the version.** `^`, `~`, `>=`, and `*` are ranges; resolve to the concrete version in the lockfile.


## Worked example: Next.js in this repo

This repo's AGENTS.md states: *"This is NOT the Next.js you know … Read the relevant guide in `node_modules/next/dist/docs/` before writing any code."* This is the discipline made mandatory. Before touching routing, data fetching, or config:

1. Resolve: read `package-lock.json` for the exact `next` version — not the `package.json` range.
2. Read `node_modules/next/dist/docs/` for that version's routing and data-fetching guide, and heed any deprecation notices there.
3. Verify the app-router conventions against those vendored docs — do **not** write `pages/`-directory conventions, old data-fetching APIs, or deprecated config keys from training memory.
4. Only then write `app/` code, each API grounded in the doc you just read.

A model that "recalls" Next.js routing here writes for a version that no longer exists. A model that reads `node_modules/next/dist/docs/` first writes for the version actually installed. The second is correct by construction.


## Output contract: version-lock header

Emit this at task start, before any dependent code. One row per dependency you will touch.

```
VERSION LOCK (resolved <UTC date>)
- <package>@<exact-installed-version>  (source: <lockfile path>)
  docs: <tier-1 path or version-pinned URL>
  notes: <deprecations/breaking changes between training-era and installed, or "none found">
```

Example:

```
VERSION LOCK (resolved 2026-07-13)
- next@15.3.1  (source: package-lock.json)
  docs: node_modules/next/dist/docs/app/  (Tier 1, on disk)
  notes: app-router only; pages-router data-fetching APIs removed; heed dynamic-route deprecation
- react@19.1.0  (source: package-lock.json)
  docs: node_modules/react/index.d.ts  (Tier 1)
  notes: verify hook signatures against 19 .d.ts, not 18 memory
```

Read [references/lookup-recipes.md](references/lookup-recipes.md) just-in-time when you need the exact command or path to resolve a version or find vendored docs for a specific ecosystem (Node, Python, Rust, Go, or a generic CLI).
