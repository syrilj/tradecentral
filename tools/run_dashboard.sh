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
PY_REQUIREMENTS="edge/requirements-dashboard.txt"

MODE="${1:-}"

# Vite 6 requires a modern Web Crypto implementation. macOS can retain an old
# /usr/local Node ahead of Homebrew's current runtime, which passes vue-tsc and
# then fails during bundling with `crypto.getRandomValues is not a function`.
if [ -x /opt/homebrew/bin/node ]; then
  export PATH="/opt/homebrew/bin:$PATH"
fi
NODE_MAJOR="$(node -p \"Number(process.versions.node.split('.')[0])\" 2>/dev/null || echo 0)"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "[deps] Node 18+ is required for the dashboard build (found $(node --version 2>/dev/null || echo none))." >&2
  exit 1
fi

if [ ! -d "$DASH/node_modules" ]; then
  echo "[deps] installing dashboard dependencies..."
  (cd "$DASH" && npm install)
fi

if ! "$PY" -c 'import exchange_calendars' >/dev/null 2>&1; then
  echo "[deps] installing live dashboard Python dependencies..."
  "$PY" -m pip install -r "$PY_REQUIREMENTS"
fi

if [ "$MODE" != "--serve" ]; then
  echo "[build] compiling Vue app -> edge/runs/dashboard_dist/"
  (cd "$DASH" && npm run build)
fi

# Kill a stale API that still answers /api/health but lacks Research/Graph routes.
# (Old processes left on :8787 are the usual reason those tabs look "broken".)
ensure_fresh_api_port() {
  local port="${1:-8787}"
  local base="http://127.0.0.1:${port}"
  if ! curl -fsS "${base}/api/health" >/dev/null 2>&1; then
    return 0
  fi
  local code path
  for path in /api/ga /api/factors /api/graph; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' "${base}${path}" 2>/dev/null || echo 000)"
    if [ "$code" != "200" ]; then
      echo "[backend] stale API on :${port} (missing ${path}) — restarting"
      if command -v lsof >/dev/null 2>&1; then
        lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
        sleep 1
      fi
      return 0
    fi
  done
  echo "[backend] already current on :${port}"
}

if [ "$MODE" = "--dev" ]; then
  echo "[dev] API on :8787, Vite on :5178 (proxying /api)"
  ensure_fresh_api_port 8787
  "$PY" edge/tools/api_server.py --no-browser &
  API_PID=$!
  trap 'kill $API_PID 2>/dev/null || true' EXIT INT TERM
  (cd "$DASH" && npm run dev)
else
  echo "[serve] http://localhost:8787"
  ensure_fresh_api_port 8787
  exec "$PY" edge/tools/api_server.py
fi
