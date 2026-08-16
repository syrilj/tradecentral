#!/usr/bin/env python3
"""fetch_gcp_results.py — Pull Vertex AI training results from GCS and update dashboard.

Downloads results.json artifacts from GCS for every model gate, writes them to
the expected local paths (edge/runs/*/results.json), and re-renders the dashboard.

Run after GCP validation jobs finish:
  python3 edge/tools/fetch_gcp_results.py

Then open edge/runs/dashboard.html in your browser.

Usage:
  python3 edge/tools/fetch_gcp_results.py
  python3 edge/tools/fetch_gcp_results.py --dry-run   (show what would be fetched)
  python3 edge/tools/fetch_gcp_results.py --no-render  (download only, skip dashboard re-render)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EDGE = ROOT / "edge"
PROJECT_ID = os.getenv("GCP_PROJECT", "gen-lang-client-0699310395")
STAGING_BUCKET = os.getenv("GCS_BUCKET", "gs://edge-artifacts-gen-lang-client-0699310395")

# Mapping: GCS artifact path → local results path
ARTIFACT_MAP = {
    # Validation jobs
    f"{STAGING_BUCKET}/results/pead_catalyst/results.json": EDGE / "runs" / "pead_catalyst" / "results.json",
    f"{STAGING_BUCKET}/results/finra_factor/results.json": EDGE / "runs" / "finra_factor" / "results.json",
    f"{STAGING_BUCKET}/results/qlib_xs3/results.json": EDGE / "runs" / "qlib_xs3" / "results.json",
    f"{STAGING_BUCKET}/results/qlib_xs2/results.json": EDGE / "runs" / "qlib_xs2" / "results.json",
    # Experiment challenger jobs
    f"{STAGING_BUCKET}/results/pead_v2/results.json": EDGE / "runs" / "pead_v2" / "results.json",
    f"{STAGING_BUCKET}/results/pead_xgb/results.json": EDGE / "runs" / "pead_xgb" / "results.json",
    f"{STAGING_BUCKET}/results/lgbm_hybrid/results.json": EDGE / "runs" / "lgbm_hybrid" / "results.json",
}


def _gsutil_stat(gcs_path: str) -> bool:
    """Return True if the GCS object exists."""
    r = subprocess.run(
        f"gsutil stat {gcs_path}", shell=True, capture_output=True, text=True, timeout=10
    )
    return r.returncode == 0


def _gsutil_cp(gcs_src: str, local_dst: Path) -> bool:
    """Copy a GCS object to a local path. Returns True on success."""
    local_dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        f"gsutil cp {gcs_src} {local_dst}", shell=True, capture_output=True, text=True, timeout=60
    )
    return r.returncode == 0


def _annotate_result(result: dict, gcs_path: str) -> dict:
    """Add GCP provenance fields to a result dict."""
    result["gcp_validated"] = True
    result["gcp_artifact"] = gcs_path
    result["fetched_utc"] = datetime.now(timezone.utc).isoformat()
    return result


def print_summary(results: dict[str, dict | None]) -> None:
    """Print a human-readable summary table of all fetched results."""
    print("\n" + "=" * 80)
    print("  GCP VALIDATION RESULTS SUMMARY")
    print("=" * 80)
    fmt = "{:<30} {:<12} {:<10} {:<10} {:<8}"
    print(fmt.format("Model", "Verdict", "IC", "Sharpe", "Net%"))
    print("-" * 80)
    for name, r in results.items():
        if r is None:
            print(fmt.format(name, "NOT READY", "—", "—", "—"))
            continue
        verdict = r.get("verdict", "?")
        ic = r.get("mean_rank_ic", r.get("mean_ic", None))
        sharpe = r.get("sharpe_ratio", r.get("sharpe", None))
        net = r.get("net_annual_return_pct", r.get("net_annual_return", None))
        ic_str = f"{ic:.4f}" if ic is not None else "—"
        sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "—"
        if net is not None:
            net_str = f"{net*100:.1f}%" if abs(net) < 10 else f"{net:.1f}%"
        else:
            net_str = "—"
        verdict_icon = "✅" if verdict == "GO" else ("❌" if verdict == "NO-GO" else "⚠️")
        print(fmt.format(name, f"{verdict_icon} {verdict}", ic_str, sharpe_str, net_str))

    print("=" * 80)

    # Recommendation
    go_models = [n for n, r in results.items() if r and r.get("verdict") == "GO"]
    nogo_models = [n for n, r in results.items() if r and r.get("verdict") == "NO-GO"]
    not_ready = [n for n, r in results.items() if r is None]
    print(f"\nGO models ({len(go_models)}): {', '.join(go_models) or 'none'}")
    print(f"NO-GO models ({len(nogo_models)}): {', '.join(nogo_models) or 'none'}")
    if not_ready:
        print(f"Still running ({len(not_ready)}): {', '.join(not_ready)}")

    # Upgrade recommendation for challengers
    for name, r in results.items():
        rec = r.get("model_upgrade_recommendation") if r else None
        if rec:
            print(f"\n📌 {name}: {rec}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Show what would be fetched without downloading")
    ap.add_argument("--no-render", action="store_true", help="Download only, skip dashboard re-render")
    ap.add_argument("--force", action="store_true", help="Overwrite existing local results")
    args = ap.parse_args(argv)

    print("=" * 70)
    print("  FETCH GCP RESULTS → UPDATE LOCAL ARTIFACTS")
    print("=" * 70)
    print(f"  Bucket: {STAGING_BUCKET}")
    print(f"  Dry-run: {args.dry_run}")

    fetched_results: dict[str, dict | None] = {}

    for gcs_path, local_path in ARTIFACT_MAP.items():
        model_name = local_path.parent.name
        print(f"\n[{model_name}]")
        print(f"  GCS: {gcs_path}")
        print(f"  Local: {local_path}")

        if args.dry_run:
            exists = _gsutil_stat(gcs_path)
            print(f"  Status: {'EXISTS' if exists else 'NOT FOUND'}")
            fetched_results[model_name] = None if not exists else {}
            continue

        # Check if already fresh and not forced
        if local_path.exists() and not args.force:
            try:
                with open(local_path) as f:
                    existing = json.load(f)
                if existing.get("gcp_validated"):
                    print("  Already GCP-validated — skipping (use --force to re-fetch)")
                    fetched_results[model_name] = existing
                    continue
            except Exception:
                pass

        # Check GCS existence
        if not _gsutil_stat(gcs_path):
            print("  ⏳ Not available yet (job may still be running)")
            fetched_results[model_name] = None
            continue

        # Download
        print("  Downloading...")
        if _gsutil_cp(gcs_path, local_path):
            try:
                with open(local_path) as f:
                    result = json.load(f)
                result = _annotate_result(result, gcs_path)
                with open(local_path, "w") as f:
                    json.dump(result, f, indent=2)
                print(f"  ✅ Downloaded: verdict={result.get('verdict', '?')}")
                fetched_results[model_name] = result
            except Exception as e:
                print(f"  ⚠️  Downloaded but parse failed: {e}")
                fetched_results[model_name] = None
        else:
            print("  ❌ gsutil cp failed")
            fetched_results[model_name] = None

    # Print summary
    print_summary(fetched_results)

    # Re-render dashboard
    if not args.dry_run and not args.no_render:
        ready_count = sum(1 for r in fetched_results.values() if r is not None)
        if ready_count > 0:
            print(f"\nRe-rendering dashboard with {ready_count} updated result(s)...")
            rc = os.system(f"python3 {EDGE}/tools/render_dashboard.py")
            if rc == 0:
                dashboard_path = EDGE / "runs" / "dashboard.html"
                print(f"✅ Dashboard updated: {dashboard_path}")
            else:
                print("⚠️  Dashboard render failed — check render_dashboard.py")
        else:
            print("\nNo new results to render.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
