# Technical audit — Regime, Flow, Options

Date: 2026-08-31 · Branch: `vpa/production-hardening`
Scope: `RegimeView.vue` (3,117 L), `FlowView.vue` (252 L) + `FlowDashboard.vue` (7,808 L),
`OptionsView.vue` (6,669 L), plus the 34 components they import — 38 files, ~37,000 lines.

Method: static parse of every template/style/script block in scope, plus **live verification**
against the running dev server on `:5178` (real computed styles, real `Tab` traversal, real
`PerformanceObserver` over a full 15s poll cycle). Contrast numbers below are measured from
rendered pixels with alpha compositing resolved, not inferred from tokens.

Bar for this audit, per operator direction: **WCAG 2.2 AA**, **desktop-only** (responsive
explicitly out of scope and therefore not scored).

---

## Remediation — all findings fixed (2026-08-31)

Everything below was fixed in the same session and verified. Re-measured live
against the running dev server, same method as the original audit:

| Measure | Before | After |
|---|---|---|
| Contrast failures, Options | 248 instances / 29 patterns (worst **1.62:1**) | **0** |
| Contrast failures, Regime | 4 instances / 3 patterns | **0** |
| Contrast failures, Flow | 147 instances / 23 patterns | **0** (see caveat) |
| Smallest rendered text | 7.5 px | **10 px** |
| Options `<h1>` | 0 | **1** |
| Clickable rows with no keyboard path | 2 (Options) — **13 app-wide** | **0** |
| SVGs with no accessible alternative | 11 in scope — **20 app-wide** | **0** |
| Unlabelled form controls | 3 | **0** |
| Focus indicator width | 1 px (fails 2.4.11) | **2 px** |
| `.input-glass` focus indicator | 1.43:1 | **9.5:1** |
| Test suite | 2,106 passing | **2,110 passing** (+4 new a11y guards) |

**Caveat on Flow:** `LSE_API_KEY` is not configured in this environment, so the
market-wide tape renders empty and I could not re-measure Flow with live rows.
Its 147 failures were all driven by tokens and font sizes fixed at source
(`--text-tertiary`, `--ink-ghost`, `.fresh-state`, `.identity-note` at 8 px),
and the same components render clean on Options — but that specific surface is
inferred, not observed. Worth one look when the feed is back.

**Scope note:** the fixes went app-wide, not just to the three audited tabs.
The new guards found 11 more clickable rows and 9 more unlabelled charts in
views outside the audit scope; those are fixed too.

### Correction to this report

The P2 finding *"No `prefers-reduced-motion` guard anywhere, including
`base.css`"* was **wrong**. `tokens.css` already had one, which zeroes every
duration token and forces `animation-iteration-count: 1` globally. The original
scan only checked `base.css` and the component files and did not look in
`tokens.css`, which `base.css` imports. What was actually missing was narrower:
rules that hard-code their own timing (the print-arrival flash, a few 0.4s bar
transitions) bypassed the token-based guard. That existing block has been
extended to cover them rather than a second guard being added.

One other correction: the P3 recommendation to tokenise all 51 `rgba()` literals
was partly wrong. `design-conformance.test.ts` deliberately *permits* structural
white/black `rgba()` inside `linear-gradient()` and flags anything else there as
a decorative gradient — so tokenising those broke the guard. The literals inside
gradients are load-bearing and have been left alone; only the standalone
background and shadow values were tokenised.

### How the fixes were made durable

Four new source-scanning tests in `design-conformance.test.ts`, in the same
style as the existing design guards, so these cannot regress silently:

- no clickable `<tr>` without a focusable control
- `--ink-ghost` never used as a text colour
- no `font-size` below the 10 px floor
- no `<svg>` without a role, label, or `aria-hidden`

Plus one in `options-ui-tokens.test.ts` asserting every ink and signed-quantity
text token clears 4.5:1 against `--panel-raise`, and that `--ink-ghost` stays
below it (proving it is not a text token).

---

