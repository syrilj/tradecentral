from __future__ import annotations

import copy
import time

from edge.tools import api_server


def _status_payload(depth: str = "deep") -> dict:
    return {
        "asof": "2026-08-11 20:00:00 UTC",
        "scan_summary": {
            "depth": depth,
            "activity_local_scanned_symbols": 576 if depth == "deep" else 175,
            "activity_market_universe_symbols": 576,
            "activity_live_completed_symbols": 2 if depth == "deep" else 0,
            "activity_live_requested_symbols": 2 if depth == "deep" else 0,
            "directional_scored_symbols": 59 if depth == "deep" else 25,
            "directional_model_universe_symbols": 59,
        },
    }


def test_api_status_scan_path_defers_unrelated_gcp_inventory(monkeypatch):
    seen: dict = {}

    def build(**kwargs):
        seen.update(kwargs)
        return _status_payload("quick")

    monkeypatch.setattr(api_server, "_get_dashboard_data_uncached", build)
    api_server._STATUS_CACHE.clear()
    api_server._STATUS_CACHE_TS.clear()

    payload = api_server.get_dashboard_data(force=True, scan_depth="quick")

    assert payload["scan_summary"]["depth"] == "quick"
    assert seen["include_gcp_resources"] is False
    assert callable(seen["progress"]) is False


def test_health_identifies_the_market_wide_flow_contract():
    payload = api_server._health_payload()

    assert payload["ok"] is True
    assert payload["flow_feed_contract"] == "market-wide-v1"
    assert payload["suggestion_contract"] == "paper-candidate-contract-v9"


def test_contract_identity_must_repeat_and_survive_restart_before_sizing_is_exposed(
    monkeypatch, tmp_path,
):
    state_path = tmp_path / "stability.json"
    monkeypatch.setattr(api_server, "_STABILITY_STATE_PATH", state_path)
    monkeypatch.setattr(api_server, "_STABILITY_STATE_LOADED", True)
    api_server._CONTRACT_STABILITY_STATE.clear()
    api_server._DIRECTION_STABILITY_STATE.clear()
    payload = {
        "rows": [{
            "symbol": "AAA",
            "suggestion": {
                "right": "call",
                "evidence_kind": "directional_context",
                "contract_plan": {
                    "kind": "chain_selected_contract",
                    "right": "call",
                    "occ_symbol": "AAA260918C00105000",
                    "action": "BUY_TO_OPEN",
                    "contract_stage": "entry_candidate",
                    "sizing_eligible": True,
                    "sizing_debit": 2.5,
                    "reference_max_loss": 250,
                    "take_profit_debit": 3.75,
                    "review_exit_debit": 1.25,
                    "rejection_reasons": [],
                },
            },
        }],
    }

    first = api_server._stabilize_contract_plans(copy.deepcopy(payload))
    first_plan = first["rows"][0]["suggestion"]["contract_plan"]
    assert first_plan["stable"] is False
    assert first_plan["action"] == "WAIT_FOR_STABILITY"
    assert first_plan["sizing_debit"] is None

    second = api_server._stabilize_contract_plans(copy.deepcopy(payload))
    second_plan = second["rows"][0]["suggestion"]["contract_plan"]
    assert second_plan["stable"] is False
    assert second_plan["stability_observations"] == 2

    third = api_server._stabilize_contract_plans(copy.deepcopy(payload))
    third_plan = third["rows"][0]["suggestion"]["contract_plan"]
    assert third_plan["stable"] is True
    assert third_plan["action"] == "BUY_TO_OPEN"
    assert third_plan["sizing_debit"] == 2.5
    assert state_path.exists()

    # Simulate a process restart: the persisted observation window is loaded
    # before the next provider refresh, so stability does not reset to one.
    api_server._CONTRACT_STABILITY_STATE.clear()
    api_server._DIRECTION_STABILITY_STATE.clear()
    api_server._STABILITY_STATE_LOADED = False
    after_restart = api_server._stabilize_contract_plans(copy.deepcopy(payload))
    restarted_plan = after_restart["rows"][0]["suggestion"]["contract_plan"]
    assert restarted_plan["stable"] is True
    assert restarted_plan["stability_observations"] == 3


