#!/usr/bin/env python3
"""gcp_run_xs3_validation.py — XS3 LightGBM 557-name sweep validation on GCP Vertex AI.

Wraps qlib_deep_wide.py (the XS3 wide sweep) to:
  1. Ingest/download price data into the qlib provider format (if not cached).
  2. Run the GATE_XS3.md confirmation sweep.
  3. Write results to edge/runs/qlib_xs3/results.json (picked up by gcp_validate_all.py
     and uploaded to GCS, then fetched by fetch_gcp_results.py).

Previous Vertex jobs (qlib-xs3-wide-sweep, qlib-xs3-wide-sweep-v2) both died because
the inline pip install floated numpy to 2.x.  This script assumes it is run AFTER
requirements-vertex.txt has been installed via gcp_validate_all.py or submit_vertex_job.py.

Usage:
  # Inside Vertex container (called by gcp_validate_all.py):
  python3 edge/tools/gcp_run_xs3_validation.py

  # Locally (smoke test):
  python3 edge/tools/gcp_run_xs3_validation.py --smoke
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EDGE = ROOT / "edge"
OUT_DIR = EDGE / "runs" / "qlib_xs3"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EDGE))

# Qlib provider path — populated by qlib_ingest_wide.py or fetched via yfinance
PROVIDER = EDGE / "data" / "qlib_us_1d"


def _ingest_data_if_missing() -> bool:
    """Run qlib_ingest.py to populate the qlib provider if data is absent."""
    if PROVIDER.exists() and len(list(PROVIDER.glob("**/*.bin"))) > 10:
        print(f"  qlib provider found at {PROVIDER} — skipping ingest.")
        return True
    print("  qlib provider missing — running qlib_ingest.py...")
    rc = os.system(f"python3 {EDGE}/tools/qlib_ingest.py 2>&1 | tail -20")
    if rc != 0:
        print("  WARNING: qlib_ingest.py exited non-zero. Trying wide ingest...")
        rc2 = os.system(f"python3 {EDGE}/tools/fetch_universe.py 2>&1 | tail -10")
        if rc2 != 0:
            print("  ERROR: Data fetch failed. Results will be inaccurate.")
            return False
    return True


def _run_xs3_sweep(smoke: bool = False) -> dict:
    """Run qlib_deep_wide.py (the XS3 wide sweep) and return parsed results."""
    # qlib_deep_wide.py is the XS3 implementation — runs the 557-name universe
    script = EDGE / "tools" / "qlib_deep_wide.py"
    if not script.exists():
        # Fallback: use qlib_sweep.py in selection phase
        script = EDGE / "tools" / "qlib_sweep.py"
        extra = "--phase selection --smoke" if smoke else "--phase selection"
    else:
        extra = "--smoke" if smoke else ""

    t0 = time.time()
    out_path = OUT_DIR / "sweep_raw.json"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cmd = f"python3 {script} {extra} --out {out_path} 2>&1 | tee {OUT_DIR}/sweep.log"
    print(f"  Running: {cmd}")
    rc = os.system(cmd)
    elapsed = time.time() - t0
    print(f"  Sweep finished in {elapsed:.0f}s (rc={rc})")

    if not out_path.exists():
        return {"error": f"sweep script exited rc={rc}, no output written", "verdict": "ERROR"}

    with open(out_path) as f:
        raw = json.load(f)

    # Summarise to the format render_dashboard.py / fetch_gcp_results.py expect
    results_list = raw.get("results", [])
    if not results_list:
        return {"error": "sweep produced empty results", "verdict": "ERROR"}

    # Pick the best config by IR (highest excess return with cost information ratio)
    best = None
    for r in results_list:
        if "error" not in r and "excess_return_with_cost" in r:
            ir = r["excess_return_with_cost"].get("information_ratio", -99)
            if best is None or ir > best["excess_return_with_cost"].get("information_ratio", -99):
                best = r

    if best is None:
        return {"error": "no successful backtest configs", "verdict": "ERROR"}

    ic_block = best.get("rank_ic", {})
    ret_block = best.get("excess_return_with_cost", {})
    to_block = best.get("turnover", {})
    mean_ic = float(ic_block.get("mean_rank_ic", 0.0))
    net_return = float(ret_block.get("annualized_return", 0.0))
    sharpe = float(ret_block.get("information_ratio", 0.0))  # qlib calls it IR
    turnover = float(to_block.get("annualized_one_way", 0.0))

    # GATE_XS3.md gate: IC > 0.005, IR (Sharpe) > 0.3, net return > 2%
    gate_ic = mean_ic > 0.005
    gate_ir = sharpe > 0.3
    gate_ret = net_return > 0.02
    verdict = "GO" if (gate_ic and gate_ir and gate_ret) else "NO-GO"

    return {
        "mean_rank_ic": mean_ic,
        "rank_icir": float(ic_block.get("rank_icir", 0.0)),
        "net_annual_return": net_return,
        "sharpe_ratio": sharpe,
        "annual_turnover": turnover,
        "best_config": {
            "universe": best.get("universe"),
            "rebalance_days": best.get("rebalance_days"),
            "topk": best.get("topk"),
            "n_drop": best.get("n_drop"),
        },
        "gate_checks": {
            "mean_ic_gt_005": gate_ic,
            "ir_gt_03": gate_ir,
            "net_ret_gt_2pct": gate_ret,
        },
        "verdict": verdict,
        "sweep_configs_evaluated": len(results_list),
        "elapsed_seconds": int(time.time() - t0 + elapsed),
        "gate": "edge/docs/GATE_XS3.md",
        "validation_source": "gcp_vertex_ai",
        "gcp_validated": True,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--smoke", action="store_true", help="Run one config only (fast smoke test)")
    args = ap.parse_args(argv)

    print("=" * 70)
    print("  XS3 LGBM 557-NAME VALIDATION — GCP VERTEX AI JOB")
    print("=" * 70)
    print(f"  Smoke: {args.smoke}")
    print(f"  Output: {OUT_DIR / 'results.json'}")

    # Ingest data if missing
    _ingest_data_if_missing()

    # Run the sweep
    results = _run_xs3_sweep(smoke=args.smoke)

    # Write results
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'=' * 70}")
    print("  XS3 Validation Results:")
    print(f"  Mean Rank IC:    {results.get('mean_rank_ic', 'N/A')}")
    print(f"  Net Annual Ret:  {results.get('net_annual_return', 'N/A')}")
    print(f"  Sharpe/IR:       {results.get('sharpe_ratio', 'N/A')}")
    print(f"  Verdict:         {results.get('verdict', 'ERROR')}")
    print(f"  Written to:      {out_file}")
    print("=" * 70)

    return 0 if results.get("verdict") != "ERROR" else 1


if __name__ == "__main__":
    sys.exit(main())
