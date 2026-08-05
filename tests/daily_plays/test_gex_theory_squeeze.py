"""Theory-aligned bullish/bearish gamma-squeeze math — worked examples + unit tests."""
from __future__ import annotations

import math

import pytest

from edge.daily_plays.gex_core import (
    amplification_factor,
    compute_theory_squeeze,
    dealer_hedge_flow_notional,
    dealer_option_delta_shares,
    delta_after_move,
    dollar_gamma_1pct,
    hedge_share_change,
    hedge_shares_for_delta,
    impact_return,
    short_premium_gex_1pct_m,
    squeeze_risk,
    directional_squeeze_scores,
)


def test_bullish_gamma_squeeze_worked_example():
    """Customers buy 10k calls; dealers short; rally lifts delta → more buying.

    S=100, Δ=0.40, Γ=0.08, q=−10_000.
    Initial hedge H = 400_000 shares long.
    After +$1: Δ→0.48, H→480_000, additional buy = 80_000 shares.
    """
    s, delta0, gamma, q, mult = 100.0, 0.40, 0.08, -10_000.0, 100.0
    d_options = dealer_option_delta_shares(q, delta0, multiplier=mult)
    assert d_options == -400_000.0
    h0 = hedge_shares_for_delta(d_options)
    assert h0 == 400_000.0

    dS = 1.0
    delta1 = delta_after_move(delta0, gamma, dS)
    assert abs(delta1 - 0.48) < 1e-12
    d_options_1 = dealer_option_delta_shares(q, delta1, multiplier=mult)
    h1 = hedge_shares_for_delta(d_options_1)
    assert abs(h1 - 480_000.0) < 1e-6
    assert abs((h1 - h0) - 80_000.0) < 1e-6

    # Equivalent via dH = −q M Γ dS
    assert abs(hedge_share_change(q, gamma, dS, multiplier=mult) - 80_000.0) < 1e-6


def test_bearish_downside_gamma_squeeze_worked_example():
    """Customers buy 10k puts; dealers short; selloff deepens put delta → more selling.

    S=100, Δ_put=−0.40, Γ=0.08, q=−10_000.
    Initial hedge H = −400_000 (short stock).
    After −$1: Δ→−0.48, H→−480_000, additional short = 80_000 shares.
    """
    s, delta0, gamma, q, mult = 100.0, -0.40, 0.08, -10_000.0, 100.0
    d_options = dealer_option_delta_shares(q, delta0, multiplier=mult)
    assert d_options == 400_000.0
    h0 = hedge_shares_for_delta(d_options)
    assert h0 == -400_000.0

    dS = -1.0
    delta1 = delta_after_move(delta0, gamma, dS)
    assert abs(delta1 - (-0.48)) < 1e-12
    h1 = hedge_shares_for_delta(dealer_option_delta_shares(q, delta1, multiplier=mult))
    assert abs(h1 - (-480_000.0)) < 1e-6
    assert abs((h0 - h1) - 80_000.0) < 1e-6  # additional short shares

    # dH = −q M Γ dS = −(−10000)(100)(0.08)(−1) = −80_000 (more short)
    assert abs(hedge_share_change(q, gamma, dS, multiplier=mult) - (-80_000.0)) < 1e-6


def test_dealer_hedge_flow_short_gamma_buys_rallies_sells_declines():
    """DollarGamma = −$500M → +1% buys $5M, −1% sells $5M."""
    dg = -500_000_000.0
    assert abs(dealer_hedge_flow_notional(dg, 0.01) - 5_000_000.0) < 1e-3
    assert abs(dealer_hedge_flow_notional(dg, -0.01) - (-5_000_000.0)) < 1e-3


def test_amplification_table():
    for f, expected in [(0.20, 1.25), (0.50, 2.0), (0.75, 4.0), (0.90, 10.0)]:
        amp = amplification_factor(f)
        assert amp is not None
        assert abs(amp - expected) < 1e-9
    assert amplification_factor(1.0) is None


def test_impact_return_dampens_when_long_gamma():
    r0 = 0.02
    # DG > 0 long gamma
    r = impact_return(r0, lambda_impact=1e-9, dollar_gamma=5e8)
    assert abs(r) < abs(r0)


def test_impact_return_amplifies_when_short_gamma():
    r0 = 0.02
    r = impact_return(r0, lambda_impact=1e-9, dollar_gamma=-5e8)
    assert abs(r) > abs(r0)


def test_dollar_gamma_1pct_formula():
    # OI=10000, Γ=0.05, S=100, M=100 → 10000*100*0.05*10000*0.01 = 5e6
    assert abs(dollar_gamma_1pct(10_000, 0.05, 100.0) - 5_000_000.0) < 1e-3


def test_short_premium_gex_always_non_positive():
    rows = [
        {"right": "call", "strike": 100, "gamma": 0.05, "open_interest": 10_000, "multiplier": 100, "dte": 5},
        {"right": "put", "strike": 100, "gamma": 0.05, "open_interest": 8_000, "multiplier": 100, "dte": 5},
    ]
    gex = short_premium_gex_1pct_m(rows, spot=100.0)
    assert gex["total_gex_m"] < 0
    assert gex["call_gex_m"] < 0
    assert gex["put_gex_m"] < 0
    assert gex["atm_share"] > 0.9  # both ATM


