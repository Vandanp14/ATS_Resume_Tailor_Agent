<!-- Source: vandan-llm-toolkit skills/web-3d-experiences/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Web 3D Experiences

Foreground 3D is the product itself, not the wallpaper — the 3D a visitor **looks at and touches**: a rotatable watch, a car you repaint, a scene the camera flies through, a model placed in AR. It is the highest-cost, strictest-budget layer on the page. The core discipline: **pick the lightest tool that hits the look, prove the poster and capability gate before the 3D loads, compress every asset, run exactly one WebGL context.**

## Boundary — cite, do not restate

- **skills/animated-backgrounds** owns the *passive* ambient layer — background blobs, gradients, particle fields, shader heroes behind content with `pointer-events:none`. If the 3D is scenery no one touches, it owns it. It also owns the **capability-gated lazy 3D loader** (`references/webgl-scenes.md`, "Is 3D worth it?") — reuse that gate verbatim, never re-derive it.
- **skills/motion-craft** owns the motion tokens (durations, easings, springs) and **reduced-motion baseline**. Camera tweens, scrub timing, and swap transitions pull easings/durations from its `tokens.md`; the no-scroll-jack ban is its rule.
- **skills/vandan-ui-system** owns the swatch/button chrome around a configurator; this skill only drives the canvas.

If the ask is "animated background," "hero gradient," or "particles behind the headline," stop — that is animated-backgrounds.

## Process — run this every time

1. **Classify against the decision table** and pick the lightest tool. Cost climbs `image-sequence < model-viewer < R3F/three.js < Spline < Pixel Streaming`. Do not open an R3F canvas for what a `<model-viewer>` or 72-frame spin delivers.
2. **Pin the stack** from Canonical values — the R3F trio is version-locked to React, or a pre-2025 starter fails to type-check or renders dark textures.
3. **Build the poster + capability gate first.** The poster is the LCP element; the 3D bundle is `dynamic()`/`React.lazy` behind the animated-backgrounds gate, so gated-out devices pay 0 KB.
4. **Compress every asset** through the glTF pipeline (meshopt + KTX2, Draco when needed) *before* shipping — a raw DCC export is 10–40 MB.
5. **Read the matching reference just before building.**
6. **Run the gates:** one GL context, `dpr={[1,2]}`, `frameloop="demand"`, reduced-motion path, transmission cap.
7. **Run the Output contract.**

## Decision table (tier: image < model-viewer < R3F < Spline < Pixel-Streaming)

| Need / genre | Tool | Tier |
| --- | --- | --- |
| One product in 3D + mobile AR, minimal code | `<model-viewer>` (`ios-src` USDZ for iOS) | model-viewer |
| Cheap universal viewer / SEO layer / no-WebGL fallback | 360 drag-to-spin image sequence | image |
| Configurator: paint/material/part swaps | three.js/R3F + `MeshPhysicalMaterial` | R3F |
| Several 3D previews in a grid | R3F + drei `<View>` (one canvas, N windows) | R3F |
| Scroll flythrough / cinematic camera dolly | ScrollTrigger proxy **or** Blender-curve `CatmullRomCurve3` | R3F |
| Glass / crystal / gel hero object | drei `MeshTransmissionMaterial` (≤2 objects) | R3F |
| Toss-the-cards / pile-of-coins physics | `@react-three/rapier` (`updateLoop="independent"`) | R3F |
| Designer-authored self-contained hero | Spline (lazy, capability-gated) | Spline |
| Stateful vector mascot / logo | Rive state machine (amortize WASM site-wide) | embed |
| Flagship fidelity, any device, cost-no-object | Unreal + Pixel Streaming | server |
| Browser game / heavy configurator engine + editor | Babylon.js | engine |

## Hard bans

