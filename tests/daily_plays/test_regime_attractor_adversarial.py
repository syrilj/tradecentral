"""Adversarial Empirical Stress-Testing Harness for Regime Attractor Engine.

Tests:
1. Extreme Strike Distributions ($0.01 micro-caps to $100,000 mega-caps, massive dynamic ranges).
2. Extreme Tenors (0DTE at 0.0001y to 730DTE+ LEAPs).
3. Extreme IVs (0.1% to 1000%, inverted skew, None/NaN/Inf in IV lists).
4. GEX Profiles (Strictly positive, strictly negative, flat/uniform, multi-crossing, extreme asymmetric spikes).
5. Max Pain Mathematical Payout Matrix Verification.
6. Gravitational Pull & Telemetry Invariants (Bounds [0, 100], NaN/Inf immunity, Conviction rankings).
7. Missing/Corrupted Data & Strict Zero-Spoofing Protocols.
8. Interest Rates, Multipliers, Permutations, and Single-Linkage Clustering.
"""

from __future__ import annotations

import math
from typing import Any
import pytest

from daily_plays.regime_attractor_engine import (
    MarketRegimeState,
    PriceMagnetLevel,
    build_price_draw_telemetry_payload,
    calculate_market_regime,
    compute_confluence_zones,
    detect_price_magnets,
)


# ============================================================================
# 1. EXTREME STRIKE DISTRIBUTIONS
# ============================================================================


class TestAdversarialExtremeStrikes:
    """Stress tests on extreme strike magnitudes and non-uniform distributions."""

    def test_micro_cap_penny_stock_strikes(self):
        """Spot = $0.05, strikes in cents ($0.01 to $0.50)."""
        spot = 0.05
        strikes = [0.01, 0.02, 0.05, 0.10, 0.20, 0.50]
        call_oi = [5000, 10000, 50000, 20000, 5000, 1000]
        put_oi = [1000, 5000, 20000, 5000, 1000, 500]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        assert regime.measurable is True
        assert not math.isnan(regime.total_net_gex_m)
        assert not math.isinf(regime.total_net_gex_m)
        assert 0.0 <= regime.regime_strength <= 1.0

        magnets = detect_price_magnets(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            regime_state=regime,
        )
        assert len(magnets) > 0
        for m in magnets:
            assert 0.0 <= m.gravitational_pull <= 100.0
            assert not math.isnan(m.price)
            assert not math.isnan(m.distance_points)
            assert not math.isnan(m.distance_pct)

    def test_mega_cap_six_figure_strikes(self):
        """Spot = $650,000 (e.g. BRK.A), strikes $500k to $800k."""
        spot = 650_000.0
        strikes = [500_000.0, 550_000.0, 600_000.0, 650_000.0, 700_000.0, 750_000.0, 800_000.0]
        call_oi = [100, 250, 500, 1200, 2000, 800, 300]
        put_oi = [300, 800, 2000, 1200, 500, 250, 100]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        assert regime.measurable is True
        assert not math.isnan(regime.total_net_gex_m)
        assert not math.isinf(regime.total_net_gex_m)
        assert 0.0 <= regime.regime_strength <= 1.0

        magnets = detect_price_magnets(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            regime_state=regime,
        )
        for m in magnets:
            assert 0.0 <= m.gravitational_pull <= 100.0
            assert not math.isnan(m.distance_pct)

    def test_extreme_strike_dynamic_range(self):
        """Dynamic strike range from $0.01 to $100,000 on $100 spot."""
        spot = 100.0
        strikes = [0.01, 1.0, 10.0, 50.0, 100.0, 200.0, 1000.0, 10000.0, 100000.0]
        call_oi = [10, 50, 100, 500, 2000, 500, 100, 50, 10]
        put_oi = [10, 50, 100, 500, 2000, 500, 100, 50, 10]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        assert regime.measurable is True
        assert 0.0 <= regime.regime_strength <= 1.0

        magnets = detect_price_magnets(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            regime_state=regime,
        )
        assert len(magnets) > 0

    def test_single_strike_chain(self):
        """Chain with only one strike."""
        spot = 100.0
        strikes = [100.0]
        call_oi = [5000]
        put_oi = [2000]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        assert regime.measurable is True
        assert regime.gamma_flip is None
        assert regime.volatility_regime == "positive_gamma"

        magnets = detect_price_magnets(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            regime_state=regime,
        )
        assert len(magnets) > 0


# ============================================================================
# 2. EXTREME EXPIRATIONS (0DTE VS LEAPS)
# ============================================================================


