#!/usr/bin/env python3
"""Submit PEAD Catalyst Model Training & Sweeps to GCP Vertex AI.

Submits custom jobs to Google Cloud Vertex AI using Spot compute:
  - Billed against GCP $1,500 Credit Pool.
  - Automatically tarballs repo context and uploads to GCS staging bucket.
  - Runs model evaluation and saves artifacts back to GCS.

Usage:
  # Dry-run (validate spec without spending credits):
  python3 edge/tools/submit_pead_gcp.py --dry-run

  # Submit job to Vertex AI (Spot Compute):
  python3 edge/tools/submit_pead_gcp.py
"""
import os
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUBMIT_SCRIPT = ROOT / "edge" / "tools" / "submit_vertex_job.py"

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Submit PEAD Catalyst model job to GCP Vertex AI")
    parser.add_argument("--dry-run", action="store_true", help="Dry run validation")
    parser.add_argument("--gpu", type=str, choices=["none", "l4", "t4"], default="none", help="GPU accelerator")
    args = parser.parse_args()

    cmd = [
        sys.executable,
        str(SUBMIT_SCRIPT),
        "--job-name", "pead-catalyst-sweep",
        "--script-path", "edge/tools/build_pead_catalyst_model.py",
        "--gpu", args.gpu,
    ]
    if args.dry_run:
        cmd.append("--dry-run")

    print("=" * 70)
    print("  GCP VERTEX AI SUBMISSION — PEAD CATALYST MODEL")
    print("=" * 70)
    print(f"Command: {' '.join(cmd)}")

    res = subprocess.run(cmd, cwd=ROOT)
    if res.returncode == 0:
        print("\n[SUCCESS] GCP Job submission flow completed successfully.")
    else:
        print(f"\n[ERROR] Submission failed with exit code {res.returncode}")

if __name__ == "__main__":
    main()
