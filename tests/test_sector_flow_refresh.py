from __future__ import annotations

import time

from edge.tools import api_server


def _reset_sector_state() -> None:
    api_server._SECTOR_FLOW_CACHE.clear()
    api_server._STATUS_CACHE.clear()
    api_server._STATUS_CACHE_TS.clear()
    api_server._ACTIVE_SCAN_DEPTH = "quick"


def test_sector_flow_reruns_on_force_and_patches_status(monkeypatch):
    calls: list[str] = []

    def fake_scan() -> dict:
        calls.append("scan")
        return {
            "asof_bar": "2026-08-14",
            "source": "yfinance",
            "sectors_ranked": [{"etf": "XLE", "flow_score": 0.03}],
        }

    monkeypatch.setattr(api_server, "fetch_sector_flow_signals", fake_scan)
    _reset_sector_state()
    api_server._STATUS_CACHE["quick"] = {
        "sector_flow": {"asof_bar": "2026-07-10", "source": "local"},
    }

    first = api_server.get_sector_flow(force=True)
    assert first["asof_bar"] == "2026-08-14"
    assert first["source"] == "yfinance"
    assert api_server._STATUS_CACHE["quick"]["sector_flow"]["asof_bar"] == "2026-08-14"
    assert calls == ["scan"]

    cached = api_server.get_sector_flow(force=False)
    assert cached["asof_bar"] == "2026-08-14"
    assert calls == ["scan"]

    api_server._SECTOR_FLOW_CACHE["ts"] = time.time() - api_server._SECTOR_FLOW_TTL_S - 1
    again = api_server.get_sector_flow(force=False)
    assert again["asof_bar"] == "2026-08-14"
    assert calls == ["scan", "scan"]


def test_cached_status_poll_kicks_expired_sector_refresh(monkeypatch):
    started = time.time()

    def fake_scan() -> dict:
        return {
            "asof_bar": "2026-08-14",
            "source": "yfinance",
            "sectors_ranked": [{"etf": "XLI", "flow_score": 0.01}],
        }

    monkeypatch.setattr(api_server, "fetch_sector_flow_signals", fake_scan)
    _reset_sector_state()
    api_server._STATUS_CACHE["quick"] = {
        "asof": "2026-08-11 20:00:00 UTC",
        "sector_flow": {"asof_bar": "2026-07-10", "source": "local"},
        "scan_summary": {"depth": "quick"},
    }
    api_server._STATUS_CACHE_TS["quick"] = time.time()

    polled = api_server.get_dashboard_data()
    assert polled["scan_summary"]["depth"] == "quick"

    deadline = started + 2.0
    updated = (polled.get("sector_flow") or {})
    while time.time() < deadline:
        updated = (api_server._STATUS_CACHE.get("quick") or {}).get("sector_flow") or {}
        if updated.get("asof_bar") == "2026-08-14":
            break
        time.sleep(0.05)
    assert updated.get("asof_bar") == "2026-08-14"
    assert updated.get("source") == "yfinance"


def test_status_poll_without_sector_does_not_background_scan(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        api_server,
        "fetch_sector_flow_signals",
        lambda: calls.append("scan") or {"asof_bar": "2026-08-14"},
    )
    _reset_sector_state()
    api_server._STATUS_CACHE["quick"] = {"scan_summary": {"depth": "quick"}}
    api_server._STATUS_CACHE_TS["quick"] = time.time()

    api_server.get_dashboard_data()
    time.sleep(0.1)
    assert calls == []
