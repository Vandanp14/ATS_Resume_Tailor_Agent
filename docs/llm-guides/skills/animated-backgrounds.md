<!-- Source: vandan-llm-toolkit skills/animated-backgrounds/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Animated Backgrounds

The ambient layer sells the product. A living background signals craft before a word is read — but it is scenery, never the show. **The background animates; the content stays legible; the CTA stays still.** Motion behind the fold is atmosphere; motion near the headline or button is noise that steals the one decision the page exists to win. Every technique here is decoration behind real DOM content, `pointer-events:none`, gated so it never taxes a device that cannot pay.

This skill owns the **ambient/scene layer**: full-bleed backgrounds, hero spectacle, scroll cinematics, campaign motion. It does **not** own micro-interaction/transition tokens or the reduced-motion policy baseline — **skills/motion-craft owns those; cite it, do not restate.** The core discipline: **pick the cheapest technique that hits the look, prove the budget, then build the fallback before the effect.** Cost climbs `css < canvas < webgl < video-bytes`. Reach for WebGL only when a shader, per-vertex displacement, or GPU-scale particles are truly required — most "Stripe-grade" gradients are a CSS aurora or tiny canvas mesh away.


## Operating rules

1. **Pick by the decision table below.** Start at the cheapest tier that hits the brief. Do not open a WebGL context for a look a CSS aurora delivers.
2. **Run the budget check before writing the effect.** Confirm the Canonical values below (DPR cap, particle count, octaves, bundle ceiling, byte budget). If the design exceeds them, downscale the design, not the budget.
3. **Build the fallback pass first.** Every scene ships three states: full effect, `prefers-reduced-motion` static frame, and capability degrade (no-WebGL / Save-Data / low-memory / no-JS). Author content visible; hide it only under a `.js` class so a script failure never blanks the page.
4. **Cull relentlessly.** Pause every rAF/GL/video loop on `visibilitychange` and via `IntersectionObserver` offscreen. A loop burning a core behind a scrolled-away hero is the most common waste.
5. **Verify contrast last.** Text over the busiest frame must clear WCAG AA (4.5:1 body). Scrim only where text sits — never a full dark wash.


## Decision table (cost tier: css < canvas < webgl)

| Context / genre | Recommended technique | Tier |
| --- | --- | --- |
| Dark SaaS / content-dense marketing | Blobs + feTurbulence grain + hairline grid | css |
| Bright/expressive brand hero | CSS aurora (blurred blobs + hue-rotate) | css |
| Campaign spectacle / streetwear | Kinetic marquee + type-as-texture; full-bleed video | css / video |
| Real per-point color control, no 3D pipeline | Canvas 2D mesh gradient (tiny buffer, upscaled) | canvas |
| Floating dust / connected network | Canvas particle field / constellation (spatial hash) | canvas |
| Product scroll story (Apple-style) | Canvas image-sequence scrub on a sticky runway | canvas |
| Heavy field that must not fight hydration | OffscreenCanvas worker starfield | canvas |
| Premium liquid gradient (Stripe-class) | Fragment-shader fBm + domain warp; or whatamesh | webgl |
| Abstract 3D blob hero | three.js noise-displaced icosahedron + fresnel | webgl |
| Image hover distortion | WebGL displacement (≤8 tiles) or SVG feDisplacementMap | webgl / svg |
| Scroll entrances / progress / pinned captions | CSS scroll-driven (`view()`) → IntersectionObserver → GSAP | css / scroll |


## Hard bans

- **Never animate layout properties** (width, top, margin, box-shadow spread) for ambient scenes. Transform and opacity only — everything else repaints.
- **Never autoplay sound.** Background video is `muted playsinline` or it does not ship.
- **Never open more than one WebGL context per page.** Beyond ~8 hover tiles, share one renderer or use the SVG filter.
- **Never ship without a `prefers-reduced-motion` fallback** that resolves to a composed static frame — not a blank box.
- **Never let the background reduce text contrast below AA.** Scrim only under text.
- **Never attach draw work to the raw scroll event.** Coalesce into one rAF via a dirty flag with `{passive:true}` listeners.
- **Never let the 3D/video bundle block LCP.** The poster image is the LCP element; the effect upgrades it in place or never loads.
- **Never GIF a background loop.** Encode video (WebM+MP4); GIF is 10–50× the bytes.


## Canonical values (copy-paste budgets)

- **DPR cap:** `Math.min(devicePixelRatio, 2)` everywhere. Fill-rate is the cost; 3× buys no visible gain.
- **CSS blobs:** ≤4 blobs, `blur ≤ 90–120px`, total bloom opacity < 0.3.
- **Film grain:** SVG overlay `opacity ≤ 0.06`; canvas grain `alpha ≤ 28`, throttle to ~24fps.
- **Canvas particles:** count = `W*H*density`, ceiling ~250, radii < 3px. Constellation `linkDist` 110–140 with a spatial hash.
- **Canvas mesh gradient buffer:** 32×24 to 64×48 texels, upscaled with `imageSmoothingEnabled=true`.
- **Image sequence:** 60–150 WebP frames, ~2–7MB desktop / half-res + 60 frames mobile; runway 300–500vh.
- **Fragment shader:** ≤5 fBm octaves desktop, 2–3 mobile; add a hairline dither term to kill banding.
- **three.js:** core ~150KB gzip (lazy-import it); icosahedron detail 64 ≈ 40k verts, low-power 24–32. OGL alternative ~10–15KB gzip.
- **Background video:** 720p, ~2–4MB (10s desktop loop), ~400–800KB mobile; poster = `fetchpriority="high"`.
- **Entrance cascade:** ≤900ms total, 60–100ms stagger, rise ≤16px; scrub lerp ~1s; marquee skew ≤8deg.


## Reference files — read the matching one just before you build

- [references/css-scenes.md](references/css-scenes.md) — zero-dependency aurora, Linear-style composited depth (blobs + grain + grid), film-grain recipes, and kinetic marquee/type-as-texture. Read before any css-tier scene.
- [references/canvas-scenes.md](references/canvas-scenes.md) — ambient particle field, spatial-hash constellation, canvas 2D mesh gradient, and the Apple-style image-sequence scroll-scrub. Read before any canvas-tier scene.
- [references/webgl-scenes.md](references/webgl-scenes.md) — fragment-shader fBm gradient, three.js displaced-icosahedron hero, image hover distortion, and the capability-gated "is 3D worth it" lazy loader. Read before any WebGL/3D scene.
- [references/scroll-scenes.md](references/scroll-scenes.md) — CSS scroll-driven timelines, GSAP ScrollTrigger master scene with its dependency-free IntersectionObserver equivalent, and the pinned-caption hand-off pattern. Read before any scroll-driven work.


## Output contract / final audit checklist

Confirm every line before calling it done:

- [ ] Cheapest viable tier chosen against the decision table.
- [ ] DPR capped at 2; particle/octave/blob counts within Canonical values.
- [ ] All loops pause on `visibilitychange` and offscreen via `IntersectionObserver`.
- [ ] `prefers-reduced-motion` resolves to a composed static frame (verified, not guessed).
- [ ] Capability degrade exists (no-WebGL → CSS gradient; Save-Data/2G/low-memory → poster; no-JS → visible content).
- [ ] Content authored visible; hidden state gated behind `.js` only; contrast clears AA with scrim under text only.
- [ ] Effect is `pointer-events:none`; no essential content in canvas/WebGL; one GL context max; 3D/video bundle lazy, poster is LCP.
- [ ] CTA and headline carry no ambient motion (defer micro-motion to skills/motion-craft).