## Audit Health Score

| # | Dimension        | Score | Key finding                                                            |
|---|------------------|-------|------------------------------------------------------------------------|
| 1 | Accessibility    | 2/4   | Symbol selection in Options is mouse-only (Level A); ~400 sub-AA texts |
| 2 | Performance      | 3/4   | 200 ms long task each poll; 5,532 DOM nodes on Flow                     |
| 3 | Theming          | 3/4   | Zero hex literals in 38 files — but the palette itself encodes sub-AA   |
| 4 | Responsive       | n/a   | Desktop-only by explicit design decision — not scored                   |
| 5 | Anti-Patterns    | 3/4   | Genuinely distinctive; 44 glass surfaces on one page is the one drift   |
| **Total** |          | **11/16** | **Acceptable — work needed, and it is concentrated in one dimension** |

Rebased bands for a 16-point scale: 14.4–16 Excellent · 11.2–13.6 Good · 8–10.4 Acceptable ·
4.8–7.2 Poor · 0–4.8 Critical. At 11/16 this sits at the top of Acceptable, one point below Good.

The score understates the codebase. Three of four scored dimensions are strong and the
engineering discipline is unusually high. Nearly all lost ground is accessibility, and most of
that traces to **two token values** and **two click handlers** — small, mechanical fixes with
outsized score impact.

---

## Anti-Patterns Verdict — **PASS**

Would someone believe "AI made this"? **No.** This is the rare interface with a real point of
view, and the code holds the line the design doc draws.

Measured across all 38 files:

| Tell                                   | Count |
|----------------------------------------|-------|
| Gradient text (`background-clip: text`) | **0** |
| `text-shadow`                           | **0** |
| Glow (`box-shadow: 0 0 Npx`)            | **0** |
| `filter: brightness()` / `drop-shadow`  | **0** |
| Bounce / elastic easing                 | **0** |
| Hard-coded hex in scoped styles         | **0** |

The three `cubic-bezier()` uses are `(0.16, 1, 0.3, 1)` and `(0.22, 1, 0.36, 1)` — ease-out-expo
and ease-out-quint. Those are the *correct* curves, chosen deliberately. Typography is
Geist / Instrument Sans / Martian Mono / IBM Plex, not the Inter-and-shrug default. Panels use
corner ticks rather than rounded drop-shadow cards. Figures are tabular throughout. One accent,
held to its documented meaning.

**The one real tell:** 61 `backdrop-filter` declarations across 8 files; the Options route alone
renders **44 glass surfaces simultaneously**. `tokens.css` states the rule plainly — glass is for
a read-only chip that must lift off a plot "so it never reads as glassmorphism or a neon scrim."
At 44 concurrent instances the exception has become the surface treatment. This is drift from an
intentional system, not slop — but it is the thing to watch.

---

## Executive Summary

- **Audit Health Score: 11/16** (Acceptable, one point below Good)
- **Issues: 1 P0 · 6 P1 · 6 P2 · 3 P3**
- No console errors on any of the three routes.

**Top 5:**

1. **[P0]** Table rows in Options select the active symbol via `@click` on bare `<tr>` — no
   keyboard path at all. This is the primary interaction of two boards. WCAG 2.1.1, Level A.
2. **[P1]** ~400 rendered text instances below AA contrast; worst measured **1.62:1**. Values
   carrying real data (`+$9.03`, `1.9% OTM`, print counts) sit at 2.1–2.6:1.
3. **[P1]** The staleness and provenance chips — the things the design doc says must always stay
   visible — are the *least* legible elements on the page (`STALE` at 3.51:1, `AGE 1h 16m` at 2.5:1).
4. **[P1]** `OptionsView` renders **no `<h1>`** and only 5 `<h2>` across 6,669 lines, with 225
   `class="label"` spans standing in for section headings.
5. **[P1]** 11 of 17 SVG charts expose no accessible alternative — while 3 others in the same
   codebase do it correctly. The pattern exists; it just was not applied evenly.

