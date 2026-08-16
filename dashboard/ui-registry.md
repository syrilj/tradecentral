## Baseline — Established 2026-08-14

[Note: This baseline was established via /imprint audit]

This is the **desk / instrument** contract. Source of truth: `src/styles/tokens.css`, `src/styles/base.css`, `docs/DESIGN.md`.

Landing, auth, and marketing `*Visual` pieces are a **separate paper system**. Do not restyle them onto these tokens, and do not restyle the desk onto paper.

| Property | Correct class |
| ---------------- | ------------- |
| Canvas | `background: var(--void)` |
| Raised panel | `.ticked` + `border: var(--hair) solid var(--rule)` + `var(--panel)` |
| Panel radius | `0` |
| Control / chip radius | `2px` |
| Lamp / live dot | `border-radius: 50%` |
| Meter fill radius | `1px` |
| Text — primary | `color: var(--ink)` |
| Text — secondary | `color: var(--ink-dim)` |
| Text — muted | `color: var(--ink-faint)` or `var(--ink-ghost)` |
| Accent / live / focus | `var(--phosphor)` only |
| Signed + / − | `var(--long)` / `var(--short)` |
| Call / put | `var(--call)` / `var(--put)` |
| Table | `.grid` — `th` `var(--s3) var(--s4)`, `td` `var(--s2) var(--s4)` |
| Control padding | `var(--density-cell-padding)` or `var(--s2) var(--s3)` |
| Chip padding | `2px 6px` or `var(--s1) var(--s2)` |
| Button primary | `--phosphor` fill, `--void` text, radius `2px` |
| Button quiet | hairline `--rule`, hover `--panel-hi` |
| Row hover | `background: var(--panel-hi)` |
| Row selected | `--phosphor-wash` + `box-shadow: inset 2px 0 0 var(--phosphor)` |
| Focus | never `outline: none`; global `:focus-visible { outline: var(--hair) solid var(--phosphor); outline-offset: 2px }` |
| Shadow | none, or `0 1px 0 rgba(0,0,0,0.18)` shelf, or inset selection bar |
| Type size | `--t-micro` / `--t-tiny` / `--t-small` / `--t-fig` — not raw 8–13px where a token exists |
| Type face | `--font-display` (Martian), `--font-ui` (Instrument Sans), `--font-data` (IBM Plex Mono) |
| Space | `--s1`–`--s8` (4px base) |
| Density | `--density-row-height` 28px, `--density-cell-padding` `3px 8px` |

**Hard rules (do not invent a second scale):**

- One accent. Green/red only for signed quantities.
- Corner ticks, not rounded cards.
- No glow. Never `box-shadow: 0 0`, `text-shadow`, or `filter: brightness()`.
- Data marks are flat fills.
- Do not use phantom tokens (`--font-mono`, `--radius-sm`, `--space-*`, `--dur-normal`). Use `--font-data`, `2px`, `--s*`, `--dur`.

### Out of desk baseline — marketing / paper

These surfaces keep the offset-print paper system. Do not imprint them onto desk tokens, and do not “fix” their shadows, cream stock, or ink mixes to match this file:

- `src/views/LandingView.vue`
- `src/views/AuthView.vue`
- `src/components/LiveStateVisual.vue`
- `src/components/GexFlowVisual.vue`
- `src/components/ResearchLoopVisual.vue`
- `src/components/OperatorAccessVisual.vue`
- `src/components/EvidenceLayerVisual.vue`
- `src/components/FlowWorkspaceMockup.vue`

---

### Panel

File: `src/components/Panel.vue`
Last updated: 2026-08-14

| Property | Class |
| ---------------- | --------------- |
| Background | `.ticked` → `var(--panel)` |
| Border | `var(--hair) solid var(--rule)` |
| Border radius | `0` (ticks, not rounding) |
| Text — primary | `.lab` / `.label` → `var(--ink)` |
| Text — secondary | `.meta` → `var(--ink-dim)` |
| Spacing | root `var(--s1)`; head `var(--s1) var(--s2)`; body `0 var(--s2) var(--s2)` |
| Hover state | `border-color: var(--rule-hi)`; shelf `0 1px 0 rgba(0,0,0,0.28)` |
| Shadow | `0 1px 0 rgba(0,0,0,0.18)` shelf only |
| Accent usage | `.live::before` 2px `--phosphor` left edge |

