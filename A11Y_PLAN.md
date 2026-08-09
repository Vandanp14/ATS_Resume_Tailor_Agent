# A11y Plan — WCAG 2.2 AA

## Stack
- Framework: native HTML/CSS/browser JavaScript · Component libs: none · Existing focus styles: partial border/outline treatment · Reduced-motion today: global removal of transition and animation at one media query

## Screens audited
- `/` — queue-enabled JD entry, tailoring progress, resume preview, file downloads, and Gemini quota status.

## Ranked findings (the gate)
| # | Severity | Screen | Location (file:line) | Issue | WCAG SC | Phase to fix |
|---|---|---|---|---|---|---|
| 1 | High | `/` | `static/index.html:17` | tracker is a `div` pretending to be a button instead of a native control | 4.1.2 | 2 |
| 2 | High | `/` | `static/app.js` queue-row renderer | clickable list rows contain a nested Remove button, producing conflicting interactive semantics | 4.1.2 | 2 |
| 3 | High | `/` | `static/index.html:34-54` | field errors are not consistently connected through `aria-describedby` and `aria-invalid` | 3.3.1, 3.3.2 | 4 |
| 4 | High | `/` | `static/index.html:8-121` | page has no `<h1>` and no skip link | 1.3.1, 2.4.1 | 2 |
| 5 | High | `/` | `static/app.css:70-124` | muted text and subtle UI boundaries are not documented or measured against AA contrast thresholds | 1.4.3, 1.4.11 | 5 |
| 6 | Medium | `/` | `static/app.css:216-238` | quiet and inline actions can be only 30–36px high | 2.5.8 | 5 |
| 7 | Medium | `/` | `static/app.css:564-599` | mobile fixed-height subtraction and horizontal clipping can obscure focused controls | 2.4.11 | 3 |
| 8 | Medium | `/` | `static/index.html:114-118` | mobile view switcher does not implement a complete tabs pattern and uses page-current semantics for in-page panels | 4.1.2 | 4 |

## Contrast failures
| Pair (fg on bg) | Measured | Threshold | Screen |
|---|---|---|---|
| Existing `#6c6c76` muted text on `#121214` | approximately 3.6:1 | 4.5:1 | `/` |
| Existing alpha borders on adjacent dark surfaces | below a documented 3:1 component boundary | 3:1 when the boundary is required to identify the control | `/` |

## Keyboard walkthrough log
- `/`: focusable controls are reachable, but scan fails at step 5 because there is no skip link; the fake tracker requires hand-written keyboard behavior; dynamic clickable rows create nested-action ambiguity; there is no modal focus-management implementation because the current form is permanently visible.

## Phase checklist
- [x] Phase 2: semantics
- [x] Phase 3: keyboard + focus
- [x] Phase 4: ARIA patterns
- [x] Phase 5: content (alt / contrast / motion)
- [x] Phase 6: gate

No `<img>` elements or positive `tabindex` values were found. Untrusted job data is currently inserted with `textContent`, not HTML parsing.

## Gate evidence

- Native buttons now own tracker, queue selection, removal, dialog, and view-switch actions; there are no nested interactive controls.
- A skip link, one page `<h1>`, semantic header/aside/main landmarks, native dialog, visible labels, connected error slots, roving accessible tabs, and reduced-motion/forced-colors fallbacks are present.
- Exact 390px browser metrics report `scrollWidth === innerWidth`; dialog focus lands on Company and all mobile action targets are at least 44px.
- Measured text contrast: muted-on-canvas 5.62:1, muted-on-white 6.04:1, rail-muted-on-rail 9.03:1, white-on-accent 5.83:1, warning-on-white 5.87:1, and negative-on-white 6.57:1.
- Chromium's accessibility tree exposes the page main landmark, headings, and native buttons. This is a code and browser gate, not a formal third-party WCAG certification.
