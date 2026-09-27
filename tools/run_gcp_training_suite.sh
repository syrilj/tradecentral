#!/usr/bin/env bash
# run_gcp_training_suite.sh — Submit all GCP training jobs in the correct order.
#
# Usage:
#   bash edge/tools/run_gcp_training_suite.sh
#   bash edge/tools/run_gcp_training_suite.sh --dry-run   (validate specs only)
#
# Jobs submitted (async — all run in parallel on Vertex AI Spot VMs):
#   1. validate-pead      — confirm PEAD IC=0.2260, Sharpe=2.86 claim
#   2. validate-finra     — confirm FINRA NO-GO claim
#   3. validate-xs3       — re-run XS3 (was broken due to numpy conflict)
#   4. validate-xs2       — re-run XS2 (was broken due to numpy conflict)
#   5. exp-pead-v2        — PEAD + VWAP challenger
#   6. exp-pead-xgb       — XGBoost meta-labeler on PEAD events
#   7. exp-lgbm-hybrid    — LightGBM + Alpha158 + gap features
#
# After all jobs finish (ETA: 30-90 min), run:
#   python3 edge/tools/fetch_gcp_results.py

set -e
cd "$(dirname "$0")/../.."   # go to alltrading/ root

DRY_RUN=""
if [ "$1" = "--dry-run" ]; then
  DRY_RUN="--dry-run"
  echo "[DRY-RUN MODE] No cloud resources will be provisioned."
fi

echo "==================================================================="
echo "  GCP TRAINING SUITE — VALIDATION + EXPERIMENTS"
echo "==================================================================="

# Phase 1: Submit validation jobs (re-validate all dashboard claims)
echo ""
echo "[PHASE 1] Submitting validation jobs..."
python3 edge/tools/gcp_validate_all.py --gates pead finra xs3 xs2 $DRY_RUN --skip-package

# Phase 2: Submit experiment jobs (test challenger models)
echo ""
echo "[PHASE 2] Submitting experiment jobs..."
python3 edge/tools/submit_vertex_job.py \
  --job-name "exp-pead-v2-$(date +%s)" \
  --script-path "edge/tools/gcp_experiment_pead_v2.py" \
  --gpu none \
  $DRY_RUN

python3 edge/tools/submit_vertex_job.py \
  --job-name "exp-pead-xgb-$(date +%s)" \
  --script-path "edge/tools/gcp_experiment_pead_xgb.py" \
  --gpu none \
  $DRY_RUN

python3 edge/tools/submit_vertex_job.py \
  --job-name "exp-lgbm-hybrid-$(date +%s)" \
  --script-path "edge/tools/gcp_experiment_lgbm_hybrid.py" \
  --gpu none \
  $DRY_RUN

echo ""
echo "==================================================================="
echo "  ALL JOBS SUBMITTED — Monitor at:"
echo "  https://console.cloud.google.com/vertex-ai/training/custom-jobs?project=gen-lang-client-0699310395"
echo ""
echo "  When jobs finish, pull results + update dashboard:"
echo "    python3 edge/tools/fetch_gcp_results.py"
echo "==================================================================="
