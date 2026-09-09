<!-- Source: vandan-llm-toolkit skills/modern-css/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Modern CSS

CSS moved further between 2021 and 2026 than in the decade before it. Weak models emit the CSS in their training data: floats and clearfix, margin soup, `padding-top: 56.25%` ratio hacks, `position: absolute` centering, `!important` escalation, JS for anything conditional, and vendor prefixes on long-unprefixed properties. Each is now replaced by a shipped, Baseline feature. This skill swaps the stale pattern for the current one **by lookup, not taste** — every row below is copy-paste ready.

The rule is absolute: **never emit a pre-2021 hack when a Baseline feature does the same job.** Read the idiom table, take the current-way cell, ship it.

## Version lock first

CSS "version" is browser support, not a package number. Before using any feature, resolve the project's support floor — read `browserslist` / `.browserslistrc` in the manifest; absent that, default to **Baseline Widely available** (safe with no fallback). For the general resolve-then-write discipline, apply the **version-grounded-coding** skill. Baseline tiers used throughout this skill:

| Tier | Meaning | How to ship |
|---|---|---|
| **Widely available** | Passed the 30-month cross-browser threshold | Ship freely, no fallback |
| **Newly available** | In all major engines, but recently | Ship; note it, no `@supports` needed for most projects |
| **Limited** | Missing in a major engine | **Gate with `@supports` or keep a JS fallback** |

## The idiom table — stale hack → modern feature

One row per idiom. Left is what training data emits; right is what you write. Dates are Baseline first-available (low) dates.

| Stale way (stop) | Modern way (write this) | Baseline |
|---|---|---|
| `padding-top: 56.25%` ratio box | `aspect-ratio: 16 / 9;` | widely, 2021-09 |
| Margins between flex/grid items | `display: flex; gap: 1rem;` | widely, 2021-04 |
| JS media-query to reflow a component | `@container (min-width: 30rem) { … }` | widely, 2023-02 |
| JS to style a parent from a child/state | `.card:has(img) { … }` | widely, 2023-12 |
| BEM name sprawl (`.card__body--lg`) | native nesting `& > h2 { … }` | widely, 2023-12 |
| `!important` to win specificity | `@layer` + `:where()` (0-specificity) | widely, 2022-03 |
| `100vh` + JS `--vh` for mobile bars | `min-height: 100svh;` (also `dvh`/`lvh`) | widely, 2022-12 |
| `position:absolute; top:50%; translate` | `display: grid; place-items: center;` | widely (grid) |
| `left/right/top/bottom` in i18n UIs | logical props: `margin-inline`, `inset` | widely, 2021-09 |
| Duplicated grid tracks in nested grids | `grid-template-columns: subgrid;` | widely, 2023-09 |
| `:focus { outline: … }` (mouse too) | `:focus-visible { … }` (keyboard-only) | widely, 2022-03 |
| JS validation styling on blur | `input:user-invalid { … }` | widely, 2023-11 |
| hex + manual tints | `oklch(...)` + `color-mix(in oklab, …)` | widely, 2023-05 |
| JS to balance a headline's lines | `h1 { text-wrap: balance; }` | newly, 2024-05 |
| Fixed px breakpoint font steps | fluid `clamp()` (see modern-features.md) | widely |

Full per-feature detail, the fluid `clamp()` formula, the `:has()` recipe collection, logical-property mapping, and `oklch`/`color-mix` usage: read [references/modern-features.md](references/modern-features.md) just before you apply them. This skill owns the **language features**; **vandan-ui-system** owns the actual token/palette values and taste — do not invent brand colors here.

## The no-JS table — component → pure CSS/HTML

Reach for JavaScript last. These mechanisms are HTML/CSS-native; full copy-paste recipes in [references/no-js-patterns.md](references/no-js-patterns.md).

| Component | Mechanism | Baseline |
|---|---|---|
| Accordion / disclosure | `<details><summary>`; `name=` for one-open | widely; `name=` newly |
| Menu / popover / tooltip | Popover API (`popover` + `popovertarget`) | newly, 2025-01 |
| Carousel | scroll-snap (`scroll-snap-type` / `-align`) | widely |
| Modal / dialog | `<dialog>` + `showModal()` | newly |
| Tooltip/menu placement | anchor positioning (`anchor-name`/`position-anchor`) | new in early 2026 — gate |
| Scroll-driven reveal | `animation-timeline: view()` | **Limited — needs JS fallback** |

