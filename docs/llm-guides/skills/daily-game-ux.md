<!-- Source: vandan-llm-toolkit skills/daily-game-ux/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Daily Game UX

The genre skill for daily-games products — hubs and game pages whose job is to be
**a place you return to every day**, not a catalog you browse once. The failure mode is
specific: a games page that reads as an e-commerce product grid. A product card never
changes; **a game tile knows you.** Every pattern here encodes that difference.

Target feel: the newspaper puzzle page (NYT Games, Puzzmo), the network-native ritual
(LinkedIn Games), the viral finish moment (Wordle). Exemplars are named for recognition;
copy their *mechanics*, never a brand's trade dress. This skill is **model-agnostic** —
every ritual value below is a copy-paste constant (day-index math, storage keys, countdown
logic, share templates) so a lower-capability model produces the same result as a frontier
one. Copy values verbatim; do not improvise equivalents.


## Composition with sibling skills

- **`vandan-ui-system`** owns base tokens, surfaces, buttons, dark-mode parity, and the
  five product modes. Its mode table has **no games mode** — this skill registers the
  missing genre. Inherit its tokens and states; this skill owns everything game-specific.
  If unavailable, still honor its floor (real `<button>`s, focus rings, loading/empty/error,
  `prefers-reduced-motion`).
- **`motion-craft`** (see skills/motion-craft) owns celebration choreography and
  streak-flame motion — the three-beat finish, confetti gating, flame flicker. It owns the
  finish moment's *timing*; this skill owns its *content*.
- **`collectible-card-ui`** (see collectible-card-ui) owns card-styled tile hover craft —
  tilt, holo, foil, facedown rarity-glow. Use it when a tile is a card.
- If a sibling is unavailable, this skill is standalone — apply its rules directly.


## Operating rules — run this every time

1. **Lead with the thing you can play.** Order the hub playable-first; never bury the one
   live game among identically-styled stubs. The available game earns a featured footprint
   (full-width row on mobile, wider span on desktop).
2. **Make every tile stateful.** Render CTA + badge from localStorage — `Play` → `Continue`
   → `Solved` (state table below). The biggest game-vs-commerce signal.
3. **Stamp the edition on everything.** Tile top and game page carry `No. N · Weekday, Mon D`
   from a launch-epoch day index. This one cheap line says *daily ritual*.
4. **Give each game an owned hue + one flat glyph** on a full-bleed field — never a product
   photo on white. Reuse the hue inside the game page so hub and page feel continuous.
5. **Tagline is a 2–4-word imperative**, never a description. One line, never two.
6. **Route every ending into the finish moment** — win *and* loss both open the stats modal
   (stats → distribution → countdown → share). A finished day's steady state is the stats
   view, not the board.
