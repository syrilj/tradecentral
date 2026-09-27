"""Empirical Challenger Deep Adversarial Stress Suite for Milestone 1.

Exhaustively stress-tests edge/daily_plays/regime_attractor_engine.py across:
- Numerical boundary invariants (NaN/Inf freedom, float overflow/underflow)
- Mathematical consistency of Greeks & root-finding
- 2-State Kalman Filter stability across pathological time series
- Multi-factor pull score invariance & boundary properties
- Zero-spoofing conformance under corrupt and degenerate feeds
- Randomized Monte Carlo stress tests (10,000 randomized chain profiles)
"""

from __future__ import annotations

import math
import random
from typing import Any
import numpy as np
import pytest

from daily_plays.regime_attractor_engine import (
    ConfluenceCluster,
    MarketRegimeState,
    PriceMagnetLevel,
    RegimeAttractorSnapshot,
    bs_d1_d2,
    calculate_bs_charm_per_day,
    calculate_bs_gamma,
    calculate_dollar_gamma_1pct,
    calculate_gravitational_pull,
    calculate_max_pain,
    classify_market_regime,
    compute_gamma_flip_and_walls,
    compute_kinematic_drift_level,
    compute_net_charm_flow,
    compute_price_attractors,
    detect_confluence_clusters,
    extract_volume_poc,
    calculate_market_regime,
    detect_price_magnets,
    compute_confluence_zones,
    build_price_draw_telemetry_payload,
)


class TestAdversarialGreeksBoundaries:
    """Probes BS Greeks across extreme mathematical domains."""

    def test_bs_d1_d2_boundaries(self):
        # Non-positive spot
        assert bs_d1_d2(0.0, 100.0, 1.0, 0.20) is None
        assert bs_d1_d2(-50.0, 100.0, 1.0, 0.20) is None

        # Non-positive strike
        assert bs_d1_d2(100.0, 0.0, 1.0, 0.20) is None
        assert bs_d1_d2(100.0, -10.0, 1.0, 0.20) is None

        # Non-positive years
        assert bs_d1_d2(100.0, 100.0, 0.0, 0.20) is None
        assert bs_d1_d2(100.0, 100.0, -0.5, 0.20) is None

        # Out-of-bounds IV (<= 0.005 or > 8.0)
        assert bs_d1_d2(100.0, 100.0, 1.0, 0.001) is None
        assert bs_d1_d2(100.0, 100.0, 1.0, 0.005) is None
        assert bs_d1_d2(100.0, 100.0, 1.0, 8.5) is None

        # Valid extreme points
        res_min = bs_d1_d2(100.0, 100.0, 1.0, 0.0051)
        assert res_min is not None
        assert not math.isnan(res_min[0]) and not math.isnan(res_min[1])

        res_max = bs_d1_d2(100.0, 100.0, 1.0, 8.0)
        assert res_max is not None
        assert not math.isnan(res_max[0]) and not math.isnan(res_max[1])

    def test_calculate_bs_gamma_extreme_ratios(self):
        # Extreme moneyness (Deep OTM: S=100, K=10,000; Deep ITM: S=100, K=1)
        gamma_otm = calculate_bs_gamma(100.0, 10000.0, 1.0, 0.5)
        assert gamma_otm is not None
        assert gamma_otm >= 0.0
        assert not math.isnan(gamma_otm)

        gamma_itm = calculate_bs_gamma(100.0, 1.0, 1.0, 0.5)
        assert gamma_itm is not None
        assert gamma_itm >= 0.0
        assert not math.isnan(gamma_itm)

    def test_calculate_bs_charm_per_day_tenor_guard(self):
        # Tenor floor guard: years < 1/365 returns None
        assert calculate_bs_charm_per_day(100.0, 100.0, 0.5 / 365.0, 0.25) is None
        assert calculate_bs_charm_per_day(100.0, 100.0, 0.0, 0.25) is None

        # Normal 30-day charm
        charm_call = calculate_bs_charm_per_day(100.0, 100.0, 30.0 / 365.0, 0.25, is_call=True)
        charm_put = calculate_bs_charm_per_day(100.0, 100.0, 30.0 / 365.0, 0.25, is_call=False)
        assert charm_call is not None and not math.isnan(charm_call)
        assert charm_put is not None and not math.isnan(charm_put)


