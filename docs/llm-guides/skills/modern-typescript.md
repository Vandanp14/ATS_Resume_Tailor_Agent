<!-- Source: vandan-llm-toolkit skills/modern-typescript/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Modern TypeScript

Weak models write TypeScript from the median of their training corpus: numeric `enum`s, `any` at every boundary, `as` casts to silence the checker, `namespace` blocks, `interface` reflexively, and generics sprinkled where a plain type would do. That code compiles and looks fluent, yet it fights the modern compiler, defeats the type system it is nominally using, and breaks the moment Node runs it by type-stripping. **The current idioms are finite and can be written down.** This skill is that discipline — apply the tables literally and you need no TypeScript taste of your own; the judgment is already encoded as an idiom table, a failure catalog, one canonical config, and a closing gate. Never tell the user to "use their judgment" on a type decision covered here.

Scope boundaries — do not restate a sibling's turf. **`state-and-data-fetching`** owns discriminated-union usage for async UI (the loading/error/empty/success quartet); model those unions here, but their rendering lives there. **`secure-by-default`** owns input validation as a *security* boundary; this skill owns parse-don't-validate only as a *typing* technique. **`data-modeling`** owns database schema. **`version-grounded-coding`** owns version resolution.

## Phase 0 — version lock first

Resolve the installed TypeScript major before applying any recipe here — per the **version-grounded-coding** skill, read the lockfile for `typescript` and cross-check the manifest. The recipes below are grounded in TypeScript 7.0 (`latest` = 7.0.2, GA 2026-07-08 — a native port, far faster than 6.0). If a repo depends on TS language-server plugins (Vue/Angular/Svelte), it may still pin TS 6.0 (the last JS-codebase release) until 7.1 ships the stable plugin API — treat that as valid, not a downgrade to fix. If the resolved major differs from these, read that version's docs before applying.

## Modeling discipline (apply always)

1. **Discriminated unions are the default model for any finite variant set** — state machines, domain variants, result types. Each member shares a literal discriminant (`kind` / `type` / `status`); code narrows on it. This is the preferred alternative to enum-plus-class hierarchies.
2. **Every exhaustive `switch` ends with a `never` guard.** Assign the narrowed value to `const _exhaustive: never = x` in `default` so an unhandled variant becomes a *compile* error the moment it is added, not a runtime bug. This is a widely-followed idiom, not a version feature.
3. **Parse, don't validate, at every boundary.** HTTP payloads, env vars, JSON, form data, and third-party responses enter as `unknown` and are parsed into a typed value with a schema (zod v4 current) — downstream code then holds a proven type. Derive the static type with `z.infer<typeof Schema>`; never declare the type twice.
4. **`unknown` at boundaries, never `any`.** `any` is a type-safety hole; `unknown` forces narrowing before use. `strict` already types `catch` variables as `unknown` — keep them that way.
5. **A type parameter must be used at least twice.** A generic that appears in one position carries no type information — make it a plain parameter or `unknown`.

## The idiom table — the core artifact

For every stale pattern there is one current replacement, copy-paste ready. **Read [references/idioms.md](references/idioms.md)** for the full table — enum, `any`, `as`-casts, interface-vs-type, overloads, `namespace`, `Function`/`{}`, discriminated unions, and parse-don't-validate. Each row is the exact code to emit.

## Failure catalog

The specific things weak models get wrong in this ecosystem, each with its fix:

| Failure | Why it is wrong | Fix |
|---|---|---|
| `x as T` / `as any` / `as unknown as T` to silence an error | Defeats the checker; the type is now a lie | Narrow with a type guard, `satisfies`, or `Schema.parse` |
| `value!` sprinkled to bypass `strictNullChecks` | Reintroduces the null crash the flag prevents | Narrow the null away, or model it in the type |
| `any` where a real type or `unknown` belongs | Silently disables all checking downstream | `unknown` + narrowing, or the actual shape |
| `enum` (esp. numeric / `const enum`) | Not erasable — dies under Node type-stripping; widens types | `as const` object + `typeof`-derived union |
| `namespace` / `module {}` for grouping | Legacy module system, non-erasable | ES module (`import`/`export`) |
| `let fn: Function` | `any`-typed args and return | Explicit signature `(x: A) => R` |
| `type Obj = {}` | Means "any non-null value", not "empty object" | `Record<string, unknown>` or the real shape |
| Single-use generic `<T>` | Adds no type relationship | Plain parameter or `unknown` |
| Type redeclared alongside its schema | Two sources of truth that drift | `z.infer<typeof Schema>` / `typeof value` |
| Optional-everything interfaces | Hides missing-data bugs behind `?` | Require what is required; model absence explicitly |

## Config, ESM, testing

**Read [references/config-and-boundaries.md](references/config-and-boundaries.md)** for the one canonical strict `tsconfig` block (app vs library variant), the typescript-eslint + formatter + test setup, the ESM rules (`verbatimModuleSyntax`, `moduleResolution` `bundler` vs `nodenext`, `.js` extensions on relative imports), and the zod boundary recipe with current testing conventions.

## Hard bans

- **Never** use `as` / `as any` / `as unknown as T` to make an error disappear — narrow, guard, or parse instead.
- **Never** emit `any` where `unknown` or a concrete type fits; never ship a non-null `!` to dodge strict null.
- **Never** write `enum` or `namespace` in new code — use `as const` unions and ES modules (both erasable).
- **Never** use the `Function` or `{}` types, or a generic that appears only once.
- **Never** declare a type that duplicates a schema you already have — derive it.
- **Never** leave a `switch` over a union without a `never` exhaustiveness guard.
- **Never** relax a strict flag to make code compile; fix the type instead.

## Closing gate — the type-review checklist

Before calling any TypeScript work done, confirm every line:

- [ ] Version-lock header emitted; idioms match the resolved TS major.
- [ ] No `as`/`as any`/double-cast, no non-null `!`, no `any`, no `Function`, no `{}` in the diff.
- [ ] No `enum` and no `namespace`; fixed value sets are `as const` unions.
- [ ] Every finite variant set is a discriminated union; every exhaustive `switch` has a `never` guard.
- [ ] Every external boundary parses `unknown` with a schema; types are `z.infer`-derived, never duplicated.
- [ ] Every generic is used in ≥2 positions; no single-use type parameters.
- [ ] `tsconfig` matches the canonical strict block (config-and-boundaries.md); `tsc --noEmit` and lint pass clean.
- [ ] ESM: `import type` where type-only; relative imports carry `.js` under `nodenext`; no CJS `require` in new code.