## Failure catalog — what weak models get wrong

1. **Floats for layout.** Use `flex`/`grid`; floats are for real text wrap only.
2. **`px`-only `min-width` media queries as the *only* responsiveness tool.** Prefer container queries for component-level reflow and intrinsic layouts: `grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr))`. Use `rem` (not `px`) breakpoints so they respect zoom.
3. **`!important` cascade wars.** Manage specificity with `@layer` and `:where()`, never escalation.
4. **`position:absolute` + `translate(-50%,-50%)` centering.** `display:grid; place-items:center`.
5. **Vendor prefixes** (`-webkit-`/`-moz-`/`-ms-` on flexbox, transitions, transforms, border-radius, box-shadow, gradients, box-sizing) — all unprefixed and Baseline. Stop emitting them and stop adding autoprefixer for them.
6. **`transition: all`.** Enumerate the properties; `all` triggers surprise reflows and paints.
7. **Shipping `Limited` features as if Baseline.** Scroll-driven animations, cross-document `@view-transition`, `interpolate-size`/`calc-size()`, and `text-wrap: pretty` are **not** Baseline as of mid-2026 (note `text-wrap: balance` *is*). Progressive-enhance them behind `@supports`; keep the static/JS path working.

## Config — copy-paste

`.browserslistrc` — target Baseline, drop the prefix crutch:

```
> 0.5%
last 2 versions
not dead
```

`.stylelintrc.json` — modern rules, no legacy-prefix churn:

```json
{
  "extends": ["stylelint-config-standard"],
  "rules": {
    "property-no-vendor-prefix": true,
    "value-no-vendor-prefix": true,
    "declaration-block-no-redundant-longhand-properties": true,
    "csstools/use-logical": "always"
  }
}
```

Canonical modern reset and cascade-layer order (community consensus, not a spec — verify against the current reset source before shipping):

```css
@layer reset, tokens, components, utilities;

@layer reset {
  *, *::before, *::after { box-sizing: border-box; }
  * { margin: 0; }
  body { min-height: 100svh; line-height: 1.5; -webkit-font-smoothing: antialiased; }
  img, picture, video, canvas, svg { display: block; max-inline-size: 100%; }
  input, button, textarea, select { font: inherit; }
  h1, h2, h3, h4 { text-wrap: balance; }
  p { text-wrap: pretty; }          /* degrades gracefully where unsupported */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation-duration: .01ms !important;
      transition-duration: .01ms !important;
      scroll-behavior: auto !important;
    }
  }
}
```

Layer order = source of truth for the cascade: `reset` loses to `tokens`, which loses to `components`, which loses to `utilities` — regardless of selector specificity. Put third-party CSS in its own early layer so your styles win without `!important`.

## Testing / feature detection

CSS "tests" are feature detection and pixel diffs, not unit tests.

- **Gate every `Limited` feature** with `@supports (prop: value) { … }` and ship a working fallback outside the block. Never assume support.
- **`prefers-reduced-motion`** has a path on every animation (**accessibility-overhaul** owns that the path must exist; **motion-craft** owns the durations/easings).
- **Focus visibility and contrast are owned by accessibility-overhaul** — this skill only picks the modern *selector* (`:focus-visible`), not the ring's look or contrast ratio.
- Verify layout with a visual-regression snapshot at container widths, not just one viewport.

## Closing gate — pass before claiming "modern"

1. Zero entries from the idiom table's stale column remain in the diff.
2. No vendor prefixes on Baseline properties; autoprefixer not added for them.
3. No `!important` except the reduced-motion safety net; specificity handled by `@layer`/`:where()`.
4. Layout is grid/flex with `gap`; no floats-for-layout, no ratio-padding, no absolute-centering.
5. Every `Limited` feature is behind `@supports` with a working fallback.
6. Logical properties used wherever the UI can be localized/RTL.
7. Breakpoints are `rem`/container-based; components reflow via `@container`, not JS.
8. Every "needs JS" component was checked against the no-JS table first.

If any item fails, fix it before presenting. Do not narrate the checklist; just pass it.
