<!-- Source: vandan-llm-toolkit skills/scroll-experiences/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Scroll Experiences

Scroll and navigation are the story's spine. When the *narrative structure itself* is expressed through scroll position, page hand-offs, and choreographed text — a graphic that pins while captions step past, a card that morphs into the next page's hero — that is this skill. The discipline: **the content is legible and navigable without any of it; motion sequences meaning, it does not gate it.** Every route renders real HTML per URL, every reveal has a static end state, every hijack of native scroll or cursor is a debt you must justify.

## Boundary — read first

This skill owns **scroll/transition experiences that structure content**: scrollytelling, page/route transitions, text-reveal choreography, kinetic type, custom cursors and magnetic elements, preloaders. It does **not** own:

- **Ambient scroll-scrubbed scenery** — a WebGL hero, particle field, mesh gradient, or decorative image-sequence scrub *behind* content is **skills/animated-backgrounds**. If the effect is atmosphere you could delete without losing the message, it lives there; it also holds the ScrollTrigger pin+scrub *basics* and IntersectionObserver reveal — this skill is the advanced orchestration on top.
- **Motion tokens and the reduced-motion policy baseline** — durations, easings, springs, and the "every pattern needs a reduced-motion path" rule are **skills/motion-craft**; pull curve values from its `tokens.md`, do not invent new ones here.
- **Surfaces, type, spacing, color** — **skills/vandan-ui-system**. Never invent design tokens.

Route "animate this background as I scroll" to animated-backgrounds; keep "tell a story / move between pages / reveal this headline" here.

## Process — run every time

1. **Classify the job** against the decision table below; pick the cheapest tool that hits it. A CSS reveal does not need GSAP; a crossfade between routes does not need a library.
2. **Copy versions and constants from Canonical values** — never guess a package version, support gate, lerp, or magnetic strength.
3. **Author the no-motion baseline first.** Real HTML per route, content visible without JS, headline present without the reveal, cursor native. The effect is an upgrade over a working page.
4. **Load the one matching reference** just before you build — do not read all three upfront.
5. **Gate every effect**: `prefers-reduced-motion`, `@supports`/feature-detect for platform APIs, `(pointer:fine)` for cursors, and offscreen/`visibilitychange` pause for any rAF loop.
6. **Run the Output contract** before claiming done.

## Decision table — pick the tool by the need

| Need | Reach for | Tier |
| --- | --- | --- |
| Reveal-on-enter, progress bar, sticky reveal, no JS | Native CSS `animation-timeline: view()`/`scroll()` behind `@supports` | css |
| Panel deck / carousel snapping, JS-free | CSS `scroll-snap` + `scrollsnapchange` events | css |
| Stepped editorial narrative, discrete state per beat | Scrollama (IntersectionObserver) sticky-graphic + steps | js-light |
| Continuously scrubbed pinned scene, snap-to-beat, horizontal-in-vertical | GSAP ScrollTrigger (numeric `scrub`, `snap`, `containerAnimation`, `batch`) | gsap |
| Expensive "glide" over the whole page | Lenis + GSAP single-ticker wiring | gsap |
| React component reveal / parallax / sticky zoom, framework-idiomatic | Motion `useScroll` + `useTransform` (+ `useSpring`) | motion |
| Shared-element morph within one component (grid→detail in place) | Motion `layout` / `layoutId` | motion |
| Route→route crossfade or shared-element morph, same origin | View Transitions API (same-doc SPA, cross-doc MPA `@view-transition`) | platform |
| JS-driven MPA needing Firefox/Safari parity or a persistent WebGL canvas | swup (`+@swup/js-plugin`) or legacy barba, GSAP `clip-path` curtain | js |
| Cinematic headline / title reveal | GSAP SplitText 3.13 (`mask`, `autoSplit`, `onSplit`) | gsap |
| Weight/width type animation on scroll | CSS scroll-driven `font-variation-settings` | css |
| First-visit intro | Preloader timeline, skippable, `sessionStorage`-gated | gsap/js |

## Hard bans

- **No scroll-jacking.** Scroll-*driven* (progress-linked) motion is fine; fighting the user's scroll speed, direction, or position is not. Lenis smoothing is the ceiling; never a fake transformed scroll container (breaks sticky, anchors, focus).
- **No custom cursor on touch or coarse pointers, ever.** Gate to `(hover:hover) and (pointer:fine)`; never hide the OS cursor otherwise — replacing it overrides an assistive accommodation.
- **No magnetic target that dodges a deliberate click.** Cap displacement; keep hit-targets ≥24×24px.
- **No content gated behind a transition or preloader.** DOM renders underneath; the overlay is decoration; SEO content never waits. Preloader ≤~1.5s, skippable, first-visit only.
- **No transition/reveal without a `prefers-reduced-motion` path** — the DOM swap/reveal still happens, only the animation is suppressed.
- **No two elements sharing one `view-transition-name` at snapshot time** — it silently skips the whole transition. Set names imperatively in `pageswap`/`pagereveal`, clear after `finished`/`ready`.
- **No new tween per `pointermove`/scroll event.** Use `gsap.quickTo`/`quickSetter` or write a CSS custom property inside one rAF loop via a ref.
- **No essential info only in a marquee or hover preview** — both are invisible to keyboard/touch and must be pausable (WCAG 2.2.2).
- **No pin/snap on `containerAnimation` triggers** — unavailable there; apply them to the outer vertical trigger.

