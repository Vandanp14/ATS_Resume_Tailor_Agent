<!-- Source: vandan-llm-toolkit skills/product-page-craft/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# product-page-craft — Flagship Product Page Grammar

Turn one product into a page that sells it the way Apple sells AirPods — or the way Nothing, Dyson, Sony, or Tesla would, when that fits the brand better. The page's slickness *is* the media and its scroll integration — that is what carries it; tokens, type, and copy are the supporting cast that keeps it legible and on-brand. Everything here is measured from live flagship pages (computed styles, network payloads, `document.getAnimations` dumps, captured 2026-07-20), not folklore: real type ladders, real section runways, real media budgets. Follow the pipeline; take values from the references, never improvise them.

## Scope & precedence — no skill conflicts

- **product-page-craft** (this skill) owns the *single product page*: its media plan, anatomy, tokens, copy voice, pacing.
- **site-architect** owns whole-site/app autonomous builds. When a full site includes a product page, site-architect leads and consults this skill for that page. When the ask is only "a page for my product", this skill leads and borrows site-architect's stack recipe if scaffolding is needed.
- **web-alive** owns motion/effect *implementation* — how media moves. This skill owns the *media plan and its generation*: which pipeline produces each asset (existing footage / AI video / AI image+3D / Blender turntable / real-time three.js / pure-code) and where it goes; the motion *code* comes from `../web-alive/references/` (video-scrub, product-scenes, apple-teardown, motion-taste). Never duplicate motion code here.
- **Standalone taste:** art direction comes from the personality matrix in `references/flagship-grammar.md` — never apply `vandan-ui-system`, `ultra-clean-native-ui`, `premium-software-brand-system`, `mobile-native-clean-components`, `premuium-dark-ui-taste`, or `app-transformer` taste rules while this skill runs, even if they also trigger. Shared inheritance is quality (a11y, reduced-motion, payload budgets), never style.

## Pipeline — run every step, in order

### 1 · BRIEF
Identify the product, the 3–5 features that actually sell it (fewer is better — each gets a section), brand adjectives from the user's language, and — first-class now — the **asset inventory**: what media already exists (shot video, photography, renders, CAD/a 3D model, or *nothing*). The inventory drives everything downstream; the page is designed around it. One product per page; a product *line* gets a family page linking to per-product pages.

### 2 · MEDIA PLAN
The media carries the page, so plan it before the layout. **Read `references/media-decision-tree.md` FIRST** — mandatory routing read: it maps asset situation → pipeline → section. Then, per section, pick a pipeline: **existing footage / AI video / AI image + 3D / Blender headless turntable / real-time three.js / pure-code**. Set a page payload total and per-section budgets from the measured pages (AirPods hero loop: 12MB MP4 is Apple-scale; a normal budget is a fraction of that — escalate richness toward the hero, never two scrub sequences back-to-back). Generation recipes live here: `references/ai-video-gen.md` (verified mid-2026 models, pricing, licensing), `references/ai-image-3d.md` (stills + 3D), `references/render-pipelines.md` (Blender headless turntable + three.js real-time product stage). Motion/scrub *implementation* comes from `../web-alive/references/video-scrub.md` (scrub engineering, ffmpeg recipes) and `product-scenes.md` (complete scene compositions).

### 3 · PERSONALITY
Read `references/flagship-grammar.md` (§personality matrix + §10 decision guide). Match brand adjectives to a personality — Apple-clean, Nothing-brutalist, Dyson-engineering, Sony-spec-rich, Tesla-minimal — and record its dial settings (type voice/weight, color temperature, motion intensity, spec density). Default to Apple-clean ONLY when the user asked for Apple or the adjectives genuinely match; "everyone ships Apple in a trench coat" is the failure this step exists to prevent.

