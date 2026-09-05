"""Comprehensive Unit and Mathematical Tests for Regime Attractor Engine.

Tests:
1. Mathematical Greeks and Black-Scholes calculations (Gamma, Charm, Dollar Gamma).
2. Vectorized Max Pain pin calculation with exact worked examples.
3. Gamma Flip S* continuous zero-crossing search and Directional Walls extraction.
4. Comprehensive Market Regime Classification (Positive/Negative Gamma, Transition, 4 Topography Quadrants).
5. Charm Decay dynamics and Kinematic Kalman state-space filtering.
6. Multi-factor Gravitational Pull score [0-100] and conviction ranking.
7. Multi-lens Confluence Clustering (±0.75% spot tolerance).
8. Strict Zero-Spoofing and Missing-Data Protocol enforcement.
9. JSON serialization and interface contract conformance.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from edge.daily_plays.regime_attractor_engine import (
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
)


# ---------------------------------------------------------------------------
# Test Fixtures & Synthetic Generators
# ---------------------------------------------------------------------------


def _build_synthetic_chain(
    spot: float = 100.0,
    strikes: list[float] | None = None,
    call_ois: list[float] | None = None,
    put_ois: list[float] | None = None,
    iv: float = 0.25,
    dte: float = 30.0,
    volume: float = 1000.0,
) -> list[dict[str, Any]]:
    """Build a balanced synthetic option chain for testing."""
    if strikes is None:
        strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
    if call_ois is None:
        call_ois = [500.0, 1000.0, 2500.0, 4000.0, 1500.0]
    if put_ois is None:
        put_ois = [1500.0, 4000.0, 2500.0, 1000.0, 500.0]

    rows: list[dict[str, Any]] = []
    for k, c_oi, p_oi in zip(strikes, call_ois, put_ois):
        rows.append(
            {
                "strike": k,
                "right": "call",
                "open_interest": c_oi,
                "iv": iv,
                "dte": dte,
                "volume": volume,
                "multiplier": 100.0,
            }
        )
        rows.append(
            {
                "strike": k,
                "right": "put",
                "open_interest": p_oi,
                "iv": iv,
                "dte": dte,
                "volume": volume,
                "multiplier": 100.0,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# 1. Mathematical Greeks & Black-Scholes Tests
# ---------------------------------------------------------------------------


def test_bs_d1_d2_valid_and_invalid_inputs():
    """Verify d1 and d2 mathematical behavior and boundary guards."""
    # Valid ATM calculation
    d1_d2 = bs_d1_d2(spot=100.0, strike=100.0, years=1.0, iv=0.20, rate=0.05)
    assert d1_d2 is not None
    d1, d2 = d1_d2
    assert math.isclose(d1, (0.05 + 0.5 * 0.04) / 0.20, rel_tol=1e-5)
    assert math.isclose(d2, d1 - 0.20, rel_tol=1e-5)

    # Invalid boundary inputs
    assert bs_d1_d2(spot=-10.0, strike=100.0, years=1.0, iv=0.20) is None
    assert bs_d1_d2(spot=100.0, strike=0.0, years=1.0, iv=0.20) is None
    assert bs_d1_d2(spot=100.0, strike=100.0, years=-0.1, iv=0.20) is None
    assert bs_d1_d2(spot=100.0, strike=100.0, years=1.0, iv=0.001) is None
    assert bs_d1_d2(spot=100.0, strike=100.0, years=1.0, iv=10.0) is None


def test_calculate_bs_gamma():
    """Verify Gamma calculation against standard Black-Scholes formula."""
    spot = 100.0
    strike = 100.0
    years = 0.25
    iv = 0.30
    rate = 0.045
    gamma = calculate_bs_gamma(spot=spot, strike=strike, years=years, iv=iv, rate=rate)
    assert gamma is not None
    assert gamma > 0.0
    # For ATM with S=100, sigma=0.30, T=0.25: phi(d1)/(100 * 0.30 * 0.5) ~ 0.3989 / 15 ~ 0.0266
    assert 0.020 <= gamma <= 0.035


def test_calculate_bs_charm_per_day():
    """Verify Charm per day calculation and tenor boundary floor."""
    spot = 100.0
    strike = 100.0
    years = 30.0 / 365.0
    iv = 0.25
    rate = 0.045
    charm = calculate_bs_charm_per_day(
        spot=spot, strike=strike, years=years, iv=iv, rate=rate, is_call=True
    )
    assert charm is not None
    # Charm per day is finite and plausible
    assert abs(charm) < 1.0

    # Tenor < 1 day floor returns None to prevent explosion
    charm_sub_day = calculate_bs_charm_per_day(
        spot=spot, strike=strike, years=0.5 / 365.0, iv=iv, rate=rate
    )
    assert charm_sub_day is None


def test_calculate_dollar_gamma_1pct():
    """Verify dollar gamma 1% calculation: OI * M * Gamma * S^2 * 0.01."""
    oi = 1000.0
    gamma = 0.02
    spot = 100.0
    mult = 100.0
    # 1000 * 100 * 0.02 * 10000 * 0.01 = 200,000.0
    dg = calculate_dollar_gamma_1pct(oi, gamma, spot, multiplier=mult)
    assert math.isclose(dg, 200_000.0, rel_tol=1e-6)

    # Edge cases
    assert calculate_dollar_gamma_1pct(0.0, gamma, spot) == 0.0
    assert calculate_dollar_gamma_1pct(oi, -0.01, spot) == 0.0
    assert calculate_dollar_gamma_1pct(oi, gamma, 0.0) == 0.0


# ---------------------------------------------------------------------------
# 2. Vectorized Max Pain Tests
# ---------------------------------------------------------------------------


def test_calculate_max_pain_worked_example():
    """Verify Max Pain finds the exact strike that minimizes total holder intrinsic value.

    Scenario:
      Strikes: [90, 100, 110]
      Calls: 90: 100 OI, 100: 500 OI, 110: 2000 OI
      Puts:  90: 2000 OI, 100: 500 OI, 110: 100 OI
      At K = 90:
        Call Loss: 0
        Put Loss: (100-90)*500 + (110-90)*100 = 5000 + 2000 = 7000
        Total = 7000
      At K = 100:
        Call Loss: (100-90)*100 = 1000
        Put Loss: (110-100)*100 = 1000
        Total = 2000 (MINIMUM)
      At K = 110:
        Call Loss: (110-90)*100 + (110-100)*500 = 2000 + 5000 = 7000
        Put Loss: 0
        Total = 7000
    """
    chain = [
        {"strike": 90.0, "right": "call", "open_interest": 100.0},
        {"strike": 100.0, "right": "call", "open_interest": 500.0},
        {"strike": 110.0, "right": "call", "open_interest": 2000.0},
        {"strike": 90.0, "right": "put", "open_interest": 2000.0},
        {"strike": 100.0, "right": "put", "open_interest": 500.0},
        {"strike": 110.0, "right": "put", "open_interest": 100.0},
    ]
    max_pain = calculate_max_pain(chain, spot=100.0)
    assert max_pain == 100.0


def test_calculate_max_pain_empty_and_zero_oi():
    """Verify Max Pain returns None for invalid or zero OI chains."""
    assert calculate_max_pain([], spot=100.0) is None
    assert (
        calculate_max_pain([{"strike": 100.0, "right": "call", "open_interest": 0.0}], spot=100.0)
        is None
    )
    assert (
        calculate_max_pain([{"strike": 100.0, "right": "call", "open_interest": 100.0}], spot=-5.0)
        is None
    )


# ---------------------------------------------------------------------------
# 3. Gamma Flip S* & Directional Walls Tests
# ---------------------------------------------------------------------------


def test_compute_gamma_flip_and_walls():
    """Verify extraction of directional walls strictly above/below spot and zero-gamma flip."""
    spot = 500.0
    # Calls concentrated at 520, Puts concentrated at 480
    chain = [
        {"strike": 460.0, "right": "put", "open_interest": 2000, "iv": 0.20, "dte": 20},
        {"strike": 480.0, "right": "put", "open_interest": 10000, "iv": 0.20, "dte": 20},
        {"strike": 490.0, "right": "put", "open_interest": 3000, "iv": 0.20, "dte": 20},
        {"strike": 500.0, "right": "call", "open_interest": 1000, "iv": 0.20, "dte": 20},
        {"strike": 500.0, "right": "put", "open_interest": 1000, "iv": 0.20, "dte": 20},
        {"strike": 510.0, "right": "call", "open_interest": 3000, "iv": 0.20, "dte": 20},
        {"strike": 520.0, "right": "call", "open_interest": 12000, "iv": 0.20, "dte": 20},
        {"strike": 540.0, "right": "call", "open_interest": 2500, "iv": 0.20, "dte": 20},
    ]

    flip, call_wall, put_wall, total_gex, mapped = compute_gamma_flip_and_walls(chain, spot=spot)

    # Call Wall must be strictly above spot (520)
    assert call_wall == 520.0
    assert call_wall > spot

    # Put Wall must be strictly below spot (480)
    assert put_wall == 480.0
    assert put_wall < spot

    # Gamma Flip must exist and be within the strike range
    assert flip is not None
    assert 460.0 <= flip <= 540.0
    assert len(mapped) > 0


def test_directional_walls_one_sided_chain():
    """Verify directional walls when all strikes are on one side of spot."""
    spot = 500.0
    # Only strikes above spot
    chain_above = [
        {"strike": 510.0, "right": "call", "open_interest": 5000, "iv": 0.20, "dte": 15},
        {"strike": 520.0, "right": "call", "open_interest": 8000, "iv": 0.20, "dte": 15},
    ]
    _, call_wall, put_wall, _, _ = compute_gamma_flip_and_walls(chain_above, spot=spot)
    assert call_wall == 520.0
    assert put_wall is None  # No strikes below spot


# ---------------------------------------------------------------------------
# 4. Market Regime Classification Tests
# ---------------------------------------------------------------------------


def test_classify_market_regime_positive_gamma():
    """Verify classification of Volatility Dampening (Long Gamma) regime."""
    spot = 100.0
    mapped_gex = [
        {"strike": 90.0, "net_gex_m": -0.5},
        {"strike": 100.0, "net_gex_m": 1.2},
        {"strike": 105.0, "net_gex_m": 3.0},
        {"strike": 110.0, "net_gex_m": 2.5},
    ]
    total_net_gex = sum(r["net_gex_m"] for r in mapped_gex)  # +6.2M

    regime = classify_market_regime(
        spot=spot,
        total_net_gex_m=total_net_gex,
        gamma_flip=92.0,
        mapped_strike_gex=mapped_gex,
        charm_drift_regime="neutral_decay",
        kinematic_regime="mean_reverting",
        expected_move_1d=1.5,
    )

    assert regime.volatility_regime == "positive_gamma"
    assert regime.volatility_behavior == "volatility_dampening"
    assert regime.topography_quadrant == "forward_positive_ramp"
    assert regime.kinematic_regime == "mean_reverting"
    assert 0.0 < regime.regime_strength <= 1.0
    assert regime.measurable is True


def test_classify_market_regime_negative_gamma():
    """Verify classification of Volatility Amplification (Short Gamma) regime."""
    spot = 100.0
    mapped_gex = [
        {"strike": 90.0, "net_gex_m": -4.5},
        {"strike": 95.0, "net_gex_m": -3.0},
        {"strike": 100.0, "net_gex_m": -1.0},
        {"strike": 105.0, "net_gex_m": 0.5},
    ]
    total_net_gex = sum(r["net_gex_m"] for r in mapped_gex)  # -8.0M

    regime = classify_market_regime(
        spot=spot,
        total_net_gex_m=total_net_gex,
        gamma_flip=104.0,  # Spot is below flip
        mapped_strike_gex=mapped_gex,
        charm_drift_regime="selling_drift",
        kinematic_regime="trend_acceleration",
        expected_move_1d=2.0,
    )

    assert regime.volatility_regime == "negative_gamma"
    assert regime.volatility_behavior == "volatility_amplification"
    assert regime.topography_quadrant == "forward_negative_slide"
    assert regime.kinematic_regime == "trend_acceleration"
    assert regime.charm_drift_regime == "selling_drift"
    assert regime.measurable is True


def test_classify_market_regime_neutral_transition():
    """Verify spot inside ±0.25% flip band triggers Neutral Transition."""
    spot = 100.0
    gamma_flip = 100.15  # |100.15 - 100| / 100 = 0.15% <= 0.25%
    mapped_gex = [
        {"strike": 95.0, "net_gex_m": -2.0},
        {"strike": 105.0, "net_gex_m": 2.0},
    ]

    regime = classify_market_regime(
        spot=spot,
        total_net_gex_m=0.0,
        gamma_flip=gamma_flip,
        mapped_strike_gex=mapped_gex,
    )

    assert regime.volatility_regime == "neutral_transition"
    assert regime.volatility_behavior == "neutral_straddle"


# ---------------------------------------------------------------------------
# 5. Charm & Kinematic Drift State-Space Tests
# ---------------------------------------------------------------------------


def test_compute_net_charm_flow():
    """Verify net charm flow calculation and regime detection."""
    spot = 100.0
    # OTM Calls (K > S) -> charm < 0, sign = +1 -> flow < 0 -> buying drift
    chain_calls = [
        {"strike": 105.0, "right": "call", "open_interest": 10000, "dte": 10, "iv": 0.25},
    ]
    flow_calls, regime_calls = compute_net_charm_flow(chain_calls, spot=spot)
    assert flow_calls < 0.0
    assert regime_calls == "buying_drift"

    # ITM Puts (K > S) -> charm < 0, sign = -1 -> flow > 0 -> selling drift
    chain_puts = [
        {"strike": 105.0, "right": "put", "open_interest": 10000, "dte": 10, "iv": 0.25},
    ]
    flow_puts, regime_puts = compute_net_charm_flow(chain_puts, spot=spot)
    assert flow_puts > 0.0
    assert regime_puts == "selling_drift"


def test_compute_kinematic_drift_level():
    """Verify 2-State Kinematic Kalman filter equilibrium price and velocity z-score."""
    spot = 105.0
    # Upward trending series
    price_series = [100.0 + i * 0.5 for i in range(20)]
    p_hat, v_z, regime = compute_kinematic_drift_level(price_series, spot=spot)

    assert p_hat is not None
    assert math.isclose(p_hat, price_series[-1], rel_tol=0.05)
    assert v_z > 0.0  # Positive velocity
    assert regime in {"trend_acceleration", "mean_reverting"}

    # Insufficient history guard
    p_none, v_0, r_none = compute_kinematic_drift_level([100.0, 101.0], spot=spot)
    assert p_none is None
    assert v_0 == 0.0
    assert r_none == "undetermined"


# ---------------------------------------------------------------------------
# 6. Multi-Factor Gravitational Pull & Ranking Tests
# ---------------------------------------------------------------------------


def test_calculate_gravitational_pull_scores():
    """Verify multi-factor pull score bounds and proximity sensitivity."""
    spot = 100.0
    mapped_gex = [{"strike": 105.0, "net_gex_m": 5.0}]

    # Level close to spot (102 vs 100, EM=2.0)
    pull_close, comps_close = calculate_gravitational_pull(
        level_price=102.0,
        spot=spot,
        level_type="call_wall",
        mapped_strike_gex=mapped_gex,
        expected_move_1d=2.0,
    )

    # Level far from spot (120 vs 100, EM=2.0)
    pull_far, comps_far = calculate_gravitational_pull(
        level_price=120.0,
        spot=spot,
        level_type="call_wall",
        mapped_strike_gex=mapped_gex,
        expected_move_1d=2.0,
    )

    assert 0.0 <= pull_close <= 100.0
    assert 0.0 <= pull_far <= 100.0
    # Closer level has higher proximity and higher pull score
    assert comps_close["proximity"] > comps_far["proximity"]
    assert pull_close > pull_far


# ---------------------------------------------------------------------------
# 7. Multi-Lens Confluence Clustering Tests
# ---------------------------------------------------------------------------


def test_detect_confluence_clusters():
    """Verify clustering of multiple attractors within ±0.75% spot tolerance."""
    spot = 100.0
    # Three levels in close proximity: 104.8, 105.0, 105.2 (all within 0.4% of 105)
    lvl1 = PriceMagnetLevel(
        level_id="call_wall",
        label="Call Wall",
        price=105.0,
        distance_points=5.0,
        distance_pct=5.0,
        direction="above",
        gravitational_pull=85.0,
        structural_force="Resistance",
        conviction_rank=1,
        components={},
    )
    lvl2 = PriceMagnetLevel(
        level_id="max_pain",
        label="Max Pain Pin",
        price=105.2,
        distance_points=5.2,
        distance_pct=5.2,
        direction="above",
        gravitational_pull=75.0,
        structural_force="Pin",
        conviction_rank=2,
        components={},
    )
    lvl3 = PriceMagnetLevel(
        level_id="volume_poc",
        label="Volume POC",
        price=104.9,
        distance_points=4.9,
        distance_pct=4.9,
        direction="above",
        gravitational_pull=70.0,
        structural_force="Volume",
        conviction_rank=3,
        components={},
    )
    # Distant level
    lvl4 = PriceMagnetLevel(
        level_id="put_wall",
        label="Put Wall",
        price=92.0,
        distance_points=-8.0,
        distance_pct=-8.0,
        direction="below",
        gravitational_pull=60.0,
        structural_force="Support",
        conviction_rank=4,
        components={},
    )

    clusters = detect_confluence_clusters([lvl1, lvl2, lvl3, lvl4], spot=spot, tolerance_pct=0.75)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert math.isclose(cluster.level, 105.0333, rel_tol=1e-3)
    assert cluster.lens_count == 3
    assert set(cluster.supporting_lenses) == {"GAMMA", "PIN", "VOLUME"}
    assert cluster.above_spot is True


# ---------------------------------------------------------------------------
# 8. Zero-Spoofing and Missing-Data Protocol Tests
# ---------------------------------------------------------------------------


def test_zero_spoofing_missing_chain_data():
    """Verify empty/missing chain data returns explicit measurable: False and unmeasured state."""
    snapshot = compute_price_attractors(symbol="SPY", spot=550.0, chain_rows=[])

    assert snapshot.symbol == "SPY"
    assert snapshot.regime_state == "unmeasurable"
    assert snapshot.regime_strength is None
    assert snapshot.dominant_direction == "unmeasured"
    assert snapshot.primary_magnet is None
    assert len(snapshot.levels) == 0
    assert len(snapshot.price_ladder) == 0
    assert snapshot.quality["measurable"] is False
    assert snapshot.quality["open_interest_available"] is False
    assert len(snapshot.warnings) > 0


def test_zero_spoofing_zero_open_interest():
    """Verify chains with all-zero open interest are flagged unmeasurable without fake zeroes."""
    chain_zero_oi = [
        {"strike": 100.0, "right": "call", "open_interest": 0.0, "volume": 0.0},
        {"strike": 100.0, "right": "put", "open_interest": 0.0, "volume": 0.0},
    ]
    snapshot = compute_price_attractors(symbol="AAPL", spot=220.0, chain_rows=chain_zero_oi)

    assert snapshot.regime_state == "unmeasurable"
    assert snapshot.quality["measurable"] is False
    assert snapshot.quality["open_interest_available"] is False
    assert snapshot.primary_magnet is None


def test_zero_spoofing_non_positive_spot():
    """Verify non-positive spot price is safely rejected."""
    snapshot = compute_price_attractors(
        symbol="NVDA", spot=0.0, chain_rows=_build_synthetic_chain()
    )
    assert snapshot.quality["measurable"] is False
    assert snapshot.spot is None


# ---------------------------------------------------------------------------
# 9. End-to-End Engine & JSON Serialization Tests
# ---------------------------------------------------------------------------


def test_full_price_attractors_pipeline_end_to_end():
    """Verify end-to-end price attractors computation, ladder sorting, and dictionary conversion."""
    spot = 500.0
    chain = _build_synthetic_chain(
        spot=spot,
        strikes=[480.0, 490.0, 500.0, 510.0, 520.0],
        call_ois=[1000.0, 2000.0, 5000.0, 12000.0, 8000.0],
        put_ois=[9000.0, 11000.0, 4000.0, 1500.0, 500.0],
        iv=0.20,
        dte=15.0,
        volume=5000.0,
    )
    price_series = [490.0 + i * 0.5 for i in range(21)]  # 490 to 500

    snapshot = compute_price_attractors(
        symbol="SPY",
        spot=spot,
        chain_rows=chain,
        price_series=price_series,
        asof_utc="2026-08-29T12:00:00Z",
    )

    assert snapshot.symbol == "SPY"
    assert snapshot.spot == 500.0
    assert snapshot.regime_state in {
        "volatility_dampening",
        "volatility_amplification",
        "charm_decay_selling",
        "charm_decay_buying",
        "neutral_transition",
    }
    assert snapshot.primary_magnet is not None
    assert snapshot.primary_magnet.conviction_rank == 1
    assert len(snapshot.levels) >= 3

    # Check Price Ladder sorting: Strictly descending by price
    prices = [lvl.price for lvl in snapshot.price_ladder]
    assert prices == sorted(prices, reverse=True)

    # Check serialization to dict
    d = snapshot.to_dict()
    assert d["symbol"] == "SPY"
    assert d["spot"] == 500.0
    assert isinstance(d["levels"], list)
    assert isinstance(d["price_ladder"], list)
    assert isinstance(d["quality"], dict)
    assert d["quality"]["measurable"] is True
    assert "conviction_rank" in d["primary_magnet"]
    assert "pull_score" in d["primary_magnet"]


# ---------------------------------------------------------------------------
# 10. Advanced Topography Quadrants & Scale-Free Strength Tests
# ---------------------------------------------------------------------------


def test_all_four_topography_quadrants():
    """Verify all four topography quadrants are correctly synthesized."""
    spot = 100.0

    # 1. Forward Positive Ramp (S >= S*, GEX_above >= GEX_below)
    map_fpr = [{"strike": 90.0, "net_gex_m": 1.0}, {"strike": 110.0, "net_gex_m": 5.0}]
    r1 = classify_market_regime(
        spot=spot, total_net_gex_m=6.0, gamma_flip=90.0, mapped_strike_gex=map_fpr
    )
    assert r1.topography_quadrant == "forward_positive_ramp"

    # 2. Backward Positive Ramp (S >= S*, GEX_below > GEX_above)
    map_bpr = [{"strike": 90.0, "net_gex_m": 5.0}, {"strike": 110.0, "net_gex_m": 1.0}]
    r2 = classify_market_regime(
        spot=spot, total_net_gex_m=6.0, gamma_flip=90.0, mapped_strike_gex=map_bpr
    )
    assert r2.topography_quadrant == "backward_positive_ramp"

    # 3. Forward Negative Slide (S < S*, GEX_below <= GEX_above)
    map_fns = [{"strike": 90.0, "net_gex_m": -5.0}, {"strike": 110.0, "net_gex_m": -1.0}]
    r3 = classify_market_regime(
        spot=spot, total_net_gex_m=-6.0, gamma_flip=110.0, mapped_strike_gex=map_fns
    )
    assert r3.topography_quadrant == "forward_negative_slide"

    # 4. Backward Negative Slide (S < S*, GEX_above < GEX_below)
    map_bns = [{"strike": 90.0, "net_gex_m": -1.0}, {"strike": 110.0, "net_gex_m": -5.0}]
    r4 = classify_market_regime(
        spot=spot, total_net_gex_m=-6.0, gamma_flip=110.0, mapped_strike_gex=map_bns
    )
    assert r4.topography_quadrant == "backward_negative_slide"


def test_scale_free_regime_strength_properties():
    """Verify scale-free regime strength bounds and flip distance sensitivity."""
    spot = 100.0
    mapped = [{"strike": 90.0, "net_gex_m": -2.0}, {"strike": 110.0, "net_gex_m": 10.0}]

    # Case A: Very close to flip -> strength close to 0
    r_close = classify_market_regime(
        spot=spot, total_net_gex_m=8.0, gamma_flip=100.05, mapped_strike_gex=mapped
    )
    assert r_close.regime_strength < 0.25

    # Case B: Far from flip with strong GEX -> strength close to 1
    r_far = classify_market_regime(
        spot=spot, total_net_gex_m=50.0, gamma_flip=80.0, mapped_strike_gex=mapped
    )
    assert r_far.regime_strength > 0.70


def test_provider_flexible_field_names():
    """Verify engine gracefully parses mixed provider field names (oi, vol, implied_vol, right/option_type)."""
    spot = 200.0
    chain = [
        {
            "strike": "190.0",
            "option_type": "P",
            "oi": "5000",
            "implied_vol": "0.22",
            "dte": "25",
            "vol": "1200",
        },
        {
            "strike": "210.0",
            "option_type": "C",
            "oi": "8000",
            "implied_vol": "0.22",
            "dte": "25",
            "vol": "3400",
        },
    ]
    snapshot = compute_price_attractors(symbol="TSLA", spot=spot, chain_rows=chain)
    assert snapshot.quality["measurable"] is True
    assert snapshot.primary_magnet is not None
    assert len(snapshot.levels) >= 2
    # Ensure signed point and percentage distances are exact
    for lvl in snapshot.levels:
        assert math.isclose(lvl.distance_points, lvl.price - spot, rel_tol=1e-6)
        assert math.isclose(lvl.distance_pct, (lvl.price - spot) / spot * 100.0, rel_tol=1e-6)
        if lvl.price > spot:
            assert lvl.direction == "above"
        elif lvl.price < spot:
            assert lvl.direction == "below"
        else:
            assert lvl.direction == "at_spot"


def test_log_price_kalman_drift_scale_invariance():
    """Verify log-price Kalman filter velocity z-scores are scale-invariant across stock prices."""
    # Series A: Penny stock ($1.00 -> $1.20)
    prices_a = [1.00 * (1.01 ** i) for i in range(20)]
    _, vz_a, reg_a = compute_kinematic_drift_level(prices_a, spot=prices_a[-1])

    # Series B: Mega stock ($1000.00 -> $1200.00)
    prices_b = [1000.00 * (1.01 ** i) for i in range(20)]
    _, vz_b, reg_b = compute_kinematic_drift_level(prices_b, spot=prices_b[-1])

    # Velocity z-scores must match closely (scale invariance)
    assert vz_a == pytest.approx(vz_b, rel=0.05)
    assert reg_a == reg_b


def test_uncrossed_profile_does_not_collapse_regime_strength_to_zero():
    """Monotonic positive-gamma chains must retain robust regime strength and gamma_flip=None."""
    spot = 500.0
    mapped = [
        {"strike": 480.0, "net_gex_m": 5.0, "call_oi": 5000, "put_oi": 0},
        {"strike": 500.0, "net_gex_m": 12.0, "call_oi": 12000, "put_oi": 0},
        {"strike": 520.0, "net_gex_m": 8.0, "call_oi": 8000, "put_oi": 0},
    ]
    state = classify_market_regime(
        spot=spot,
        total_net_gex_m=25.0,
        gamma_flip=None,
        mapped_strike_gex=mapped,
    )
    assert state.gamma_flip is None
    assert state.volatility_regime == "positive_gamma"
    assert state.topography_quadrant == "unmeasurable"
    assert state.regime_strength >= 0.20


def test_normalized_expected_move_pull_score_smooth_decay():
    """Verify pull score decays smoothly with distance normalized by Expected Move."""
    spot = 500.0
    em = 10.0  # $10 1-day expected move

    pull_05, comp_05 = calculate_gravitational_pull(
        level_price=505.0, spot=spot, level_type="call_wall", expected_move_1d=em
    )
    pull_10, comp_10 = calculate_gravitational_pull(
        level_price=510.0, spot=spot, level_type="call_wall", expected_move_1d=em
    )
    pull_30, comp_30 = calculate_gravitational_pull(
        level_price=530.0, spot=spot, level_type="call_wall", expected_move_1d=em
    )

    assert pull_05 > pull_10 > pull_30
    assert 10.0 <= pull_30 <= pull_10 <= pull_05 <= 100.0
    # Proximity follows Gaussian decay
    assert comp_05["proximity"] > comp_10["proximity"] > comp_30["proximity"]