**Recommended next steps:** fix the P0 first (two `<tr>` elements, ~10 lines). Then raise
`--ink-ghost` and `--ink-faint` at the token level — that single change clears the large majority
of the ~400 contrast failures at once, because the codebase's token discipline is already perfect.

---

## Detailed Findings by Severity

### [P0] Symbol selection in Options is unreachable by keyboard

- **Location**: [OptionsView.vue:3424](dashboard/src/views/OptionsView.vue:3424) and
  [OptionsView.vue:3573](dashboard/src/views/OptionsView.vue:3573)
- **Category**: Accessibility
- **WCAG**: 2.1.1 Keyboard — **Level A**
- **Impact**: Both the flow board and the opportunity board load a symbol via
  `<tr … @click="loadSymbol(row.symbol)">`. The rows carry no `tabindex`, no `role`, no key
  handler, and contain no focusable child. A keyboard or switch user can read both tables and
  select nothing from either. This is the main path into the tab's per-symbol analysis, so the
  route's core job is unavailable without a mouse.
- **Recommendation**: Wrap the first cell's content in a `<button class="row-btn">` that carries
  the handler (keeps native semantics, focus, and Enter/Space for free), or give the row
  `role="button"`, `tabindex="0"` and a `@keydown.enter/.space` handler. The button-in-cell
  approach is preferable and matches `contract-row-btn`, already used elsewhere in this file.
- **Suggested command**: `/harden`

### [P1] ~400 text instances fail AA contrast; worst 1.62:1

- **Location**: measured live — Options 248 instances / 29 patterns; Flow 147 / 23; Regime 4 / 3
- **Category**: Accessibility · Theming
- **WCAG**: 1.4.3 Contrast (Minimum) — Level AA
- **Impact**: Worst offenders on Options, all measured against their true composited background:

  | Element | Text | Size | Ratio |
  |---|---|---|---|
  | `span.prov-sep` | `·` | 11 px | **1.62** |
  | `em.ld-abs` | `—` | 11 px | **2.11** |
  | `span.moneyness-tag` | `1.0% OTM` | 11 px | **2.18** |
  | `em.ld-abs` | `+$9.03` | 11 px | **2.44** |
  | `span.prov-item` | `AGE 1h 16m` | 11 px | **2.50** |
  | `span.tab-count` | `13` | 9 px | **2.56** |
  | `button.label` | `UNUSUAL` | 11 px | **2.58** |
  | `span.moneyness-tag` ×23 | `1.9% OTM` | 11 px | **2.61** |

  These are not decorative. Moneyness, signed price deltas, and print counts are the numbers the
  operator came to compare. `button.label` at 2.58:1 additionally fails 1.4.11 for UI components.
- **Root cause — and why the fix is cheap**: this is a *token* defect, not a usage defect.
  `--ink-ghost` is **2.71:1** on `--void` (fails even the 3:1 large-text floor) and is used as a
  text colour in 46 places. `--ink-faint` / `--text-tertiary` is **4.36:1** — just under the bar —
  and is used in 139 places, overwhelmingly at `--t-micro` (11 px) and below, where 4.5:1 applies.
  Because the codebase never hard-codes colour, raising these two values fixes nearly all of it
  centrally.
- **Recommendation**: lift `--ink-faint` to ≥4.5:1 on `--panel-raise` (the darkest common
  surface, currently 3.40:1) and either lift `--ink-ghost` to ≥4.5:1 or restrict it by contract to
  non-text use (rules, disabled chrome) and migrate its 46 text call-sites to `--ink-faint`.
  Also review the 8 px and 9 px sizes — `.identity-note` and `.tab-count` are below any size at
  which a 4.5:1 ratio is comfortable.
- **Suggested command**: `/colorize`, then `/normalize`

### [P1] Provenance and staleness are the least legible things on screen

- **Location**: `FlowDashboard.vue` `.fresh-state` (3.51:1), `.prov-item` / `.prov-sep` in
  `OptionsView.vue` (2.50 / 1.62:1)
