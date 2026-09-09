# 19 — Symbol Verification

Rule: **locate before you reference.** For every NEW symbol you are about to write —
import, function, method, component prop, config/env key, route, CSS token — confirm
its definition exists in THIS repo by grep or read FIRST. Weak models emit
plausible-but-nonexistent identifiers from training memory: a helper that isn't
exported, a method with the wrong name, a design token that was renamed, a prop the
component never declares. Each typechecks in the model's head and fails in the repo.

## The four failures this deletes

- `import { formatDate } from '@/lib/utils'` — `utils` exports no `formatDate`.
- `arr.remove(x)` / `dayjs().subtract` variants — wrong-named method on a real object.
- `bg-brand-500` — the token is `brand-primary`; the class silently does nothing.
- `<Card elevated />` — `Card` never declares `elevated`, so the prop is dropped.

## The procedure — run per symbol, before writing the call

```
1. Name the symbol and its kind (import / method / prop / env key / route / token).
2. Run the matching lookup recipe below.
3. Found → copy the EXACT name + signature into your scratch note. Write the call.
4. Not found → do NOT write it. Pick a symbol that exists, or create the
   definition first, then reference it. Never emit an unlocated symbol.
```

One symbol, one lookup, one confirmation. No batching from memory.

## Fast lookup recipes

- **Import / exported function:** grep the export in the source module.
  ```bash
  grep -rn "export .*formatDate\|formatDate\s*[:=(]" src/lib/
  ```
  Zero hits = it does not exist. Do not import it.
- **Method on an object/library:** read the type or the real class.
  ```bash
  grep -rn "formatDate" node_modules/<pkg>/**/*.d.ts   # or open the .d.ts
  ```
  For your own objects, read the class/interface and list its real methods.
- **Package export path:** check the `exports` map before deep-importing.
  ```bash
  grep -n "\"exports\"" -A 30 node_modules/<pkg>/package.json
  ```
- **Component prop:** read the component's prop type / interface, not its call sites.
  ```bash
  grep -rn "interface .*Props\|type .*Props" src/components/Card.tsx
  ```
  If the prop name is not in that declaration, the component ignores it.
- **Config / env key:** grep the schema/loader and the example file.
  ```bash
  grep -rn "API_TOKEN" .env.example src/config/ src/lib/env*
  ```
- **Route / path:** grep the router or route table for the exact path string.
- **CSS token / class:** grep the theme/config for the token; never guess the scale.
  ```bash
  grep -rn "brand" tailwind.config.* src/app/globals.css
  ```

## Hard ban

- **Never write a symbol you have not located this session.** No exceptions for
  "obvious" names, "standard" helpers, or "it's probably called that."
- **Never trust training memory for a repo-local name** — libraries, tokens, and
  helpers are versioned and renamed; your memory is stale by construction.
- **Never copy a symbol from another call site without confirming the source declares
  it** — the call site may itself be wrong or from a different version.

## Confirmed-symbols scratch note

Keep a running list for the current edit. One line per symbol:

```
CONFIRMED SYMBOLS (this edit)
- formatDate        -> src/lib/date.ts:12 (export function formatDate(d: Date): string)
- Card.variant      -> src/components/Card.tsx:8 ("primary" | "ghost")
- NEXT_PUBLIC_API   -> .env.example:4
```

## Output contract

Before the edit is done: every NEW symbol in the diff appears in the scratch note with
a `file:line` where it is defined. Run the gate to catch strays:

```bash
# unresolved local imports — every hit must be explainable
grep -rn "^import .* from '@/" src/<changed-file> \
  | while read -r l; do echo "VERIFY: $l"; done
```

Any symbol you could not locate is either removed or defined first — never shipped
unlocated.
