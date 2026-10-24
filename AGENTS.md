# AGENTS.md

Guidance for autonomous agents working in the TradeCentral repository.

## Repository overview

TradeCentral is a local-first quantitative market research and decision-support
workstation for US equities and options. It combines a Vue 3 + TypeScript
operator dashboard (`dashboard/`) with a Python research/API stack
(`research/`, `daily_plays/`, `tools/`, `eval/`).

The checked-in pipeline is decision support only; it does not place or route
broker orders.

## Checkout convention

The internal Python/runtime namespace is `edge`. Several launchers assume the
repository is checked out as an `edge/` directory inside a workspace root:

```bash
mkdir tradecentral-workspace
cd tradecentral-workspace
git clone git@github.com:syrilj/tradecentral.git edge
```

## Prerequisites

- Python 3.10+ (the frozen research environment is Python 3.10)
- Node.js 18+ and npm
- Optional provider credentials in a local `.env` (see `.env.example`)

## Setup

```bash
# From the workspace root (repo checked out as edge/)
cp edge/.env.example edge/.env   # fill in only the providers you use

# Frontend dependencies
cd edge/dashboard
npm install
```

## Build

```bash
# Production build (type-checks with vue-tsc, then Vite build)
cd edge/dashboard
npm run build

# Fast build without type-checking
npm run build:fast
```

## Run

```bash
# Build the SPA and serve the API + compiled dashboard on localhost:8787
bash edge/tools/run_dashboard.sh

# Development mode: Vite HMR on localhost:5178, /api proxied to localhost:8787
bash edge/tools/run_dashboard.sh --dev

# Serve an existing build without rebuilding
bash edge/tools/run_dashboard.sh --serve
```

The API binds to `127.0.0.1` by default. Do not expose it to a LAN or the
public internet.

## Test

```bash
# Frontend (Vitest)
cd edge/dashboard
npm test                 # vitest run
npm run test:coverage    # vitest run with coverage thresholds

# Python (pytest)
cd <workspace-root>
python3 -m pytest edge/eval -q          # core leak-resistance checks
python3 -m pytest edge/tests -q        # full suite (needs research env)
```

## Lint and format

```bash
# Frontend
cd edge/dashboard
npm run lint            # ESLint
npm run format          # Prettier write
npm run format:check    # Prettier check

# Python
ruff check .            # lint
ruff format .           # format
black --check .         # format check (Black-compatible)
```

Pre-commit hooks run these automatically on staged files. Install them with:

```bash
pre-commit install
```

## Conventions

- TypeScript: `strict` mode is on; keep `noUnusedLocals`/`noUnusedParameters` clean.
- Python: follow ruff (E, F, I, UP) rules; use `edge` as the package namespace.
- Missing data renders as an explicit missing/stale state, never a fake zero.
- Keep provider-specific payloads behind adapter boundaries (`daily_plays/adapters/`).
- Do not commit `.env`, private keys, provider tokens, model binaries, or generated
  market data (`data/`, `runs/` are gitignored).
- Research evidence, diagnostics, and decision authorization are separate concepts.

## CI

`.github/workflows/ci.yml` runs lint, type-check, and tests with coverage
thresholds on every push and pull request.

## Cursor Cloud specific instructions

Cloud Agent checkouts are the repository root (`/workspace`), not a parent
directory that contains `edge/`. `tools/api_server.py` resolves the checkout as
`<parent>/edge`, and `pytest.ini` adds that parent to `sys.path`. The
environment install links `/edge` to the checkout and creates
`/opt/tradecentral/venv` (Python 3.12, which satisfies the 3.10+ requirement).
`python3`, `pip`, `pytest`, and `ruff` on `PATH` are wrappers for that venv, so
`import edge` works from the repo root. Run pytest the way CI does, from the
repo root: `python3 -m pytest eval -q` and
`python3 -m pytest tests -q -m "not needs_market_data_files and not needs_live_network"`.
`python3 -m pytest edge/eval` only works when the current directory is the
parent of a checkout named `edge`.

Dev servers start on boot and bind to loopback only. They set
`EDGE_AUTH_MODE=local` and `VITE_EDGE_AUTH_MODE=local`, so the desk opens
without Clerk or provider keys. API: `http://127.0.0.1:8787` (`/api/health`).
Vite: `http://127.0.0.1:5178`, proxying `/api`. `data/` is gitignored, so a
fresh checkout reports market stores as missing. Keys in `.env.example` stay
optional.
