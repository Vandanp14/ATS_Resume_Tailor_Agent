<!-- Source: vandan-llm-toolkit skills/web-alive/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# web-alive — Motion & Effects Transformer

Hand-coded implementations of the effects that make creative-studio and Awwwards-tier sites feel alive instead of static. Every technique here was reverse-engineered from a crawl of 30+ real production sites (Cuberto, Lusion, Locomotive, Unseen, Exo Ape, Dennis Snellenberg, and more) — the library choices, timing curves, and accessibility wiring reflect what those sites actually ship, not folklore. Every reference file contains complete, runnable, single-file snippets ready to paste and adapt — no pseudocode anywhere. v1.5 adds the quality layer — measured timing/easing values, choreography laws, and an anti-pattern lint so output matches award-tier taste, not just award-tier techniques.

This skill does NOT restyle. It animates. Colors, typography, spacing, and surfaces are the job of `vandan-ui-system` / `app-transformer`; this skill adds the motion layer on top of whatever visual system exists.

## The Full Transform

Use this workflow when the ask is broad — "transform this website 100%", "make it feel alive", "it looks static". For a single specific effect ("add a custom cursor"), skip to Step 3 and read only that one reference file.

### Step 1 — AUDIT (never skip)

Inventory before touching anything:

- **Sections present**: hero, nav, testimonials/logos, project/feature grid, long-form content, footer.
- **Stack**: vanilla / React / Next.js / Vite / Astro; SSR or not; existing animation libraries already loaded (don't ship GSAP twice).
- **Existing motion**: what already animates, what's broken, what's AI-slop (purple gradient blobs, random fade-ins on everything).
- **Content shape**: fixed strings vs CMS-driven (this decides CSS-only vs JS variants later).

Write the inventory down (a short list in your response or a scratch note). The selection step maps directly onto it.

### Step 2 — SELECT

Pick effects per section using the table below. Two rules that separate premium from noise:

- **Dosage**: ONE dominant motion moment per screen. Everything else is supporting (subtle, short, low-amplitude). A page where everything moves reads as a template demo, not a crafted site.
- **Meaning**: motion must carry information — guide the eye, reveal hierarchy, acknowledge input. If an effect exists only to decorate, cut it.

| Section / goal | Recommended effect(s) | Reference |
|---|---|---|
| Hero headline | Split-char stagger reveal, or line-mask reveal for multi-line | `references/kinetic-text.md` |
| Hero tagline / claim | Typewriter + cycling statement (blinking caret) | `references/kinetic-text.md` |
| Hero backdrop | Grain/noise overlay on moody photo (cheap, huge payoff) | `references/grain-noise.md` |
| Hero backdrop (bigger budget) | Animated noise shader or particle field | `references/webgl-backgrounds.md` |
| Whole-page feel | Lenis smooth scroll + scroll-linked reveals | `references/scroll-storytelling.md` |
| Portfolio / project showcase | Horizontal-scroll section or pinned scrubbed panel | `references/scroll-storytelling.md` |
| Social proof | Testimonial card marquee; logo ticker | `references/infinite-loops.md` |
| Oversized statement / brand word | Marquee headline, scroll-scaled display type | `references/kinetic-text.md` |
| Navigation | Full-screen overlay menu (clip-path bloom or curtain) | `references/overlay-menus.md` |
| Pointer feel (desktop) | Custom cursor dot+ring; magnetic CTA; image trail on galleries | `references/cursors.md` |
| Site entry | Preloader counter + curtain lift + hero choreography | `references/transitions-preloaders.md` |
| Between pages | Native View Transitions; curtain wipe as fallback | `references/transitions-preloaders.md` |

### Step 3 — IMPLEMENT

- Read ONLY the reference files for the selected effects (plus the quality-layer chapters, which are always read). Each file is self-contained; loading every chapter wastes context.
- Never improvise durations, easings, staggers, or travel distances — take them from the `references/motion-taste.md` tables. Choreograph sequences per `references/choreography.md`; elements never animate simultaneously unless related.
- Adapt snippets to the project's stack. Every reference carries React/Next deltas where the implementation meaningfully differs (useGSAP cleanup, SSR guards, rAF cancellation in effects).
- Pin the CDN versions exactly as given in the references — they were verified live. Don't guess newer paths.
- Where the reference offers a CSS-only variant, prefer it unless the JS variant buys something the project actually needs (dynamic content, velocity reactivity, cross-browser parity).

### Step 4 — VERIFY (never skip)

- Run the site and exercise every added effect by hand.
- Run the anti-patterns lint pass from `references/anti-patterns.md` over every file you touched; fix all hits before declaring done.
- Walk the Non-negotiables checklist below for each effect.
- Emulate `prefers-reduced-motion: reduce` (DevTools → Rendering) and confirm every effect degrades to a static, fully-readable state.
- Keyboard-test any overlay menu: Tab stays trapped, Esc closes, focus returns to the trigger.
- Check the console for errors and watch for layout shift while scrolling.

## Library decision rules (from the crawl)

These reflect what production award sites actually use — don't relitigate per project:

- **Kinetic text / scroll choreography**: GSAP + SplitText + ScrollTrigger. GSAP and ALL its plugins are 100% free since v3.13 (Webflow acquisition) — no license key, no trial build. CDN: `https://cdn.jsdelivr.net/npm/gsap@3.13.0/dist/gsap.min.js` (+ `SplitText.min.js`, `ScrollTrigger.min.js`, `ScrambleTextPlugin.min.js` at the same path).
- **Smooth scroll**: Lenis — package is `lenis@1.3.25` (renamed from `@studio-freight/lenis`; old name is stale). Drive it from GSAP's ticker, never a second rAF loop.
- **Cursors, overlay menus, grain, marquees, preloaders**: NO library. Production sites hand-roll all of these; the references show how in <100 lines each.
- **3D**: three.js `0.185.1` (~86 KB gzip official min build) — only when a real 3D moment is wanted, never as default decoration. Replace Spline embeds (~634 KB gzip runtime) with raw three.js when the scene is decorative.
- **Page transitions**: native View Transitions API first, feature-detected (`@view-transition` / `document.startViewTransition`), with instant navigation as the natural fallback. If a JS transition router is genuinely needed, pick swup (actively maintained) over barba (legacy).
- **Pure CSS beats JS** whenever the reference offers a CSS-only variant and the extra JS buys nothing — logo tickers, simple reveals, grain, marquee headlines are all CSS-first.

## Non-negotiables checklist

These are what separate crafted motion from liability. Every one exists because skipping it visibly breaks real users:

- [ ] Every effect has a `prefers-reduced-motion: reduce` branch that lands on a static, complete state (vestibular safety; also the no-JS state).
- [ ] Split text: readable sentence on the container via `aria-label`, generated spans `aria-hidden="true"` (screen readers must not hear letter salad).
- [ ] Split AFTER `document.fonts.ready` (splitting against fallback-font metrics re-wraps on FOUT and letters jump).
- [ ] Cursor effects gated behind `@media (pointer: fine)` / matchMedia; never `cursor: none` without a drawn replacement; nothing cursor-related on touch.
- [ ] Animate `transform` and `opacity` only — never top/left/width/margin (compositor vs layout).
- [ ] Marquee duplicate copies carry `aria-hidden="true"` (content must not be announced twice) and reduced-motion collapses to a static wrapped list.
- [ ] Overlay menu ships the full contract: `aria-expanded`, Esc closes, focus moves in and RETURNS to trigger, Tab focus trap, `inert` on background, body scroll-lock.
- [ ] Preloader: under ~1.5 s, tied to real loading (`document.fonts.ready`, image `decode()`), `sessionStorage` guard so it plays once per session. A preloader measuring nothing is a splash screen delaying LCP.
- [ ] Canvas/WebGL: cap `devicePixelRatio` at 2; handle `webglcontextlost`; pause the rAF loop on `visibilitychange` (battery).
- [ ] One rAF loop per concern; cancel it on unmount/cleanup in React.

## Reference index

### Quality layer — read BEFORE writing any motion code, regardless of effect

| File | Contents |
|---|---|
| `references/motion-taste.md` | The numbers: easings, durations, staggers, amplitudes |
| `references/anti-patterns.md` | 18 detect→fix failures + 10-line lint pass |
| `references/choreography.md` | Sequencing laws + 3 complete timelines |

### Per-effect chapters — read only for selected effects

Each file is self-contained with runnable snippets, CSS-only alternatives, perf/a11y caveats, and React/Next deltas.

| File | Contents | Read when |
|---|---|---|
| `references/kinetic-text.md` | 7 techniques: split-stagger, scramble, typewriter/cycling, marquee headline, cursor-reactive variable font, scroll-scrubbed type, line-mask reveal | Any text animation |
| `references/grain-noise.md` | 4: static feTurbulence hero recipe, steps() animated grain, canvas 12fps grain, body::after utility | Texture/film look |
| `references/cursors.md` | 4: dot+ring lerp cursor, magnetic button, image trail, blend-mode spotlight | Pointer feel |
| `references/scroll-storytelling.md` | 5: Lenis+ScrollTrigger setup, pinned scrub, horizontal scroll, native CSS scroll()/view(), canvas image sequence | Scroll behavior |
| `references/infinite-loops.md` | 3: CSS logo ticker, testimonial card marquee, rAF velocity marquee | Logos/testimonials |
| `references/overlay-menus.md` | 2: no-library clip-path menu with full a11y, GSAP curtain timeline | Navigation |
| `references/webgl-backgrounds.md` | 4 + R3F note: noise shader, particle field, Spline replacement, Rive | 3D/shader moments |
| `references/transitions-preloaders.md` | 4: MPA View Transitions, startViewTransition, curtain wipe, preloader counter | Entry/navigation |
| `references/micro-interactions.md` | Hover/press/focus motion with values read from Linear/Vercel/Stripe CSS | Any hover/press/focus work |
| `references/scroll-rhythm.md` | Pacing motion across a full page: density, rest, variation rules | Any scroll-triggered work |
| `references/live-deconstructions.md` | Measured timing values from real award-tier sites | When unsure a value is right |

### Product showcase (Apple/Uber-class) — read for product/marketing pages with a signature hero

| File | Contents | Read when |
|---|---|---|
| `references/apple-teardown.md` | Live-deconstruction evidence: how Apple really builds its scrub heroes (pinned canvas, image-sequence payloads, codec byte-probes) | Apple-style product page |
| `references/video-scrub.md` | Scrubbed video vs image-sequence engineering — frame-for-pixel locking, ffmpeg all-intra encoding, payload math | Scroll-scrubbed video / image sequence on scroll |
| `references/showcase-patterns.md` | Cross-site pattern intelligence: how Uber, Stripe, Tesla-class sites do scroll storytelling beyond Apple's playbook | Non-Apple product/marketing showcase |
| `references/product-scenes.md` | 3 complete self-contained scene recipes (single-file, procedural media, reduced-motion paths) | Building a full showcase composition |

### Imagination constructs (3D/WebGL) — read for "impossible"/vibe-driven visuals

| File | Contents | Read when |
|---|---|---|
| `references/gallery-3d.md` | Cylinder / helix / orbit galleries ("carousels that are not carousels") + depth-of-field blur | 3D gallery / carousel / tunnel |
| `references/volumetric-magic.md` | Volumetric constructs: tunnels, energy beams, liquid light | Magic/volumetric hero moments |
| `references/impossible-transitions.md` | Scene-to-scene magic: dissolves, portals, metaballs, velocity morphs | Shader transition / portal effect |

## Composing with other skills

When the ask includes a full visual redesign ("make it premium" covering look AND feel): run `vandan-ui-system` / `app-transformer` first for surfaces, typography, and layout, then web-alive for the motion layer. Motion applied to a weak visual system amplifies the weakness — get the static frame right, then bring it alive.
