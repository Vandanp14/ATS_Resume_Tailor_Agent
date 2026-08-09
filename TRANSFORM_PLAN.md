# Transform Plan

## Stack
- Framework: dependency-free HTML and browser JavaScript served by FastAPI 0.141.1 · Styling: hand-written CSS with no browserslist (Baseline Widely Available floor) · Components: native HTML elements · Charts: none · Fonts: Apple/system sans and SF Mono stack

## Product mode
Precision Tool + Dense Enterprise — this is an operational queue and document-review workspace that needs compact navigation, strong status hierarchy, and one focused work canvas.
Accent color decision: restrained cobalt on a warm light canvas, with a contrasting deep-slate navigation rail.

## Screens
| Route | Job | Key components | Gaps |
|---|---|---|---|
| `/` | Add JDs, monitor queued tailoring work, inspect progress, preview and download results | application header, queue rail, JD form, job detail, Gemini tracker | three fixed panes overflow from 901–1223px; three competing scrollers; permanently visible form; empty bordered space; progress and PDF stacked together; weak tablet/mobile structure |

## Slop found
- `static/index.html:8-121` — every workflow surface is permanently visible — replace with a two-pane shell, focused detail tabs, and a temporary native dialog drawer.
- `static/app.css:130-136` — fixed `360px 320px minmax(480px, 1fr)` tracks guarantee horizontal overflow — replace with a bounded rail and `minmax(0, 1fr)` workspace.
- `static/app.css:140-147` — every pane owns vertical scrolling — assign one scroll owner per active surface.
- `static/app.css:564-599` — one late mobile breakpoint and fixed `100vh` subtraction clip controls — use structure-specific desktop/tablet/mobile layouts and `100dvh`.
- No gradients, glass overuse, Inter, decorative icon spam, hype copy, unsafe HTML rendering, or card-grid slop found.

## Keep
- Existing queue, SSE, job selection, artifact preview/download, and safe `textContent` rendering behavior.
- Existing system font direction, compact density, restrained cobalt accent, semantic form labels, and reduced-motion intent.
- Existing backend pipeline, master resume, prompt logic, stages, queue ordering, and `resumepdfs/` export behavior.

## Phase checklist
- [x] Phase 2: tokens & type
- [x] Phase 3: structure
- [x] Phase 4: components
- [x] Phase 5: polish
- [x] Phase 6: verify (score: 29/30)

Baseline note: before transformation, the full suite reports 99 passed, 16 failed, and 29 errors. Most web failures are pre-existing factory/test-contract drift; one real-Tectonic render failure is unrelated to this UI transformation.

## Verification score

| Check | Score |
|---|---:|
| Hard-ban compliance | 2 |
| Tokenized surfaces | 2 |
| Typography and tabular data | 2 |
| Restrained accent | 2 |
| One dominant element | 2 |
| Product-mode shell | 2 |
| Structural mobile adaptation | 2 |
| Interaction states | 1 |
| Loading, error, empty, success states | 2 |
| Motion and reduced motion | 2 |
| Accessibility floor | 2 |
| Concrete copy | 2 |
| Radius and spacing consistency | 2 |
| Chart treatment (no charts used) | 2 |
| Screenshot quality at 390px and 1440px | 2 |
| **Total** | **29/30** |

Evidence: 127 non-integration tests passed; exact 390px and 1440px Chromium screenshots have matching viewport and document widths; the mobile dialog opens with focus on Company; the Gemini usage popover opens and exposes all three quota dimensions. The real-Tectonic integration remains externally blocked by the installed binary's macOS system-configuration panic.
