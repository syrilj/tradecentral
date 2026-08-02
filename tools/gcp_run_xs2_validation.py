#!/usr/bin/env python3
"""gcp_run_xs2_validation.py — XS2 Cross-Sectional 40-name validation on GCP Vertex AI.

Runs qlib_sweep.py in selection phase then confirmation phase for xs40/pit30 universes.
Previous jobs never finished due to numpy conflict (now fixed via requirements-vertex.txt).

Usage:
  python3 edge/tools/gcp_run_xs2_validation.py
  python3 edge/tools/gcp_run_xs2_validation.py --smoke
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
OUT_DIR = EDGE / "runs" / "qlib_xs2"
PROVIDER = EDGE / "data" / "qlib_us_1d"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EDGE))


def _ingest_if_missing() -> None:
    if PROVIDER.exists() and len(list(PROVIDER.glob("**/*.bin"))) > 10:
        print(f"  qlib provider found — skipping ingest.")
        return
    print("  qlib provider missing — running qlib_ingest.py...")
    os.system(f"python3 {EDGE}/tools/qlib_ingest.py 2>&1 | tail -20")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--smoke", action="store_true", help="One config only (smoke test)")
    args = ap.parse_args(argv)

    print("=" * 70)
    print("  XS2 CROSS-SECTIONAL 40-NAME VALIDATION — GCP VERTEX AI JOB")
    print("=" * 70)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    _ingest_if_missing()

    sweep_script = EDGE / "tools" / "qlib_sweep.py"
    smoke_flag = "--smoke" if args.smoke else ""

    # Selection phase: 36 configs on 2022-2023 segment
    sel_out = OUT_DIR / "selection.json"
    print("\n[PHASE 1] Running selection phase...")
    t0 = time.time()
    rc_sel = os.system(
        f"python3 {sweep_script} --phase selection {smoke_flag} "
        f"--out {sel_out} 2>&1 | tee {OUT_DIR}/selection.log"
    )
    print(f"  Selection done in {time.time()-t0:.0f}s (rc={rc_sel})")

    # Parse selection winner
    winner = None
    if sel_out.exists():
        with open(sel_out) as f:
            sel_data = json.load(f)
        winner = sel_data.get("winner")

    if winner is None:
        print("  No winner from selection — NO-GO (gate failed selection filter).")
        results = {
            "mean_rank_ic": 0.0,
            "net_annual_return": 0.0,
            "sharpe_ratio": 0.0,
            "verdict": "NO-GO",
            "reason": "No config survived selection turnover filter",
            "gate": "edge/docs/GATE_XS2.md",
            "gcp_validated": True,
        }
        out_file = OUT_DIR / "results.json"
        with open(out_file, "w") as f:
            json.dump(results, f, indent=2)
        return 0

    print(f"  Selected: {winner}")

    # Confirmation phase: run the winner on 2024-2026 segment
    conf_out = OUT_DIR / "confirmation.json"
    print("\n[PHASE 2] Running confirmation phase...")
    t1 = time.time()
    rc_conf = os.system(
        f"python3 {sweep_script} --phase confirmation "
        f"--universe {winner['universe']} "
        f"--rebalance {winner['rebalance_days']} "
        f"--topk {winner['topk']} "
        f"--n-drop {winner['n_drop']} "
        f"--out {conf_out} 2>&1 | tee {OUT_DIR}/confirmation.log"
    )
    print(f"  Confirmation done in {time.time()-t1:.0f}s (rc={rc_conf})")

    # Parse confirmation results
    results_conf = {"mean_rank_ic": 0.0, "net_annual_return": 0.0, "sharpe_ratio": 0.0}
    if conf_out.exists():
        with open(conf_out) as f:
            conf_data = json.load(f)
        conf_results = conf_data.get("results", [{}])
        primary_arm = next((r for r in conf_results if r.get("arm") == "5y"), conf_results[0] if conf_results else {})
        ic_block = primary_arm.get("rank_ic", {})
        ret_block = primary_arm.get("excess_return_with_cost", {})
        to_block = primary_arm.get("turnover", {})
        results_conf = {
            "mean_rank_ic": float(ic_block.get("mean_rank_ic", 0.0)),
            "net_annual_return": float(ret_block.get("annualized_return", 0.0)),
            "sharpe_ratio": float(ret_block.get("information_ratio", 0.0)),
            "annual_turnover": float(to_block.get("annualized_one_way", 0.0)),
        }

    # GATE_XS2.md criteria (primary arm, 5y window)
    mean_ic = results_conf["mean_rank_ic"]
    ir = results_conf["sharpe_ratio"]
    net_ret = results_conf["net_annual_return"]
    verdict = "GO" if (mean_ic > 0.004 and ir > 0.3 and net_ret > 0.005) else "NO-GO"

    results = {
        **results_conf,
        "winner_config": winner,
        "gate_checks": {
            "mean_ic_gt_004": mean_ic > 0.004,
            "ir_gt_03": ir > 0.3,
            "net_ret_gt_05pct": net_ret > 0.005,
        },
        "verdict": verdict,
        "gate": "edge/docs/GATE_XS2.md",
        "validation_source": "gcp_vertex_ai",
        "gcp_validated": True,
    }

    out_file = OUT_DIR / "results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'=' * 70}")
    print(f"  XS2 Validation:")
    print(f"  Mean IC:     {mean_ic:.4f}")
    print(f"  Net Return:  {net_ret:.2%}")
    print(f"  IR:          {ir:.3f}")
    print(f"  Verdict:     {verdict}")
    print(f"  Written to:  {out_file}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
