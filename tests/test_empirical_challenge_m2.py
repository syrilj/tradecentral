"""Empirical Challenge Test Suite for Milestone 2 (Layer 3 Reconciliation Engine).

Adversarial and stress-testing harness verifying:
1. Softmax probability normalization across 10,000 synthetic configurations: assert sum(p_i) == 1.0 +- 1e-6 strictly everywhere.
2. Multiplicative confidence behavior: assert C in [0.0, 1.0] under all parameter bounds; assert introducing model conflict strictly reduces C.
3. Fail-closed boundary testing: assert flip band proximity |delta_flip| <= 0.0025 strictly forces UNCERTAIN_TRANSITIONAL.
4. Missing data handling: assert missing options or low-bar history yields measurable=False or unmeasurable states without NaNs.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
import pytest

from edge.research.regime_engine import (
    FlowContext,
    MarketStructure,
    ModelAgreement,
    ModelPosture,
    PairwiseConflict,
    PrimaryRegime,
    QualityMetrics,
    RegimeProbabilities,
    StructuralLevels,
    UnifiedMarketState,
    VolatilityState,
    build_agreement_matrix,
    compute_a_models,
    compute_calibrated_confidence,
    compute_d_boundary,
    compute_multi_model_postures,
    compute_q_data,
    compute_regime_probabilities,
    compute_s_persistence,
    compute_t_risk_hazard,
    compute_unified_market_regime,
    reconcile_market_regime,
)


def _make_synthetic_ohlcv(
    n: int = 100,
    trend: float = 0.001,
    vol: float = 0.01,
    seed: int = 42,
    base_price: float = 100.0,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(loc=trend, scale=vol, size=n)
    close = base_price * np.cumprod(1.0 + rets)
    open_ = np.concatenate([[base_price], close[:-1]])
    high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0, 0.002, size=n)))
    low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0, 0.002, size=n)))
    volume = rng.integers(1_000_000, 5_000_000, size=n).astype(float)
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


# ============================================================================
# Task 1: 10,000 Synthetic Configuration Softmax Simplex Normalization
# ============================================================================


class TestProbabilitySimplex10kStress:
    """Stress-test softmax probability normalization across 10,000 synthetic configurations."""

    def test_10000_synthetic_probability_configurations(self):
        """Assert sum(p_i) == 1.0000 +- 1e-6 and p_i in [0.0, 1.0] across 10,000 random configurations."""
        rng = np.random.default_rng(987654321)
        n_trials = 10_000

        vol_states = [
            "COMPRESSION_LOW",
            "NORMAL_MEDIUM",
            "ELEVATED_HIGH",
            "VOLATILITY_SHOCK",
        ]

        # Generate batch parameters
        kalman_zs = rng.uniform(-10.0, 10.0, size=n_trials)
        flow_mad_zs = rng.uniform(-10.0, 10.0, size=n_trials)
        variance_ratios = rng.uniform(0.01, 10.0, size=n_trials)
        vol_pctiles = rng.uniform(-0.5, 1.5, size=n_trials)  # intentionally test beyond [0, 1]
        t_risks = rng.uniform(-0.5, 1.5, size=n_trials)      # intentionally test beyond [0, 1]
        a_models_arr = rng.uniform(-0.5, 1.5, size=n_trials)  # intentionally test beyond [0, 1]
        tau_0s = rng.uniform(0.05, 5.0, size=n_trials)

        for i in range(n_trials):
            # Introduce occasional None, zero, and extreme values
            net_gex = None if rng.random() < 0.25 else float(rng.uniform(-1e11, 1e11))
            delta_flip = None if rng.random() < 0.25 else float(rng.uniform(-0.50, 0.50))
            vol_state = rng.choice(vol_states)

            probs = compute_regime_probabilities(
                kalman_z=float(kalman_zs[i]),
                flow_mad_z=float(flow_mad_zs[i]),
                variance_ratio=float(variance_ratios[i]),
                net_gex_usd=net_gex,
                delta_flip=delta_flip,
                vol_percentile=float(vol_pctiles[i]),
                vol_state=str(vol_state),
                t_risk=float(t_risks[i]),
                a_models=float(a_models_arr[i]),
                tau_0=float(tau_0s[i]),
            )

            p_bull = probs.bullish
            p_bear = probs.bearish
            p_neutral = probs.neutral

            # 1. No NaNs or Infs
            assert math.isfinite(p_bull), f"Iteration {i}: p_bull is non-finite: {p_bull}"
            assert math.isfinite(p_bear), f"Iteration {i}: p_bear is non-finite: {p_bear}"
            assert math.isfinite(p_neutral), f"Iteration {i}: p_neutral is non-finite: {p_neutral}"

            # 2. Probability bounds [0.0, 1.0]
            assert 0.0 <= p_bull <= 1.0, f"Iteration {i}: p_bull={p_bull} out of bounds"
            assert 0.0 <= p_bear <= 1.0, f"Iteration {i}: p_bear={p_bear} out of bounds"
            assert 0.0 <= p_neutral <= 1.0, f"Iteration {i}: p_neutral={p_neutral} out of bounds"

            # 3. Sum equals 1.0000 within 1e-6 tolerance strictly
            p_sum = p_bull + p_bear + p_neutral
            assert math.isclose(p_sum, 1.0000, abs_tol=1e-6), (
                f"Iteration {i}: sum={p_sum:.8f} != 1.0000"
            )

            # 4. Dictionary representation compliance
            p_dict = probs.to_dict()
            assert set(p_dict.keys()) == {"bullish", "bearish", "neutral"}
            assert math.isclose(sum(p_dict.values()), 1.0000, abs_tol=1e-6)

    def test_extreme_magnitude_numerical_stability(self):
        """Test extreme input numbers (+-1e6) do not overflow softmax or produce NaNs."""
        for extreme_val in [-1e6, -1e4, -100.0, 100.0, 1e4, 1e6]:
            probs = compute_regime_probabilities(
                kalman_z=extreme_val,
                flow_mad_z=extreme_val,
                variance_ratio=abs(extreme_val),
                net_gex_usd=extreme_val * 1e6,
                delta_flip=extreme_val,
                vol_percentile=0.5,
                vol_state="NORMAL_MEDIUM",
                t_risk=0.5,
                a_models=0.5,
            )
            p_sum = probs.bullish + probs.bearish + probs.neutral
            assert math.isclose(p_sum, 1.0000, abs_tol=1e-6)
            assert 0.0 <= probs.bullish <= 1.0
            assert 0.0 <= probs.bearish <= 1.0
            assert 0.0 <= probs.neutral <= 1.0


# ============================================================================
# Task 2: Multiplicative Calibrated Confidence Bounds & Conflict Monotonicity
# ============================================================================


class TestCalibratedConfidenceAndConflictMonotonicity:
    """Stress-test confidence bounds [0, 1], zero-collapse, and monotonicity under conflict."""

    def test_10000_confidence_parameter_sweeps(self):
        """Assert C in [0.0, 1.0] under 10,000 randomized parameter configurations."""
        rng = np.random.default_rng(54321)
        n_trials = 10_000

        q_datas = rng.uniform(-2.0, 2.0, size=n_trials)
        a_models = rng.uniform(-2.0, 2.0, size=n_trials)
        d_bounds = rng.uniform(-2.0, 2.0, size=n_trials)
        s_persists = rng.uniform(-2.0, 2.0, size=n_trials)
        t_risks = rng.uniform(-2.0, 2.0, size=n_trials)

        for i in range(n_trials):
            c = compute_calibrated_confidence(
                q_data=float(q_datas[i]),
                a_models=float(a_models[i]),
                d_boundary=float(d_bounds[i]),
                s_persistence=float(s_persists[i]),
                t_risk=float(t_risks[i]),
            )

            assert math.isfinite(c), f"Iteration {i}: non-finite confidence {c}"
            assert 0.0 <= c <= 1.0, f"Iteration {i}: confidence {c} out of [0.0, 1.0]"

    def test_zero_trust_collapse_property(self):
        """Assert C == 0.0 strictly whenever any individual confidence pillar is zero."""
        # 1. Zero data quality -> C = 0.0
        assert compute_calibrated_confidence(0.0, 1.0, 1.0, 1.0, 0.0) == 0.0
        # 2. Zero model agreement -> C = 0.0
        assert compute_calibrated_confidence(1.0, 0.0, 1.0, 1.0, 0.0) == 0.0
        # 3. Zero boundary distance -> C = 0.0
        assert compute_calibrated_confidence(1.0, 1.0, 0.0, 1.0, 0.0) == 0.0
        # 4. Zero persistence -> C = 0.0
        assert compute_calibrated_confidence(1.0, 1.0, 1.0, 0.0, 0.0) == 0.0

    def test_conflict_strictly_reduces_agreement_and_confidence(self):
        """Assert introducing model conflict strictly reduces consensus score A and confidence C."""
        # Baseline: Fully aligned bullish postures across all 5 models
        postures_aligned = [
            ModelPosture("Trend (Kalman)", 0.85, 1, "kalman_z", 2.0, "Trend bull"),
            ModelPosture("Gamma Topography", 0.80, 1, "net_gex_m", 50.0, "Gamma bull"),
            ModelPosture("Market Structure (VR)", 0.75, 1, "variance_ratio_5", 1.4, "Structure bull"),
            ModelPosture("Order Flow (MAD)", 0.70, 1, "flow_mad_z", 2.0, "Flow bull"),
            ModelPosture("Volatility Environment", 0.65, 1, "volatility_percentile", 0.35, "Vol bull"),
        ]

        mat_0, a_0, confs_0 = build_agreement_matrix(postures_aligned)
        c_0 = compute_calibrated_confidence(q_data=1.0, a_models=a_0, d_boundary=1.0, s_persistence=1.0, t_risk=0.1)

        assert len(confs_0) == 0
        assert a_0 > 0.75

        # Step 1: Introduce Conflict 1 (Gamma opposes Trend: dealer short gamma)
        postures_conf1 = list(postures_aligned)
        postures_conf1[1] = ModelPosture("Gamma Topography", -0.80, -1, "net_gex_m", -50.0, "Gamma short")
        mat_1, a_1, confs_1 = build_agreement_matrix(postures_conf1)
        c_1 = compute_calibrated_confidence(q_data=1.0, a_models=a_1, d_boundary=1.0, s_persistence=1.0, t_risk=0.1)

        # Monotonic reduction check
        assert a_1 < a_0, f"Consensus score failed to decrease: a_1 ({a_1}) >= a_0 ({a_0})"
        assert c_1 < c_0, f"Confidence failed to decrease: c_1 ({c_1}) >= c_0 ({c_0})"
        assert any(c.conflict_code == "CONF_GAMMA_TREND" for c in confs_1)

        # Step 2: Introduce Conflict 2 (Order Flow opposes Trend: distribution into momentum)
        postures_conf2 = list(postures_conf1)
        postures_conf2[3] = ModelPosture("Order Flow (MAD)", -0.75, -1, "flow_mad_z", -2.2, "Flow bear")
        mat_2, a_2, confs_2 = build_agreement_matrix(postures_conf2)
        c_2 = compute_calibrated_confidence(q_data=1.0, a_models=a_2, d_boundary=1.0, s_persistence=1.0, t_risk=0.1)

        # Monotonic reduction check
        assert a_2 < a_1, f"Consensus score failed to decrease: a_2 ({a_2}) >= a_1 ({a_1})"
        assert c_2 < c_1, f"Confidence failed to decrease: c_2 ({c_2}) >= c_1 ({c_1})"
        assert any(c.conflict_code == "CONF_FLOW_PRICE" for c in confs_2)

        # Step 3: Extreme conflict (2 bull, 2 bear, 1 neutral)
        postures_conf3 = [
            ModelPosture("Trend (Kalman)", 1.0, 1, "kalman_z", 2.5, "Trend bull"),
            ModelPosture("Gamma Topography", -1.0, -1, "net_gex_m", -80.0, "Gamma short"),
            ModelPosture("Market Structure (VR)", 1.0, 1, "variance_ratio_5", 1.5, "Structure bull"),
            ModelPosture("Order Flow (MAD)", -1.0, -1, "flow_mad_z", -3.0, "Flow bear"),
            ModelPosture("Volatility Environment", 0.0, 0, "volatility_percentile", 0.5, "Vol flat"),
        ]
        mat_3, a_3, confs_3 = build_agreement_matrix(postures_conf3)
        c_3 = compute_calibrated_confidence(q_data=1.0, a_models=a_3, d_boundary=1.0, s_persistence=1.0, t_risk=0.1)

        assert a_3 < a_2, f"Consensus score failed to decrease: a_3 ({a_3}) >= a_2 ({a_2})"
        assert c_3 < c_2, f"Confidence failed to decrease: c_3 ({c_3}) >= c_2 ({c_2})"
        assert c_3 <= 0.55 * c_0

    def test_all_five_named_conflicts_detection(self):
        """Verify each of the 5 named pairwise conflicts triggers accurately."""
        # 1. CONF_GAMMA_TREND
        p1 = [
            ModelPosture("Trend (Kalman)", 0.70, 1, "", 0, ""),
            ModelPosture("Gamma Topography", -0.60, -1, "", 0, ""),
            ModelPosture("Market Structure (VR)", 0.0, 0, "", 0, ""),
            ModelPosture("Order Flow (MAD)", 0.0, 0, "", 0, ""),
            ModelPosture("Volatility Environment", 0.0, 0, "", 0, ""),
        ]
        _, _, conf1 = build_agreement_matrix(p1)
        assert any(c.conflict_code == "CONF_GAMMA_TREND" for c in conf1)

        # 2. CONF_FLOW_PRICE
        p2 = [
            ModelPosture("Trend (Kalman)", 0.70, 1, "", 0, ""),
            ModelPosture("Gamma Topography", 0.0, 0, "", 0, ""),
            ModelPosture("Market Structure (VR)", 0.0, 0, "", 0, ""),
            ModelPosture("Order Flow (MAD)", -0.70, -1, "", 0, ""),
            ModelPosture("Volatility Environment", 0.0, 0, "", 0, ""),
        ]
        _, _, conf2 = build_agreement_matrix(p2)
        assert any(c.conflict_code == "CONF_FLOW_PRICE" for c in conf2)

        # 3. CONF_VOL_EXPANSION
        p3 = [
            ModelPosture("Trend (Kalman)", 0.70, 1, "", 0, ""),
            ModelPosture("Gamma Topography", 0.0, 0, "", 0, ""),
            ModelPosture("Market Structure (VR)", 0.0, 0, "", 0, ""),
            ModelPosture("Order Flow (MAD)", 0.0, 0, "", 0, ""),
            ModelPosture("Volatility Environment", -0.5, -1, "", 0, ""),
        ]
        _, _, conf3 = build_agreement_matrix(p3, vol_state="VOLATILITY_SHOCK")
        assert any(c.conflict_code == "CONF_VOL_EXPANSION" for c in conf3)

        # 4. CONF_STRUCT_MOMENTUM
        p4 = [
            ModelPosture("Trend (Kalman)", 0.85, 1, "", 0, ""),
            ModelPosture("Gamma Topography", 0.0, 0, "", 0, ""),
            ModelPosture("Market Structure (VR)", -0.80, -1, "", 0, ""),
            ModelPosture("Order Flow (MAD)", 0.0, 0, "", 0, ""),
            ModelPosture("Volatility Environment", 0.0, 0, "", 0, ""),
        ]
        _, _, conf4 = build_agreement_matrix(p4, variance_ratio=0.75, ou_half_life=8.0)
        assert any(c.conflict_code == "CONF_STRUCT_MOMENTUM" for c in conf4)

        # 5. CONF_GAMMA_FLOW
        p5 = [
            ModelPosture("Trend (Kalman)", 0.0, 0, "", 0, ""),
            ModelPosture("Gamma Topography", 0.70, 1, "", 0, ""),
            ModelPosture("Market Structure (VR)", 0.0, 0, "", 0, ""),
            ModelPosture("Order Flow (MAD)", -0.80, -1, "", 0, ""),
            ModelPosture("Volatility Environment", 0.0, 0, "", 0, ""),
        ]
        _, _, conf5 = build_agreement_matrix(p5)
        assert any(c.conflict_code == "CONF_GAMMA_FLOW" for c in conf5)


# ============================================================================
# Task 3: Fail-Closed Boundary Testing
# ============================================================================


class TestFailClosedBoundaries:
    """Stress-test flip band proximity |delta_flip| <= 0.0025, hazard spikes, and consensus break."""

    def test_flip_band_proximity_boundary_sweep(self):
        """Assert |delta_flip| <= 0.0025 strictly forces UNCERTAIN_TRANSITIONAL regardless of strong trends."""
        # Inside flip band: -0.0025 <= delta_flip <= 0.0025
        inside_band_deltas = [
            -0.002500,
            -0.002499,
            -0.002000,
            -0.001000,
            -0.000100,
            0.000000,
            0.000100,
            0.001000,
            0.002000,
            0.002499,
            0.002500,
        ]

        for df in inside_band_deltas:
            # Overwhelming bullish conditions
            regime = reconcile_market_regime(
                kalman_z=3.0,
                trend_state="BULLISH_TREND",
                vol_percentile=0.30,
                vol_state=VolatilityState.NORMAL_MEDIUM,
                market_structure=MarketStructure.TRENDING,
                variance_ratio=1.50,
                ou_half_life=30.0,
                flow_mad_z=3.0,
                t_risk=0.05,
                delta_flip=df,
                agreement_ratio=0.95,
                has_model_conflict=False,
                is_measurable=True,
            )
            assert regime == PrimaryRegime.UNCERTAIN_TRANSITIONAL, (
                f"delta_flip={df} inside flip band failed to force UNCERTAIN_TRANSITIONAL (got {regime})"
            )

    def test_outside_flip_band_allows_regime_formation(self):
        """Assert |delta_flip| > 0.0025 allows strong trend regime formation when other conditions hold."""
        outside_band_deltas = [
            0.002501,
            0.003000,
            0.005000,
            0.020000,
            0.050000,
        ]

        for df in outside_band_deltas:
            regime_bull = reconcile_market_regime(
                kalman_z=2.0,
                trend_state="BULLISH_TREND",
                vol_percentile=0.30,
                vol_state=VolatilityState.NORMAL_MEDIUM,
                market_structure=MarketStructure.TRENDING,
                variance_ratio=1.40,
                ou_half_life=30.0,
                flow_mad_z=2.0,
                t_risk=0.10,
                delta_flip=df,
                agreement_ratio=0.90,
                has_model_conflict=False,
                is_measurable=True,
            )
            assert regime_bull == PrimaryRegime.BULLISH_TREND, (
                f"delta_flip={df} outside flip band incorrectly blocked BULLISH_TREND (got {regime_bull})"
            )

        outside_band_neg_deltas = [
            -0.002501,
            -0.003000,
            -0.005000,
            -0.020000,
            -0.050000,
        ]

        for df in outside_band_neg_deltas:
            regime_bear = reconcile_market_regime(
                kalman_z=-2.0,
                trend_state="BEARISH_TREND",
                vol_percentile=0.30,
                vol_state=VolatilityState.NORMAL_MEDIUM,
                market_structure=MarketStructure.TRENDING,
                variance_ratio=1.40,
                ou_half_life=30.0,
                flow_mad_z=-2.0,
                t_risk=0.10,
                delta_flip=df,
                agreement_ratio=0.90,
                has_model_conflict=False,
                is_measurable=True,
            )
            assert regime_bear == PrimaryRegime.BEARISH_TREND, (
                f"delta_flip={df} outside flip band incorrectly blocked BEARISH_TREND (got {regime_bear})"
            )

    def test_transition_risk_hazard_spike_fail_closed(self):
        """Assert T_risk >= 0.65 strictly forces UNCERTAIN_TRANSITIONAL."""
        for t_risk in [0.6500, 0.6501, 0.70, 0.85, 0.99, 1.00]:
            regime = reconcile_market_regime(
                kalman_z=2.5,
                trend_state="BULLISH_TREND",
                vol_percentile=0.30,
                vol_state=VolatilityState.NORMAL_MEDIUM,
                market_structure=MarketStructure.TRENDING,
                variance_ratio=1.40,
                ou_half_life=30.0,
                flow_mad_z=2.0,
                t_risk=t_risk,
                delta_flip=0.03,
                agreement_ratio=0.90,
                has_model_conflict=False,
            )
            assert regime == PrimaryRegime.UNCERTAIN_TRANSITIONAL, (
                f"T_risk={t_risk} failed to force UNCERTAIN_TRANSITIONAL (got {regime})"
            )

    def test_consensus_broken_and_conflict_fail_closed(self):
        """Assert agreement_ratio < 0.40 or has_model_conflict strictly forces UNCERTAIN_TRANSITIONAL."""
        for agree in [0.0, 0.10, 0.25, 0.3999]:
            regime = reconcile_market_regime(
                kalman_z=2.5,
                trend_state="BULLISH_TREND",
                vol_percentile=0.30,
                vol_state=VolatilityState.NORMAL_MEDIUM,
                market_structure=MarketStructure.TRENDING,
                variance_ratio=1.40,
                ou_half_life=30.0,
                flow_mad_z=2.0,
                t_risk=0.10,
                delta_flip=0.03,
                agreement_ratio=agree,
                has_model_conflict=False,
            )
            assert regime == PrimaryRegime.UNCERTAIN_TRANSITIONAL

        # Critical model conflict with high agreement ratio
        regime_conf = reconcile_market_regime(
            kalman_z=2.5,
            trend_state="BULLISH_TREND",
            vol_percentile=0.30,
            vol_state=VolatilityState.NORMAL_MEDIUM,
            market_structure=MarketStructure.TRENDING,
            variance_ratio=1.40,
            ou_half_life=30.0,
            flow_mad_z=2.0,
            t_risk=0.10,
            delta_flip=0.03,
            agreement_ratio=0.85,
            has_model_conflict=True,
        )
        assert regime_conf == PrimaryRegime.UNCERTAIN_TRANSITIONAL


# ============================================================================
# Task 4: Missing Data Handling & Zero-NaN Invariants
# ============================================================================


class TestMissingDataAndZeroNaNInvariants:
    """Stress-test missing options, short history, invalid prices, and assert zero NaNs."""

    def test_missing_options_chain_graceful_adaptation(self):
        """When options chain is None or empty, pipeline functions cleanly with 4 lenses, no NaNs."""
        bars = _make_synthetic_ohlcv(n=100, trend=0.001, vol=0.01)

        # 1. options_chain = None
        state_none = compute_unified_market_regime(symbol="AAPL", prices=bars, options_chain=None)
        assert state_none.quality.measurable is True
        assert state_none.quality.missing_lenses == ["Gamma Topography"]
        assert state_none.levels.gamma_flip is None
        assert state_none.levels.call_wall is None
        assert state_none.levels.put_wall is None
        assert 0.0 <= state_none.confidence <= 1.0
        assert math.isclose(sum(state_none.probabilities.to_dict().values()), 1.0000, abs_tol=1e-6)

        # Verify serialization has zero NaNs
        payload_none = state_none.to_dict()
        _assert_no_nan_recursive(payload_none)

        # 2. options_chain = empty DataFrame
        state_empty = compute_unified_market_regime(symbol="AAPL", prices=bars, options_chain=pd.DataFrame())
        assert state_empty.quality.measurable is True
        assert state_empty.quality.missing_lenses == ["Gamma Topography"]
        assert state_empty.levels.gamma_flip is None
        payload_empty = state_empty.to_dict()
        _assert_no_nan_recursive(payload_empty)

    def test_low_bar_history_unmeasurable_guarantee(self):
        """When price bar history is below 20 bars, pipeline strictly yields UNMEASURABLE with measurable=False."""
        for bar_count in [0, 1, 5, 10, 15, 19]:
            if bar_count == 0:
                bars = pd.DataFrame()
            else:
                bars = _make_synthetic_ohlcv(n=bar_count)

            state = compute_unified_market_regime(symbol="TEST", prices=bars)
            assert state.primary_regime == PrimaryRegime.UNMEASURABLE
            assert state.quality.measurable is False
            assert state.confidence == 0.0
            assert state.spot is None or bar_count == 0
            assert state.explainability.headline is not None
            assert "Withheld" in state.explainability.headline or "Unmeasurable" in state.explainability.headline

            # Serialized dictionary must not contain NaNs
            payload = state.to_dict()
            _assert_no_nan_recursive(payload)

    def test_corrupted_price_data_handling(self):
        """Test non-positive, all-NaN, or missing close column data cleanly produces UNMEASURABLE."""
        # 1. Missing close column
        df_no_close = pd.DataFrame({"open": [100.0] * 50, "high": [105.0] * 50})
        s1 = compute_unified_market_regime(symbol="TEST", prices=df_no_close)
        assert s1.primary_regime == PrimaryRegime.UNMEASURABLE
        assert s1.quality.measurable is False
        _assert_no_nan_recursive(s1.to_dict())

        # 2. Non-positive close prices (e.g. 0.0 or negative)
        bars_neg = _make_synthetic_ohlcv(n=50)
        bars_neg.loc[bars_neg.index[10], "close"] = -5.0
        s2 = compute_unified_market_regime(symbol="TEST", prices=bars_neg)
        assert s2.primary_regime == PrimaryRegime.UNMEASURABLE
        assert s2.quality.measurable is False
        _assert_no_nan_recursive(s2.to_dict())

        # 3. All NaN close prices
        bars_nan = _make_synthetic_ohlcv(n=50)
        bars_nan["close"] = np.nan
        s3 = compute_unified_market_regime(symbol="TEST", prices=bars_nan)
        assert s3.primary_regime == PrimaryRegime.UNMEASURABLE
        assert s3.quality.measurable is False
        _assert_no_nan_recursive(s3.to_dict())


class TestComprehensiveScenarioSimulations:
    """Stress-test 50 diverse market scenarios and verify regime diversity, schema validity, zero NaNs."""

    def test_500_randomized_conflict_monotonicity_trials(self):
        """Across 500 randomized trials, flipping an agreeing model to disagree strictly reduces consensus score A."""
        rng = np.random.default_rng(777)
        for _ in range(500):
            # Base aligned postures with same sign
            sign = 1.0 if rng.random() > 0.5 else -1.0
            base_scores = rng.uniform(0.4, 0.95, size=5) * sign
            
            postures = [
                ModelPosture(f"Model_{k}", float(base_scores[k]), int(np.sign(base_scores[k])), "raw", 1.0, "desc")
                for k in range(5)
            ]
            _, a_base, _ = build_agreement_matrix(postures)
            c_base = compute_calibrated_confidence(1.0, a_base, 1.0, 1.0, 0.1)

            # Flip one model to opposite sign
            flip_idx = rng.integers(0, 5)
            postures_flipped = list(postures)
            flipped_score = -float(base_scores[flip_idx])
            postures_flipped[flip_idx] = ModelPosture(
                f"Model_{flip_idx}", flipped_score, int(np.sign(flipped_score)), "raw", 1.0, "desc"
            )
            _, a_flipped, _ = build_agreement_matrix(postures_flipped)
            c_flipped = compute_calibrated_confidence(1.0, a_flipped, 1.0, 1.0, 0.1)

            assert a_flipped < a_base, f"Consensus score failed to strictly drop: a_flipped={a_flipped} >= a_base={a_base}"
            assert c_flipped < c_base, f"Confidence failed to strictly drop: c_flipped={c_flipped} >= c_base={c_base}"

    def test_50_diverse_end_to_end_market_scenarios(self):
        """Simulate 50 varied market regimes (trends, ranges, mean reversion, vol shocks, unmeasurable)."""
        rng = np.random.default_rng(20260902)
        regimes_observed = set()

        for seed in range(50):
            trend = rng.uniform(-0.005, 0.005)
            vol = rng.uniform(0.004, 0.04)
            n_bars = rng.integers(10, 180)
            bars = _make_synthetic_ohlcv(n=n_bars, trend=trend, vol=vol, seed=seed)

            # Synthetic options chain
            if rng.random() > 0.30 and n_bars >= 20:
                spot = float(bars["close"].iloc[-1])
                strikes = np.linspace(spot * 0.85, spot * 1.15, 20)
                calls = pd.DataFrame({
                    "strike": strikes,
                    "open_interest": rng.integers(100, 10000, size=20),
                    "implied_volatility": rng.uniform(0.15, 0.60, size=20),
                    "days_to_expiration": 15.0,
                    "option_type": "call",
                    "bid": 2.0,
                    "ask": 2.2,
                    "expiration": "2026-09-18",
                })
                puts = pd.DataFrame({
                    "strike": strikes,
                    "open_interest": rng.integers(100, 10000, size=20),
                    "implied_volatility": rng.uniform(0.15, 0.60, size=20),
                    "days_to_expiration": 15.0,
                    "option_type": "put",
                    "bid": 2.0,
                    "ask": 2.2,
                    "expiration": "2026-09-18",
                })
                chain = pd.concat([calls, puts], ignore_index=True)
            else:
                chain = None

            state = compute_unified_market_regime(symbol=f"SYM_{seed}", prices=bars, options_chain=chain)
            regimes_observed.add(state.primary_regime)

            # Invariants
            assert 0.0 <= state.confidence <= 1.0
            assert math.isclose(sum(state.probabilities.to_dict().values()), 1.0000, abs_tol=1e-6)
            assert state.explainability.headline is not None
            assert len(state.explainability.summary_text) > 0
            _assert_no_nan_recursive(state.to_dict())

        # Verify variety of regimes produced
        assert len(regimes_observed) >= 3


def _assert_no_nan_recursive(val: Any, path: str = "root") -> None:
    """Helper asserting no float NaN exists anywhere in nested dict/list structures."""
    if isinstance(val, float):
        assert not math.isnan(val), f"NaN detected at {path}"
    elif isinstance(val, dict):
        for k, v in val.items():
            _assert_no_nan_recursive(v, f"{path}.{k}")
    elif isinstance(val, list):
        for idx, item in enumerate(val):
            _assert_no_nan_recursive(item, f"{path}[{idx}]")
