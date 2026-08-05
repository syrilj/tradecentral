# edge · instrument

Vue 3 dashboard for the `edge/` research stack. Replaces the string-templated
HTML that `edge/tools/render_dashboard.py` used to emit — that file is still the
signal-aggregation engine, it just no longer builds markup.

## Run it

```bash
bash edge/tools/run_dashboard.sh          # build + serve on :8787
bash edge/tools/run_dashboard.sh --dev    # Vite HMR on :5178 against the live API
bash edge/tools/run_dashboard.sh --serve  # serve an existing build, no rebuild
```

The build lands in `edge/runs/dashboard_dist/`, which `edge/tools/api_server.py`
serves as its SPA root. Fonts are bundled via `@fontsource`, so the panel renders
with the network down. The launcher also installs the pinned operational Python
dependency in `edge/requirements-dashboard.txt`; this is kept separate from the
frozen Vertex training environment. The API binds to `127.0.0.1` only because
its trading context is unauthenticated and must not be exposed to the LAN.

## Views

| | | |
|---|---|---|
| `01` | **Desk** | Quick/Deep market activity scan, live LSE flow flags, PEAD ordinal flags, directional signals, capital interlock |
| `02` | **Market** | Symbol search over the 558-name daily universe, price/growth trajectory with a drawdown underlay, factor loadings, rebased compare basket with a return-correlation matrix |
| `03` | **Sectors** | Sector rotation, relative strength, and flow watch names |
| `04` | **Sentiment** | Positioning, short-volume, and filing sentiment diagnostics |
| `05` | **Anomalies** | Statistical outlier detection and cross-sectional anomaly context |
| `06` | **Options** | Truth-preserving call/put activity overlay, GEX topology, noise audit, and risk-neutral implied ranges |
| `07` | **Gates** | Every pre-registered gate, its verdict, and the individual bars it passed or failed |
| `08` | **Cloud** | Vertex AI custom jobs, artifact storage, credit posture |
| `09` | **Evolution** | Genetic algorithm lab: fitness trajectory, elites, confirmation survivors (research-only) |

`⌘K` opens symbol search from anywhere; number keys jump between views.

## Design notes

The aesthetic is an instrument, not a product — oscilloscope graticules,
printer's registration ticks instead of rounded cards, one phosphor accent that
only ever means "measured now". Green and red are reserved for signed
quantities and are never used for chrome, so a red cell always means a negative
number rather than an error.

Two conventions are load-bearing:

- **Missing renders as `—`, never as `0.00`.** A zero that means "no data" is a
  lie on a trading surface. See `src/format.ts`.
- **A failed refresh keeps the last good data and marks it stale** rather than
  blanking the panel. See `src/composables/useResource.ts`.
- **The XNYS clock comes from exchange session data, not weekday arithmetic.**
  Early closes, holidays, and DST are resolved by `exchange_calendars`; a
  visibly labelled conservative fallback is available for stripped runtimes.

The live-capital interlock sits at the top of the Desk on purpose. Every model
in this stack is currently research-only, and showing candidate trades above
that fact would be an invitation to act on them.

## Layout

```
src/
  api.ts                  typed client for edge/tools/api_server.py
  format.ts               number/date formatting; missing-value discipline
  router.ts
  charts/                 dependency-free SVG scales, paths, statistics
  composables/            polling resource primitive
  components/             Panel, readouts, search, and dependency-free SVG charts
  views/                  Desk, Market, Sectors, Sentiment, Anomalies, Options, Gates, Cloud
  styles/tokens.css       the design system
```

No charting library. `src/charts/` emits SVG path strings directly, which is
both smaller than a chart dependency and means the traces inherit the same CSS
variables as everything else.
