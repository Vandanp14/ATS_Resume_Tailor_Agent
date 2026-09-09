<!-- Source: vandan-llm-toolkit skills/data-modeling/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Data Modeling

Turn a plain-English product description into a complete, correct PostgreSQL schema.
Written so the **output does not depend on the model or user running it**: every phase
has a decision table, copy-paste DDL, and a closing gate. The user supplies the product;
this skill supplies all the modeling judgment. Never ask the user to "use their
judgment" on keys, types, constraints, or indexes — decide from the tables here.

Version grounding: values below are current as of PostgreSQL 18 (2025-09) and RFC 9562
(May 2024, which finalized UUIDv7 and obsoletes RFC 4122). PG18 added `uuidv7()`, a
`uuidv4()` alias, and `VIRTUAL` generated columns — do not fall back to older idioms
without a reason.

Scope: this skill owns **greenfield design and the target-state schema**. Changes to a
schema already running in a system go through
[guide 13 — database migrations](../../guides/capability-pack/13-database-migrations.md).
Money/time/null correctness comes from
[guide 17 — data correctness](../../guides/capability-pack/17-data-correctness.md); this
skill enforces its *schema* half.

## Operating rules (read first, apply always)

1. **Six phases, in order.** Do not jump to writing DDL before Phase 1 names the
   entities. Each later phase reads the artifact the previous one produced.
2. **Copy values verbatim.** When a table gives a type, DDL pattern, or index shape, use
   it exactly. Do not substitute a "similar" type.
3. **Constraints are truth; the app only assists.** Every invariant that must always
   hold is enforced by the database (FK, CHECK, UNIQUE, NOT NULL). App-only rules rot.
4. **NOT NULL by default.** A nullable column is a *decision* you must justify in one
   line ("null = not yet answered, distinct from zero"). Absent a reason, add NOT NULL.
5. **Never skip Phase 1 (nouns) or the closing gate.**
6. **Write the model doc.** The final artifact is a complete DDL block plus a one-page
   model doc (entities, keys, invariants) — see the output contract.

## Phase 1 — NOUNS (do this inline, before reading any reference)

Extract the data model's entities and relationships from the product description. Make
**no type or key decisions yet** — only name the things and how they relate.

1. **List entities.** Every distinct noun the product tracks that has its own identity
   and lifecycle is a table (user, order, product, invoice). A noun that is only an
   attribute of another (a user's email) is a column, not a table.
2. **List relationships and their cardinality.** For each pair of related entities,
   decide 1:1, 1:N, or M:N. Every M:N becomes its own **junction table** (two FKs, no
   surrogate PK needed unless the relationship itself has attributes).
3. **Fill the cardinality table** — this is the Phase 1 artifact:

| Entity A | Relationship | Entity B | Cardinality | Realized as |
|---|---|---|---|---|
| order | has | line_item | 1:N | `line_item.order_id` FK |
| product | appears in | order | M:N | `line_item` junction (order_id, product_id) |
| user | has | profile | 1:1 | `profile.user_id` FK + UNIQUE |

Rule: 1:N puts the FK on the **many** side. 1:1 is a 1:N with a UNIQUE on the FK.
Never model M:N with an array column or comma-joined text — always a junction table.

## The six phases

Read the reference file for a phase right before executing it. Do not read all three
references upfront.

| Phase | File | Produces |
|---|---|---|
| 1. Nouns | inline above | entity list + cardinality table |
| 2. Keys | [references/keys-and-columns.md](references/keys-and-columns.md) | id strategy per table |
| 3. Columns | [references/keys-and-columns.md](references/keys-and-columns.md) | typed, named, null-decided columns; enum strategy |
| 4. Constraints | [references/constraints-and-indexes.md](references/constraints-and-indexes.md) | FK / CHECK / UNIQUE DDL |
| 5. Access patterns | [references/constraints-and-indexes.md](references/constraints-and-indexes.md) | indexes matched to real queries |
| 6. Hard cases | [references/hard-cases.md](references/hard-cases.md) | soft-delete, JSONB, multi-tenancy, money/time decisions |

## Hard bans (enforced in every phase)

- **No FK-less "joins in application code."** Any column that points at another table's
  row is a real `REFERENCES` foreign key. If two tables relate, the DB knows it.
- **No `float`/`real`/`double precision` for money.** Use `numeric(precision, scale)` or
  integer minor units (cents). See guide 17.
- **No naked `timestamp` for an instant.** Any moment in time is `timestamptz`. Plain
  `timestamp`/`date` only for genuinely zoneless wall-clock values (a birth date).
- **No enum-in-app-only that the DB stores as free text.** If a column has a fixed value
  set, the DB constrains it — CHECK, native enum, or FK to a lookup table. Never a bare
  `text` column that the app "promises" to keep valid.
- **No soft delete without a filtered unique index.** If you add `deleted_at`, every
  unique constraint on that table becomes a partial unique index scoped to live rows.
- **No speculative indexes.** Index only columns that a listed query filters, joins, or
  sorts on. An unused index is pure write-cost.
- **No UUIDv4 primary keys for index-friendliness reasons.** Random UUIDs fragment the
  primary-key index; use `bigint` identity or time-ordered `uuidv7()` (Phase 2).

If you find a violation while designing, fix it before finishing the phase.

## Output contract

The skill is done only when both artifacts exist:

1. **A complete DDL block** — `CREATE TABLE` for every entity and junction, with keys,
   types, NOT NULLs, defaults, all FK/CHECK/UNIQUE constraints, and `CREATE INDEX` for
   every access pattern. It must run top-to-bottom on a clean PostgreSQL 18 database
   (parent tables before children). Prepend any required `CREATE EXTENSION` lines (e.g.
   `CREATE EXTENSION IF NOT EXISTS citext;` whenever a `citext` column is used — it is a
   contrib type absent from a stock DB).
2. **A one-page model doc** with exactly these sections:

```markdown
# Data Model — <product>

## Entities
<one line per table: what it is, its grain (one row = one ___)>

## Keys
| Table | PK strategy | Natural key (UNIQUE) | Why |

## Invariants (DB-enforced)
- <each CHECK / UNIQUE / FK rule, in plain English>

## Deliberate nullables
- <each nullable column + why null is meaningful>

## Deferred / open
- <anything needing product input, and hard-case decisions taken (soft-delete, tenancy)>
```

Closing gate — every box true before you report done:
`[ ]` every entity and every M:N junction from Phase 1 is a table ·
`[ ]` every table has a PK and every FK points at one ·
`[ ]` no banned type (float money, naked timestamp) present ·
`[ ]` every fixed-value column is DB-constrained (not app-only) ·
`[ ]` every index traces to a listed query; no speculative indexes ·
`[ ]` soft-delete (if used) has partial unique indexes ·
`[ ]` every extension a used type needs (e.g. `citext`) is created at the top of the DDL ·
`[ ]` the DDL block runs clean and the model doc's four+ sections are filled.