- **Category**: Accessibility · Anti-Pattern (design-contract violation)
- **WCAG**: 1.4.3
- **Impact**: `DESIGN.md` principle 4 states uncertainty "must remain visible… part of the data
  model, not cosmetic edge cases." In practice `STALE`, `AGE 1h 16m`, and the provenance
  separators are rendered at the lowest contrast on the page. An operator can misread stale data
  as live — the single most consequential failure mode this product has. Worth separating from
  the bulk contrast issue because it inverts a stated principle rather than merely missing a ratio.
- **Recommendation**: give staleness and provenance their own token at or above `--ink-dim`
  (7.39:1) and exempt them from the "quiet meta" treatment. Staleness is not meta.
- **Suggested command**: `/clarify`

### [P1] OptionsView has no `<h1>` and almost no heading structure

- **Location**: [OptionsView.vue](dashboard/src/views/OptionsView.vue) — verified live: `h1: 0`, `h2: 5`, `h3: 0`
- **Category**: Accessibility
- **WCAG**: 1.3.1 Info and Relationships (A) · 2.4.6 Headings and Labels (AA)
- **Impact**: 6,669 lines and ~2,570 rendered elements with no page heading and five section
  headings, all inherited from `Panel.vue`. 225 `class="label"` spans carry the visual weight of
  headings without the semantics. Screen-reader users get no document outline for the densest
  surface in the product; heading navigation is effectively unavailable. Regime and Flow both
  render a correct `<h1>`, so Options is the outlier.
- **Recommendation**: add the `<h1>` the other two routes already have, and promote the
  `class="label"` section titles that genuinely start a region to `<h2>`/`<h3>`. Keep the visual
  treatment — this is a semantics change, not a design change.
- **Suggested command**: `/arrange`

### [P1] 11 of 17 SVG charts have no accessible alternative

- **Location**: `CausalEnvelopeChart`, `FlowSummaryDonutCard`, `KalmanKinematicPhasePlot`,
  `NetFlowByExpiryChart`, `NetGammaSpotTimeSeries`, `StrikeGammaExposureChart`,
  `StrikeOpenInterestChart`, `VolatilitySurface3D`, `SqueezeScreener`, `RegimeHeaderRibbon`,
  `FlowDashboard`
- **Category**: Accessibility
- **WCAG**: 1.1.1 Non-text Content — Level A
- **Impact**: No `role`, no `aria-label`, no `<title>`, no table fallback. The charts are the
  analysis on Regime; without an alternative their content is simply absent for screen-reader
  users. Note this is *inconsistency*, not ignorance: `RegimeSurfaceChart` and `GammaExposureMap`
  each ship `role` + `aria-label` + `<title>` + a `<table>` fallback, and `PowerAlertsBoard` and
  `DealerGammaMap` carry `role` + `aria-label`. The house pattern exists and is good.
- **Recommendation**: apply the `RegimeSurfaceChart` pattern to the other 11. The underlying
  series data is already in scope in each component, so the table fallback is mostly mechanical.
- **Suggested command**: `/harden`

### [P1] The Regime tab's primary symbol selector is unlabelled

- **Location**: [RegimeHeaderRibbon.vue:96](dashboard/src/components/RegimeHeaderRibbon.vue:96)
- **Category**: Accessibility
- **WCAG**: 4.1.2 Name, Role, Value (A) · 3.3.2 Labels or Instructions (A)
- **Impact**: The `<select>` that drives the entire Regime workspace has no `aria-label`, no
  `id`/`<label for>` pair, and no wrapping `<label>`. It announces as an unnamed combobox. The
  only nearby text, `US EQUITIES / INDEX`, is a caption beneath it and is not programmatically
  associated. Worth noting the codebase is otherwise good here — 21 of 24 form controls *are*
  correctly wrapped in `<label>`; this is one of only three exceptions.
