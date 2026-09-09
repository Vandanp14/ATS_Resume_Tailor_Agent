<!-- Source: vandan-llm-toolkit skills/nextjs-craft/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Next.js Craft

Next.js changes its defaults faster than any model's training data. The biggest failure
mode is a weak model writing fluent code for a major no one is running: fetch assumed
cached, `getServerSideProps` in an App Router file, `middleware.ts` as current, `'use
client'` everywhere. It compiles in the model's head and misbehaves in production. This
skill removes those failures **not by asking you to know current Next.js, but by giving you
the exact current idiom for each decision.** Follow it literally — every value is here or in
the two reference files.

This is a currency-discipline skill, not a tutorial. It encodes what is *idiomatic in the
installed Next.js right now* and what is stale. The user may arrive with a vague ask — you
own the judgment path end to end.

## Phase 0 — VERSION LOCK (do this before writing a single line)

Idioms below shifted hard across Next 14, 15, and 16. **Do not apply any recipe from
memory.** Resolve the installed major first (this is the `version-grounded-coding`
discipline — read its SKILL.md for the full procedure and header format):

1. **Read `package.json` / the lockfile** and pin the exact `next` major. `^16.0.0` is a
   range, not a version — resolve the concrete number on disk.
2. **If vendored docs exist at `node_modules/next/dist/docs/`, READ THOSE FIRST.** This
   repo pattern is real (see this repo's own AGENTS.md) and those docs *are* the installed
   version — they cannot be wrong about what shipped. They outrank this skill and every
   blog.
3. **This skill is grounded in Next.js 16 (React 19.2), the current major as of mid-2026.**
   If the resolved major is 15 or 14, the caching defaults and several APIs differ — read
   that version's vendored docs before applying any recipe here. A Next-14 idiom in a
   Next-16 repo is a defect, not a style choice.

Emit the `version-grounded-coding` version-lock header naming `next` and `react` before
dependent code.

## The idiom table (stale way → current way)

This is the core artifact. Each row: what weak models emit from training data → the
current idiom. Copy the right column verbatim. Grounded in Next.js 16.

| Stale (reject) | Current (Next.js 16) |
|---|---|
| `getServerSideProps` / `getStaticProps` / `getStaticPaths` | `async` Server Component that `await`s data, or a route loader |
| `next/head` for `<title>`/meta | `export const metadata` or `async generateMetadata()` |
| `pages/_app.js`, `pages/_document.js` | `app/layout.tsx` root layout |
| "fetch is cached by default" (true only in 14) | `fetch()` is **uncached** by default; opt in with `cache: 'force-cache'` |
| blanket `{ cache: 'no-store' }` to "fix" staleness | already the default — instead opt *into* caching with `'use cache'` |
| `experimental.ppr` / `export const experimental_ppr` | `cacheComponents: true` + `Suspense` boundaries (PPR is absorbed) |
| `experimental.dynamicIO` | `cacheComponents: true` (renamed) |
| `middleware.ts` exporting `middleware` | `proxy.ts` exporting `proxy` (runs on Node.js runtime) |
| `revalidateTag('tag')` (single arg) | `revalidateTag('tag', 'max')` — a cacheLife profile is required |
| synchronous `params` / `searchParams` | `const { id } = await params` (they are Promises) |
| synchronous `cookies()` / `headers()` / `draftMode()` | `await cookies()`, `await headers()`, `await draftMode()` |
| `images.domains` | `images.remotePatterns` |
| `ImageResponse` from `next/server` | `ImageResponse` from `next/og` |
| `next lint` | run ESLint or Biome directly (`next lint` was removed) |
| "webpack is the bundler" | Turbopack is the default; opt out with `--webpack` |
| parallel-route slot with no `default.js` | add `app/@slot/default.js` returning `null` (build fails without it) |
| `'use client'` at the top of everything | Server Components are the default; add `'use client'` only at interactive leaves |

## Caching — the #1 failure (read the reference)

Weak models get caching wrong more than anything else here. The full **caching truth
table** for Next.js 16 (what is cached by default, how to opt in/out with `'use cache'` +
`cacheComponents`, and the `revalidateTag` / `updateTag` / `refresh` recipes) lives in
[references/caching-and-data.md](references/caching-and-data.md). Read it before writing any
data fetch, cache flag, or revalidation call. The one-line truth: **in Next.js 16 nothing
is cached by default — you opt in.**

## Routing, metadata, images, fonts (read the reference)

File conventions (`layout`/`page`/`loading`/`error`/`not-found`/`template`/`route`),
parallel and intercepting routes and the mandatory `default.js`, async `params`, the
metadata + OpenGraph recipe, and the `next/image` / `next/font` recipes with Next-16
default changes are in
[references/routing-and-conventions.md](references/routing-and-conventions.md). Read it
before creating routes, metadata, or media.

## Server actions & forms

Server Actions are the standard App Router mutation mechanism — a function with the
`'use server'` directive, inline or in a separate file. Pair them with the Next-16
cache APIs `updateTag()` (read-your-writes in the same request) and `refresh()` (refresh
uncached data). The full mutation recipe is in `references/caching-and-data.md`.

The **form UX layer** — labels, validation timing, accessible errors, submission and
double-submit states — is owned by **`form-craft`**; read it, do not restate it here. This
skill owns only the server-action wiring. The idiomatic form shape passes an action to
`<form action={...}>` (or uses the `next/form` component) with `useActionState` for pending
state.

## Server vs client components — one rule

Server Components are the default; add `'use client'` only at the smallest interactive leaf
that needs browser state or event handlers. The general server-vs-client-state boundary is
owned by **`state-and-data-fetching`** — read it, don't duplicate it here.

## Config — canonical copy-paste block

`next.config.ts` with current values. Adjust the hostname; keep the rest.

```ts
// next.config.ts
import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  cacheComponents: true, // opt into "use cache" + PPR (was experimental.dynamicIO)
  images: {
    remotePatterns: [{ protocol: 'https', hostname: 'example.com' }], // NOT images.domains
    qualities: [75], // Next 16 default is [75], not [1..100]
  },
  // output: 'standalone', // uncomment for self-hosting (minimal server bundle)
};

export default nextConfig;
```

Linting: `next lint` was removed — run ESLint or Biome directly (`next build` no longer
lints). Turbopack is the default bundler; pass `--webpack` only if a plugin forces it.
Upgrade with `npx @next/codemod@canary upgrade latest`.

## Testing conventions

Next.js does not prescribe a runner. *Inferred, not version-locked:* unit/component tests
typically use Vitest or Jest with React Testing Library; end-to-end flows use Playwright,
which exercises the real server and more reliably covers async Server Components and server
actions. Keep server-action logic in plain functions so it is unit-testable without a
request. Confirm the runner actually present in the repo before writing tests.

## Closing gate — every line true before "done"

- Version resolved from `package.json`/lockfile; vendored `node_modules/next/dist/docs/`
  read first if present; version-lock header emitted.
- No stale idiom from the table above survives (no `getServerSideProps`, `next/head`,
  `middleware.ts`, `images.domains`, `ImageResponse` from `next/server`, `next lint`).
- Caching is explicit and matches `references/caching-and-data.md`: nothing assumed cached
  by default; `revalidateTag` calls pass a cacheLife profile.
- `params`/`searchParams` and `cookies()`/`headers()`/`draftMode()` are awaited.
- Every parallel-route slot has a `default.js`.
- `'use client'` appears only at interactive leaves, not by default.
- `next.config.ts` uses `remotePatterns` and `cacheComponents`, not deprecated keys.
