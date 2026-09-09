<!-- Source: vandan-llm-toolkit skills/image-director/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# image-director — The Sealed-Brief Round-Trip

Design here, generate there, build here. The site is designed and built in this session, but its imagery comes from an external agent — Google Antigravity, the agentic IDE of the Gemini 3 era, generating with Nano Banana / Nano Banana Pro — and that agent has zero project context: it cannot see the layout, the palette, the section plan, or this repo. Prompt it ad-hoc and it returns whatever it returns — wrong ratios, drifting product identity, unguessable filenames — and the site gets rebuilt around the delivery. The fix is to decide everything BEFORE generation — every asset id, aspect ratio, consistency rule, prompt, and the exact folder layout of the delivery — and seal it into one self-contained artifact, `IMAGE-BRIEF.md`, written into the user's project. Phase A (**DIRECT**) writes that brief; Phase B (**INTEGRATE**) validates what came back and wires it in.

## Scope & precedence — no skill conflicts

- **image-director** (this skill) owns the round-trip itself: the asset plan, the sealed brief, and intake of the delivery. It is specifically the EXTERNAL handoff — generation happens in a tool that cannot read this repo or this session.
- **product-page-craft** owns media specs, prompt doctrine, and payload budgets — this skill's files cite `../product-page-craft/references/` (media-decision-tree.md, ai-image-3d.md, ai-video-gen.md) and never restate them. The emitted brief does the opposite, by design — the **sealed-artifact rule**: `IMAGE-BRIEF.md` inlines distilled values, prompts, and rules verbatim, with zero references to this repo, because the consuming agent can read the brief and nothing else.
- **web-alive** owns motion implementation: the canvas scrub (technique 4.5, `../web-alive/references/scroll-storytelling.md`) and image-sequence engineering (Route B, `../web-alive/references/video-scrub.md`). Never duplicate motion code here — Phase B wires delivered frames into web-alive's implementations.
- **framer-grade-sites** owns page composition — which sections exist, in what order, at what rhythm. The asset plan walks its section stack; this skill never invents page structure.
- **site-architect** owns the stack when a new build is needed — route through `../site-architect/references/stack-verdict.md`, always.
- **Standalone taste — hard override:** art direction comes from the project's own direction, never from `vandan-ui-system`, `ultra-clean-native-ui`, `premium-software-brand-system`, `mobile-native-clean-components`, `premuium-dark-ui-taste`, or `app-transformer` — even if they also trigger. Shared inheritance is quality (a11y, reduced-motion, payload budgets), never style.

Tie-breaks: if product-page-craft also triggers (the site showcases one product), it owns the page grammar and this skill runs *inside* its step-2 media plan as the external-generation route. If media will be generated in-session — image/video API keys available right here — product-page-craft's own pipelines apply instead; this skill exists for the handoff case only.

## Pipeline — detect the phase, then run its steps in order

### 0 · DETECT
Route by ground truth, not phrasing. A `gen/` directory with images beside `IMAGE-BRIEF.md`, or the user saying generation is done → **Phase B**. No images yet → **Phase A**. Ambiguous — empty `gen/`, partial delivery, images but no brief — ask one question; never guess the phase.

### A1 · ASSET PLAN
Walk the site's section plan (framer-grade-sites' stack, or product-page-craft's blueprint when it leads). One row per needed asset: kebab-case id, role, section, still vs sequence, and for sequences a tier — **Lite** 12–24 frames (crossfade/step scrub), **Standard** 40–60 (edit-chain), **Cinema** 100–160 (only via video-gen → frame extraction; when no video model is available the generating agent falls back to Standard and records the deviation in DELIVERY.md). Consult `../product-page-craft/references/media-decision-tree.md` for the section→media mapping and payload budgets: richness escalates toward the hero, never two sequences back-to-back.

### A2 · BRIEF
Copy `templates/IMAGE-BRIEF-template.md` and fill every section per `references/brief-anatomy.md`; spec sequences per `references/sequence-craft.md`. The brief prescribes the delivery contract verbatim: `gen/` beside the brief; stills `gen/<asset-id>.png`; sequence frames `gen/seq/<seq-id>/frame_0001.png` (4-digit zero-padded, 1-indexed); PNG at gen time (Phase B transcodes); and `gen/DELIVERY.md`, the generating agent's per-asset report (id | files delivered | deviations | notes, plus environment notes). It is Antigravity-tuned — Nano Banana edit-chains from reference images for consistency, the supported ratio set (1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9), up to 4K, SynthID watermark — but must read correctly pasted into any agentic IDE with image tools. Sealed-artifact rule applies: everything inlined, zero toolkit references.

### A3 · HANDOFF
Write `IMAGE-BRIEF.md` to the project root and hand the user a three-line instruction — nothing else to remember: open Antigravity, point its agent at `IMAGE-BRIEF.md`, return when `gen/` and `gen/DELIVERY.md` exist.

### B1 · INTAKE
Validate the delivery against the brief per `references/intake-integration.md`: every asset id present, frame counts and naming intact, `DELIVERY.md` deviations read and triaged (a Cinema→Standard fallback changes wiring, not design).

### B2 · OPTIMIZE
Transcode the PNG masters to web formats and sizes per `references/intake-integration.md`, holding product-page-craft's payload budgets. Masters stay in `gen/`; the site ships derivatives.

### B3 · WIRE
Stills into their composition slots; sequences through web-alive's implementations — technique 4.5 canvas scrub (`../web-alive/references/scroll-storytelling.md`) and Route B sequence engineering (`../web-alive/references/video-scrub.md`). `references/intake-integration.md` maps each asset kind to its implementation home.

### B4 · VERIFY
Run the checklist in `references/intake-integration.md`: payload vs budget, LCP with hero media in place, reduced-motion shows a complete page, and every section still communicates with images stripped.

## References

| File | What's inside | Read when |
|---|---|---|
| `references/brief-anatomy.md` | Anatomy of a sealed IMAGE-BRIEF.md: identity block, per-asset spec rows, delivery contract, DELIVERY.md spec, what to distill (inline) from product-page-craft | Writing the brief (A2) |
| `references/sequence-craft.md` | Sequence design: Lite/Standard/Cinema tier selection, frame counts, edit-chain consistency prompting, video-gen frame extraction, fallback rules | Tier calls (A1); sequence specs (A2) |
| `references/intake-integration.md` | Phase B playbook: delivery validation checklist, transcode recipes, asset-kind→implementation mapping, verify gates | Every Phase B step (B1–B4) |
| `templates/IMAGE-BRIEF-template.md` | The fill-in brief skeleton copied into the user's project — sealed, self-contained | A2 — copy, then fill |

Scrub and motion implementation lives in `../web-alive/references/` — video-scrub.md (Route B engineering, ffmpeg recipes) and scroll-storytelling.md (technique 4.5 canvas scrub). Media doctrine lives in `../product-page-craft/references/` — media-decision-tree.md (section→media routing, payload budgets) plus ai-image-3d.md and ai-video-gen.md (the model landscape the brief's inlined values are distilled from). Stack scaffolding, when a new project is needed, comes from `../site-architect/references/stack-verdict.md`.
