"""/api/vol-target-trend endpoint tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from edge.tools import api_server


def _frame(n: int = 500, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    drift = np.concatenate([np.full(n // 2, 0.003), np.full(n - n // 2, -0.002)])
    close = np.exp(np.log(100.0) + np.cumsum(drift + rng.normal(0.0, 0.01, n)))
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": close * 0.998,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(n, 500_000.0),
        },
        index=idx,
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    api_server._VOL_TARGET_CACHE.clear()
    yield
    api_server._VOL_TARGET_CACHE.clear()


def test_vol_target_payload_structure(monkeypatch):
    frame = _frame()
    monkeypatch.setattr(api_server, "_load_symbol_bars", lambda symbol, prefer_intraday=False: frame)
    payload = api_server._vol_target_trend_payload(
        "TEST",
        "1y",
        target_vol=0.15,
        lev_cap=3.0,
        fast_days=5.0,
        slow_days=20.0,
        vol_days=20.0,
        capital=100_000.0,
        intraday=False,
    )
    assert payload["available"] is True
    assert payload["symbol"] == "TEST"
    assert payload["window"] == "1y"
    assert payload["n_bars"] > 0
    assert payload["n_bars_full"] == len(frame)
    assert "series" in payload and len(payload["series"]) == payload["n_bars"]
    assert "trades" in payload
    assert "stats" in payload and payload["stats"] is not None
    assert "now" in payload and payload["now"] is not None
    assert "plots" in payload and "annualised vol" in payload["plots"]

    first_pt = payload["series"][0]
    assert "d" in first_pt
    assert "close" in first_pt
    assert "ema_f" in first_pt
    assert "ema_s" in first_pt
    assert "ann_vol" in first_pt
    assert "leverage" in first_pt
    assert "pos" in first_pt


def test_vol_target_payload_caching(monkeypatch):
    frame = _frame()
    calls = {"n": 0}

    def fake_loader(symbol, *, prefer_intraday=True):
        calls["n"] += 1
        return frame

    monkeypatch.setattr(api_server, "_load_symbol_bars", fake_loader)

    p1 = api_server._vol_target_trend_payload(
        "TEST", "1y", target_vol=0.15, lev_cap=3.0, fast_days=5.0, slow_days=20.0, vol_days=20.0, capital=100_000.0, intraday=False
    )
    assert calls["n"] == 1

    p2 = api_server._vol_target_trend_payload(
        "TEST", "1y", target_vol=0.15, lev_cap=3.0, fast_days=5.0, slow_days=20.0, vol_days=20.0, capital=100_000.0, intraday=False
    )
    # Cached: loader not called again
    assert calls["n"] == 1
    assert p1 == p2

    # Different parameter recomputes
    p3 = api_server._vol_target_trend_payload(
        "TEST", "1y", target_vol=0.20, lev_cap=3.0, fast_days=5.0, slow_days=20.0, vol_days=20.0, capital=100_000.0, intraday=False
    )
    assert calls["n"] == 2
    assert p3["params"]["target_vol"] == 0.20


def test_vol_target_payload_empty_bars(monkeypatch):
    monkeypatch.setattr(api_server, "_load_symbol_bars", lambda symbol, prefer_intraday=False: pd.DataFrame())
    payload = api_server._vol_target_trend_payload(
        "TEST", "1y", target_vol=0.15, lev_cap=3.0, fast_days=5.0, slow_days=20.0, vol_days=20.0, capital=100_000.0, intraday=False
    )
    assert payload["available"] is False
    assert "no bars found" in payload["reason"]


def test_vol_target_signals_payload(monkeypatch):
    frame = _frame()
    monkeypatch.setattr(api_server, "_load_symbol_bars", lambda symbol, prefer_intraday=False: frame)
    payload = api_server._vol_target_signals_payload(
        ["AAPL", "MSFT", "INVALID"],
        target_vol=0.15,
        lev_cap=3.0,
        fast_days=5.0,
        slow_days=20.0,
        vol_days=20.0,
        capital=100_000.0,
        intraday=False,
    )
    assert "signals" in payload
    assert payload["count"] == 3
    signals = payload["signals"]
    assert len(signals) == 3
    sig_aapl = next(s for s in signals if s["symbol"] == "AAPL")
    assert sig_aapl["available"] is True
    assert sig_aapl["signal"] in {"BUY", "SELL"}
    assert "leverage" in sig_aapl
    assert "target_qty" in sig_aapl
    assert "target_notional" in sig_aapl

