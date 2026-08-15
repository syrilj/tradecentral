#!/usr/bin/env python3
"""gcp_run_walkforward_job.py — Submit Multi-Year Walk-Forward Validation Job to GCP Vertex AI.

Executes `run_walkforward_backtest.py` on GCP Vertex AI (`n1-standard-8` Spot instance),
uploads out-of-sample inferences and validation metrics to GCS bucket:
  gs://edge-artifacts-gen-lang-client-0699310395/results/walkforward/
and loads results into BigQuery dataset `trading_research`.

Usage:
  python3 edge/tools/gcp_run_walkforward_job.py
  python3 edge/tools/gcp_run_walkforward_job.py --smoke
  python3 edge/tools/gcp_run_walkforward_job.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EDGE = ROOT / "edge"
PROJECT_ID = os.getenv("GCP_PROJECT", "gen-lang-client-0699310395")
REGION = os.getenv("GCP_REGION", "us-central1")
STAGING_BUCKET = os.getenv("GCS_BUCKET", "gs://edge-artifacts-gen-lang-client-0699310395")
CONTAINER_URI = "us-docker.pkg.dev/vertex-ai/training/tf-cpu.2-12.py310:latest"

MACHINE_SPEC = {
    "machine_type": "n1-standard-8",
    "accelerator_type": "ACCELERATOR_TYPE_UNSPECIFIED",
    "accelerator_count": 0,
}
DISK_SPEC = {"boot_disk_type": "pd-standard", "boot_disk_size_gb": 100}
JOB_TIMEOUT = 7200  # 2-hour hard timeout safeguard
OUT_GCS = f"{STAGING_BUCKET}/results/walkforward/results.json"
OOF_GCS = f"{STAGING_BUCKET}/results/walkforward/oof_inferences.parquet"
DAILY_GCS = f"{STAGING_BUCKET}/results/walkforward/daily_portfolio_returns.parquet"


# Allowlist of paths the remote job actually needs, relative to ROOT.
# This is deliberately an ALLOWLIST, not a denylist. The previous denylist did not
# exclude TradingAlgoWork/ (5.3 GB) or edge/.venv-qlib/ (1.7 GB), so the "36 MB"
# package silently grew past 1.6 GB and the submit step hung before ever reaching
# Vertex AI. run_walkforward_backtest.py and bq_setup_and_load.py import no local
# modules, so tools + config + the 1d parquet cache is the complete dependency set.
PACKAGE_INCLUDE = [
    "edge/tools",
    "edge/config",
    "edge/data/1d",
]
_SKIP_DIRS = {"__pycache__", ".ipynb_checkpoints", ".pytest_cache"}
MAX_PACKAGE_MB = 250


def build_repo_package() -> Path:
    """Tar only the files the remote job needs, then stage to GCS."""
    pkg_path = EDGE / "runs" / "packages" / "edge_walkforward_pkg.tar.gz"
    pkg_path.parent.mkdir(parents=True, exist_ok=True)
    pkg_path.unlink(missing_ok=True)
    print(f"Building package: {pkg_path}")

    def _filter(ti: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
        parts = set(Path(ti.name).parts)
        if parts & _SKIP_DIRS or ti.name.endswith((".pyc", ".pyo")):
            return None
        return ti

    n_missing = 0
    with tarfile.open(pkg_path, "w:gz") as tar:
        for rel in PACKAGE_INCLUDE:
            src = ROOT / rel
            if not src.exists():
                print(f"  WARNING: {rel} not found — skipping")
                n_missing += 1
                continue
            tar.add(src, arcname=rel, filter=_filter)
            print(f"  + {rel}")

    size_mb = pkg_path.stat().st_size / 1e6
    print(f"Package created ({size_mb:.1f} MB).")
    if size_mb > MAX_PACKAGE_MB:
        raise RuntimeError(
            f"Package is {size_mb:.0f} MB (limit {MAX_PACKAGE_MB} MB). "
            "Something oversized slipped into PACKAGE_INCLUDE — refusing to upload."
        )
    if n_missing:
        raise RuntimeError(f"{n_missing} required package path(s) missing — aborting.")

    print("Uploading to GCS...")
    subprocess.run(
        ["gsutil", "cp", str(pkg_path),
         f"{STAGING_BUCKET}/packages/edge_walkforward_pkg.tar.gz"],
        check=True,
    )
    return pkg_path


def build_remote_command(smoke: bool) -> str:
    """Build bash execution script for Vertex AI container."""
    extra = "--smoke" if smoke else ""
    return (
        "echo '::STEP 1/5 Download & Extract Package' && "
        f"gsutil cp {STAGING_BUCKET}/packages/edge_walkforward_pkg.tar.gz /tmp/pkg.tar.gz && "
        "mkdir -p /workspace && tar -xzf /tmp/pkg.tar.gz -C /workspace --no-same-owner --warning=no-unknown-keyword && "
        "cd /workspace && "
        "echo '::STEP 2/5 Install Dependencies' && "
        # numpy MUST stay <2: the tf-cpu.2-12 image ships a conda scipy compiled
        # against numpy 1.x that does `from numpy.core.numeric import ComplexWarning`.
        # Letting pip pull numpy 2.x breaks `import sklearn` and the job dies at
        # STEP 3 with "Missing scikit-learn". All pins below are the exact versions
        # validated locally against this script. Single pip pass so the resolver
        # sees every constraint at once and cannot silently upgrade numpy.
        "pip install --no-cache-dir "
        "'numpy==1.26.4' 'scipy==1.15.3' 'pandas==2.2.2' 'pyarrow>=14,<26' "
        "'scikit-learn==1.7.1' 'xgboost==3.2.0' "
        "python-json-logger yfinance pandas-gbq google-cloud-bigquery && "
        # Fail fast with a readable message instead of dying 4 minutes later.
        "echo '::STEP 2b/5 Verify Dependency Graph' && "
        "python3 -c \"import numpy,scipy,sklearn,xgboost,pandas,pyarrow;"
        "print('[deps] numpy',numpy.__version__,'scipy',scipy.__version__,"
        "'sklearn',sklearn.__version__,'xgboost',xgboost.__version__)\" && "
        "echo '::STEP 3/5 Execute Multi-Year Walk-Forward Backtest' && "
        f"python3 edge/tools/run_walkforward_backtest.py {extra} && "
        "echo '::STEP 4/5 Upload Artifacts to GCS' && "
        f"gsutil cp edge/runs/walkforward/results.json {OUT_GCS} && "
        f"gsutil cp edge/runs/walkforward/oof_inferences.parquet {OOF_GCS} && "
        f"gsutil cp edge/runs/walkforward/daily_portfolio_returns.parquet {DAILY_GCS} && "
        "echo '::STEP 5/5 Sync Out-of-Sample Inferences to BigQuery' && "
        # Non-fatal: artifacts are already safely in GCS by this point, so a BQ
        # permission/schema hiccup should not mark an otherwise-good run as Failed.
        "(python3 edge/tools/bq_setup_and_load.py --tables oof_inferences model_gate_results "
        "|| echo '::WARN BigQuery sync failed — GCS artifacts are still valid') && "
        "echo '::COMPLETE Multi-Year Walk-Forward GCP Job Finished Successfully!'"
    )


def submit_vertex_job(smoke: bool = False, dry_run: bool = False) -> str:
    """Submit CustomJob to Vertex AI using Google Cloud AIPlatform SDK."""
    if not dry_run:
        build_repo_package()
    bash_cmd = build_remote_command(smoke)
    display_name = f"multiyear-walkforward-{int(time.time())}"

    worker_pool_specs = [
        {
            "machine_spec": MACHINE_SPEC,
            "replica_count": 1,
            "disk_spec": DISK_SPEC,
            "container_spec": {
                "image_uri": CONTAINER_URI,
                "command": ["bash", "-c"],
                "args": [bash_cmd],
            },
        }
    ]

    if dry_run:
        print("\n[DRY RUN] Job Spec:")
        print(json.dumps(worker_pool_specs, indent=2))
        return "dry-run-job-id"

    try:
        from google.cloud import aiplatform
        from google.cloud.aiplatform_v1.types import Scheduling
        aiplatform.init(project=PROJECT_ID, location=REGION, staging_bucket=STAGING_BUCKET)
        job = aiplatform.CustomJob(
            display_name=display_name,
            worker_pool_specs=worker_pool_specs,
        )
        print("Submitting job to Vertex AI on Spot compute...")
        job.submit(
            restart_job_on_worker_restart=False,
            timeout=JOB_TIMEOUT,
            scheduling_strategy=Scheduling.Strategy.SPOT,
        )
        job_name = job.resource_name
        print(f"SUCCESS: Vertex AI Job created: {job_name} (Spot Compute)")
        return job_name
    except Exception as e:
        print(f"ERROR submitting job: {e}")
        return ""


def main():
    parser = argparse.ArgumentParser(description="Submit Multi-Year Walk-Forward Backtest to GCP")
    parser.add_argument("--smoke", action="store_true", help="Run smoke test mode")
    parser.add_argument("--dry-run", action="store_true", help="Dry run only")
    args = parser.parse_args()

    job_id = submit_vertex_job(smoke=args.smoke, dry_run=args.dry_run)
    if job_id:
        print(f"\nWalk-forward backtest job submitted successfully: {job_id}")


if __name__ == "__main__":
    main()
