"""/api/kalman-trend contract.

The filter is recursive, so the endpoint's one non-obvious guarantee is that
it always runs over FULL history and slices only the display: restarting at
the window boundary would paint the filter's own P=I transient at the left
edge of every chart and fabricate a trade there.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.tools import api_server


def _frame(n: int = 800, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    drift = np.concatenate([np.full(n // 2, 0.004), np.full(n - n // 2, -0.003)])
    close = np.exp(np.log(60.0) + np.cumsum(drift + rng.normal(0.0, 0.009, n)))
    idx = pd.date_range("2021-01-04", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": close * 0.997,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    api_server._KALMAN_CACHE.clear()
    yield
    api_server._KALMAN_CACHE.clear()


def _payload(monkeypatch, frame, **kw):
    calls = {"n": 0, "intraday": None}

    def fake_loader(symbol, *, prefer_intraday=True):
        calls["n"] += 1
        calls["intraday"] = prefer_intraday
        return frame

    monkeypatch.setattr(api_server, "_load_symbol_bars", fake_loader)
    opts = dict(
        q=1e-6, entry_z=1.0, exit_z=0.0, noise_days=20, allow_short=True, intraday=False
    )
    opts.update(kw)
    window = opts.pop("window", "1y")
    return api_server._kalman_trend_payload("TEST", window, **opts), calls


def test_payload_reports_full_history_and_a_sliced_display(monkeypatch):
    frame = _frame()
    payload, _ = _payload(monkeypatch, frame)
    assert payload["available"] is True
    assert payload["n_bars_full"] == len(frame)
    assert 0 < payload["n_bars"] < payload["n_bars_full"]
    assert payload["series"][0]["d"] == payload["first_date"]
    assert payload["params"]["noise_bars"] == 20
    assert payload["params"]["bars_per_day"] == 1.0
    assert payload["params"]["observation_variance"] == 1.0


def test_window_change_does_not_alter_the_filtered_values(monkeypatch):
    frame = _frame()
    long_win, _ = _payload(monkeypatch, frame, window="max")
    short_win, _ = _payload(monkeypatch, frame, window="1y")
    by_date = {p["d"]: p for p in long_win["series"]}
    for point in short_win["series"]:
        assert by_date[point["d"]]["slope"] == point["slope"]
        assert by_date[point["d"]]["score"] == point["score"]
    # Same trades either way -- the window is a viewport, not a backtest span.
    assert short_win["n_trades"] == long_win["n_trades"]


def test_trades_are_priced_at_the_fill_bar_open_never_the_signal_close(monkeypatch):
    frame = _frame()
    payload, _ = _payload(monkeypatch, frame, window="max")
    opens = frame["open"]
    assert payload["trades"]
    for trade in payload["trades"]:
        assert trade["entry_px"] == pytest.approx(float(opens.loc[trade["entry_d"]]), rel=1e-6)
        assert trade["exit_px"] == pytest.approx(float(opens.loc[trade["exit_d"]]), rel=1e-6)
        raw = trade["exit_px"] / trade["entry_px"] - 1.0
        expected = raw if trade["dir"] == "long" else -raw
        assert trade["ret_pct"] == pytest.approx(expected * 100.0, abs=0.01)


def test_long_only_request_never_returns_a_short(monkeypatch):
    payload, _ = _payload(monkeypatch, _frame(), window="max", allow_short=False)
    assert payload["stats"]["n_short"] == 0
    assert all(t["dir"] == "long" for t in payload["trades"])


def test_now_block_reports_the_rule_position_and_flags_a_forced_exit(monkeypatch):
    payload, _ = _payload(monkeypatch, _frame(), window="max")
    now = payload["now"]
    assert now["position"] in {"long", "short", "flat"}
    if now["forced_exit"]:
        # The exit rule never fired; the trade list shows it closed at the
        # last bar, so the readout must not claim the desk is flat.
        assert now["position"] == payload["trades"][0]["dir"]


def test_payload_is_never_trade_authorized(monkeypatch):
    payload, _ = _payload(monkeypatch, _frame())
    assert payload["decision_authorized"] is False
    assert "no costs" in payload["caveat"]


def test_short_history_degrades_with_a_reason_not_an_empty_chart(monkeypatch):
    payload, _ = _payload(monkeypatch, _frame(n=30))
    assert payload["available"] is False
    assert "usable bars" in payload["reason"]
    assert payload["series"] == []


def test_missing_symbol_reports_the_reason(monkeypatch):
    payload, _ = _payload(monkeypatch, pd.DataFrame())
    assert payload["available"] is False
    assert "no bars found" in payload["reason"]


def test_results_are_cached_per_parameter_set(monkeypatch):
    frame = _frame()
    first, calls = _payload(monkeypatch, frame)

    def fake_loader(symbol, *, prefer_intraday=True):
        calls["n"] += 1
        return frame

    monkeypatch.setattr(api_server, "_load_symbol_bars", fake_loader)
    again = api_server._kalman_trend_payload(
        "TEST", "1y", q=1e-6, entry_z=1.0, exit_z=0.0, noise_days=20, allow_short=True,
        intraday=False,
    )
    assert again is first
    assert calls["n"] == 1
    # A different threshold is a different run, not a cache hit.
    other = api_server._kalman_trend_payload(
        "TEST", "1y", q=1e-6, entry_z=2.0, exit_z=0.0, noise_days=20, allow_short=True,
        intraday=False,
    )
    assert other is not first
    assert calls["n"] == 2


def test_intraday_flag_selects_the_hourly_tier(monkeypatch):
    _, calls = _payload(monkeypatch, _frame(), intraday=True)
    assert calls["intraday"] is True


def test_safe_float_clamps_and_rejects_non_finite():
    assert api_server._safe_float("2.5", 1.0, lo=0.0, hi=10.0) == 2.5
    assert api_server._safe_float("99", 1.0, lo=0.0, hi=10.0) == 10.0
    assert api_server._safe_float("nan", 1.0, lo=0.0, hi=10.0) == 1.0
    assert api_server._safe_float("inf", 1.0) == 1.0
    assert api_server._safe_float("abc", 0.5) == 0.5
