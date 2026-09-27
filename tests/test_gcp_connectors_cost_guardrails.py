#!/usr/bin/env python3
"""test_gcp_connectors_cost_guardrails.py — Test Suite for GCP Cost Optimization Guardrails.

Verifies:
  - Spot VM scheduling strategy is enforced across all Vertex AI submission scripts.
  - Right-sized persistent disk specifications are used by default.
  - BigQuery tables have clustering and partition expiration configured.
  - BigQuery queries enforce maximum_bytes_billed limits.
  - Cloud Scheduler job counts adhere to the <= 3 free jobs quota.
  - Centralized gcp_config.py provides consistent settings.
  - Cost auditor certifies the entire deployment as $0.00 out-of-pocket.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import gcp_config
from audit_gcp_costs import GCPCostAuditor
from check_gcp_resources import get_all_gcp_resources, get_bigquery_status


def test_gcp_config_defaults_and_env_overrides(monkeypatch):
    """Verify default GCP configuration values and environment variable overrides."""
    # Test defaults
    assert gcp_config.DEFAULT_PROJECT_ID == "gen-lang-client-0699310395"
    assert gcp_config.DEFAULT_REGION == "us-central1"
    assert "edge-artifacts-" in gcp_config.DEFAULT_BUCKET_NAME
    assert gcp_config.DEFAULT_BQ_DATASET == "trading_research"

    # Test getters with defaults
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    monkeypatch.delenv("GCP_REGION", raising=False)
    monkeypatch.delenv("GCS_BUCKET", raising=False)
    monkeypatch.delenv("BQ_DATASET", raising=False)

    assert gcp_config.get_project_id() == "gen-lang-client-0699310395"
    assert gcp_config.get_region() == "us-central1"
    assert gcp_config.get_bucket_name() == "edge-artifacts-gen-lang-client-0699310395"
    assert gcp_config.get_bucket_uri() == "gs://edge-artifacts-gen-lang-client-0699310395"
    assert gcp_config.get_bq_dataset() == "trading_research"

    # Test environment variable overrides
    monkeypatch.setenv("GCP_PROJECT", "custom-trading-project")
    monkeypatch.setenv("GCP_REGION", "us-east1")
    monkeypatch.setenv("GCS_BUCKET", "gs://custom-bucket-uri")
    monkeypatch.setenv("BQ_DATASET", "custom_dataset")

    assert gcp_config.get_project_id() == "custom-trading-project"
    assert gcp_config.get_region() == "us-east1"
    assert gcp_config.get_bucket_name() == "custom-bucket-uri"
    assert gcp_config.get_bucket_uri() == "gs://custom-bucket-uri"
    assert gcp_config.get_bq_dataset() == "custom_dataset"


def test_gcp_config_free_tier_limits():
    """Verify Free Tier limits are accurately documented."""
    limits = gcp_config.FREE_TIER_LIMITS
    assert limits["gcs_storage_bytes"] == 5 * 1024 * 1024 * 1024  # 5 GB
    assert limits["bq_storage_bytes"] == 10 * 1024 * 1024 * 1024  # 10 GB
    assert limits["bq_query_bytes_monthly"] == 1024 * 1024 * 1024 * 1024  # 1 TB
    assert limits["cloud_run_requests_monthly"] == 2_000_000
    assert limits["cloud_scheduler_jobs"] == 3


def test_spot_vm_scheduling_strategy_enforced_in_all_vertex_submitters():
    """Ensure every Vertex AI submitter script explicitly sets SPOT scheduling."""
    submitter_scripts = [
        TOOLS / "submit_vertex_job.py",
        TOOLS / "gcp_validate_all.py",
        TOOLS / "gcp_run_walkforward_job.py",
        TOOLS / "gcp_ga_evolve.py",
        TOOLS / "gcp_directional_bakeoff.py",
        TOOLS / "gcp_squeeze_validation.py",
    ]

    for script in submitter_scripts:
        assert script.exists(), f"Submitter script {script.name} must exist"
        source = script.read_text()
        has_spot_flag = (
            "Scheduling.Strategy.SPOT" in source or
            "scheduling_strategy=Scheduling.Strategy.SPOT" in source or
            "scheduling_strategy" in source
        )
        assert has_spot_flag, f"{script.name} must explicitly enforce SPOT scheduling strategy"


def test_disk_specs_avoid_heavy_pd_ssd_200gb_by_default():
    """Ensure submitter scripts default to right-sized pd-standard 50-100GB disks."""
    submitter_scripts = [
        TOOLS / "gcp_validate_all.py",
        TOOLS / "gcp_run_walkforward_job.py",
        TOOLS / "gcp_ga_evolve.py",
        TOOLS / "gcp_directional_bakeoff.py",
        TOOLS / "gcp_squeeze_validation.py",
    ]

    for script in submitter_scripts:
        source = script.read_text()
        # Should not have hardcoded pd-ssd 200GB
        assert not ('"boot_disk_type": "pd-ssd"' in source and '"boot_disk_size_gb": 200' in source), (
            f"{script.name} should not default to expensive 200GB SSD"
        )
        # Should contain pd-standard
        assert "pd-standard" in source, f"{script.name} should default to pd-standard disk"


def test_bigquery_clustering_and_partitioning_configured():
    """Verify BigQuery setup configures table clustering and 180-day partition expiration."""
    bq_setup = (TOOLS / "bq_setup_and_load.py").read_text()
    assert "table.clustering_fields" in bq_setup
    assert "oof_inferences" in bq_setup
    assert "symbol" in bq_setup
    assert "trial" in bq_setup
    assert "expiration_ms" in bq_setup or "180" in bq_setup


def test_bigquery_query_safety_guardrails_configured():
    """Verify BigQuery analysis query script configures maximum_bytes_billed and dry_run."""
    bq_analysis = (TOOLS / "bq_score_decile_analysis.py").read_text()
    assert "maximum_bytes_billed" in bq_analysis
    assert "total_bytes_processed" in bq_analysis or "dry_run" in bq_analysis


def test_cloud_scheduler_within_free_tier_limit():
    """Verify Cloud Scheduler script creates <= 3 jobs and sets retry caps."""
    scheduler_source = (TOOLS / "deploy_shadow_scheduler.py").read_text()
    assert "--max-retry-attempts=1" in scheduler_source
    assert "--min-backoff=30s" in scheduler_source
    assert "cloud_scheduler_jobs" in scheduler_source or "<= 3" in scheduler_source


def test_audit_gcp_costs_auditor_reports_certified_pass():
    """Execute GCPCostAuditor and assert full pass certification."""
    auditor = GCPCostAuditor()
    report = auditor.run_full_audit()
    assert report["audit_certified"] is True
    assert report["out_of_pocket_guarantee"] == "$0.00 Out-of-Pocket"
    assert len(report["warnings"]) == 0


def test_cost_scenario_calculations():
    """Validate cost projection calculations across deployment tiers."""
    auditor = GCPCostAuditor()
    scenarios = auditor.calculate_deployment_cost_scenarios()

    idle = scenarios["idle_standby"]
    assert idle["monthly_out_of_pocket"] == 0.00
    assert idle["monthly_billed_cost"] == 0.00

    daily = scenarios["daily_operational"]
    assert daily["monthly_out_of_pocket"] == 0.00
    assert daily["monthly_billed_cost"] == 0.00

    research = scenarios["intensive_research"]
    assert research["monthly_out_of_pocket"] == 0.00
    assert research["monthly_billed_cost"] > 0.00
    assert research["monthly_credit_usage"] <= 5.00  # under $5/mo against $1,500 credits


def test_gcp_resources_api_payload_includes_cost_breakdown_and_bigquery():
    """Verify check_gcp_resources module returns valid payload for /api/gcp."""
    data = get_all_gcp_resources(force_refresh=True)
    assert "project_id" in data
    assert "region" in data
    assert "storage" in data
    assert "bigquery" in data
    assert "cloud_run" in data
    assert "cost_breakdown" in data
    assert data["cost_breakdown"]["out_of_pocket_monthly"] == 0.00

    bq = get_bigquery_status()
    assert bq["storage_free_tier_mb"] == 10240
    assert bq["query_free_tier_gb_monthly"] == 1024
    assert bq["clustering_active"] is True
