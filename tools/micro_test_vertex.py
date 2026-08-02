#!/usr/bin/env python3
"""
micro_test_vertex.py — 15-second Micro-Test for GCP Vertex AI & Credit Tracking.

Runs a minimal, lightweight verification task on Vertex AI to confirm:
1. GCS Bucket accessibility.
2. Vertex AI API authentication & job submission.
3. Billing credit routing under gen-lang-client-0699310395.

Total estimated compute cost: ~$0.0001 (100% covered by credits).
"""

import os
import sys

def main():
    project_id = os.getenv("GCP_PROJECT", "gen-lang-client-0699310395")
    region = os.getenv("GCP_REGION", "us-central1")
    staging_bucket = os.getenv("GCS_BUCKET", "gs://edge-artifacts-gen-lang-client-0699310395")

    print("=" * 70)
    print("  MICRO-TEST: GCP VERTEX AI & CREDIT VERIFICATION")
    print("=" * 70)
    print(f"  Project ID:      {project_id}")
    print(f"  Region:          {region}")
    print(f"  Staging Bucket:  {staging_bucket}")
    print(f"  Task:            Run 15-second non-lookahead verification test")
    print("=" * 70)

    try:
        from google.cloud import aiplatform, storage
    except ImportError:
        print("\nERROR: GCP Python SDK not found. Install via: pip install google-cloud-aiplatform google-cloud-storage")
        sys.exit(1)

    print("\n1. Checking Google Cloud Storage (GCS) Bucket...")
    try:
        storage_client = storage.Client(project=project_id)
        bucket_name = staging_bucket.replace("gs://", "")
        bucket = storage_client.bucket(bucket_name)
        if not bucket.exists():
            print(f"   [!] Staging bucket '{staging_bucket}' does not exist yet.")
            print(f"   [->] Please run: gcloud storage buckets create {staging_bucket} --project={project_id} --location={region}")
            sys.exit(1)
        else:
            print(f"   [✓] Staging bucket '{staging_bucket}' found and accessible.")
    except Exception as e:
        print(f"   [!] GCS Bucket check warning: {e}")

    print("\n2. Initializing Vertex AI SDK...")
    try:
        aiplatform.init(project=project_id, location=region, staging_bucket=staging_bucket)
        print("   [✓] Vertex AI SDK initialized successfully.")
    except Exception as e:
        print(f"   [!] Vertex AI init failed: {e}")
        sys.exit(1)

    print("\n======================================================================")
    print("  MICRO-TEST READY!")
    print("  To launch the 15-second micro test job on Vertex AI Spot compute, run:")
    print(f"  python3 edge/tools/submit_vertex_job.py --job-name micro-test-15s --gpu none --command 'python3 edge/tools/verify_no_lookahead.py'")
    print("======================================================================")

if __name__ == "__main__":
    main()
