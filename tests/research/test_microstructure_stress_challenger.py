"""Empirical stress-testing harness for Options Microstructure, Attractor Engine, and GEX Model.

Challenger 2 Empirical Verification:
1. Unipolar GEX curves (strictly positive or strictly negative gamma across all strikes).
2. 0DTE options at expiration (tau -> 0, dte <= 0, sub-minute tenors).
3. Extreme out-of-the-money options and wide strike grids with multiple sign crossings.
4. Gravitational pull score normalization and smooth Gaussian decay.
5. Black-Scholes scenario revaluation under +/-2% spot shocks and convexity shifts.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence
import numpy as np
import pandas as pd
import pytest

from edge.research.microstructure_regime import (
    bs_d1_d2,
    calculate_option_greeks,
    calculate_contract_gex,
    calculate_contract_vex,
    calculate_contract_chex,
    compute_microstructure_regime,
    _nearest_flip,
    _regime_strength,
    _directional_walls,
    _build_gex_profile,
    OptionGreeks,
    SharedLevels,
)
from edge.daily_plays.regime_attractor_engine import (
    calculate_bs_gamma,
    calculate_bs_charm_per_day,
    calculate_dollar_gamma_1pct,
    compute_gamma_flip_and_walls,
    classify_market_regime,
    calculate_gravitational_pull,
    compute_kinematic_drift_level,
    compute_net_charm_flow,
    detect_confluence_clusters,
    calculate_max_pain,
    PriceMagnetLevel,
    MarketRegimeState,
    _parse_chain_row,
)
from edge.research.gex_model import (
    _bs_gamma,
    compute_dollar_gamma,
    compute_unbiased_gex_profile,
    GammaExposureProfile,
)


# ============================================================================
# 1. UNIPOLAR GEX CURVES (Strictly positive or strictly negative)
# ============================================================================

class TestUnipolarGexCurves:
    """Stress tests on unipolar GEX curves without zero crossings."""

    def test_strictly_positive_gex_microstructure_regime(self):
        """When all strikes produce strictly positive dealer GEX (e.g. index with heavy call OI)."""
        spot = 500.0
        strikes = [480, 490, 500, 510, 520]
        # Calls only under index convention (phi_call = +1.0)
        chain = [
            {
                "strike": k,
                "right": "call",
                "open_interest": 10000,
                "volume": 1000,
                "implied_volatility": 0.20,
                "dte": 10,
            }
            for k in strikes
        ]

        snapshot = compute_microstructure_regime(chain, spot=spot, symbol="SPY", is_index=True)

        assert snapshot.quality.measurable is True
        assert snapshot.quality.flip_located is False
        assert snapshot.gamma_flip is None, "Unipolar positive GEX must have gamma_flip = None, not a fake level"
        assert snapshot.regime == "positive_gamma"
        assert snapshot.regime_strength > 0.0, f"Regime strength must be non-zero, got {snapshot.regime_strength}"
        assert snapshot.regime_strength <= 1.0
        assert snapshot.topography.quadrant == "unmeasurable", "Topography quadrant must be unmeasurable without a flip"
        assert snapshot.net_gex_m > 0.0

    def test_strictly_negative_gex_microstructure_regime(self):
        """When all strikes produce strictly negative dealer GEX (e.g. single stock or heavy puts)."""
        spot = 100.0
        strikes = [80, 90, 100, 110, 120]
        # Puts only under index convention (phi_put = -1.0)
        chain = [
            {
                "strike": k,
                "right": "put",
                "open_interest": 10000,
                "volume": 1000,
                "implied_volatility": 0.30,
                "dte": 10,
            }
            for k in strikes
        ]

        snapshot = compute_microstructure_regime(chain, spot=spot, symbol="AAPL", is_index=True)

        assert snapshot.quality.measurable is True
        assert snapshot.quality.flip_located is False
        assert snapshot.gamma_flip is None, "Unipolar negative GEX must have gamma_flip = None"
        assert snapshot.regime == "negative_gamma"
        assert snapshot.regime_strength > 0.0
        assert snapshot.regime_strength <= 1.0
        assert snapshot.topography.quadrant == "unmeasurable"
        assert snapshot.net_gex_m < 0.0

    def test_unipolar_curves_attractor_engine(self):
        """Test compute_gamma_flip_and_walls and classify_market_regime on unipolar profiles."""
        spot = 200.0
        # Only calls (positive GEX)
        chain_pos = [
            {"strike": 180, "right": "call", "oi": 5000, "iv": 0.25, "dte": 14},
            {"strike": 200, "right": "call", "oi": 15000, "iv": 0.25, "dte": 14},
            {"strike": 220, "right": "call", "oi": 8000, "iv": 0.25, "dte": 14},
        ]
        flip_pos, cw_pos, pw_pos, net_gex_pos, mapped_pos = compute_gamma_flip_and_walls(chain_pos, spot=spot)

        assert flip_pos is None, "Attractor engine must return gamma_flip = None for strictly positive GEX"
        assert cw_pos == 220.0, "Call wall above spot must be 220"
        assert pw_pos is None, "Put wall below spot must be None when no puts exist"
        assert net_gex_pos > 0.0

        regime_pos = classify_market_regime(spot=spot, total_net_gex_m=net_gex_pos, gamma_flip=flip_pos, mapped_strike_gex=mapped_pos)
        assert regime_pos.volatility_regime == "positive_gamma"
        assert regime_pos.volatility_behavior == "volatility_dampening"
        assert regime_pos.regime_strength > 0.0, "Regime strength must not collapse to 0.0 on uncrossed profile"
        assert regime_pos.topography_quadrant == "unmeasurable"

        # Only puts (negative GEX)
        chain_neg = [
            {"strike": 180, "right": "put", "oi": 10000, "iv": 0.25, "dte": 14},
            {"strike": 200, "right": "put", "oi": 12000, "iv": 0.25, "dte": 14},
            {"strike": 220, "right": "put", "oi": 4000, "iv": 0.25, "dte": 14},
        ]
        flip_neg, cw_neg, pw_neg, net_gex_neg, mapped_neg = compute_gamma_flip_and_walls(chain_neg, spot=spot)

        assert flip_neg is None
        assert cw_neg is None
        assert pw_neg == 180.0
        assert net_gex_neg < 0.0

        regime_neg = classify_market_regime(spot=spot, total_net_gex_m=net_gex_neg, gamma_flip=flip_neg, mapped_strike_gex=mapped_neg)
        assert regime_neg.volatility_regime == "negative_gamma"
        assert regime_neg.volatility_behavior == "volatility_amplification"
        assert regime_neg.regime_strength > 0.0
        assert regime_neg.topography_quadrant == "unmeasurable"


# ============================================================================
# 2. 0DTE OPTIONS AT EXPIRATION (tau -> 0)
# ============================================================================

class TestZeroDteExpirationLimits:
    """Stress tests on 0DTE options at expiry, avoiding NaN, Inf, or ZeroDivisionError."""

    @pytest.mark.parametrize("dte,years", [
        (0.0, 0.0),
        (0.0, -1.0),
        (0.0, 1e-12),
        (0.0001, 0.0001 / 365.25),
        (0.5, 0.5 / 365.25),
    ])
    def test_greeks_numerical_stability_near_expiry(self, dte: float, years: float):
        """Greeks calculation must be finite, stable, and free of division by zero."""
        spot = 450.0
        for strike in [400.0, 450.0, 500.0]:  # ITM, ATM, OTM
            for right in ["call", "put"]:
                greeks = calculate_option_greeks(
                    spot=spot,
                    strike=strike,
                    years=years,
                    iv=0.20,
                    right=right,
                )
                if greeks is not None:
                    assert math.isfinite(greeks.delta)
                    assert math.isfinite(greeks.gamma)
                    assert math.isfinite(greeks.theta)
                    assert math.isfinite(greeks.vega)
                    assert math.isfinite(greeks.rho)
                    assert math.isfinite(greeks.vanna)
                    assert math.isfinite(greeks.charm)
                    assert math.isfinite(greeks.speed)
                    assert math.isfinite(greeks.zomma)
                    assert greeks.gamma >= 0.0
                    assert greeks.vega >= 0.0

    def test_0dte_chain_microstructure_regime(self):
        """0DTE chain processing in compute_microstructure_regime."""
        spot = 500.0
        chain_0dte = [
            {"strike": 495.0, "right": "call", "open_interest": 5000, "volume": 12000, "iv": 0.15, "dte": 0.0},
            {"strike": 500.0, "right": "call", "open_interest": 20000, "volume": 35000, "iv": 0.15, "dte": 0.0},
            {"strike": 505.0, "right": "call", "open_interest": 8000, "volume": 15000, "iv": 0.15, "dte": 0.0},
            {"strike": 495.0, "right": "put", "open_interest": 9000, "volume": 18000, "iv": 0.18, "dte": 0.0},
            {"strike": 500.0, "right": "put", "open_interest": 18000, "volume": 40000, "iv": 0.18, "dte": 0.0},
            {"strike": 505.0, "right": "put", "open_interest": 4000, "volume": 9000, "iv": 0.18, "dte": 0.0},
        ]
        snapshot = compute_microstructure_regime(chain_0dte, spot=spot, symbol="QQQ")
        assert snapshot.quality.measurable is True
        assert math.isfinite(snapshot.net_gex_m)
        assert math.isfinite(snapshot.net_vex_m)
        assert math.isfinite(snapshot.net_chex_m)
        assert math.isfinite(snapshot.zero_dte_charm_drift_m)
        assert snapshot.zero_dte_charm_drift_m >= 0.0
        for s in snapshot.strikes:
            assert math.isfinite(s.call_gex_m)
            assert math.isfinite(s.put_gex_m)
            assert math.isfinite(s.net_gex_m)
            assert math.isfinite(s.speed_m)
            assert math.isfinite(s.zomma_m)

    def test_0dte_attractor_and_gex_model(self):
        """0DTE in regime attractor engine and gex_model."""
        spot = 100.0
        chain_rows = [
            {"strike": 95, "right": "call", "oi": 1000, "iv": 0.20, "dte": 0.0},
            {"strike": 100, "right": "call", "oi": 5000, "iv": 0.20, "dte": 0.0},
            {"strike": 105, "right": "put", "oi": 2000, "iv": 0.20, "dte": 0.0},
        ]
        flip, cw, pw, net_gex, _ = compute_gamma_flip_and_walls(chain_rows, spot=spot)
        assert math.isfinite(net_gex)

        df = pd.DataFrame([
            {"strike": 95, "option_type": "call", "open_interest": 1000, "iv": 0.20, "days_to_expiration": 0.0},
            {"strike": 100, "option_type": "call", "open_interest": 5000, "iv": 0.20, "days_to_expiration": 0.0},
            {"strike": 105, "option_type": "put", "open_interest": 2000, "iv": 0.20, "days_to_expiration": 0.0},
        ])
        profile = compute_unbiased_gex_profile(df, spot_price=spot)
        assert math.isfinite(profile.total_abs_gamma_usd)
        assert math.isfinite(profile.scenario_positive_gex_usd)
        assert math.isfinite(profile.scenario_negative_gex_usd)
        assert profile.total_abs_gamma_usd > 0.0


# ============================================================================
# 3. EXTREME OTM OPTIONS & MULTI-ROOT ZERO CROSSINGS
# ============================================================================

class TestExtremeStrikesAndMultiRootDisambiguation:
    """Stress tests on wide strike grids and multi-crossing flip selection."""

    def test_nearest_to_spot_flip_selection_microstructure(self):
        """Profile with multiple zero-crossings must select the root closest to spot."""
        # Synthetic profile crossing zero at 460, 490, 519, 547.5
        profile = [
            {"spot": 450.0, "net_gex_m": -10.0},
            {"spot": 470.0, "net_gex_m": 10.0},   # Crossing 1: ~460.0
            {"spot": 485.0, "net_gex_m": 5.0},
            {"spot": 495.0, "net_gex_m": -5.0},   # Crossing 2: ~490.0 (near spot 492)
            {"spot": 510.0, "net_gex_m": -8.0},
            {"spot": 525.0, "net_gex_m": 12.0},   # Crossing 3: ~519.0 (near spot 515)
            {"spot": 540.0, "net_gex_m": 6.0},
            {"spot": 560.0, "net_gex_m": -10.0},  # Crossing 4: ~547.5
        ]
        spot = 492.0
        flip = _nearest_flip(profile, spot=spot)
        assert flip is not None
        # Crossing 2 is at 485 + 10 * (5/10) = 490.0
        assert math.isclose(flip, 490.0, abs_tol=1.0), f"Expected flip near 490.0, got {flip}"

        # If spot moves to 515.0, flip should select crossing 3 (510 + 15 * 8/20 = 516.0)
        flip_515 = _nearest_flip(profile, spot=515.0)
        assert flip_515 is not None
        assert math.isclose(flip_515, 516.0, abs_tol=1.0)

    def test_nearest_to_spot_flip_selection_attractor_engine(self):
        """Attractor engine multi-crossing flip selection."""
        spot = 500.0
        chain = [
            {"strike": 400, "right": "put", "oi": 50000, "iv": 0.20, "dte": 30},
            {"strike": 450, "right": "call", "oi": 60000, "iv": 0.20, "dte": 30},
            {"strike": 490, "right": "put", "oi": 70000, "iv": 0.20, "dte": 30},
            {"strike": 510, "right": "call", "oi": 80000, "iv": 0.20, "dte": 30},
            {"strike": 550, "right": "put", "oi": 60000, "iv": 0.20, "dte": 30},
        ]
        flip, cw, pw, net_gex, mapped = compute_gamma_flip_and_walls(chain, spot=spot)
        assert flip is not None
        assert abs(flip - spot) < 30.0, f"Flip {flip} must be the one closest to spot {spot}"
        assert cw is not None and cw > spot, f"Call wall {cw} must be strictly > spot {spot}"
        assert pw is not None and pw < spot, f"Put wall {pw} must be strictly < spot {spot}"

    def test_extreme_otm_and_wide_strike_ranges(self):
        """Strikes from $0.01 to $1,000,000 on a $500 stock."""
        spot = 500.0
        chain = [
            {"strike": 0.01, "right": "put", "oi": 1000, "iv": 0.50, "dte": 30},
            {"strike": 10.0, "right": "put", "oi": 5000, "iv": 0.40, "dte": 30},
            {"strike": 490.0, "right": "put", "oi": 10000, "iv": 0.20, "dte": 30},
            {"strike": 500.0, "right": "call", "oi": 15000, "iv": 0.20, "dte": 30},
            {"strike": 510.0, "right": "call", "oi": 12000, "iv": 0.20, "dte": 30},
            {"strike": 10000.0, "right": "call", "oi": 500, "iv": 0.80, "dte": 30},
            {"strike": 1000000.0, "right": "call", "oi": 100, "iv": 1.50, "dte": 30},
        ]
        snapshot = compute_microstructure_regime(chain, spot=spot, symbol="NVDA")
        assert snapshot.quality.measurable is True
        assert math.isfinite(snapshot.net_gex_m)
        assert snapshot.call_wall is not None and snapshot.call_wall > spot
        assert snapshot.put_wall is not None and snapshot.put_wall < spot


# ============================================================================
# 4. GRAVITATIONAL PULL SCORE NORMALIZATION & SMOOTH DECAY
# ============================================================================

class TestGravitationalPullScoreProperties:
    """Stress tests on gravitational pull scores: bounds [0, 100] and Gaussian decay."""

    def test_pull_scores_stay_bounded(self):
        """Pull scores must remain strictly in [0.0, 100.0] under all extreme inputs."""
        spot = 100.0
        level_types = ["gamma_flip", "call_wall", "put_wall", "max_pain", "kinematic_drift", "volume_poc"]

        for level_type in level_types:
            for price in [0.01, 50.0, 99.0, 100.0, 101.0, 200.0, 10000.0]:
                for em in [None, 0.01, 1.0, 5.0, 50.0]:
                    for v_z in [-10.0, -2.0, 0.0, 2.0, 10.0]:
                        for drift in ["selling_drift", "buying_drift", "neutral_decay"]:
                            score, comp = calculate_gravitational_pull(
                                level_price=price,
                                spot=spot,
                                level_type=level_type,
                                expected_move_1d=em,
                                kinematic_velocity_z=v_z,
                                charm_drift_regime=drift,
                            )
                            assert 0.0 <= score <= 100.0, f"Score {score} out of bounds for {level_type} at {price}"
                            assert 0.0 <= comp["proximity"] <= 1.0
                            assert 0.0 <= comp["gex_mass"] <= 1.0
                            assert comp["alignment"] > 0.0

    def test_smooth_monotonic_decay_with_distance(self):
        """Pull score proximity must decay smoothly and monotonically as distance increases."""
        spot = 100.0
        em = 2.0  # 2% EM = $2.00
        distances = np.linspace(0.0, 20.0, 50)  # 0 to 10 EM
        proximities = []
        pull_scores = []

        for d in distances:
            price = spot + d
            score, comp = calculate_gravitational_pull(
                level_price=price,
                spot=spot,
                level_type="gamma_flip",
                expected_move_1d=em,
            )
            proximities.append(comp["proximity"])
            pull_scores.append(score)

        # Proximity must be strictly monotonically non-increasing
        for i in range(len(proximities) - 1):
            assert proximities[i] >= proximities[i + 1] - 1e-9, f"Proximity increased from {proximities[i]} to {proximities[i+1]}"

        # At d=0 (at spot), proximity is exactly 1.0
        assert math.isclose(proximities[0], 1.0, rel_tol=1e-5)
        # At d = 10 EM (d=20), proximity should be near 0 (exp(-0.5 * (10/2)^2) = exp(-12.5) ~ 3.7e-6)
        assert proximities[-1] < 1e-4

        # Pull score must be smoothly non-increasing
        for i in range(len(pull_scores) - 1):
            assert pull_scores[i] >= pull_scores[i + 1] - 1e-6


# ============================================================================
# 5. SCENARIO REVALUATION & BLACK-SCHOLES CONVEXITY SHIFTS
# ============================================================================

class TestScenarioRevaluationConvexity:
    """Verify non-linear Black-Scholes Greeks revaluation under +/-2% spot shocks."""

    def test_unbiased_gex_scenario_revaluation_convexity(self):
        """Verify scenario revaluation in research/gex_model.py under spot shocks."""
        spot = 100.0
        df_otm_call = pd.DataFrame([{
            "strike": 105.0,
            "option_type": "call",
            "open_interest": 10000,
            "days_to_expiration": 30.0,
            "implied_volatility": 0.20,
        }])

        profile = compute_unbiased_gex_profile(df_otm_call, spot_price=spot)
        base_gex = profile.total_abs_gamma_usd
        pos_gex = profile.scenario_positive_gex_usd
        neg_gex = profile.scenario_negative_gex_usd

        assert base_gex > 0.0
        assert pos_gex > 0.0
        assert neg_gex > 0.0

        # Non-linear check: pos_gex must not simply be base_gex * 1.02
        linear_scale_pos = base_gex * 1.02
        linear_scale_neg = base_gex * 0.98

        assert not math.isclose(pos_gex, linear_scale_pos, rel_tol=1e-3), (
            f"pos_gex {pos_gex} is identical to linear scale {linear_scale_pos}! "
            "Must be true Black-Scholes revaluation."
        )
        assert not math.isclose(neg_gex, linear_scale_neg, rel_tol=1e-3)

        # For OTM Call at 105 with spot moving 100 -> 102, gamma increases significantly
        tau = 30.0 / 365.25
        g_base = _bs_gamma(spot=100.0, strike=105.0, years=tau, iv=0.20)
        g_up = _bs_gamma(spot=102.0, strike=105.0, years=tau, iv=0.20)
        g_down = _bs_gamma(spot=98.0, strike=105.0, years=tau, iv=0.20)

        assert g_up > g_base > g_down, "Gamma must increase as spot moves towards OTM strike"
        dg_base = compute_dollar_gamma(10000, g_base, 100.0)
        dg_up = compute_dollar_gamma(10000, g_up, 102.0)
        dg_down = compute_dollar_gamma(10000, g_down, 98.0)

        assert math.isclose(base_gex, dg_base, rel_tol=1e-5)
        assert math.isclose(pos_gex, dg_up, rel_tol=1e-5)
        assert math.isclose(neg_gex, dg_down, rel_tol=1e-5)

    def test_gex_profile_black_scholes_spot_curve(self):
        """Verify _build_gex_profile revalues Gamma at each test spot."""
        spot = 500.0
        strike_map = {
            500.0: {
                "strike": 500.0,
                "call_oi": 10000,
                "put_oi": 10000,
                "call_iv": 0.20,
                "put_iv": 0.20,
                "call_years": 30.0 / 365.25,
                "put_years": 30.0 / 365.25,
            }
        }
        profile = _build_gex_profile(
            strike_map=strike_map,
            sorted_strikes=[500.0],
            spot=spot,
            rate=0.045,
            phi_call=1.0,
            phi_put=-1.0,
        )
        assert len(profile) == 50
        for pt in profile:
            assert math.isclose(pt["net_gex_m"], 0.0, abs_tol=1e-3)


# ============================================================================
# 6. MONTE CARLO RANDOM FUZZING & CORRUPTED DATA RESILIENCE
# ============================================================================

class TestAdversarialFuzzingAndCorruptedData:
    """Stress tests across randomized chain topologies and corrupted inputs."""

    def test_monte_carlo_random_chain_fuzzing(self):
        """Generate 100 randomized chains across varied strikes, OIs, IVs, and tenors."""
        np.random.seed(42)
        for _ in range(100):
            spot = float(np.random.uniform(1.0, 5000.0))
            num_strikes = int(np.random.randint(3, 40))
            strike_spread = float(np.random.uniform(0.1, 0.5)) * spot
            strikes = np.linspace(max(0.01, spot - strike_spread), spot + strike_spread, num_strikes)
            
            chain = []
            for k in strikes:
                chain.append({
                    "strike": float(k),
                    "right": "call",
                    "open_interest": int(np.random.randint(0, 50000)),
                    "volume": int(np.random.randint(0, 10000)),
                    "iv": float(np.random.uniform(0.05, 1.50)),
                    "dte": float(np.random.uniform(0.0, 365.0)),
                })
                chain.append({
                    "strike": float(k),
                    "right": "put",
                    "open_interest": int(np.random.randint(0, 50000)),
                    "volume": int(np.random.randint(0, 10000)),
                    "iv": float(np.random.uniform(0.05, 1.50)),
                    "dte": float(np.random.uniform(0.0, 365.0)),
                })

            snapshot = compute_microstructure_regime(chain, spot=spot, symbol="FUZZ")
            assert snapshot.quality.measurable is True
            assert math.isfinite(snapshot.net_gex_m)
            assert 0.0 <= snapshot.regime_strength <= 1.0
            if snapshot.gamma_flip is not None:
                assert math.isfinite(snapshot.gamma_flip)
                assert snapshot.gamma_flip > 0

    def test_corrupted_rows_and_missing_data_resilience(self):
        """Chains with corrupted strings, NaNs, missing fields, and zero OI."""
        spot = 100.0
        corrupted_chain = [
            {"strike": "invalid", "right": "call", "oi": "NaN"},
            {"strike": None, "right": "call"},
            {"strike": -50.0, "right": "call", "oi": 1000},
            {"strike": 100.0, "right": "unknown_side", "oi": 1000},
            {"strike": 100.0, "right": "call", "open_interest": 0, "volume": 0},
            {"strike": 100.0, "right": "put", "open_interest": 0, "volume": 0},
        ]
        snapshot = compute_microstructure_regime(corrupted_chain, spot=spot, symbol="CORRUPT")
        assert snapshot.quality.measurable is False
        assert snapshot.regime == "unmeasurable"
        assert snapshot.gamma_flip is None


# ============================================================================
# 7. MULTI-THREADED CONCURRENCY VERIFICATION
# ============================================================================

class TestMultiThreadedEvaluation:
    """Ensure thread safety of Black-Scholes and Attractor engine calculations."""

    def test_concurrent_execution(self):
        import concurrent.futures

        def worker(spot: float):
            chain = [
                {"strike": spot * 0.95, "right": "put", "oi": 5000, "iv": 0.20, "dte": 14},
                {"strike": spot, "right": "call", "oi": 10000, "iv": 0.20, "dte": 14},
                {"strike": spot * 1.05, "right": "call", "oi": 8000, "iv": 0.20, "dte": 14},
            ]
            s = compute_microstructure_regime(chain, spot=spot, symbol="THREAD")
            f, cw, pw, g, _ = compute_gamma_flip_and_walls(chain, spot=spot)
            return s.quality.measurable, math.isfinite(s.net_gex_m), f is not None or f is None

        spots = [50.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0] * 5
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(worker, spots))

        assert len(results) == len(spots)
        for m, finite_gex, valid_flip in results:
            assert m is True
            assert finite_gex is True

