<!-- Source: vandan-llm-toolkit skills/site-architect/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Site Architect

Autonomous pipeline: brief → stack → direction → architecture → libraries → build → verify. The user gives intent ("make me a super cool portfolio"); this skill makes every technical and creative decision itself, from scaffold command to the last easing curve. Verdicts in `references/` were verified against npm/GitHub in July 2026 — trust them over training-data memory.

## Standalone taste — hard override

Never apply `vandan-ui-system`, `ultra-clean-native-ui`, `premium-software-brand-system`, `mobile-native-clean-components`, `premuium-dark-ui-taste`, or `app-transformer` taste rules while this skill runs — even if they also trigger, and even though other skills in this repo cite them. Their restrained product-UI system (fixed canvas ladder, one-accent minimalism, hard bans) contradicts per-project creative direction: an agency site may need cream + serif, a playground may need chromatic chaos. site-architect defines art direction itself in step 2, from the brief — not from a house system. The only shared inheritance is *quality* (a11y, reduced-motion, performance budgets), never *style*.

## Pipeline — run every step, in order

### 0 · BRIEF
Classify the project: **creative portfolio/agency site** | **product app** | **experimental playground**. Extract mood words from the user's language ("moody", "playful", "brutalist", "luxury"), inventory the content that exists (copy, images, data), and note hard constraints (SEO, CMS, auth). If the user gave a vibe example (a site, an effect like dangling letters), record it as the signature-moment candidate.

### 0.5 · DECODE
When the ask carries vibey/visual language the user can't quite name ("circular diagonal scroll", "magic laser tunnel", "photos blurring out" — any hard-to-name visual), don't guess and don't ship a literal word-match (a flat "carousel" for a construct that is not one). Read `references/imagination-lexicon.md` and decode the vibe to **named, buildable constructs**. Then:
- **Paraphrase back** to the user in concrete geometry words ("a cylinder gallery whose cards face the camera and rotate top-to-bottom while the row drifts left"), with **1-2 nearest alternates**, so they can correct the read before anything is built.
- Build a **<150-line single-file spike** of that signature moment alone — no full app — for approval.
- Only once the read is confirmed do you integrate the construct into the pipeline below.

Construct *implementation* code lives in `../web-alive/references/` (`gallery-3d`, `volumetric-magic`, `impossible-transitions`) — the lexicon names the construct, those chapters build it. Skip this step only when the ask is already in concrete, named terms.

### 1 · STACK
Read `references/stack-verdict.md` (decision matrix §7, full recipes §6) and choose. Condensed matrix:

| Project | Stack | Scaffold |
|---|---|---|
| Creative portfolio / agency / editorial | **Astro 7 + Tailwind v4 + GSAP + Lenis** (+ three/R3F island only if a section needs 3D) | `npm create astro@latest -- --template minimal --typescript strict` → `npx astro add tailwind` → `npm i gsap lenis` |
| Product app (SaaS, dashboard, tool) | **Next 16 + Tailwind v4 + shadcn/ui (Base UI default) + Motion** | `npx create-next-app@latest --ts --tailwind --app` → `npx shadcn@latest init` → `npm i motion` |
| Experimental / pure WebGL playground | **Vite 8 + vanilla TS + three + GSAP** | `npm create vite@latest -- --template vanilla-ts` → `npm i three gsap lenis` |
| Solo interactive one-pager | SvelteKit 2 / Svelte 5 runes + Tailwind v4 | see stack-verdict §7 |

Language is always TypeScript 7.x (native `tsgo` compiler GA since 2026-07); styling default Tailwind v4 (CSS-first `@theme`). If none of the rows fit, default to **Next 16 + shadcn (Base UI) + Motion on Vercel** per stack-verdict §9. Run the scaffold commands before writing any code.

### 2 · DIRECTION
Define art direction from the brief — never from a house design system:
- **Palette** derived from mood words (moody → near-black + one hot accent; luxury → cream/ink + serif; playful → saturated duotone). Pick 1 canvas, 2-3 surfaces, 1 accent, and stick to them.
- **Type pairing**: one display face with character (not Inter) + one workhorse. Display sizes clamp large (`clamp(3rem, 12vw, 10rem)` territory for heroes).
- **Motion-intensity dial 1-3**: 1 = product-calm (micro-interactions only), 2 = editorial (scroll reveals + one hero moment), 3 = full studio (preloader, WebGL, kinetic type). Product apps cap at 1-2.
- **One signature moment**: the single effect the site is remembered by (physics headline, shader hero, horizontal reel). Everything else supports it.

