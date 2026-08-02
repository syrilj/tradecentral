#!/usr/bin/env python3
"""GCP Vertex AI Submission Utility for Track 1 & Track 2 Model Validation.

Leverages `submit_vertex_job.py` to route training, hyperparameter sweeps, and 
cross-validation tasks to GCP Vertex AI Custom Jobs (using Spot compute).

Usage:
  # Dry-run validation (verify command specs without launching GCP billing):
  python3 edge/tools/submit_vol_finra_gcp.py --dry-run

  # Submit Track 1 Volatility Timing Sweep to GCP:
  python3 edge/tools/submit_vol_finra_gcp.py --track 1

  # Submit Track 2 FINRA Factor Engine Sweep to GCP:
  python3 edge/tools/submit_vol_finra_gcp.py --track 2
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUBMIT_SCRIPT = ROOT / "edge" / "tools" / "submit_vertex_job.py"

def main():
    parser = argparse.ArgumentParser(description="Submit Track 1 & Track 2 sweeps to GCP Vertex AI")
    parser.add_argument("--track", type=int, choices=[1, 2], default=1, help="Strategy track (1=Vol Timing, 2=FINRA Factors)")
    parser.add_argument("--dry-run", action="store_true", help="Perform dry run without submitting job")
    parser.add_argument("--gpu", type=str, choices=["none", "t4", "l4"], default="none", help="GPU accelerator selection")
    args = parser.parse_args()

    if args.track == 1:
        job_name = "vol-timing-sweep"
        script_path = "edge/tools/backtest_vol_timing.py"
    else:
        job_name = "finra-factor-sweep"
        script_path = "edge/tools/build_finra_factor_model.py"

    cmd = [
        sys.executable,
        str(SUBMIT_SCRIPT),
        "--job-name", job_name,
        "--script-path", script_path,
        "--gpu", args.gpu,
    ]
    if args.dry_run:
        cmd.append("--dry-run")

    print(f"Launching GCP Vertex AI Submission for Track {args.track}...")
    print(f"Command: {' '.join(cmd)}")

    import subprocess
    res = subprocess.run(cmd, cwd=ROOT)
    if res.returncode == 0:
        print("\n[SUCCESS] GCP Job dispatch flow executed cleanly.")
    else:
        print(f"\n[ERROR] Submission exited with code {res.returncode}")

if __name__ == "__main__":
    main()
