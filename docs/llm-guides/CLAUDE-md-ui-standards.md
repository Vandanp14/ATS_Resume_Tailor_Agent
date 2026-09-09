# UI Standards (paste into any project's CLAUDE.md / AGENTS.md)

Copy the block below into the project's agent instructions file. It is
model-agnostic and self-contained — it works without any skills installed.

---

## UI Standards — non-negotiable

Target: calm, expensive, finished. Quality bar: Linear precision, Vercel restraint,
Apple Wallet matte surfaces. Never a generic template or "AI-generated" look.

**Tokens (use these, no one-off hexes):** canvas `#050506`; surfaces `#121214` →
`#1A1A1E` → `#232328` (lighter = higher); text `#F5F5F7` / `#A1A1AA` / `#71717A`;
borders `rgba(255,255,255,0.08)`–`0.14`; status `#34D399` / `#FBBF24` / `#F87171`.
ONE accent color for CTAs/active/highlights only. Elevation = surface step + border +
soft shadow (`0 18px 50px rgba(0,0,0,0.36)`), never heavy drops.

**Type:** system/SF stack or Geist/Satoshi — never default Inter. Bold hierarchy:
page titles 28–44px/700+, big metrics `clamp(42px,7vw,64px)`/800/`-0.04em`, body
14–16px, labels muted. All money/stats/counts get `tabular-nums`. No weights <400.

**Layout:** one dominant element per screen. Fewer, stronger cards — merge identical
card grids into one card with `divide-y divide-white/[0.07]` rows. Cards float on the
dark canvas. Group related tightly (8–12px), separate unrelated clearly (24–32px).
Radius consistent: cards 24–32px (consumer/native feel) or 12–16px (dev/enterprise
tools); pick one scale and keep it.

**Responsive by structure:** mobile is not squeezed desktop. Tables → grouped rows on
mobile; modals → bottom sheets; hover-only actions get a touch path; targets ≥44px;
bottom nav only on mobile (3–5 destinations), sidebar only on desktop.

**States:** every interactive element ships hover + pressed (`scale(0.985)`) +
focus-visible + disabled. Every data view ships loading (skeletons, not spinners),
empty (title + one sentence + one action, no illustration), and error (what happened +
how to fix). Transitions 120–280ms, ease-out in / ease-in out, no bounce, respect
`prefers-reduced-motion`.

**Copy:** verb + object CTAs ("Add transaction", "Save changes"). Banned words:
unlock, supercharge, seamlessly, revolutionize, empower, effortless, "AI-powered
platform".

**Banned visuals** (unless user explicitly asks): purple/blue gradients, gradient
text, glassmorphism as the design language (max ONE glass element app-wide),
neon/cyber glow, 3D blobs, stock illustrations, emoji decoration, sparkle/brain/robot
logos, icons beside every heading, repeated 3-column feature-card grids, unstyled
shadcn/Tailwind defaults (`rounded-lg border bg-card p-6 shadow-sm`).

**Before presenting any UI change,** verify: no banned visuals; tokens used; one
dominant element; states present; mobile structurally adapted; screenshot would sit
comfortably next to Linear/Vercel/Apple Wallet. If not, revise first.

---

Adaptation notes when pasting:
- If the project already has a token system, keep its values and apply the rules
  (hierarchy, states, bans) on top — note the mapping in the pasted block.
- For light-mode products swap tokens: canvas `#F7F7F4`, surface `#FFFFFF`/`#F2F2EF`,
  text `#111113`/`#55555C`, borders `rgba(0,0,0,0.08)` — same rules otherwise.
- For a full transformation of an existing app, run the `app-transformer` skill
  (six-phase pipeline) rather than ad-hoc edits.