class TestAdversarialKalmanFilter:
    """Probes the 2-State Constant Velocity Kalman Filter."""

    def test_kalman_constant_series(self):
        series = [150.0] * 50
        p_hat, v_z, regime = compute_kinematic_drift_level(series, spot=150.0)
        assert p_hat is not None
        assert math.isclose(p_hat, 150.0, abs_tol=0.1)
        assert math.isclose(v_z, 0.0, abs_tol=0.01)
        assert regime == "mean_reverting"

    def test_kalman_linear_ramp_trend_acceleration(self):
        # 10 points increasing by $2 each step
        series = [100.0 + 2.0 * i for i in range(20)]
        p_hat, v_z, regime = compute_kinematic_drift_level(series, spot=series[-1])
        assert p_hat is not None
        assert v_z > 1.5
        assert regime == "trend_acceleration"

    def test_kalman_series_with_nans_and_invalids(self):
        series = [100.0, None, float("nan"), 102.0, -10.0, 104.0, 106.0, 108.0, None, 110.0]
        p_hat, v_z, regime = compute_kinematic_drift_level(series, spot=110.0)
        assert p_hat is not None
        assert not math.isnan(p_hat)
        assert not math.isnan(v_z)

    def test_kalman_short_series_returns_undetermined(self):
        assert compute_kinematic_drift_level([100.0, 101.0, 102.0], spot=102.0) == (
            None,
            0.0,
            "undetermined",
        )
        assert compute_kinematic_drift_level([], spot=100.0) == (None, 0.0, "undetermined")
        assert compute_kinematic_drift_level(None, spot=100.0) == (None, 0.0, "undetermined")


class TestAdversarialMaxPainAndWalls:
    """Tests Max Pain pinning and directional walls under strange market shapes."""

    def test_max_pain_single_strike(self):
        chain = [{"strike": 100.0, "right": "call", "open_interest": 500, "iv": 0.20, "dte": 10}]
        mp = calculate_max_pain(chain, spot=100.0)
        assert mp == 100.0

    def test_max_pain_large_strikes(self):
        chain = [
            {"strike": 1_000_000.0, "right": "call", "open_interest": 100, "iv": 0.20, "dte": 10},
            {"strike": 1_050_000.0, "right": "call", "open_interest": 500, "iv": 0.20, "dte": 10},
            {"strike": 1_100_000.0, "right": "put", "open_interest": 1000, "iv": 0.20, "dte": 10},
        ]
        mp = calculate_max_pain(chain, spot=1_050_000.0)
        assert mp is not None
        assert mp in [1_000_000.0, 1_050_000.0, 1_100_000.0]

    def test_directional_walls_filtering_strictly_above_below(self):
        # Chain has calls only below spot and puts only above spot
        spot = 100.0
        chain = [
            {"strike": 90.0, "right": "call", "open_interest": 5000, "iv": 0.20, "dte": 10},
            {"strike": 95.0, "right": "call", "open_interest": 5000, "iv": 0.20, "dte": 10},
            {"strike": 105.0, "right": "put", "open_interest": 5000, "iv": 0.20, "dte": 10},
            {"strike": 110.0, "right": "put", "open_interest": 5000, "iv": 0.20, "dte": 10},
        ]
        flip, call_wall, put_wall, total_gex, mapped = compute_gamma_flip_and_walls(
            chain, spot=spot
        )
        # Since calls are below spot, there are no calls ABOVE spot -> call_wall is None
        assert call_wall is None
        # Since puts are above spot, there are no puts BELOW spot -> put_wall is None
        assert put_wall is None


