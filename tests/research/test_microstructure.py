"""
Unit tests for Workstream 3: Microstructure Features & Feature Ablation Suite.
"""

from __future__ import annotations

import pytest
import pandas as pd
import numpy as np

try:
    from edge.research.microstructure import (
        compute_signed_trade_imbalance,
        compute_quote_imbalance,
        compute_relative_spread,
        compute_relative_volume,
        compute_short_term_price_impact,
        compute_liquidity_shock,
    )
    from edge.research.ablation import run_ablation_suite, evaluate_single_feature
except ImportError:
    from research.microstructure import (
        compute_signed_trade_imbalance,
        compute_quote_imbalance,
        compute_relative_spread,
        compute_relative_volume,
        compute_short_term_price_impact,
        compute_liquidity_shock,
    )
    from research.ablation import run_ablation_suite, evaluate_single_feature


def test_signed_trade_imbalance():
    buy_v = np.array([100.0, 50.0, 0.0])
    sell_v = np.array([0.0, 50.0, 100.0])

    ti = compute_signed_trade_imbalance(buy_v, sell_v)
    assert ti[0] == pytest.approx(1.0, abs=1e-4)   # All buy
    assert ti[1] == pytest.approx(0.0, abs=1e-4)   # Balanced
    assert ti[2] == pytest.approx(-1.0, abs=1e-4)  # All sell


def test_quote_imbalance():
    bid_s = np.array([500.0, 100.0])
    ask_s = np.array([100.0, 500.0])

    qi = compute_quote_imbalance(bid_s, ask_s)
    assert qi[0] > 0.6  # Bid-heavy
    assert qi[1] < -0.6 # Ask-heavy


def test_relative_spread():
    bids = np.array([99.0, 199.0])
    asks = np.array([101.0, 201.0])

    rel_spread = compute_relative_spread(bids, asks)
    # Mid = 100.0, Spread = 2.0 -> Rel Spread = 0.02 (200 bps)
    assert rel_spread[0] == pytest.approx(0.02, abs=1e-4)
    # Mid = 200.0, Spread = 2.0 -> Rel Spread = 0.01 (100 bps)
    assert rel_spread[1] == pytest.approx(0.01, abs=1e-4)


def test_relative_volume():
    vol = pd.Series([100.0] * 20 + [500.0])  # Normal volume 100, spikes to 500
    rvol = compute_relative_volume(vol, window=20)
    assert rvol.iloc[-1] == pytest.approx(5.0, abs=1e-2)  # 5x relative volume


def test_short_term_price_impact():
    flow = np.array([1.0, -1.0, 0.0, 0.0, 0.0, 0.0])
    close = np.array([100.0, 100.0, 105.0, 95.0, 100.0, 100.0])

    impact = compute_short_term_price_impact(flow, close, horizon=2)
    # At t=0: flow +1.0, log(P_2 / P_0) = log(105/100) > 0 -> positive impact
    assert impact[0] > 0
    # At t=1: flow -1.0, log(P_3 / P_1) = log(95/100) < 0 -> positive signed impact
    assert impact[1] > 0


def test_liquidity_shock():
    spread = pd.Series([0.01] * 20 + [0.05])  # Spread widens 5x
    volume = pd.Series([1000.0] * 20 + [200.0]) # Volume collapses 5x

    shock = compute_liquidity_shock(spread, volume, window=20)
    assert shock.iloc[-1] > 4.0  # Large liquidity shock indicator


def test_ablation_suite_execution():
    dates = pd.bdate_range("2024-01-01", periods=500)
    syms = [f"S{i}" for i in range(10)]
    rng = np.random.default_rng(42)

    # Predictive feature (strongly correlated with forward return)
    f_good = pd.DataFrame(rng.normal(0, 1, (500, 10)), index=dates, columns=syms)
    rets = f_good * 0.10 + pd.DataFrame(rng.normal(0, 0.01, (500, 10)), index=dates, columns=syms)

    # Pure noise feature
    f_noise = pd.DataFrame(rng.normal(0, 1, (500, 10)), index=dates, columns=syms)

    features = {"trade_imbalance": f_good, "noise_feature": f_noise}
    results = run_ablation_suite(features, rets)

    assert "trade_imbalance" in results
    assert "noise_feature" in results

    assert results["trade_imbalance"].decision == "APPROVED"
    assert results["noise_feature"].decision == "REJECTED"
