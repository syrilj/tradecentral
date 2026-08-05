#!/usr/bin/env python3
"""Submit / fetch / status for the genetic evolution lab on Vertex AI (GCP).

Mirrors ``gcp_directional_bakeoff.py``: package code + daily bars, run on a
Spot CPU worker, upload ``runs/ga/*`` to GCS.

Usage:
  # Validate job spec without spending credits
  python edge/tools/gcp_ga_evolve.py submit --dry-run

  # Launch full evolution on Vertex SPOT CPU
  python edge/tools/gcp_ga_evolve.py submit --pop 300 --gens 20

  # Pull artifacts
  python edge/tools/gcp_ga_evolve.py fetch

  # Job state
  python edge/tools/gcp_ga_evolve.py status projects/.../customJobs/...
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time


EDGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EDGE_ROOT.parent
PROJECT_ID = os.getenv("GCP_PROJECT", "gen-lang-client-0699310395")
REGION = os.getenv("GCP_REGION", "us-central1")
BUCKET_NAME = os.getenv("GCS_BUCKET", "edge-artifacts-gen-lang-client-0699310395").removeprefix("gs://")
BUCKET_URI = f"gs://{BUCKET_NAME}"
PACKAGE_URI = f"{BUCKET_URI}/packages/edge_ga_evolve_v1.tar.gz"
RESULT_PREFIX = "results/ga_evolve_v1"
CONTAINER_URI = "us-docker.pkg.dev/vertex-ai/training/tf-cpu.2-12.py310:latest"
PACKAGE_PATH = Path("/tmp/edge_ga_evolve_v1.tar.gz")
PACKAGE_INCLUDE = (
    "edge/__init__.py",
    "edge/research",
    "edge/tools/run_ga_evolve.py",
    "edge/config/universe_directional_v2.json",
    "edge/data/1d",
)
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".ipynb_checkpoints", "mlruns", "node_modules"}


def build_package() -> Path:
    def package_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if set(Path(info.name).parts) & SKIP_PARTS or info.name.endswith((".pyc", ".pyo")):
            return None
        return info

    PACKAGE_PATH.unlink(missing_ok=True)
    with tarfile.open(PACKAGE_PATH, "w:gz") as archive:
        for relative in PACKAGE_INCLUDE:
            source = REPO_ROOT / relative
            if not source.exists():
                raise FileNotFoundError(f"required package path missing: {source}")
            archive.add(source, arcname=relative, filter=package_filter)
    size_mb = PACKAGE_PATH.stat().st_size / 1_000_000
    if size_mb > 250:
        raise RuntimeError(f"GA package unexpectedly large: {size_mb:.1f} MB")
    print(f"Built {PACKAGE_PATH} ({size_mb:.1f} MB)")
    return PACKAGE_PATH


def upload_package(path: Path) -> None:
    subprocess.run(["gsutil", "cp", str(path), PACKAGE_URI], check=True)


def remote_command(*, pop: int, gens: int, seed: int, max_symbols: int | None) -> str:
    max_sym_flag = f"--max-symbols {int(max_symbols)}" if max_symbols else ""
    return (
        "set -euo pipefail && "
        "echo '::STEP 1/5 download-package' && "
        f"gsutil cp {PACKAGE_URI} /tmp/package.tar.gz && "
        "mkdir -p /workspace && "
        "tar -xzf /tmp/package.tar.gz -C /workspace --no-same-owner --warning=no-unknown-keyword && "
        "cd /workspace && "
        "echo '::STEP 2/5 install-pinned-dependencies' && "
        "pip install --quiet --no-cache-dir "
        "'numpy==1.26.4' 'scipy==1.15.3' 'pandas==2.2.2' 'pyarrow==25.0.0' && "
        "echo '::STEP 3/5 verify-environment' && "
        "python3 -c \"import numpy,pandas,pyarrow; print(numpy.__version__, pandas.__version__)\" && "
        "echo '::STEP 4/5 execute-ga-evolve' && "
        f"python3 edge/tools/run_ga_evolve.py --pop {int(pop)} --gens {int(gens)} "
        f"--seed {int(seed)} {max_sym_flag} && "
        "echo '::STEP 5/5 upload-artifacts' && "
        f"gsutil -m cp -r edge/runs/ga/* {BUCKET_URI}/{RESULT_PREFIX}/ && "
        "echo '::COMPLETE ga-evolve-v1'"
    )


def submit(
    *,
    dry_run: bool,
    pop: int,
    gens: int,
    seed: int,
    max_symbols: int | None,
    machine_type: str,
) -> str:
    print("=" * 70)
    print("  GA EVOLUTION — VERTEX AI SPOT (credit-friendly)")
    print("=" * 70)
    print(f"  Project:   {PROJECT_ID}")
    print(f"  Region:    {REGION}")
    print(f"  Bucket:    {BUCKET_URI}")
    print(f"  Pop/Gens:  {pop} / {gens}")
    print(f"  Machine:   {machine_type} (SPOT)")
    print("=" * 70)

    package = build_package()
    command = remote_command(pop=pop, gens=gens, seed=seed, max_symbols=max_symbols)
    spec = [{
        "machine_spec": {
            "machine_type": machine_type,
            "accelerator_type": "ACCELERATOR_TYPE_UNSPECIFIED",
            "accelerator_count": 0,
        },
        "replica_count": 1,
        "disk_spec": {"boot_disk_type": "pd-standard", "boot_disk_size_gb": 100},
        "container_spec": {
            "image_uri": CONTAINER_URI,
            "command": ["bash", "-c"],
            "args": [command],
        },
    }]
    if dry_run:
        print(json.dumps({
            "worker_pool_specs": spec,
            "strategy": "SPOT",
            "timeout_seconds": 14_400,
            "package_uri": PACKAGE_URI,
            "result_prefix": f"{BUCKET_URI}/{RESULT_PREFIX}/",
        }, indent=2))
        return "dry-run"

    upload_package(package)
    from google.cloud import aiplatform
    from google.cloud.aiplatform_v1.types import Scheduling

    aiplatform.init(project=PROJECT_ID, location=REGION, staging_bucket=BUCKET_URI)
    job = aiplatform.CustomJob(
        display_name=f"ga-evolve-v1-{int(time.time())}",
        worker_pool_specs=spec,
    )
    job.submit(
        timeout=14_400,
        restart_job_on_worker_restart=False,
        scheduling_strategy=Scheduling.Strategy.SPOT,
    )
    print(job.resource_name)
    return str(job.resource_name)


def fetch(*, output_dir: Path) -> list[str]:
    from google.cloud import storage

    client = storage.Client(project=PROJECT_ID)
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []
    for blob in client.list_blobs(BUCKET_NAME, prefix=f"{RESULT_PREFIX}/"):
        if blob.name.endswith("/"):
            continue
        # Preserve run subdirectories when present
        rel = blob.name[len(RESULT_PREFIX) :].lstrip("/")
        target = output_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(target)
        downloaded.append(str(target))
    if not downloaded:
        raise FileNotFoundError(f"no artifacts under gs://{BUCKET_NAME}/{RESULT_PREFIX}/")
    print(json.dumps(downloaded, indent=2))
    return downloaded


def status(job_id: str) -> dict[str, object]:
    from google.cloud import aiplatform

    aiplatform.init(project=PROJECT_ID, location=REGION)
    job = aiplatform.CustomJob.get(resource_name=job_id)
    payload = {
        "resource_name": job.resource_name,
        "display_name": job.display_name,
        "state": str(job.state),
        "error": str(job.error) if job.error else None,
    }
    print(json.dumps(payload, indent=2))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    submit_parser = sub.add_parser("submit")
    submit_parser.add_argument("--dry-run", action="store_true")
    submit_parser.add_argument("--pop", type=int, default=300)
    submit_parser.add_argument("--gens", type=int, default=20)
    submit_parser.add_argument("--seed", type=int, default=20260803)
    submit_parser.add_argument("--max-symbols", type=int, default=None)
    submit_parser.add_argument("--machine-type", type=str, default="n1-standard-8")

    fetch_parser = sub.add_parser("fetch")
    fetch_parser.add_argument(
        "--output-dir",
        type=Path,
        default=EDGE_ROOT / "runs" / "ga",
    )

    status_parser = sub.add_parser("status")
    status_parser.add_argument("job_id")

    args = parser.parse_args()
    if args.command == "submit":
        submit(
            dry_run=args.dry_run,
            pop=args.pop,
            gens=args.gens,
            seed=args.seed,
            max_symbols=args.max_symbols,
            machine_type=args.machine_type,
        )
    elif args.command == "fetch":
        fetch(output_dir=args.output_dir)
    else:
        status(args.job_id)


if __name__ == "__main__":
    main()
