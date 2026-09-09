<!-- Source: vandan-llm-toolkit skills/collectible-card-ui/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Collectible Card UI

The toolkit for interfaces where **the card is the product** — trading cards, graded slabs, digital packs, collectible tiles — calibrated for a welcoming collectors' hub, not a casino. Every value here is exact and brand-neutral: the motion, blend, and gradient recipes produce the same result no matter which model runs them. Copy values verbatim, never "similar" hexes or curves — pasting the canonical blocks below is how lower-capability models get frontier output.

The canonical open-source reference is **simeydotme/pokemon-cards-css** (the "poke-holo" architecture). The platform patterns are distilled from NYT Games and Puzzmo pacing plus collectibles marketplaces (Whatnot, Alt, Arena Club, Courtyard, PSA, eBay) — named as exemplars, never as trade dress to clone.


## Process — run this every time

1. **Set the card baseline.** Trading-card aspect ratio is `aspect-ratio: 5/7` (2.5"×3.5"). Wrong ratio is the fastest tell that something is "not a real card." Slabs are wider (~3.3"×5.4") with a label band adding ~20% height.
2. **Pick the finish by rarity, not by taste.** Effect *intensity* is the rarity signal — see the tier table. A common card gets a sheen sweep; a grail gets the full holo stack.
3. **Wire the pointer pipeline once.** JS writes custom properties (`--pointer-x/y`, `--rotate-x/y`, `--background-x/y`, `--pointer-from-center`, `--card-opacity`); every visual layer is pure CSS reading them. Never animate layers from JS or React state.
4. **Read the recipe reference right before applying it**, not all files upfront. Paste the exact block, adjust only the documented knobs.
5. **Gate for touch, motion, and blend safety** before shipping — see Hard bans and the Output contract.
6. **Run the Final audit.** Every item must pass before claiming done.


## What this skill owns

The pointer custom-property pipeline · holo, foil, glitter, and glare layers · 3D tilt with spring-back · hover and one-shot sheen · the rarity-tier gradient system and its escalation language · card anatomy, tier badges, and serial stamps · collector vocabulary · and the perf/a11y gates for these effects (GPU budget, touch, `prefers-reduced-motion`).

**Composition:** if `motion-craft` is available it owns spring physics and 60fps rules; if `vandan-ui-system` is available it owns base surfaces, type, and neutral tokens (cards sit on its canvas). Reference them, don't restate. If neither is present, this skill is standalone — use the canonical values below as-is.


## Rarity tiers — the escalation language

Encode rarity **three redundant ways**: gem color (newbie legibility), foil finish (the premium feel), and a fake print-run stamp (veteran authenticity). Intensity escalates down the table.

| Tier | Gem accent | Finish | Stamp | Motion |
|---|---|---|---|---|
| **Base** | gray `#9aa0a6` | flat surface | none | sheen on hover |
| **Refractor** | blue `#0070dd` | silver refractor rainbow (soft-light) | `/99` | sheen + subtle glare |
| **Numbered** | purple `#a335ee` | gold foil, near-white specular stop | `/25`, `/10` | glare + static holo |
| **Grail / 1-of-1** | gold `#ff8000` | black relic + gold rim, full holo stack | `1/1` in gold | tilt + animated foil |

The hue ramp (gray → blue → purple → orange/gold) is the WoW/Hearthstone convention — keep it for rings, glows, and labels only; the *surface finish* carries the premium feel. Face-down cards **glow in their tier color on hover** before flipping. Full escalation copy and stamp recipes: rarity-and-vocab.md.


## Effect recipes

Read each reference **right before applying it** — paste the exact block, tune only the noted knobs.

- [references/effects.md](references/effects.md) — the full CSS/React pipeline: pointer handler, tilt, rainbow shine, glare, glitter, static finishes, sheen sweep. Read when building any card visual effect.
- [references/card-anatomy.md](references/card-anatomy.md) — card anatomy, slab layout, tier badges, density/typography. Read when laying out a card/slab or a collection screen.
- [references/rarity-and-vocab.md](references/rarity-and-vocab.md) — rarity escalation, serial stamps, the collector glossary, and the top transferable patterns. Read when writing product copy or encoding rarity.

