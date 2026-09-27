# Phase dashboard — UI Review

**Audited:** 2026-08-11  
**Baseline:** [`DESIGN.md`](DESIGN.md) approved design contract  
**Screenshots:** not captured (no dev server responding on localhost ports 3000, 5173, 8080, or documented port 5178)

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 2/4 | Analytical views use concrete, source-aware language, but the root route uses promotional claims and `JOIN THE EDGE` CTAs that contradict the research-instrument contract. |
| 2. Visuals | 2/4 | The shared shell and chart primitives are instrument-like; Landing and Options introduce competing marketing/card-heavy visual systems. |
| 3. Color | 1/4 | Options locally replaces the approved token palette with saturated blue/green values, gradients, rounded cards, and elevated shadows. |
| 4. Typography | 2/4 | Token roles are well defined, but 8–10px local type is pervasive and Landing adds 58–96px promotional headlines outside the approved 11–36px scale. |
| 5. Spacing | 3/4 | Shell geometry and common panels use the 4px tokens, though view-local CSS frequently bypasses the declared scale and table variants have drifted. |
| 6. Experience Design | 2/4 | Loading, error, stale, proxy, and unavailable states are unusually strong, but many common row/chart interactions are mouse-only and the 3D view can render a default model without inputs. |

**Overall: 12/24**

---

## Top 3 Priority Fixes

1. **Make `/` an operator entry point, not a consumer-finance landing page** — the first experience implies sign-up, “actionable insight,” and illustrative market claims instead of showing measured evidence — redirect `/` to Desk, or move Landing outside the operator dashboard and rewrite it around research-only boundaries.
2. **Remove the Options workspace’s private blue/neon token override** — one primary workspace no longer shares the shell’s semantic colors, density, or panel language, so meanings shift as operators navigate — inherit `tokens.css`; replace local gradients, radii, and shadows with `--panel`, rules, and the approved sage/call/put colors.
3. **Make data exploration keyboard-operable** — users who navigate by keyboard cannot open numerous actionable table rows or inspect the Graph chart — replace clickable rows/SVG marks with buttons or links, or add explicit `tabindex`, roles, Enter/Space handlers, and visible focus treatment.

---

## Follow-up Remediation

Applied after this audit:

- The overview was rewritten to the instrument contract: `JOIN THE EDGE` campaign copy, the abstract liquidity-map SVG, and the illustrative market board were removed. The page now reports measured instrument state from the local API (session, data as-of, gate verdicts, readiness, shadow progress) with explicit unavailable/stale handling, and its type, spacing, and surfaces are back on the shared token scale. A source gate (`landing-contract.test.ts`) keeps the promotional patterns from returning.
- `/` now opens this contract-compliant overview as the application entry point (product decision, post-audit), with `/about` redirecting to it. The Desk remains the operator workspace one click away at `/desk`; because the overview is now measured state rather than marketing surface, the original "operator entry point" concern no longer applies.
- The Options workspace now inherits the shared instrument palette and uses flat shared panel surfaces; its non-order `LONG IT` control is now an informational `SETUP WATCH` label.
- The 3D probability surface is disabled unless the measured ATM IV and expiry inputs are available; fallback spot, IV, and horizon values were removed from the renderer.
- The global stage, Market search, and command-palette input again retain a visible phosphor focus treatment. The mobile status strip now uses a compact session-state treatment.

Remaining work:

- Keyboard-equivalent controls for the data rows and Graph marks require a focused interaction pass across the affected workspaces.

---

## Detailed Findings

### Pillar 1: Copywriting (2/4)

- Strong: primary analytical views state data limitations instead of concealing them. `format.ts:4-6` establishes the `—` missing-value rule; `OptionsView.vue:1023-1040` explains why gamma is unmeasured and how to resolve it; `FlowStateView.vue:342-371` distinguishes loading, failed refresh, and stale artifacts.
- Strong: source-specific empty/error text is concrete, for example `SearchPalette.vue:190-196`, `FlowView.vue:352-413`, and `ChangepointsView.vue:743-748` tell the operator what is absent and what to inspect next.
- Contract gap: the root route uses campaign copy — `JOIN THE EDGE` at `LandingView.vue:97-100`, `114-115`, and `345`; “actionable insight” at `LandingView.vue:69` and `109-110`. This conflicts with the approved labels and the research-only operating posture in `DESIGN.md` §§1, 17, and 24.
- Contract gap: `OptionsView.vue:1017-1019` labels a non-order action `LONG IT`. The title caveat helps, but a button-style label should name the actual inspection action, such as `Inspect long setup`.