def test_directional_scores_favour_aligned_flow_and_momentum():
    sr = 1.0
    # Call buying + up move → bullish dominates
    d = directional_squeeze_scores(
        squeeze_risk_value=sr, call_imbalance=0.5, momentum=0.03,
    )
    assert d["bullish_score"] > d["bearish_score"]
    assert d["bearish_score"] == 0
    assert 0 < d["bullish_score"] <= 1.0

    # Put side + down move → bearish dominates
    d2 = directional_squeeze_scores(
        squeeze_risk_value=sr, call_imbalance=-0.5, momentum=-0.03,
    )
    assert d2["bearish_score"] > d2["bullish_score"]
    assert d2["bullish_score"] == 0

    # Aligned beats conflicted at identical fuel: flow and momentum agreeing
    # must outscore the same flow fighting the tape.
    assert d["bullish_score"] > directional_squeeze_scores(
        squeeze_risk_value=sr, call_imbalance=0.5, momentum=-0.03,
    )["bullish_score"]


def test_conflicting_flow_and_momentum_report_two_way_not_zero():
    """Full fuel + call tape into a falling price is coiled, not quiet.

    The old form multiplied the directional gates, so a disagreement drove both
    legs to exactly zero and the ``two_way`` readout was unreachable.
    """
    d = directional_squeeze_scores(
        squeeze_risk_value=1.0, call_imbalance=1.0, momentum=-0.03,
    )
    assert d["fuel_ui"] > 0.99
    assert d["bullish_score"] > 0
    assert d["bearish_score"] > 0
    # Symmetric conflict → no net directional edge, but both legs loaded.
    assert d["net_directional"] == pytest.approx(0.0, abs=1e-9)


def test_no_fuel_means_no_squeeze_in_either_direction():
    """Fuel stays multiplicative: no short dealer gamma ⇒ nothing to squeeze."""
    d = directional_squeeze_scores(
        squeeze_risk_value=0.0, call_imbalance=1.0, momentum=0.05,
    )
    assert d["bullish_score"] == 0
    assert d["bearish_score"] == 0


def test_squeeze_risk_scales_with_neg_gex_atm_and_urgency():
    base = squeeze_risk(neg_gex_1pct_m=-100.0, adv_m=50.0, atm_share=0.5, weighted_dte=30.0)
    more_fuel = squeeze_risk(neg_gex_1pct_m=-200.0, adv_m=50.0, atm_share=0.5, weighted_dte=30.0)
    more_atm = squeeze_risk(neg_gex_1pct_m=-100.0, adv_m=50.0, atm_share=1.0, weighted_dte=30.0)
    shorter = squeeze_risk(neg_gex_1pct_m=-100.0, adv_m=50.0, atm_share=0.5, weighted_dte=2.0)
    pos = squeeze_risk(neg_gex_1pct_m=50.0, adv_m=50.0, atm_share=1.0, weighted_dte=2.0)
    assert more_fuel > base
    assert more_atm > base
    assert shorter > base
    assert pos == 0.0


def test_compute_theory_squeeze_bullish_setup():
    """Call-heavy short-dated OI + call imbalance + up momentum → bullish_squeeze."""
    rows = [
        {"right": "call", "strike": 101, "gamma": 0.08, "open_interest": 50_000, "multiplier": 100, "dte": 2},
        {"right": "put", "strike": 99, "gamma": 0.02, "open_interest": 5_000, "multiplier": 100, "dte": 2},
    ]
    out = compute_theory_squeeze(
        chain_rows=rows,
        spot=100.0,
        adv_notional=50_000_000.0,  # $50M ADV
        call_imbalance=0.6,
        momentum=0.04,
        score_scale=40.0,
    )
    assert out["squeeze_label"] == "bullish_squeeze"
    assert out["squeeze_score"] >= 20
    assert out["bullish_score_raw"] > out["bearish_score_raw"]


def test_compute_theory_squeeze_bearish_setup():
    rows = [
        {"right": "put", "strike": 99, "gamma": 0.08, "open_interest": 50_000, "multiplier": 100, "dte": 2},
        {"right": "call", "strike": 101, "gamma": 0.02, "open_interest": 5_000, "multiplier": 100, "dte": 2},
    ]
    out = compute_theory_squeeze(
        chain_rows=rows,
        spot=100.0,
        adv_notional=50_000_000.0,
        call_imbalance=-0.6,
        momentum=-0.04,
        score_scale=40.0,
    )
    assert out["squeeze_label"] == "bearish_squeeze"
    assert out["squeeze_score"] <= -20


def test_short_gamma_without_directional_shock_stays_neutral():
    """Fuel alone is not a directional squeeze — need flow × momentum."""
    rows = [
        {"right": "call", "strike": 100, "gamma": 0.1, "open_interest": 100_000, "multiplier": 100, "dte": 1},
        {"right": "put", "strike": 100, "gamma": 0.1, "open_interest": 100_000, "multiplier": 100, "dte": 1},
    ]
    out = compute_theory_squeeze(
        chain_rows=rows,
        spot=100.0,
        adv_notional=10_000_000.0,
        call_imbalance=0.0,
        momentum=0.0,
        score_scale=40.0,
    )
    assert out["squeeze_label"] == "neutral"
    assert out["squeeze_risk"] > 0  # fuel present
    assert abs(out["squeeze_score"]) < 20