The one non-composited technique is **animated `background-position` on the foil layer** — it repaints every frame. Budget it to one hero card; everything else is transform/opacity and GPU-cheap.


## Canonical values

Copy these verbatim. They are brand-neutral (motion and blend physics, not identity) and behave identically in light and dark when `isolation: isolate` is set on the card.

```css
/* tilt spring-back return curve — reads as a spring, no library */
--ease-card-spring: cubic-bezier(0.03, 0.98, 0.52, 0.99);
/* pointer pipeline (JS writes these; CSS layers read them) */
--pointer-x: 50%;  --pointer-y: 50%;     /* cursor % within card */
--rotate-x: 0deg;  --rotate-y: 0deg;     /* damped, ~±14deg max */
--background-x: 50%; --background-y: 50%;/* foil position, moves against pointer */
--pointer-from-center: 0;                /* 0..1 Euclidean, drives glitter/scale */
--card-opacity: 0;                       /* glare fade in on hover, out on leave */
```

```css
/* effect constants — apply these exact values in the recipe blocks */
/* perspective:           600px                                              */
/* tilt transition:       400ms var(--ease-card-spring)                      */
/* sheen sweep:           600ms ease (one-shot for "new pull!")              */
/* shine background-size: 400% 400%                                          */
/* shine blend:           color-dodge; filter: brightness(.85) contrast(2.75) saturate(.65) */
/* glare blend:           overlay (survives light theme; color-dodge does not) */
/* foil aspect:           5 / 7   (slab: ~3.3/5.4)                           */
```

Exact gradient stops for refractor, gold, and relic finishes are in effects.md — do not eyeball them.


## Hard bans

- **No animating layers from JS or React state.** State updates per `pointermove` guarantee jank. Write `el.style.setProperty` inside `requestAnimationFrame` via a ref.
- **No `color-dodge` on a glare layer over light backgrounds** — it blows out. Glare uses `overlay`; only shine/glitter use `color-dodge`, and only over card art.
- **No card using `mix-blend-mode` without `isolation: isolate` on its wrapper** — the blend will composite against the page and break light/dark. This one line is the theme-safety mechanism.
- **No animated foil across a grid.** The per-frame repaint is for one hero card only, never twelve.
- **No body text on a foil layer.** Foil is decoration behind or beside text plates; gold finishes pin dark text explicitly.
- **No tilt or sheen on touch devices.** Gate hover effects behind `@media (hover: hover) and (pointer: fine)` and gate the JS handler behind `matchMedia`, or touch users strand mid-tilt.
- **No spatial motion under `prefers-reduced-motion: reduce`** — kill tilt, sheen sweep, and celebration keyframes; keep static foil gradients and glare-at-rest (color is safe, motion is the vestibular trigger).
- **No wrong aspect ratio, and no cloning a real marketplace's trade dress** (its exact refractor-as-chrome, wordmark, or heritage frames). Use the generic patterns, not the brand.
- **No unglossed jargon on a newcomer hub.** Use the lexicon *with* one-line tooltips — see the glossary.


## Final audit — run before presenting

1. Card renders at `aspect-ratio: 5/7` (slab at ~3.3/5.4)?
2. Rarity encoded three ways — gem color, finish, stamp — with intensity matching the tier table?
3. Pointer pipeline writes custom properties via a rAF ref, never React state?
4. `isolation: isolate` on every card that uses a blend mode?
5. Glare uses `overlay`; only shine/glitter use `color-dodge`, and only over art?
6. Animated foil limited to one hero card; `will-change: transform` only on the hovered card?
7. Hover effects gated behind `(hover: hover) and (pointer: fine)`; JS handler behind `matchMedia`?
8. `prefers-reduced-motion` kills spatial motion but keeps static color?
9. No body text on any foil layer; gold finishes pin dark text?
10. Collector copy uses the real lexicon with teach-on-hover tooltips; no incumbent trade dress?

If any answer is no, revise before presenting. Do not narrate the checklist to the user; just pass it.
