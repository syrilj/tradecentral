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
    assert snapshot.call_wall >= spot
    assert snapshot.put_wall <= spot
    assert snapshot.gamma_flip > 0
    assert snapshot.regime in {"positive_gamma", "negative_gamma", "neutral_transition"}
    assert snapshot.topography.quadrant in {
        "forward_positive_ramp",
        "backward_positive_ramp",
        "forward_negative_slide",
        "backward_negative_slide",
    }
    assert len(snapshot.strikes) == len(strikes)
    assert len(snapshot.synthetic_gex_profile) > 0
    assert isinstance(snapshot.hedging_flow_m, float)