### 3 · ARCHITECT
Map routes/pages and their section stacks; write the component inventory (name, props, which library provides the base); folder structure per the chosen framework's recipe build-order; content/data model (markdown collections for Astro, server components + `use cache` for Next, none for playground).

### 4 · LIBRARIES
Pick per need from the references, pinning the versions they list — never improvise a dependency:

| Need | Read |
|---|---|
| Timeline/scroll choreography, kinetic type engine | `references/animation-engines.md` (GSAP roster vs Motion vs anime v4) |
| Physics — dangling/hanging letters, ropes, collisions | `references/physics-text.md` (Matter.js chandelier demo; Rapier when serious) |
| 3D, shaders, particles, designer embeds | `references/webgl-3d.md` (three/R3F+drei, OGL, Pixi, Rive/Spline costs) |
| Product-UI components, animated component sources | `references/component-libs.md` (shadcn+Base UI; raid Aceternity/Magic UI/ReactBits selectively) |
| Smooth scroll, sliders, page transitions, DnD, popovers | `references/scroll-interaction.md` (Lenis, Embla, swup vs View Transitions, dnd-kit, floating-ui) |
| Garnish — globes, confetti, fluid cursors, number tickers, audio | `references/wildcards.md` |

Budget check before installing: creative site ≤ ~250KB JS gzip (three counts ~150KB alone — one 3D island max), product app ≤ ~300KB first load, playground unbounded but DPR-clamped. Reject any library the references flag "legacy — avoid for new work".

### 5 · BUILD — fixed order
scaffold → **tokens** (palette/type/space as `@theme` or CSS vars, from step 2) → **layout shell** (nav, grid, footer) → **sections/content** (real copy first, placeholders read as slop) → **motion layer** → **micro-interactions** → **one wildcard garnish max**.

For the motion layer, implement from `../web-alive/references/` (the effect chapters: kinetic-text, grain-noise, cursors, scroll-storytelling, infinite-loops, overlay-menus, webgl-backgrounds, transitions-preloaders). Its quality layer is mandatory reading before writing any motion code: `motion-taste.md` (every duration/easing/stagger value comes from its tables), `choreography.md` (sequencing laws — nothing animates simultaneously unless related), `anti-patterns.md` (the 18 failures). Micro-interactions come from `../web-alive/references/micro-interactions.md`; scroll pacing from `scroll-rhythm.md`.

### 6 · VERIFY
Run the app and drive it: every route, every effect. Then gate on: web-alive `anti-patterns.md` lint pass over all motion code; `prefers-reduced-motion` emulation shows a complete, calm site; keyboard-only nav works (menus trap + return focus, `inert` background); console clean; LCP within budget (preloader ≤1.5s and tied to real loading, if one exists); resize + DPR clamp on any canvas; `tsc` clean. Fix and re-verify before declaring done.

## Reference index

| File | Contents | Read when |
|---|---|---|
| `references/imagination-lexicon.md` | Vibe-language → named 3D/WebGL constructs: the disambiguation lexicon + paraphrase-back protocol (construct *code* lives in `../web-alive/references/` `gallery-3d`, `volumetric-magic`, `impossible-transitions`) | Step 0.5, any hard-to-name visual ask |
| `references/stack-verdict.md` | Framework/styling/language verdicts, 3 full recipes with scaffold commands + build order, decision matrix, Framer boundary | Step 1, always |
| `references/animation-engines.md` | GSAP free-plugin roster, Motion, anime v4, WAAPI, dead-lib flags | Step 4, any animation |
| `references/physics-text.md` | Matter.js dangling-letters demo, Rapier/cannon-es, text-effect libs vs hand-code | Physics or playful-text asks |
| `references/webgl-3d.md` | three/R3F/drei/OGL/Pixi verdicts, background options ranked by cost | Any 3D/shader/particles |
| `references/component-libs.md` | shadcn (Base UI default), Aceternity/Magic UI/ReactBits taste verdicts, primitives | Product apps; component raids |
| `references/scroll-interaction.md` | Lenis, sliders (Embla verdict), swup vs View Transitions, dnd-kit, floating-ui | Scroll/slider/transition/DnD |
| `references/wildcards.md` | 2025-26 new & underrated, ranked garnish picks | Step 5 garnish; novelty asks |

Effect *implementation* (runnable snippets, a11y wiring, measured taste values) lives in `../web-alive/references/` — this skill's references decide *which* library; web-alive's decide *how it moves*.

## Precedence

If `framer-grade-sites` also triggers: site-architect wins when the user wants stack choice + a full autonomous build; framer-grade-sites remains the guide for pure composition questions on an already-chosen stack (and note its section-stack tables cite vandan-ui modes — those citations are void while site-architect runs; the standalone-taste clause above governs).
