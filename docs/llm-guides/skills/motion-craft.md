<!-- Source: vandan-llm-toolkit skills/motion-craft/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Motion Craft

The motion depth layer for high-craft web work. This skill owns everything that moves: the token vocabulary, the composition laws that decide *what* animates, the recipe catalog that decides *how*, and the hard gates that decide *whether* it ships. The target is motion that reads as **finished, not decorated** — the polish premium products earn through discipline, not more animation.

This skill is model-agnostic. Every value is a copy-paste constant — exact cubic-beziers, millisecond durations, spring configs — so a weaker model copying verbatim produces the same result as a frontier one. **Never invent a curve or a duration.** If a value is not in `tokens.md`, it does not exist. Motion is a subtractive craft; when in doubt, cut it.


## Process — run this every time

1. **Pick the mode** — premium-minimal or expressive/playful, from the table below. The mode governs which easings and recipes are on-brand; the gates are universal either way.
2. **Load the tokens, not from memory.** Copy the duration/easing/spring/distance/stagger values from `references/tokens.md` verbatim into `:root`. Reference them by name everywhere.
3. **Classify each motion into one of four categories** (see Composition laws). Categories never blend.
4. **Pull the recipe** from the correct recipe file, right before you implement it. Adapt the copy-paste code; do not re-derive it.
5. **Run the gates:** reduced-motion path, 60fps transform/opacity-only, load-choreography budget. A motion that fails a gate does not ship.
6. **Run the Output contract** before claiming done.


## Mode split

Same tokens, two dialects. Pick one primary; a playful accent inside a premium-minimal product is fine, the reverse rarely is.

| | Premium-minimal | Expressive / playful |
|---|---|---|
| **For** | dev tools, SaaS, finance, editorial, luxury | games, learning, commerce hype, brand campaigns |
| **Exemplars** | Apple · Linear · Stripe · Vercel | Nike · Duolingo · Airbnb · Spotify Wrapped |
| **Easings** | `--ease-out`, `--ease-out-expo`, `--ease-standard`, `--ease-luxe` | above **plus** `--ease-out-back`, `--ease-in-back`, spring `bouncy`/`squishy` |
| **Overshoot / bounce** | never | reserved for celebration, mascots, playful buttons |
| **Signature recipes** | scroll reveal · spotlight card · conic border · count-up · skeleton | word-stagger · marquee · squash-stretch · confetti · three-beat celebration |
| **Celebration** | a state change, a 150ms fade | a choreographed 3-beat sequence, rarely |
| **Read** | recipes-core.md | recipes-core.md **and** recipes-expressive.md |


## Reference files

Read each one **just in time** — right before you apply it, not all upfront. They are code-heavy; loading them early wastes context.

- [references/tokens.md](references/tokens.md) — every duration, easing cubic-bezier, spring config, distance, and stagger value, copy-paste. Read first, before writing any motion.
- [references/recipes-core.md](references/recipes-core.md) — restrained/premium recipes: scroll reveals + etiquette, word-stagger headline, count-up, skeleton shimmer, conic-gradient border, spotlight hover card, scroll-scrub sequence, view-transition morph. Read when building a premium-minimal effect.
- [references/recipes-expressive.md](references/recipes-expressive.md) — playful recipes: infinite marquee, squash-stretch button, three-beat celebration choreography, confetti restraint, streak/mascot motion, data-driven story motion. Read when building an expressive effect.


## Composition laws

1. **Every motion is exactly one of four categories, never blended.** *Instant feedback* — ≤150ms, expo-out (hovers, taps, selection). *Reveal* — 500–700ms, quint-out, fires **once** (content entering view). *Scrubbed story* — progress = scroll position, `linear` timeline (canvas sequences, pinned captions). *Ambient loop* — ≥4s, ease-in-out, decorative (gradients, marquees).
2. **One spectacle per page.** A WebGL gradient *or* a scroll-scrub canvas — never two. Everything else is calm.
3. **Choreograph in beats.** Sequenced entrances cascade in DOM order (60–100ms apart); celebrations run anticipation → burst → settle.
4. **Ease-out for things arriving; ease-in-out for things moving and returning; ease-in for things leaving.** Never `ease-in` alone for an entrance. No bounce on premium surfaces.
5. **Opacity + transform only** for anything continuous. Everything visible without JS; everything meaningful visible without motion.
6. **Motion must mean something** — cause/effect, spatial relationship, state change, or reward. Decorative motion is the first cut.
7. **Speed is craft.** Micro-interactions 120–200ms; most transitions 200–450ms; only cinematic beats exceed ~600ms.


## Hard bans

- **No value not in `tokens.md`.** No `0.3s` guesses, no hand-tuned beziers, no `stiffness: 137`.
- **Nothing between 1s and 4s.** Interactive motion lives ≤900ms; ambient loops live ≥4s. The gap reads as sluggish or distracting.
- **No animating `width/height/top/left/margin/padding`** (layout) or `box-shadow`/`background-position` on large areas (paint). Skeleton shimmer on small blocks is the one tolerated exception.
- **No React state on `pointermove` / scroll.** Write `el.style.setProperty` inside `requestAnimationFrame` via a ref. This is the biggest jank lever.
- **No scroll-jacking.** Scroll-*driven* (progress-linked) motion is fine; fighting the user's scroll speed, direction, or position is not.
- **No bounce/overshoot on premium, enterprise, finance, or luxury surfaces.** `-back` curves and springy `squishy`/`bouncy` are playful-only.
- **No motion that blocks content.** Never delay the LCP element behind a reveal chain; never make users wait for confetti to interact.
- **No confetti/celebration on frequent or trivial actions.** Frequent celebration is inflation.
- **No motion without a reduced-motion path.** Disable-only is not a path; reveal the static end state.
- **No blanket `will-change`.** Set it on the element about to animate; remove it when done.


## Cross-reference

If **vandan-ui-system** is present it owns surfaces, type, spacing, and the baseline interaction floor; its Hard bans still apply and this skill supplies the motion depth on top. If it is absent, this skill is standalone for motion. **app-transformer** phase-5 (motion pass) states the intent; read this skill for the actual token values and recipe code — motion-craft supplies the constants.


## Output contract

Before claiming the motion work is done, confirm every item:

1. **Every duration, easing, and spring is a named token from `tokens.md`** — zero literal ad-hoc values in the diff.
2. **Each motion sits in exactly one of the four categories** — no blended reveal-loops or scrubbed-feedback hybrids.
3. **One spectacle maximum on the page.**
4. **`prefers-reduced-motion: reduce` handled on every pattern** — static end state shown (poster frame, final number, static block), JS handlers gated too, not just CSS.
5. **Continuous motion animates only `transform`/`opacity`** (filter sparingly); no layout or large-area paint properties.
6. **No `pointermove`/scroll React re-renders**; custom properties written in rAF via refs.
7. **Load choreography ≤ 900ms total, 60–100ms per item, above-the-fold only**; LCP element never animates its layout.
8. **Staggers cap at ~6 participants, 60–80ms apart**; grids stagger by row, not per cell.
9. **Skeletons match real geometry** (CLS ≈ 0) and appear only after ~150–200ms.
10. **Verified at 4× CPU throttle** — 60fps holds off an M-series laptop.

If any item fails, fix it before presenting. Do not narrate the checklist; just pass it.