- **Recommendation**: add `aria-label="Symbol"`, or associate the existing caption via
  `aria-labelledby`.
- **Suggested command**: `/harden`

### [P2] Two more controls lack accessible names

- **Location**: [RealTimeFlowTape.vue:81](dashboard/src/components/RealTimeFlowTape.vue:81) —
  visible `<span>Filter</span>` sits beside the `<select>` but is not associated;
  [OptionsView.vue:3259](dashboard/src/views/OptionsView.vue:3259) — history search input is
  placeholder-only.
- **Category**: Accessibility · **WCAG**: 4.1.2, 3.3.2 (A)
- **Impact**: Placeholder text is not an accessible name and disappears on input.
- **Recommendation**: `<label for>` on the tape filter; `aria-label="Search history"` on the input.
- **Suggested command**: `/harden`

### [P2] Focus indicator fails WCAG 2.2's new focus-appearance rule

- **Location**: `--hair` is `1px` globally; `.input-glass:focus` in `OptionsView.vue`
- **Category**: Accessibility · **WCAG**: 2.4.11 Focus Appearance — **new in 2.2, Level AA**
- **Impact**: Two distinct problems, measured live:
  - `.input-glass:focus` uses `outline: 3px solid color-mix(in srgb, var(--phosphor) 18%, transparent)`,
    which composites to **1.43:1** against the panel — below the required 3:1. Effectively invisible.
  - The `:focus` styles that swap `border-color` to `--phosphor` clear the contrast bar easily
    (7.67:1) but the indicator is only **1 px**; 2.4.11 requires an area at least equal to a 2 px
    perimeter.
- **Credit where due**: the global `:focus-visible { outline: var(--hair) solid var(--phosphor) }`
  works, was confirmed by real `Tab` traversal, and every `outline: none` in scope except one
  supplies a `border-color` replacement. This is a near-miss on a rule new to 2.2, not neglect.
- **Recommendation**: raise `--hair` to 2px in the focus context (or add `outline-offset` plus a
  2px outline), and replace the 18% `color-mix` with solid `--phosphor`.
- **Suggested command**: `/harden`

### [P2] Command-palette input removes its focus ring with no replacement

- **Location**: `.input[data-v-f5dd2217]:focus-visible { outline: none }` (command palette)
- **Category**: Accessibility · **WCAG**: 2.4.7 (AA)
- **Impact**: Specificity 30 beats the global `:focus-visible` (10), and unlike the other five
  `outline: none` rules this one supplies no border or shadow replacement. Mitigated by the input
  being auto-focused and alone in its dialog, which is why this is P2 and not P1.
- **Recommendation**: remove the override, or add a border/shadow replacement.
- **Suggested command**: `/harden`

### [P2] No `prefers-reduced-motion` guard anywhere, including `base.css`

- **Location**: `base.css` (no guard at all); `FlowView.vue` `dot-pulse … infinite`;
  `LoadingState.vue` `spin … infinite`; `OptionsView.vue` `printArrivalFlash`
- **Category**: Accessibility · **WCAG**: 2.2.2 Pause, Stop, Hide (A) for the infinite pulse;
  2.3.3 Animation from Interactions (AAA) for the rest
- **Impact**: The live-dot pulses indefinitely on Flow with no way to stop it. Users with
  vestibular sensitivity have no escape hatch, and there is no global guard to inherit.
- **Recommendation**: add the standard reduced-motion block to `base.css` to cover the whole app
  at once. Three files already guard `prefers-reduced-transparency`, so the pattern is understood
  — it just was not extended to motion.
- **Suggested command**: `/animate`

### [P2] Auto-polling surfaces are silent to screen readers

- **Location**: 3 `aria-live` regions across all 38 files; Options renders 1, Flow 2
- **Category**: Accessibility · **WCAG**: 4.1.3 Status Messages (AA)
- **Impact**: Flow and Options repoll every 15 s and rewrite tables in place. Nothing announces
  that the tape advanced, that a threshold changed the result set, or that data went stale.