7. **Coming-soon is never a gray box** — facedown card or full-fidelity notify-me stub.
8. **Frame trends personally, never competitively** — no global percentiles (they
   demotivate and you can't build them client-side anyway).
9. **Read each reference right before applying it; do not read all files upfront.**


## Tile state machine

| State | Trigger (from localStorage) | CTA | Badge / art |
|---|---|---|---|
| **Unplayed** | no entry for today's `dayId` | filled pill **"Play"** in the game's hue, near-black label | idle glyph art |
| **In progress** | saved board exists for today | **"Continue"** + thin progress hint ("3/5", "Best pull: …") | idle art + progress |
| **Solved** | today's run finished | ghost **"See stats"** + check badge | art swaps to *your result*; streak flame `🔥N` if any |
| **Coming soon** | game not released | **no CTA** | facedown back or notify-me stub |

Copy always uses verbs: **"Play"**, never "Start" / "View" / "Get".


## Hard bans

- **No e-commerce card anatomy** — no price slot, no "Free · 5 min", no "Add to cart" grammar.
- **No shipping/announcement promo strips** ("always free / no account needed") — recast as a rotating daily fact or callout.
- **No product-photography grids** on white; no rendered product shots as tile art.
- **No competitive global percentiles or global leaderboards as the primary frame** — personal trends only.
- **No countdown-scarcity** ("2 left!", sale timers). The only countdown allowed is *time to the next edition*.
- **No gray "Coming soon" chip on a dimmed product card** — facedown or full stub only.
- **No two-line taglines; no descriptive taglines.**
- **No UTC day math** — compute the day from the *local* date string, always.
- **Never re-render the whole tree on every countdown tick;** update one node, `tabular-nums`, reserved height.


## Canonical values — copy verbatim

Day index and edition label (the ritual's backbone). Pick one launch epoch and never change it:

```ts
const LAUNCH = new Date("2026-03-01T00:00:00"); // fixed epoch; local time
export const dayId = (d = new Date()) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const editionNo = (d = new Date()) =>
  Math.floor((d.setHours(0,0,0,0) - new Date(LAUNCH).setHours(0,0,0,0)) / 86_400_000) + 1;
// label: `No. ${editionNo()} · ${d.toLocaleDateString(undefined,{weekday:"short",month:"short",day:"numeric"})}`
```

Next-edition countdown — diff to next *local* midnight, tick one node:

```tsx
function Countdown({ to }: { to: number }) {
  const [left, setLeft] = React.useState(() => to - Date.now());
  React.useEffect(() => {
    const id = setInterval(() => setLeft(to - Date.now()), 1000);
    return () => clearInterval(id);
  }, [to]);
  if (left <= 0) return <span>New edition ready</span>;
  const pad = (n: number) => String(n).padStart(2, "0");
  return <time style={{ fontVariantNumeric: "tabular-nums" }}>
    {pad(Math.floor(left/3.6e6))}:{pad(Math.floor(left/6e4)%60)}:{pad(Math.floor(left/1e3)%60)}
  </time>;
}
// to = next local midnight: const d=new Date(); d.setHours(24,0,0,0); const to=+d;
```

Storage-key convention — one namespace prefix, per-game, date-scoped where daily:

```
<app>:<game>:state          // resume payload { board, score, dayId }
<app>:<game>:stats          // lifetime stats (schema in game-page-rituals.md)
<app>:<game>:seen-howto      // "1" once the first-run modal was dismissed
<app>:notify:<game>          // "1" once a coming-soon stub opt-in was stored
<app>:<game>:<dayId>         // per-day hub tile state { status, score }
```

**Streak rule (memorize):** `currentStreak` increments when the user plays on
*consecutive local calendar days*; a missed day **or** a loss resets it to `0`; update
`maxStreak = max(maxStreak, currentStreak)` on every finish.


## References — read just-in-time

Read the file at the moment you apply it, not all upfront.

- [references/hub-patterns.md](references/hub-patterns.md) — tile anatomy, playable-first ordering, edition/masthead chrome, per-game streaks, completion memorialization. Read when building or auditing the **hub grid**.
- [references/game-page-rituals.md](references/game-page-rituals.md) — pre-game splash, how-to-play first-run modal, post-game stats modal + the localStorage stats schema, the share-text template, win/lose overlay grammar, coming-soon stubs. Read when building a **single game page** or a finish moment.


## Output contract — pass before claiming done

1. Hub is playable-first; the live game is visually featured, not buried among stubs.
2. Every tile is stateful (Play/Continue/Solved/Coming-soon) and reads its state from localStorage.
3. Edition stamp present on tiles and game page; day index from a fixed launch epoch, local time.
4. Each game owns a hue + flat glyph; the hue carries into its page. Taglines are one-line imperatives.
5. Both game endings route into the stats modal: four tiles → distribution (today's row in accent) → next-edition countdown → Share.
6. Stats persist in the documented key shape; streak uses local-day math and resets on a missed day or loss.
7. Share artifact is spoiler-free, carries the edition number, and embeds a "Play this" link; clipboard-then-web-share delivery.
8. First visit auto-opens how-to once (`seen-howto` set); a persistent `?` reopens it forever.
9. Coming-soon slots are facedown cards or full notify-me stubs — never gray boxes; opt-in flips to "You're on the list ✓".
10. No hard-ban violations; personal-trend framing only, no global percentiles.

If any answer is no, fix it before presenting. Do not narrate the checklist.
