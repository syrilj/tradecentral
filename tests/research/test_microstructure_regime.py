"""Unit and integration tests for Microstructure Regime Dynamics, Dealer Greeks & Topography."""
from __future__ import annotations

import math
import pytest
import numpy as np

from edge.research.microstructure_regime import (
    bs_d1_d2,
    calculate_option_greeks,
    calculate_contract_gex,
    calculate_contract_vex,
    calculate_contract_chex,
    compute_microstructure_regime,
    OptionGreeks,
    SharedLevels,
    _nearest_flip,
)


def test_bs_d1_d2_valid_and_invalid():
    # Standard ATM call
    d1_d2 = bs_d1_d2(spot=100.0, strike=100.0, years=1.0, iv=0.20, rate=0.05)
    assert d1_d2 is not None
    d1, d2 = d1_d2
    assert math.isclose(d1, (0.05 + 0.5 * 0.04) / 0.20, rel_tol=1e-5)
    assert math.isclose(d2, d1 - 0.20, rel_tol=1e-5)

    # Invalid inputs
    assert bs_d1_d2(spot=-10.0, strike=100.0, years=1.0, iv=0.20) is None
    assert bs_d1_d2(spot=100.0, strike=0.0, years=1.0, iv=0.20) is None
    assert bs_d1_d2(spot=100.0, strike=100.0, years=-0.5, iv=0.20) is None
    assert bs_d1_d2(spot=100.0, strike=100.0, years=1.0, iv=0.001) is None


def test_calculate_option_greeks():
    # ATM Call
    greeks_c = calculate_option_greeks(
        spot=500.0, strike=500.0, years=30.0 / 365.25, iv=0.20, right="call", rate=0.045
    )
    assert greeks_c is not None
    assert 0.45 < greeks_c.delta < 0.60
    assert greeks_c.gamma > 0.0
    assert greeks_c.vega > 0.0
    assert greeks_c.theta < 0.0  # Daily time decay is negative for long call
    assert isinstance(greeks_c.vanna, float)
    assert isinstance(greeks_c.charm, float)
    assert isinstance(greeks_c.speed, float)
    assert isinstance(greeks_c.zomma, float)

    # ATM Put
    greeks_p = calculate_option_greeks(
        spot=500.0, strike=500.0, years=30.0 / 365.25, iv=0.20, right="put", rate=0.045
    )
    assert greeks_p is not None
    assert -0.55 < greeks_p.delta < -0.40
    # Put Gamma equals Call Gamma
    assert math.isclose(greeks_c.gamma, greeks_p.gamma, rel_tol=1e-5)
    # Put Vega equals Call Vega
    assert math.isclose(greeks_c.vega, greeks_p.vega, rel_tol=1e-5)


def test_exposure_formulas():
    spot = 500.0
    gamma = 0.015
    oi = 10_000
    gex = calculate_contract_gex(open_interest=oi, gamma=gamma, spot=spot, multiplier=100.0)
    # GEX = 10,000 * 100 * 0.015 * (500^2) * 0.01 = 37,500,000
    assert math.isclose(gex, 37_500_000.0, rel_tol=1e-4)

    vanna = -0.5
    vex = calculate_contract_vex(open_interest=oi, vanna=vanna, spot=spot)
    assert vex < 0.0

    charm = 0.002
    chex = calculate_contract_chex(open_interest=oi, charm=charm, spot=spot)
    assert chex > 0.0


