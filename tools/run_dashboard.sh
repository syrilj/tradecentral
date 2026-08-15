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
NODE_MAJOR="$(node -p "Number(process.versions.node.split('.')[0])" 2>/dev/null || echo 0)"
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

# Accept an existing backend only when it exposes both the current route set
# and the standalone market-wide Flow response contract.
backend_is_current() {
  local port="${1:-8787}"
  local base="http://127.0.0.1:${port}"
  local code path health
  health="$(curl -fsS "${base}/api/health" 2>/dev/null)" || return 1
  case "$health" in
    *'"flow_feed_contract": "market-wide-v1"'*) ;;
    *) return 1 ;;
  esac
  case "$health" in
    *'"suggestion_contract": "paper-candidate-contract-v9"'*) ;;
    *) return 1 ;;
  esac
  for path in /api/ga /api/factors /api/graph /api/changepoints /api/flow-state /api/scan_status; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' "${base}${path}" 2>/dev/null || echo 000)"
    [ "$code" = "200" ] || return 1
  done
  code="$(curl -sS -o /dev/null -w '%{http_code}' "${base}/api/flow-tape?symbol=SPY" 2>/dev/null || echo 000)"
  [ "$code" = "200" ] || return 1
  return 0
}

stop_stale_backend() {
  local port="${1:-8787}"
  local base="http://127.0.0.1:${port}"
  if curl -fsS "${base}/api/health" >/dev/null 2>&1; then
    echo "[backend] stale API on :${port} (old routes or Flow contract) — restarting"
    if command -v lsof >/dev/null 2>&1; then
      lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
      sleep 1
    fi
  fi
}

wait_for_backend() {
  local pid="$1"
  local port="${2:-8787}"
  local attempt
  for attempt in $(seq 1 60); do
    if backend_is_current "$port"; then
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid"
      return 1
    fi
    sleep 1
  done
  return 1
}

frontend_is_current() {
  local port="${1:-5178}"
  local html
  html="$(curl -fsS "http://127.0.0.1:${port}/" 2>/dev/null)" || return 1
  case "$html" in
    *'/@vite/client'*'/src/main.ts'*) return 0 ;;
    *) return 1 ;;
  esac
}

if [ "$MODE" = "--dev" ]; then
  echo "[dev] API on :8787, Vite on :5178 (proxying /api)"
  API_PID=""
  if backend_is_current 8787; then
    echo "[backend] already current on :8787"
  else
    stop_stale_backend 8787
    "$PY" edge/tools/api_server.py --no-browser &
    API_PID=$!
    trap 'if [ -n "$API_PID" ]; then kill "$API_PID" 2>/dev/null || true; fi' EXIT INT TERM
    if ! wait_for_backend "$API_PID" 8787; then
      echo "[backend] failed to start with the current Flow contract" >&2
      exit 1
    fi
    echo "[backend] current on :8787"
  fi

  if frontend_is_current 5178; then
    echo "[frontend] already running on :5178 (Vite current)"
    if [ -n "$API_PID" ]; then
      wait "$API_PID"
    fi
    exit 0
  fi
  (cd "$DASH" && npm run dev)
else
  echo "[serve] http://localhost:8787"
  if backend_is_current 8787; then
    echo "[backend] already current on :8787"
    exit 0
  fi
  stop_stale_backend 8787
  exec "$PY" edge/tools/api_server.py
fi