**Pattern notes:**
Every desk block of data sits in a Panel. Registration ticks come from `.ticked` in `base.css`. Do not add `border-radius` or glow. Use `flush` for edge-to-edge tables and charts.

---

### Readout

File: `src/components/Readout.vue`
Last updated: 2026-08-14

| Property | Class |
| ---------------- | --------------- |
| Background | none |
| Border | none |
| Border radius | none |
| Text — primary | `.val.fig` → `var(--ink)`; size `--t-small` / `--t-fig` / `--t-fig-lg` |
| Text — secondary | `.label` + `.sub` → `var(--ink-dim)` |
| Spacing | column; gap `3px` |
| Hover state | none |
| Shadow | none |
| Accent usage | tone map only: `pos` `--long`, `neg` `--short`, `call` `--call`, `put` `--put`, `accent` `--phosphor`, `flat` `--ink-dim` |

**Pattern notes:**
A labelled figure is the atom of the instrument strip. Signed color is data, not chrome. Never glow a figure to emphasize it.

---

### VerdictChip

File: `src/components/VerdictChip.vue`
Last updated: 2026-08-14

| Property | Class |
| ---------------- | --------------- |
| Background | wash of the verdict (`--long-wash` / `--short-wash` / `--warn-wash`) |
| Border | `var(--hair) solid currentColor` |
| Border radius | `2px` |
| Text — primary | currentColor; `--go` / `--no-go` / `--running` / `--unknown` |
| Text — secondary | none |
| Spacing | `4px 9px 4px 7px`; `sm` `3px 7px 3px 6px` |
| Hover state | none |
| Shadow | none |
| Accent usage | 5px lamp `border-radius: 50%`; running lamp uses `pulse-lamp` |

**Pattern notes:**
Owns GO / NO-GO / UNKNOWN / RUNNING only. Do not reuse for generic tags. Lamp is a flat fill, never a glow.

---

### App shell (rail + strip)

File: `src/App.vue`
Last updated: 2026-08-14

| Property | Class |
| ---------------- | --------------- |
| Background | canvas `var(--void)`; rail / foot `var(--void-lift)`; strip `linear-gradient(90deg, color-mix(in srgb, var(--phosphor) 4%, transparent), transparent 24%)` over `var(--void-lift)` |
| Border | `var(--hair) solid var(--rule)` (rail right, strip bottom, foot top) |
| Border radius | `0` |
| Text — primary | `var(--ink)` |
| Text — secondary | `var(--ink-dim)`; ghost meta `var(--ink-ghost)` |
| Spacing | rail `var(--rail-w)` 80px; strip `var(--strip-h)` 60px; stage pad `var(--s5)` |
| Hover state | nav / gauge `var(--panel-hi)`; text `var(--ink)` |
| Shadow | more-panel shelf `0 1px 0 rgba(0,0,0,0.4)` |
| Accent usage | `.nav-item.on` `--phosphor` + `--phosphor-wash` + 3px inner phosphor bar |

**Pattern notes:**
One navigation system. Active state is phosphor, not a filled neon rail. Signed colors appear only on change figures (`--long` / `--short`). Skip-link is the only shell primary fill (`--phosphor` on `--void` text). `.strip-search` and `.more-search` are quiet `--ink-dim` controls; hover is `--phosphor` text on `--phosphor-wash`.

---

### `.ticked`

File: `src/styles/base.css`
Last updated: 2026-08-14

| Property | Class |
| ---------------- | --------------- |
| Background | eight `--phosphor-dim` corner ticks + `var(--panel)` |
| Border | supplied by the host (`var(--hair) solid var(--rule)`) |
| Border radius | `0` |
| Text — primary | inherited |
| Text — secondary | inherited |
| Spacing | tick length `var(--tick)` 8px; tick weight `var(--hair)` |
| Hover state | none (host Panel darkens the rule) |
| Shadow | none |
| Accent usage | ticks only — phosphor-dim, not glow |