- **Recommendation**: `role="status"` on the freshness/print-count region; `aria-live="polite"`
  on the refresh summary. Do not put the whole tape in a live region — announce the summary only.
- **Suggested command**: `/harden`

### [P2] 200 ms long task on every poll cycle

- **Location**: `FlowDashboard.vue` — measured live over a 23 s window spanning ≥1 poll
- **Category**: Performance
- **Impact**: 2 long tasks, 376 ms total blocked, **longest 200 ms**. The main thread stalls for a
  fifth of a second every 15 s; a click landing in that window feels stuck. Likely cause is
  visible in the templates: **210 function calls sit in interpolations** across the three big
  surfaces and re-run on every render — `actionInsight` (68 lines, array ops) ×6,
  `directionRead` (83 lines) ×5, `priceRead` (32 lines) ×5, all in `FlowDashboard`. None are
  memoised; there is no `v-memo`, `v-once`, `shallowRef` or `markRaw` anywhere in scope.
- **Recommendation**: convert `actionInsight`, `directionRead` and `priceRead` to `computed`
  keyed by row, or precompute them into the row objects when the payload lands. The codebase
  already uses `computed` heavily and correctly (48 in this file) — these three just escaped it.
- **Suggested command**: `/optimize`

### [P3] 5,532 DOM elements on the Flow route

- **Category**: Performance
- **Impact**: ~3.7× the 1,500-node figure at which Lighthouse flags excessive DOM size, driven by
  `FLOW_LIMIT = 500` rows. Compounds the long-task cost above. Not urgent on desktop hardware.
- **Recommendation**: virtualise the tape, or page it, once the long-task fix lands.
- **Suggested command**: `/optimize`

### [P3] Three transitions animate layout properties

- **Location**: [OptionsConvictionBoard.vue:372](dashboard/src/components/OptionsConvictionBoard.vue:372) (`width`),
  [SqueezeScreener.vue:527](dashboard/src/components/SqueezeScreener.vue:527) (`left`),
  [SqueezeScreener.vue:936](dashboard/src/components/SqueezeScreener.vue:936) (`width`);
  plus `.tape-search-input:focus { width: 220px }`
- **Category**: Performance
- **Impact**: Layout + paint per frame instead of compositor-only. Three instances in ~37,000
  lines is a very low rate — noted for completeness.
- **Recommendation**: `transform: scaleX()` with `transform-origin: left` for the bars.
- **Suggested command**: `/animate`

### [P3] 51 rgba() literals duplicate existing tokens

- **Location**: `FlowDashboard.vue` (27), `DealerGammaMap.vue` (7), `Panel.vue` (6), others
- **Category**: Theming
- **Impact**: All are neutral white/black alpha for washes (26), shadows (21) and strokes (4), so
  nothing breaks — but `rgba(255,255,255,0.02)` recurs as a de-facto untokenised wash while
  `--glass-*` and `--phosphor-wash` already exist. Against a file set with **zero** hex literals,
  this is the only theming gap.
- **Recommendation**: add `--wash-1/2/3` and `--shadow-1/2` tokens and migrate.
- **Suggested command**: `/normalize`

### [P3] Clickable elements that duplicate a keyboard-reachable control

- **Location**: [FlowDashboard.vue:4025 and 4031](dashboard/src/components/FlowDashboard.vue:4025)
  (`<i>` bar segments); [SectorPairCorrelationCard.vue:107](dashboard/src/components/SectorPairCorrelationCard.vue:107)
  (`<span class="etf-badge">`)
- **Category**: Accessibility
- **Impact**: The two `<i>` segments filter calls/puts with no keyboard path — but sibling
  `<button>` elements immediately above perform the same two actions, so no function is lost.
  The `etf-badge` span is the more real of the three: it switches symbol and has no equivalent.
- **Recommendation**: make `etf-badge` a `<button>`; add `aria-hidden="true"` to the two
  decorative `<i>` segments since their function is already exposed.
