<!-- Source: vandan-llm-toolkit skills/framer-grade-sites/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Framer-Grade Sites

A page reads as agency-made because of how sections are *ordered, sized, and sequenced* — not because any single effect is fancy. This skill owns **composition**: choosing the archetype, laying sections in the canonical stack, sizing them to an agency rhythm, and deciding what animates on enter versus what stays still. It is the conductor; the ingredient skills are the instruments.

## Boundary — cite, never restate

This repo already holds the effect skills. Read the matching one's SKILL.md *before* you build that section, and pull its values verbatim — do not re-derive them here.

- **animated-backgrounds** owns every ambient scene (aurora, mesh, shader hero, particles, video background) and their budgets/fallbacks.
- **scroll-experiences** owns scroll mechanics (ScrollTrigger, Lenis, pinning, sticky-stacking, text reveals, view transitions).
- **web-3d-experiences** owns interactive foreground 3D (R3F, Spline, model-viewer).
- **motion-craft** owns motion tokens — every duration, easing, spring, stagger value. Reference by name; invent none.
- **ui-component-arsenal** owns acquiring/adapting components (bento cards, marquee, accordion, command menu).
- **vandan-ui-system** owns base tokens (color, type, spacing, radii), taste, product modes, and hard bans.

This skill owns only the layer none of them do: **assembling their output into a whole page.**

## Process — run every time

1. **Pick archetype + mood** from the decision table below. This sets the vandan-ui product mode, the dark/light lane, and the default hero.
2. **Assemble sections in the fixed order** from the Section archetype table — nav → hero → logo strip → bento features → product showcase → testimonials → pricing → FAQ → CTA band → mega-footer. Drop sections you lack content for; never reorder.
3. **Apply the choreography plan** — set each section's enter-vs-still behavior and enforce one spectacle per viewport (see page-choreography.md).
4. **Craft pass** — apply canonical rhythm values, pull effect code from the owning skill, wire motion via motion-craft tokens.
5. **Run the closing gate** before calling it done.

## Archetype + mood decision table

| Ask / product | vandan-ui mode | Mood | Default hero |
|---|---|---|---|
| Dark design-led SaaS / dev tool | Precision Tool / Product Marketing | dark canvas + one neon accent | gradient/shader scene |
| B2B SaaS with a real UI to sell | Product Marketing | dark or light | product screenshot |
| Fintech / service / early-stage (trust) | Product Marketing / Editorial | cream/warm light + serif accent | screenshot or illustration |
| Brand / lifestyle / agency | Editorial Premium | either; cinematic | muted video loop |
| Abstract or immersive product | Editorial / Product Marketing | dark | interactive 3D object |

If the ask names no product or audience, default to the Product Marketing (B2B SaaS) row, dark + one neon accent, product-screenshot hero — the worked example below — and confirm with the user.

Mood is audience-driven, not fashion: dark-neon signals techno-futurism; cream-warm-light signals trust. This tracks how leading design-led sites split in current practice.

## Section archetype table

Each row: purpose, composition recipe, which skill supplies the flash, what animates on enter vs stays still. Full per-section spec in [references/section-archetypes.md](references/section-archetypes.md).

| Section | Purpose | Composition recipe | Flash from | On enter / still |
|---|---|---|---|---|
| Nav | orient + one CTA | sticky blur bar or floating pill; logo · links · one accent button | ui-component-arsenal; glass from vandan-ui-system | collapses/shrinks on scroll · otherwise still |
| Hero | one claim + one visual | oversized clamp() headline, one italic-serif accent word, sub ≤60ch, dual CTA, one visual | see Hero table | headline word-reveal + visual entrance once · then still |
| Logo strip | social proof | grayscale "trusted by" auto-marquee | ui-component-arsenal marquee | ambient auto-scroll · no per-enter reveal |
| Bento features | scan value props | asymmetric 12-col grid, cards span uneven col/row | ui-component-arsenal bento | staggered card reveal by row · cards still after |
| Product showcase | show it working | screenshot/video in perspective frame, or sticky-stacking cards | scroll-experiences (pin/stack); animated-backgrounds (video) | scrubbed to scroll · frame stays pinned |
| Testimonials | trust | 2–3 quote cards or a calm marquee row | ui-component-arsenal | simple fade-up · still |
| Pricing | convert | 3 tiers, one highlighted, monthly/annual toggle | ui-component-arsenal | simple fade-up · fully still + legible |
| FAQ | remove doubt | accordion, single-open | ui-component-arsenal accordion | fade-up · panels expand on click only |
| CTA band | final ask | full-bleed band, one headline, one button | vandan-ui-system | subtle scale/fade in · button never ambient-animates |
| Mega-footer | navigate + close | 4–5 link columns + oversized wordmark row | vandan-ui-system | none / minimal · still |

## Agency-look canonical values (copy-paste)

These layout constants are this skill's own — the measurable "agency tell." Durations and easings themselves come from **motion-craft tokens**; the values below are rhythm, not motion curves.

```
--container-max: 1280px;        /* hold 1140–1280 even on >=1440 ultra-wide; never full-bleed body text */
--gutter: 16px mobile / 24px tablet / 32px desktop;
section padding-block: 32px mobile / 48px tablet / 96px desktop / 128px ultra-wide;
--space-scale: 8,16,24,32,40,48,64,96,128 (px, 8px rhythm);
Body: 16–18px, line-height 1.5–1.7, measure 70–80ch max;
Type scale ratio: 1.25 (minor third) → 1.333 (perfect fourth);
H1 practical 40–52px (44–56 ultra-wide); hero display clamp(3rem, 8vw, 7.5rem), letter-spacing -0.03em;
Type voices: exactly two — one tight sans everywhere + one italic-serif accent word;
Color budget: <=4 total — two surface tones + one accent (single accent across the whole page);
Grid stagger cadence: 0.08–0.12s between cards; fade-up rise 24–40px; ScrollTrigger start "top 80%".
```