**Pattern notes:**
This is the signature desk frame. New raised surfaces use `.ticked`, not `border-radius`.

---

### `.hairline`

File: `src/styles/base.css`
Last updated: 2026-08-14

| Property | Class |
| ---------------- | --------------- |
| Background | none |
| Border | `var(--hair) solid var(--rule)` |
| Border radius | none |
| Text — primary | inherited |
| Text — secondary | inherited |
| Spacing | none |
| Hover state | none |
| Shadow | none |
| Accent usage | none |

**Pattern notes:**
Use for internal rules and quiet controls. Prefer `var(--hair)` over raw `1px`.

---

### `.label`

File: `src/styles/base.css`
Last updated: 2026-08-14

| Property | Class |
| ---------------- | --------------- |
| Background | none |
| Border | none |
| Border radius | none |
| Text — primary | `var(--font-display)` `--t-micro` weight 600 uppercase `var(--track-label)` |
| Text — secondary | `color: var(--ink-dim)` |
| Spacing | ellipsis; `max-width: 100%` |
| Hover state | none |
| Shadow | none |
| Accent usage | none |

**Pattern notes:**
Instrument labels, not body copy. Do not set raw 10–11px when `--t-micro` exists.

---

### `.fig`

File: `src/styles/base.css`
Last updated: 2026-08-14

| Property | Class |
| ---------------- | --------------- |
| Background | none |
| Border | none |
| Border radius | none |
| Text — primary | `var(--font-data)`; tabular-nums; `'zero' 1`; `var(--track-tight)` |
| Text — secondary | none |
| Spacing | none |
| Hover state | none |
| Shadow | none |
| Accent usage | none |

**Pattern notes:**
Every aligned number. Alias `.mono` is the same face. Never `--font-mono`.

---

### `.grid`

File: `src/styles/base.css`
Last updated: 2026-08-14

| Property | Class |
| ---------------- | --------------- |
| Background | `th` sticky `var(--panel-hi)` |
| Border | `th` bottom `var(--hair) solid var(--rule)`; `td` `var(--rule-faint)` |
| Border radius | `0` |
| Text — primary | `td` `var(--ink)`; size `var(--t-small)` |
| Text — secondary | `th` `var(--ink-dim)` weight 700 |
| Spacing | `th` `var(--s3) var(--s4)`; `td` `var(--s2) var(--s4)` |
| Hover state | host row `var(--panel-hi)` |
| Shadow | selected row may add inset `2px 0 0 var(--phosphor)` |
| Accent usage | none on the table chrome |

**Pattern notes:**
Canonical data table. Numeric columns use `.num` (right + tabular). New tables should not invent a second padding scale.

---

### Desk / Options / Flow (2026-08-14 visible pass)

Files: `src/views/DeskView.vue`, `src/views/OptionsView.vue`, `src/views/FlowView.vue`, `src/components/FlowDashboard.vue`, `src/styles/base.css`

| Property | Class |
| ---------------- | --------------- |
| Workspace title | `--t-display` + `--font-display`, not a marketing clamp headline |
| Raised block | `.ticked` + hairline `--rule` + 2px phosphor/semantic left rule |
| KPI / scan / queue | `.ticked`, radius `0`, no hover lift, no wash fill |
| Button primary | `.btn-primary` values: `--phosphor` fill, `--void` text, `--t-micro`, `--density-control-h` |
| Button quiet | `.btn-quiet` values: hairline `--rule`, hover `--panel-hi` |
| Table | `.grid` padding; row hover `--panel-hi` |
| Type | `--t-micro` labels, `--t-tiny` meta, `--t-small` table, `--t-fig` figures |

**Pattern notes:**
Desk KPI tiles, scan console, and authorization queue now use corner ticks. Options no longer overrides Panel background (ticks stay). Flow header and control rail match the same title/button scale. Specialist surfaces (Sectors, Gates, etc.) were not part of this pass.

---

### Sectors rotation chrome

File: `src/views/SectorsView.vue`
Last updated: 2026-08-14

