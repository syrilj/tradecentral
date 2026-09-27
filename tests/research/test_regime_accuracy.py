"""Unit and property tests for live-trading accuracy improvements to the regime engine."""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

from edge.research.kalman_trend import kalman_trend
from edge.research.regimes import compute_cusum_transition_risk
from edge.research.regime_engine import (
    MarketStructure,
    PrimaryRegime,
    VolatilityState,
    compute_calibrated_confidence,
    reconcile_market_regime,
)


def _make_trending_bars(n: int = 150, drift: float = 0.005, vol: float = 0.015, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    shocks = rng.normal(0.0, vol, size=n)
    log_p = np.log(100.0) + np.cumsum(np.full(n, drift) + shocks)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.Series(np.exp(log_p), index=dates, name="close")


def test_adaptive_kalman_scaling_high_vol():
    """Verify adaptive Kalman scaling increases q and reduces lag for high-volatility series."""
    # Low-vol baseline (annualized vol ~ 12%)
    low_vol_p = _make_trending_bars(n=200, drift=0.001, vol=0.0075, seed=1)
    res_low_def = kalman_trend(low_vol_p, adaptive_vol_scaling=False)
    res_low_adp = kalman_trend(low_vol_p, adaptive_vol_scaling=True)

    # For low vol, q_effective should remain at base q (1e-6)
    assert np.all(res_low_adp.q_effective <= 1.5e-6)

    # High-vol series (annualized vol ~ 90%)
    high_vol_p = _make_trending_bars(n=200, drift=0.003, vol=0.055, seed=2)
    res_high_adp = kalman_trend(high_vol_p, adaptive_vol_scaling=True)

    # For high vol, q_effective should scale up significantly to eliminate lag
    assert np.mean(res_high_adp.q_effective) > 5e-6
    assert res_high_adp.extension_zscore is not None
    assert len(res_high_adp.extension_zscore) == 200


def test_directional_cusum_hazard_separation():
    """Verify positive and negative innovations are decoupled into upside_expansion and downside_hazard."""
    # Sudden +15% upward surge (breakout)
    rets_up = pd.Series([0.001] * 30 + [0.15, 0.05, 0.04])
    c_up = compute_cusum_transition_risk(rets_up)

    assert c_up.upside_expansion is not None
    assert c_up.downside_hazard is not None
    assert c_up.upside_expansion.iloc[-1] > 0.50
    assert c_up.downside_hazard.iloc[-1] < 0.20

    # Sudden -15% downward collapse (liquidation hazard)
    rets_down = pd.Series([0.001] * 30 + [-0.15, -0.05, -0.04])
    c_down = compute_cusum_transition_risk(rets_down)

    assert c_down.upside_expansion.iloc[-1] < 0.20
    assert c_down.downside_hazard.iloc[-1] > 0.50


def test_confidence_extension_penalty():
    """Verify confidence drops when price is vertically overextended above trend."""
    # Normal distance (|z| <= 2.0)
    c_normal = compute_calibrated_confidence(
        q_data=1.0,
        a_models=0.9,
        d_boundary=1.0,
        s_persistence=0.8,
        t_risk=0.1,
        z_extension=1.0,
    )
    # Severe overextension (z = 4.0)
    c_extended = compute_calibrated_confidence(
        q_data=1.0,
        a_models=0.9,
        d_boundary=1.0,
        s_persistence=0.8,
        t_risk=0.1,
        z_extension=4.0,
    )

    assert c_normal > 0.60
    assert c_extended < c_normal * 0.55  # Overextension penalty cuts confidence by ~50%


def test_bull_market_pullback_not_bear_trend():
    """Verify negative velocity above 50-day SMA is classified as MEAN_REVERTING rather than BEARISH_TREND."""
    regime = reconcile_market_regime(
        kalman_z=-1.0,
        trend_state="BEARISH_TREND",
        vol_percentile=0.50,
        vol_state=VolatilityState.NORMAL_MEDIUM,
        market_structure=MarketStructure.TRENDING,
        variance_ratio=1.20,
        ou_half_life=25.0,
        flow_mad_z=-0.2,
        t_risk=0.1,
        delta_flip=0.05,
        agreement_ratio=0.8,
        has_model_conflict=False,
        is_measurable=True,
        dist_sma50=0.08,  # Price is 8% above 50 SMA (macro uptrend)
    )

    assert regime == PrimaryRegime.MEAN_REVERTING


def test_capitulation_washout_protection():
    """Verify extreme downside extension with hazard forces UNCERTAIN_TRANSITIONAL to prevent shorting bottoms."""
    regime = reconcile_market_regime(
        kalman_z=-2.0,
        trend_state="BEARISH_ACCELERATING",
        vol_percentile=0.90,
        vol_state=VolatilityState.VOLATILITY_SHOCK,
        market_structure=MarketStructure.TRENDING,
        variance_ratio=1.40,
        ou_half_life=30.0,
        flow_mad_z=-2.5,
        t_risk=0.85,
        delta_flip=-0.05,
        agreement_ratio=0.8,
        has_model_conflict=False,
        is_measurable=True,
        downside_hazard=0.85,
        z_extension=-3.5,  # Capitulation washout
    )

    assert regime == PrimaryRegime.UNCERTAIN_TRANSITIONAL


def test_directional_vol_shock_decoupling():
    """Verify that a positive return shock boosts upside_expansion, NOT downside_hazard."""
    rets_bullish_shock = pd.Series([0.001] * 20 + [0.25])
    vol_shock_mask = pd.Series([False] * 20 + [True])
    c_res = compute_cusum_transition_risk(rets_bullish_shock, vol_shock_mask=vol_shock_mask)

    assert c_res.upside_expansion.iloc[-1] >= 0.85
    assert c_res.downside_hazard.iloc[-1] < 0.20


def test_breakout_requires_positive_velocity():
    """Verify that negative velocity with elevated vol is BEARISH_TREND, not VOL_EXPANSION_BREAKOUT."""
    regime = reconcile_market_regime(
        kalman_z=-1.5,  # Crashing downwards
        trend_state="BEARISH_ACCELERATING",
        vol_percentile=0.95,
        vol_state=VolatilityState.VOLATILITY_SHOCK,
        market_structure=MarketStructure.TRENDING,
        variance_ratio=1.40,
        ou_half_life=30.0,
        flow_mad_z=-1.8,
        t_risk=0.2,
        delta_flip=-0.05,
        agreement_ratio=0.8,
        has_model_conflict=False,
        is_measurable=True,
    )
    assert regime == PrimaryRegime.BEARISH_TREND


def test_spy_out_of_sample_institutional_metrics():
    """Verify that SPY backtest produces low drawdown and strong Sharpe out-of-sample."""
    from edge.tools.backtest_regimes import load_symbol_prices, run_regime_backtest
    df = load_symbol_prices("SPY")
    assert df is not None
    res = run_regime_backtest("SPY", df)
    oos = res["walk_forward_cross_validation"]["out_of_sample"]
    assert oos["max_drawdown_pct"] > -20.0  # MaxDD strictly better than -20%
    assert oos["sharpe"] >= 0.50  # Out-of-sample Sharpe >= 0.50