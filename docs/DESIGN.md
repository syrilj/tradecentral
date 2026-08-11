# TradeCentral Interface and Design System

Status: living product/design specification  
Scope: operator dashboard, data visualization, interaction patterns, and visual semantics

## 1. Design position

TradeCentral is a quantitative research instrument. It should read like software used to inspect evidence and make disciplined decisions, not like a consumer finance app, a gaming dashboard, or a generic AI-generated admin panel.

The visual language is based on five ideas:

1. **Data before decoration.** The strongest visual object on a screen should normally be the information the operator is trying to compare.
2. **Semantics before color.** Color is reserved for states with stable meanings; it is not used to make empty chrome look more interesting.
3. **Hierarchy before density.** Dense screens are acceptable only when grouping, alignment, typography, and spacing make the reading order obvious.
4. **Uncertainty must remain visible.** Missing, stale, proxy, degraded, unavailable, and research-only states are part of the data model, not cosmetic edge cases.
5. **One navigation system.** Do not duplicate the same routes in competing sidebars, top tabs, cards, and command menus.

The current design tokens live in `dashboard/src/styles/tokens.css`. This document defines how those tokens should be used and what the interface should communicate.

## 2. Product experience goals

A good TradeCentral screen should let an operator answer these questions quickly:

- What am I looking at?
- What changed?
- What matters most?
- What is measured versus inferred?
- How fresh is the data?
- What is bullish, bearish, neutral, or simply unknown?
- Which source produced the value?
- What should I inspect next?
- Is this research evidence, a diagnostic, or a decision-support output?

If a screen cannot answer those questions without reading tooltips or guessing from color, the design is not complete.

## 3. Information architecture

### 3.1 Primary workspaces

The shell should keep the highest-frequency jobs in a small, stable primary set:

| Workspace | Operator question |
|---|---|
| **Desk** | What is the market posture and what needs attention now? |
| **Market** | What is happening in this symbol and relative to peers? |
| **Options** | What is the positioning/structure for one underlier? |
| **Flow** | Where is market-wide activity concentrating? |
| **Research** | What methods, models, gates, and diagnostics support the claims? |

These five workspaces are the primary navigation model already represented in `App.vue`.

### 3.2 Specialist surfaces

Specialist routes belong in one secondary system rather than competing with the primary workspaces:

- Sectors
- Pulse
- Momentum
- Fintel
- Gates
- Evolution
- Live Blend
- Graph
- Breaks
- Cloud

The secondary system may be a `More` menu, secondary rail, or grouped research menu, but it should not duplicate the full primary route set.

### 3.3 Route consolidation

When a function becomes a tab within an existing workspace, the legacy route should redirect into that workspace instead of keeping a second independent version.

The existing `/anomalies -> /sentiment?tab=outliers` and `/flow-state -> /flow?tab=states` pattern is the preferred direction.

## 4. Shell anatomy

The shell has three structural regions:

1. **Navigation rail** — workspace switching and persistent system identity/state.
2. **Status strip** — market session, readiness, warnings, high-level conditions, search access.
3. **Stage** — the active workspace.

The current design tokens define:

- navigation rail width: `80px`;
- top/status strip height: `60px`;
- compact row height: `28px`;
- comfortable row height: `36px`.

These values create a dense desktop instrument. New surfaces should work inside this geometry before inventing additional global sidebars or headers.

## 5. Reading hierarchy

Every routed view should follow the same hierarchy.

### Level 1: workspace identity

A concise title plus one short line explaining the question the workspace answers. Avoid oversized marketing headlines.

### Level 2: decision context

The current symbol, time window, market session, filter set, model/gate version, or relevant mode should be visible before the main chart/table.

### Level 3: primary evidence

The main analytical object: chart, ranked board, exposure map, factor profile, flow board, or gate matrix.

### Level 4: supporting evidence

Secondary plots, distributions, component breakdowns, source details, and diagnostics.

### Level 5: provenance and caveats