class TestAdversarialExtremeTenors:
    """Stress tests on extreme options expiries: 0DTE (seconds/hours) to 5-year LEAPs."""

    def test_sub_hour_0dte_near_expiration(self):
        """0DTE with 15 minutes left (dte_years = 0.00003)."""
        spot = 100.0
        strikes = [95.0, 100.0, 105.0]
        call_oi = [5000, 20000, 5000]
        put_oi = [2000, 8000, 2000]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            dte_years=0.00003,
        )
        assert regime.measurable is True
        assert not math.isnan(regime.total_net_gex_m)
        assert not math.isinf(regime.total_net_gex_m)
        assert regime.charm_drift_regime in ("selling_drift", "buying_drift", "neutral_decay")

    def test_multi_year_leaps(self):
        """LEAPs expiring in 3 years (dte_years = 3.0)."""
        spot = 100.0
        strikes = [70.0, 80.0, 90.0, 100.0, 110.0, 120.0, 130.0]
        call_oi = [1000, 2000, 5000, 10000, 8000, 4000, 2000]
        put_oi = [2000, 4000, 8000, 10000, 5000, 2000, 1000]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            dte_years=3.0,
        )
        assert regime.measurable is True
        assert regime.charm_drift_regime == "neutral_decay"
        assert not math.isnan(regime.total_net_gex_m)

    def test_zero_and_negative_dte_years(self):
        """Negative or 0 DTE is clamped safely."""
        spot = 100.0
        strikes = [95.0, 100.0, 105.0]
        call_oi = [1000, 2000, 1000]
        put_oi = [1000, 2000, 1000]

        for bad_dte in [0.0, -0.1, -1.0]:
            regime = calculate_market_regime(
                spot=spot,
                strikes=strikes,
                call_oi=call_oi,
                put_oi=put_oi,
                dte_years=bad_dte,
            )
            assert regime.measurable is True
            assert not math.isnan(regime.total_net_gex_m)


# ============================================================================
# 3. EXTREME VOLATILITY / IVs
# ============================================================================


class TestAdversarialExtremeIVs:
    """Stress tests on extreme implied volatilities: 0.1% to 2000% and invalid IV arrays."""

    def test_ultra_low_iv_compressed_market(self):
        """IV = 0.001 (0.1% IV, extremely low)."""
        spot = 100.0
        strikes = [95.0, 100.0, 105.0]
        call_oi = [1000, 5000, 1000]
        put_oi = [1000, 5000, 1000]
        ivs = [0.001, 0.001, 0.001]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            ivs=ivs,
        )
        assert regime.measurable is True
        assert not math.isnan(regime.total_net_gex_m)
        assert regime.expected_move_1d is not None

    def test_hyper_volatility_meme_stock_iv(self):
        """IV = 10.0 (1000% IV, hypervolatility)."""
        spot = 100.0
        strikes = [50.0, 100.0, 200.0]
        call_oi = [1000, 5000, 1000]
        put_oi = [1000, 5000, 1000]
        ivs = [10.0, 10.0, 10.0]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            ivs=ivs,
        )
        assert regime.measurable is True
        assert not math.isnan(regime.total_net_gex_m)

    def test_none_and_invalid_elements_in_iv_array(self):
        """Array containing None or missing elements does not crash."""
        spot = 100.0
        strikes = [90.0, 95.0, 100.0, 105.0]
        call_oi = [1000, 2000, 3000, 4000]
        put_oi = [4000, 3000, 2000, 1000]
        ivs = [0.25, None, 0.30, None]  # Some strikes lack IV

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            ivs=ivs,
        )
        assert regime.measurable is True
        assert regime.expected_move_1d is not None

    def test_inverted_iv_skew(self):
        """Deep OTM calls having much higher IV than OTM puts (inverted skew)."""
        spot = 100.0
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        call_oi = [500, 1000, 2000, 5000, 10000]
        put_oi = [10000, 5000, 2000, 1000, 500]
        ivs = [0.15, 0.20, 0.30, 0.65, 1.20]  # Sharp upward call skew

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            ivs=ivs,
        )
        assert regime.measurable is True
        assert not math.isnan(regime.total_net_gex_m)


# ============================================================================
# 4. GEX PROFILES & CURVATURE
# ============================================================================