Breakpoints: mobile <=599 / tablet 600–991 / desktop 992–1439 / ultra-wide >=1440. These rhythm figures reflect current agency-page practice; treat the confirmed spacing/max-width numbers as firm and the type-scale figures as strong defaults you may nudge per brand.

## Hero decision table

Pick one — ranked by prevalence in current agency/SaaS work. Implementation lives in the owning skill; only the perspective-frame transform below is this skill's composition value.

| Hero | When to use | Wow / cost | Owned by |
|---|---|---|---|
| Product screenshot in perspective frame | you have real UI to sell (B2B default) | high credibility / low | ui-component-arsenal + vandan-ui-system |
| Gradient / shader scene behind type | dark design-led brand, no strong product visual | high / low (CSS aurora) → med (WebGL) | animated-backgrounds |
| Muted cinematic video loop | brand/lifestyle, premium feel | high / med (bytes) | animated-backgrounds (video budget) |
| Interactive 3D object | abstract product or immersive hook | highest craft, trending down / highest cost | web-3d-experiences |

```css
/* perspective frame for a screenshot hero (composition-level) */
.hero__shot{transform:perspective(2000px) rotateX(28deg);border-radius:12px;box-shadow:0 40px 120px rgba(0,0,0,.5)}
```

## Page-level choreography rules

Detail and the reduced-motion plan in [references/page-choreography.md](references/page-choreography.md).

- **One spectacle per viewport.** A shader hero *or* a 3D object *or* a pinned scrub — never two competing in the same screenful. Everything else in that viewport is calm.
- **CTA never ambient-animates.** A button may enter once with its section, then it is still forever. Motion near the primary decision is noise.
- **Load order:** nav + hero above-the-fold entrance ≤900ms total (motion-craft budget); everything below the fold reveals on scroll, once, at `top 80%`.
- **Below-fold sections fade-up on enter; grids stagger by row, not per cell.** Pricing and FAQ stay fully still and legible — no heavy motion where a decision is made.
- **Ambient elements** (logo marquee, hero scene) loop; they never re-trigger on scroll.

## Hard bans

- **No two competing spectacles in one viewport.** Route the second to calm.
- **No scroll-jacking** — scroll-*driven* motion only (scroll-experiences / motion-craft rule).
- **No hero carousel** — one claim, one visual; rotating heroes bury the message.
- **No wall-of-badges** — social proof is a calm grayscale marquee, not a grid of 30 logos.
- **Content must read and navigate with all animation removed** — every reveal has a static end state; motion sequences meaning, never gates it.
- **No third type voice, no fifth color, no full-bleed body text** — cap the measure at 70–80ch.
- **Invent no tokens or curves here** — colors from vandan-ui-system, motion from motion-craft, scenes from animated-backgrounds.

## Worked example — SaaS landing build plan

Dark design-led B2B SaaS with a real product UI. Archetype: Product Marketing, dark + one neon accent, product-screenshot hero. Build plan (a plan, not full code — each row points at the owning skill):

| Section | Build | Ingredient skill | Enter behavior |
|---|---|---|---|
| Nav | floating pill, logo · 4 links · accent CTA; blur-collapse on scroll | ui-component-arsenal (pill) + vandan-ui-system (glass token) | shrink on scroll |
| Hero | clamp(3rem,8vw,7.5rem) headline, one italic-serif word, sub ≤60ch, dual CTA, screenshot in perspective frame; faint CSS aurora behind | animated-backgrounds (aurora) + motion-craft (word-stagger) | word-reveal + frame rise, once |
| Logo strip | 6 grayscale logos, auto-marquee, "Trusted by" | ui-component-arsenal marquee | ambient loop |
| Bento features | 12-col grid, 6 cards, 2 large + 4 small asymmetric | ui-component-arsenal bento | row-staggered reveal 0.08–0.12s |
| Product showcase | 3 UI cards sticky-stacking on a pinned runway | scroll-experiences (pin/stack) | scrubbed to scroll |
| Testimonials | 3 quote cards, one accent border | vandan-ui-system | fade-up |
| Pricing | 3 tiers, middle highlighted, annual toggle | ui-component-arsenal | fade-up, then still |
| FAQ | single-open accordion, 6 items | ui-component-arsenal accordion | fade-up |
| CTA band | full-bleed, one line, one accent button | vandan-ui-system | scale/fade once |
| Mega-footer | 5 columns + oversized wordmark row | vandan-ui-system | none |

Spectacle ledger: hero aurora (viewport 1) and the pinned showcase (mid-page) are the only two spectacles, and they never share a screen. Everything else is calm.

## Closing gate — confirm before done

- [ ] Archetype + mood picked; sections in the fixed order, none reordered.
- [ ] Container ≤1280px, section padding and 8px rhythm applied; body measure ≤80ch.
- [ ] Two type voices, ≤4 colors, single accent across the whole page.
- [ ] Each section's flash pulled from its owning skill (nothing re-derived here); motion via motion-craft tokens.
- [ ] One spectacle per viewport; CTA carries no ambient motion; below-fold reveals once at `top 80%`.
- [ ] Page fully readable and navigable with all animation removed (reduced-motion honored by every ingredient skill).
- [ ] No hero carousel, no wall-of-badges, no scroll-jacking, no competing spectacles.