## Canonical values (copy-paste)

- **GSAP `3.13.0`** (2025-04-29) — 100% free incl. SplitText/MorphSVG/ScrollSmoother/ScrollTrigger/Flip/ScrambleText. `npm i gsap`; import from `gsap/ScrollTrigger`, `gsap/SplitText`. No token, no Club registry. ~23KB gzip, modular.
- **Lenis `1.3.25`** — `lenis` + `lenis/react` (`ReactLenis`), ~2KB. `lerp: 0.1`, `duration: 1.2`, `syncTouch: false`, `autoRaf: false` when driven from `gsap.ticker`. Wire: `lenis.on('scroll', ScrollTrigger.update)`; `gsap.ticker.add(t => lenis.raf(t*1000))`; `gsap.ticker.lagSmoothing(0)`. The `t*1000` (s→ms) is load-bearing.
- **Motion `12.42.2`** (ex-`framer-motion`) — import `motion/react`. ~32KB, **not** tree-shakeable. Wrap in `<MotionConfig reducedMotion="user">`. No native pinning — use `position:sticky` or GSAP.
- **Numeric scrub:** `0.5–1` standalone; **`0.1–0.3` with Lenis** (don't double-smooth into mush).
- **Support gates:** CSS scroll-driven — Chrome/Edge 115+, Safari 18+, Firefox flagged → `@supports (animation-timeline: view())`. View Transitions same-doc — 111+/18+/144+ (Baseline); cross-doc MPA — Chrome/Edge 126+, Safari 18.2+, Firefox flagged (progressive only). `scrollsnapchange` — Chrome 129+. `@property` integer counter — Chromium only (ship JS fallback).
- **Cursor/magnetic:** follow lerp `0.12–0.15`; magnetic strength `0.35` (0.2–0.4); spring home `elastic.out(1, 0.3)`.
- **SplitText:** `mask:"lines"`, `yPercent:100→0`, `duration 0.6–0.8`, `stagger 0.1–0.12`; split lines not chars for body; wait `document.fonts.ready` or set `autoSplit:true`.
- **Marquee:** duplicate once + `aria-hidden="true"`; `translateX(calc(-100% - var(--gap)))`; pause on `:hover`/`:focus-within`.

## Reference files — load the matching one just in time

- [references/scrollytelling.md](references/scrollytelling.md) — Lenis + ScrollTrigger single-ticker wiring, numeric scrub + velocity-aware snap, `batch()` grid reveals, `containerAnimation` horizontal-in-vertical, native CSS scroll-driven + scroll-snap events, Scrollama sticky-graphic/stepped-text structure, Motion `useScroll`/`useTransform`/`layoutId`. Read before any scroll-narrative work.
- [references/transitions-and-cursors.md](references/transitions-and-cursors.md) — View Transitions same-doc (`match-element`, `view-transition-class`, transition types) and cross-doc MPA (`pageswap`/`pagereveal` dynamic names), swup/barba `clip-path` curtain, preloader choreography, custom cursor + magnetic elements + the usability gates, link-hover inventions. Read before any page-transition or cursor work.
- [references/text-effects.md](references/text-effects.md) — SplitText 3.13 masked line/word reveal, text scramble/decode, scroll-driven variable-font kinetic type, accessible infinite marquee, number/odometer counters. Read before any text-choreography work.

## Output contract

Confirm every line before calling it done:

- [ ] Cheapest viable tool from the decision table; no library added for a job CSS/platform does.
- [ ] Real HTML per route; content visible and navigable with JS and motion disabled.
- [ ] Exact versions/gates from Canonical values used verbatim; no guessed version or support claim.
- [ ] `prefers-reduced-motion` handled on every pattern (DOM swap/reveal still happens; animation suppressed).
- [ ] Platform APIs feature-detected (`@supports`, `startViewTransition`) and degrade to a plain navigation.
- [ ] Custom cursor gated to `(hover:hover) and (pointer:fine)`; never hidden on touch; `:focus-visible` intact.
- [ ] No new tween per pointer/scroll event; `quickTo`/rAF-via-ref only; rAF loops pause offscreen.
- [ ] `view-transition-name`s unique per snapshot (imperative set/clear for lists); shared names match on both pages.
- [ ] Preloader skippable, ≤1.5s, first-visit only, content rendered underneath.
- [ ] Marquees/hover previews pausable, `aria-hidden` duplicates, never the sole carrier of information.
- [ ] Curves from motion-craft; tokens from vandan-ui-system; ambient background scroll deferred to animated-backgrounds.
