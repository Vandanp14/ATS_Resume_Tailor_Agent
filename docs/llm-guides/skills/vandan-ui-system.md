<!-- Source: vandan-llm-toolkit skills/vandan-ui-system/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Vandan UI System

The one skill for all of Vandan's UI work. If any of the four legacy taste skills
(`ultra-clean-native-ui`, `mobile-native-clean-components`, `premium-software-brand-system`,
`premium-dark-ui-taste`) also trigger, **this skill wins** — it is their merged and
upgraded successor. Ignore them when this skill is loaded.

The target is never "cool" or "trendy". The target is **calm, expensive, finished** —
a product that looks like people already use it every day.

Quality bar: Linear precision · Vercel restraint · Apple Wallet matte surfaces ·
Raycast utility · Stripe clarity. Use these as a standard, never as something to copy.


## Process — run this every time

1. **Match the project first.** Before inventing anything, look at the existing codebase:
   tokens, fonts, radius scale, existing components, CLAUDE.md design notes. Extend what
   exists; only introduce the canonical system below when the project has none or the
   user asked for a redesign. A new component that ignores its neighbors is a bug.
2. **Classify the product**, then pick a mode from the table below. The mode controls
   density, radius, shell, and navigation — not the brand DNA, which stays constant.
3. **Read the relevant reference file** before building:
   - [references/tokens.md](references/tokens.md) — full color/type/spacing/radius/shadow
     tokens, light mode, Tailwind mappings. Read when setting up a system or picking values.
   - [references/components.md](references/components.md) — recipes for every core
     component (cards, rows, segmented controls, metric cards, icon tiles, floating
     panels, buttons, inputs, tables, sheets, charts, empty/loading/error states).
     Read when implementing components.
   - [references/modes.md](references/modes.md) — the five product modes in depth:
     app shells, device behavior, landing-page structure, logo/brand kit rules.
     Read when starting a new app, page, or redesign.
4. **Build**, honoring the core taste and hard bans below.
5. **Run the final audit** before presenting anything.

For a quick component tweak in an established project, steps 1 and 4–5 may be enough.
For anything new, do all five.


## Product modes

Same taste, different expression. Pick one primary mode (a secondary is fine):

| Mode | Use for | Feel | Density / radius |
|---|---|---|---|
| **Native Matte** | finance, fitness, habit, personal dashboards, mobile-first tools | Apple Wallet / iOS | compact rows, large radii (cards 24–32px) |
| **Precision Tool** | dev tools, AI tools, productivity, admin, extensions | Linear / Raycast | tight grids, sharper radii (cards 12–16px) |
| **Editorial Premium** | portfolios, personal sites, brand pages | Apple product pages | spacious, typographic |
| **Dense Enterprise** | CRMs, ops tools, data-heavy internal tools | modern enterprise | table-first, compact |
| **Product Marketing** | SaaS landing pages, launch pages | product-led, credible | compact hero, real UI early |

Never cross-contaminate: a finance app is not a dev tool; a portfolio is not an admin
panel; a desktop app is not an enlarged phone; a mobile app is not a squeezed desktop.
Details, shells, and device behavior: [references/modes.md](references/modes.md).


## Core taste

- **Dark-first.** Near-black canvas (`#050506`), charcoal surfaces, white-alpha borders.
  Elevation comes from surface contrast + border opacity + soft shadow, not heavy drops.
- **Bold native typography.** System/SF stack or Geist/Satoshi-class sans. Never default
  Inter. Numbers are large, bold, `tabular-nums`. Metadata is muted but readable.
- **Fewer, stronger components.** One dominant card or module per screen, not a grid of
  identical cards. Dividers inside cards beat nested cards.
- **Compact, rhythmic spacing.** Grouped info sits tight; unrelated info separates
  clearly. No `p-6` everywhere, no landing-page whitespace inside apps.
- **Restrained color.** One accent, meaning-bearing only (CTA, active state, status,
  chart highlight). Category color lives inside small icon tiles, never floods the page.
- **Tactile controls.** Pills and segmented controls that look pressable, ~`scale(0.985)`
  on press, 120–220ms transitions, clear focus rings.
