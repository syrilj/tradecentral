#!/usr/bin/env python3
"""
submit_vertex_job.py — Submit containerized trading model jobs to GCP Vertex AI.

Fully compatible with Google Gen AI / Vertex AI $1,500 credits.
Routes all compute through Vertex AI Custom Jobs API to ensure billing hits
the credit allocation rather than personal credit cards.

Usage:
    # Dry run (verify job spec & credit routing without spending):
    python3 edge/tools/submit_vertex_job.py --dry-run

    # CPU Parallel Sweep:
    python3 edge/tools/submit_vertex_job.py --job-name v90-wide-sweep --gpu none

    # GPU Fine-Tuning (NVIDIA L4 Spot GPU):
    python3 edge/tools/submit_vertex_job.py --job-name kronos-l4-finetune --gpu l4
"""

import argparse
import os
import sys
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def parse_args():
    parser = argparse.ArgumentParser(description="Submit training jobs to GCP Vertex AI.")
    parser.add_argument("--job-name", type=str, default="edge-training-job", help="Unique name for the job")
    parser.add_argument("--project-id", type=str, default=os.getenv("GCP_PROJECT", "gen-lang-client-0699310395"), help="GCP Project ID")
    parser.add_argument("--region", type=str, default=os.getenv("GCP_REGION", "us-central1"), help="GCP Region")
    parser.add_argument("--staging-bucket", type=str, default=os.getenv("GCS_BUCKET", "gs://edge-artifacts-gen-lang-client-0699310395"), help="GCS Bucket for artifacts")
    parser.add_argument("--container-uri", type=str, default="", help="Container URI in Artifact Registry")
    parser.add_argument("--gpu", type=str, choices=["none", "t4", "l4", "a100"], default="none", help="GPU type for Spot VM")
    parser.add_argument("--dry-run", action="store_true", help="Print job spec without launching")
    parser.add_argument("--script-path", type=str, default="edge/tools/train_v90_wide.py", help="Script to run inside container")
    parser.add_argument("--sync", action="store_true", help="Wait for job completion in terminal instead of background submission")
    parser.add_argument("--skip-package", action="store_true", help="Skip packaging and reuse existing GCS tarball")
    parser.add_argument("--timeout", type=int, default=3600, help="Max execution time in seconds before auto-killing job (default: 3600 = 1 hour)")
    parser.add_argument("--disk-type", type=str, choices=["pd-standard", "pd-ssd"], default="pd-standard", help="Boot disk type (default: pd-standard for minimal cost)")
    parser.add_argument("--disk-size-gb", type=int, default=100, help="Boot disk size in GB (default: 100)")
    return parser.parse_args()

def check_credit_safety_notice():
    print("=" * 70)
    print("  GOOGLE CLOUD VERTEX AI CREDIT SAFETY CHECK")
    print("=" * 70)
    print("  [✓] Billing SKU: Vertex AI Custom Training (Vertex AI Platform Service)")
    print("  [✓] Gen AI Credit Eligible: YES ($1,500 Credit Pool Target)")
    print("  [✓] Provisioning Model: SPOT (Max 70% Cost Discount Guardrail)")
    print("  [✓] Max Execution Timeout: 7,200s (2 Hours Hard Termination Limit)")
    print("=" * 70)

