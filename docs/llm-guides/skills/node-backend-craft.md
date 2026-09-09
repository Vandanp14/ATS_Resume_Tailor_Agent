<!-- Source: vandan-llm-toolkit skills/node-backend-craft/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Node Backend Craft

Node moves faster than any model's training data, and the median Node code in that corpus is years stale: CommonJS `require`, error-first callbacks, `axios` for a GET, `dotenv` + `nodemon` + `ts-node` for a dev loop, Jest for three assertions. A weak model reproduces that median fluently, shipping a backend the current LTS runtime does natively minus the dependencies. Frontier-quality Node is not cleverer code; it is refusing to emit the stale idiom when the runtime already owns the job.

This is a current-idiom discipline, not a tutorial: it assumes you can write a route and corrects *which* idiom you reach for. The core artifact is the [idiom table](#idiom-table) — stale-way → current-way, each row copy-paste ready. Apply it while you write, not in a cleanup pass.

**Cross-references — read the named skill's SKILL.md before writing that layer:** security middleware, input validation, CORS, and secrets live in `secure-by-default`. Outbound-call reliability (timeouts, retries, idempotency) and the RFC 9457 error envelope live in `integration-glue`. This skill owns runtime discipline, project setup, framework choice, and process lifecycle.


## Step 1 — Version lock first

Before applying any row below, resolve the installed Node major and framework versions — built-ins and stable features differ sharply across lines. **Run the `version-grounded-coding` skill for the resolution procedure and version-lock header.** One-line orientation for mid-2026:

| Line | Status | Use it when |
|---|---|---|
| v24 (Krypton) | Active LTS | Default production target for new services |
| v22 (Jod) | Maintenance LTS | Conservative / legacy continuity |
| v26 | Current | Early adoption only (LTS Oct 2026) |

Pin new work to the LTS (`.nvmrc` + `engines`, per the canonical config below). If a feature below is unavailable, you are on an older line — do not polyfill with a dependency the newer LTS makes native; upgrade the runtime.


## Idiom table

The core artifact. Left is what a weak model emits from training memory; right is the current idiom on Active LTS. Replace on sight.

| Stale way | Current way |
|---|---|
| `const fs = require('fs')` / `module.exports` | `import fs from 'node:fs/promises'` / `export` |
| `__dirname`, `__filename` | `import.meta.dirname`, `import.meta.filename` |
| `import { readFile } from 'fs'` | `import { readFile } from 'node:fs/promises'` (always `node:` prefix) |
| error-first callback / `util.promisify(fn)` | `await` a `node:fs/promises` / `node:timers/promises` API |
| `new Promise(r => setTimeout(r, ms))` | `import { setTimeout } from 'node:timers/promises'; await setTimeout(ms)` |
| `axios` / `node-fetch` / `got` for HTTP | global `fetch` (undici, built in) |
| `require('ws')` for a WebSocket **client** | global `new WebSocket(url)` (server still needs `ws`) |
| `require('dotenv').config()` | `node --env-file=.env app.js` |
| `nodemon app.js` | `node --watch app.js` |
| `ts-node` / `tsx` for plain TS | `node app.ts` (native type stripping) |
| `jest` / `mocha` for a small suite | `node:test` + `node --test` |
| manual `.pipe()` chains | `await pipeline(src, xform, dst)` from `node:stream/promises` |
| `stream.on('data'|'end', …)` | `for await (const chunk of stream)` |
| hand-rolled `AbortController` + timer | `fetch(url, { signal: AbortSignal.timeout(5000) })` |
| Express 4 as the default new API | Fastify for a new Node API (see [decision table](references/server-patterns.md)) |

Built-ins to reach for before adding a dependency, the runtime-lifecycle recipe, and the framework decision table live in [references/runtime-and-setup.md](references/runtime-and-setup.md) and [references/server-patterns.md](references/server-patterns.md) — read them just-in-time.


## Failure catalog

The specific things weak models get wrong in this ecosystem. Each has one fix.

- **Error-first callbacks where a promise API exists.** Any callback + `util.promisify` is a smell. Fix: `node:fs/promises`, `node:timers/promises`, `async/await` end to end.
- **Synchronous fs/crypto in a request handler.** `readFileSync`, `existsSync`, sync hashing block the event loop and stall every concurrent request. Fix: the `await`ed promises variant; sync APIs only at startup.
- **Floating promises.** An `async` call whose result is never `await`ed or `.catch`ed — the rejection escapes and crashes the process. Fix: `await` it, or attach a handler; enable `no-floating-promises` in the linter.
- **Express-4 async error handling.** In Express 4, a throw inside an `async` route does *not* reach the error middleware — it becomes an unhandled rejection. Fix: run Express **5** (async errors propagate to `next` automatically) or wrap every async handler.
- **God middleware.** One `app.use` that authenticates, validates, logs, and mutates the body. Fix: one concern per middleware, ordered.
- **Assuming unhandled rejections only warn.** Since Node 15 the default is `--unhandled-rejections=throw`: an unhandled rejection **crashes** the process. Fix: never swallow; let it crash and restart under a supervisor, using the handler only to log + shut down.
- **Type-stripping the un-strippable.** `enum`, `namespace` with runtime code, parameter properties, and legacy decorators are NOT erasable, and the `--experimental-transform-types` flag was removed in v24.12/v25.2 (and stays gone in v26). Fix: avoid them, or add a real build step (`tsc`/`esbuild`/`swc`/`tsx`) — not a Node flag.
- **CJS `require()` of an ESM module with top-level await.** `require(esm)` is stable now, but a module using top-level `await` throws `ERR_REQUIRE_ASYNC_MODULE`. Fix: `await import()` it, or remove the top-level await.


## Canonical config

Copy this ESM-first, native-TypeScript project verbatim; do not substitute values from memory. Fuller `package.json` and rationale in [the reference](references/runtime-and-setup.md).

```jsonc
// package.json (essentials)
{
  "type": "module",
  "engines": { "node": ">=24" },
  "scripts": {
    "dev":   "node --watch --env-file=.env src/server.ts",
    "start": "node --env-file-if-exists=.env src/server.ts",
    "test":  "node --test",
    "test:cov": "node --test --experimental-test-coverage"
  }
}
```

```jsonc
// tsconfig.json — TypeScript 5.8+, Node type stripping (no emit)
{
  "compilerOptions": {
    "noEmit": true,
    "target": "esnext",
    "module": "nodenext",
    "rewriteRelativeImportExtensions": true,
    "erasableSyntaxOnly": true,
    "verbatimModuleSyntax": true
  }
}
```

```
// .nvmrc          // imports must mark type-only specifiers:
24                 import type { User } from './user.ts';
                   import { fn, type Opts } from './fn.ts';
```


## Testing

Use the built-in runner; it replaces Jest/Mocha/Vitest for server-side libraries and small-to-mid services — assertions, mocking, coverage, watch, glob discovery, and parallel execution, running `*.test.ts` natively.

```ts
import { test, describe, it, mock } from 'node:test';
import assert from 'node:assert/strict';
test('adds', () => { assert.equal(1 + 1, 2); });
```

Run: `node --test` (add `--watch` in dev, `--experimental-test-coverage` for coverage). Reach for a third-party framework only for a need the built-in lacks (snapshot ecosystems, browser DOM testing) — and say why.


## Closing gate

Before calling a Node backend done, confirm every line:

- [ ] Version-lock header emitted (`version-grounded-coding`); `.nvmrc` + `engines` pin the LTS.
- [ ] `"type": "module"`; ESM throughout; `node:` prefix on every built-in import; no `__dirname`/`require` in ESM.
- [ ] No dependency that a built-in covers — `fetch`, `node:test`, `--env-file`, `--watch`, native TS (see the dep→built-in table in the reference).
- [ ] No callbacks/`promisify` where a promise API exists; no sync fs/crypto in a handler; no floating promises.
- [ ] Framework chosen from the decision table; server structured routes → handlers → services; async errors reach the error middleware (Express 5, not 4).
- [ ] Graceful shutdown wired: SIGTERM/SIGINT → `server.close()` → drain pools → exit; unhandled-rejection policy is log-and-exit, never swallow.
- [ ] Config validated once at startup into a frozen typed object; `process.env` read only there.
- [ ] Security checked against `secure-by-default`; outbound calls and the RFC 9457 error envelope against `integration-glue`.
