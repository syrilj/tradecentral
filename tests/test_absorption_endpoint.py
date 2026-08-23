"""Endpoint tests for /api/absorption and /api/absorption/{SYMBOL}."""
from __future__ import annotations

import dataclasses

import pandas as pd

from edge.daily_plays import absorption as absorption_module
from edge.tools import api_server


def _bars(closes, volumes):
    n = len(closes)
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": closes,
            "volume": volumes,
        },
        index=idx,
    )


def test_scan_payload_uses_loaders_and_caches(monkeypatch):
    calls = {"load": 0}

    def fake_load():
        calls["load"] += 1
        return {"AAA": _bars([100.0] * 60, [1000.0] * 60)}

    monkeypatch.setattr(api_server, "_load_absorption_price_data", fake_load)
    api_server._ABSORPTION_SCAN_CACHE = None
    api_server._ABSORPTION_SCAN_CACHE_TS = 0.0

    first = api_server._absorption_scan_payload()
    second = api_server._absorption_scan_payload()

    assert calls["load"] == 1
    assert first is second
    assert first["decision_authorized"] is False
    assert first["score_kind"] == "ordinal_absorption"
    assert first["universe_size"] == 1
    assert first["evaluated"] == 1


def test_scan_payload_force_bypasses_cache(monkeypatch):
    calls = {"load": 0}

    def fake_load():
        calls["load"] += 1
        return {"AAA": _bars([100.0] * 60, [1000.0] * 60)}

    monkeypatch.setattr(api_server, "_load_absorption_price_data", fake_load)
    api_server._ABSORPTION_SCAN_CACHE = None
    api_server._ABSORPTION_SCAN_CACHE_TS = 0.0

    api_server._absorption_scan_payload()
    api_server._absorption_scan_payload(force=True)

    assert calls["load"] == 2


def test_symbol_payload_falls_back_to_bars_when_tape_is_degenerate(monkeypatch):
    # No LSE credential -> tape returns unavailable -> bars fallback.
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    monkeypatch.setattr(
        api_server,
        "_load_symbol_bars",
        lambda symbol, prefer_intraday=True: _bars([100.0] * 60, [1000.0] * 60),
    )
    payload = api_server._absorption_symbol_payload("SPY")
    assert payload["available"] is True
    assert payload["source"] == "bars"
    assert payload["decision_authorized"] is False
    assert len(payload["series"]) == 60
    assert payload["backtest"] is not None


def test_symbol_payload_missing_data_is_unavailable(monkeypatch):
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    monkeypatch.setattr(api_server, "_load_symbol_bars", lambda *a, **k: None)
    payload = api_server._absorption_symbol_payload("NOPE")
    assert payload["available"] is False
    assert payload["reason"] is not None
    assert payload["series"] == []
    assert payload["backtest"] is None
    # Missing data must be an explicit state (true zeros/nulls), never a
    # fake zero masquerading as "evaluated, found nothing" -- AGENTS.md.
    assert payload["series_total"] == 0
    assert payload["series_start_index"] is None
    assert payload["series_end_index"] is None
    assert payload["series_first_ts"] is None
    assert payload["series_last_ts"] is None
    assert payload["signal_total_count"] == 0
    assert payload["signal_window_count"] == 0
    assert payload["baseline_warming_total_count"] == 0
    assert payload["baseline_warming_window_count"] == 0


