<!-- Source: vandan-llm-toolkit skills/accessibility-overhaul/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Accessibility Overhaul

Turn any web UI into a **WCAG 2.2 AA** product through six phases. Output quality does not
depend on the model running it or on the user knowing anything about accessibility: every
phase has exact values, copy-paste code, an output contract, and a gate. The taste is encoded
here — never fall back on "use your judgment." Follow the phases literally.

Target standard: **WCAG 2.2, Level AA** — the current W3C Recommendation (12 December 2024)
and the right conformance target in 2026. Do **not** target WCAG 3.0; it is an incomplete
Working Draft. AAA criteria are labelled AAA below — hold at AA.

Cross-skill sources of truth (if present, they override on their turf):
- **`vandan-ui-system`** owns the focus ring's *visual* style (color, thickness, offset).
  This skill owns that a visible focus indicator **exists** and is never removed.
- **`motion-craft`** owns the reduced-motion tokens. This skill owns that a
  `prefers-reduced-motion` path **exists**.

## Operating rules (read first, apply always)

1. **One phase at a time, in order.** Finish a phase's output contract before the next.
   Each reference file is self-contained for one-phase-per-session work.
2. **Never skip Phase 1 (audit) or Phase 6 (gate).** The audit's ranked findings table gates
   Phase 2+; the Phase 6 checklist gates any claim of "accessible."
3. **Copy values verbatim.** Contrast ratios, pixel sizes, CSS, and ARIA strings are exact —
   no "similar" substitutes.
4. **Automation is a floor, not proof.** axe-core / Lighthouse catch only a minority of
   issues — roughly 57% by Deque's benchmark, conservatively 30–40% (Lighthouse runs a
   subset of axe rules). Keyboard operability, focus order, alt-text quality, and live-region
   announcements **require the manual keyboard walkthrough**.
5. **Preserve behavior.** This is a semantics/interaction pass, not a redesign; all routes,
   data flow, and tests still pass after every phase.
6. **Write the plan file.** Phase 1 produces `A11Y_PLAN.md` at the repo root; every later
   phase reads it and checks off items, so a weak model or fresh session resumes cleanly.

## The six phases

Read the phase file right before executing it. Do not read all references upfront.

| Phase | File | Produces |
|---|---|---|
| 1. Audit | [references/audit.md](references/audit.md) | `A11Y_PLAN.md`: ranked findings table (the gate) from 5 scans |
| 2. Semantics | [references/semantics-and-keyboard.md](references/semantics-and-keyboard.md) | Native elements replace div-soup; heading + landmark hierarchy fixed |
| 3. Keyboard + focus | [references/semantics-and-keyboard.md](references/semantics-and-keyboard.md) | Visible focus, sane tab order, skip link, modal focus handling |
| 4. ARIA patterns | [references/aria-patterns.md](references/aria-patterns.md) | APG recipes **only where native cannot** — each with a key table |
| 5. Content | inline below | Alt-text decisions, exact contrast fixes, reduced-motion + forced-colors |
| 6. Gate | inline below | Evidence checklist: axe clean + keyboard walk + contrast table |

Order note: semantics (2) precede keyboard/focus (3) so focus lands on real
`<button>`/`<a>` elements, not a `div` you would have to hand-patch.

## Canonical WCAG 2.2 AA values (copy verbatim)

| Thing | Value | Criterion |
|---|---|---|
| Body / small UI text contrast | **≥ 4.5:1** | 1.4.3 (AA) |
| Large text contrast (≥ 24px, or ≥ 18.66px bold) | **≥ 3:1** | 1.4.3 (AA) |
| UI component boundary, state, focus indicator, meaningful graphic | **≥ 3:1** vs adjacent color | 1.4.11 (AA) |
| Pointer target size | **≥ 24 × 24 CSS px** (or pass the Spacing exception) | 2.5.8 (AA) |
| Keyboard focus indicator is visible | **required** | 2.4.7 (AA) |
| Focused component not entirely hidden by sticky/overlay content | **required** | 2.4.11 (AA) |
| Focus indicator size/contrast minimums (2.4.13) | AAA — **not** required for AA | 2.4.13 (AAA) |

