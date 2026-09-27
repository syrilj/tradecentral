"""Contract coverage for the daily-plays read endpoints.

The /api/plays endpoint is read-only: it reconstructs the latest persisted
run from the ledger without recomputing the pipeline. These tests exercise
that reconstruction against synthetic run directories, including the
fail-closed NO PLAY case and the honest fallbacks for missing artifacts.
"""
from __future__ import annotations

import json
from pathlib import Path

from edge.tools import api_server


def _write_run(root: Path, run_id: str, *, decisions: list[dict] | None = None,
               plays: list[dict] | None = None, candidates: list[dict] | None = None,
               snapshots: list[dict] | None = None, discovery: dict | None = None,
               flow_activity: dict | None = None, research_board: list[dict] | None = None,
               manifest: dict | None = None) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "manifest.json": manifest or {
            "run_id": run_id,
            "requested_for": "2026-08-17",
            "asof_utc": "2026-08-17T14:05:00Z",
            "market_session": "regular",
            "mode": "live",
            "account": 10000.0,
            "config_hash": "c" * 64,
            "warnings": [],
        },
        "decisions.json": decisions if decisions is not None else [],
        "plays.json": plays if plays is not None else [],
        "candidates.json": candidates if candidates is not None else [],
        "option_snapshots.json": snapshots if snapshots is not None else [],
        "discovery.json": discovery if discovery is not None else {},
        "flow_activity.json": flow_activity if flow_activity is not None else {},
        "research_board.json": research_board if research_board is not None else [],
    }
    for name, value in artifacts.items():
        (run_dir / name).write_text(json.dumps(value), encoding="utf-8")
    return run_dir


def _decision(symbol: str, state: str, *, reasons: list[str] | None = None,
              failed: list[str] | None = None) -> dict:
    return {
        "play_id": f"run:{symbol}:long_call",
        "symbol": symbol,
        "side": "long",
        "strategy": "long_call",
        "state": state,
        "rank": 1,
        "thesis": ["Model and research candidate; decision support only."],
        "invalidation": [],
        "entry": {
            "limit_reference": 0.0,
            "underlying_reference": 0.0,
            "quote_asof_utc": "2026-08-17T14:05:00Z",
            "max_quote_age_seconds": 30,
        },
        "legs": [],
        "risk": {"account": 10000.0, "max_loss_dollars": 0.0, "max_loss_pct": 0.0,
                 "contracts": 0, "reward_risk_reference": None},
        "confidence": {
            "state": state,
            "confidence_kind": "ordinal_score",
            "evidence_grade": "C",
            "model_probability": None,
            "calibrated_probability": None,
            "calibration_version": None,
            "reasons": reasons or [],
            "failed_checks": failed or [],
            "probability_target": None,
            "horizon_days": None,
            "entry_threshold": None,
            "threshold_version": None,
            "model_artifact_sha256": None,
            "promotion_authorized": False,
        },
        "evidence": {},
        "freshness": {},
        "provenance": {"decision_support_only": True, "shadow_only": True},
    }


def test_missing_output_root_is_unavailable_with_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "_DAILY_PLAYS_OUTPUT_ROOT", tmp_path / "nope")

    payload = api_server._latest_plays_payload()

    assert payload["available"] is False
    assert "No daily plays runs have been persisted yet." in payload["reason"]


