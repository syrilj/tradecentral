#!/usr/bin/env python3
"""gcp_validate_all.py — Submit GCP Vertex AI jobs to validate/disprove every dashboard claim.

What this does:
  1. Validates PEAD Catalyst model claim (IC=0.2260, Sharpe=2.86, Net=+141%).
  2. Validates FINRA Short Volume factor claim (IC=0.0078, Net=-3.3%, NO-GO).
  3. Re-runs XS2 confirmation job (was broken due to numpy conflict — now fixed).
  4. Re-runs XS3 wide sweep job (was broken — now fixed with pinned requirements).

After all jobs finish, run:
  python3 edge/tools/fetch_gcp_results.py
to pull results from GCS and re-render the dashboard with confirmed/disproved labels.

Usage:
  # Submit all validation jobs (recommended):
  python3 edge/tools/gcp_validate_all.py

  # Dry-run only (print job specs, no cloud spend):
  python3 edge/tools/gcp_validate_all.py --dry-run

  # Submit just one gate:
  python3 edge/tools/gcp_validate_all.py --gates pead finra

  # Wait for jobs to complete (sync mode):
  python3 edge/tools/gcp_validate_all.py --sync
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

# Pinned CPU-only machine for all validation jobs (Spot pricing, 200GB SSD)
MACHINE_SPEC = {
    "machine_type": "n1-standard-8",  # 8 vCPU / 30 GB RAM — headroom for qlib Alpha158
    "accelerator_type": "ACCELERATOR_TYPE_UNSPECIFIED",
    "accelerator_count": 0,
}
DISK_SPEC = {"boot_disk_type": "pd-ssd", "boot_disk_size_gb": 200}
JOB_TIMEOUT = 7200  # 2 hours hard cap per job

# Gate definitions — what each job validates and what metric we expect
GATES = {
    "pead": {
        "display_name": "validate-pead-catalyst",
        "script": "edge/tools/build_pead_catalyst_model.py",
        "claim": "PEAD Catalyst: IC=0.2260, Sharpe=2.86, Net=+141% → GO",
        "output_gcs": f"{STAGING_BUCKET}/results/pead_catalyst/results.json",
        "local_out": EDGE / "runs" / "pead_catalyst" / "results.json",
        "description": "Confirms or disproves PEAD Catalyst IC/Sharpe numbers shown on dashboard",
    },
    "finra": {
        "display_name": "validate-finra-factor",
        "script": "edge/tools/build_finra_factor_model.py",
        "claim": "FINRA Short Vol: IC=0.0078, Net=-3.3% → NO-GO",
        "output_gcs": f"{STAGING_BUCKET}/results/finra_factor/results.json",
        "local_out": EDGE / "runs" / "finra_factor" / "results.json",
        "description": "Confirms FINRA factor is a NO-GO (negative edge after costs)",
    },
    "xs3": {
        "display_name": "validate-xs3-lgbm-557",
        "script": "edge/tools/gcp_run_xs3_validation.py",
        "claim": "XS3 LightGBM 557 names: IC=+0.0052, Net=+0.37% → NO-GO (UNCONFIRMED)",
        "output_gcs": f"{STAGING_BUCKET}/results/qlib_xs3/results.json",
        "local_out": EDGE / "runs" / "qlib_xs3" / "results.json",
        "description": "Previous jobs failed due to numpy conflict. Re-runs with fixed deps.",
    },
    "xs2": {
        "display_name": "validate-xs2-cross-sect-40",
        "script": "edge/tools/gcp_run_xs2_validation.py",
        "claim": "XS2 Cross-Sectional 40 names: IC=+0.0080, Net=+0.12% → NO-GO (UNCONFIRMED)",
        "output_gcs": f"{STAGING_BUCKET}/results/qlib_xs2/results.json",
        "local_out": EDGE / "runs" / "qlib_xs2" / "results.json",
        "description": "Confirms or disproves XS2 results (previous jobs never finished).",
    },
}


def _remote_cmd(script_path: str, output_gcs: str) -> str:
    """Build the bash command that runs inside the Vertex AI container."""
    return (
        # Step 1: pull and extract the repo package
        "echo '::STEP 1/6 gsutil-download-and-extract' && "
        f"gsutil cp {STAGING_BUCKET}/packages/edge_repo_package.tar.gz /tmp/pkg.tar.gz && "
        f"mkdir -p /workspace && tar -xzf /tmp/pkg.tar.gz -C /workspace --no-same-owner --warning=no-unknown-keyword && "
        f"cd /workspace && "
        # Step 2: install pinned requirements (numpy==1.26.4 etc.)
        "echo '::STEP 2/6 pip-install-requirements-vertex' && "
        f"pip install --quiet --no-cache-dir "
        f"--extra-index-url https://download.pytorch.org/whl/cpu "
        f"-r edge/requirements-vertex.txt && "
        # Step 3: install GCP SDK + extras not in requirements-vertex.txt
        "echo '::STEP 3/6 pip-install-gcp-sdk-and-extras' && "
        f"pip install --quiet --no-cache-dir "
        f"google-cloud-aiplatform google-cloud-storage google-cloud-bigquery "
        f"xgboost conformal yfinance einops && "
        # Step 4: preflight check — exits 1 on version drift
        "echo '::STEP 4/6 preflight-env-check' && "
        f"python3 edge/tools/preflight_env.py && "
        # Step 5: run validation script
        "echo '::STEP 5/6 run-validation-script' && "
        f"python3 {script_path} && "
        # Step 6: upload results to GCS via google.cloud.storage Python SDK
        "echo '::STEP 6/6 upload-results-to-gcs' && "
        f"python3 -c \"import sys, glob, os; from google.cloud import storage; "
        f"b = storage.Client().bucket('{STAGING_BUCKET.replace('gs://', '')}'); "
        f"files = glob.glob('edge/runs/**/results.json', recursive=True); "
        f"print('Found results files:', files); "
        f"[b.blob(f'results/{{os.path.basename(os.path.dirname(f))}}/results.json').upload_from_filename(f) for f in files]; "
        f"print('GCS upload complete')\" && "
        "echo '::STEP 6/6 COMPLETE — all steps succeeded'"
    )


def build_package(tar_path: Path) -> None:
    """Package the repo (excluding heavy dirs) for upload to GCS."""
    if tar_path.exists():
        tar_path.unlink()
    print("Building repository tarball...")
    exclude = [
        "--exclude=./.git",
        "--exclude=./.venv*",
        "--exclude=./.venv-qlib",
        "--exclude=./edge/runs",
        "--exclude=./edge/data",
        "--exclude=./__pycache__",
        "--exclude=./.pytest_cache",
        "--exclude=./.qlib-src",
        "--exclude=./.DS_Store",
        "--exclude=./node_modules",
        "--exclude=./.worktrees",
        f"--exclude={tar_path.name}",
    ]
    cmd = f"COPYFILE_DISABLE=1 tar -czf {tar_path} {' '.join(exclude)} -C {ROOT} edge TradingAlgoWork Kronos"
    subprocess.run(cmd, shell=True, check=True)
    size_mb = tar_path.stat().st_size / 1e6
    print(f"  Tarball: {tar_path.name} ({size_mb:.1f} MB)")


def upload_package(tar_path: Path) -> None:
    """Upload the package tarball to GCS."""
    dest = f"{STAGING_BUCKET}/packages/edge_repo_package.tar.gz"
    print(f"Uploading package to {dest} ...")
    subprocess.run(f"gsutil cp {tar_path} {dest}", shell=True, check=True)
    print("  Upload complete.")


def submit_job(gate_name: str, gate: dict, *, dry_run: bool = False, sync: bool = False) -> object:
    """Submit a single validation job to Vertex AI."""
    display_name = f"{gate['display_name']}-{int(time.time())}"
    remote_cmd = _remote_cmd(gate["script"], gate["output_gcs"])

    worker_pool_specs = [{
        "machine_spec": MACHINE_SPEC,
        "replica_count": 1,
        "disk_spec": DISK_SPEC,
        "container_spec": {
            "image_uri": CONTAINER_URI,
            "command": ["bash", "-c"],
            "args": [remote_cmd],
        },
    }]

    print(f"\n{'[DRY-RUN] ' if dry_run else ''}Submitting: {display_name}")
    print(f"  Claim: {gate['claim']}")
    print(f"  Script: {gate['script']}")
    print(f"  GCS output: {gate['output_gcs']}")

    if dry_run:
        print("  [DRY-RUN] No cloud resources provisioned.")
        return None

    from google.cloud import aiplatform

    job = aiplatform.CustomJob(
        display_name=display_name,
        worker_pool_specs=worker_pool_specs,
    )

    if sync:
        job.run(restart_job_on_worker_restart=False, timeout=JOB_TIMEOUT, sync=True)
        print(f"  [DONE] Job completed: {job.resource_name}")
    else:
        job.submit(restart_job_on_worker_restart=False, timeout=JOB_TIMEOUT)
        resource_id = job.resource_name.split("/")[-1] if job.resource_name else "UNKNOWN"
        print(f"  [SUBMITTED] Job ID: {resource_id}")
        print(f"  Console: https://console.cloud.google.com/vertex-ai/training/custom-jobs?project={PROJECT_ID}")

    return job


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gates", nargs="+", choices=list(GATES.keys()), default=list(GATES.keys()),
                    help="Which gates to validate (default: all)")
    ap.add_argument("--dry-run", action="store_true", help="Print job specs without spending credits")
    ap.add_argument("--sync", action="store_true", help="Wait for each job to finish before next")
    ap.add_argument("--skip-package", action="store_true",
                    help="Skip rebuild+upload of repo package (use existing GCS tarball)")
    args = ap.parse_args(argv)

    print("=" * 70)
    print("  GCP VERTEX AI — DASHBOARD VALIDATION RUN")
    print("=" * 70)
    print(f"  Project:  {PROJECT_ID}")
    print(f"  Region:   {REGION}")
    print(f"  Bucket:   {STAGING_BUCKET}")
    print(f"  Gates:    {', '.join(args.gates)}")
    print(f"  Dry-run:  {args.dry_run}")
    print(f"  Sync:     {args.sync}")
    print("=" * 70)

    # Package and upload repo
    if not args.dry_run and not args.skip_package:
        tar_path = ROOT / ".tmp_edge_repo_package.tar.gz"
        build_package(tar_path)
        upload_package(tar_path)
        try:
            tar_path.unlink()
        except OSError:
            pass
    elif not args.dry_run and args.skip_package:
        print("Skipping package build — using existing GCS tarball.")

    # Initialize Vertex AI SDK
    if not args.dry_run:
        try:
            from google.cloud import aiplatform
        except ImportError:
            print("ERROR: google-cloud-aiplatform not installed. Run: pip install google-cloud-aiplatform")
            return 1
        aiplatform.init(project=PROJECT_ID, location=REGION, staging_bucket=STAGING_BUCKET)

    # Submit jobs
    submitted_jobs = []
    for gate_name in args.gates:
        gate = GATES[gate_name]
        job = submit_job(gate_name, gate, dry_run=args.dry_run, sync=args.sync)
        if job is not None:
            submitted_jobs.append((gate_name, job))

    print("\n" + "=" * 70)
    if args.dry_run:
        print(f"DRY-RUN COMPLETE: {len(args.gates)} job specs validated.")
        print("Remove --dry-run to submit to GCP.")
    else:
        print(f"SUBMITTED: {len(submitted_jobs)} job(s) to Vertex AI.")
        print()
        print("Next steps:")
        print("  1. Monitor: https://console.cloud.google.com/vertex-ai/training/custom-jobs?project=" + PROJECT_ID)
        print("  2. After completion, pull results:")
        print("     python3 edge/tools/fetch_gcp_results.py")
        print("  3. Re-render dashboard:")
        print("     python3 edge/tools/render_dashboard.py")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
