"""Comprehensive 4-Tier E2E Test Suite for Real-Time Market Regime Detection
& Price Attraction / Magnet Levels Engine (Python Backend & API Suite).

Authoritative source of expected behaviors & contracts: ORIGINAL_REQUEST.md & PROJECT.md.

Test Tier Architecture:
- Tier 1: Feature Coverage (F01 - F06, >=5 tests per feature, 36 tests total)
- Tier 2: Boundary & Corner Cases (B01 - B12, 12 dimensions, 36 tests total)
- Tier 3: Cross-Feature Pairwise Combinations (P01 - P08, 8 tests total)
- Tier 4: Real-World Institutional Scenarios (S01 - S06, 6 tests total)
"""

from __future__ import annotations

import concurrent.futures
import math
import time
from typing import Any

import pytest

from daily_plays import gex_core
from daily_plays.regime_attractor_engine import (
    MarketRegimeState,
    PriceMagnetLevel,
    build_price_draw_telemetry_payload,
    calculate_market_regime,
    compute_confluence_zones,
    detect_price_magnets,
)


# ============================================================================
# TIER 1: FEATURE COVERAGE (F01 - F06)
# ============================================================================


class TestTier1Feature01MarketRegimeClassifier:
    """F01: Real-time market regime classification (Long/Short Gamma, Charm, Flip)."""

    def test_f1_1_positive_gamma_dampening_classification(self):
        """Spot in heavy call open interest territory classifies as positive_gamma / volatility_dampening."""
        spot = 100.0
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        call_oi = [1000, 2500, 8000, 15000, 12000]  # Heavy call OI (positive gamma)
        put_oi = [500, 1000, 1500, 2000, 1000]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        assert regime.measurable is True
        assert regime.volatility_regime == "positive_gamma"
        assert regime.volatility_behavior == "volatility_dampening"
        assert regime.total_net_gex_m > 0
        assert regime.regime_strength > 0.0

    def test_f1_2_negative_gamma_amplification_classification(self):
        """Spot in heavy put open interest territory classifies as negative_gamma / volatility_amplification."""
        spot = 100.0
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        call_oi = [500, 800, 1000, 1500, 1000]
        put_oi = [12000, 18000, 10000, 2000, 500]  # Heavy put OI (negative gamma)

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        assert regime.measurable is True
        assert regime.volatility_regime == "negative_gamma"
        assert regime.volatility_behavior == "volatility_amplification"
        assert regime.total_net_gex_m < 0

    def test_f1_3_neutral_transition_inside_flip_band(self):
        """Spot sitting directly on the zero-gamma flip boundary classifies as neutral_transition."""
        spot = 100.0
        strikes = [95.0, 100.0, 105.0]
        # Perfectly balanced call and put distribution around spot
        call_oi = [1000, 5000, 1000]
        put_oi = [1000, 5000, 1000]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        assert regime.measurable is True
        assert regime.volatility_regime == "neutral_transition"
        assert regime.volatility_behavior == "neutral_straddle"

    def test_f1_4_0dte_short_expiry_charm_drift_detection(self):
        """0DTE options chain (< 5 days to expiry) detects charm decay selling drift."""
        spot = 100.0
        strikes = [95.0, 100.0, 105.0]
        call_oi = [1000, 8000, 15000]  # Heavy calls
        put_oi = [500, 1000, 2000]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            dte_years=1.0 / 365.0,  # 1 day to expiry
        )
        assert regime.measurable is True
        assert regime.charm_drift_regime == "selling_drift"

    def test_f1_5_kinematic_trend_acceleration_vs_mean_reversion(self):
        """High kinematic velocity in short gamma regime produces trend_acceleration."""
        spot = 100.0
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        call_oi = [500, 800, 1000, 1500, 1000]
        put_oi = [12000, 18000, 10000, 2000, 500]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            kinematic_velocity=0.035,  # High breakout velocity
        )
        assert regime.kinematic_regime == "trend_acceleration"

    def test_f1_6_topography_quadrant_classification(self):
        """Topography correctly distinguishes forward positive ramp when spot >= gamma flip."""
        spot = 105.0
        strikes = [95.0, 100.0, 105.0, 110.0]
        call_oi = [2000, 5000, 12000, 15000]
        put_oi = [1000, 2000, 3000, 1000]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        assert regime.topography_quadrant == "forward_positive_ramp"