### Pillar 2: Visuals (2/4)

- Strong: the global shell establishes one stable rail, status strip, and stage (`App.vue:237-443`), preserves a skip link (`239`), and gives the five primary operator jobs a coherent navigation system (`22-41`, `253-303`). The deterministic Graph layout and its explicit collapsed-tail treatment are also a good example of information-first hierarchy (`GraphView.vue:40-83`, `543-579`).
- Strong: analytical chart components visibly label the relevant axes and signed context: `GammaExposureMap.vue:539-559`, `OptionsDriftChart.vue:523-599`, and `ProbabilityDensityChart.vue:327-364`.
- Contract gap: Landing is a full marketing surface with a 96px headline (`LandingView.vue:503-511`), abstract global-liquidity map and filters (`131-203`), decorative “signal promise” cards (`213-222`), and an illustrative market board (`269-335`). It is materially different from the calibrated, dense operator terminal required by `DESIGN.md` §§1, 5, and 10.
- Contract gap: the Options workspace changes the common panel anatomy into rounded, shadowed card stacks (`OptionsView.vue:1649-1663`, `1710-1721`, `2217-2237`), rather than using the shared `Panel` system. This makes a primary workspace look like a separate product.

### Pillar 3: Color (1/4)

- Static usage count across Vue/CSS: `var(--phosphor` 418 references; `--warn` 133; `--call` 127; `--short` 102; `--put` 91; and `--long` 78. Most components apply the semantic roles correctly: signed quantity colors in `TrajectoryChart.vue:338-341`, option-right colors in `GammaExposureMap.vue:505-517`, and explicit stale/proxy treatment in `OptionsView.vue:675-705`.
- Critical contract divergence: `OptionsView.vue:1604-1636` overrides every core surface, ink, accent, signed, call/put, and warning token with hard-coded values. It changes phosphor from the approved sage to high-saturation green and adopts a blue-black palette. This violates the single shared token source required by `DESIGN.md` §§6–7 and 27.
- Critical contract divergence: the same view adds decorative radial/linear gradients at `OptionsView.vue:1644-1646`, gradient panels and deep shadows at `1649-1655`, and more gradient/card treatments at `1710-1721`, `1972-1982`, and `2226-2237`. The contract explicitly prohibits decorative gradients, glow-like elevation, and consumer card chrome.
- Landing also adds decorative gradients (`LandingView.vue:397-405`, `615-626`, `770-789`). Its SVG uses blur and turbulence filters (`131-140`, `159-170`), which is counter to the restrained, non-neon visual rule.

### Pillar 4: Typography (2/4)

- Strong: the token scale in `styles/tokens.css:119-144` matches the approved font roles and uses tabular data typography. `base.css:107-117` applies the data face and tabular figures globally; shared `Readout.vue:17-21` keeps label/value/sub-value hierarchy consistent.
- Static scan: token sizes remain common (`--t-small` 76 references, `--t-micro` 56, `--t-tiny` 26), but raw values proliferate: `9px` 59 times, `10px` 35, `8px` 17, and `11px` 17. The approved lower bound is the 11px micro role (`DESIGN.md` §8), so 8–10px labels should be consolidated or increased.
- Contract gap: Landing’s `clamp(64px, 6vw, 96px)` headline (`LandingView.vue:503-510`) and 38–58px section headings (`654-662`) violate the 18px view-title/36px large-figure ceiling. The Options symbol at `OptionsView.vue:1729-1733` is also outside the normal workspace hierarchy.

### Pillar 5: Spacing (3/4)

