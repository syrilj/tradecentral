"""tests/test_drift_backtest.py — Unit and integration tests for Drift Tab Backtest Engine."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from edge.tools.backtest_drift_tab import (
    evaluate_snapshot_signals,
    evaluate_systematic_execution,
    load_symbol_daily_bars,
    run_drift_tab_backtests,
)


def test_load_symbol_daily_bars():
    for sym in ["CRDO", "TSLA", "SPY", "ASTS"]:
        df = load_symbol_daily_bars(sym)
        assert df is not None, f"Failed to load daily bars for {sym}"
        assert len(df) > 100
        assert "close" in df.columns
        assert isinstance(df.index, pd.DatetimeIndex)


def test_evaluate_systematic_execution():
    df = load_symbol_daily_bars("SPY")
    assert df is not None
    tearsheet = evaluate_systematic_execution("SPY", df, window="1y")

    assert tearsheet["symbol"] == "SPY"
    assert tearsheet["n_bars"] > 0
    assert "total_return_pct" in tearsheet
    assert "sharpe_ratio" in tearsheet
    assert "win_rate" in tearsheet
    assert "max_drawdown_pct" in tearsheet
    assert isinstance(tearsheet["equity_curve"], list)
    assert len(tearsheet["equity_curve"]) == tearsheet["n_bars"]


def test_evaluate_snapshot_signals():
    df = load_symbol_daily_bars("SPY")
    assert df is not None
    res = evaluate_snapshot_signals("SPY", df)

    assert res["symbol"] == "SPY"
    assert res["snapshot_count"] > 0
    assert len(res["snapshots"]) == res["snapshot_count"]
    first = res["snapshots"][0]
    assert "spot" in first
    assert "net_charm_flow" in first
    assert "primary_strategy" in first


def test_run_drift_tab_backtests_smoke(tmp_path):
    out = run_drift_tab_backtests(["SPY"], out_dir=tmp_path, window="1y")
    assert "SPY" in out["tier1_snapshots"]
    assert "SPY" in out["tier2_systematic"]
    summary_file = tmp_path / "drift_tab_backtest_summary.json"
    assert summary_file.exists()
