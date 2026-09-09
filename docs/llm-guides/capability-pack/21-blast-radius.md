# 21 — Blast Radius

Rule: **before you touch any shared symbol, find every consumer first.** Weak models
edit the definition, then discover the rest of the blast radius through broken builds —
or worse, ship a half-migrated codebase where old and new coexist. Frontier models
enumerate every caller, test, and format the change touches and update them in the
*same* change. This guide makes that enumeration mechanical.

Extends guide 08 (refactoring-safety), which covers HOW to change a symbol safely.
This guide covers WHO the change hits — and it applies to **any** behavior change, not
just refactors: a new required parameter, a changed return shape, an altered prop, a
renamed DB column all have a blast radius.

## What counts as a shared symbol

Any exported/public **function, type, class, constant, schema, DB column, route,
endpoint, component, prop, config key, or string key** used outside the file you're
editing. If a name crosses a file boundary, this guide applies.

## The procedure

```
1. NAME the symbol and the exact change (rename? new param? return shape? column?).
2. GREP for every reference — use the patterns below. Save the full list.
3. LIST each hit as: file · reason it references the symbol · needs-edit? (Y/N).
   This is the IMPACT MAP. Append it to the plan/PLAN.md.
4. CLASSIFY the change: local / module / cross-cutting (see below).
   If the map is bigger than your estimate, STOP and re-scope the plan.
5. EDIT the definition AND every needs-edit hit in the same change.
6. RECONCILE: count references found vs. references accounted for. N = N or not done.
```

## Ready-to-run search patterns

```bash
# Callers / imports of a symbol (widen: no word boundary if it's part of a name)
grep -rn "myFunction" --include='*.*' .
# Config / string keys / env vars (quoted usage is invisible to type-checkers)
grep -rn "MY_KEY\|\"my_key\"\|'my_key'" .
# Routes / endpoints (path strings, not the handler name)
grep -rn "/api/orders" .
# Component + every prop usage
grep -rn "<OrderCard\|OrderCard(" .
# Field/column across serializers, fixtures, migrations
grep -rniE "order_status|orderStatus" .
```

Run the grep BEFORE writing the plan. A plan scoped to the files you happened to have
open is scoped to nothing.

## Forgotten-consumer taxonomy — check every row

| Consumer class | Why it's missed |
|---|---|
| Unit/integration tests | grep skips `*_test`/`spec` dirs unless you include them |
| Snapshots / golden files | not code; a changed shape breaks them silently |
| Serializers / (de)serializers | field rename passes types but corrupts output |
| Wire formats / API schemas | external consumers you can't see in this repo |
| Persisted / cached data | old rows/keys already written in the old shape |
| Other services / repos | grep this repo only; they break at runtime |
| Config, fixtures, seed data | string keys, invisible to the compiler |
| Docs / examples / generated code | drift into lies the moment you rename |

## Classify before you touch code

- **Local** — every reference is inside one file. Edit freely.
- **Module** — references stay within one package/dir. Update all in one change.
- **Cross-cutting** — references cross packages, services, wire formats, or persisted
  data. Requires a migration plan and the reversibility check below.

## Reversibility & migration check (data/contract changes)

If the change touches persisted data or an external contract: can old and new coexist
during rollout? If not, you need a two-step migration (add new → migrate → remove old),
not a rename. Never assume every consumer deploys atomically with you.

## Hard bans

- **No partial migration.** Never leave the old name/shape AND the new one coexisting
  "for now." Every consumer moves in this change, or the change doesn't ship.
- **No "should be all of them."** Only the grep decides the reference set, not memory.
- **No "trivial rename" claim** before the grep proves the fan-out is small.
- **No editing the definition before the impact map exists.**

## Output contract

Change is ready only when: the impact map is appended to the plan (file × reason ×
needs-edit) · the change is classified local/module/cross-cutting · every needs-edit
consumer across the taxonomy is updated in this change · no old+new coexistence remains
· and the reference-count reconciliation holds — **N references found, N accounted
for.** If N ≠ N, you are not done.
