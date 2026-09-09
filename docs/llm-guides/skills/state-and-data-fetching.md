<!-- Source: vandan-llm-toolkit skills/state-and-data-fetching/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# State & Data Fetching

Weak models write async UI as a happy path: fetch in a `useEffect`, drop the result into `useState`, render a spinner until it arrives. That code demos fine and breaks the moment reality intrudes — the request fails and nothing renders, the list is empty and the spinner hangs forever, the user types fast and a stale response overwrites a fresh one, or an effect copies props into state and the two drift apart. **Async UI has a small, fixed set of states and a small, fixed set of traps, and both can be written down.** This skill is that discipline: follow it literally and you need no taste — the judgment is already encoded as contracts, tables, and bans.

You own the **UI layer**: what renders in each async state, where each piece of state lives, and how fetches, mutations, and effects behave in the browser. The **server seam** — retry, timeout, idempotency, deadline propagation on the outbound call itself — belongs to `integration-glue`; call into it past the network boundary, do not restate it here. Form field UX (validation display, input affordances) belongs to `form-craft` if available; this skill owns only a form's *submission* states. Verifying installed framework versions belongs to `version-grounded-coding`.

## Phase 0 — verify versions before you write a line

The idioms below shift by major version, fast. **Do not apply any recipe from memory.** Resolve the installed majors first (per `version-grounded-coding`): read the lockfile for `react`, `react-dom`, `next`, and `@tanstack/react-query`. The recipes in `references/fetching-recipes.md` are grounded in React 19.2, Next.js 16, and TanStack Query v5 (mid-2026). If a resolved major differs, read that version's vendored docs before applying — a v4 Query call in a v5 repo is a defect, not a style choice.

## Operating rules (apply always)

1. **Every async render satisfies the state quartet.** Loading, error, empty, and success are four distinct branches, and a component renders exactly one. A component missing any branch fails review. This is the central contract — see [references/state-quartet.md](references/state-quartet.md).
2. **Server state is not client state.** Backend-owned data goes in a query layer (Server Component / route loader, or TanStack Query) that caches, dedupes, and invalidates. Local UI concerns go in `useState`/`useReducer`. Never mirror server data into local state via an effect.
3. **Derive, do not store.** Anything computable from existing props or state is computed during render — never held in a second state and synced with an effect. See [references/effect-discipline.md](references/effect-discipline.md).
4. **Effects are for external-system sync only.** Interaction-triggered code goes in an event handler; prefer the framework/query layer over a raw fetching effect.
5. **Every fetch is race-safe.** Any fetch keyed on changing input either cancels the stale request (`AbortController`) or ignores its result (ignore-flag). No exceptions on typeahead, tabs, or pagination.

## Decide where each piece of state lives (do this first)

| The state is… | Examples | Put it in |
|---|---|---|
| Server-owned data over the network, reused across the app | user profile, product list, comments | Server Component / route loader, or TanStack Query — **not** `useState` |
| Async data local to one screen, client-fetched | a widget's search results | TanStack Query, keyed by its inputs |
| Ephemeral UI concern for this component only | open/closed, hovered, current tab | `useState` / `useReducer` |
| Shared client-only UI state | theme, sidebar collapse, wizard step | small client store (Zustand/Jotai) or Context |
| Derivable from the above | filtered list, full name, totals | **nothing** — compute during render |

This split reflects the current mid-2026 consensus, not a hard spec; when unsure, ask "does a backend own the truth of this value?" — if yes it is server state and belongs in the query layer, never hand-synced into `useState`.

## Then classify the task and read the recipe

| Task | Read |
|---|---|
| Render any fetched screen correctly | [references/state-quartet.md](references/state-quartet.md) |
| Fetch in a Server Component / with `use()` / TanStack Query; mutate + invalidate; optimistic update; prevent races | [references/fetching-recipes.md](references/fetching-recipes.md) |
| Remove a bad effect (derived state, prop mirroring, event logic); fix a stale closure or render loop | [references/effect-discipline.md](references/effect-discipline.md) |
| Submit a form (pending / disable / feedback) | [references/fetching-recipes.md](references/fetching-recipes.md), then `form-craft` for field UX |

## Hard bans

- **No fetch-in-render without the framework's cache.** In the App Router, uncached async work streams via `<Suspense>` or uses the `'use cache'` directive — never `fetch().then(setState)` as your app-wide data layer.
- **No loading spinner without its error and empty branches.** A spinner alone is incomplete. All four quartet branches or it does not ship.
- **No `useEffect` for derived state or prop mirroring.** Compute during render; copying props/state into state via an effect is always a bug.
- **No `useEffect` for logic that belongs to a user interaction.** That code goes in the event handler.
- **No unkeyed list rendering.** Every mapped item has a stable, data-derived `key` — never the array index for reorderable/mutable lists.
- **No swallowing a fetch error into `console.log`.** A caught error sets the quartet's error branch (or rethrows to an error boundary). Silent catch is banned.

## Output contract — the async-UI review gate

Before calling any data-fetching work done, confirm every line:

- [ ] Version-lock header emitted; recipes match the resolved React/Next/Query majors.
- [ ] Every async component renders exactly one of loading / error / empty / success — all four branches present.
- [ ] Empty is distinct from loading; the error branch surfaces the failure and offers retry where sensible.
- [ ] Server data lives in the query/RSC layer; no server data mirrored into `useState` via an effect.
- [ ] No `useEffect` produces derived state or copies props into state; derived values are computed during render.
- [ ] Every input-keyed fetch cancels or ignores stale responses; no last-write-wins race remains.
- [ ] Mutations invalidate or update the cache; optimistic updates roll back on error.
- [ ] Every mapped list has a stable data-derived key; no swallowed fetch errors.
- [ ] Server-seam reliability (timeout/retry/idempotency) checked against `integration-glue`.
