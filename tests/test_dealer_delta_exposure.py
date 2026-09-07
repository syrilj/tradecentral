"""Net DEX and the derived VWAP sigma bands.

DEX shares the dealer sign convention with GEX, so the tests that matter are
the ones that would catch a sign or convention slip -- a DEX that agreed with
its own parts but disagreed with the gamma book would read as a real
directional imbalance.
"""
from __future__ import annotations

import numpy as np
import pytest

from edge.research.microstructure_regime import (
    calculate_contract_dex,
    calculate_option_greeks,
    compute_microstructure_regime,
    unmeasurable_regime_snapshot,
)
from edge.research.state_estimation import compute_anchored_vwap


def _chain(oi_call=5000, oi_put=5000, dte=5):
    return [
        {
            "strike": k,
            "right": right,
            "open_interest": oi_call if right == "call" else oi_put,
            "implied_volatility": 0.18,
            "dte": dte,
        }
        for k in range(600, 681, 5)
        for right in ("call", "put")
    ]


def test_put_delta_is_not_clamped_away():
    """Puts carry negative delta; a gamma-style `<= 0` guard would zero them."""
    dex = calculate_contract_dex(open_interest=1000, delta=-0.4, spot=100.0)
    assert dex == pytest.approx(-0.4 * 1000 * 100 * 100.0)
    assert dex < 0


def test_dex_is_zero_without_open_interest():
    assert calculate_contract_dex(open_interest=0, delta=0.5, spot=100.0) == 0.0


def test_net_dex_equals_the_sum_of_its_sides():
    snap = compute_microstructure_regime(_chain(), symbol="SPY", spot=640.0, is_index=True)
    assert snap.quality.measurable is True
    assert snap.net_dex_m == pytest.approx(snap.call_dex_m + snap.put_dex_m, abs=1e-3)


def test_net_dex_equals_the_sum_over_strikes():
    snap = compute_microstructure_regime(_chain(), symbol="SPY", spot=640.0, is_index=True)
    per_strike = sum(s.net_dex_m for s in snap.strikes)
    assert snap.net_dex_m == pytest.approx(per_strike, abs=0.05)


def test_index_convention_leaves_dealers_long_delta_on_a_balanced_chain():
    """Long calls and short puts are both long delta, so the two sides add."""
    snap = compute_microstructure_regime(_chain(), symbol="SPY", spot=640.0, is_index=True)
    assert snap.call_dex_m > 0
    assert snap.put_dex_m > 0
    assert snap.net_dex_m > 0


def test_equity_convention_flips_the_call_side():
    """Under the speculative-equity sign, dealers are short the call book."""
    snap = compute_microstructure_regime(_chain(), symbol="TSLA", spot=640.0, is_index=False)
    assert snap.call_dex_m < 0


def test_heavy_call_open_interest_pushes_dex_short_under_equity_convention():
    """The gamma-squeeze precondition: dealers short a call-heavy book."""
    snap = compute_microstructure_regime(
        _chain(oi_call=50_000, oi_put=1_000), symbol="TSLA", spot=640.0, is_index=False
    )
    assert snap.net_dex_m < 0


def test_unmeasurable_chain_reports_none_not_zero():
    """Zero net DEX is a real reading (a balanced book) and must stay distinct."""
    snap = unmeasurable_regime_snapshot(
        symbol="SPY",
        spot=640.0,
        reason="no chain",
        asof="2026-09-02T14:30:00Z",
        dealer_convention="index",
        contracts=0,
        strikes=0,
        total_open_interest=0,
    )
    assert snap.net_dex_m is None


def test_dex_scales_linearly_with_open_interest():
    base = compute_microstructure_regime(_chain(oi_call=1000, oi_put=1000), symbol="SPY", spot=640.0)
    doubled = compute_microstructure_regime(_chain(oi_call=2000, oi_put=2000), symbol="SPY", spot=640.0)
    assert doubled.net_dex_m == pytest.approx(2 * base.net_dex_m, rel=1e-6)


# --------------------------------------------------------------------------
# VWAP sigma bands
# --------------------------------------------------------------------------


def _series():
    prices = np.array([100, 101, 102, 101, 103, 104, 102, 105], dtype=float)
    volumes = np.array([1000, 1200, 900, 1500, 1100, 1300, 800, 1400], dtype=float)
    return compute_anchored_vwap(prices, volumes, [0], ["session"])[0]


def test_derived_band_reproduces_the_stored_two_sigma_series():
    """The derivation and the stored bands must not be two different answers."""
    result = _series()
    upper, lower = result.band(2)
    assert np.allclose(upper, result.upper_2sd, equal_nan=True)
    assert np.allclose(lower, result.lower_2sd, equal_nan=True)


def test_three_sigma_is_wider_than_two():
    result = _series()
    u3, l3 = result.band(3)
    # Skip the anchor bar, where dispersion is still exactly zero.
    assert np.all(u3[1:] > result.upper_2sd[1:])
    assert np.all(l3[1:] < result.lower_2sd[1:])


def test_sigma_is_non_negative():
    assert np.all(_series().sigma >= 0)