- **Never static-import the 3D canvas into a route.** `dynamic(() => import('./Scene'), { ssr:false })` / `React.lazy`, behind the capability gate + poster; the bundle never blocks first paint or LCP.
- **Never open more than one WebGL context per page.** Browsers cap live contexts at ~16; a grid of thumbnails uses drei `<View>` on one canvas.
- **Never ship raw OBJ/FBX or uncompressed glTF.** Ship `.glb`: meshopt geometry, KTX2/ETC1S textures, Draco only for the smallest geometry download.
- **Never call `KTX2Loader` without `.detectSupport(renderer)`** — it must see the live context to pick the GPU format, or textures fall back to full size.
- **Never place more than 1–2 transmission objects on a page** — each triggers a full extra scene render per frame; fake small ones with CSS/SVG (animated-backgrounds).
- **Never render above `dpr={[1,2]}`.** Retina 3× quadruples fragment work for no visible gain.
- **Never leave a permanent 60fps rAF running.** `frameloop="demand"` + rapier `updateLoop="independent"` = a settled scene costs zero frames.
- **Never mutate a material *map* without `material.needsUpdate = true`** (recompile — pre-warm off-screen); scalar/color swaps are free.
- **Never ship without a reduced-motion path and capability fallback** — reduced-motion → static angle, no scrub/auto-rotate; no-WebGL/Save-Data → turntable or poster.
- **Never scroll-jack** (motion-craft's ban): scroll-*driven* camera motion is fine, fighting the scroll is not.

## Canonical values (copy-paste)

- **R3F trio, version-locked:** React **19** + `@react-three/fiber` **^9** + `@react-three/drei` **^10** + `@react-three/rapier` **^2** (React 18 → v8/v9/v1). three.js **r185** (WebGPU via `three/webgpu`, production since **r171**; `await renderer.init()` required, async).
- **Embeds:** `@google/model-viewer` **4.3.x**; `@splinetool/react-spline` + runtime **1.9.x** (large; 99% CPU / Lighthouse hits — lazy only); `@rive-app/react-canvas` (**~200 KB WASM**, `.riv` ~10–15× smaller than Lottie); GSAP **3.13+** (all plugins free); Lenis **1.3.25**.
- **Bundle:** three core **~150 KB gzip**; OGL **~10–15 KB** for a shader with no scene graph. All lazy.
- **Canvas:** `<Canvas frameloop="demand" dpr={[1,2]}>`; `<Preload all />`; `<Detailed>` LOD; `<Bvh>` raycasting.
- **Transmission:** `resolution` 256–512, `samples` 6, `backside` only if hollow, 1–2 objects.
- **360 spin:** 36 frames (10°) = good; 72 frames (5°) = high-end. WebP/AVIF, pre-sized.
- **Decoders (pin versions):** Draco `gstatic.com/draco/versioned/decoders/1.5.7/`; KTX2 transcoder from the pinned three `examples/jsm/libs/basis/`; `MeshoptDecoder` from three addons.
- **Studio lighting, zero HDR:** `RoomEnvironment` → `PMREMGenerator.fromScene(…, 0.04)` → `scene.environment`; bake once, `dispose()`.
- **Build:** `gltf-transform optimize in.glb out.glb --texture-compress ktx2 --compress draco`.

## Reference files — read the matching one just before you build

- [references/r3f-scenes.md](references/r3f-scenes.md) — R3F + drei: dynamic Canvas, `<Environment>`/`<ContactShadows>`/`<View>`/`<ScrollControls>`, `MeshTransmissionMaterial`, rapier physics, both scroll-camera patterns (ScrollTrigger proxy + Blender-curve `CatmullRomCurve3`). Read before any R3F/three.js scene.
- [references/product-viewers.md](references/product-viewers.md) — the configurator: `GLTFLoader` + Draco/KTX2/Meshopt, the `MeshPhysicalMaterial` recipe library, `RoomEnvironment` lighting + clamped `OrbitControls`, runtime finish-swap, 360 drag-to-spin fallback. Read before any viewer or material work.
- [references/embeds-and-pipeline.md](references/embeds-and-pipeline.md) — `<model-viewer>` + AR, Spline (and when glTF beats it), Rive vs Lottie, three vs Babylon, the glTF-Transform pipeline, the WebGL/WebGPU/Pixel-Streaming matrix. Read before embedding an export or choosing a rendering model.

## Output contract

Confirm every line before calling it done:

- [ ] Lightest viable tool chosen (image-sequence / model-viewer over R3F when they suffice); stack version-locked to the React version.
- [ ] Poster is the LCP element; 3D bundle is `dynamic`/`lazy` behind the animated-backgrounds gate — 0 KB on gated-out devices.
- [ ] Assets compressed (`.glb`, meshopt + KTX2, Draco if needed); `KTX2Loader.detectSupport(renderer)` called.
- [ ] Exactly one WebGL context (grids use `<View>`); `dpr={[1,2]}`; `frameloop="demand"`; ≤2 transmission objects.
- [ ] Material *map* changes flagged `needsUpdate`; scalar/color swaps are not.
- [ ] Reduced-motion → static angle, no scrub/auto-rotate; no-WebGL/Save-Data → turntable or poster.
- [ ] Camera/swap easings and durations are motion-craft tokens; no scroll-jacking; UI chrome styled via vandan-ui-system.
