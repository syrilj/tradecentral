"""GEX / OI walls, expiry totals, and OI-by-strike from the shipped builder."""
from __future__ import annotations

from datetime import datetime, timezone

from edge.daily_plays.options_intelligence import OptionsFilters, build_options_intelligence


ASOF = datetime(2026, 7, 31, 15, 0, tzinfo=timezone.utc)


def _contract(right: str, strike: float, expiry: str, oi: int, gamma: float) -> dict:
    return {
        "right": right,
        "expiry": expiry,
        "strike": strike,
        "bid": 2.0,
        "ask": 2.2,
        "volume": 100,
        "open_interest": oi,
        "iv": 0.35,
        "gamma": gamma,
        "multiplier": 100,
        "captured_utc": ASOF.isoformat(),
        "quote_live": True,
        "quote_source": "fixture",
        "spot": 100,
    }


def test_walls_zero_gamma_expiry_totals_and_oi_by_strike():
    chain = [
        _contract("call", 110, "2026-08-28", 8_000, 0.03),
        _contract("put", 90, "2026-08-28", 7_000, 0.03),
        _contract("call", 110, "2026-09-18", 2_000, 0.02),
        _contract("put", 90, "2026-09-18", 3_000, 0.02),
        _contract("call", 100, "2026-08-28", 1_000, 0.05),
        _contract("put", 100, "2026-08-28", 1_000, 0.05),
    ]
    result = build_options_intelligence(
        symbol="TEST",
        chain_rows=chain,
        flow_rows=[],
        price_series=[{"t": ASOF.isoformat(), "close": 100, "volume": 1_000_000}],
        spot=100,
        filters=OptionsFilters(range="1d", min_premium=0, min_volume=0, min_open_interest=0, expiry="all"),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="fixture",
        asof_utc=ASOF,
    )
    summary = result["summary"]
    assert summary["call_wall"] == 110
    assert summary["put_wall"] == 90
    assert summary["call_wall"] > 100
    assert summary["put_wall"] < 100
    zero = summary.get("zero_gamma")
    if zero is None:
        zero = summary["gamma_flip"]
    assert zero is not None
    assert summary["put_wall"] < zero < summary["call_wall"]

    oi_by_strike = {row["strike"]: row for row in result["oi_by_strike"]}
    assert oi_by_strike[110]["call_oi"] == 10_000
    assert oi_by_strike[110]["put_oi"] == 0
    assert oi_by_strike[110]["total_oi"] == 10_000
    assert oi_by_strike[90]["put_oi"] == 10_000
    assert oi_by_strike[90]["call_oi"] == 0
    assert oi_by_strike[100]["total_oi"] == 2_000
    assert sum(row["total_oi"] for row in result["oi_by_strike"]) == 22_000

    by_expiry = {row["expiry"]: row for row in result["gex_by_expiry"]}
    assert by_expiry["2026-08-28"]["call_oi"] == 9_000
    assert by_expiry["2026-08-28"]["put_oi"] == 8_000
    assert by_expiry["2026-09-18"]["call_oi"] == 2_000
    assert by_expiry["2026-09-18"]["put_oi"] == 3_000
    assert summary["call_oi"] == 11_000
    assert summary["put_oi"] == 11_000
