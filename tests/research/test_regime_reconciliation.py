"""Unit and property tests for Layer 3 Reconciliation Engine & Calibrated Confidence."""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

from edge.research.regime_engine import (
    FlowContext,
    MarketStructure,
    ModelPosture,
    PrimaryRegime,
    RegimeProbabilities,
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


def _make_synthetic_bars(
    n: int = 100,
    trend: float = 0.001,
    vol: float = 0.01,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(loc=trend, scale=vol, size=n)
    close = 100.0 * np.cumprod(1.0 + rets)
    open_ = np.concatenate([[100.0], close[:-1]])
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


# ---------------------------------------------------------------------------
# 1. Probability Simplex Tests
# ---------------------------------------------------------------------------


def test_probability_simplex_sum_to_one_sweeps():
    """Verify p_bull + p_bear + p_neutral = 1.0000 across 500 randomized parameter sweeps."""
    rng = np.random.default_rng(12345)

    for _ in range(500):
        kalman_z = float(rng.uniform(-4.0, 4.0))
        flow_mad_z = float(rng.uniform(-4.0, 4.0))
        variance_ratio = float(rng.uniform(0.4, 2.5))
        net_gex = float(rng.uniform(-1e8, 1e8)) if rng.random() > 0.2 else None
        delta_flip = float(rng.uniform(-0.05, 0.05)) if rng.random() > 0.2 else None
        vol_pctile = float(rng.uniform(0.0, 1.0))
        vol_state = rng.choice(
            ["COMPRESSION_LOW", "NORMAL_MEDIUM", "ELEVATED_HIGH", "VOLATILITY_SHOCK"]
        )
        t_risk = float(rng.uniform(0.0, 1.0))
        a_models = float(rng.uniform(0.0, 1.0))

        probs = compute_regime_probabilities(
            kalman_z=kalman_z,
            flow_mad_z=flow_mad_z,
            variance_ratio=variance_ratio,
            net_gex_usd=net_gex,
            delta_flip=delta_flip,
            vol_percentile=vol_pctile,
            vol_state=vol_state,
            t_risk=t_risk,
            a_models=a_models,
        )

        total = probs.bullish + probs.bearish + probs.neutral
        assert pytest.approx(total, abs=1e-6) == 1.0000
        assert 0.0 <= probs.bullish <= 1.0
        assert 0.0 <= probs.bearish <= 1.0
        assert 0.0 <= probs.neutral <= 1.0


def test_temperature_scaling_entropy_expansion():
    """Verify Shannon entropy increases monotonically as transition risk increases."""
    # Strong bullish evidence
    kalman_z = 3.0
    flow_mad_z = 2.5
    variance_ratio = 1.5
    net_gex = 5e7
    delta_flip = 0.03
    vol_pctile = 0.40
    vol_state = "NORMAL_MEDIUM"
    a_models = 0.90

    t_risks = np.linspace(0.0, 1.0, 11)
    entropies = []

    for tr in t_risks:
        probs = compute_regime_probabilities(
            kalman_z=kalman_z,
            flow_mad_z=flow_mad_z,
            variance_ratio=variance_ratio,
            net_gex_usd=net_gex,
            delta_flip=delta_flip,
            vol_percentile=vol_pctile,
            vol_state=vol_state,
            t_risk=float(tr),
            a_models=a_models,
        )
        p_arr = np.array([probs.bullish, probs.bearish, probs.neutral])
        p_arr = p_arr[p_arr > 0]
        entropy = -np.sum(p_arr * np.log(p_arr))
        entropies.append(entropy)

    # Verify entropy increases strictly or non-decreasingly as T_risk spikes
    for i in range(len(entropies) - 1):
        assert entropies[i + 1] >= entropies[i] - 1e-4

    # Low risk should be highly concentrated (low entropy), high risk significantly higher entropy
    assert entropies[0] < entropies[-1]
    assert entropies[0] < 0.10
    assert entropies[-1] > 0.45

    # Under maximum uncertainty (T_risk=1.0 and A_models=0.0), distribution flattens toward uniform ln(3) ~ 1.0986
    probs_flat = compute_regime_probabilities(
        kalman_z=kalman_z,
        flow_mad_z=flow_mad_z,
        variance_ratio=variance_ratio,
        net_gex_usd=net_gex,
        delta_flip=delta_flip,
        vol_percentile=vol_pctile,
        vol_state=vol_state,
        t_risk=1.0,
        a_models=0.0,
    )
    p_flat = np.array([probs_flat.bullish, probs_flat.bearish, probs_flat.neutral])
    entropy_flat = -np.sum(p_flat[p_flat > 0] * np.log(p_flat[p_flat > 0]))
    assert entropy_flat > 0.65


# ---------------------------------------------------------------------------
# 2. Multi-Factor Calibrated Confidence Invariants
# ---------------------------------------------------------------------------


def test_calibrated_confidence_bounds_and_zero_collapse():
    """Verify multiplicative confidence C is in [0, 1] and strictly zero on any failure."""
    # Complete failure on boundary
    c_zero_bound = compute_calibrated_confidence(
        q_data=1.0, a_models=1.0, d_boundary=0.0, s_persistence=1.0, t_risk=0.0
    )
    assert c_zero_bound == 0.0

    # Complete failure on data completeness
    c_zero_data = compute_calibrated_confidence(
        q_data=0.0, a_models=1.0, d_boundary=1.0, s_persistence=1.0, t_risk=0.0
    )
    assert c_zero_data == 0.0

    # Complete failure on agreement
    c_zero_agree = compute_calibrated_confidence(
        q_data=1.0, a_models=0.0, d_boundary=1.0, s_persistence=1.0, t_risk=0.0
    )
    assert c_zero_agree == 0.0

    # Perfect alignment
    c_perfect = compute_calibrated_confidence(
        q_data=1.0, a_models=1.0, d_boundary=1.0, s_persistence=1.0, t_risk=0.0
    )
    assert pytest.approx(c_perfect, abs=1e-4) == 1.0

    # Maximum hazard haircut (50% reduction)
    c_max_hazard = compute_calibrated_confidence(
        q_data=1.0, a_models=1.0, d_boundary=1.0, s_persistence=1.0, t_risk=1.0
    )
    assert pytest.approx(c_max_hazard, abs=1e-4) == 0.50


def test_d_boundary_monotonicity():
    """Verify D_boundary collapses on flip boundary and increases away from it."""
    d_zero = compute_d_boundary(spot=500.0, gamma_flip=500.0, kalman_z=2.0)
    assert pytest.approx(d_zero, abs=1e-4) == 0.0

    d_band = compute_d_boundary(spot=500.0, gamma_flip=498.75, kalman_z=2.0)  # 0.25% distance
    assert 0.20 <= d_band <= 0.30

    d_far = compute_d_boundary(spot=500.0, gamma_flip=480.0, kalman_z=2.0)  # 4.0% distance
    assert d_far > 0.95

    assert d_zero < d_band < d_far


def test_s_persistence_and_whipsaw():
    """Verify S_persistence scales with tenure and penalizes whipsaw flips."""
    s_1 = compute_s_persistence(n_unbroken_bars=1, n_recent_flips=1)
    s_5 = compute_s_persistence(n_unbroken_bars=5, n_recent_flips=1)
    s_15 = compute_s_persistence(n_unbroken_bars=15, n_recent_flips=1)
    assert s_1 < s_5 < s_15
    assert pytest.approx(s_15, abs=0.01) == 1.0

    s_whip = compute_s_persistence(n_unbroken_bars=5, n_recent_flips=4)
    assert s_whip < s_5 * 0.5


# ---------------------------------------------------------------------------
# 3. 5x5 Multi-Model Agreement Matrix & Named Conflicts
# ---------------------------------------------------------------------------


def test_5x5_agreement_matrix_properties_and_conflicts():
    """Verify agreement matrix symmetry, unit diagonal, consensus score, and conflict detection."""
    # Postures: [Trend: Bull (+1.0), Gamma: Short (-1.0), Struct: Bull (+1.0), Flow: Bear (-1.0), Vol: Shock (-1.0)]
    postures = [1.0, -1.0, 1.0, -1.0, -1.0]
    mat, ratio, conflicts = build_agreement_matrix(
        postures=postures,
        vol_state="VOLATILITY_SHOCK",
        variance_ratio=1.4,
        ou_half_life=25.0,
    )

    # Symmetry
    assert np.allclose(mat, mat.T)
    # Unit diagonal
    assert np.allclose(np.diag(mat), 1.0)
    # Ratio in [0, 1]
    assert 0.0 <= ratio <= 1.0

    conflict_codes = [c.conflict_code for c in conflicts]
    assert "CONF_GAMMA_TREND" in conflict_codes
    assert "CONF_FLOW_PRICE" in conflict_codes
    assert "CONF_VOL_EXPANSION" in conflict_codes


# ---------------------------------------------------------------------------
# 4. Fail-Closed Triggers & Primary Regime Reconciliation
# ---------------------------------------------------------------------------


def test_fail_closed_flip_transition_band():
    """Verify spot inside flip band (|delta_flip| <= 0.25%) forces UNCERTAIN_TRANSITIONAL."""
    regime = reconcile_market_regime(
        kalman_z=2.0,
        trend_state="BULLISH_TREND",
        vol_percentile=0.40,
        vol_state=VolatilityState.NORMAL_MEDIUM,
        market_structure=MarketStructure.TRENDING,
        variance_ratio=1.40,
        ou_half_life=25.0,
        flow_mad_z=1.5,
        t_risk=0.10,
        delta_flip=0.0015,  # 0.15% < 0.25%
        agreement_ratio=0.85,
        has_model_conflict=False,
    )
    assert regime == PrimaryRegime.UNCERTAIN_TRANSITIONAL


def test_fail_closed_high_transition_hazard():
    """Verify T_risk >= 0.65 forces UNCERTAIN_TRANSITIONAL."""
    regime = reconcile_market_regime(
        kalman_z=2.0,
        trend_state="BULLISH_TREND",
        vol_percentile=0.40,
        vol_state=VolatilityState.NORMAL_MEDIUM,
        market_structure=MarketStructure.TRENDING,
        variance_ratio=1.40,
        ou_half_life=25.0,
        flow_mad_z=1.5,
        t_risk=0.75,  # High hazard >= 0.65
        delta_flip=0.02,
        agreement_ratio=0.85,
        has_model_conflict=False,
    )
    assert regime == PrimaryRegime.UNCERTAIN_TRANSITIONAL


def test_fail_closed_model_conflict_and_low_consensus():
    """Verify model conflict or A_models < 0.40 forces UNCERTAIN_TRANSITIONAL."""
    regime = reconcile_market_regime(
        kalman_z=2.0,
        trend_state="BULLISH_TREND",
        vol_percentile=0.40,
        vol_state=VolatilityState.NORMAL_MEDIUM,
        market_structure=MarketStructure.TRENDING,
        variance_ratio=1.40,
        ou_half_life=25.0,
        flow_mad_z=1.5,
        t_risk=0.10,
        delta_flip=0.02,
        agreement_ratio=0.35,  # < 0.40
        has_model_conflict=True,
    )
    assert regime == PrimaryRegime.UNCERTAIN_TRANSITIONAL


def test_deterministic_bullish_trend_reconciliation():
    """Verify agreeing bullish inputs yield BULLISH_TREND."""
    regime = reconcile_market_regime(
        kalman_z=1.8,
        trend_state="BULLISH_TREND",
        vol_percentile=0.45,
        vol_state=VolatilityState.NORMAL_MEDIUM,
        market_structure=MarketStructure.TRENDING,
        variance_ratio=1.35,
        ou_half_life=25.0,
        flow_mad_z=1.2,
        t_risk=0.15,
        delta_flip=0.03,
        agreement_ratio=0.85,
        has_model_conflict=False,
    )
    assert regime == PrimaryRegime.BULLISH_TREND


def test_deterministic_bearish_trend_reconciliation():
    """Verify agreeing bearish inputs yield BEARISH_TREND."""
    regime = reconcile_market_regime(
        kalman_z=-1.8,
        trend_state="BEARISH_TREND",
        vol_percentile=0.45,
        vol_state=VolatilityState.NORMAL_MEDIUM,
        market_structure=MarketStructure.TRENDING,
        variance_ratio=1.35,
        ou_half_life=25.0,
        flow_mad_z=-1.2,
        t_risk=0.15,
        delta_flip=-0.03,
        agreement_ratio=0.85,
        has_model_conflict=False,
    )
    assert regime == PrimaryRegime.BEARISH_TREND


def test_deterministic_compression_range_reconciliation():
    """Verify low vol percentile and flat velocity yield COMPRESSION_RANGE."""
    regime = reconcile_market_regime(
        kalman_z=0.1,
        trend_state="FLAT_NEUTRAL",
        vol_percentile=0.15,
        vol_state=VolatilityState.COMPRESSION_LOW,
        market_structure=MarketStructure.RANGE_BOUND,
        variance_ratio=1.0,
        ou_half_life=30.0,
        flow_mad_z=0.2,
        t_risk=0.05,
        delta_flip=0.02,
        agreement_ratio=0.80,
        has_model_conflict=False,
    )
    assert regime == PrimaryRegime.COMPRESSION_RANGE


def test_deterministic_mean_reverting_reconciliation():
    """Verify VR < 0.85 and low half-life yield MEAN_REVERTING."""
    regime = reconcile_market_regime(
        kalman_z=0.2,
        trend_state="FLAT_NEUTRAL",
        vol_percentile=0.50,
        vol_state=VolatilityState.NORMAL_MEDIUM,
        market_structure=MarketStructure.MEAN_REVERTING,
        variance_ratio=0.70,
        ou_half_life=6.0,
        flow_mad_z=0.0,
        t_risk=0.10,
        delta_flip=0.02,
        agreement_ratio=0.75,
        has_model_conflict=False,
    )
    assert regime == PrimaryRegime.MEAN_REVERTING


def test_deterministic_vol_expansion_breakout_reconciliation():
    """Verify vol shock and high velocity inside trending structure yield VOL_EXPANSION_BREAKOUT."""
    regime = reconcile_market_regime(
        kalman_z=2.2,
        trend_state="BULLISH_ACCELERATING",
        vol_percentile=0.95,
        vol_state=VolatilityState.VOLATILITY_SHOCK,
        market_structure=MarketStructure.TRENDING,
        variance_ratio=1.45,
        ou_half_life=30.0,
        flow_mad_z=2.5,
        t_risk=0.20,
        delta_flip=0.04,
        agreement_ratio=0.75,
        has_model_conflict=False,
    )
    assert regime == PrimaryRegime.VOL_EXPANSION_BREAKOUT


# ---------------------------------------------------------------------------
# 5. Full End-to-End Pipeline & Unmeasurable Honesty Tests
# ---------------------------------------------------------------------------


def test_unified_pipeline_end_to_end():
    """Verify compute_unified_market_regime executes end-to-end on synthetic bars."""
    bars = _make_synthetic_bars(n=120, trend=0.002, vol=0.008)
    state = compute_unified_market_regime(symbol="SPY", prices=bars)

    assert isinstance(state, UnifiedMarketState)
    assert state.symbol == "SPY"
    assert state.spot is not None and state.spot > 0
    assert state.primary_regime in PrimaryRegime
    assert 0.0 <= state.confidence <= 1.0
    assert pytest.approx(sum(state.probabilities.to_dict().values()), abs=1e-6) == 1.0000
    assert state.quality.measurable is True
    assert state.explainability.headline is not None
    assert len(state.explainability.leading_drivers) > 0


def test_unmeasurable_on_empty_and_short_data():
    """Verify empty or short data cleanly returns UNMEASURABLE with 0 confidence and honest explanation."""
    # Empty DataFrame
    s_empty = compute_unified_market_regime(symbol="SPY", prices=pd.DataFrame())
    assert s_empty.primary_regime == PrimaryRegime.UNMEASURABLE
    assert s_empty.confidence == 0.0
    assert s_empty.quality.measurable is False
    assert "Withheld" in s_empty.explainability.headline

    # Short bars (N = 10 < 20)
    bars_short = _make_synthetic_bars(n=10)
    s_short = compute_unified_market_regime(symbol="SPY", prices=bars_short)
    assert s_short.primary_regime == PrimaryRegime.UNMEASURABLE
    assert s_short.confidence == 0.0
    assert s_short.quality.measurable is False


def test_monotonic_gamma_profile_without_crossing():
    """Verify monotonic positive gamma (no flip root crossing) handles cleanly without crashing."""
    from edge.research.microstructure_regime import SharedLevels, _nearest_flip

    bars = _make_synthetic_bars(n=100, trend=0.001, vol=0.008)
    spot = float(bars["close"].iloc[-1])

    # Purely positive gamma across all spots (no zero crossing)
    monotonic_profile = [
        {"spot": spot * 0.90 + i * (spot * 0.20 / 20), "net_gex_m": 50.0 + i * 2.0}
        for i in range(21)
    ]
    flip = _nearest_flip(monotonic_profile, spot=spot)
    assert flip is None

    shared = SharedLevels(
        gex_profile=monotonic_profile,
        call_wall=spot * 1.05,
        put_wall=spot * 0.95,
    )

    state = compute_unified_market_regime(
        symbol="SPY",
        prices=bars,
        shared_levels=shared,
    )

    assert isinstance(state, UnifiedMarketState)
    assert state.levels.gamma_flip is None
    assert state.levels.call_wall == pytest.approx(spot * 1.05)
    assert state.levels.put_wall == pytest.approx(spot * 0.95)
    assert state.pillar_metrics is not None
    assert state.pillar_metrics["net_gex_m"] is not None and state.pillar_metrics["net_gex_m"] > 0
    assert state.primary_regime in PrimaryRegime


def test_shared_levels_adoption_and_interpolation():
    """Verify shared_levels profile and walls are adopted and interpolated when options_chain df is omitted."""
    from edge.research.microstructure_regime import SharedLevels

    bars = _make_synthetic_bars(n=100, trend=0.001, vol=0.008)
    spot = float(bars["close"].iloc[-1])

    # Profile crossing zero at spot * 0.98
    profile = [
        {"spot": spot * 0.90, "net_gex_m": -80.0},
        {"spot": spot * 0.98, "net_gex_m": 0.0},
        {"spot": spot * 1.10, "net_gex_m": 120.0},
    ]

    shared = SharedLevels(
        gex_profile=profile,
        call_wall=round(spot * 1.04, 2),
        put_wall=round(spot * 0.94, 2),
    )

    state = compute_unified_market_regime(
        symbol="SPY",
        prices=bars,
        shared_levels=shared,
    )

    assert state.levels.call_wall == pytest.approx(spot * 1.04, abs=0.05)
    assert state.levels.put_wall == pytest.approx(spot * 0.94, abs=0.05)
    assert state.levels.gamma_flip == pytest.approx(spot * 0.98, abs=0.05)
    assert state.pillar_metrics is not None
    assert state.pillar_metrics["net_gex_m"] is not None
    assert state.pillar_metrics["net_gex_m"] > 0  # spot > spot * 0.98 -> positive gamma


def test_shared_levels_with_empty_profile_and_walls():
    """Verify SharedLevels with empty profile still adopts call and put walls."""
    from edge.research.microstructure_regime import SharedLevels

    bars = _make_synthetic_bars(n=100)
    spot = float(bars["close"].iloc[-1])

    shared = SharedLevels(
        gex_profile=[],
        call_wall=550.0,
        put_wall=510.0,
    )

    state = compute_unified_market_regime(
        symbol="SPY",
        prices=bars,
        shared_levels=shared,
    )

    assert state.levels.call_wall == 550.0
    assert state.levels.put_wall == 510.0
    assert state.levels.gamma_flip is None