- **Decoration is guilty until proven functional.** If an element doesn't improve
  hierarchy, comprehension, or interaction — delete it.


## Hard bans

Never use these unless the user explicitly asks:

- Purple/blue gradient backgrounds, AI-glow haze, gradient text, rainbow anything
- Full-page glassmorphism or frosted cards as the design language (one intentional
  glass element — a command menu, nav, or floating panel — is allowed)
- Neon/cyber styling, fake 3D blobs and orbs, stock illustrations, emoji decoration
- Random icons beside every heading; sparkle/brain/robot/magic-wand iconography or logos
- Generic SaaS hero + repeated 3-column feature-card grids
- Default Inter look; fragile thin low-contrast text
- shadcn or Tailwind defaults shipped unstyled (`rounded-xl border bg-card p-6 shadow-sm`)
- Buzzword copy: "unlock", "supercharge", "seamlessly", "AI-powered platform for modern teams"
- Desktop tables squeezed onto mobile; mobile UI enlarged onto desktop; hover-only
  functionality on touch

When in doubt, delete decoration rather than adding more.


## Canonical tokens (essentials)

Full system, light mode, and Tailwind mappings in
[references/tokens.md](references/tokens.md). The short version:

```css
--bg: #050506;            /* canvas; pure #000 OK for mobile-app previews */
--surface-1: #121214;     /* cards */
--surface-2: #1A1A1E;     /* nested / hover */
--surface-3: #232328;     /* elevated / active control */
--text-1: #F5F5F7;
--text-2: #A1A1AA;
--text-3: #71717A;
--border-subtle: rgba(255,255,255,0.08);
--border-strong: rgba(255,255,255,0.14);
--positive: #34D399;  --warning: #FBBF24;  --negative: #F87171;
```

- Accent by product: finance/fitness → emerald/graphite/champagne; dev/AI → cool blue or
  cyan (sparingly); portfolio → one memorable signature color; enterprise → slate/indigo.
- Gradients: default **none**. Allowed only as a tiny functional detail (inside a chart
  bar, an icon tile, a barely-there radial glow behind a product visual).
- Typography scale, spacing rhythm, and per-mode radius scale: see tokens reference.


## States and motion — non-negotiable finish

Every interactive element ships with hover, pressed/active, focus-visible, and disabled
states. Every data view ships with loading (skeletons, not spinners), empty (short title,
one sentence, one useful action, no illustration), and error (what happened + how to fix)
states. A UI that only works in the happy path is not finished.

Motion timings: hover/press 120–160ms · segmented/tabs 160–220ms · page transitions
180–260ms · modal/sheet/drawer 200–280ms. Ease-out entrances, ease-in exits, no bounce.
Respect `prefers-reduced-motion`. Motion confirms intent; it never delays it.

Accessibility floor: real `<button>` elements, labels on icon-only actions, ≥44px touch
targets, visible focus rings, semantic structure, readable contrast even on muted text.


## Charts

Charts are card content, not a library dump. Subtle gridlines, sparse muted labels,
rounded marks, low series count, no legends unless necessary, no rainbow palettes.
Emphasize the one value that matters. If a `dataviz` skill is available for the task,
its palette/method guidance composes with this — this skill still owns surfaces,
spacing, and typography.


## Copy

Minimal and direct: "Add transaction", "Review changes", "View insights". Concrete
labels, short CTAs, calm confidence, product-specific language. No hype, no filler.


## Final audit — run before presenting

1. Does this match or intentionally upgrade the project's existing design language?
2. Right mode for the product type — and does mobile feel native, desktop tailored?
3. Fewer, stronger components — or a grid of identical weak cards?
4. Typography bold, native, readable; numbers tabular and confident?
5. Color restrained: one accent, meaning-bearing, category color contained in tiles?
6. Zero hard-ban violations (gradients, glass-everything, icon spam, template SaaS)?
7. Spacing compact and rhythmic; radii consistent with the mode?
8. All interaction states + loading/empty/error present where relevant?
9. Copy direct and buzzword-free?
10. Screenshot test: with no explanation, does this look at home next to Linear, Vercel,
    or Apple Wallet — calm and expensive, not trendy?

If any answer is no, revise before presenting. Do not narrate the checklist to the user;
just pass it.
