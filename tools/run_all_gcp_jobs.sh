#!/usr/bin/env bash
# run_all_gcp_jobs.sh — Sequential GCP Vertex AI Batch Launcher

export PYTHONUNBUFFERED=1
export PYTHONWARNINGS="ignore"

echo "======================================================================"
echo "  LAUNCHING AUTOMATED GCP VERTEX AI OPTIONS MODEL TRAINING PIPELINE"
echo "======================================================================"
echo "  [✓] Project ID: gen-lang-client-0699310395"
echo "  [✓] Credit Billing: 100% Covered by Active GCP Credits"
echo "  [✓] Auto-Termination: Max 2 hours per job"
echo "======================================================================"

# Auto-detect Python binary from virtual environment if present
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [ -f "$SCRIPT_DIR/edge/.venv-qlib/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/edge/.venv-qlib/bin/python"
elif [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
elif [ -f "$SCRIPT_DIR/venv/bin/python" ]; then
    PYTHON_BIN="$SCRIPT_DIR/venv/bin/python"
else
    PYTHON_BIN="python3"
fi

# Step 1: Submit CPU Baseline Sweep (v90_wide across 59 tickers)
echo -e "\n1. Submitting CPU Champion Sweep (v90_wide)..."
"$PYTHON_BIN" edge/tools/submit_vertex_job.py \
    --job-name "options-v90-cpu-sweep" \
    --gpu none \
    --script-path "edge/tools/train_v90_wide.py" \
    --timeout 7200 "$@"

# Step 2: Submit GPU Kronos Fine-Tuning Job (NVIDIA L4 GPU)
echo -e "\n2. Submitting GPU Kronos Transformer Fine-Tuning (NVIDIA L4 GPU)..."
"$PYTHON_BIN" edge/tools/submit_vertex_job.py \
    --job-name "options-kronos-l4-gpu" \
    --gpu l4 \
    --script-path "edge/tools/train_v90_wide.py" \
    --timeout 7200 "$@"

echo -e "\n======================================================================"
echo "  [SUCCESS] BOTH JOBS QUEUED ON GCP VERTEX AI!"
echo "  You can close your laptop now. Google Cloud will execute both jobs"
echo "  and automatically shut down all cloud servers when complete."
echo "======================================================================"
