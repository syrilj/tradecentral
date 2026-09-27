"""Vanna surface: by-expiry aggregation, sign conventions, pivot, endpoint data contract.

The arithmetic tests feed a small synthetic chain straight into
``_stacked_theta_vanna`` (pure math, no parquet, no network) and into the pure
``aggregate_vanna_by_expiry`` / ``compute_vanna_pivot`` helpers; only
``compute_vanna_surface`` touches ``tools.api_server``, with the cached-chain
loader monkeypatched — the same pattern as tests/test_gamma_regime_endpoint.py.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from edge.daily_plays.options_intelligence import _bs_vanna, _stacked_theta_vanna
from edge.daily_plays.vanna_exposure import (
    aggregate_vanna_by_expiry,
    compute_vanna_pivot,
    compute_vanna_surface,
)

SPOT = 590.0
RATE = 0.045
ASOF_DAY = date(2026, 9, 14)

# Two calls + one put, two strikes, two expiries — matches _normalize_chain_row's
# output shape (what _stacked_theta_vanna consumes).
CHAIN = [
    {"strike": 580.0, "right": "call", "dte": 4, "iv": 0.25, "open_interest": 1000, "multiplier": 100, "volume": 50},
    {"strike": 600.0, "right": "call", "dte": 32, "iv": 0.22, "open_interest": 500, "multiplier": 100, "volume": 25},
    {"strike": 580.0, "right": "put", "dte": 4, "iv": 0.28, "open_interest": 800, "multiplier": 100, "volume": 40},
]


def _expected_flows() -> tuple[float, float, float]:
    """flow = sign * vanna * OI * multiplier * spot; sign: call +1 / put -1."""
    v_a = _bs_vanna(spot=SPOT, strike=580.0, years=4 / 365.0, iv=0.25, rate=RATE)
    v_b = _bs_vanna(spot=SPOT, strike=600.0, years=32 / 365.0, iv=0.22, rate=RATE)
    v_c = _bs_vanna(spot=SPOT, strike=580.0, years=4 / 365.0, iv=0.28, rate=RATE)
    assert v_a is not None and v_b is not None and v_c is not None
    return (
        v_a * 1000 * 100 * SPOT,      # call A, strike 580, dte 4
        v_b * 500 * 100 * SPOT,       # call B, strike 600, dte 32
        -1.0 * v_c * 800 * 100 * SPOT,  # put C, strike 580, dte 4 (dealer sign)
    )


def test_by_strike_sign_conventions_exact_arithmetic():
    flow_a, flow_b, flow_c = _expected_flows()
    by_strike, _theta_summary, _contracts, vanna_summary, skipped = _stacked_theta_vanna(
        chain_rows=CHAIN, spot=SPOT, rate=RATE
    )
    assert skipped == 0
    cells = {row["strike"]: row for row in by_strike}

    assert cells[580.0]["call_vanna_flow"] == pytest.approx(round(flow_a, 4))
    assert cells[580.0]["put_vanna_flow"] == pytest.approx(round(flow_c, 4))
    assert cells[580.0]["net_vanna_flow"] == pytest.approx(round(flow_a + flow_c, 4))
    assert cells[600.0]["call_vanna_flow"] == pytest.approx(round(flow_b, 4))
    assert cells[600.0]["put_vanna_flow"] == 0.0
    assert cells[600.0]["net_vanna_flow"] == pytest.approx(round(flow_b, 4))

    # Summary net = sum of per-strike nets (each rounded at the cell level).
    assert vanna_summary["net_vanna_flow"] == pytest.approx(
        round(round(flow_a + flow_c, 4) + round(flow_b, 4), 4)
    )
    assert vanna_summary["source"] == "black_scholes_vanna"
    assert vanna_summary["regime"] in {
        "iv_up_supportive",
        "iv_up_pressuring",
        "neutral",
    }


def test_aggregate_vanna_by_expiry_pure_grouping():
    flow_a, flow_b, flow_c = _expected_flows()
    _by_strike, _theta_summary, contract_rows, _summary, skipped = _stacked_theta_vanna(
        chain_rows=CHAIN, spot=SPOT, rate=RATE
    )
    assert skipped == 0

    by_expiry = aggregate_vanna_by_expiry(contract_rows, ASOF_DAY)
    assert [(row["expiry"], row["dte"]) for row in by_expiry] == [
        ("2026-09-18", 4),
        ("2026-10-16", 32),
    ]
    assert by_expiry[0]["call_vanna_flow"] == pytest.approx(round(flow_a, 4))
    assert by_expiry[0]["put_vanna_flow"] == pytest.approx(round(flow_c, 4))
    assert by_expiry[0]["net_vanna_flow"] == pytest.approx(round(flow_a + flow_c, 4))
    assert by_expiry[1]["call_vanna_flow"] == pytest.approx(round(flow_b, 4))
    assert by_expiry[1]["put_vanna_flow"] == 0.0
    assert by_expiry[1]["net_vanna_flow"] == pytest.approx(round(flow_b, 4))


def test_pivot_zero_crossing_interpolates():
    rows = [
        {"strike": 100.0, "net_vanna_flow": 10.0},
        {"strike": 110.0, "net_vanna_flow": -30.0},
    ]
    # Cumulative: +10 at 100, -20 at 110 → zero at 100 + 10 * 10/30.
    assert compute_vanna_pivot(rows, spot=105.0) == pytest.approx(103.3333, abs=1e-3)


def test_pivot_fallback_dominant_strike_when_one_sided():
    rows = [
        {"strike": 100.0, "net_vanna_flow": 10.0},
        {"strike": 110.0, "net_vanna_flow": 30.0},
        {"strike": 120.0, "net_vanna_flow": 5.0},
    ]
    assert compute_vanna_pivot(rows, spot=118.0) == 110.0


def test_pivot_none_on_empty_surface():
    assert compute_vanna_pivot([], spot=100.0) is None


def _raw_snapshot_rows() -> list[dict]:
    """Raw cached-chain rows as the data/option_chains parquet carries them."""
    return [
        {"expiry": "2026-09-18", "right": "call", "strike": 580.0, "iv": 0.25, "open_interest": 1000, "multiplier": 100, "spot": SPOT},
        {"expiry": "2026-10-16", "right": "call", "strike": 600.0, "iv": 0.22, "open_interest": 500, "multiplier": 100, "spot": SPOT},
        {"expiry": "2026-09-18", "right": "put", "strike": 580.0, "iv": 0.28, "open_interest": 800, "multiplier": 100, "spot": SPOT},
    ]


def test_compute_vanna_surface_contract(monkeypatch):
    from edge.tools import api_server

    monkeypatch.setattr(
        api_server,
        "_historical_option_rows",
        lambda symbol, **kwargs: (_raw_snapshot_rows(), "2026-09-14", ["2026-09-14"]),
    )
    payload = compute_vanna_surface(
        "TEST", asof=datetime(2026, 9, 14, 15, 30, tzinfo=timezone.utc)
    )
    assert payload is not None
    assert set(payload) == {
        "symbol", "asof", "spot", "vanna_summary", "by_strike",
        "by_expiry", "vanna_pivot", "event_context",
    }
    assert payload["symbol"] == "TEST"
    assert payload["spot"] == SPOT
    assert payload["vanna_summary"]["source"] == "black_scholes_vanna"
    assert payload["vanna_summary"]["contracts_skipped"] == 0
    assert payload["vanna_summary"]["direction"] in {
        "iv_up_supportive", "iv_up_pressuring", "neutral",
    }
    assert [row["strike"] for row in payload["by_strike"]] == [580.0, 600.0]
    assert [(row["expiry"], row["dte"]) for row in payload["by_expiry"]] == [
        ("2026-09-18", 4),
        ("2026-10-16", 32),
    ]
    assert payload["vanna_pivot"] is not None
    assert payload["event_context"]["phase"] == "pre_fomc"

    # Same numbers as the pure-path test — endpoint adds normalization only.
    flow_a, flow_b, flow_c = _expected_flows()
    cells = {row["strike"]: row for row in payload["by_strike"]}
    assert cells[580.0]["call_vanna_flow"] == pytest.approx(round(flow_a, 4))
    assert cells[580.0]["put_vanna_flow"] == pytest.approx(round(flow_c, 4))
    assert cells[600.0]["net_vanna_flow"] == pytest.approx(round(flow_b, 4))


def test_compute_vanna_surface_returns_none_without_chain(monkeypatch):
    from edge.tools import api_server

    monkeypatch.setattr(
        api_server, "_historical_option_rows", lambda symbol, **kwargs: ([], None, [])
    )
    assert compute_vanna_surface("ZZZZ") is None
