#!/usr/bin/env bash
# Start the edge dashboard API backend and Vite frontend together.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

API_PORT="${API_PORT:-8787}"
FRONTEND_PORT="${FRONTEND_PORT:-5178}"
API_URL="http://127.0.0.1:${API_PORT}"
PYTHON_BIN="${PYTHON_BIN:-}"
API_PID=""

if [ -z "$PYTHON_BIN" ]; then
  if [ -x "$ROOT/.venv-qlib/bin/python" ]; then
    PYTHON_BIN="$ROOT/.venv-qlib/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

cleanup() {
  if [ -n "$API_PID" ] && kill -0 "$API_PID" 2>/dev/null; then
    echo
    echo "[stop] backend pid ${API_PID}"
    kill "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [ ! -d "$ROOT/dashboard/node_modules" ]; then
  echo "[deps] installing dashboard dependencies"
  (cd "$ROOT/dashboard" && npm install)
fi

# Prefer a backend that includes current routes. An old api_server left running
# from a prior session will pass /api/health but 404 new endpoints.
# Require the current research routes plus Flow State. A prior backend can
# answer /api/health while leaving the Flow workspace on a permanent 404.
backend_is_current() {
  curl -fsS "${API_URL}/api/health" >/dev/null 2>&1 || return 1
  local code path
  for path in /api/ga /api/factors /api/graph /api/changepoints /api/flow-state; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' "${API_URL}${path}" 2>/dev/null || echo 000)"
    [ "$code" = "200" ] || return 1
  done
  return 0
}

if backend_is_current; then
  echo "[backend] already running at ${API_URL} (routes current)"
else
  if curl -fsS "${API_URL}/api/health" >/dev/null 2>&1; then
    echo "[backend] stale API on :${API_PORT} (missing current routes) — restarting"
    # Best-effort kill of whatever is bound to the API port on loopback.
    if command -v lsof >/dev/null 2>&1; then
      lsof -tiTCP:"${API_PORT}" -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
      sleep 1
    fi
  fi
  echo "[backend] starting at ${API_URL}"
  "$PYTHON_BIN" "$ROOT/tools/api_server.py" --port "$API_PORT" --no-browser &
  API_PID="$!"

  for _ in $(seq 1 60); do
    if backend_is_current; then
      break
    fi
    if ! kill -0 "$API_PID" 2>/dev/null; then
      echo "[backend] failed to start" >&2
      wait "$API_PID"
      exit 1
    fi
    sleep 1
  done

  if ! backend_is_current; then
    echo "[backend] timed out waiting for ${API_URL} with current routes" >&2
    exit 1
  fi
fi

echo "[frontend] http://localhost:${FRONTEND_PORT}"
echo "[backend]  ${API_URL}"
npm --prefix "$ROOT/dashboard" run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
