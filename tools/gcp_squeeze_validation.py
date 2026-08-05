#!/usr/bin/env python3
"""Submit gamma-squeeze theory validation on Vertex AI (SPOT)."""
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
PACKAGE_URI = f"{BUCKET_URI}/packages/edge_squeeze_validation_v1.tar.gz"
RESULT_PREFIX = "results/squeeze_validation_v1"
CONTAINER_URI = "us-docker.pkg.dev/vertex-ai/training/tf-cpu.2-12.py310:latest"
PACKAGE_PATH = Path("/tmp/edge_squeeze_validation_v1.tar.gz")
# Ship full packages: edge.research.__init__ imports hashing/labels/etc., and
# edge.daily_plays.__init__ imports contracts. Partial packaging caused the
# first Vertex job to fail with ModuleNotFoundError: edge.research.hashing.
PACKAGE_INCLUDE = (
    "edge/__init__.py",
    "edge/daily_plays",
    "edge/research",
    "edge/tools/run_squeeze_validation.py",
    "edge/data/option_chains",
    "edge/data/1d",
)
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".ipynb_checkpoints"}


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
    print(f"Built {PACKAGE_PATH} ({size_mb:.1f} MB)")
    return PACKAGE_PATH


def upload_package(path: Path) -> None:
    subprocess.run(["gsutil", "cp", str(path), PACKAGE_URI], check=True)


def remote_command() -> str:
    # PYTHONPATH=/workspace so `import edge...` works regardless of CWD tricks.
    # Install deps that research.__init__ may pull transitively are avoided by
    # only importing squeeze_validation after path setup; keep scientific stack pinned.
    return (
        "set -euo pipefail && "
        "echo '::STEP 1/6 download-package' && "
        f"gsutil cp {PACKAGE_URI} /tmp/package.tar.gz && "
        "mkdir -p /workspace && "
        "tar -xzf /tmp/package.tar.gz -C /workspace --no-same-owner --warning=no-unknown-keyword && "
        "cd /workspace && "
        "export PYTHONPATH=/workspace:${PYTHONPATH:-} && "
        "echo '::STEP 2/6 install-deps' && "
        "pip install --quiet --no-cache-dir "
        "'numpy==1.26.4' 'scipy==1.15.3' 'pandas==2.2.2' 'pyarrow==25.0.0' "
        "'yfinance>=0.2.40' && "
        "echo '::STEP 3/6 verify-imports' && "
        "python3 -c \""
        "import numpy,pandas,pyarrow; "
        "import edge.daily_plays.gex_core; "
        "import edge.research.hashing; "
        "import edge.research.squeeze_validation; "
        "print('imports-ok', numpy.__version__, pandas.__version__)"
        "\" && "
        "echo '::STEP 4/6 run-squeeze-validation' && "
        "python3 edge/tools/run_squeeze_validation.py "
        "--out-dir edge/runs/squeeze_validation && "
        "echo '::STEP 5/6 list-artifacts' && "
        "ls -la edge/runs/squeeze_validation && "
        "echo '::STEP 6/6 upload' && "
        f"gsutil -m cp -r edge/runs/squeeze_validation/* {BUCKET_URI}/{RESULT_PREFIX}/ && "
        "echo '::COMPLETE squeeze-validation-v1'"
    )


def submit(*, dry_run: bool) -> str:
    package = build_package()
    command = remote_command()
    spec = [{
        "machine_spec": {
            "machine_type": "n1-standard-4",
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
        print(json.dumps({"worker_pool_specs": spec, "strategy": "SPOT"}, indent=2))
        return "dry-run"
    upload_package(package)
    from google.cloud import aiplatform
    from google.cloud.aiplatform_v1.types import Scheduling

    aiplatform.init(project=PROJECT_ID, location=REGION, staging_bucket=BUCKET_URI)
    job = aiplatform.CustomJob(
        display_name=f"squeeze-validation-v1-{int(time.time())}",
        worker_pool_specs=spec,
    )
    job.submit(
        timeout=3_600,
        restart_job_on_worker_restart=False,
        scheduling_strategy=Scheduling.Strategy.SPOT,
    )
    print(job.resource_name)
    return str(job.resource_name)


def fetch(*, output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = str(output_dir)
    subprocess.run(
        ["gsutil", "-m", "cp", "-r", f"{BUCKET_URI}/{RESULT_PREFIX}/*", dest],
        check=True,
    )
    return sorted(str(p) for p in output_dir.iterdir())


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["submit", "fetch", "dry-run"])
    p.add_argument("--output-dir", type=Path, default=EDGE_ROOT / "runs" / "squeeze_validation_gcp")
    args = p.parse_args()
    if args.action == "dry-run":
        submit(dry_run=True)
    elif args.action == "submit":
        submit(dry_run=False)
    else:
        files = fetch(output_dir=args.output_dir)
        print("fetched:", *files, sep="\n  ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