**Spacing exception:** a target smaller than 24px passes if a 24px-diameter circle centered on it does not overlap any other target or another target's 24px circle.

## Phase 5 — Content

**Alt-text decision rules** (pick exactly one per image):

| Image role | `alt` value |
|---|---|
| Informative | Concise description of the information it conveys |
| Decorative / redundant with adjacent text | `alt=""` (empty, not missing) |
| Functional (inside a link/button) | The **action or destination**, not the picture |
| Image of text | The text, verbatim |
| Complex (chart/diagram) | Short `alt` + a longer description in nearby text |
| Icon-only control | Put the name on the control (visually-hidden text or `aria-label`); the icon is decorative |

**Contrast fixes.** Measure every foreground/background pair; if below the canonical-table
value, adjust the foreground (or add a solid layer under text on images) until it meets the
ratio. Logotypes and disabled/inactive controls are exempt. Never encode state or meaning in
**color alone** — add text, an icon, underline, or shape.

**Reduced motion.** Every animation/transition needs a `prefers-reduced-motion` path (tokens
from `motion-craft` if present). Global safety net:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

**Forced colors (Windows High Contrast).** Do not build a separate design behind
`@media (forced-colors: active)`; let the browser remap and only patch legibility with
system-color keywords. `outline` survives forced-colors, so focus rings keep working:

```css
@media (forced-colors: active) {
  .btn { border: 1px solid ButtonText; color: ButtonText; background: ButtonFace; }
  :focus-visible { outline: 2px solid Highlight; }
}
```

Use `forced-color-adjust: none` **only** where color is the content (swatches, charts).

## Phase 6 — Gate (each box needs evidence)

- [ ] **axe-core / axe DevTools: 0 violations** — attach the run output. (Floor only.)
- [ ] **Keyboard-only walkthrough complete** (Phase 1 script re-run): every interactive
      element reachable and operable, visible focus at all times, tab order matches reading
      order, no unexpected trap, Escape closes every overlay, focus returns to the trigger.
- [ ] **Contrast table** listing every text/UI pair with its measured ratio ≥ its threshold.
- [ ] **Forms:** every field has a programmatic label; errors are text, not color-only.
- [ ] **Images:** every `<img>` has a resolved alt-text decision from the Phase 5 table.
- [ ] **Modals:** native `<dialog>`+`showModal()` (or role + `inert` + JS trap) verified.
- [ ] **Reduced-motion path** verified; no hard-ban item present.

The gate is closed only when every box is checked **with its evidence attached**. Automation
green + manual boxes unchecked = not done.

## Hard bans (never do these)

- **No ARIA on an element with a native equivalent** — reach for `<button>`, `<a>`, `<nav>`,
  `<dialog>`, `<details>` before `role=` + JS. No ARIA beats bad ARIA.
- **No positive `tabindex`** (`1`+). Only `0` or `-1`.
- **No color-only** state, error, or meaning.
- **No `outline: none`** (or `:focus { outline: none }`) without a visible replacement.
- **No `aria-*` name on non-interactive text** (plain `<p>`, `<span>`, `<div>`).
- **No `role="menu"` for site navigation** — that role is for app action menus; nav is a
  `<ul>` of `<a>` links inside `<nav>`.
- **No claiming "accessible" from a Lighthouse/axe pass alone** — the manual walk is required.

## For orchestrating models

Run phases 2–5 as sequential subagents (one each), handing each the phase file plus
`A11Y_PLAN.md`. Verify each output contract between phases. Never parallelize — they are
order-dependent. Run Phase 6 yourself. This skill supersedes the backlog `accessibility-audit`
guide entry (it covers that checklist and extends it into remediation) — do not author that.