def test_symbol_payload_windows_to_most_recent_points_and_reports_totals(monkeypatch):
    # FIX 1: unbounded series (thousands of points) blew past 1MB per
    # response. The endpoint must now cap the series, return the TAIL
    # (most recent points, not the earliest history), and report enough
    # metadata for the client to render "showing last N of M".
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    n = 500
    closes = [100.0 + (i % 7) * 0.1 for i in range(n)]
    volumes = [1000.0] * n
    monkeypatch.setattr(
        api_server,
        "_load_symbol_bars",
        lambda symbol, prefer_intraday=True: _bars(closes, volumes),
    )

    # A limit above n returns everything -- our reference "full" series.
    full = api_server._absorption_symbol_payload(
        "SPY", limit=api_server._ABSORPTION_SERIES_MAX_LIMIT
    )
    assert full["series_total"] == n
    assert len(full["series"]) == n

    # No limit -> the documented default window.
    windowed = api_server._absorption_symbol_payload("SPY")
    default_limit = api_server._ABSORPTION_SERIES_DEFAULT_LIMIT

    assert windowed["series_total"] == n
    assert windowed["series_limit"] == default_limit
    assert len(windowed["series"]) == default_limit

    # The window must be the TAIL of the full series (most recent points),
    # not the head.
    assert windowed["series"] == full["series"][-default_limit:]
    assert windowed["series"] != full["series"][:default_limit]

    assert windowed["series_start_index"] == windowed["series"][0]["index"]
    assert windowed["series_end_index"] == windowed["series"][-1]["index"]

    # first/last ts must describe the FULL evaluated range, not just the
    # window, so the client can show the true evaluated span even though
    # only the tail was returned.
    assert windowed["series_first_ts"] == full["series"][0]["ts"]
    assert windowed["series_last_ts"] == full["series"][-1]["ts"]

    # An explicit `limit` query value is honored and clamped.
    custom = api_server._absorption_symbol_payload("SPY", limit=25)
    assert custom["series_limit"] == 25
    assert len(custom["series"]) == 25
    assert custom["series"] == full["series"][-25:]

    too_big = api_server._absorption_symbol_payload("SPY", limit=999_999)
    assert too_big["series_limit"] == api_server._ABSORPTION_SERIES_MAX_LIMIT

    too_small = api_server._absorption_symbol_payload("SPY", limit=1)
    assert too_small["series_limit"] == api_server._ABSORPTION_SERIES_MIN_LIMIT


def test_symbol_payload_reports_warming_points_separately_from_evaluated(monkeypatch):
    # baseline_warming=True means "not yet evaluable" (fail-closed warm-up),
    # a different state from signal=False ("evaluated, found nothing"). The
    # first observations of any real series are warming; with a long
    # series and the default tail window, those warming points fall
    # outside the window and must still be visible via the total count.
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    n = 500
    closes = [100.0 + (i % 7) * 0.1 for i in range(n)]
    volumes = [1000.0] * n
    monkeypatch.setattr(
        api_server,
        "_load_symbol_bars",
        lambda symbol, prefer_intraday=True: _bars(closes, volumes),
    )

    payload = api_server._absorption_symbol_payload("SPY")

    assert payload["baseline_warming_total_count"] > 0
    assert payload["baseline_warming_window_count"] == 0
    assert payload["baseline_warming_total_count"] >= payload["baseline_warming_window_count"]

    # And every returned series point exposes the field (dropped by the
    # old hand-rolled dict; now delegated to readout_to_dict()).
    assert all("baseline_warming" in point for point in payload["series"])


def test_symbol_payload_signal_outside_window_is_counted_not_dropped(monkeypatch):
    # FIX 1 requirement: signals must not be silently dropped by
    # windowing. A signal outside the returned tail window must still be
    # reflected in the total count, distinguishing "no signals" from
    # "signals outside this window".
    monkeypatch.delenv("LSE_API_KEY", raising=False)
    n = 500
    closes = [100.0 + (i % 7) * 0.1 for i in range(n)]
    volumes = [1000.0] * n
    monkeypatch.setattr(
        api_server,
        "_load_symbol_bars",
        lambda symbol, prefer_intraday=True: _bars(closes, volumes),
    )

    real_detect = absorption_module.detect_absorption_series

    def fake_detect(observations, cfg):
        readouts = list(real_detect(observations, cfg))
        # Force a genuine signal at raw index 5 -- far before the tail
        # window a limit=50 request will return (indices 450-499).
        readouts[5] = dataclasses.replace(
            readouts[5],
            signal=True,
            signal_kind="buy_absorption",
            baseline_warming=False,
        )
        return readouts

    monkeypatch.setattr(absorption_module, "detect_absorption_series", fake_detect)

    payload = api_server._absorption_symbol_payload("SPY", limit=50)

    assert payload["series_total"] == n
    assert len(payload["series"]) == 50
    assert all(point["index"] != 5 for point in payload["series"])
    assert payload["signal_total_count"] >= 1
    assert payload["signal_window_count"] == 0