As-of timestamps, source identifiers, proxy/degraded labels, methodology notes, and research-only warnings.

A view should not place low-value summary cards above the analytical object simply because cards are easy to build.

## 6. Surface and border system

The interface is dark and neutral. Panels are separated with structure, not glow.

Core surfaces:

| Token | Role |
|---|---|
| `--void` | canvas/background |
| `--void-lift` | base shell lift |
| `--panel` | default panel |
| `--panel-hi` | overlay/high panel |
| `--panel-raise` | selected/raised local surface |
| `--rule` | standard structural line |
| `--rule-hi` | emphasized boundary |
| `--rule-faint` | quiet internal separation |

### Rules

- Prefer one-pixel rules to shadowed card stacks.
- Use spacing plus alignment before adding containers.
- Do not round every object into a card.
- Do not use large-radius consumer UI pills for ordinary metadata.
- Do not use glassmorphism, blurred backgrounds, or translucent neon surfaces.
- Use stronger borders only when the information architecture changes, not around every metric.

The visual reference is a calibrated instrument panel: precise, quiet, and legible.

## 7. Color semantics

Color must encode a specific meaning.

### 7.1 Live/focus accent

`--phosphor: #a9c46c`

Use only for:

- selected navigation;
- keyboard focus;
- current/live measured state;
- active controls;
- the one value that needs to read as live/selected.

Do not use the accent as generic decoration across every chart and label.

### 7.2 Signed direction

| Meaning | Token | Value |
|---|---|---|
| Positive / long | `--long` | `#4fae80` |
| Negative / short | `--short` | `#cf5f6b` |

Green and red are reserved for signed quantities and verdict semantics. They should never mean ordinary navigation, hover, or decorative emphasis.

### 7.3 Option right

Options need a semantic channel separate from bullish/bearish direction.

| Meaning | Token | Value |
|---|---|---|
| Call identity | `--call` | `#5b95b5` |
| Put identity | `--put` | `#c1955e` |

A call is not automatically bullish evidence and a put is not automatically bearish evidence. The UI must preserve that distinction.

### 7.4 Warning and halt

- `--warn` indicates caution, partial quality, stale state, or an operator warning.
- `--halt` indicates blocked/failed/unsafe state.

Warnings should explain the reason in text. Color alone is never sufficient.

### 7.5 Categorical color

The `--cat-*` ramp is for nominal categories such as graph communities. It should not be reused for arbitrary dashboard decoration.

## 8. Typography

TradeCentral uses three typography roles.

| Role | Font token | Use |
|---|---|---|
| Display / instrument label | `--font-display` | workspace title, section identity, compact uppercase labels |
| UI | `--font-ui` | explanatory text, controls, menus |
| Data | `--font-data` | prices, percentages, timestamps, tabular metrics |

### Rules

- All aligned numerical columns use tabular/monospace data type.
- Do not use wide tracking on large bodies of text.
- Uppercase is for small labels, not entire paragraphs.
- Important figures gain hierarchy through size/weight/alignment, not glow.
- A metric label and metric value must be visually distinct.

Current type scale:

- micro: 11px
- tiny: 12px
- small: 13px
- body: 14px
- lead: 16px
- figure: 22px
- large figure: 36px
- view title: 18px

The dashboard is an instrument, so giant 48–72px dashboard headlines are usually inappropriate.

## 9. Spacing and density

The spacing system uses a 4px base:

`4 / 8 / 12 / 16 / 24 / 32 / 48 / 64`

Use spacing to express grouping:

- 4–8px: tightly related labels and values;
- 12–16px: component internals;
- 24–32px: sections;
- 48px+: major workspace separation.

### Compact mode

Default for active desk use. Tables and boards prioritize scan speed.

### Comfortable mode

Used for review, presentation, or slower analytical work. It should change spacing and row height, not the information architecture.

Do not create separate compact and comfortable components. Density belongs in tokens.

## 10. Panel composition

A panel should have a reason to exist.

Recommended anatomy:

```text
[eyebrow / source]                 [as-of / state]
Primary title                      Optional control
Short methodology/context line
--------------------------------------------------
Primary chart / table / figure
--------------------------------------------------
Supporting readouts / legend / provenance
```

A panel should not contain:

- a title that restates the page title;
- three decorative KPI tiles before the real chart;
- icons with no semantic meaning;
- repeated descriptions that belong in the workspace header;
- bright full-width color fills simply to create hierarchy.

## 11. Readouts and KPIs

A readout is appropriate when one number deserves isolated emphasis.

Every readout should include, as applicable:

- label;
- value;
- unit;
- comparison/baseline;
- time horizon;
- source/as-of;
- quality state.

Bad:

```text
SQUEEZE
82
```

Better:

```text
Squeeze pressure
82 / 100
Cross-sectional percentile: 94th
As of 14:31:00Z · options + short-interest inputs
```

The user should not need to infer the unit or direction from styling.

## 12. Data tables

Tables are a first-class analytical surface.

### Required behavior

- stable column alignment;
- explicit units in headers or cells;
- sortable columns where rank matters;
- sticky headers for long tables;
- right-aligned numeric values;
- consistent decimal precision by column;
- visible missing values as `—`;
- provenance/quality state for proxy or delayed fields;
- row hover that helps tracking without recoloring the entire row aggressively.

### Precision

Precision should match the data's actual meaning. Do not show four decimals because they are available in the payload.

Examples:

- prices: enough decimals for the instrument;
- percentages: usually 1–2 decimals;
- ratios/scores: document the scale;
- timestamps: seconds only when operationally relevant.

## 13. Missing, stale, degraded, and proxy data

These states must be visually distinct.

### Missing

Render `—` and, when relevant, explain why no value exists.

Never turn missing into `0`, `0.0%`, or an empty bar.

### Stale

Keep the last known good value, reduce emphasis slightly, and add an explicit stale/as-of marker.

### Degraded

The system has data, but its quality or provider path is weaker than normal. Mark the quality and explain which capability is missing.

### Proxy

A proxy is an approximation of another concept. Label it as a proxy near the value or chart legend. Do not allow a proxy visualization to look identical to direct measurement.

### Unavailable artifact

For offline research artifacts that have not been generated, show:

- unavailable state;
- reason;
- artifact name;
- command or workflow needed to create it when appropriate.

Do not show a fake empty chart.

## 14. Charts

Charts must answer a concrete analytical question.

### 14.1 General rules

- Every axis needs a unit.
- Every encoded color needs a stable meaning.
- A legend is required when the meaning is not obvious from direct labels.
- Zero lines should be visible when sign matters.
- Comparison series should share a justified scale.
- Show the as-of/window context near the chart.
- Avoid more than one major visual encoding per mark unless the second encoding is necessary.
- Prefer direct labels to distant legends for small series counts.

### 14.2 No decorative gradients

A gradient implies an encoded continuum. Do not use a gradient simply to make a bar or line look more polished.

### 14.3 No neon/glow

Do not use:

- outer glows;
- neon shadows;
- bloom effects;
- high-saturation cyan/purple as generic “finance” chrome;
- blinking/pulsing animation except for a narrowly justified critical live state.

Emphasis comes from contrast, position, stroke weight, and flat fills.

### 14.4 Bullish/bearish balance

A chart that contains both positive and negative evidence must make both sides visually comparable.

Do not give bullish evidence a full graphic while reducing bearish evidence to a small red label, or vice versa.

### 14.5 Distribution before verdict

When a score comes from multiple inputs, prefer showing:

- the component contributions;
- the reference distribution/percentile;
- the confidence/quality;
- then the summary score.

This makes the metric inspectable rather than mystical.

## 15. Options-specific visualization rules

Options data is easy to misrepresent. The UI must keep these dimensions separate:

- call versus put;
- bought versus sold/aggressor direction when known;
- volume versus open interest;
- premium/notional versus contract count;
- strike and expiry;
- gamma exposure versus flow;
- observed versus inferred dealer positioning.

