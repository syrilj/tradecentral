"""Comprehensive unit, mathematical invariant, and point-in-time causality tests for Layer 1 Features.

Covers:
- Strictly causal log returns r_t and realized volatilities (Close-Close, Parkinson, Garman-Klass).
- True Range (TR) and Wilder's Average True Range (ATR / nATR).
- West's incremental weighted session VWAP, variance, and dispersion bands.
- Slot-relative volume baseline with causal shift(1) exclusion.
- Complete 1st, 2nd, and 3rd order Black-Scholes Greeks and dollar GEX/VEX/CHEX profiles.
- Signed volume flow proxy (CLV * V) and robust Median/MAD z-scores.
- Executable point-in-time perturbation tests (assert_causal_leak_resistant).
- Numerical stability, zero-variance, and boundary guardrails.
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

from edge.research.regime_features import (
    OptionGreeks,
    RegimeFeatureConfig,
    assert_causal_leak_resistant,
    build_layer1_regime_features,
    calculate_option_greeks,
    compute_dollar_gex_profile,
    compute_log_returns,
    compute_realized_volatilities,
    compute_session_vwap_west,
    compute_signed_flow_proxy,
    compute_slot_relative_volume,
    compute_true_range,
    compute_wilders_atr,
)


# ---------------------------------------------------------------------------
# Test Fixtures & Synthetic Data Generators
# ---------------------------------------------------------------------------


def _synthetic_daily_bars(n: int = 100, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-02", periods=n)
    log_ret = rng.normal(0.0005, 0.015, n)
    close = 100.0 * np.exp(np.cumsum(log_ret))
    high = close * (1.0 + rng.uniform(0.002, 0.015, n))
    low = close * (1.0 - rng.uniform(0.002, 0.015, n))
    open_p = low + rng.uniform(0.1, 0.9, n) * (high - low)
    volume = rng.integers(10_000, 500_000, n).astype(float)
    return pd.DataFrame(
        {"open": open_p, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def _synthetic_intraday_bars(sessions: int = 5, bars_per_sess: int = 7, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    records = []
    base_price = 500.0

    for s in range(sessions):
        date_str = f"2024-01-{s + 2:02d}"
        cur_p = base_price
        for b in range(bars_per_sess):
            hour = 9 + b
            dt = pd.Timestamp(f"{date_str} {hour:02d}:30:00")
            ret = rng.normal(0.0, 0.003)
            close = cur_p * math.exp(ret)
            high = max(cur_p, close) * (1.0 + rng.uniform(0.0005, 0.004))
            low = min(cur_p, close) * (1.0 - rng.uniform(0.0005, 0.004))
            open_p = cur_p
            cur_p = close
            vol = float(rng.integers(5_000, 50_000))
            records.append({
                "datetime": dt,
                "open": open_p,
                "high": high,
                "low": low,
                "close": close,
                "volume": vol,
            })
        base_price = cur_p

    df = pd.DataFrame(records).set_index("datetime")
    return df


# ---------------------------------------------------------------------------
# 1. Causal Log Returns & Multi-Estimator Volatilities
# ---------------------------------------------------------------------------


def test_log_returns_causality_and_properties():
    prices = pd.Series([100.0, 105.0, 102.0, 110.0])
    r = compute_log_returns(prices)
    assert np.isnan(r.iloc[0])
    assert r.iloc[1] == pytest.approx(math.log(105.0 / 100.0), abs=1e-9)
    assert r.iloc[2] == pytest.approx(math.log(102.0 / 105.0), abs=1e-9)
    assert r.iloc[3] == pytest.approx(math.log(110.0 / 102.0), abs=1e-9)


def test_realized_volatilities_estimators_and_warmup():
    bars = _synthetic_daily_bars(n=60)
    vols = compute_realized_volatilities(bars, window=20, annualization=252.0)

    # Warmup check: Close-to-Close has 20 NaNs (requires 20 returns = 21 price bars)
    # Single-bar estimators (Parkinson, GK) require 20 single-bar samples (indices 0..18 NaN)
    assert vols["vol_close_to_close"].iloc[:20].isna().all()
    assert vols["vol_parkinson"].iloc[:19].isna().all()
    assert vols["vol_garman_klass"].iloc[:19].isna().all()

    # Valid values after warmup
    assert vols["vol_close_to_close"].iloc[20:].notna().all()
    assert vols["vol_parkinson"].iloc[19:].notna().all()
    assert vols["vol_garman_klass"].iloc[19:].notna().all()

    # Non-negativity check
    assert (vols["vol_close_to_close"].dropna() >= 0.0).all()
    assert (vols["vol_parkinson"].dropna() >= 0.0).all()
    assert (vols["vol_garman_klass"].dropna() >= 0.0).all()

    # Parkinson and GK should track similar annualized scale as Close-to-Close
    mean_cc = vols["vol_close_to_close"].dropna().mean()
    mean_park = vols["vol_parkinson"].dropna().mean()
    mean_gk = vols["vol_garman_klass"].dropna().mean()
    assert 0.05 < mean_cc < 0.50
    assert 0.05 < mean_park < 0.50
    assert 0.05 < mean_gk < 0.50


# ---------------------------------------------------------------------------
# 2. True Range & Wilder's Average True Range
# ---------------------------------------------------------------------------


def test_true_range_calculation():
    bars = pd.DataFrame(
        {
            "high": [10.0, 12.0, 11.0],
            "low": [8.0, 9.0, 7.0],
            "close": [9.0, 11.0, 8.0],
        }
    )
    tr = compute_true_range(bars)
    # Bar 0: H - L = 10 - 8 = 2.0
    assert tr.iloc[0] == pytest.approx(2.0)
    # Bar 1: max(12-9, |12-9|, |9-9|) = 3.0
    assert tr.iloc[1] == pytest.approx(3.0)
    # Bar 2: max(11-7, |11-11|, |7-11|) = max(4, 0, 4) = 4.0
    assert tr.iloc[2] == pytest.approx(4.0)


def test_wilders_atr_recursive_smoothing():
    bars = _synthetic_daily_bars(n=50)
    atr_df = compute_wilders_atr(bars, window=14)

    # First 13 bars must be NaN
    assert atr_df["atr"].iloc[:13].isna().all()
    # Bar 13 is initial SMA
    expected_sma = atr_df["true_range"].iloc[:14].mean()
    assert atr_df["atr"].iloc[13] == pytest.approx(expected_sma, abs=1e-9)

    # Subsequent bars follow Wilder's recursion: ATR_t = (ATR_{t-1} * 13 + TR_t) / 14
    for i in range(14, len(bars)):
        prev_atr = atr_df["atr"].iloc[i - 1]
        cur_tr = atr_df["true_range"].iloc[i]
        expected_atr = (prev_atr * 13.0 + cur_tr) / 14.0
        assert atr_df["atr"].iloc[i] == pytest.approx(expected_atr, abs=1e-9)

    # Normalized ATR = ATR / Close
    natr = atr_df["natr"].dropna()
    assert (natr > 0.0).all()
    assert (natr < 1.0).all()


# ---------------------------------------------------------------------------
# 3. West's Incremental Weighted Session VWAP
# ---------------------------------------------------------------------------


def test_west_incremental_vwap_zero_catastrophic_cancellation():
    # Large baseline offset with tiny fluctuations to stress numerical precision
    offset = 1e8
    n = 100
    bars = pd.DataFrame(
        {
            "high": offset + np.linspace(1.0, 2.0, n),
            "low": offset + np.linspace(0.0, 1.0, n),
            "close": offset + np.linspace(0.5, 1.5, n),
            "volume": np.full(n, 100.0),
        }
    )
    vwap_df = compute_session_vwap_west(bars)

    # Variance and standard deviation must remain strictly non-negative and finite
    assert (vwap_df["vwap_sd"].dropna() >= 0.0).all()
    assert np.isfinite(vwap_df["vwap"].to_numpy()).all()
    assert (vwap_df["upper_band_1"] >= vwap_df["vwap"]).all()
    assert (vwap_df["lower_band_1"] <= vwap_df["vwap"]).all()
    assert (vwap_df["upper_band_2"] >= vwap_df["upper_band_1"]).all()
    assert (vwap_df["lower_band_2"] <= vwap_df["lower_band_1"]).all()


def test_session_vwap_resets_at_session_boundaries():
    bars = _synthetic_intraday_bars(sessions=3, bars_per_sess=7)
    vwap_df = compute_session_vwap_west(bars)

    # At the start of each session, vwap equals bar 0's typical price
    for s_idx in [0, 7, 14]:
        tp_0 = (bars["high"].iloc[s_idx] + bars["low"].iloc[s_idx] + bars["close"].iloc[s_idx]) / 3.0
        assert vwap_df["vwap"].iloc[s_idx] == pytest.approx(tp_0, abs=1e-6)
        assert vwap_df["vwap_sd"].iloc[s_idx] == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 4. Slot-Relative Volume Baseline
# ---------------------------------------------------------------------------


def test_slot_relative_volume_shift1_causality():
    bars = _synthetic_intraday_bars(sessions=15, bars_per_sess=7)
    rvol_df = compute_slot_relative_volume(
        bars, baseline_sessions=10, min_slot_samples=5, fallback_bars=10, min_fallback_samples=3
    )

    assert "rvol_slot" in rvol_df.columns
    assert "log_rvol_slot" in rvol_df.columns
    assert "cum_rvol_session" in rvol_df.columns

    # Verify that changing future bar volume does not affect earlier baselines
    k_cut = 50
    tampered = bars.copy()
    vol_col_idx = tampered.columns.get_loc("volume")
    tampered.iloc[k_cut:, vol_col_idx] *= 50.0
    rvol_tampered = compute_slot_relative_volume(
        tampered, baseline_sessions=10, min_slot_samples=5, fallback_bars=10, min_fallback_samples=3
    )

    np.testing.assert_allclose(
        rvol_df["rvol_slot"].iloc[:k_cut].to_numpy(),
        rvol_tampered["rvol_slot"].iloc[:k_cut].to_numpy(),
        equal_nan=True,
    )


# ---------------------------------------------------------------------------
# 5. Black-Scholes Greeks (1st, 2nd, 3rd Order) & Strike Exposure Engine
# ---------------------------------------------------------------------------


def test_black_scholes_greeks_and_higher_order_derivatives():
    spot = 500.0
    strike = 500.0
    years = 30.0 / 365.25
    iv = 0.20
    rate = 0.045

    call_g = calculate_option_greeks(spot=spot, strike=strike, years=years, iv=iv, right="call", rate=rate)
    put_g = calculate_option_greeks(spot=spot, strike=strike, years=years, iv=iv, right="put", rate=rate)

    assert call_g is not None
    assert put_g is not None

    # Delta relations
    assert 0.45 < call_g.delta < 0.60
    assert -0.55 < put_g.delta < -0.40
    assert (call_g.delta - put_g.delta) == pytest.approx(1.0, abs=1e-5)

    # Gamma identical for Call and Put
    assert call_g.gamma > 0.0
    assert call_g.gamma == pytest.approx(put_g.gamma, abs=1e-9)

    # Vega identical for Call and Put
    assert call_g.vega > 0.0
    assert call_g.vega == pytest.approx(put_g.vega, abs=1e-9)

    # Higher-order derivatives
    assert isinstance(call_g.vanna, float)
    assert isinstance(call_g.charm, float)
    assert isinstance(call_g.speed, float)
    assert isinstance(call_g.zomma, float)


def test_dollar_gex_profile_and_wall_extraction():
    spot = 500.0
    strikes = [480, 490, 500, 510, 520]
    chain = pd.DataFrame(
        [
            {"strike": 480, "option_type": "PUT", "open_interest": 10000, "implied_volatility": 0.20, "days_to_expiration": 15},
            {"strike": 490, "option_type": "PUT", "open_interest": 5000, "implied_volatility": 0.20, "days_to_expiration": 15},
            {"strike": 500, "option_type": "CALL", "open_interest": 4000, "implied_volatility": 0.20, "days_to_expiration": 15},
            {"strike": 510, "option_type": "CALL", "open_interest": 8000, "implied_volatility": 0.20, "days_to_expiration": 15},
            {"strike": 520, "option_type": "CALL", "open_interest": 12000, "implied_volatility": 0.20, "days_to_expiration": 15},
        ]
    )

    profile = compute_dollar_gex_profile(chain, spot=spot)

    assert profile["spot"] == spot
    assert profile["call_gex_usd"] > 0.0
    assert profile["put_gex_usd"] > 0.0
    assert profile["call_wall"] is not None
    assert profile["put_wall"] is not None

    # Call wall strictly > spot, Put wall strictly < spot
    assert profile["call_wall"] > spot
    assert profile["put_wall"] < spot

    # Gamma flip nearest zero crossing
    assert profile["gamma_flip"] is not None
    assert 480.0 <= profile["gamma_flip"] <= 520.0


# ---------------------------------------------------------------------------
# 6. Signed Volume Flow Proxy & Robust Median/MAD Z-Scores
# ---------------------------------------------------------------------------


def test_signed_flow_proxy_and_mad_scaling():
    bars = _synthetic_daily_bars(n=50)
    flow_df = compute_signed_flow_proxy(bars, mad_window=20)

    assert "clv" in flow_df.columns
    assert "signed_flow_proxy" in flow_df.columns
    assert "flow_mad_z" in flow_df.columns

    # CLV is bounded strictly in [-1.0, 1.0]
    assert (flow_df["clv"] >= -1.0 - 1e-9).all()
    assert (flow_df["clv"] <= 1.0 + 1e-9).all()

    # flow_mad_z is clipped in [-5.0, 5.0]
    valid_z = flow_df["flow_mad_z"].dropna()
    assert (valid_z >= -5.0).all()
    assert (valid_z <= 5.0).all()


# ---------------------------------------------------------------------------
# 7. Executable Point-in-Time Causality & Leak-Resistance Assertion
# ---------------------------------------------------------------------------


def test_assert_causal_leak_resistant_passes():
    bars = _synthetic_daily_bars(n=80)
    assert_causal_leak_resistant(bars, cut=0.7)


def test_zero_variance_constant_price_hygiene():
    n = 40
    idx = pd.bdate_range("2024-01-02", periods=n)
    flat_bars = pd.DataFrame(
        {
            "open": np.full(n, 50.0),
            "high": np.full(n, 50.0),
            "low": np.full(n, 50.0),
            "close": np.full(n, 50.0),
            "volume": np.full(n, 1000.0),
        },
        index=idx,
    )

    features = build_layer1_regime_features(flat_bars)
    assert len(features) == n
    # Volatilities on constant price should be 0.0 without crashing or producing inf
    assert (features["vol_close_to_close"].dropna() == 0.0).all()
    assert (features["vol_parkinson"].dropna() == 0.0).all()
    assert (features["vol_garman_klass"].dropna() == 0.0).all()
    assert (features["true_range"] == 0.0).all()