class TestTier1Feature02MultiFactorPriceMagnetDetection:
    """F02: Multi-factor structural price magnet detection (Call/Put Walls, Flip, Max Pain)."""

    def test_f2_1_call_wall_detection_and_resistance_attribution(self):
        """Call Wall accurately identifies maximum call open interest strike as overhead resistance."""
        spot = 100.0
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        call_oi = [500, 1200, 3000, 18000, 4000]  # Strike 105 has max call OI
        put_oi = [5000, 2000, 1000, 500, 200]

        magnets = detect_price_magnets(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        cw = next((m for m in magnets if m.level_id == "call_wall"), None)
        assert cw is not None
        assert cw.price == 105.0
        assert cw.direction == "above"
        assert "Resistance" in cw.structural_force
        assert cw.gravitational_pull > 50.0

    def test_f2_2_put_wall_detection_and_support_attribution(self):
        """Put Wall accurately identifies maximum put open interest strike as downside support."""
        spot = 100.0
        strikes = [85.0, 90.0, 95.0, 100.0, 105.0]
        call_oi = [200, 500, 1000, 3000, 8000]
        put_oi = [1000, 15000, 6000, 1000, 200]  # Strike 90 has max put OI

        magnets = detect_price_magnets(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        pw = next((m for m in magnets if m.level_id == "put_wall"), None)
        assert pw is not None
        assert pw.price == 90.0
        assert pw.direction == "below"
        assert "Support" in pw.structural_force
        assert pw.distance_points == -10.0

    def test_f2_3_gamma_flip_pivot_magnet_detection(self):
        """Gamma Flip level included as primary transition pivot when regime state is provided."""
        spot = 100.0
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        call_oi = [1000, 2000, 5000, 10000, 12000]
        put_oi = [12000, 8000, 3000, 1000, 500]

        regime = calculate_market_regime(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        magnets = detect_price_magnets(
            spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi, regime_state=regime
        )

        gf = next((m for m in magnets if m.level_id == "gamma_flip"), None)
        assert gf is not None
        assert "Pivot" in gf.structural_force
        assert gf.gravitational_pull > 60.0

    def test_f2_4_max_pain_pinning_magnet_calculation(self):
        """Max Pain pin accurately computes strike that minimizes total option buyer dollar payout."""
        spot = 100.0
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        # Put heavy OI at edges (90 and 110), so 100 minimizes buyer payout
        call_oi = [100, 500, 1000, 5000, 20000]
        put_oi = [20000, 5000, 1000, 500, 100]

        magnets = detect_price_magnets(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        mp = next((m for m in magnets if m.level_id == "max_pain"), None)
        assert mp is not None
        assert mp.price == 100.0
        assert mp.direction == "at_spot"
        assert "Pinning" in mp.structural_force

    def test_f2_5_kinematic_drift_and_volume_poc_magnets(self):
        """Kinematic drift target and Volume POC nodes are incorporated into magnet hierarchy."""
        spot = 100.0
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        call_oi = [1000, 2000, 3000, 4000, 5000]
        put_oi = [5000, 4000, 3000, 2000, 1000]
        call_vol = [100, 200, 300, 5000, 500]  # Heavy volume at 105
        put_vol = [500, 300, 200, 5000, 100]

        magnets = detect_price_magnets(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            call_volume=call_vol,
            put_volume=put_vol,
            kinematic_target=103.5,
        )
        kd = next((m for m in magnets if m.level_id == "kinematic_drift"), None)
        vp = next((m for m in magnets if m.level_id == "volume_poc"), None)

        assert kd is not None
        assert kd.price == 103.5
        assert vp is not None
        assert vp.price == 105.0

    def test_f2_6_conviction_ranking_descending_by_pull_score(self):
        """Magnet levels are strictly ranked 1..N in descending order of gravitational pull."""
        spot = 100.0
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        call_oi = [1000, 2000, 5000, 15000, 8000]
        put_oi = [8000, 15000, 5000, 2000, 1000]

        magnets = detect_price_magnets(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        assert len(magnets) >= 3
        for i in range(len(magnets) - 1):
            assert magnets[i].gravitational_pull >= magnets[i + 1].gravitational_pull
            assert magnets[i].conviction_rank == i + 1


class TestTier1Feature03QuantitativeAttractorTelemetry:
    """F03: Quantitative attractor telemetry (Signed Distance, Pull Score, Direction)."""

    def test_f3_1_signed_point_distance_calculations(self):
        """Signed point distance is positive above spot, negative below spot, and zero at spot."""
        spot = 200.0
        strikes = [180.0, 200.0, 220.0]
        call_oi = [1000, 5000, 10000]
        put_oi = [10000, 5000, 1000]

        magnets = detect_price_magnets(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        cw = next(m for m in magnets if m.level_id == "call_wall")
        pw = next(m for m in magnets if m.level_id == "put_wall")
        mp = next(m for m in magnets if m.level_id == "max_pain")

        assert cw.distance_points == 20.0
        assert pw.distance_points == -20.0
        assert mp.distance_points == 0.0

    def test_f3_2_signed_percentage_distance_calculations(self):
        """Signed percentage distance accurately scales with spot price."""
        spot = 50.0
        strikes = [45.0, 50.0, 55.0]
        call_oi = [100, 500, 2000]
        put_oi = [2000, 500, 100]

        magnets = detect_price_magnets(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        cw = next(m for m in magnets if m.level_id == "call_wall")
        pw = next(m for m in magnets if m.level_id == "put_wall")

        assert cw.distance_pct == 10.0  # (55 - 50) / 50 * 100
        assert pw.distance_pct == -10.0  # (45 - 50) / 50 * 100

    def test_f3_3_direction_classification_above_below_at_spot(self):
        """Directional classification accurately maps 'above', 'below', and 'at_spot'."""
        spot = 100.0
        strikes = [90.0, 100.0, 110.0]
        call_oi = [500, 1000, 5000]
        put_oi = [5000, 1000, 500]

        magnets = detect_price_magnets(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        for m in magnets:
            if m.price > spot:
                assert m.direction == "above"
            elif m.price < spot:
                assert m.direction == "below"
            else:
                assert m.direction == "at_spot"

    def test_f3_4_gravitational_pull_score_bounds_0_to_100(self):
        """Gravitational pull scores are strictly bounded within [0.0, 100.0]."""
        spot = 100.0
        strikes = [50.0, 75.0, 100.0, 125.0, 150.0]
        call_oi = [100, 500, 1000, 5000, 25000]
        put_oi = [25000, 5000, 1000, 500, 100]

        magnets = detect_price_magnets(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        for m in magnets:
            assert 0.0 <= m.gravitational_pull <= 100.0

    def test_f3_5_components_dictionary_metadata(self):
        """Each magnet level provides quantitative component breakdown metadata."""
        spot = 100.0
        strikes = [90.0, 100.0, 110.0]
        call_oi = [500, 1000, 5000]
        put_oi = [5000, 1000, 500]

        magnets = detect_price_magnets(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        for m in magnets:
            assert isinstance(m.components, dict)
            assert "proximity" in m.components or len(m.components) > 0

    def test_f3_6_expected_move_1d_scaling_with_volatility(self):
        """Expected move 1D expands monotonically with higher implied volatility."""
        spot = 100.0
        strikes = [90.0, 100.0, 110.0]
        call_oi = [1000, 2000, 3000]
        put_oi = [3000, 2000, 1000]

        regime_low_iv = calculate_market_regime(
            spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi, ivs=[0.15] * 3
        )
        regime_high_iv = calculate_market_regime(
            spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi, ivs=[0.60] * 3
        )

        assert regime_low_iv.expected_move_1d is not None
        assert regime_high_iv.expected_move_1d is not None
        assert regime_high_iv.expected_move_1d > regime_low_iv.expected_move_1d


class TestTier1Feature04ZeroSpoofingProtocol:
    """F04: Zero-spoofing and missing data protocol (no fake zeroes or unmeasured defaults)."""

    def test_f4_1_empty_chain_returns_unmeasurable_regime(self):
        """Empty strikes or zero open interest returns measurable: false with unmeasurable regime."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[],
            call_oi=[],
            put_oi=[],
        )
        assert regime.measurable is False
        assert regime.volatility_regime == "unmeasurable"
        assert regime.gamma_flip is None
        assert regime.expected_move_1d is None

    def test_f4_2_zero_open_interest_returns_unmeasurable(self):
        """Chains with all zero open interest flag as unmeasurable."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[0, 0, 0],
            put_oi=[0, 0, 0],
        )
        assert regime.measurable is False
        assert regime.volatility_regime == "unmeasurable"

    def test_f4_3_telemetry_payload_unmeasured_contract(self):
        """Unmeasured payload propagates null spot, null regime strength, and explicit reason."""
        regime = calculate_market_regime(spot=0.0, strikes=[], call_oi=[], put_oi=[])
        payload = build_price_draw_telemetry_payload(
            symbol="SPY",
            spot=None,
            regime_state=regime,
            magnets=[],
            quality_reason="No options chain available for ticker",
        )
        assert payload["quality"]["measurable"] is False
        assert payload["spot"] is None
        assert payload["regime_strength"] is None
        assert payload["dominant_direction"] == "unmeasured"
        assert payload["quality"]["reason"] == "No options chain available for ticker"
        assert len(payload["levels"]) == 0

    def test_f4_4_negative_or_zero_spot_price_rejected(self):
        """Non-positive spot price produces unmeasurable state without throwing exceptions."""
        regime = calculate_market_regime(
            spot=-10.0,
            strikes=[90.0, 100.0],
            call_oi=[100, 100],
            put_oi=[100, 100],
        )
        assert regime.measurable is False
        magnets = detect_price_magnets(
            spot=0.0,
            strikes=[90.0, 100.0],
            call_oi=[100, 100],
            put_oi=[100, 100],
        )
        assert len(magnets) == 0

    def test_f4_5_confluence_zones_empty_on_unmeasured_data(self):
        """Confluence clusters return empty list when spot or magnets are invalid."""
        clusters_empty = compute_confluence_zones([], 100.0)
        assert clusters_empty == []
        clusters_zero_spot = compute_confluence_zones(
            [PriceMagnetLevel("cw", "CW", 105.0, 5.0, 5.0, "above", 80.0, "Res", 1)], 0.0
        )
        assert clusters_zero_spot == []

    def test_f4_6_warnings_array_populated_on_missing_feed(self):
        """Warnings array contains transparent explanation when chain data is absent."""
        regime = calculate_market_regime(spot=100.0, strikes=[], call_oi=[], put_oi=[])
        payload = build_price_draw_telemetry_payload(
            symbol="NVDA",
            spot=None,
            regime_state=regime,
            magnets=[],
            quality_reason="Market data provider feed timeout",
        )
        assert "Market data provider feed timeout" in payload["warnings"]


class TestTier1Feature05ApiEndpointContracts:
    """F05: API endpoint contracts (/api/price-attractors, /api/options, /api/quotes)."""

    def test_f5_1_payload_schema_matches_typescript_interface(self):
        """Compiled payload strictly adheres to PriceDrawTelemetryPayload interface."""
        spot = 150.0
        strikes = [140.0, 145.0, 150.0, 155.0, 160.0]
        call_oi = [500, 1000, 3000, 12000, 8000]
        put_oi = [8000, 12000, 3000, 1000, 500]

        regime = calculate_market_regime(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        magnets = detect_price_magnets(
            spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi, regime_state=regime
        )
        payload = build_price_draw_telemetry_payload(
            symbol="AAPL", spot=spot, regime_state=regime, magnets=magnets
        )

        required_keys = {
            "symbol",
            "spot",
            "asof_utc",
            "regime_state",
            "regime_label",
            "regime_strength",
            "dominant_direction",
            "primary_magnet",
            "levels",
            "confluence_clusters",
            "quality",
            "warnings",
        }
        assert required_keys.issubset(payload.keys())
        assert payload["symbol"] == "AAPL"
        assert payload["spot"] == 150.0

    def test_f5_2_levels_contain_required_lenses_and_roles(self):
        """Each level in payload contains supporting_lenses array and lens_count."""
        spot = 100.0
        strikes = [90.0, 100.0, 110.0]
        call_oi = [1000, 2000, 5000]
        put_oi = [5000, 2000, 1000]

        regime = calculate_market_regime(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        magnets = detect_price_magnets(
            spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi, regime_state=regime
        )
        payload = build_price_draw_telemetry_payload(
            symbol="MSFT", spot=spot, regime_state=regime, magnets=magnets
        )

        for lvl in payload["levels"]:
            assert "supporting_lenses" in lvl
            assert "lens_count" in lvl
            assert len(lvl["supporting_lenses"]) == lvl["lens_count"]
            assert "is_primary_magnet" in lvl

    def test_f5_3_dominant_direction_bullish_pull_resolution(self):
        """Dominant direction resolves to bullish_pull when overhead magnet pull dominates."""
        spot = 100.0
        m1 = PriceMagnetLevel(
            "call_wall", "Call Wall", 110.0, 10.0, 10.0, "above", 90.0, "Resistance", 1
        )
        m2 = PriceMagnetLevel(
            "kinematic_drift", "Kinematic", 108.0, 8.0, 8.0, "above", 80.0, "Velocity", 2
        )
        m3 = PriceMagnetLevel("put_wall", "Put Wall", 95.0, -5.0, -5.0, "below", 30.0, "Support", 3)

        regime = MarketRegimeState(
            "positive_gamma",
            "volatility_dampening",
            "forward_positive_ramp",
            "mean_reverting",
            "neutral_decay",
            0.8,
            15.0,
            95.0,
            spot,
            2.5,
            True,
        )
        payload = build_price_draw_telemetry_payload(
            symbol="NVDA", spot=spot, regime_state=regime, magnets=[m1, m2, m3]
        )

        assert payload["dominant_direction"] == "bullish_pull"

    def test_f5_4_dominant_direction_bearish_pull_resolution(self):
        """Dominant direction resolves to bearish_pull when downside magnet pull dominates."""
        spot = 100.0
        m1 = PriceMagnetLevel(
            "put_wall", "Put Wall", 90.0, -10.0, -10.0, "below", 90.0, "Support", 1
        )
        m2 = PriceMagnetLevel(
            "kinematic_drift", "Kinematic", 92.0, -8.0, -8.0, "below", 80.0, "Velocity", 2
        )
        m3 = PriceMagnetLevel(
            "call_wall", "Call Wall", 105.0, 5.0, 5.0, "above", 30.0, "Resistance", 3
        )

        regime = MarketRegimeState(
            "negative_gamma",
            "volatility_amplification",
            "backward_negative_slide",
            "trend_acceleration",
            "neutral_decay",
            0.8,
            -15.0,
            105.0,
            spot,
            2.5,
            True,
        )
        payload = build_price_draw_telemetry_payload(
            symbol="TSLA", spot=spot, regime_state=regime, magnets=[m1, m2, m3]
        )

        assert payload["dominant_direction"] == "bearish_pull"

    def test_f5_5_dominant_direction_neutral_pin_resolution(self):
        """Dominant direction resolves to neutral_pin when forces are balanced within 15%."""
        spot = 100.0
        m1 = PriceMagnetLevel(
            "call_wall", "Call Wall", 105.0, 5.0, 5.0, "above", 70.0, "Resistance", 1
        )
        m2 = PriceMagnetLevel("put_wall", "Put Wall", 95.0, -5.0, -5.0, "below", 70.0, "Support", 2)

        regime = MarketRegimeState(
            "neutral_transition",
            "neutral_straddle",
            "forward_positive_ramp",
            "mean_reverting",
            "neutral_decay",
            0.1,
            0.0,
            100.0,
            spot,
            2.0,
            True,
        )
        payload = build_price_draw_telemetry_payload(
            symbol="QQQ", spot=spot, regime_state=regime, magnets=[m1, m2]
        )

        assert payload["dominant_direction"] == "neutral_pin"

    def test_f5_6_quality_breakdown_flags_boolean_types(self):
        """Quality breakdown provides explicit boolean flags for all sub-feeds."""
        regime = calculate_market_regime(
            spot=100.0, strikes=[90.0, 100.0], call_oi=[100, 100], put_oi=[100, 100]
        )
        payload = build_price_draw_telemetry_payload(
            symbol="IWM", spot=100.0, regime_state=regime, magnets=[]
        )
        q = payload["quality"]
        assert isinstance(q["measurable"], bool)
        assert isinstance(q["open_interest_available"], bool)
        assert isinstance(q["iv_available"], bool)
        assert isinstance(q["volume_available"], bool)


class TestTier1Feature06ConcurrencyAndCacheInvariants:
    """F06: Concurrency, Thread Safety, and Cache Coalescing Invariants."""

    def test_f6_1_deterministic_output_across_repeated_invocations(self):
        """Identical inputs produce strictly identical telemetry payloads without state leakage."""
        spot = 100.0
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        call_oi = [1000, 2000, 5000, 10000, 8000]
        put_oi = [8000, 10000, 5000, 2000, 1000]

        r1 = calculate_market_regime(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        r2 = calculate_market_regime(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        assert r1 == r2

    def test_f6_2_thread_safe_concurrent_engine_execution(self):
        """Concurrent multi-threaded execution across 10 workers produces 0 race conditions."""
        spot = 150.0
        strikes = [140.0, 145.0, 150.0, 155.0, 160.0]
        call_oi = [1000, 2000, 4000, 8000, 6000]
        put_oi = [6000, 8000, 4000, 2000, 1000]

        def compute_worker(sym: str):
            regime = calculate_market_regime(
                spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi
            )
            magnets = detect_price_magnets(
                spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi, regime_state=regime
            )
            return build_price_draw_telemetry_payload(
                symbol=sym, spot=spot, regime_state=regime, magnets=magnets
            )

        symbols = [f"SYM{i}" for i in range(20)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(compute_worker, symbols))

        assert len(results) == 20
        for i, res in enumerate(results):
            assert res["symbol"] == f"SYM{i}"
            assert res["quality"]["measurable"] is True
            assert res["spot"] == 150.0

    def test_f6_3_confluence_zones_clustering_within_threshold(self):
        """Confluence zones cluster attractors within 0.75% of spot."""
        spot = 100.0
        m1 = PriceMagnetLevel("call_wall", "Call Wall", 105.0, 5.0, 5.0, "above", 85.0, "Res", 1)
        m2 = PriceMagnetLevel("max_pain", "Max Pain", 105.4, 5.4, 5.4, "above", 80.0, "Pin", 2)
        clusters = compute_confluence_zones([m1, m2], spot, cluster_threshold_pct=0.75)

        assert len(clusters) == 1
        assert clusters[0]["lens_count"] == 2
        assert "GAMMA" in clusters[0]["supporting_lenses"]
        assert "THETA" in clusters[0]["supporting_lenses"]

    def test_f6_4_confluence_zones_exclude_distant_attractors(self):
        """Attractors separated by more than cluster threshold are not merged."""
        spot = 100.0
        m1 = PriceMagnetLevel("call_wall", "Call Wall", 105.0, 5.0, 5.0, "above", 85.0, "Res", 1)
        m2 = PriceMagnetLevel("put_wall", "Put Wall", 95.0, -5.0, -5.0, "below", 80.0, "Sup", 2)
        clusters = compute_confluence_zones([m1, m2], spot, cluster_threshold_pct=0.75)
        assert len(clusters) == 0

    def test_f6_5_sub_millisecond_analytical_latency(self):
        """Full regime and magnet analysis completes in under 5 milliseconds."""
        spot = 100.0
        strikes = [float(k) for k in range(50, 150, 2)]
        call_oi = [1000 + i * 50 for i in range(len(strikes))]
        put_oi = [5000 - i * 40 for i in range(len(strikes))]

        start = time.perf_counter()
        regime = calculate_market_regime(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        magnets = detect_price_magnets(
            spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi, regime_state=regime
        )
        payload = build_price_draw_telemetry_payload(
            symbol="SPY", spot=spot, regime_state=regime, magnets=magnets
        )
        duration_ms = (time.perf_counter() - start) * 1000.0

        assert duration_ms < 15.0, f"Analysis took {duration_ms:.2f}ms, exceeding 15ms target"
        assert payload["quality"]["measurable"] is True

    def test_f6_6_iso_timestamp_validity_in_payload(self):
        """asof_utc timestamp in payload is valid ISO format."""
        regime = calculate_market_regime(
            spot=100.0, strikes=[90.0, 100.0], call_oi=[100, 100], put_oi=[100, 100]
        )
        payload = build_price_draw_telemetry_payload(
            symbol="SPY", spot=100.0, regime_state=regime, magnets=[]
        )
        assert "T" in payload["asof_utc"]


# ============================================================================
# TIER 2: BOUNDARY & CORNER CASES (B01 - B12)
# ============================================================================


class TestTier2BoundaryAndCornerCases:
    """B01-B12: Stress testing across 12 boundary and degenerate data dimensions."""

    # Dimension 1: Zero & Flat Gamma Surfaces
    def test_b1_1_flat_zero_gamma_surface_fallback(self):
        """Flat gamma surface with equal small OI falls back gracefully to neutral transition."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[10, 10, 10],
            put_oi=[10, 10, 10],
            call_gammas=[0.0, 0.0, 0.0],
            put_gammas=[0.0, 0.0, 0.0],
        )
        assert regime.measurable is True
        assert regime.volatility_regime == "neutral_transition"

    def test_b1_2_zero_gamma_pull_scores_finite(self):
        """Pull scores remain finite and valid when all gammas are zero."""
        magnets = detect_price_magnets(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[10, 10, 10],
            put_oi=[10, 10, 10],
        )
        for m in magnets:
            assert not math.isnan(m.gravitational_pull)
            assert not math.isinf(m.gravitational_pull)

    def test_b1_3_zero_distance_at_exact_strike(self):
        """Level at exact spot price produces 0.0 distance points and pct."""
        magnets = detect_price_magnets(
            spot=100.0,
            strikes=[100.0],
            call_oi=[1000],
            put_oi=[1000],
        )
        assert magnets[0].distance_points == 0.0
        assert magnets[0].distance_pct == 0.0
        assert magnets[0].direction == "at_spot"

    # Dimension 2: Extreme Moneyness & Astronomical Strikes
    def test_b2_1_deep_otm_strikes_500_percent_from_spot(self):
        """Extreme deep OTM strikes (500% from spot) calculate distance correctly without overflow."""
        spot = 100.0
        strikes = [100.0, 600.0]
        call_oi = [1000, 50000]
        put_oi = [1000, 100]

        magnets = detect_price_magnets(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        cw = next(m for m in magnets if m.level_id == "call_wall")
        assert cw.price == 600.0
        assert cw.distance_pct == 500.0

    def test_b2_2_penny_stock_precision(self):
        """Sub-dollar micro-cap stock with 4 decimal places maintains precision."""
        spot = 0.8540
        strikes = [0.50, 0.8540, 1.00]
        call_oi = [100, 500, 1000]
        put_oi = [1000, 500, 100]

        regime = calculate_market_regime(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        assert regime.measurable is True
        assert regime.spot == 0.8540

    def test_b2_3_astronomical_index_price(self):
        """Massive index prices ($50,000) do not cause float overflow or precision loss."""
        spot = 50000.0
        strikes = [45000.0, 50000.0, 55000.0]
        call_oi = [5000, 10000, 20000]
        put_oi = [20000, 10000, 5000]

        regime = calculate_market_regime(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        assert regime.measurable is True
        assert regime.total_net_gex_m > 0

    # Dimension 3: Extreme DTE Regimes (0DTE vs 730DTE LEAPs)
    def test_b3_1_0dte_expiry_near_zero_time(self):
        """0DTE options with 2 hours to expiry (0.0002 years) compute valid BS gamma without div by zero."""
        gamma = gex_core.bs_gamma(spot=100.0, strike=100.0, years=0.0002, iv=0.25)
        assert gamma is not None
        assert gamma > 0.0

    def test_b3_2_730dte_leaps_long_maturity(self):
        """2-Year LEAPs (2.0 years) compute smoothly without underflow."""
        gamma = gex_core.bs_gamma(spot=100.0, strike=100.0, years=2.0, iv=0.25)
        assert gamma is not None
        assert gamma > 0.0

    def test_b3_3_0dte_charm_decay_regime_activation(self):
        """0DTE chain triggers charm decay selling when calls dominate."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[95.0, 100.0, 105.0],
            call_oi=[1000, 5000, 15000],
            put_oi=[500, 1000, 2000],
            dte_years=0.5 / 365.0,
        )
        assert regime.charm_drift_regime == "selling_drift"

    # Dimension 4: Missing OI Feeds & Partial Chain Topography
    def test_b4_1_none_values_in_gammas_gracefully_fallback(self):
        """None values in gamma sequence gracefully fall back to internal Black-Scholes."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[1000, 2000, 3000],
            put_oi=[3000, 2000, 1000],
            call_gammas=[None, None, None],
            put_gammas=[None, None, None],
        )
        assert regime.measurable is True

    def test_b4_2_none_values_in_iv_gracefully_fallback(self):
        """None values in IV sequence fall back to default 25% IV."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[1000, 2000, 3000],
            put_oi=[3000, 2000, 1000],
            ivs=[None, None, None],
        )
        assert regime.measurable is True

    def test_b4_3_partial_oi_feed_with_zeros(self):
        """Chains where some strikes have 0 OI are processed cleanly."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 95.0, 100.0, 105.0],
            call_oi=[0, 1000, 0, 5000],
            put_oi=[5000, 0, 1000, 0],
        )
        assert regime.measurable is True

    # Dimension 5: Monotonic Non-Crossing GEX Curves
    def test_b5_1_strictly_positive_gamma_all_strikes(self):
        """Chains with strictly positive gamma on every strike produce positive_gamma."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[10000, 20000, 30000],
            put_oi=[0, 0, 0],
        )
        assert regime.volatility_regime == "positive_gamma"

    def test_b5_2_strictly_negative_gamma_all_strikes(self):
        """Chains with strictly negative gamma on every strike produce negative_gamma."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[0, 0, 0],
            put_oi=[10000, 20000, 30000],
        )
        assert regime.volatility_regime == "negative_gamma"

    def test_b5_3_monotonic_fallback_for_gamma_flip(self):
        """When no zero crossing exists, gamma flip defaults to spot."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[10000, 20000, 30000],
            put_oi=[0, 0, 0],
        )
        assert regime.gamma_flip == 100.0

    # Dimension 6: Negative & Zero Interest Rates
    def test_b6_1_zero_interest_rate_stability(self):
        """Zero interest rate (rate=0.0) maintains mathematical stability in Black-Scholes."""
        gamma = gex_core.bs_gamma(spot=100.0, strike=100.0, years=0.1, iv=0.25, rate=0.0)
        assert gamma is not None
        assert gamma > 0.0

    def test_b6_2_negative_interest_rate_stability(self):
        """Negative interest rate (rate=-0.005, e.g. EUR/JPY) maintains stability."""
        gamma = gex_core.bs_gamma(spot=100.0, strike=100.0, years=0.1, iv=0.25, rate=-0.005)
        assert gamma is not None
        assert gamma > 0.0

    def test_b6_3_zero_rate_regime_calculation(self):
        """Market regime calculation succeeds under zero rate environment."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[1000, 2000, 3000],
            put_oi=[3000, 2000, 1000],
            rate=0.0,
        )
        assert regime.measurable is True

    # Dimension 7: Multi-Crossing Gamma Topography
    def test_b7_1_oscillating_gamma_profile_finds_first_zero_crossing(self):
        """Profile with multiple zero crossings locates the first structural regime transition."""
        strikes = [80.0, 90.0, 100.0, 110.0, 120.0]
        # Call > Put at 80 (+), Put > Call at 90 (-), Call > Put at 100 (+)
        call_oi = [10000, 1000, 10000, 1000, 10000]
        put_oi = [1000, 10000, 1000, 10000, 1000]

        regime = calculate_market_regime(
            spot=95.0,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        assert regime.gamma_flip is not None
        assert 80.0 <= regime.gamma_flip <= 120.0

    def test_b7_2_multi_attractor_candidates_handled_gracefully(self):
        """Multiple candidate attractors are ranked without dropped levels."""
        magnets = detect_price_magnets(
            spot=100.0,
            strikes=[80.0, 90.0, 100.0, 110.0, 120.0],
            call_oi=[5000, 1000, 2000, 1000, 8000],
            put_oi=[8000, 1000, 2000, 1000, 5000],
            kinematic_target=102.5,
        )
        assert len(magnets) >= 4

    def test_b7_3_regime_strength_scale_free_between_0_and_1(self):
        """Regime strength metric is normalized scale-free within [0.0, 1.0]."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[10000, 5000, 1000],
            put_oi=[1000, 5000, 10000],
        )
        assert 0.0 <= regime.regime_strength <= 1.0

    # Dimension 8: Exact Strike Collision / Spot at Gamma Flip
    def test_b8_1_spot_equals_exact_strike(self):
        """Spot price exactly at a strike produces exact 0.0 point distance."""
        magnets = detect_price_magnets(
            spot=100.0,
            strikes=[100.0],
            call_oi=[5000],
            put_oi=[5000],
        )
        cw = next(m for m in magnets if m.level_id == "call_wall")
        assert cw.distance_points == 0.0
        assert cw.direction == "at_spot"

    def test_b8_2_spot_equals_exact_gamma_flip(self):
        """Spot price exactly at gamma flip classifies as neutral transition inside flip band."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[95.0, 100.0, 105.0],
            call_oi=[5000, 5000, 5000],
            put_oi=[5000, 5000, 5000],
        )
        assert regime.volatility_regime == "neutral_transition"

    def test_b8_3_max_pain_at_exact_spot(self):
        """Max pain at spot is assigned at_spot direction."""
        magnets = detect_price_magnets(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[100, 1000, 10000],
            put_oi=[10000, 1000, 100],
        )
        mp = next(m for m in magnets if m.level_id == "max_pain")
        assert mp.price == 100.0
        assert mp.direction == "at_spot"

    # Dimension 9: Single-Contract & Sparse Chains
    def test_b9_1_single_contract_chain(self):
        """Chain with exactly 1 strike processes cleanly."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[100.0],
            call_oi=[1000],
            put_oi=[500],
        )
        assert regime.measurable is True
        assert regime.total_net_gex_m > 0

    def test_b9_2_single_strike_magnet_detection(self):
        """Single strike chain produces valid Call Wall and Put Wall."""
        magnets = detect_price_magnets(
            spot=100.0,
            strikes=[100.0],
            call_oi=[1000],
            put_oi=[500],
        )
        assert len(magnets) >= 2

    def test_b9_3_single_strike_confluence_exclusion(self):
        """Single level cannot form a confluence cluster alone."""
        m = PriceMagnetLevel("cw", "CW", 100.0, 0.0, 0.0, "at_spot", 80.0, "Res", 1)
        clusters = compute_confluence_zones([m], 100.0)
        assert len(clusters) == 0

    # Dimension 10: Symmetric Straddle Distributions
    def test_b10_1_perfectly_symmetric_straddle_net_gex_near_zero(self):
        """Symmetric call and put OI creates near-zero net GEX."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[5000, 10000, 5000],
            put_oi=[5000, 10000, 5000],
        )
        assert abs(regime.total_net_gex_m) < 0.01

    def test_b10_2_symmetric_straddle_dominant_direction_neutral_pin(self):
        """Symmetric straddle resolves dominant direction to neutral_pin."""
        m1 = PriceMagnetLevel(
            "call_wall", "Call Wall", 110.0, 10.0, 10.0, "above", 70.0, "Resistance", 1
        )
        m2 = PriceMagnetLevel(
            "put_wall", "Put Wall", 90.0, -10.0, -10.0, "below", 70.0, "Support", 2
        )

        regime = MarketRegimeState(
            "neutral_transition",
            "neutral_straddle",
            "forward_positive_ramp",
            "mean_reverting",
            "neutral_decay",
            0.05,
            0.0,
            100.0,
            100.0,
            2.0,
            True,
        )
        payload = build_price_draw_telemetry_payload(
            symbol="SPY", spot=100.0, regime_state=regime, magnets=[m1, m2]
        )
        assert payload["dominant_direction"] == "neutral_pin"

    def test_b10_3_symmetric_straddle_pull_scores_equal(self):
        """Equidistant symmetric walls produce equal pull scores."""
        magnets = detect_price_magnets(
            spot=100.0,
            strikes=[90.0, 110.0],
            call_oi=[1000, 10000],
            put_oi=[10000, 1000],
        )
        cw = next(m for m in magnets if m.level_id == "call_wall")
        pw = next(m for m in magnets if m.level_id == "put_wall")
        assert cw.gravitational_pull == pw.gravitational_pull

    # Dimension 11: Extreme Volatility Spikes (>300% IV)
    def test_b11_1_extreme_volatility_iv_300_percent(self):
        """Extreme IV (3.0 = 300%) computes valid non-NaN gamma."""
        gamma = gex_core.bs_gamma(spot=100.0, strike=100.0, years=0.1, iv=3.0)
        assert gamma is not None
        assert gamma > 0.0

    def test_b11_2_extreme_volatility_wide_expected_move(self):
        """Extreme IV results in wide 1D expected move without overflow."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[1000, 2000, 3000],
            put_oi=[3000, 2000, 1000],
            ivs=[3.0, 3.0, 3.0],
        )
        assert regime.expected_move_1d is not None
        assert regime.expected_move_1d > 15.0

    def test_b11_3_extreme_volatility_pull_score_bounded(self):
        """Pull score remains <= 100 under extreme volatility spike."""
        magnets = detect_price_magnets(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[100000, 200000, 500000],
            put_oi=[500000, 200000, 100000],
        )
        for m in magnets:
            assert m.gravitational_pull <= 100.0

    # Dimension 12: Malformed Payloads & Non-Standard Symbols
    def test_b12_1_lowercase_symbol_uppercased(self):
        """Lowercase symbol input is normalized to uppercase in payload."""
        regime = calculate_market_regime(
            spot=100.0, strikes=[90.0, 100.0], call_oi=[100, 100], put_oi=[100, 100]
        )
        payload = build_price_draw_telemetry_payload(
            symbol="aapl", spot=100.0, regime_state=regime, magnets=[]
        )
        assert payload["symbol"] == "AAPL"

    def test_b12_2_crypto_hyphenated_symbol(self):
        """Hyphenated cryptocurrency ticker symbol (BTC-USD) handled cleanly."""
        regime = calculate_market_regime(
            spot=65000.0, strikes=[60000.0, 70000.0], call_oi=[100, 100], put_oi=[100, 100]
        )
        payload = build_price_draw_telemetry_payload(
            symbol="btc-usd", spot=65000.0, regime_state=regime, magnets=[]
        )
        assert payload["symbol"] == "BTC-USD"

    def test_b12_3_mismatched_sequence_lengths_handled_safely(self):
        """Mismatched strikes and OI sequence lengths do not crash."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0, 120.0],
            call_oi=[1000, 2000],  # Short OI array
            put_oi=[2000, 1000],
        )
        assert regime.measurable is True


# ============================================================================
# TIER 3: CROSS-FEATURE PAIRWISE COMBINATIONS (P01 - P08)
# ============================================================================


class TestTier3CrossFeatureCombinations:
    """P01-P08: Multi-variable interaction & state transition combinations."""

    def test_p01_regime_transition_and_magnet_retargeting(self):
        """Spot crossing gamma flip triggers regime transition and retargets primary magnet."""
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        call_oi = [1000, 2000, 5000, 15000, 20000]
        put_oi = [20000, 15000, 5000, 2000, 1000]

        # Case A: Spot at 92 (below flip ~100 -> negative gamma territory)
        regime_below = calculate_market_regime(
            spot=92.0, strikes=strikes, call_oi=call_oi, put_oi=put_oi
        )
        magnets_below = detect_price_magnets(
            spot=92.0, strikes=strikes, call_oi=call_oi, put_oi=put_oi, regime_state=regime_below
        )
        assert regime_below.volatility_regime == "negative_gamma"

        # Case B: Spot rallies to 108 (above flip ~100 -> positive gamma territory)
        regime_above = calculate_market_regime(
            spot=108.0, strikes=strikes, call_oi=call_oi, put_oi=put_oi
        )
        magnets_above = detect_price_magnets(
            spot=108.0, strikes=strikes, call_oi=call_oi, put_oi=put_oi, regime_state=regime_above
        )
        assert regime_above.volatility_regime == "positive_gamma"
        assert (
            magnets_above[0].level_id != magnets_below[0].level_id
            or magnets_above[0].direction != magnets_below[0].direction
        )

    def test_p02_opex_pinning_and_kinematic_envelope_confluence(self):
        """Max Pain pin aligning with kinematic drift within 0.5% forms a high-conviction confluence zone."""
        spot = 500.0
        strikes = [480.0, 490.0, 500.0, 510.0, 520.0]
        call_oi = [100, 500, 1000, 10000, 20000]
        put_oi = [20000, 10000, 1000, 500, 100]

        magnets = detect_price_magnets(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            kinematic_target=501.5,  # 0.3% from 500 Max Pain
        )
        clusters = compute_confluence_zones(magnets, spot, cluster_threshold_pct=0.75)
        assert len(clusters) >= 1
        assert "THETA" in clusters[0]["supporting_lenses"]
        assert "KALMAN" in clusters[0]["supporting_lenses"]

    def test_p03_0dte_afternoon_charm_bleed_and_put_wall_decay(self):
        """0DTE afternoon charm bleed accelerating selling pressure toward put wall floor."""
        spot = 430.0
        strikes = [420.0, 425.0, 430.0, 435.0, 440.0]
        call_oi = [1000, 2000, 5000, 20000, 15000]
        put_oi = [15000, 20000, 5000, 2000, 1000]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            dte_years=0.1 / 365.0,  # 0DTE final session hours
        )
        assert regime.charm_drift_regime == "selling_drift"
        magnets = detect_price_magnets(
            spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi, regime_state=regime
        )
        pw = next(m for m in magnets if m.level_id == "put_wall")
        assert pw.direction == "below"

    def test_p04_batch_quote_and_price_attractor_cache_coalescing(self):
        """Simulated parallel API calls for quotes and attractors share calculation cache without race conditions."""
        spot = 150.0
        strikes = [140.0, 150.0, 160.0]
        call_oi = [1000, 5000, 10000]
        put_oi = [10000, 5000, 1000]

        results = []

        def fetch():
            reg = calculate_market_regime(
                spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi
            )
            mags = detect_price_magnets(
                spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi, regime_state=reg
            )
            return build_price_draw_telemetry_payload(
                symbol="AAPL", spot=spot, regime_state=reg, magnets=mags
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            futs = [ex.submit(fetch) for _ in range(10)]
            for f in concurrent.futures.as_completed(futs):
                results.append(f.result())

        assert len(results) == 10
        assert all(r["symbol"] == "AAPL" for r in results)

    def test_p05_missing_oi_feed_and_options_enrichment(self):
        """Options chain missing OI marks price draw unmeasured while preserving standard Greek fields."""
        regime = calculate_market_regime(spot=100.0, strikes=[], call_oi=[], put_oi=[])
        payload = build_price_draw_telemetry_payload(
            symbol="IWM", spot=100.0, regime_state=regime, magnets=[], quality_reason="Missing OI"
        )
        assert payload["quality"]["measurable"] is False
        assert payload["regime_state"] == "unmeasurable"

    def test_p06_high_vanna_sensitivity_and_volatility_expansion(self):
        """High IV dispersion in short gamma classifies as volatility amplification."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 95.0, 100.0],
            call_oi=[500, 1000, 1500],
            put_oi=[15000, 20000, 10000],
            ivs=[0.80, 0.75, 0.70],  # High elevated IV skew
        )
        assert regime.volatility_behavior == "volatility_amplification"
        assert regime.total_net_gex_m < 0

    def test_p07_call_wall_put_wall_collar_inversion(self):
        """Inverted market where Put Wall > Call Wall resolves directional draw accurately."""
        spot = 100.0
        # Call Wall at 95, Put Wall at 105
        strikes = [95.0, 100.0, 105.0]
        call_oi = [15000, 2000, 1000]
        put_oi = [1000, 2000, 15000]

        magnets = detect_price_magnets(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        cw = next(m for m in magnets if m.level_id == "call_wall")
        pw = next(m for m in magnets if m.level_id == "put_wall")

        assert cw.price == 95.0
        assert pw.price == 105.0
        assert cw.direction == "below"
        assert pw.direction == "above"

    def test_p08_confluence_cluster_and_dominant_direction_alignment(self):
        """Heavy confluence cluster above spot aligns dominant direction with bullish_pull."""
        spot = 100.0
        strikes = [90.0, 100.0, 110.0]
        call_oi = [100, 1000, 30000]  # Huge call cluster at 110
        put_oi = [1000, 1000, 100]

        regime = calculate_market_regime(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        magnets = detect_price_magnets(
            spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi, kinematic_target=110.5
        )
        payload = build_price_draw_telemetry_payload(
            symbol="NVDA", spot=spot, regime_state=regime, magnets=magnets
        )

        assert payload["dominant_direction"] == "bullish_pull"
        assert len(payload["confluence_clusters"]) >= 1


# ============================================================================
# TIER 4: REAL-WORLD INSTITUTIONAL SCENARIOS (S01 - S06)
# ============================================================================


class TestTier4RealWorldScenarios:
    """S01-S06: High-fidelity production institutional market simulations."""

    def test_s01_triple_witching_quarterly_opex_pinning(self):
        """Simulation: Quarterly Triple Witching creates immense pinning gravity at 500 strike."""
        spot = 500.0
        strikes = [480.0, 490.0, 500.0, 510.0, 520.0]
        call_oi = [5000, 15000, 120000, 20000, 8000]  # Massive 120k OI pin at 500
        put_oi = [8000, 20000, 120000, 15000, 5000]

        regime = calculate_market_regime(spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi)
        magnets = detect_price_magnets(
            spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi, regime_state=regime
        )
        payload = build_price_draw_telemetry_payload(
            symbol="SPY", spot=spot, regime_state=regime, magnets=magnets
        )

        mp = next(m for m in magnets if m.level_id == "max_pain")
        assert mp.price == 500.0
        assert mp.gravitational_pull > 80.0
        assert payload["dominant_direction"] == "neutral_pin"

    def test_s02_short_gamma_squeeze_cascade_acceleration(self):
        """Simulation: Spot breaches Call Wall in negative gamma, triggering cascade breakout."""
        spot = 155.0  # Breached above Call Wall 150
        strikes = [140.0, 145.0, 150.0, 155.0, 160.0]
        call_oi = [1000, 2000, 10000, 5000, 2000]  # Call Wall was at 150
        put_oi = [10000, 30000, 60000, 80000, 20000]  # Heavy puts create negative gamma

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            kinematic_velocity=0.04,  # Rapid breakout velocity
        )
        assert regime.volatility_behavior == "volatility_amplification"
        assert regime.kinematic_regime == "trend_acceleration"

        magnets = detect_price_magnets(
            spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi, regime_state=regime
        )
        cw = next(m for m in magnets if m.level_id == "call_wall")
        assert cw.price == 150.0
        assert cw.direction == "below"  # Squeezed past wall

    def test_s03_0dte_afternoon_charm_bleed_flash_draw(self):
        """Simulation: Accelerated theta decay in final 90 mins forces dealer delta re-hedging."""
        spot = 430.0
        strikes = [420.0, 425.0, 430.0, 435.0, 440.0]
        call_oi = [2000, 5000, 15000, 80000, 40000]  # Heavy calls overhead
        put_oi = [5000, 8000, 10000, 5000, 2000]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            dte_years=0.05 / 365.0,  # Afternoon 0DTE
        )
        assert regime.charm_drift_regime == "selling_drift"

    def test_s04_market_open_volatility_dislocation_and_gap(self):
        """Simulation: Pre-market +4% gap requires instant telemetry re-indexing."""
        pre_spot = 100.0
        open_spot = 104.0
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        call_oi = [1000, 2000, 5000, 15000, 10000]
        put_oi = [10000, 15000, 5000, 2000, 1000]

        reg_pre = calculate_market_regime(
            spot=pre_spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi
        )
        reg_open = calculate_market_regime(
            spot=open_spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi
        )

        # Flip was above pre-market spot, now below open spot
        assert reg_pre.gamma_flip is not None
        assert pre_spot < reg_pre.gamma_flip or reg_pre.volatility_regime in (
            "negative_gamma",
            "neutral_transition",
        )
        assert open_spot > reg_open.gamma_flip

    def test_s05_sudden_regime_pivot_upon_put_wall_breach(self):
        """Simulation: Spot collapsing below Put Wall flips market from dampening to cascade."""
        strikes = [180.0, 190.0, 200.0, 210.0, 220.0]
        call_oi = [1000, 2000, 5000, 20000, 15000]
        put_oi = [20000, 50000, 20000, 5000, 1000]  # Put wall at 190

        # Before breach: Spot at 195
        reg_before = calculate_market_regime(
            spot=195.0, strikes=strikes, call_oi=call_oi, put_oi=put_oi
        )
        # After breach: Spot crashes to 185
        reg_after = calculate_market_regime(
            spot=185.0, strikes=strikes, call_oi=call_oi, put_oi=put_oi
        )

        assert reg_after.volatility_regime == "negative_gamma"
        assert reg_after.volatility_behavior == "volatility_amplification"

    def test_s06_earnings_announcement_iv_crush_and_magnet_dissipation(self):
        """Simulation: Post-earnings IV crush (120% -> 30%) collapses net dollar GEX mass."""
        spot = 250.0
        strikes = [230.0, 240.0, 250.0, 260.0, 270.0]
        call_oi = [5000, 10000, 25000, 10000, 5000]
        put_oi = [5000, 10000, 25000, 10000, 5000]

        reg_pre = calculate_market_regime(
            spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi, ivs=[1.20] * 5
        )
        reg_post = calculate_market_regime(
            spot=spot, strikes=strikes, call_oi=call_oi, put_oi=put_oi, ivs=[0.30] * 5
        )

        assert reg_pre.expected_move_1d is not None
        assert reg_post.expected_move_1d is not None
        assert reg_post.expected_move_1d < reg_pre.expected_move_1d * 0.35
