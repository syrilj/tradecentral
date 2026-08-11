# TradeCentral Dashboard

The TradeCentral dashboard is the Vue 3 and TypeScript operator interface for the local quantitative research and decision-support stack.

This file is intentionally limited to frontend/runtime notes. System architecture lives in [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md), and the visual/interaction contract lives in [`../docs/DESIGN.md`](../docs/DESIGN.md).

## Run

From the workspace root, with this repository checked out as `edge/`:

```bash
# Build the SPA and serve it with the local API on :8787
bash edge/tools/run_dashboard.sh

# Vite HMR on :5178, proxying /api to the Python server on :8787
bash edge/tools/run_dashboard.sh --dev

# Serve an existing build without rebuilding
bash edge/tools/run_dashboard.sh --serve
```

The production build is written to `edge/runs/dashboard_dist/` and served by `edge/tools/api_server.py`.

The backend binds to `127.0.0.1`. The current application is a single-operator local research surface and does not provide the authentication required for public/LAN exposure.

## Frontend stack

- Vue 3
- TypeScript
- Vue Router
- Vite
- Vitest
- Dependency-light SVG chart primitives under `src/charts/`
- Three.js only where a surface genuinely requires 3D rendering
- Locally bundled fonts via `@fontsource`

## Source layout

```text
src/
├── api.ts                  Typed client for tools/api_server.py
├── App.vue                 Global shell, polling, navigation, market/readiness state
├── router.ts               Route source of truth
├── format.ts               Number/date formatting and missing-value discipline
├── charts/                 SVG scales, path builders, and statistics
├── composables/            Shared polling/resource behavior
├── components/             Reusable instrument components
├── styles/                 Design tokens and global styles
└── views/                  Routed workspaces
```

## Navigation

The primary operator jobs are:

- Desk
- Market
- Options
- Flow
- Research

Specialist research/diagnostic surfaces are exposed through the secondary navigation. Do not duplicate the full route set into additional sidebars or top tab bars.

`src/router.ts` is the source of truth for the current route inventory. Legacy URLs should redirect into their consolidated workspace when functionality is moved rather than keeping duplicate implementations alive.

## Data behavior

The dashboard follows four non-negotiable rules:

1. Missing values render as `—`, never a fake numeric zero.
2. Failed refreshes preserve the last good data and make stale/error state visible.
3. Source/as-of/quality state must remain available when it affects interpretation.
4. Expensive offline research is read from artifacts; a UI poll must not silently trigger a walk-forward, graph rebuild, or other heavy experiment.

## Design behavior

The UI is a dense institutional research instrument, not a consumer-finance dashboard.

- Neutral dark surfaces
- One restrained live/focus accent
- Green/red reserved for signed quantities
- Separate call/put colors for option identity
- No neon glow, decorative gradients, or generic “AI” chrome
- Tabular data typography for aligned numbers
- Compact and comfortable density from shared tokens
- Keyboard-first global symbol search

See [`../docs/DESIGN.md`](../docs/DESIGN.md) before introducing new global navigation, colors, chart semantics, or component patterns.

## Development

```bash
npm install
npm test
npm run build
```

The production build runs `vue-tsc --noEmit` before Vite compilation. A successful dashboard build validates frontend contracts only; it is not evidence that any research model or strategy is approved for live capital.
