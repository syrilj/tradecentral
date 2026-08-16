#!/usr/bin/env python3
"""GCP Cloud Scheduler Provisioning Script for Shadow Evidence Loop.

Deploys Cloud Scheduler jobs targeting GCP Cloud Run daily scanner:
  - Daily 9:15 AM EST (14:15 UTC): Pre-market shadow decision scan & realization.
  - Weekly Sunday 20:00 UTC: Model reliability analysis & leaderboard refresh.

Cost: $0.00 (under 3 free cron jobs per GCP account).
"""

from __future__ import annotations

import argparse
import subprocess

import gcp_config

PROJECT_ID = gcp_config.get_project_id()
REGION = gcp_config.get_region()


def deploy_scheduler_jobs(dry_run: bool = False) -> None:
    print("=" * 60)
    print("  GCP CLOUD SCHEDULER PROVISIONING — SHADOW EVIDENCE LOOP")
    print("=" * 60)
    print(f"  Project:   {PROJECT_ID}")
    print(f"  Region:    {REGION}")
    print(f"  Dry-run:   {dry_run}")
    print("  Cost:      $0.00 (under 3 free cron jobs limit)")
    print("=" * 60)

    jobs = [
        {
            "name": "daily-shadow-scan",
            "schedule": "15 14 * * 1-5",  # Mon-Fri 14:15 UTC (9:15 EST)
            "description": "Daily pre-market shadow scan and outcome realization",
            "uri": f"https://{REGION}-{PROJECT_ID}.cloudfunctions.net/daily-plays-scanner",
        },
        {
            "name": "weekly-reliability-check",
            "schedule": "0 20 * * 0",  # Sun 20:00 UTC
            "description": "Weekly reliability evaluation and leaderboard audit",
            "uri": f"https://{REGION}-{PROJECT_ID}.cloudfunctions.net/daily-plays-scanner?action=reliability",
        },
    ]

    if len(jobs) > gcp_config.FREE_TIER_LIMITS["cloud_scheduler_jobs"]:
        raise ValueError(f"Job count ({len(jobs)}) exceeds GCP Free Tier limit of 3 jobs!")

    for j in jobs:
        print(f"\nProvisioning job [{j['name']}]...")
        cmd = (
            f"gcloud scheduler jobs create http {j['name']} "
            f"--schedule='{j['schedule']}' "
            f"--uri='{j['uri']}' "
            f"--description='{j['description']}' "
            f"--project={PROJECT_ID} --location={REGION} "
            f"--attempt-deadline=300s --max-retry-attempts=1 --min-backoff=30s || "
            f"gcloud scheduler jobs update http {j['name']} "
            f"--schedule='{j['schedule']}' "
            f"--uri='{j['uri']}' "
            f"--project={PROJECT_ID} --location={REGION} "
            f"--attempt-deadline=300s --max-retry-attempts=1 --min-backoff=30s"
        )

        if dry_run:
            print(f"  [DRY-RUN] Command: {cmd}")
        else:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if res.returncode == 0:
                print(f"  ✅ Cloud Scheduler job [{j['name']}] provisioned successfully.")
            else:
                print(f"  Notice: {res.stderr.strip() or res.stdout.strip()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print scheduler configuration without provisioning GCP resources")
    args = parser.parse_args()

    deploy_scheduler_jobs(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
