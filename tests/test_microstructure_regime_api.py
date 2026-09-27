"""Tests for Microstructure Regime, State Estimation, Anchored VWAP, and Systematic Backtest API endpoints."""
from __future__ import annotations

import pytest

from edge.tools.api_server import (
    _microstructure_regime_payload,
    _state_estimation_payload,
    _anchored_vwap_payload,
    _systematic_signals_payload,
    _systematic_backtest_payload,
)


def test_microstructure_regime_payload():
    """Shape contract, and the withholding contract when there is no chain.

    This used to assert `isinstance(payload["hedging_flow_m"], float)` and a
    populated profile, which passed in a bare checkout only because the endpoint
    invented a 31-strike option chain whenever the real one was missing. The
    endpoint no longer does that, so in an environment with no market data the
    correct payload is an explicitly unmeasurable one -- and the test now checks
    for exactly that rather than for the fabrication.
    """
    payload, status = _microstructure_regime_payload("SPY", {"rate": ["0.045"]})
    assert status == 200
    assert payload["symbol"] == "SPY"
    for key in (
        "regime",
        "regime_strength",
        "topography",
        "call_wall",
        "put_wall",
        "gamma_flip",
        "gex_profile",
        "strikes",
        "quality",
        "hedging_flow_m",
    ):
        assert key in payload, key

    quality = payload["quality"]
    assert quality["dealer_convention"] == "index"

    if quality["measurable"]:
        assert payload["regime"] in {"positive_gamma", "negative_gamma", "neutral_transition"}
        assert payload["gex_profile"]
        assert payload["strikes"]
    else:
        # No chain -> no claim. Nothing numeric may survive, or the UI cannot
        # tell a withheld read apart from a genuinely balanced one.
        assert payload["regime"] == "unmeasurable"
        assert payload["gamma_flip"] is None
        assert payload["call_wall"] is None
        assert payload["put_wall"] is None
        assert payload["hedging_flow_m"] is None
        assert payload["gex_profile"] == []
        assert payload["strikes"] == []
        assert payload["topography"]["quadrant"] == "unmeasurable"
        assert quality["reason"]


def test_state_estimation_payload():
    payload, status = _state_estimation_payload(
        "SPY",
        {"window": ["1y"], "h": ["20.0"], "alpha": ["2.0"], "q": ["0.001"]},
    )
    assert status == 200
    assert payload["symbol"] == "SPY"
    assert "points" in payload
    assert len(payload["points"]) > 0
    pt0 = payload["points"][0]
    assert "price" in pt0
    assert "nw_mean" in pt0
    assert "nw_upper" in pt0
    assert "nw_lower" in pt0
    assert "kalman_velocity" in pt0
    assert "kalman_zscore" in pt0


def test_anchored_vwap_payload():
    payload, status = _anchored_vwap_payload("SPY", {"window": ["1y"]})
    assert status == 200
    assert payload["symbol"] == "SPY"
    assert "anchors" in payload
    assert len(payload["anchors"]) > 0
    anchor0 = payload["anchors"][0]
    assert "anchor_name" in anchor0
    assert "series" in anchor0
    assert len(anchor0["series"]) > 0


def test_systematic_signals_payload():
    payload, status = _systematic_signals_payload("SPY", {"window": ["1y"]})
    assert status == 200
    assert payload["symbol"] == "SPY"
    assert "signals" in payload
    assert len(payload["signals"]) > 0
    assert "latest_signal" in payload


def test_systematic_backtest_payload():
    payload, status = _systematic_backtest_payload(
        "SPY",
        {"window": ["1y"], "capital": ["100000.0"], "risk_pct": ["0.02"]},
    )
    assert status == 200
    assert payload["symbol"] == "SPY"
    assert "total_net_pnl" in payload
    assert "sharpe_ratio" in payload
    assert "max_drawdown_pct" in payload
    assert "equity_curve" in payload
    assert "trades" in payload
    assert "regime_breakdown" in payload