| Property | Class |
| ---------------- | --------------- |
| Panel | `.ticked` via `Panel`; `live` phosphor left edge while the scan is running |
| Meta | `BAR {shortDate} · {source} · {age}` + ` · STALE` in `--warn` only when bar age > 3d |
| Re-run control | existing `.filter-btn` — hairline `--rule`, active `--panel-raise` / `--phosphor` |
| KPI tiles | `.kpi-card` hairline `--rule`, radius `0`; armed `--long` / held `--short` |
| Rotation row | inset 2px `--long` / `--short`; hover `--panel-hi` |
| Type | `.label` / `.fig`; scores `var(--t-small)` |

**Pattern notes:**
Sectors re-runs its own daily panel (`/api/sector-flow`). Do not invent a second refresh button style — reuse `.filter-btn`. Date the bar in the Panel meta, not a new badge language.

---

### Options portfolio calculator

File: `src/components/OptionsCalculator.vue`
Last updated: 2026-08-15

| Property | Class |
| ---------------- | --------------- |
| Workspace | own `/calculator` tab — not embedded on Options |
| Layout | `.calc-desk` book left, allocation + Greeks right |
| Panel | `.ticked` via `Panel`; book + P/L each own `.grid` |
| Controls | `.btn-quiet`; selected `.on` is `--phosphor` text + `--phosphor-wash` |
| Input | `--void-lift` fill, hairline `--rule`, radius `2px`, `--font-data` |
| Table | `.grid` — `th`/`td` inherit desk padding |
| Signed debit / P/L | `--long` credit, `--short` debit |
| Allocation | `.alloc-bar` call `--call` / put `--put`; cash figures signed |
| Payoff | `--long-wash` profit fill, `--short-wash` loss fill, `--ink` stroke, `--rule-hi` zero, `--phosphor` dashed spot, call/put strike dashes; no glow |
| Type | `.label` / `.fig` / Readout |

**Pattern notes:**
The book is a table of signed legs. Presets seed the book; adding or editing a row marks the book custom. Chart geometry lives in `buildPayoffChart` / `bookAllocation`. Do not mount `OptionsCalculator` on Options — hand off to `{ name: 'calculator' }`.

---

### Flow review workspace

File: `src/components/FlowDashboard.vue`
Last updated: 2026-08-15

| Property | Class |
| ---------------- | --------------- |
| Fold order | snapshot strip → index majors → compact book alerts → latest pulse → filters → review table |
| Book alerts | one-line `.alert-tray`; armed uses `--phosphor-wash`; empty is not a hero block |
| Leaders | `.symbol-tape` / `.sym-chip` hairline grid, min-height 52px, no 88px cards |
| Index cards | `.major-card` min-height 228px; call/put identity bar 8px flat fills |
| Call / put | `--call` / `--put` bars and labels; signed lean `--long` / `--short` |
| History | lives in the raw-tape drawer only |

**Pattern notes:**
Index concentration and the latest sample occupy the fold. Watchlist hits are a secondary tape, not a second workspace. Do not restore the empty book-alert explainer or a standalone history panel above the tape.

---

### Setup level headlines

File: `src/views/SuggestView.vue`
Last updated: 2026-08-15

| Property | Class |
| ---------------- | --------------- |
| Background | `.completeness` → `var(--warn-wash)`; complete → `var(--phosphor-wash)` |
| Border | `var(--hair) solid var(--warn)`; complete `var(--phosphor-dim)`; left 3px |
| Text — primary | `.fig` / Readout value → `var(--ink)` |
| Text — secondary | small / sub → `var(--ink-dim)` |
| Spacing | completeness `var(--s3)`; headlines 2-col `var(--s3)` gap |
| Shadow | none |
| Accent usage | complete/ready uses `--phosphor` only |

**Pattern notes:**
Four first-class headlines — Strike, Supports, Invalidation, Take profit zones — sit in the existing Readout grid. Missing values use the dash / "not supplied" marker. Completeness is fail-closed: incomplete or uncalibrated rows stay warn-wash, never ready phosphor. Drawer (`FlowSuggestionDrawer.vue`) uses the same labels and tokens.

---

## Remaining desk debt

Specialist workspaces (Sentiment, Momentum, Fintel, Gates, …) still have some raw 8–13px type and hairline-only KPI cards. Touch those when those views are next redesigned.