class TestAdversarialGexProfiles:
    """Stress tests on monotonic, flat, strictly one-sided, and multi-crossing GEX."""

    def test_strictly_positive_gamma_all_strikes_is_not_neutral_transition(self):
        """When every strike has massive call OI and 0 put OI, regime MUST be positive_gamma."""
        spot = 100.0
        strikes = [90.0, 100.0, 110.0]
        call_oi = [50000, 100000, 50000]
        put_oi = [0, 0, 0]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        assert regime.measurable is True
        assert regime.total_net_gex_m > 0
        assert regime.volatility_regime == "positive_gamma", (
            f"Expected positive_gamma, got {regime.volatility_regime}. "
            f"Net GEX = {regime.total_net_gex_m}, flip = {regime.gamma_flip}"
        )
        assert regime.volatility_behavior == "volatility_dampening"

    def test_strictly_negative_gamma_all_strikes_is_not_neutral_transition(self):
        """When every strike has massive put OI and 0 call OI, regime MUST be negative_gamma."""
        spot = 100.0
        strikes = [90.0, 100.0, 110.0]
        call_oi = [0, 0, 0]
        put_oi = [50000, 100000, 50000]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        assert regime.measurable is True
        assert regime.total_net_gex_m < 0
        assert regime.volatility_regime == "negative_gamma", (
            f"Expected negative_gamma, got {regime.volatility_regime}. "
            f"Net GEX = {regime.total_net_gex_m}, flip = {regime.gamma_flip}"
        )
        assert regime.volatility_behavior == "volatility_amplification"

    def test_multi_crossing_gamma_profile(self):
        """Net GEX crosses zero multiple times (+ - + - +)."""
        spot = 100.0
        strikes = [80.0, 90.0, 100.0, 110.0, 120.0]
        call_oi = [10000, 100, 10000, 100, 10000]
        put_oi = [100, 10000, 100, 10000, 100]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        assert regime.measurable is True
        assert regime.gamma_flip is not None
        assert 80.0 <= regime.gamma_flip <= 120.0

    def test_flat_uniform_oi_across_all_strikes(self):
        """Equal call and put OI across all strikes."""
        spot = 100.0
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        call_oi = [1000, 1000, 1000, 1000, 1000]
        put_oi = [1000, 1000, 1000, 1000, 1000]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        assert regime.measurable is True
        assert regime.volatility_regime == "neutral_transition"


# ============================================================================
# 5. MAX PAIN EXACT MATHEMATICAL LOSS MINIMIZATION
# ============================================================================


