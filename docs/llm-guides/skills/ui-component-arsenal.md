<!-- Source: vandan-llm-toolkit skills/ui-component-arsenal/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# UI Component Arsenal

The web is full of gorgeous, free, copy-paste React components. The discipline is not finding them — it is **taking the behavior and leaving the look.** A page assembled from five libraries' default aesthetics reads as a demo reel; the same five components re-skinned to one token system read as a product. This skill routes a component need to the right source, screens its license and tech assumptions, and runs the procedure that re-themes it into the host design system. **Steal the mechanism; re-author the surface.**

## Boundary — what this skill does and does not own

- **skills/vandan-ui-system owns the token system itself** — the colors, type, spacing, radii, surfaces, and component taste a component gets re-themed *into*. This skill never redefines tokens; it consumes them. When re-skinning, pull the exact values from vandan-ui-system; do not invent a palette here.
- **skills/motion-craft owns motion tokens and the reduced-motion baseline.** Any animation a vendored component ships is replaced with motion-craft's named durations/easings and gated per its reduced-motion policy. Cite it; do not restate curves.
- **skills/animated-backgrounds owns the passive ambient/scene layer** — full-bleed heroes, WebGL gradients, particle fields. When a spectacle component (Aceternity Beams, Magic UI Globe) is a *background*, that skill governs its budget and fallbacks; this skill only governs acquiring and adapting it.

This skill owns exactly one thing those three don't: **acquiring third-party components and folding them into the host system.**


## Process — run every time

1. **Name the component class** (foundational input · command palette · drawer · toast · spectacle effect · motion primitive). Match it to a source in the decision table.
2. **Check the distribution model and license** before pulling anything. A component you cannot legally ship, or a dependency whose upgrade risk you cannot accept, is disqualified regardless of looks. Use the license/tech table in `references/library-map.md`.
3. **Prefer headless over styled.** If an unstyled primitive covers the behavior (cmdk, Vaul, Sonner, Ark UI), take it — behavior arrives with zero visual opinion, so there is nothing to strip.
4. **Install through the registry**, then **adapt**. Run `shadcn add`, then immediately run the re-theming procedure in `references/adaptation-procedure.md` — strip vendored tokens, delete `tailwind.config` extensions, re-point at vandan-ui-system CSS variables, swap ad-hoc motion for motion-craft tokens.
5. **Strip bloat.** Delete unused variants, demo copy, dark-mode assumptions, and inline SVG the design doesn't use. Keep behavior and logic only.
6. **Run the Output contract** before calling it done.


## Distribution models (pick the model before the library)

| Model | You get | You own | Risk | Members |
|---|---|---|---|---|
| **npm dependency** | `npm install`, themed via props/CSS-vars | nothing (versioned package) | upgrade/breaking-change | HeroUI v3, Vaul, Sonner, cmdk |
| **copy-paste / registry** | CLI writes editable source into your repo | the source (no runtime dep) | no upstream fixes | shadcn/ui, Aceternity, Magic UI, Origin UI, Cult UI, Motion Primitives, React Bits, Park UI |
| **community marketplace** | search + per-item snippets | the snippet | uneven per-author quality | 21st.dev, Uiverse.io |

Take an **npm dependency only** when the primitive is single-purpose, battle-tested, and *unstyled by design* (cmdk/Vaul/Sonner) — then the dependency buys upstream fixes without fighting a bundled look. For anything with a visual opinion, prefer copy-paste so restyling is a normal edit, not a fork.


## Component-class → source decision table

| You need | Reach for | Model / License |
|---|---|---|
| Base components + gap-filling inputs (OTP, tags, date field, selects) | **Origin UI** (400+, shadcn-idiomatic) → then shadcn/ui core | copy-paste · MIT |
| Command palette / ⌘K | **cmdk** (unstyled, `cmdk-*` data-attrs) | npm · MIT |
| Mobile drawer / dialog-on-mobile | **Vaul** (Radix Dialog, snap points) | npm · MIT |
| Toast / notifications | **Sonner** (shadcn default) | npm · MIT (pin — 2.0 broke) |
| Animated marketing (marquee, bento, animated beam, border beam, dock) | **Magic UI** | copy-paste · MIT |
| Spectacle hero effects (beams, 3D card, spotlight, aurora, lamp) | **Aceternity** (free tier; treat as reference effect) | copy-paste · free / Pro proprietary |
| Text-animation & interactive bits (split/blur text, particles, click-spark) | **React Bits** (4 variants incl. plain CSS) | copy-paste · MIT + Commons Clause |
| Reusable motion behaviors (animated number, morphing dialog, infinite slider) | **Motion Primitives** | copy-paste · MIT |
| Restrained animated blocks (texture cards, expanding islands) | **Cult UI** (free tier) | copy-paste · MIT free / Pro |
| Headless logic across React/Vue/Solid/Svelte (combobox, date picker) | **Park UI / Ark UI** | copy-paste · MIT |
| Full themeable component library, React 19 / Tailwind v4 | **HeroUI v3** (React Aria) | **npm dep** · Apache/MIT ambiguous · high upgrade risk |
| Discovery / one-off block search | **21st.dev** (vet each author) | marketplace · MIT |
| Framework-agnostic CSS micro-interaction (loader, toggle) | **Uiverse.io** (normalize to tokens; a11y not guaranteed) | snippet · community |

