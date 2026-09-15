"""Unit tests for calibrated expected move engine."""

import pytest
import pandas as pd
from edge.research.expected_move import (
    compute_expected_move_1d,
    compute_calibrated_expected_move,
)


def test_monotonic_boundaries():
    """Verify tail_low < expected_low < median_low < spot < median_high < expected_high < tail_high."""
    res = compute_calibrated_expected_move(spot=100.0, fallback_iv=0.30, dte=5.0)

    assert res.tail_low_95 < res.expected_low < res.median_low < res.spot
    assert res.spot < res.median_high < res.expected_high < res.tail_high_95
    assert res.expected_move_1sigma > 0
    assert pytest.approx(res.expected_high - res.spot, rel=1e-4) == res.expected_move_up
    assert pytest.approx(res.spot - res.expected_low, rel=1e-4) == res.expected_move_down


def test_skew_asymmetry_put_heavy():
    """Verify put skew (e.g. SPY/AAPL index downside hedge) creates asymmetric downside move."""
    chain = [
        {"strike": 100.0, "right": "C", "impliedVolatility": 0.15, "bid": 1.0, "ask": 1.2},
        {"strike": 100.0, "right": "P", "impliedVolatility": 0.35, "bid": 2.0, "ask": 2.4},
    ]
    res = compute_calibrated_expected_move(spot=100.0, dte=30.0, chain_df_or_rows=chain)

    assert res.call_skew_ratio < 0.50
    assert res.expected_move_down > res.expected_move_up * 2.0
    assert res.straddle_price is not None
    assert pytest.approx(res.straddle_price, rel=1e-4) == 1.1 + 2.2


def test_skew_asymmetry_call_heavy():
    """Verify call skew (e.g. TSLA/NVDA upside squeeze bid) creates asymmetric upside move."""
    chain = [
        {"strike": 300.0, "right": "C", "impliedVolatility": 0.60, "bid": 10.0, "ask": 11.0},
        {"strike": 300.0, "right": "P", "impliedVolatility": 0.30, "bid": 4.0, "ask": 5.0},
    ]
    res = compute_calibrated_expected_move(spot=300.0, dte=7.0, chain_df_or_rows=chain)

    assert res.call_skew_ratio > 1.8
    assert res.expected_move_up > res.expected_move_down * 1.8


def test_calendar_scaling_vs_trading_days():
    """Verify calendar scaling avoids the +20% inflation bug of 1/252."""
    em_cal = compute_expected_move_1d(spot=100.0, iv=0.20, dte=1.0, calendar_days=True)
    em_252 = compute_expected_move_1d(spot=100.0, iv=0.20, dte=1.0, calendar_days=False)

    # sqrt(365/252) ~= 1.2034 -> em_252 is 20.3% wider than em_cal
    assert em_252 > em_cal
    assert pytest.approx(em_252 / em_cal, rel=1e-3) == 1.2034