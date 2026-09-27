#!/usr/bin/env bash
# Start the edge dashboard API backend and Vite frontend together.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# api_server.py reads provider credentials (LSE_API_KEY and friends) straight
# from the environment and never loads a dotenv itself, so launching through
# this script left them unset: the flow tape came back `credential_missing`
# and the desk rendered empty. Export .env here when it exists; values in the
# file take precedence over the caller's shell, so override with `.env` itself
# rather than an inline prefix.
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

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

# Vite 6 needs Node 18+ with Web Crypto. Prefer the current Homebrew runtime
# when macOS still has an older /usr/local Node earlier on PATH.
if [ -x /opt/homebrew/bin/node ]; then
  export PATH="/opt/homebrew/bin:$PATH"
fi
NODE_MAJOR="$(node -p "Number(process.versions.node.split('.')[0])" 2>/dev/null || echo 0)"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "[deps] Node 18+ is required (found $(node --version 2>/dev/null || echo none))." >&2
  exit 1
fi

cleanup() {
  if [ -n "$API_PID" ] && kill -0 "$API_PID" 2>/dev/null; then
    echo
    echo "[stop] backend pid ${API_PID}"
    kill "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Install (or repair) frontend deps. An incomplete node_modules can leave the
# directory present while .bin/vite is a dangling symlink → "vite: command not found".
if [ ! -d "$ROOT/dashboard/node_modules" ] || [ ! -x "$ROOT/dashboard/node_modules/.bin/vite" ] \
  || [ ! -e "$ROOT/dashboard/node_modules/vite/bin/vite.js" ]; then
  echo "[deps] installing dashboard dependencies"
  (cd "$ROOT/dashboard" && npm install)
fi

# Prefer a backend that includes current routes and the standalone market-wide
# Flow contract. A prior process can expose every route while still returning
# the retired Deep-scan payload, so route checks alone are insufficient.
backend_is_current() {
  local code path health
  health="$(curl -fsS "${API_URL}/api/health" 2>/dev/null)" || return 1
  # /api/health is serialized with compact separators (`{"k":"v"}`), so match
  # against a space-stripped copy rather than assuming `"k": "v"` spacing --
  # a spacing-sensitive pattern here never matches, and the caller then kills
  # the healthy backend it just started as "stale".
  local health_nospace="${health// /}"
  case "$health_nospace" in
    *'"flow_feed_contract":"market-wide-v1"'*) ;;
    *) return 1 ;;
  esac
  case "$health_nospace" in
    *'"suggestion_contract":"paper-candidate-contract-v9"'*) ;;
    *) return 1 ;;
  esac
  case "$health_nospace" in
    *'"gamma_regime_contract":"gamma-regime-v1"'*) ;;
    *) return 1 ;;
  esac
  # A backend that answers /api/* can still be unable to read the SPA bundle:
  # a process launched without filesystem access to this tree returns
  # 500 PermissionError on every static read while /api/health stays green.
  # Probe the root document so such a process is treated as stale.
  code="$(curl -sS -o /dev/null -w '%{http_code}' "${API_URL}/" 2>/dev/null || echo 000)"
  [ "$code" = "200" ] || return 1
  for path in /api/ga /api/factors /api/graph /api/changepoints /api/flow-state /api/scan_status; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' "${API_URL}${path}" 2>/dev/null || echo 000)"
    [ "$code" = "200" ] || return 1
  done
  for path in "/api/company-profile?symbol=SPY" "/api/financials?symbol=SPY" "/api/insiders?symbol=SPY" "/api/government?symbol=SPY" "/api/ownership?symbol=SPY"; do
    code="$(curl -sS -o /dev/null -w '%{http_code}' "${API_URL}${path}" 2>/dev/null || echo 000)"
    [ "$code" = "200" ] || return 1
  done
  code="$(curl -sS -o /dev/null -w '%{http_code}' "${API_URL}/api/flow-tape?symbol=SPY" 2>/dev/null || echo 000)"
  [ "$code" = "200" ] || return 1
  code="$(curl -sS -o /dev/null -w '%{http_code}' "${API_URL}/api/options-calculator?strategy=long_call&spot=100&strike=100&dte=1&vol=0.3&debit=1" 2>/dev/null || echo 000)"
  [ "$code" = "200" ] || return 1
  return 0
}

frontend_is_current() {
  local html
  html="$(curl -fsS "http://127.0.0.1:${FRONTEND_PORT}/" 2>/dev/null)" || return 1
  case "$html" in
    *'/@vite/client'*'/src/main.ts'*) return 0 ;;
    *) return 1 ;;
  esac
}

if backend_is_current; then
  echo "[backend] already running at ${API_URL} (routes current)"
else
  if curl -fsS "${API_URL}/api/health" >/dev/null 2>&1; then
    echo "[backend] stale API on :${API_PORT} (old routes or Flow contract) — restarting"
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

echo "[backend]  ${API_URL}"
if frontend_is_current; then
  echo "[frontend] already running at http://localhost:${FRONTEND_PORT} (Vite current)"
  if [ -n "$API_PID" ]; then
    # This invocation owns the newly started backend. Keep it alive while the
    # already-running Vite process continues to proxy requests to it.
    wait "$API_PID"
  fi
  exit 0
fi

echo "[frontend] http://localhost:${FRONTEND_PORT}"
npm --prefix "$ROOT/dashboard" run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