def test_latest_run_reconstructs_funnel_and_decision_buckets(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "_DAILY_PLAYS_OUTPUT_ROOT", tmp_path)
    _write_run(
        tmp_path,
        "20260817T140500Z-aaaa",
        decisions=[
            _decision("NVDA", "ENTER", reasons=["calibrated_probability_passed"]),
            _decision("MU", "WATCH", reasons=["model_probability_below_entry_threshold"]),
            _decision("SPY", "ABSTAIN", reasons=["no_directional_model_setup"]),
        ],
        plays=[_decision("NVDA", "ENTER", reasons=["calibrated_probability_passed"])],
        candidates=[{"symbol": "NVDA", "side": "long", "rank": 1, "confidence": {}}],
        snapshots=[{"symbol": "NVDA", "provider": "lse", "degraded": False, "contracts": []}],
        discovery={
            "sector_books_scored": 14,
            "targeted_count": 25,
            "model_covered_symbols": ["NVDA", "MU", "SPY"],
            "market_map": {
                "source": "sector-flow",
                "rotation": {"kind": "semis_to_tech", "confidence": 0.9, "is_definitive": True},
                "money_in": [{"etf": "XLY", "name": "Discretionary", "direction": "in",
                              "rs_1d": 0.02, "definitive": True}],
                "money_out": [],
            },
        },
        flow_activity={
            "coverage": {"requested": 25, "completed": 20, "with_activity": 20},
            "rows": [{"symbol": "NVDA", "direction": "neutral", "activity_rank": 1,
                      "evidence": {"premium": 100000.0, "alert_count": 10}}],
        },
        manifest={
            "run_id": "20260817T140500Z-aaaa",
            "requested_for": "2026-08-17",
            "asof_utc": "2026-08-17T14:05:00Z",
            "market_session": "regular",
            "mode": "live",
            "account": 10000.0,
            "config_hash": "c" * 64,
            "warnings": ["unsupported_promoted_symbol:TSLA", "unsupported_promoted_symbol:TSLA"],
        },
    )

    payload = api_server._latest_plays_payload()

    assert payload["available"] is True
    assert payload["status"] == "COMPLETE"
    assert payload["run_id"] == "20260817T140500Z-aaaa"
    assert [row["symbol"] for row in payload["plays"]] == ["NVDA"]
    assert [row["symbol"] for row in payload["watchlist"]] == ["MU"]
    assert [row["symbol"] for row in payload["rejections"]] == ["SPY"]
    assert [row["symbol"] for row in payload["candidates"]] == ["NVDA"]
    assert payload["scan_scope"]["sector_books_scored"] == 14
    assert payload["scan_scope"]["targeted_count"] == 25
    assert payload["scan_scope"]["model_domain_supported"] == 3
    assert payload["scan_scope"]["successfully_scanned_candidates"] == 3
    assert payload["scan_scope"]["directional_setups"] == 0
    assert payload["scan_scope"]["chain_requests"] is None
    assert payload["scan_scope"]["chain_snapshots"] == 1
    assert payload["scan_scope"]["flow_activity_requested"] == 25
    assert payload["scan_scope"]["flow_activity_observed"] == 20
    assert payload["scan_scope"]["unavailable_model_symbols"] == ["TSLA"]
    assert payload["decision_blockers"] == [
        "calibrated_probability_passed",
        "model_probability_below_entry_threshold",
        "no_directional_model_setup",
    ]


def test_no_play_run_keeps_honest_fallback_blocker(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "_DAILY_PLAYS_OUTPUT_ROOT", tmp_path)
    _write_run(tmp_path, "20260817T140500Z-bbbb", decisions=[], plays=[])

    payload = api_server._latest_plays_payload()

    assert payload["available"] is True
    assert payload["status"] == "NO_PLAY"
    assert payload["plays"] == []
    assert payload["decision_blockers"] == ["no_successfully_scanned_model_candidates"]


def test_abstained_decisions_without_reasons_get_pipeline_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "_DAILY_PLAYS_OUTPUT_ROOT", tmp_path)
    _write_run(
        tmp_path,
        "20260817T140500Z-cccc",
        decisions=[_decision("SPY", "ABSTAIN", reasons=[])],
        plays=[],
    )

    payload = api_server._latest_plays_payload()

    assert payload["status"] == "NO_PLAY"
    assert payload["decision_blockers"] == ["no_live_validated_actionable_plays"]


def test_missing_optional_artifacts_never_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "_DAILY_PLAYS_OUTPUT_ROOT", tmp_path)
    run_dir = tmp_path / "20260817T140500Z-dddd"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": "20260817T140500Z-dddd", "asof_utc": "2026-08-17T14:05:00Z",
                    "market_session": "regular", "mode": "live", "account": 10000.0,
                    "config_hash": "c" * 64, "warnings": []}),
        encoding="utf-8",
    )

    payload = api_server._latest_plays_payload()

    assert payload["available"] is True
    assert payload["plays"] == []
    assert payload["watchlist"] == []
    assert payload["rejections"] == []
    assert payload["candidates"] == []
    assert payload["research_board"] == []
    assert payload["scan_scope"]["chain_snapshots"] == 0
    assert payload["decision_blockers"] == ["no_successfully_scanned_model_candidates"]


def test_unreadable_manifest_is_unavailable_with_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(api_server, "_DAILY_PLAYS_OUTPUT_ROOT", tmp_path)
    run_dir = tmp_path / "20260817T140500Z-eeee"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text("{not valid json", encoding="utf-8")

    payload = api_server._latest_plays_payload()

    assert payload["available"] is False
    assert "no readable manifest" in payload["reason"]


def test_plays_endpoint_serves_reconstructed_payload(tmp_path, monkeypatch, api_client):
    monkeypatch.setattr(api_server, "_DAILY_PLAYS_OUTPUT_ROOT", tmp_path)
    _write_run(tmp_path, "20260817T140500Z-ffff", decisions=[], plays=[])

    response = api_client.get("/api/plays")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["status"] == "NO_PLAY"
    assert body["decision_blockers"] == ["no_successfully_scanned_model_candidates"]
