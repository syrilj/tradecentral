from __future__ import annotations

import pandas as pd

from edge.tools import api_server


def _prices() -> pd.DataFrame:
    index = pd.bdate_range("2026-01-02", periods=25)
    close = pd.Series(range(100, 125), index=index, dtype=float)
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.5,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000_000,
        },
        index=index,
    )


def test_pandas_helpers_load_the_lazy_dependency_before_using_it():
    prices = _prices()

    assert api_server._ytd_chg_pct(prices["close"]) is not None

    atr, atr_pct, adv = api_server._atr_adv(prices)
    assert atr is not None
    assert atr_pct is not None
    assert adv is not None

    factors = api_server._compute_factors(prices)
    assert factors["adv20_usd"] is not None
    assert factors["liq"] is not None


def test_compare_payload_uses_the_lazy_pandas_dependency(monkeypatch):
    prices = _prices()
    monkeypatch.setattr(api_server, "_load_symbol_df", lambda _symbol: (prices, "core"))

    payload, status = api_server._compare_payload(["AAA", "BBB"], "1m")

    assert status == 200
    assert set(payload["series"]) == {"AAA", "BBB"}
    assert payload["generated_at"]
    assert payload["stats"]["AAA"]["asof"] == prices.index[-1].date().isoformat()
    assert payload["stats"]["AAA"]["change_basis"] == "last_two_observed_closes"


def test_compare_change_does_not_use_forward_filled_overlap(monkeypatch):
    early = _prices().iloc[:20].copy()
    late = _prices().copy()
    expected = ((early["close"].iloc[-1] / early["close"].iloc[-2]) - 1.0) * 100.0

    monkeypatch.setattr(
        api_server,
        "_load_symbol_df",
        lambda symbol: (early if symbol == "AAA" else late, "core"),
    )

    payload, status = api_server._compare_payload(["AAA", "BBB"], "1m")

    assert status == 200
    assert payload["stats"]["AAA"]["chg_1d_pct"] == round(expected, 4)
    assert payload["stats"]["AAA"]["asof"] == early.index[-1].date().isoformat()
    assert payload["stats"]["BBB"]["asof"] == late.index[-1].date().isoformat()


def test_stale_shell_benchmark_prefers_newer_bounded_refresh(monkeypatch):
    local = _prices().copy()
    live = _prices().copy()
    live.index = pd.bdate_range("2026-07-08", periods=len(live))
    live["close"] = live["close"] + 50
    api_server._COMPARE_REFRESH_CACHE.clear()

    monkeypatch.setattr(api_server, "_load_symbol_df", lambda _symbol: (local, "core"))
    monkeypatch.setattr(api_server, "_fetch_yfinance_ohlcv", lambda _symbol: live)
    monkeypatch.setattr(
        api_server,
        "_frame_age_days",
        lambda frame, now=None: 10 if frame is local else 0,
    )

    payload, status = api_server._compare_payload(["SPY"], "1m")

    assert status == 200
    assert payload["stats"]["SPY"]["source"] == "yfinance_refresh"
    assert payload["stats"]["SPY"]["quality"] == "current"
    assert payload["stats"]["SPY"]["asof"] == live.index[-1].date().isoformat()
    assert payload["stats"]["SPY"]["last_price"] == live["close"].iloc[-1]
    api_server._COMPARE_REFRESH_CACHE.clear()