def test_right_flip_resets_contract_stability(monkeypatch, tmp_path):
    monkeypatch.setattr(api_server, "_STABILITY_STATE_PATH", tmp_path / "flip-state.json")
    monkeypatch.setattr(api_server, "_STABILITY_STATE_LOADED", True)
    api_server._CONTRACT_STABILITY_STATE.clear()
    api_server._DIRECTION_STABILITY_STATE.clear()

    def payload(right: str) -> dict:
        return {"rows": [{
            "symbol": "AAA",
            "suggestion": {
                "right": right,
                "evidence_kind": "activity_lean",
                "contract_plan": {
                    "kind": "chain_selected_contract",
                    "right": right,
                    "occ_symbol": f"AAA260918{'C' if right == 'call' else 'P'}00100000",
                    "action": "BUY_TO_OPEN",
                    "sizing_eligible": True,
                    "sizing_debit": 2.0,
                    "rejection_reasons": [],
                },
            },
        }]}

    for _ in range(3):
        stable_call = api_server._stabilize_contract_plans(payload("call"))
    assert stable_call["rows"][0]["suggestion"]["contract_plan"]["stable"] is True

    flipped = api_server._stabilize_contract_plans(payload("put"))
    suggestion = flipped["rows"][0]["suggestion"]
    assert suggestion["direction_churned"] is True
    assert suggestion["direction_observations"] == 1
    assert suggestion["direction_stable"] is False
    assert suggestion["contract_plan"]["stability_observations"] == 1
    assert suggestion["contract_plan"]["stable"] is False
    assert suggestion["contract_plan"]["sizing_eligible"] is False


def test_stable_delayed_contract_becomes_unsized_paper_action(monkeypatch, tmp_path):
    monkeypatch.setattr(api_server, "_STABILITY_STATE_PATH", tmp_path / "paper-action.json")
    monkeypatch.setattr(api_server, "_STABILITY_STATE_LOADED", True)
    api_server._CONTRACT_STABILITY_STATE.clear()
    api_server._DIRECTION_STABILITY_STATE.clear()
    payload = {
        "asof_utc": "2026-08-14T20:30:00+00:00",
        "filters": {"min_volume": 10, "min_open_interest": 100, "max_spread_pct": 0.25},
        "coverage": {},
        "rows": [{
            "symbol": "AAA",
            "live_ready": False,
            "freshness": {"pass": False},
            "suggestion": {
                "right": "call",
                "setup_tier": "paper",
                "evidence_kind": "directional_context",
                "risk_levels_complete": True,
                "contract_plan": {
                    "kind": "chain_selected_contract",
                    "right": "call",
                    "occ_symbol": "AAA260918C00105000",
                    "action": "WAIT_FOR_LIVE_QUOTE",
                    "contract_stage": "chain_matched_delayed_reference",
                    "quote_complete": False,
                    "quote_reference_only": True,
                    "reference_debit": 2.5,
                    "observed_at": "2026-08-14T19:45:00+00:00",
                    "volume": 50,
                    "open_interest": 500,
                    "spread_pct": 0.04,
                    "sizing_eligible": False,
                    "sizing_debit": None,
                    "rejection_reasons": ["quote is delayed reference only"],
                },
            },
        }],
    }

    for _ in range(3):
        result = api_server._stabilize_contract_plans(copy.deepcopy(payload))

    row = result["rows"][0]
    suggestion = row["suggestion"]
    plan = suggestion["contract_plan"]
    assert suggestion["paper_actionable"] is True
    assert suggestion["paper_action"] == "PAPER_BUY_CALL"
    assert suggestion["review_label"] == "PAPER ACTION"
    assert suggestion.get("entry_eligible") is not True
    assert plan["action"] == "PAPER_BUY_TO_OPEN"
    assert plan["contract_stage"] == "paper_action_candidate"
    assert plan["sizing_eligible"] is False
    assert plan["sizing_debit"] is None
    assert row["live_ready"] is False
    assert result["coverage"]["paper_actionable"] == 1
    assert result["coverage"]["live_ready"] == 0

    expired_payload = copy.deepcopy(payload)
    expired_payload["asof_utc"] = "2026-08-15T13:30:00+00:00"
    expired = api_server._stabilize_contract_plans(expired_payload)
    expired_suggestion = expired["rows"][0]["suggestion"]
    assert expired_suggestion["paper_actionable"] is False
    assert "fresh or same-session chain reference" in expired_suggestion["paper_action_blockers"]


def test_scan_job_reports_progress_and_publishes_completed_result(monkeypatch):
    job_id = "job-test"
    now = "2026-08-11T20:00:00+00:00"
    api_server._SCAN_JOBS.clear()
    api_server._SCAN_JOBS[job_id] = {
        "id": job_id,
        "depth": "deep",
        "state": "queued",
        "stage": "queued",
        "progress": 0,
        "message": "queued",
        "started_at": now,
        "updated_at": now,
        "started_monotonic": time.perf_counter(),
        "error": None,
    }
    monkeypatch.setattr(api_server, "_ACTIVE_SCAN_JOB_ID", job_id)

    def build(**kwargs):
        kwargs["progress"]("qlib", 75, "Cross-section ranked.")
        return _status_payload("deep")

    monkeypatch.setattr(api_server, "get_dashboard_data", build)
    api_server._run_scan_job(job_id, "deep")

    payload, status = api_server._scan_status_payload(job_id)
    assert status == 200
    assert payload["job"]["state"] == "completed"
    assert payload["job"]["progress"] == 100
    assert payload["job"]["result"]["data"]["scan_summary"]["depth"] == "deep"
    assert api_server._ACTIVE_SCAN_JOB_ID is None


