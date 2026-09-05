from __future__ import annotations

import pandas as pd
import pytest

from edge.tools import api_server


def _sample_ohlcv() -> pd.DataFrame:
    index = pd.bdate_range("2025-01-02", periods=250)
    close = pd.Series(range(50, 300), index=index, dtype=float)
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.5,
            "low": close - 1.0,
            "close": close,
            "volume": 500_000.0,
        },
        index=index,
    )


def test_load_symbol_bars_falls_back_to_load_symbol_df(monkeypatch):
    sample = _sample_ohlcv()

    # When not found in local parquet directories, fallback to _load_symbol_df
    monkeypatch.setattr(api_server, "_load_symbol_df", lambda sym: (sample.copy(), "live"))

    df = api_server._load_symbol_bars("ASTS", prefer_intraday=False)
    assert df is not None
    assert not df.empty
    assert "close" in df.columns
    assert len(df) >= 250


def test_microstructure_endpoints_succeed_for_fallback_symbol(monkeypatch):
    sample = _sample_ohlcv()
    monkeypatch.setattr(api_server, "_load_symbol_df", lambda sym: (sample.copy(), "live"))

    # 1. State estimation
    payload, status = api_server._state_estimation_payload("ASTS", {"window": ["1y"]})
    assert status == 200
    assert payload["symbol"] == "ASTS"
    assert len(payload["points"]) > 0

    # 2. Anchored VWAP
    payload, status = api_server._anchored_vwap_payload("ASTS", {"window": ["1y"]})
    assert status == 200
    assert payload["symbol"] == "ASTS"
    assert len(payload["anchors"]) > 0

    # 3. Systematic Signals
    payload, status = api_server._systematic_signals_payload("ASTS", {"window": ["1y"]})
    assert status == 200
    assert payload["symbol"] == "ASTS"
    assert len(payload["signals"]) > 0

    # 4. Systematic Backtest
    payload, status = api_server._systematic_backtest_payload("ASTS", {"window": ["1y"]})
    assert status == 200
    assert payload["symbol"] == "ASTS"
    assert "total_trades" in payload
