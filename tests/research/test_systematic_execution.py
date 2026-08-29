"""Unit and integration tests for Systematic Execution Engine and Backtest Simulator."""
from __future__ import annotations

import math
import pytest
import numpy as np

from edge.research.systematic_execution import (
    generate_microstructure_signals,
    run_microstructure_backtest,
    ExecutionSignal,
    BacktestTearsheet,
)


def test_generate_microstructure_signals():
    n = 60
    np.random.seed(42)
    # Generate oscillating prices around 500
    t_vals = np.linspace(0, 4 * np.pi, n)
    prices = 500.0 + 10.0 * np.sin(t_vals) + np.random.normal(0, 0.5, n)
    
    signals, nw_res, kalman_res, vwap_results = generate_microstructure_signals(
        prices,
        symbol="SPY",
        gamma_flip_series=np.full(n, 495.0),
        call_wall_series=np.full(n, 515.0),
        put_wall_series=np.full(n, 485.0),
        net_gex_series=np.full(n, 150.0),
        net_chex_series=np.full(n, 5.0),
    )

    assert len(signals) == n
    assert len(nw_res.mean) == n
    assert len(kalman_res.latent_price) == n
    assert len(vwap_results) > 0

    actions = [s.action for s in signals]
    assert any(a in {"ENTER_LONG", "ENTER_SHORT", "NONE"} for a in actions)
    
    first_sig = signals[0]
    assert isinstance(first_sig, ExecutionSignal)
    assert first_sig.symbol == "SPY"
    assert first_sig.regime in {"positive_gamma", "negative_gamma", "neutral_transition"}


def test_run_microstructure_backtest():
    n = 100
    np.random.seed(42)
    t_vals = np.linspace(0, 6 * np.pi, n)
    prices = 500.0 + 15.0 * np.sin(t_vals) + np.random.normal(0, 0.5, n)
    
    tearsheet = run_microstructure_backtest(
        prices,
        symbol="SPY",
        gamma_flip_series=np.full(n, 495.0),
        call_wall_series=np.full(n, 520.0),
        put_wall_series=np.full(n, 480.0),
        net_gex_series=np.full(n, 200.0),
        initial_capital=100_000.0,
        risk_per_trade_pct=0.02,
        slippage_bps=1.0,
    )

    assert isinstance(tearsheet, BacktestTearsheet)
    assert tearsheet.symbol == "SPY"
    assert tearsheet.n_bars == n
    assert tearsheet.initial_capital == 100_000.0
    assert len(tearsheet.equity_curve) == n
    assert len(tearsheet.drawdown_curve) == n
    assert "positive_gamma" in tearsheet.regime_breakdown
    assert "negative_gamma" in tearsheet.regime_breakdown