### GEX

A GEX view should show:

- zero gamma / pivot level when available;
- positive and negative exposure on a signed axis;
- concentration by strike;
- current spot location;
- expiry/window context;
- whether dealer sign is observed or inferred;
- units.

Do not use a generic gauge when the actual topology across strikes is what matters.

### Squeeze/pressure metrics

A squeeze score must state what it measures. If it combines short interest, borrow, options positioning, volume, and price behavior, expose those components.

The main visual should explain *why* pressure is high or low, not only display a final number.

## 16. Flow-specific visualization rules

Market-wide flow should emphasize ranking and concentration.

Recommended hierarchy:

1. market/sector posture;
2. ranked symbols or clusters;
3. premium/volume context;
4. call/put identity;
5. unusualness relative to baseline;
6. source/freshness.

A whole-market flow board should not look identical to the single-underlier Options workspace. They answer different questions.

## 17. Research and gate visualization

Research UI must resist the temptation to turn scientific evidence into gamified scores.

### Gates

A gate should display:

- gate name/version;
- preregistration source;
- final verdict;
- each criterion;
- threshold;
- observed value;
- pass/fail/unknown;
- artifact timestamp/hash when available.

The verdict is the result of the criteria. It is not a decorative badge independent of them.

### Model diagnostics

When displaying model quality, show the actual evidence type:

- IC and t-stat;
- calibration/ECE;
- win rate with sample count/interval;
- expectancy after costs;
- turnover;
- drawdown;
- regime sensitivity;
- out-of-sample period.

Do not collapse incompatible metrics into one “AI confidence” score.

## 18. Navigation behavior

### Primary rail

Use stable icons and labels for the five primary workspaces. Active state should be obvious without filling the entire rail with color.

### Secondary menu

Specialist tools should be grouped by job, for example:

**Market diagnostics**
- Sectors
- Pulse
- Momentum
- Fintel

**Research and governance**
- Gates
- Evolution
- Live Blend
- Graph
- Breaks
- Cloud

This grouping is more informative than an undifferentiated list of fourteen icons.

### Search

`Cmd/Ctrl + K` and `/` should open global symbol search. Search should route the symbol into the current compatible workspace where possible instead of always forcing a new page.

## 19. Interaction design

### Controls

- Use segmented controls only when options are mutually exclusive and few.
- Use select menus for larger finite sets.
- Use tabs for different views of the same underlying analytical object.
- Use routes for different operator jobs.
- Use buttons for actions, not navigation disguised as actions.

### Hover

Hover can reveal detail but must not be required for basic interpretation.

### Tooltips

Tooltips should explain methodology or exact values, not compensate for missing axis labels or missing units.

### Loading

Prefer stable skeleton/layout placeholders that preserve geometry. Avoid full-screen spinners for individual panel refreshes.

### Mutation actions

Actions that fetch/capture/backfill provider data should clearly indicate:

- what will change;
- source/provider;
- expected scope;
- completion or failure;
- resulting as-of timestamp.

## 20. Motion

Motion is functional, restrained, and short.

Current tokens:

- fast: 120ms
- standard: 220ms
- slow: 480ms

Use motion for:

- menu opening;
- focus movement;
- small state transitions;
- chart updates when they improve tracking.

Do not use continuous ambient animation, shimmering cards, floating particles, or bouncing status indicators.

Respect `prefers-reduced-motion` and allow motion duration to collapse to zero.

## 21. Accessibility

Financial density is not an excuse for inaccessible UI.

Required practices:

- keyboard navigation for global and frequent actions;
- visible focus state;
- semantic HTML for nav, tables, headings, buttons, and form controls;
- labels for icon-only controls;
- sufficient text/background contrast;
- color-independent status labels;
- reduced-motion support;
- readable hit targets even in compact mode;
- screen-reader text for chart summaries when practical.

The shell already includes a skip link; new global structure should preserve it.

## 22. Responsive strategy

