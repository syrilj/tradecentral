#!/usr/bin/env bash
# run_dashboard.sh — build the Vue instrument panel and serve it with the live API.
#
#   bash edge/tools/run_dashboard.sh           # build + serve on :8787
#   bash edge/tools/run_dashboard.sh --dev     # Vite dev server on :5178, API on :8787
#   bash edge/tools/run_dashboard.sh --serve   # skip the build, serve existing dist
#
# The built SPA lands in edge/runs/dashboard_dist/, which api_server.py serves
# as its static root. `--dev` runs both processes so frontend edits hot-reload
# against real data.

set -euo pipefail
cd "$(dirname "$0")/../.."

DASH="edge/dashboard"
PY="edge/.venv-qlib/bin/python"
[ -x "$PY" ] || PY="python3"

MODE="${1:-}"

if [ ! -d "$DASH/node_modules" ]; then
  echo "[deps] installing dashboard dependencies..."
  (cd "$DASH" && npm install)
fi

if [ "$MODE" != "--serve" ]; then
  echo "[build] compiling Vue app -> edge/runs/dashboard_dist/"
  (cd "$DASH" && npm run build)
fi

if [ "$MODE" = "--dev" ]; then
  echo "[dev] API on :8787, Vite on :5178 (proxying /api)"
  "$PY" edge/tools/api_server.py --no-browser &
  API_PID=$!
  trap 'kill $API_PID 2>/dev/null || true' EXIT INT TERM
  (cd "$DASH" && npm run dev)
else
  echo "[serve] http://localhost:8787"
  exec "$PY" edge/tools/api_server.py
fi