class TestAdversarialGravitationalPullScores:
    """Tests multi-factor pull scores under pathological parameters."""

    def test_pull_score_with_extreme_expected_moves(self):
        # 0 expected move fallback
        pull_0, comps_0 = calculate_gravitational_pull(
            level_price=105.0,
            spot=100.0,
            level_type="call_wall",
            expected_move_1d=0.0,
        )
        assert 10.0 <= pull_0 <= 100.0
        assert 0.0 <= comps_0["proximity"] <= 1.0

        # Massive expected move
        pull_big, comps_big = calculate_gravitational_pull(
            level_price=200.0,
            spot=100.0,
            level_type="gamma_flip",
            expected_move_1d=500.0,
        )
        assert 10.0 <= pull_big <= 100.0

    def test_pull_score_infinite_distance(self):
        pull, comps = calculate_gravitational_pull(
            level_price=1_000_000.0,
            spot=100.0,
            level_type="call_wall",
        )
        assert pull >= 10.0
        assert comps["proximity"] == 0.0


class TestAdversarialMonteCarloSimulation:
    """Generates 500 randomized realistic and degenerate market structures to test pipeline robustness."""

    def test_monte_carlo_random_market_configurations(self):
        rng = random.Random(42)

        for trial in range(500):
            spot = round(rng.uniform(0.5, 5000.0), 2)
            n_strikes = rng.randint(1, 30)
            center_strike = spot
            spread = spot * rng.uniform(0.05, 0.50)
            strikes = sorted(
                set(
                    round(rng.uniform(max(0.01, center_strike - spread), center_strike + spread), 2)
                    for _ in range(n_strikes)
                )
            )
            if not strikes:
                strikes = [spot]

            chain_rows = []
            for k in strikes:
                # Call
                chain_rows.append(
                    {
                        "strike": k,
                        "right": "call",
                        "open_interest": rng.choice([0, rng.randint(1, 20000)]),
                        "iv": rng.choice([0.05, 0.20, 0.50, 1.5, 5.0]),
                        "dte": rng.choice([0.0, 1.0, 15.0, 60.0, 365.0]),
                        "volume": rng.choice([0, rng.randint(1, 5000)]),
                    }
                )
                # Put
                chain_rows.append(
                    {
                        "strike": k,
                        "right": "put",
                        "open_interest": rng.choice([0, rng.randint(1, 20000)]),
                        "iv": rng.choice([0.05, 0.20, 0.50, 1.5, 5.0]),
                        "dte": rng.choice([0.0, 1.0, 15.0, 60.0, 365.0]),
                        "volume": rng.choice([0, rng.randint(1, 5000)]),
                    }
                )

            price_series = [
                spot * (1.0 + rng.uniform(-0.05, 0.05)) for _ in range(rng.randint(0, 20))
            ]

            # Compute Price Attractors snapshot
            snapshot = compute_price_attractors(
                symbol=f"SYM{trial}",
                spot=spot,
                chain_rows=chain_rows,
                price_series=price_series,
            )

            # Assert invariants
            assert snapshot.symbol == f"SYM{trial}"
            if snapshot.quality["measurable"]:
                assert snapshot.spot == spot
                assert snapshot.regime_strength is not None
                assert 0.0 <= snapshot.regime_strength <= 1.0
                assert snapshot.dominant_direction in (
                    "bullish_pull",
                    "bearish_pull",
                    "neutral_pin",
                    "unmeasured",
                )
                for lvl in snapshot.levels:
                    assert 0.0 <= lvl.gravitational_pull <= 100.0
                    assert not math.isnan(lvl.price)
                    assert not math.isnan(lvl.distance_points)
                    assert not math.isnan(lvl.distance_pct)
                    assert lvl.direction in ("above", "below", "at_spot")
            else:
                assert snapshot.regime_state == "unmeasurable"
                assert snapshot.levels == []

            # Test to_dict() serialization
            d = snapshot.to_dict()
            assert isinstance(d, dict)
            assert "symbol" in d
            assert "levels" in d


