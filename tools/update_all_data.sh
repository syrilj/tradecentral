#!/usr/bin/env bash
# Automated Market & Research Data Sync Pipeline for Edge.
# Updates daily OHLCV prices (core + wide), Qlib binary feature matrices,
# volatility complex series, and FINRA short volume dataset up to today.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="$ROOT/.venv-qlib/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

TODAY="$(date +%Y-%m-%d)"
echo "============================================================"
echo "  EDGE DATA PIPELINE AUTOMATIC SYNC — $TODAY"
echo "============================================================"

echo "--> [1/7] Fetching main universe daily OHLCV prices..."
"$PYTHON_BIN" "$ROOT/tools/fetch_universe.py" --interval 1d --force || true

echo "--> [2/7] Fetching wide candidate universe daily OHLCV prices..."
"$PYTHON_BIN" "$ROOT/tools/fetch_universe_wide.py" --force || true

echo "--> [3/7] Re-indexing Qlib binary feature datasets..."
"$PYTHON_BIN" "$ROOT/tools/qlib_ingest.py"
"$PYTHON_BIN" "$ROOT/tools/qlib_ingest_wide.py"

echo "--> [4/7] Updating Volatility Complex dataset..."
"$PYTHON_BIN" "$ROOT/tools/fetch_vol_complex.py" --end "$TODAY" || true

echo "--> [5/7] Updating FINRA short volume dataset..."
"$PYTHON_BIN" "$ROOT/tools/fetch_finra_short_vol.py" --days 30 || true

echo "--> [6/7] Fetching small-cap momentum-scan universe..."
"$PYTHON_BIN" "$ROOT/tools/fetch_smallcap_universe.py" || true

echo "--> [7/7] Fetching float data for the momentum scan..."
"$PYTHON_BIN" "$ROOT/tools/fetch_float_data.py" || true

# Notify running API server to reload caches if active on localhost:8787
if curl -fsS "http://127.0.0.1:8787/api/health" >/dev/null 2>&1; then
  echo "--> Notifying API server on :8787 of updated datasets..."
  curl -sS -X POST "http://127.0.0.1:8787/api/sync_data?force=1" >/dev/null 2>&1 || true
fi

echo "============================================================"
echo "  ✅ All market and research datasets are now up to date as of $TODAY!"
echo "============================================================"