- Strong: the shell uses the declared rail, strip, row, and spacing tokens (`App.vue:447-465`, `688-846`; `styles/tokens.css:136-163`). `Panel.vue:45-120` and the canonical table in `base.css:225-259` provide a sound shared baseline.
- Static scan: raw spacing literals recur extensively (145 occurrences of `8px`, 129 of `6px`, 112 of `10px`, and 94 of `9px`). Some are valid borders or tiny icon geometry, but significant layout examples are off-scale: `OptionsView.vue:1637-1643` (10px gap, 16px/32px padding), `1711-1719` (8px/10px command strip), and `LandingView.vue:474-480` (42px gap, 78px padding).
- The comments in `base.css:213-223` acknowledge hand-rolled table drift; seven scoped copies remain deliberately distinct. Migrate active tables to the canonical `.grid` rules when each workspace is touched, then delete the obsolete local copies.

### Pillar 6: Experience Design (2/4)

- Strong: `useResource.ts:19-27` and `61-89` preserve last-good data on refresh failure, pause background polling, and avoid stale response races. This is carried through to visible UI in `App.vue:421-435`, `OptionsView.vue:924-949`, `FlowStateView.vue:342-371`, `FintelView.vue:285-286`, and `SentimentView.vue:552-635`.
- Strong: the Options workspace clearly separates live, stale, historical, proxy, missing, and unmeasured states (`OptionsView.vue:630-705`, `833-870`, `1022-1043`), matching the contract’s most important data-semantics rule.
- Accessibility gap: numerous table rows are clickable but have no semantic role, keyboard handler, or focusability, including `DeskView.vue:528`, `622`, `693`, and `796`; `SectorsView.vue:283`; `SentimentView.vue:455`, `480`, `609`, `655`, `688`, and `720`; and `AnomaliesView.vue:143`, `192`, `219`, `243`, and `268`. In contrast, `OptionsConvictionBoard.vue:155-165` demonstrates the intended semantic/keyboard pattern.
- Accessibility gap: Graph’s selectable SVG sectors and node ticks are mouse-only (`GraphView.vue:384-415`), as are its click rows (`445-461`, `489-498`). Provide focusable controls plus an equivalent selectable table/list and a text summary of the graph.
- Data-integrity gap: switching to `3D MODEL` is always allowed (`ProbabilityDensityChart.vue:264`, `267-302`), while `RiskNeutral3DModel.vue:110-113` substitutes spot `100`, IV `0.25`, and horizon `30` when input is absent. The corresponding 2D view correctly says `Need ATM IV + expiry` (`ProbabilityDensityChart.vue:304-365`). Disable 3D until the same inputs exist; never render a default financial model.
- Focus gap: `App.vue:847`, `MarketView.vue:671`, and `SearchPalette.vue:253` suppress default focus outlines without adding a component-level replacement. Keep the global phosphor focus ring, especially for search and the skip-link target.
- Motion note: `tokens.css:183-188` correctly honors reduced motion, but the 3D renderer continuously animates with `requestAnimationFrame` (`RiskNeutral3DModel.vue:266-271`) even for a static model. Render only on interaction/data changes or pause when the view is not visible.

---

## Files Audited

- Shell, routing, data and styling: `dashboard/src/App.vue`, `main.ts`, `router.ts`, `api.ts`, `format.ts`, `composables/useResource.ts`, `composables/useChartSize.ts`, `styles/base.css`, and `styles/tokens.css`.
- Shared UI: all components under `dashboard/src/components/`, including the search, panel, readout, loading, verdict, options, gamma, probability, 3D risk, and trajectory components.
- Routed workspaces: all views under `dashboard/src/views/`, including Desk, Market, Options, Flow, Research, Sectors, Pulse/Sentiment, Momentum, Fintel, Gates, Evolution, Live Blend/Adaptive, Graph, Breaks/Changepoints, Cloud, Flow State, Anomalies, and Landing.
- Chart primitives: `dashboard/src/charts/index.ts`, `path.ts`, `scale.ts`, and `stats.ts`.
- Registry audit skipped: no root `components.json` (shadcn not initialized).
