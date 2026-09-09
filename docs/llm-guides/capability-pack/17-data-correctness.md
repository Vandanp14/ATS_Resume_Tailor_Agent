# 17 — Data Correctness

The silent-bug catalog: money, time, text, floats, null. These bugs pass happy-path
tests and corrupt data for months. Check every rule against any code that touches the
relevant type.

## Money

- **Never binary float.** `0.1 + 0.2 != 0.3`. Store integer minor units (cents) or
  `Decimal`/`numeric`. DB column: `INTEGER` or `NUMERIC(precision, scale)` — never
  `FLOAT`/`REAL`/`DOUBLE`.
- Serialize as integer cents or string decimal in APIs — JSON numbers round-trip
  through float in many parsers.
- Rounding: pick a rule (banker's vs half-up), apply at ONE defined point (final
  display or final total), not per intermediate step. Sum-then-round ≠ round-then-sum;
  know which the domain needs.
- Currency travels with amount. No naked numbers if more than one currency can exist.

## Time

- **Store UTC, convert at the display edge.** DB columns timezone-aware
  (`timestamptz`); serialize ISO-8601 with offset (`2026-07-08T14:00:00Z`).
- Never mix naive and aware datetimes — pick aware everywhere:
  `datetime.now(timezone.utc)`, not `datetime.utcnow()` (naive, deprecated).
- **A date is not a midnight datetime.** Birthdays, due dates, calendar days = `DATE`
  type. Converting a date through a timezone shifts it a day for half the planet.
- "Today"/"this week" are user-timezone questions — compute against the USER's tz,
  not the server's. Server tz must never matter (set UTC anyway).
- DST exists: "add 1 day" ≠ "add 24 hours" (tz-aware calendar arithmetic vs
  timedelta); 02:30 sometimes doesn't exist or exists twice. Recurring schedules
  ("every day at 9am") need the tz rules library (`zoneinfo`), not timedelta math.
- Tests: freeze the clock (guide 04); test the DST-transition and year-boundary
  cases; never assert "now"-relative values loosely.

## Text

- UTF-8 everywhere, DECLARED: `open(path, encoding="utf-8")` — the default is
  platform-dependent and will burn you on Windows/CI.
- Length ≠ bytes ≠ glyphs: emoji and combining chars break `len()`-based truncation
  and `VARCHAR(n)` byte limits. Truncate carefully, ideally not at all.
- User-input comparison: normalize (`unicodedata.normalize("NFC", s)`, casefold,
  strip) before comparing/deduping — "é" has two encodings.
- Never parse CSV/JSON with `split(",")`/regex — real parser (`csv`, `json`), which
  handles quoting, escapes, embedded delimiters.

## Floats (non-money numerics)

- No equality: `math.isclose(a, b, rel_tol=…)` / epsilon compare.
- Accumulating many small floats drifts — `math.fsum` or restructure.
- Ints in JSON > 2^53 lose precision in JS clients — serialize big IDs as strings.

## Null / empty / zero — three different facts

- `None`≠`0`≠`""`≠`[]`: "not answered" vs "answered zero". Schema and code must pick
  deliberately; `if not x` conflates all four — write `if x is None` when you mean it.
- DB: `NULL` never equals anything (`= NULL` is always false — `IS NULL`); NULLs sort
  oddly and vanish from `COUNT(col)` and `WHERE col != 'x'`. Check every query
  touching nullable columns against these.

## IDs & keys

- IDs are opaque strings: don't parse meaning from them, don't do arithmetic on them,
  don't let JS clients receive them as big ints (see floats).
- Natural keys (email, username) change — surrogate keys for identity, unique
  constraint for the natural value.

## Output contract

Any diff touching money/time/text/nullable data: rules above checked line-by-line ·
edge-case tests added (DST boundary, unicode input, null vs zero, rounding) per
guide 04 · types in schema match the rules (no FLOAT money, no naive timestamps).