### 4 · SECTION BLUEPRINT
Read the two teardowns (`references/airpods-max-teardown.md`, `references/iphone-teardown.md`) for the anatomy and scale ladder, then blueprint sections **around the step-2 media plan** — each section is designed to carry its chosen media: **hero statement → feature proof stories (one idea per viewport, one section per selling feature) → gallery/finishes → specs anchor → CTA**. Budget scroll runway per section from the measured pages (AirPods Max: ~18,000px doc height; iPhone Pro: ~34,000px — scale to product importance; a simple product earns the short ladder, not the Pro treatment).

### 5 · TOKENS
Start from the CSS custom-properties block in `references/apple-design-language.md` (measured type ladder 110/80/56/48/32/28/21/19/17px, section palette #000/#f5f5f7/#1d1d1f, CTA blue #0071e3, spacing rhythm, durations/easings), then re-dial to the chosen personality (e.g. Dyson weight 300, Samsung 700 — not reflexive 600; Nothing swaps the ladder to mono/dot-matrix display type).

### 6 · COPY
Write in the personality's voice using the formula in `references/apple-design-language.md` (§copy voice): headline word counts (hero ≤6 words, section heads ≤8), claim-then-detail rhythm, sentence fragments allowed, spec-poetry pattern ("The longest battery life ever in an iPhone."), you/your address. Re-dial per personality (Sony: lead with numbers; Nothing: lowercase deadpan; Dyson: engineering claims with units).

### 7 · BUILD
Order: tokens → sections top-down → media (produced per the step-2 plan) → motion. Motion values come from `../web-alive/references/motion-taste.md`; default doctrine is Apple restraint (no bounce, no cursor effects, no parallax overdose — see `references/apple-design-language.md` §motion doctrine) unless the personality dictates otherwise (Nothing tolerates harder cuts; Dyson tolerates exploded-view choreography).

### 8 · VERIFY
Run the lint pass from `../web-alive/references/anti-patterns.md` over everything; test reduced-motion (page must read complete with zero motion — Apple's own pages do); check payload against the step-2 budget; check LCP (hero media must not block first statement paint); keyboard-walk the page; confirm every section still communicates with images stripped (copy carries the argument).

## References

| File | What's inside | Read when |
|---|---|---|
| `references/media-decision-tree.md` | Routing chapter: asset situation → pipeline → section, with payload/licensing guardrails; jumps to the pipeline chapters below | **Media plan (step 2) — mandatory first read** |
| `references/ai-video-gen.md` | AI video pipeline: verified mid-2026 models, per-second pricing, commercial licensing, seamless-loop + scrub-source recipes | Media plan (step 2) when a section's pipeline is AI video |
| `references/ai-image-3d.md` | AI image & 3D pipeline: stills, relighting, backgrounds, generated/scanned 3D models, licensing flags | Media plan (step 2) when generating stills or 3D assets |
| `references/render-pipelines.md` | No-asset pipelines: Blender headless turntable (baked frames) + three.js real-time product stage (zero-payload, GPU-rendered), plus getting a model when there's no CAD | Media plan (step 2) / Build (step 7) when rendering your own |
| `references/airpods-max-teardown.md` | Live-measured section map, media payloads, motion inventory, type tiers, reproduce-checklist for apple.com/airpods-max | Media budgeting (step 2); blueprinting (step 4) |
| `references/iphone-teardown.md` | Same protocol on the flagship iPhone page + the scale ladder vs simpler pages | Blueprinting (step 4); deciding how much page the product earns |
| `references/apple-design-language.md` | Generalized measured tokens: type ladder, section palette, layout grammar, copy voice formula, motion restraint doctrine, drop-in CSS custom-properties block | Tokens (step 5); copy (step 6); motion doctrine (step 7) |
| `references/flagship-grammar.md` | The grammar all flagship pages share + the brand dials: personality matrix (Apple/Nothing/Dyson/Sony/Tesla) and the adjectives→personality decision guide | Personality (step 3); whenever tempted to default to Apple |

Effect implementation lives in `../web-alive/references/` — video-scrub.md, product-scenes.md, apple-teardown.md (engineering-level teardown), motion-taste.md, anti-patterns.md. Stack scaffolding, if a new project is needed, comes from `../site-architect/references/stack-verdict.md`.