Full per-library detail, standout components, and the maintenance-risk matrix: `references/library-map.md`.


## Hard bans

- **Never import a library's aesthetic with its behavior.** Its gradients, dark-mode assumptions, spacing, and radii are not yours — strip them the same commit you add the component.
- **Never leave vendored tokens behind.** After `shadcn add`, no hardcoded hex/shadow/radius and no `tailwind.config` extension from the source may remain. If it survived the paste, it is a bug.
- **Never vendor a license-forbidden component into a redistributable kit.** Aceternity **Pro** (proprietary, no-resell) and React Bits (**Commons Clause**) are fine inside end products, forbidden as a resold library. Confirm before pulling.
- **Never take an npm dependency for a styled block** you could copy and own. Dependencies are for unstyled scoped primitives only.
- **Never ship a styled block when a headless primitive exists** — behavior with zero look always wins.
- **Never leave a dependency unpinned.** Even "tiny" primitives break across majors (Sonner 1.x→2.0). Pin the exact version.
- **Never drop a spectacle demo in raw.** Keep the effect mechanism; re-skin the content layer entirely (see adaptation-procedure.md).
- **Never let vendored motion bypass motion-craft.** Replace bundled durations/easings with its tokens; add its reduced-motion path.


## Canonical values (copy-paste, verbatim)

```bash
# CLI 3.0 (Aug 2025) — namespaced registries + auth. Register a namespace ONCE:
pnpm dlx shadcn@latest registry add @acme=https://acme.com/r/{name}.json
pnpm dlx shadcn@latest add @acme/button          # namespaced install
pnpm dlx shadcn@latest add https://acme.com/r/button.json   # or raw URL
pnpm dlx shadcn@latest build                     # emit your own registry to public/r/
```

- Known namespaces: **`@magicuidesign`** (Magic UI), **`@cult-ui`** (Cult UI). Origin UI / Aceternity / 21st.dev install via raw URL or CLI.
- npm primitives to pin: `cmdk@1.1.x`, `vaul@1.1.x`, `sonner@2.x`.
- React Bits ships **JS+CSS, JS+Tailwind, TS+CSS, TS+Tailwind** — pull the plain-CSS variant to skip a Tailwind/Motion dependency.


## Reference files — read the matching one just before you act

- [references/library-map.md](references/library-map.md) — full per-library profiles, the license/tech-assumption table (Tailwind version, React version, RSC-safety), standout components worth stealing per library, and the maintenance-risk matrix. Read before choosing or licensing a source.
- [references/adaptation-procedure.md](references/adaptation-procedure.md) — the step-by-step re-theming procedure (`add` → strip tokens → re-point at vandan-ui-system vars → swap motion), bloat-stripping rules, the spectacle re-skin, the copy-paste-vs-dependency triage, and the private-namespace `registry.json` setup. Read before adapting anything.


## Output contract — confirm every line before calling it done

- [ ] Component class matched to the correct source via the decision table; cheapest acceptable model chosen (headless > copy-paste > npm dep).
- [ ] License verified and compatible with how this code ships (internal vs redistributed kit); no Aceternity-Pro / Commons-Clause code in a resold kit.
- [ ] Every dependency pinned to an exact version.
- [ ] All vendored tokens gone: no hardcoded colors/shadows/radii, no leftover `tailwind.config` extension; component reads only vandan-ui-system CSS variables.
- [ ] Bundled motion replaced with motion-craft tokens and given a reduced-motion path.
- [ ] Spectacle effects re-skinned at the content layer, not dropped in as demos; background spectacle deferred to animated-backgrounds for budget/fallback.
- [ ] Unused variants, demo copy, and dark-mode assumptions stripped; behavior/logic only.
- [ ] Component sits at home next to the host system (vandan-ui-system final audit passes).
