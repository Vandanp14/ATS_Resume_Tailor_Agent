<!-- Source: vandan-llm-toolkit skills/form-craft/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Form Craft

A form is where users hand you their data — the most abandoned surface in most apps.
Weak models ship forms that look fine and fail in use: placeholders where labels belong,
red errors flashing mid-keystroke, autofill that never fires, a submit button that
double-charges, a validation error that wipes everything typed. This skill removes those
failures — **not by asking you to have taste, but by giving you the exact recipe for
every decision.** Follow it literally; every value you need is here or in the two
reference files.

The user may arrive with no vocabulary for this. "Make this form better" and
"build me a signup form" both route here for the full treatment. You own the judgment
path end-to-end.

## Operating rules (read first, apply always)

1. **Client validation is UX, never security.** Every rule here improves the fill
   experience. It does not protect anything. The server re-validates and authorizes
   independently — that is `secure-by-default`'s job. Never treat a passing client check
   as trust.
2. **Copy values verbatim.** The `type`, `inputmode`, `autocomplete`, ARIA wiring, and
   timing rules are exact. Do not substitute "similar" tokens — autofill and screen
   readers break on near-misses.
3. **Native first.** Use the platform control (`<select>`, `<input type=date>`, native
   file input) unless a hard requirement forces custom. A custom widget you build is a
   custom widget you must make accessible from scratch, and you will get it wrong.
4. **Never blame the user in copy.** Error text states what happened and how to fix it.
   No "invalid", no "you must", no scolding.
5. **Visual styling is not owned here.** Colors, radii, focus-ring look, spacing scale
   belong to `ui-component-arsenal`. This skill owns structure, semantics, and behavior;
   pull the skin from there.

## Deterministic build order

Do these phases in order. Read the reference file named in a phase *right before* doing
that phase — do not read both references upfront.

| Phase | Do | Read |
|---|---|---|
| 1. Classify | Count fields; pick the validation pattern (table below) and single- vs multi-step. | this file |
| 2. Build each field | Apply the field anatomy; set type + inputmode + autocomplete from the table. | [references/field-recipes.md](references/field-recipes.md) |
| 3. Wire validation & states | Add timing, accessible errors, submission states, multi-step persistence. | [references/validation-and-states.md](references/validation-and-states.md) |
| 4. Gate | Run the closing checklist; fix every miss before declaring done. | this file |

## Phase 1 — Classify

Pick the validation-surfacing pattern from form size. This is not a judgment call; read
it off the table.

| Form shape | Error surfacing |
|---|---|
| Short form (≈9 fields or fewer) | Inline message at each field only. No top summary. |
| Long single page (≈10+ fields) | Inline at each field **and** an error summary at the top, focused on submit. |
| Multi-step wizard | Inline at each field, validated per step; summary optional per step. |

Choose multi-step when the form is long *and* used infrequently (onboarding,
applications, checkout). Keep a form used repeatedly by the same people (internal data
entry) on one page. When unsure, stay single page — a wizard adds state you must persist.

## Field anatomy (the fixed layout, every field)

Every field is built from four parts in this DOM order. Never reorder them; the order is
what makes the autofill and screen-reader wiring in Phase 3 correct.

1. **Label** — a real `<label for="…">`, always visible, above the control.
2. **Help text** — optional one line under the label, `id="<field>-help"`, explaining
   format or why you ask ("We'll only email you a receipt").
3. **Control** — the input/select, `aria-describedby="<field>-help <field>-err"`.
4. **Error slot** — an always-present container `id="<field>-err"` with reserved height
   so showing an error causes no layout shift. Empty when valid.

Help text goes *before* the control so the user reads the instruction before typing; the
error slot goes *after* so the correction sits next to what the user just left. Exact
markup and the describedby chaining are in `references/field-recipes.md`.

## Hard bans (enforced in every form)

- **No placeholder as the label.** Placeholders vanish on focus and fail contrast; label
  above, always. A placeholder may show an *example* value only ("e.g. 555-0142").
- **No validation on keystroke for a pristine field.** First feedback comes on blur or on
  submit. Only after a field has errored once does it re-validate on input.
- **No disabled submit button as the only signal of an invalid form.** A greyed-out
  button with no explanation is a dead end. Keep submit enabled and explain on click, or
  pair any disabling with a visible reason.
- **No clearing the form on a failed submit.** Keep every value.
- **No custom dropdown where a native `<select>` works.** Custom pickers break keyboard,
  mobile, and autofill. Go native unless a hard requirement forces otherwise.
- **No `type="number"` for identifiers** — OTP, ZIP, card, phone. It strips leading zeros
  and allows exponents. Use `type="text"` + `inputmode="numeric"`.
- **No `:invalid`/`:valid` styling.** They flag empty required fields on load. Use
  `:user-invalid`/`:user-valid`, which only match after interaction.
- **No drag-and-drop-only file upload.** Always keep the native click-to-browse input as
  the accessible path.

## Cross-references (don't duplicate their work)

- **`ui-component-arsenal`** owns the *visual* styling of inputs, buttons, and controls.
  Structure and behavior here; skin there.
- **`secure-by-default`** owns *server-side* validation and authorization. Everything in
  this skill is client-side UX and provides zero security.
- **`integration-glue`** owns *server-side idempotency*. The double-submit guard in
  Phase 3 is the client half; the server must also dedupe by idempotency key.
- **`accessibility-overhaul`** (if installed) owns deep a11y beyond forms. This skill
  covers form-specific ARIA wiring; defer broader audits to it.

## Phase 4 — Closing gate

The form is done only when every line is true. Check each explicitly.

- Every control has a visible `<label for>`; no placeholder stands in for a label.
- Every field's `type`, `inputmode`, and `autocomplete` match the table in
  `field-recipes.md`; autofill fills a saved profile in one tap.
- No field shows an error before its first blur; a corrected field clears its error on
  input.
- The size-appropriate error surfacing from Phase 1 is present (summary focused on submit
  for long forms).
- Every error message names what happened and how to fix it, with no blame.
- Errors are wired with `aria-describedby` + `aria-invalid`; the summary uses `role=alert`.
- Submit disables with a spinner, guards against double-click, and shows explicit success
  and failure states.
- A failed submit preserves every entered value.
- Multi-step only: state survives Back and refresh; each step validates before advancing.