def main():
    args = parse_args()
    check_credit_safety_notice()

    project_id = args.project_id or "<YOUR_GCP_PROJECT_ID>"
    staging_bucket = args.staging_bucket or "gs://<YOUR_GCS_BUCKET_NAME>"
    container_uri = args.container_uri or f"gcr.io/{project_id}/edge-vertex:latest"

    # Map GPU choice to Vertex AI Machine Specs
    gpu_specs = {
        "none": {"machine_type": "n1-standard-4", "accelerator_type": "ACCELERATOR_TYPE_UNSPECIFIED", "accelerator_count": 0},
        "t4": {"machine_type": "n1-standard-8", "accelerator_type": "NVIDIA_TESLA_T4", "accelerator_count": 1},
        "l4": {"machine_type": "g2-standard-8", "accelerator_type": "NVIDIA_L4", "accelerator_count": 1},
        "a100": {"machine_type": "a2-highgpu-1g", "accelerator_type": "NVIDIA_TESLA_A100", "accelerator_count": 1},
    }
    
    spec = gpu_specs[args.gpu]
    # Pre-built Google Vertex AI containers (No local Docker build needed)
    prebuilt_containers = {
        "none": "us-docker.pkg.dev/vertex-ai/training/tf-cpu.2-12.py310:latest",
        "t4": "us-docker.pkg.dev/vertex-ai/training/pytorch-gpu.2-0.py310:latest",
        "l4": "us-docker.pkg.dev/vertex-ai/training/pytorch-gpu.2-0.py310:latest",
        "a100": "us-docker.pkg.dev/vertex-ai/training/pytorch-gpu.2-0.py310:latest",
    }

    container_uri = args.container_uri or prebuilt_containers[args.gpu]

    print(f"\n[JOB CONFIGURATION]")
    print(f"  Job Name:          {args.job_name}")
    print(f"  GCP Project:       {project_id}")
    print(f"  Region:            {args.region}")
    print(f"  Machine Type:      {spec['machine_type']}")
    print(f"  GPU Accelerator:   {spec['accelerator_type'] or 'None (CPU Only)'}")
    print(f"  Container Image:   {container_uri}")
    print(f"  Execution Script:  {args.script_path}")
    print(f"  Staging Bucket:    {staging_bucket}\n")

    if args.dry_run:
        print("[DRY-RUN COMPLETE] Job specification validated. No cloud resources were provisioned.")
        print("To launch this job on GCP, ensure gcloud is authenticated and re-run without --dry-run.\n")
        return

    try:
        from google.cloud import aiplatform
    except ImportError:
        print("ERROR: google-cloud-aiplatform is not installed locally.")
        print("Install via: pip install google-cloud-aiplatform")
        sys.exit(1)

    print(f"Initializing Vertex AI SDK for Project {project_id}...")
    aiplatform.init(project=project_id, location=args.region, staging_bucket=staging_bucket)

    print("Packaging repository and launching Vertex AI Custom Job on Spot compute...")
    
    def tar_filter(tarinfo):
        path_str = tarinfo.name.lower()
        parts = path_str.split("/")
        excluded_keywords = ["__pycache__", "venv", ".git", "runs", "apps", "graphify-out", "data_cache", ".pytest_cache", ".ds_store", "node_modules", ".qlib-src"]
        for part in parts:
            for ex in excluded_keywords:
                if ex in part:
                    return None
        return tarinfo

    tar_path = os.path.join(ROOT, ".tmp_edge_repo_package.tar.gz")
    if not args.skip_package:
        if os.path.exists(tar_path):
            try:
                os.remove(tar_path)
            except Exception:
                pass
        print("Creating compressed repository tarball (excluding heavy runs/logs)...")
        # COPYFILE_DISABLE=1 stops macOS's bsdtar from writing
        # LIBARCHIVE.xattr.com.apple.provenance PAX extended-attribute
        # headers into the archive. Those headers are harmless but GNU tar
        # on the container prints one "Ignoring unknown extended header
        # keyword" warning line per file on extraction -- hundreds of lines
        # that buried the real failure in every log pulled while debugging
        # the 2026-07-31 outage. See --no-same-owner/--warning below too.
        tar_cmd = (
            f"COPYFILE_DISABLE=1 tar -czf {tar_path} "
            f"--exclude='.*venv*' --exclude='.git' --exclude='__pycache__' --exclude='runs' "
            f"--exclude='apps' --exclude='graphify-out' --exclude='data_cache' --exclude='.pytest_cache' "
            f"--exclude='.ds_store' --exclude='node_modules' --exclude='.qlib-src' --exclude='.worktrees' "
            f"--exclude='.env*' --exclude='*.tar.gz' "
            f"-C {ROOT} edge TradingAlgoWork Kronos"
        )
        subprocess.run(tar_cmd, shell=True, check=True)
        size_mb = os.path.getsize(tar_path) / 1e6
        print(f"  Tarball: {os.path.basename(tar_path)} ({size_mb:.1f} MB)")

        print("Uploading repository package to Google Cloud Storage...")
        subprocess.run(
            f"gsutil cp {tar_path} {staging_bucket}/packages/edge_repo_package.tar.gz",
            shell=True,
            check=True,
        )
        print("Upload complete!")
    else:
        print("Skipping package build — using existing GCS tarball.")

    # -------------------------------------------------------------------------
    # FIX (2026-07-31): Previous jobs used bare `pip install numpy` which
    # upgraded to NumPy 2.x on the TF container, breaking sklearn's
    # `numpy.core.numeric` import at module load time.  We now install from
    # requirements-vertex.txt which pins numpy==1.26.4 and every other
    # dependency to exactly the versions the local edge/.venv-qlib used when
    # all GATE_XS* results were produced.  preflight_env.py exits non-zero
    # on any version drift so the job fails fast with a clear message rather
    # than dying deep inside model code.
    # -------------------------------------------------------------------------
    # FIX (2026-07-31, round 2): the "workerpool0-0 exited with a non-zero
    # status of N" message Vertex AI surfaces never says *which* of the 6
    # chained steps died -- every job submitted 03:27Z-20:31Z this outage
    # actually died in step 4 (preflight_env.py false-positived on
    # torch's "2.4.1+cpu" build tag; fixed separately in preflight_env.py),
    # but the exit code alone was indistinguishable from a pip resolver
    # failure, a missing script, or an OOM kill. Each step now echoes an
    # '::STEP' marker before it runs, so `gcloud logging read ... | grep
    # ::STEP` immediately shows the last step that started. Every command
    # stays chained with plain `&&` (echo cannot fail, so it never masks a
    # real non-zero exit) -- the job must still exit non-zero when it
    # genuinely fails. tar also gets --no-same-owner/--warning=no-unknown-
    # keyword so the LIBARCHIVE.xattr PAX-header spam (hundreds of lines
    # from macOS-built tarballs, see the tar_cmd COPYFILE_DISABLE comment
    # above) doesn't bury whatever error comes after it.
    # -------------------------------------------------------------------------
    remote_cmd = (
        # Step 1: pull and extract the repo package
        "echo '::STEP 1/6 gsutil-download-and-extract' && "
        f"gsutil cp {staging_bucket}/packages/edge_repo_package.tar.gz /tmp/pkg.tar.gz && "
        f"mkdir -p /workspace && "
        f"tar -xzf /tmp/pkg.tar.gz -C /workspace --no-same-owner --warning=no-unknown-keyword && "
        f"cd /workspace && "
        # Step 2: install pinned requirements — no floating versions
        "echo '::STEP 2/6 pip-install-requirements-vertex' && "
        f"pip install --quiet --no-cache-dir "
        f"--extra-index-url https://download.pytorch.org/whl/cpu "
        f"-r edge/requirements-vertex.txt && "
        # Step 3: install google-cloud SDK packages (not in requirements-vertex.txt)
        "echo '::STEP 3/6 pip-install-gcp-sdk-and-extras' && "
        f"pip install --quiet --no-cache-dir "
        f"google-cloud-aiplatform google-cloud-storage google-cloud-bigquery "
        f"xgboost conformal yfinance einops && "
        # Step 4: sanity check — exits 1 if a package is missing, 2 if a pinned
        # version drifted (local build tags like "+cpu" are normalized first)
        "echo '::STEP 4/6 preflight-env-check' && "
        f"python3 edge/tools/preflight_env.py && "
        # Step 5: run the target training script
        "echo '::STEP 5/6 run-training-script' && "
        f"python3 {args.script_path} && "
        # Step 6: upload results to GCS via google.cloud.storage Python SDK
        "echo '::STEP 6/6 upload-results-to-gcs' && "
        f"python3 -c \"import sys, glob, os; from google.cloud import storage; "
        f"b = storage.Client().bucket('{staging_bucket.replace('gs://', '')}'); "
        f"files = glob.glob('edge/runs/**/results.json', recursive=True); "
        f"print('Found results files:', files); "
        f"[b.blob(f'results/{{os.path.basename(os.path.dirname(f))}}/results.json').upload_from_filename(f) for f in files]; "
        f"print('GCS upload complete')\" && "
        "echo '::STEP 6/6 COMPLETE — all steps succeeded'"
    )

    # Use Vertex AI's CustomJob with full repo context
    worker_pool_specs = [{
        "machine_spec": {
            "machine_type": spec["machine_type"],
            "accelerator_type": spec["accelerator_type"],
            "accelerator_count": spec["accelerator_count"],
        },
        "replica_count": 1,
        "disk_spec": {
            # Default to pd-standard 100 GB for minimal cost ($0.04/GB/mo billed only during run)
            "boot_disk_type": args.disk_type,
            "boot_disk_size_gb": args.disk_size_gb,
        },
        "container_spec": {
            "image_uri": container_uri,
            "command": ["bash", "-c"],
            "args": [remote_cmd],
        },
    }]

    from google.cloud.aiplatform_v1.types import Scheduling

    job = aiplatform.CustomJob(
        display_name=args.job_name,
        worker_pool_specs=worker_pool_specs,
    )

    if args.sync:
        job.run(
            service_account=None,
            restart_job_on_worker_restart=False,
            timeout=args.timeout,
            scheduling_strategy=Scheduling.Strategy.SPOT,
            sync=True,
        )
        print(f"\n[SUCCESS] Job completed! Artifacts saved to {staging_bucket}.")
    else:
        job.submit(
            service_account=None,
            restart_job_on_worker_restart=False,
            timeout=args.timeout,
            scheduling_strategy=Scheduling.Strategy.SPOT,
        )
        print("\n[JOB SUBMITTED SUCCESSFULLY] The job is now running on GCP in the background (Spot Compute).")
        print(f"  Resource ID: {job.resource_name}")
        print(f"  Track live progress in browser: https://console.cloud.google.com/vertex-ai/training/custom-jobs?project={project_id}")

    # Clean up local temporary tarball after submission
    if os.path.exists(tar_path):
        try:
            os.remove(tar_path)
        except OSError:
            pass

if __name__ == "__main__":
    main()