def test_compute_microstructure_regime_index_and_topography():
    spot = 500.0
    strikes = [480, 490, 500, 510, 520]
    chain = []
    for k in strikes:
        chain.append({
            "strike": k,
            "right": "call",
            "open_interest": 5000 if k >= 500 else 1000,
            "volume": 500,
            "implied_volatility": 0.18,
            "dte": 15,
        })
        chain.append({
            "strike": k,
            "right": "put",
            "open_interest": 6000 if k <= 500 else 1000,
            "volume": 400,
            "implied_volatility": 0.22,
            "dte": 15,
        })

    snapshot = compute_microstructure_regime(
        chain,
        symbol="SPY",
        spot=spot,
        asof="2026-08-28T16:00:00Z",
        is_index=True,
        ds_dt_pct=0.005,
        dvol_dt_pct=-0.01,
    )

    assert snapshot.symbol == "SPY"
    assert snapshot.spot == spot
    # Walls are directional: resistance strictly above spot, support strictly
    # below. A global argmax put both on the same ATM strike.
    assert snapshot.call_wall > spot
    assert snapshot.put_wall < spot
    assert snapshot.gamma_flip is None or snapshot.gamma_flip > 0
    assert snapshot.regime in {"positive_gamma", "negative_gamma", "neutral_transition"}
    assert snapshot.topography.quadrant in {
        "forward_positive_ramp",
        "backward_positive_ramp",
        "forward_negative_slide",
        "backward_negative_slide",
        "unmeasurable",
    }
    assert len(snapshot.strikes) == len(strikes)
    assert len(snapshot.gex_profile) > 0
    assert isinstance(snapshot.hedging_flow_m, float)  # both velocities supplied
    assert snapshot.quality.measurable is True
    assert snapshot.quality.dealer_convention == "index"
    assert 0.0 <= snapshot.regime_strength <= 1.0


def _flat_chain(spot: float, *, call_oi: int, put_oi: int, strikes=(480, 490, 500, 510, 520)):
    chain = []
    for k in strikes:
        chain.append({"strike": k, "right": "call", "open_interest": call_oi,
                      "volume": 10, "implied_volatility": 0.20, "dte": 15})
        chain.append({"strike": k, "right": "put", "open_interest": put_oi,
                      "volume": 10, "implied_volatility": 0.20, "dte": 15})
    return chain


def test_empty_and_zero_oi_chains_are_withheld_not_zeroed():
    """A chain with nothing in it must not render as a neutral read."""
    for chain in ([], _flat_chain(500.0, call_oi=0, put_oi=0)):
        snap = compute_microstructure_regime(chain, symbol="SPY", spot=500.0, asof="")
        assert snap.regime == "unmeasurable"
        assert snap.quality.measurable is False
        assert snap.quality.reason
        # Every structural level withheld -- not defaulted to spot or a
        # percentage of it, which reads on screen exactly like a real level.
        assert snap.gamma_flip is None
        assert snap.call_wall is None
        assert snap.put_wall is None
        assert snap.volatility_trigger is None
        assert snap.topography.quadrant == "unmeasurable"
        assert snap.strikes == []


def test_flip_is_none_when_net_gamma_never_changes_sign():
    """No zero crossing means no flip -- not spot * 0.95."""
    # Calls only, index convention: dealer gamma is positive at every test spot.
    chain = [
        {"strike": k, "right": "call", "open_interest": 8000,
         "volume": 10, "implied_volatility": 0.20, "dte": 15}
        for k in (480, 490, 500, 510, 520)
    ]
    snap = compute_microstructure_regime(chain, symbol="SPY", spot=500.0, asof="")
    assert snap.gamma_flip is None
    assert snap.quality.flip_located is False
    assert snap.topography.quadrant == "unmeasurable"
    # The directional read survives -- only the boundary is missing.
    assert snap.regime == "positive_gamma"
    assert snap.net_gex_m > 0


def test_flip_picks_the_crossing_nearest_spot():
    """Scanning bottom-up returned whichever root sat lowest in the range."""
    profile = [
        {"spot": 400.0, "net_gex_m": -50.0},
        {"spot": 410.0, "net_gex_m": 50.0},   # crossing at ~405, far below
        {"spot": 495.0, "net_gex_m": 50.0},
        {"spot": 505.0, "net_gex_m": -50.0},  # crossing at 500, at the money
    ]
    assert _nearest_flip(profile, 500.0) == pytest.approx(500.0, abs=0.5)
    assert _nearest_flip(profile, 402.0) == pytest.approx(405.0, abs=0.5)
    assert _nearest_flip([{"spot": 1.0, "net_gex_m": 5.0}, {"spot": 2.0, "net_gex_m": 7.0}], 1.5) is None