- **Suggested command**: `/harden`

---

## Patterns & Systemic Issues

1. **Two token values cause most of the accessibility score.** `--ink-ghost` (2.71:1) and
   `--ink-faint` (4.36:1) account for the large majority of ~400 contrast failures. Because the
   codebase has **zero** hard-coded colours, this is one of the cheapest high-impact fixes
   available — the discipline that makes the audit look bad is the same discipline that makes it
   easy to fix.
2. **Good patterns exist but are unevenly applied.** Accessible charts (5 of 17 correct),
   reduced-transparency guards (3 of 8 glass files), form labelling (21 of 24 correct). The house
   style is right; coverage is the gap. This calls for a lint rule, not a redesign.
3. **Sub-11px type is systemic.** 68 selectors at `--t-micro` (11 px) plus ~30 at 8–10 px. At
   those sizes AA contrast is doing heavy lifting it was not designed for.
4. **Semantics lag visuals on the densest surface.** 225 `class="label"` spans in Options carry
   heading and label meaning without heading or label semantics.
5. **The glass exception has become the rule.** 44 concurrent glass surfaces on Options against a
   token comment authorising it for occasional read-only chips.

---

## Positive Findings

Worth stating plainly: this is materially better-built than most production frontends.

- **Zero hard-coded hex colours across 38 files and ~37,000 lines.** Rare at any scale.
- **Zero AI-slop tells** — no gradient text, glow, text-shadow, brightness filters, or bounce
  easing. The easing curves chosen are the right ones.
- **Perfect resource cleanup.** Every `setInterval`, `requestAnimationFrame`, `addEventListener`
  and `ResizeObserver` in scope is balanced by its teardown — **0 unbalanced across 38 files.**
- **Every `v-for` has a `:key`.** All 47 of them.
- **All 30 routes lazy-loaded** via dynamic import, keeping the 205 KB Options view off the
  initial parse.
- **Explicit "GO LIVE" gating on Regime** — no requests and no timers until the operator asks.
  A genuinely thoughtful choice for a data-cost-sensitive product, and rarer than it should be.
- **A working skip link** as the first tab stop, plus a real `:focus-visible` phosphor ring —
  both confirmed by actual `Tab` traversal, not assumed.
- **Zero icon-only buttons without an accessible name.**
- **No console errors** on any of the three routes.
- **A written, specific, opinionated design contract** in `DESIGN.md` and `tokens.css` — and code
  that mostly honours it. Most of this report is measuring the codebase against its own stated
  standard rather than an external one.

---

## Recommended Actions

1. **[P0] `/harden`** — give the two Options `<tr>` boards a keyboard path. ~10 lines; clears the
   only Level A interaction failure.
2. **[P1] `/colorize`** — raise `--ink-ghost` and `--ink-faint` to clear 4.5:1 on `--panel-raise`.
   One token change resolves most of ~400 failures.
3. **[P1] `/clarify`** — promote staleness and provenance out of the quiet-meta treatment so
   `STALE` is never the faintest thing on screen.
4. **[P1] `/arrange`** — add the missing `<h1>` to Options and promote real section titles to
   headings.
5. **[P1] `/harden`** — apply the existing `RegimeSurfaceChart` accessibility pattern to the 11
   charts missing it; label the Regime symbol `<select>`.
6. **[P2] `/optimize`** — memoise `actionInsight`, `directionRead`, `priceRead` to remove the
   200 ms per-poll stall.
7. **[P2] `/animate`** — add a global `prefers-reduced-motion` block to `base.css`.
8. **[P2] `/harden`** — fix focus appearance: 2px indicator, solid `--phosphor` on `.input-glass`.
9. **[P3] `/normalize`** — tokenise the 51 rgba() literals as `--wash-*` / `--shadow-*`.
10. **[P3] `/quieter`** — reduce concurrent glass surfaces on Options back toward the documented
    "occasional read-only chip" intent.
11. **`/polish`** — final pass once the above land.