class TestAdversarialMaxPainExactness:
    """Verifies Max Pain minimizes total option buyer intrinsic payout."""

    def test_max_pain_known_ground_truth(self):
        """Ground truth test case:
        Strikes: [90, 100, 110]
        Call OI: 90: 100, 100: 500, 110: 2000
        Put OI:  90: 2000, 100: 500, 110: 100

        Total Payout Calculation at Expiry Price S:
        At S=90: Payout = 7,000
        At S=100: Payout = 2,000 (MINIMUM)
        At S=110: Payout = 7,000
        """
        spot = 100.0
        strikes = [90.0, 100.0, 110.0]
        call_oi = [100, 500, 2000]
        put_oi = [2000, 500, 100]

        magnets = detect_price_magnets(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        mp = next((m for m in magnets if m.level_id == "max_pain"), None)
        assert mp is not None
        assert mp.price == 100.0, f"Expected Max Pain 100.0, got {mp.price}"

    def test_max_pain_triple_witching_pin(self):
        """Quarterly OpEx with huge concentration at 500 strike."""
        spot = 500.0
        strikes = [480.0, 490.0, 500.0, 510.0, 520.0]
        call_oi = [5000, 15000, 120000, 20000, 8000]
        put_oi = [8000, 20000, 120000, 15000, 5000]

        magnets = detect_price_magnets(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        mp = next((m for m in magnets if m.level_id == "max_pain"), None)
        assert mp is not None
        assert mp.price == 500.0, f"Expected Max Pain 500.0, got {mp.price}"


# ============================================================================
# 6. GRAVITATIONAL PULL & TELEMETRY INVARIANTS
# ============================================================================


class TestAdversarialPullScoresAndInvariants:
    """Stress tests on pull scores, conviction rankings, and dominant direction."""

    def test_pull_scores_strictly_bounded(self):
        """Gravitational pull scores must remain in [0.0, 100.0] across all levels."""
        spot = 100.0
        strikes = [50.0, 75.0, 100.0, 125.0, 150.0]
        call_oi = [100, 500, 10000, 500, 100]
        put_oi = [100, 500, 10000, 500, 100]

        magnets = detect_price_magnets(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            kinematic_target=102.5,
        )
        for m in magnets:
            assert 0.0 <= m.gravitational_pull <= 100.0, f"Out of bounds: {m}"

    def test_conviction_ranks_unique_and_ordered(self):
        """Conviction ranks 1..N must be strictly unique and ordered by pull score descending."""
        spot = 100.0
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
        call_oi = [1000, 2000, 5000, 10000, 3000]
        put_oi = [3000, 10000, 5000, 2000, 1000]

        magnets = detect_price_magnets(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            kinematic_target=101.0,
        )
        ranks = [m.conviction_rank for m in magnets]
        assert ranks == list(range(1, len(magnets) + 1))
        pulls = [m.gravitational_pull for m in magnets]
        assert pulls == sorted(pulls, reverse=True)

    def test_symmetric_straddle_resolves_to_neutral_pin(self):
        """Symmetric chain around spot must produce dominant_direction == neutral_pin."""
        spot = 100.0
        strikes = [90.0, 100.0, 110.0]
        call_oi = [5000, 10000, 5000]
        put_oi = [5000, 10000, 5000]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
        )
        magnets = detect_price_magnets(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            regime_state=regime,
        )
        payload = build_price_draw_telemetry_payload(
            symbol="SPY",
            spot=spot,
            regime_state=regime,
            magnets=magnets,
        )
        assert payload["dominant_direction"] == "neutral_pin", (
            f"Expected neutral_pin for symmetric distribution, got {payload['dominant_direction']}"
        )


# ============================================================================
# 7. ZERO-SPOOFING & MISSING DATA RESILIENCE
# ============================================================================


class TestAdversarialZeroSpoofingAndMissingData:
    """Stress tests on corrupt, empty, and non-positive inputs."""

    def test_zero_or_negative_spot_price(self):
        """Spot <= 0 returns unmeasurable regime and empty magnets."""
        for bad_spot in [0.0, -100.0, -0.0001]:
            regime = calculate_market_regime(
                spot=bad_spot,
                strikes=[90.0, 100.0, 110.0],
                call_oi=[1000, 1000, 1000],
                put_oi=[1000, 1000, 1000],
            )
            assert regime.measurable is False
            assert regime.volatility_regime == "unmeasurable"

            magnets = detect_price_magnets(
                spot=bad_spot,
                strikes=[90.0, 100.0, 110.0],
                call_oi=[1000, 1000, 1000],
                put_oi=[1000, 1000, 1000],
            )
            assert magnets == []

            payload = build_price_draw_telemetry_payload(
                symbol="TEST",
                spot=bad_spot,
                regime_state=regime,
                magnets=magnets,
            )
            assert payload["quality"]["measurable"] is False
            assert payload["spot"] is None
            assert payload["levels"] == []

    def test_all_zero_open_interest(self):
        """Zero OI across all strikes triggers unmeasurable state."""
        regime = calculate_market_regime(
            spot=100.0,
            strikes=[90.0, 100.0, 110.0],
            call_oi=[0, 0, 0],
            put_oi=[0, 0, 0],
        )
        assert regime.measurable is False
        assert regime.volatility_regime == "unmeasurable"


# ============================================================================
# 8. INTEREST RATES & CONFLUENCE CLUSTERING
# ============================================================================


class TestAdversarialRatesAndClustering:
    """Stress tests on negative rates, zero rates, and multi-lens confluence clustering."""

    def test_negative_interest_rate(self):
        """Negative interest rate environment (e.g. EUR/JPY historical negative rates)."""
        spot = 100.0
        strikes = [95.0, 100.0, 105.0]
        call_oi = [1000, 5000, 1000]
        put_oi = [1000, 5000, 1000]

        regime = calculate_market_regime(
            spot=spot,
            strikes=strikes,
            call_oi=call_oi,
            put_oi=put_oi,
            rate=-0.005,
        )
        assert regime.measurable is True
        assert not math.isnan(regime.total_net_gex_m)

    def test_multi_lens_confluence_clustering(self):
        """Test confluence clustering when Call Wall and Kinematic target are within 0.5%."""
        spot = 100.0
        magnets = [
            PriceMagnetLevel(
                "call_wall", "Call Wall", 102.0, 2.0, 2.0, "above", 80.0, "Resistance", 1
            ),
            PriceMagnetLevel(
                "kinematic_drift", "Kinematic Attractor", 102.3, 2.3, 2.3, "above", 75.0, "Drift", 2
            ),
            PriceMagnetLevel("put_wall", "Put Wall", 95.0, -5.0, -5.0, "below", 70.0, "Support", 3),
        ]
        clusters = compute_confluence_zones(magnets, spot=spot, cluster_threshold_pct=0.75)
        assert len(clusters) == 1
        assert clusters[0]["lens_count"] == 2
        assert "GAMMA" in clusters[0]["supporting_lenses"]
        assert "KALMAN" in clusters[0]["supporting_lenses"]