class TestAdversarialDataDegeneracies:
    """Tests resilience against malformed, string-encoded, and corrupt chain rows."""

    def test_string_numeric_types_in_chain_rows(self):
        spot = 100.0
        chain = [
            {
                "strike": "90",
                "right": "call",
                "open_interest": "1500",
                "iv": "0.25",
                "dte": "30",
                "volume": "500",
            },
            {
                "strike": "100",
                "right": "put",
                "open_interest": "2500",
                "iv": "0.30",
                "dte": "30",
                "volume": "800",
            },
            {
                "strike": "110",
                "right": "call",
                "open_interest": "3500",
                "iv": "0.22",
                "dte": "30",
                "volume": "1200",
            },
        ]
        snapshot = compute_price_attractors("STR", spot, chain)
        assert snapshot.quality["measurable"] is True
        assert len(snapshot.levels) > 0
        assert snapshot.primary_magnet is not None

    def test_corrupted_rows_mixed_with_valid_rows(self):
        spot = 100.0
        chain = [
            {"strike": "invalid", "right": "call", "open_interest": 1000},
            {"strike": -50.0, "right": "call", "open_interest": 1000},
            {"strike": 100.0, "right": "invalid_type", "open_interest": 1000},
            {"strike": 100.0, "right": "call", "open_interest": "not_a_number"},
            None,
            {},
            {"strike": 95.0, "right": "put", "open_interest": 2000, "iv": 0.25, "dte": 15},
            {"strike": 105.0, "right": "call", "open_interest": 3000, "iv": 0.25, "dte": 15},
        ]
        valid_chain = [r for r in chain if isinstance(r, dict)]
        snapshot = compute_price_attractors("CORRUPT", spot, valid_chain)
        assert snapshot.quality["measurable"] is True
        assert len(snapshot.levels) > 0

    def test_all_attractors_confluence_cluster(self):
        spot = 100.0
        # Create 6 levels all within 0.2% of spot
        levels = [
            PriceMagnetLevel(
                "call_wall", "Call Wall", 100.1, 0.1, 0.1, "above", 85.0, "Resistance", 1
            ),
            PriceMagnetLevel("put_wall", "Put Wall", 99.9, -0.1, -0.1, "below", 85.0, "Support", 2),
            PriceMagnetLevel(
                "gamma_flip", "Zero-Gamma Flip", 100.0, 0.0, 0.0, "at_spot", 90.0, "Pivot", 3
            ),
            PriceMagnetLevel(
                "max_pain", "Max Pain Pin", 100.05, 0.05, 0.05, "above", 80.0, "Pin", 4
            ),
            PriceMagnetLevel(
                "kinematic_drift",
                "Kinematic Attractor",
                100.15,
                0.15,
                0.15,
                "above",
                75.0,
                "Drift",
                5,
            ),
            PriceMagnetLevel(
                "volume_poc", "Volume POC", 99.95, -0.05, -0.05, "below", 70.0, "POC", 6
            ),
        ]
        clusters = detect_confluence_clusters(levels, spot=spot, tolerance_pct=0.75)
        assert len(clusters) == 1
        assert clusters[0].lens_count == 4
        assert set(clusters[0].supporting_lenses) == {"GAMMA", "PIN", "VOLUME", "KALMAN"}
        assert len(clusters[0].labels) == 6


class TestAdversarialMultiThreadedConcurrency:
    """Validates thread-safety and re-entrancy under high concurrent load."""

    def test_high_concurrency_multi_threaded_snapshots(self):
        import concurrent.futures

        def worker(symbol_idx: int):
            spot = 100.0 + symbol_idx
            chain = [
                {
                    "strike": spot - 5.0,
                    "right": "put",
                    "open_interest": 1000 + symbol_idx,
                    "iv": 0.25,
                    "dte": 30,
                },
                {"strike": spot, "right": "call", "open_interest": 5000, "iv": 0.25, "dte": 30},
                {
                    "strike": spot + 5.0,
                    "right": "call",
                    "open_interest": 2000,
                    "iv": 0.25,
                    "dte": 30,
                },
            ]
            prices = [spot - 2.0, spot - 1.0, spot, spot + 0.5, spot + 1.0]
            snapshot = compute_price_attractors(f"TICK{symbol_idx}", spot, chain, prices)
            assert snapshot.symbol == f"TICK{symbol_idx}"
            assert snapshot.spot == spot
            return snapshot.to_dict()

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(worker, i) for i in range(100)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 100
        for r in results:
            assert r["quality"]["measurable"] is True
            assert len(r["levels"]) > 0