TradeCentral is desktop-first. It should not pretend a dense multi-panel trading/research terminal can be compressed into a phone layout without losing meaning.

### Large desktop

Primary target. Multi-column analytical layouts are acceptable.

### Laptop

Must remain fully usable. Reduce columns before reducing text below the defined type scale.

### Narrow/tablet

Stack panels and preserve table horizontal scrolling where necessary. Keep the analytical relationships intact.

### Phone

Support basic inspection if practical, but do not compromise the desktop information architecture to make every surface phone-native.

## 23. Component contracts

Reusable components should encode semantics, not only appearance.

Examples:

### `Panel`

Owns structural frame, title region, optional source/as-of placement, and empty/error slot behavior.

### `Readout`

Owns label/value/unit/quality presentation and numeric alignment.

### `VerdictChip`

Owns GO/NO-GO/UNKNOWN/RUNNING semantics. It must not be repurposed for unrelated tags.

### `TrajectoryChart`

Owns time-series axes, window context, missing points, and direct comparison semantics.

### `SearchPalette`

Owns global symbol lookup and keyboard interaction.

### `AppIcon`

Owns the icon vocabulary. Do not introduce emoji as application icons.

When a component starts accumulating one-off boolean flags for unrelated screens, the underlying component boundary should be reconsidered.

## 24. Content and labels

Use short, concrete labels.

Prefer:

- `Open interest`
- `Call premium`
- `30D implied range`
- `Data stale · 4m`
- `Proxy · daily bars`
- `Research only`

Avoid:

- `AI Insight`
- `Smart Money Meter`
- `Market Energy`
- `Opportunity Power`
- unexplained abbreviations that only make the interface look technical.

Technical terminology is appropriate when it is the real domain term and the underlying calculation is defined.

## 25. Anti-patterns

Do not introduce the following without a concrete analytical justification:

- duplicate navigation systems;
- neon cyan/purple finance palettes;
- gradients on ordinary bars;
- glowing cards;
- excessive rounded rectangles;
- oversized KPI tile grids;
- emoji icons;
- decorative people/avatars in a research terminal;
- unlabelled gauges;
- red/green used for ordinary navigation;
- charts without units;
- scores without component definitions;
- zeros standing in for missing data;
- hidden stale states;
- “AI confidence” that mixes incompatible evidence types;
- a second component that presents the same metric differently on another page without a reason.

## 26. Design review checklist

Before a dashboard change is considered complete, review it against this list.

### Information architecture

- Is the screen answering one clear operator question?
- Is this a new route, a tab, a panel, or a control for a defensible reason?
- Does it duplicate another navigation or surface?

### Data semantics

- Are units visible?
- Are source and as-of state available?
- Are missing/stale/proxy/degraded states explicit?
- Are observed and inferred values visually distinguished?
- Is a score's scale and composition explained?

### Visual hierarchy

- Is the main analytical object visually dominant?
- Can the screen be scanned without reading every label?
- Is color carrying semantics rather than decoration?
- Is there unnecessary card chrome around information that could be aligned directly?

### Charts

- Are axes and zero/reference lines correct?
- Are positive and negative evidence comparable?
- Are legends/direct labels sufficient?
- Is uncertainty/context shown where it affects interpretation?

### Interaction

- Can frequent actions be used by keyboard?
- Does loading preserve layout?
- Does a failed refresh preserve last-good context and show stale/error state?
- Are mutation actions explicit about what they change?

### Accessibility

- Is focus visible?
- Does the screen work without color alone?
- Are icon-only controls labelled?
- Is reduced motion respected?

## 27. Design ownership

`dashboard/src/styles/tokens.css` is the implementation source of truth for reusable visual tokens. This document is the semantic source of truth for how those tokens should be applied.

When the implementation and this document disagree:

1. determine whether the code intentionally changed the design contract;
2. if yes, update the document in the same PR;
3. if not, treat the code divergence as design debt.

The goal is not pixel uniformity for its own sake. The goal is a terminal where the operator can trust that the same visual treatment means the same thing everywhere.
