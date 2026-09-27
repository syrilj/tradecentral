"""Empirical Stress-Testing and Property Verification Suite for Milestone 1.

Challenger 1 Verification Harness:
1. Walk-Forward Causality Perturbation: Strict bit-level / machine-precision invariance at t <= T when mutating t > T.
2. Extreme & Adversarial Inputs: Zero-variance series, single-bar inputs, non-positive prices, NaNs, zero volume, High==Low.
3. Statistical Properties & Regime Discriminators: Variance ratio and OU half-life under White Noise, GBM, OU mean-reverting, and Momentum processes.
4. Scale Invariance: Exact scale-free properties of Kalman velocity and z-score across $0.01 penny stocks, $500 SPY, and $50,000 BTC.
"""

from __future__ import annotations

import math
from typing import List, Tuple
import numpy as np
import pandas as pd
import pytest

from edge.research.regime_features import (
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
from edge.research.regimes import (
    classify_regimes,
    compute_cusum_transition_risk,
    compute_market_structure,
    compute_ou_half_life,
    compute_rolling_volatility_regime,
    compute_variance_ratio,
)
from edge.research.kalman_trend import (
    kalman_constant_velocity,
    kalman_trend,
    KalmanTrendResult,
)


# ===========================================================================
# Helper Generators for Synthetic Processes
# ===========================================================================


def _generate_synthetic_panel(
    n_sessions: int = 10,
    bars_per_session: int = 20,
    seed: int = 42,
    base_price: float = 100.0,
    drift: float = 0.0001,
    vol: float = 0.005,
) -> pd.DataFrame:
    """Generate multi-session intraday bar panel with realistic microstructure."""
    rng = np.random.default_rng(seed)
    records = []
    curr_close = base_price

    for s in range(n_sessions):
        date_str = f"2024-03-{s + 1:02d}"
        for b in range(bars_per_session):
            hour = 9 + (b * 15) // 60
            minute = (b * 15) % 60
            dt = pd.Timestamp(f"{date_str} {hour:02d}:{minute:02d}:00")
            ret = rng.normal(drift, vol)
            new_close = max(0.01, curr_close * math.exp(ret))
            spread = max(0.02, new_close * rng.uniform(0.001, 0.006))
            high = max(curr_close, new_close) + spread * rng.uniform(0.2, 0.8)
            low = min(curr_close, new_close) - spread * rng.uniform(0.2, 0.8)
            open_p = curr_close + (new_close - curr_close) * rng.uniform(0.1, 0.5)
            vol_val = float(rng.integers(1000, 50000))
            records.append(
                {
                    "datetime": dt,
                    "open": open_p,
                    "high": high,
                    "low": low,
                    "close": new_close,
                    "volume": vol_val,
                }
            )
            curr_close = new_close

    df = pd.DataFrame(records).set_index("datetime")
    return df


# ===========================================================================
# 1. Walk-Forward Causality & Bit-Level Invariance Tests
# ===========================================================================


@pytest.mark.parametrize("cut_idx", [15, 50, 100, 150])
def test_layer1_full_feature_matrix_causal_invariance(cut_idx: int) -> None:
    """Mutating all future bars t > T must produce exact invariant features at t <= T."""
    df = _generate_synthetic_panel(n_sessions=10, bars_per_session=20, seed=101)
    cfg = RegimeFeatureConfig(
        volatility_window=10,
        atr_window=10,
        baseline_sessions=5,
        min_slot_samples=2,
        fallback_bars=10,
        min_fallback_samples=2,
        flow_mad_window=10,
    )

    baseline = build_layer1_regime_features(df, config=cfg)

    # Apply severe multi-dimensional perturbations to future bars
    tampered = df.copy()
    tampered.iloc[cut_idx:, tampered.columns.get_loc("open")] *= 5.0
    tampered.iloc[cut_idx:, tampered.columns.get_loc("high")] *= 7.0
    tampered.iloc[cut_idx:, tampered.columns.get_loc("low")] *= 0.1
    tampered.iloc[cut_idx:, tampered.columns.get_loc("close")] *= 4.0
    tampered.iloc[cut_idx:, tampered.columns.get_loc("volume")] *= 100.0

    mutated = build_layer1_regime_features(tampered, config=cfg)

    # Slice at cut_idx
    base_head = baseline.iloc[:cut_idx]
    mut_head = mutated.iloc[:cut_idx]

    # Verify column by column
    for col in baseline.columns:
        if col == "rvol_baseline_kind":
            assert (base_head[col].to_numpy() == mut_head[col].to_numpy()).all(), (
                f"String column {col} mismatch under future perturbation at cut {cut_idx}"
            )
        else:
            b_vals = base_head[col].to_numpy(dtype=float)
            m_vals = mut_head[col].to_numpy(dtype=float)
            both_nan = np.isnan(b_vals) & np.isnan(m_vals)
            equal = np.isclose(b_vals, m_vals, rtol=1e-12, atol=1e-12, equal_nan=True) | both_nan
            if not equal.all():
                bad_idx = np.where(~equal)[0]
                pytest.fail(
                    f"Causality leak in column '{col}' at indices {bad_idx}. "
                    f"Baseline: {b_vals[bad_idx]}, Mutated: {m_vals[bad_idx]}"
                )


@pytest.mark.parametrize("cut_idx", [30, 80, 140])
def test_layer2_models_causal_invariance(cut_idx: int) -> None:
    """Layer 2 Statistical Models (Vol Regime, Market Structure, CUSUM, Kalman) must be strictly causal."""
    df = _generate_synthetic_panel(n_sessions=10, bars_per_session=20, seed=202)
    prices = df["close"]

    # 1. Baseline runs
    base_vol = compute_rolling_volatility_regime(prices, vol_window=15, percentile_window=60)
    base_struct = compute_market_structure(prices, vr_window=30, vr_lag=5, ou_window=20)
    log_ret = compute_log_returns(prices)
    base_cusum = compute_cusum_transition_risk(log_ret, vol_window=15)
    base_kalman = kalman_trend(prices, q=1e-6, noise_days=10)

    # 2. Tampered runs
    mut_prices = prices.copy()
    mut_prices.iloc[cut_idx:] *= 3.5

    mut_vol = compute_rolling_volatility_regime(mut_prices, vol_window=15, percentile_window=60)
    mut_struct = compute_market_structure(mut_prices, vr_window=30, vr_lag=5, ou_window=20)
    mut_log_ret = compute_log_returns(mut_prices)
    mut_cusum = compute_cusum_transition_risk(mut_log_ret, vol_window=15)
    mut_kalman = kalman_trend(mut_prices, q=1e-6, noise_days=10)

    # 3. Assert exact equivalence up to cut_idx
    # Volatility Regime
    np.testing.assert_allclose(
        base_vol.realized_volatility.iloc[:cut_idx].to_numpy(),
        mut_vol.realized_volatility.iloc[:cut_idx].to_numpy(),
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )
    np.testing.assert_allclose(
        base_vol.volatility_percentile.iloc[:cut_idx].to_numpy(),
        mut_vol.volatility_percentile.iloc[:cut_idx].to_numpy(),
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )
    pd.testing.assert_series_equal(
        base_vol.volatility_state.iloc[:cut_idx],
        mut_vol.volatility_state.iloc[:cut_idx],
    )
    pd.testing.assert_series_equal(
        base_vol.volatility_shock.iloc[:cut_idx],
        mut_vol.volatility_shock.iloc[:cut_idx],
    )

    # Market Structure
    np.testing.assert_allclose(
        base_struct.variance_ratio_5.iloc[:cut_idx].to_numpy(),
        mut_struct.variance_ratio_5.iloc[:cut_idx].to_numpy(),
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )
    np.testing.assert_allclose(
        base_struct.ou_half_life.iloc[:cut_idx].to_numpy(),
        mut_struct.ou_half_life.iloc[:cut_idx].to_numpy(),
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )
    pd.testing.assert_series_equal(
        base_struct.market_structure.iloc[:cut_idx],
        mut_struct.market_structure.iloc[:cut_idx],
    )

    # CUSUM Transition Risk
    np.testing.assert_allclose(
        base_cusum.transition_risk.iloc[:cut_idx].to_numpy(),
        mut_cusum.transition_risk.iloc[:cut_idx].to_numpy(),
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )

    # Kalman Filter
    np.testing.assert_allclose(
        base_kalman.level[:cut_idx],
        mut_kalman.level[:cut_idx],
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )
    np.testing.assert_allclose(
        base_kalman.slope[:cut_idx],
        mut_kalman.slope[:cut_idx],
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )
    np.testing.assert_allclose(
        base_kalman.score[:cut_idx],
        mut_kalman.score[:cut_idx],
        rtol=1e-12,
        atol=1e-12,
        equal_nan=True,
    )
    assert (base_kalman.trend_state[:cut_idx] == mut_kalman.trend_state[:cut_idx]).all()


# ===========================================================================
# 2. Extreme Inputs & Adversarial Boundary Tests
# ===========================================================================


def test_zero_variance_constant_series_comprehensive() -> None:
    """A series where prices never move must not cause ZeroDivisionError, Inf, or NaN leaks."""
    n = 60
    idx = pd.bdate_range("2024-01-02", periods=n)
    flat_df = pd.DataFrame(
        {
            "open": np.full(n, 100.0),
            "high": np.full(n, 100.0),
            "low": np.full(n, 100.0),
            "close": np.full(n, 100.0),
            "volume": np.full(n, 5000.0),
        },
        index=idx,
    )

    # Layer 1 Features
    l1 = build_layer1_regime_features(flat_df)
    assert (l1["log_return"].dropna() == 0.0).all()
    assert (l1["vol_close_to_close"].dropna() == 0.0).all()
    assert (l1["vol_parkinson"].dropna() == 0.0).all()
    assert (l1["vol_garman_klass"].dropna() == 0.0).all()
    assert (l1["true_range"] == 0.0).all()
    assert (l1["atr"].dropna() == 0.0).all()
    assert (l1["natr"].dropna() == 0.0).all()
    assert (l1["vwap"] == 100.0).all()
    assert (l1["vwap_sd"] == 0.0).all()
    assert (l1["clv"] == 0.0).all()
    assert (l1["signed_flow_proxy"] == 0.0).all()

    # Layer 2 Models
    vol_res = compute_rolling_volatility_regime(
        flat_df["close"], vol_window=10, percentile_window=30
    )
    assert (vol_res.realized_volatility.dropna() == 0.0).all()
    assert (vol_res.volatility_shock == False).all()

    struct_res = compute_market_structure(flat_df["close"], vr_window=20, ou_window=15)
    assert (struct_res.variance_ratio_5.dropna() == 1.0).all()
    assert (struct_res.ou_half_life.dropna() == 100.0).all()
    assert (struct_res.market_structure == "RANGE_BOUND").all()

    kalman_res = kalman_trend(flat_df["close"], q=1e-6, noise_days=10)
    assert np.allclose(kalman_res.slope, 0.0)
    assert np.allclose(kalman_res.score, 0.0)
    assert (kalman_res.trend_state == "FLAT_NEUTRAL").all()
    assert len(kalman_res.trades) == 0


def test_zero_volume_bars_resilience() -> None:
    """Zero volume bars must not divide by zero in VWAP, slot RVOL, or signed flow."""
    n = 40
    idx = pd.bdate_range("2024-01-02", periods=n)
    zero_vol_df = pd.DataFrame(
        {
            "open": np.linspace(100, 110, n),
            "high": np.linspace(101, 111, n),
            "low": np.linspace(99, 109, n),
            "close": np.linspace(100.5, 110.5, n),
            "volume": np.zeros(n),
        },
        index=idx,
    )

    vwap_df = compute_session_vwap_west(zero_vol_df)
    # With 0 volume, VWAP remains NaN without crash
    assert vwap_df["vwap"].isna().all()
    assert vwap_df["vwap_sd"].isna().all()

    flow_df = compute_signed_flow_proxy(zero_vol_df, mad_window=10)
    assert (flow_df["signed_flow_proxy"] == 0.0).all()
    assert (flow_df["cum_signed_flow_session"] == 0.0).all()


def test_single_bar_input_handling() -> None:
    """Single bar input (N=1) must return cleanly without unhandled crashes."""
    single_bar = pd.DataFrame(
        {"open": [100.0], "high": [105.0], "low": [98.0], "close": [102.0], "volume": [1000.0]},
        index=pd.to_datetime(["2024-01-02"]),
    )

    # Log returns
    r = compute_log_returns(single_bar["close"])
    assert len(r) == 1
    assert np.isnan(r.iloc[0])

    # True range
    tr = compute_true_range(single_bar)
    assert len(tr) == 1
    assert tr.iloc[0] == pytest.approx(7.0)

    # ATR on 1 bar (window=14) -> NaN
    atr_df = compute_wilders_atr(single_bar, window=14)
    assert atr_df["atr"].isna().iloc[0]

    # Kalman trend on 1 bar
    kt = kalman_trend(single_bar["close"], q=1e-6, noise_days=10)
    assert len(kt.level) == 1
    assert len(kt.trades) == 0

    # compute_rolling_volatility_regime on N=1 produces NaN / pd.NA without crash
    vol_res = compute_rolling_volatility_regime(
        single_bar["close"], vol_window=20, percentile_window=252
    )
    assert len(vol_res.realized_volatility) == 1
    assert vol_res.realized_volatility.isna().iloc[0]
    assert pd.isna(vol_res.volatility_state.iloc[0])


def test_negative_and_zero_prices_rejection() -> None:
    """Non-positive prices must be safely rejected in log-transform models."""
    bad_prices_neg = pd.Series([100.0, -5.0, 102.0], index=pd.bdate_range("2024-01-02", periods=3))
    bad_prices_zero = pd.Series([100.0, 0.0, 102.0], index=pd.bdate_range("2024-01-02", periods=3))

    # kalman_trend must raise ValueError
    with pytest.raises(ValueError, match="strictly positive"):
        kalman_trend(bad_prices_neg)
    with pytest.raises(ValueError, match="strictly positive"):
        kalman_trend(bad_prices_zero)

    # compute_rolling_volatility_regime must raise ValueError
    with pytest.raises(ValueError, match="strictly positive"):
        compute_rolling_volatility_regime(bad_prices_neg)

    # compute_market_structure must raise ValueError
    with pytest.raises(ValueError, match="strictly positive"):
        compute_market_structure(bad_prices_zero)


def test_black_scholes_extreme_inputs() -> None:
    """Black-Scholes Greek calculation under extreme boundaries (IV=0, DTE=0, Spot<=0)."""
    # Negative spot / strike
    assert calculate_option_greeks(spot=-10.0, strike=100.0, years=0.1, iv=0.2, right="C") is None
    assert calculate_option_greeks(spot=100.0, strike=0.0, years=0.1, iv=0.2, right="C") is None

    # Extremely high IV (> _MAX_IV = 5.0) or below min IV
    assert calculate_option_greeks(spot=100.0, strike=100.0, years=0.1, iv=10.0, right="C") is None
    assert calculate_option_greeks(spot=100.0, strike=100.0, years=0.1, iv=0.001, right="C") is None

    # Very small time to expiry (0.0001 year) -> clamped safely to _MIN_TIME_YEARS without ZeroDivisionError
    g = calculate_option_greeks(spot=100.0, strike=100.0, years=0.00001, iv=0.20, right="C")
    assert g is not None
    assert np.isfinite(g.delta)
    assert np.isfinite(g.gamma)
    assert np.isfinite(g.theta)


def test_empty_and_flat_option_chains() -> None:
    """compute_dollar_gex_profile on empty or zero OI option chains."""
    empty_df = pd.DataFrame()
    res = compute_dollar_gex_profile(empty_df, spot=100.0)
    assert res["net_gex_usd"] == 0.0
    assert res["gamma_flip"] is None
    assert res["call_wall"] is None
    assert res["put_wall"] is None

    zero_oi_df = pd.DataFrame(
        [
            {
                "strike": 100,
                "option_type": "CALL",
                "open_interest": 0,
                "implied_volatility": 0.2,
                "days_to_expiration": 30,
            }
        ]
    )
    res_zero = compute_dollar_gex_profile(zero_oi_df, spot=100.0)
    assert res_zero["net_gex_usd"] == 0.0


# ===========================================================================
# 3. Statistical Properties: Variance Ratio & OU Half-Life Across Processes
# ===========================================================================


def test_variance_ratio_and_ou_across_synthetic_stochastic_processes() -> None:
    """Empirically test VR(5) and OU half-life under 4 distinct mathematical processes:

    1. Pure White Noise (stationary in levels, negative 1-lag return correlation): VR << 1.0, short OU half-life.
    2. Geometric Brownian Motion (random walk in log-price): VR ~ 1.0, long OU half-life.
    3. Discrete Ornstein-Uhlenbeck Process: AR(1) reversion matches theoretical half-life t_1/2 = ln(2)/theta.
    4. Momentum / Trending Process: Positive return autocorrelation: VR > 1.20.
    """
    n = 2000
    rng = np.random.default_rng(12345)

    # ---------------------------------------------------------
    # 1. Pure White Noise in Price Levels: P_t = 100 + epsilon_t
    # ---------------------------------------------------------
    noise = rng.normal(0.0, 1.0, n)
    wn_prices = 100.0 + noise
    log_wn = np.log(wn_prices)

    vr_wn = compute_variance_ratio(log_wn, q=5)
    ou_wn = compute_ou_half_life(wn_prices, window=500)

    # For white noise levels, q-lag variance ratio is ~ 1/q = 0.20
    assert vr_wn < 0.50, f"Expected White Noise VR(5) < 0.50, got {vr_wn:.3f}"
    assert ou_wn <= 3.0, f"Expected White Noise OU half-life <= 3 bars, got {ou_wn:.3f}"

    # ---------------------------------------------------------
    # 2. Geometric Brownian Motion (Random Walk): r_t ~ i.i.d Normal
    # ---------------------------------------------------------
    gbm_ret = rng.normal(0.0, 0.01, n)
    gbm_log_p = np.cumsum(gbm_ret) + np.log(100.0)
    gbm_prices = np.exp(gbm_log_p)

    vr_gbm = compute_variance_ratio(gbm_log_p, q=5)
    ou_gbm = compute_ou_half_life(gbm_prices, window=500)

    # For GBM, VR(5) must be close to 1.0
    assert 0.85 <= vr_gbm <= 1.15, f"Expected GBM VR(5) in [0.85, 1.15], got {vr_gbm:.3f}"
    # OU half-life should be long (> 30 bars) since random walk has no mean reversion
    assert ou_gbm >= 30.0, f"Expected GBM OU half-life >= 30 bars, got {ou_gbm:.3f}"

    # ---------------------------------------------------------
    # 3. Discrete OU Process: X_t = beta * X_{t-1} + eps_t (Monte Carlo mean across seeds)
    # ---------------------------------------------------------
    for target_half_life in [5.0, 12.0, 25.0]:
        theta = math.log(2.0) / target_half_life
        beta = math.exp(-theta)
        mc_estimates = []
        for s in range(20):
            r_seed = np.random.default_rng(1000 + s)
            x = np.zeros(n)
            for t in range(1, n):
                x[t] = beta * x[t - 1] + r_seed.normal(0.0, 0.5)
            ou_prices = 100.0 + x
            est = compute_ou_half_life(ou_prices, window=n)
            mc_estimates.append(est)

        mean_est = float(np.mean(mc_estimates))
        assert mean_est == pytest.approx(target_half_life, rel=0.15), (
            f"Expected mean OU half-life ~ {target_half_life}, got {mean_est:.2f}"
        )

    # ---------------------------------------------------------
    # 4. Momentum / Trending Process: r_t = 0.6 * r_{t-1} + eps_t
    # ---------------------------------------------------------
    mom_ret = np.zeros(n)
    for t in range(1, n):
        mom_ret[t] = 0.6 * mom_ret[t - 1] + rng.normal(0.0, 0.005)
    mom_log_p = np.cumsum(mom_ret) + np.log(100.0)

    vr_mom = compute_variance_ratio(mom_log_p, q=5)
    assert vr_mom > 1.30, f"Expected Momentum VR(5) > 1.30, got {vr_mom:.3f}"


# ===========================================================================
# 4. Scale Invariance: Kalman Velocity Z-Score Across Asset Price Tiers
# ===========================================================================


@pytest.mark.parametrize(
    "scale_factor",
    [0.01, 0.1, 1.0, 50.0, 500.0, 50000.0],
)
def test_kalman_velocity_zscore_strict_scale_invariance(scale_factor: float) -> None:
    """Kalman filter operates on log-prices; velocity z-score must be bit-level scale invariant.

    Testing identical return paths scaled from $0.01 (micro-penny) to $50,000 (crypto/mega-cap).
    Float64 machine precision ensures score agreement to < 1e-9 across 7 orders of magnitude.
    """
    rng = np.random.default_rng(999)
    n = 300
    idx = pd.bdate_range("2024-01-02", periods=n)
    log_returns = rng.normal(0.0005, 0.012, n)
    base_prices = 100.0 * np.exp(np.cumsum(log_returns))

    scaled_prices = pd.Series(base_prices * scale_factor, index=idx)
    reference_prices = pd.Series(base_prices, index=idx)

    res_scaled = kalman_trend(scaled_prices, q=1e-6, noise_days=20)
    res_ref = kalman_trend(reference_prices, q=1e-6, noise_days=20)

    # 1. Slope (velocity in log-space) must be numerically identical
    np.testing.assert_allclose(
        res_scaled.slope,
        res_ref.slope,
        rtol=1e-9,
        atol=1e-9,
        err_msg=f"Kalman slope mismatch at scale {scale_factor}",
    )

    # 2. Rolling noise of slope must be numerically identical
    np.testing.assert_allclose(
        res_scaled.noise,
        res_ref.noise,
        rtol=1e-9,
        atol=1e-9,
        equal_nan=True,
        err_msg=f"Kalman noise mismatch at scale {scale_factor}",
    )

    # 3. Velocity z-score (score) must be numerically identical
    np.testing.assert_allclose(
        res_scaled.score,
        res_ref.score,
        rtol=1e-9,
        atol=1e-9,
        err_msg=f"Kalman velocity z-score mismatch at scale {scale_factor}",
    )

    # 4. Trend state classification must be 100% identical
    assert (res_scaled.trend_state == res_ref.trend_state).all(), (
        f"Trend state mismatch at scale {scale_factor}"
    )

    # 5. Persistence counts must be 100% identical
    assert (res_scaled.persistence == res_ref.persistence).all()
    assert (res_scaled.persistence_score == res_ref.persistence_score).all()

    # 6. Reconstructed trades must be 100% identical
    assert len(res_scaled.trades) == len(res_ref.trades)
    for t_scale, t_ref in zip(res_scaled.trades, res_ref.trades):
        assert t_scale.entry_i == t_ref.entry_i
        assert t_scale.exit_i == t_ref.exit_i
        assert t_scale.direction == t_ref.direction
    assert res_scaled.open_at_end == res_ref.open_at_end