def test_status_poll_does_not_recompute_or_replace_an_activated_scan(monkeypatch):
    api_server._STATUS_CACHE.clear()
    api_server._STATUS_CACHE_TS.clear()
    api_server._ACTIVE_SCAN_DEPTH = "quick"
    builds: list[str] = []

    def build(**kwargs):
        depth = kwargs.get("scan_depth") or "quick"
        builds.append(depth)
        return _status_payload(depth)

    monkeypatch.setattr(api_server, "_get_dashboard_data_uncached", build)

    deep = api_server.get_dashboard_data(force=True, scan_depth="deep", activate=True)
    assert deep["scan_summary"]["depth"] == "deep"
    assert builds == ["deep"]

    polled = api_server.get_dashboard_data()
    stale = api_server.get_dashboard_data(scan_depth="quick")
    assert polled["scan_summary"]["depth"] == "deep"
    assert stale["scan_summary"]["depth"] == "deep"
    assert builds == ["deep"]


def test_quotes_payload_prefers_live_spot(monkeypatch):
    import pandas as pd

    frame = pd.DataFrame({"close": [98.0, 100.0]}, index=pd.to_datetime(["2026-08-11", "2026-08-12"]))
    monkeypatch.setattr(api_server, "_load_symbol_df", lambda symbol: (frame, "wide"))
    monkeypatch.setattr(api_server, "_frame_asof_date", lambda _frame: "2026-08-12")
    monkeypatch.setattr(
        api_server,
        "_fetch_lse_equity_spot",
        lambda symbol: (101.5, "2026-08-13T14:00:00+00:00"),
    )

    payload = api_server._quotes_payload(["aapl", "AAPL", "bad symbol!!", "MSFT"])
    assert payload["count"] == 2
    assert payload["rows"][0]["symbol"] == "AAPL"
    assert payload["rows"][0]["last"] == 101.5
    assert payload["rows"][0]["quality"] == "live"
    assert payload["rows"][0]["source"] == "lse_equity_candles"


def test_standalone_flow_never_reads_the_legacy_deep_snapshot(monkeypatch):
    api_server._UNUSUAL_FLOW_CACHE.clear()

    seen: dict = {}

    def build(**kwargs):
        seen.update(kwargs)
        return {
            "rows": [],
            "coverage": {"provider_requests": 1, "provider_requests_completed": 1},
        }

    monkeypatch.setattr(api_server, "build_unusual_options_flow", build)

    payload = api_server._unusual_flow_payload_impl(
        limit=80,
        min_premium=25_000.0,
        force=False,
    )

    assert payload["source_snapshot"] == "market_flow"
    assert seen["row_limit"] == 80
    assert "live_target_limit" not in seen


def test_flow_aggregate_carries_latest_tape_underlying_price(monkeypatch):
    api_server._UNUSUAL_FLOW_CACHE.clear()
    monkeypatch.setattr(
        api_server,
        "build_unusual_options_flow",
        lambda **_: {
            "rows": [{"symbol": "MU", "activity_lean": "bullish"}],
            "tape": [
                {"symbol": "MU", "timestamp": "2026-08-13T20:00:00Z", "underlying_price": 270.0,
                 "right": "call", "strike": 275, "expiry": "2026-09-18", "price": 4.1,
                 "premium": 205_000, "contracts": 500},
                {"symbol": "MU", "timestamp": "2026-08-13T20:01:00Z", "underlying_price": 271.25,
                 "right": "call", "strike": 280, "expiry": "2026-09-18", "price": 2.6,
                 "premium": 260_000, "contracts": 1000},
                {"symbol": "MU", "timestamp": "2026-08-13T20:02:00Z", "underlying_price": None,
                 "right": "put", "strike": 265, "expiry": "2026-09-18", "price": 2.2,
                 "premium": 220_000, "contracts": 1000},
                {"symbol": "MU", "timestamp": "2026-08-13T20:03:00Z", "underlying_price": 271.25,
                 "right": "call", "strike": 1000, "expiry": "2026-09-18", "dte": 36,
                 "price": 0.1, "premium": 9_000_000, "contracts": 900_000},
            ],
            "coverage": {},
        },
    )

    payload = api_server._unusual_flow_payload_impl(
        limit=80, min_premium=25_000.0, force=False,
    )

    assert payload["rows"][0]["spot"] == 271.25
    assert payload["rows"][0]["flow_focus"]["call"]["strike"] == 280
    assert payload["rows"][0]["flow_focus"]["call"]["price"] == 2.6
    assert payload["rows"][0]["flow_focus_rejections"]["call"] == [
        "strike is more than 25% from underlying spot",
    ]
    # Contract identity is independent from the print carrying underlying spot.
    assert payload["rows"][0]["flow_focus"]["put"]["strike"] == 265