def test_regime_sign_never_contradicts_net_gex():
    """Positive net GEX must not classify as negative_gamma.

    The old rule required `net_gex > 0 AND spot > flip`, so a positive-gamma
    chain read as "negative_gamma" whenever spot happened to sit below the flip
    -- printed next to the positive net GEX figure it contradicted.
    """
    chain = _flat_chain(500.0, call_oi=20000, put_oi=100)
    snap = compute_microstructure_regime(chain, symbol="SPY", spot=500.0, asof="")
    assert snap.net_gex_m > 0
    assert snap.regime != "negative_gamma"


def test_hedging_flow_withheld_without_measured_velocities():
    """An instantaneous flow rate needs a measured velocity, not an assumed one."""
    chain = _flat_chain(500.0, call_oi=5000, put_oi=6000)
    assert compute_microstructure_regime(chain, symbol="SPY", spot=500.0, asof="").hedging_flow_m is None
    with_vel = compute_microstructure_regime(
        chain, symbol="SPY", spot=500.0, asof="", ds_dt_pct=0.01, dvol_dt_pct=-0.01
    )
    assert isinstance(with_vel.hedging_flow_m, float)


def test_shared_levels_are_adopted_verbatim():
    """Upstream levels win, so the page cannot show two answers at once."""
    chain = _flat_chain(500.0, call_oi=5000, put_oi=6000)
    solo = compute_microstructure_regime(chain, symbol="SPY", spot=500.0, asof="")
    shared = compute_microstructure_regime(
        chain,
        symbol="SPY",
        spot=500.0,
        asof="",
        shared_levels=SharedLevels(
            gex_profile=[
                {"spot": 450.0, "net_gex_m": -120.0},
                {"spot": 500.0, "net_gex_m": 40.0},
                {"spot": 550.0, "net_gex_m": 200.0},
            ],
            call_wall=515.0,
            put_wall=485.0,
        ),
    )
    assert shared.call_wall == 515.0
    assert shared.put_wall == 485.0
    # The flip comes off the supplied curve, not a parallel measurement.
    assert 450.0 < shared.gamma_flip < 500.0
    assert shared.gamma_flip != solo.gamma_flip
    # The supplied curve read at spot is reported explicitly...
    assert shared.net_gex_profile_m == pytest.approx(40.0, abs=1e-6)
    # ...but does NOT replace the per-strike sum, whose components must keep
    # adding up. Silently substituting it would leave call + put != net on
    # screen, which is the exact contradiction this rework removes.
    assert shared.net_gex_m == pytest.approx(shared.call_gex_m + shared.put_gex_m, abs=1e-3)
    assert solo.net_gex_m == pytest.approx(solo.call_gex_m + solo.put_gex_m, abs=1e-3)


def test_call_and_put_components_always_sum_to_net():
    """The one invariant a reader will check by eye on the Greeks card."""
    for oi in ((5000, 6000), (20000, 100), (100, 20000)):
        snap = compute_microstructure_regime(
            _flat_chain(500.0, call_oi=oi[0], put_oi=oi[1]), symbol="SPY", spot=500.0, asof=""
        )
        assert snap.net_gex_m == pytest.approx(snap.call_gex_m + snap.put_gex_m, abs=1e-3)


def test_regime_strength_is_scale_free():
    """The old 0.70 + net_gex/500 pinned to its ceiling on any index."""
    small = compute_microstructure_regime(
        _flat_chain(500.0, call_oi=200, put_oi=240), symbol="TINY", spot=500.0, asof=""
    )
    large = compute_microstructure_regime(
        _flat_chain(500.0, call_oi=2_000_000, put_oi=2_400_000), symbol="SPX", spot=500.0, asof=""
    )
    # Same relative posture, wildly different absolute size -> same strength.
    assert large.regime_strength == pytest.approx(small.regime_strength, abs=0.05)
    assert 0.0 <= small.regime_strength <= 1.0
