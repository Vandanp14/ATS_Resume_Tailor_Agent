<!-- Source: vandan-llm-toolkit skills/react-craft/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# React Craft

Weak models write React from pre-2024 training data: class components with lifecycle methods, `forwardRef` around every ref, `useEffect` for anything that moves, `useMemo`/`useCallback` sprinkled on every value, and `key={index}` on dynamic lists. That code looks fluent and is a decade stale. This skill is the current idiom, encoded as tables and bans so the output is model-independent: you do not need React taste, because the judgment is written down. Read first, match the row, then write.

The rule is absolute: **do not emit a React pattern from memory when a current idiom exists for it.** Every row below has a stale way and a current way. Ship the current one.

## Version lock first

The idioms here shift by major version. Resolve the installed `react`/`react-dom` major from the lockfile before applying anything (per `version-grounded-coding` — read that skill's procedure, do not restate it). React 19 is the current major; the recipes below are grounded in the React 19.2 line (mid-2026). If the resolved major is 18 or lower, read that version's vendored docs before applying — several rows below (ref-as-prop, `use()`, the compiler) do not exist pre-19.

## The idiom table — stale way → current way

Each row is copy-paste ready. Match the code you are writing or fixing to a row and emit the right column.

| Stale way (reject on sight) | Current way (React 19) |
|---|---|
| `class Foo extends React.Component` + lifecycle methods | function component + hooks |
| `const X = forwardRef((props, ref) => …)` | `function X({ ref, ...props }) { … }` — ref is a plain prop |
| `X.defaultProps = { size: 'md' }` | ES default params: `function X({ size = 'md' })` |
| `X.propTypes = { … }` | TypeScript prop types (see `modern-typescript` if available) |
| `useEffect(() => { fetch(url).then(setState) }, [url])` | fetch in a Server Component (`await`) or the query layer — see `state-and-data-fetching` |
| `useEffect(() => setFull(first + ' ' + last), [first,last])` | compute during render: `const full = first + ' ' + last` |
| `useEffect(() => setState(initial), [id])` to reset on prop change | remount with a `key`: `<Panel key={id} />` |
| `useMemo`/`useCallback` on every value "for perf" | let the React Compiler memoize; add manual hooks only for precise control |
| `{items.map((x,i) => <Row key={i} />)}` | `{items.map(x => <Row key={x.id} />)}` — stable data id |
| throw a promise manually to trigger Suspense | `const data = use(promise)` inside a `<Suspense>` boundary |
| read Context with `use()`/hooks in a Server Component | pass data as props, or `await` the source; `use(Context)` is client-only |
| `isPrimary`/`isSecondary`/`isDanger` boolean-explosion props | one discriminated union: `variant: 'primary' \| 'secondary' \| 'danger'` |
| render prop purely to share logic (`<Data>{d => …}</Data>`) | a custom hook: `const d = useData()` |
| passing a prop through 3 wrappers that never read it | composition — pass JSX via `children` / slot props |

Two rows carry deprecation weight: `forwardRef` still works but the docs state it "will be deprecated in a future release" — write ref-as-prop for new components. `defaultProps`/`propTypes`/string refs/legacy context are removed for function components — using them is a defect, not a style choice.

## Failure catalog — what weak models get wrong here

| Symptom | Why it is wrong | Fix |
|---|---|---|
| `key={index}` on a list that can reorder/insert/delete | index keys bind state to position, so rows corrupt on mutation | key off a stable data id; never index, never `Math.random()` |
| a prop threaded through 2+ components that don't use it | prop drilling; couples the tree to a value it doesn't own | invert with composition — pass `children`; see [references/composition.md](references/composition.md) |
| one Context holding theme + user + everything | every consumer re-renders on any change | split providers, memoize the value; no native `useContextSelector` exists — use an external store via `useSyncExternalStore` for hot state |
| `useEffect` that derives state from props/state | derived values drift and cause extra renders | compute during render; for the full effect discipline read [references/hooks-and-effects.md](references/hooks-and-effects.md) |
| class components / `componentDidMount` in new code | pre-hooks pattern, not written today | function component + hooks |
| `useMemo`/`useCallback` before any measured problem | premature; the compiler already memoizes | remove it; add back only for precise control or to stabilize effect deps |

## Read the reference just-in-time

| Task | Read |
|---|---|
| Decide server vs client component; compose with children/slots; build a compound component (Tabs/Accordion) | [references/composition.md](references/composition.md) |
| Pick which hooks earn their place; React Compiler memoization stance; extract a custom hook; ref idioms; effect boundary | [references/hooks-and-effects.md](references/hooks-and-effects.md) |
| Any data fetching, loading/error/empty states, prop-mirroring, or race safety | `state-and-data-fetching` (owns the full effect + fetching discipline) |

## Config — canonical copy-paste

Current values, mid-2026. Install the runtime, the compiler, and the compiler-powered lint:

```sh
npm install react@^19.2 react-dom@^19.2
npm install --save-dev --save-exact babel-plugin-react-compiler@latest
npm install --save-dev eslint-plugin-react-hooks@latest   # 'recommended' preset; compiler-powered lint
```

Register the compiler's Babel plugin and extend the lint's recommended preset (resolve exact option names from the compiler's install doc for your version):

```js
// babel.config.js
module.exports = { plugins: ['babel-plugin-react-compiler'] };

// eslint.config.js
import reactHooks from 'eslint-plugin-react-hooks';
export default [reactHooks.configs.recommended];
```

The compiler reached 1.0 stable (Oct 2025) and auto-memoizes at build time — it does not fully obsolete `useMemo`/`useCallback` (still needed for precise control and to keep effect deps stable). For existing code, leave current memoization in place unless you test that removing it is safe.

## Testing conventions

Current React Testing Library sits on the 16.x major; since v16, `@testing-library/dom` is a peer dependency you install explicitly:

```sh
npm install --save-dev @testing-library/react @testing-library/dom @testing-library/user-event @testing-library/jest-dom
```

Test behavior, not implementation. Query by accessible role with an accessible name; reserve `getByTestId` for a last resort. Drive interaction with `userEvent.setup()`, not `fireEvent`. Assert async with `findBy*`/`waitFor`.

```js
const user = userEvent.setup();
await user.click(screen.getByRole('button', { name: /save/i }));
expect(await screen.findByRole('status')).toHaveTextContent('Saved');
```

Reject Enzyme, `container.querySelector`, and snapshot-everything tests — they assert structure, not behavior.

## Closing gate — confirm before calling React work done

- [ ] Version-lock header emitted; recipes match the resolved React major.
- [ ] No class components, `forwardRef` for plain ref passing, `defaultProps`, `propTypes`, or string refs in new code.
- [ ] Refs are passed as ordinary props.
- [ ] No `useEffect` derives state, mirrors props, or fetches app data (that belongs to `state-and-data-fetching`).
- [ ] No `useMemo`/`useCallback` added without a precise-control or effect-dep reason; the compiler owns the rest.
- [ ] Every mapped list has a stable, data-derived `key` — never the index.
- [ ] Prop drilling past two levels replaced by composition; no single god-Context.
- [ ] Boolean-explosion props collapsed to a discriminated union.
- [ ] Tests query by role and drive with `userEvent`; no Enzyme or `querySelector`.
