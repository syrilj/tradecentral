from __future__ import annotations

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
