"""Stacked-signals lenses: theta/vanna exposure, IV surface, volume profile.

Each lens is an independent read on the same chain/tape; the payload stacks
them so no single Greek has to carry the whole picture. Tests pin the dealer
sign conventions, the skip-don't-clamp rule for missing inputs, and the fact
that confluence is a descriptive cluster — never a probability.
"""
from datetime import datetime, timezone

import pytest

from edge.daily_plays.options_intelligence import (
    OptionsFilters,
    _bs_theta_per_day,
    _bs_vanna,
    _stacked_confluence,
    _stacked_iv_surface,
    _stacked_theta_vanna,
    _stacked_volume_profile,
    build_options_intelligence,
)


ASOF = datetime(2026, 7, 31, 15, 0, tzinfo=timezone.utc)
SPOT = 100.0


def _chain(strikes, *, dte=14, iv=0.45):
    rows = []
    for strike in strikes:
        for right in ("call", "put"):
            rows.append({
                "right": right,
                "expiry": "2026-08-14",
                "strike": float(strike),
                # Normalized chain rows carry dte alongside expiry; these
                # helpers run post-filter, so the fixture mirrors that shape.
                "dte": dte,
                "bid": 1.0,
                "ask": 1.2,
                "volume": 50 + max(0, 100 - abs(strike - SPOT)) * 10,
                "open_interest": 500 + max(0, 200 - abs(strike - SPOT)) * 20,
                "iv": iv,
                "multiplier": 100,
                "captured_utc": ASOF.isoformat(),
                "spot": SPOT,
            })
    return rows


def test_theta_is_negative_for_long_premium_and_put_heavy_near_atm():
    put_theta = _bs_theta_per_day(spot=100, strike=95, years=14 / 365, iv=0.45, rate=0.045, is_call=False)
    call_theta = _bs_theta_per_day(spot=100, strike=105, years=14 / 365, iv=0.45, rate=0.045, is_call=True)
    assert put_theta is not None and call_theta is not None
    assert put_theta < 0 and call_theta < 0


def test_vanna_sign_flips_across_the_money():
    otm_call_vanna = _bs_vanna(spot=100, strike=120, years=30 / 365, iv=0.45, rate=0.045)
    otm_put_vanna = _bs_vanna(spot=100, strike=80, years=30 / 365, iv=0.45, rate=0.045)
    assert otm_call_vanna is not None and otm_put_vanna is not None
    # OTM calls gain delta as IV rises (positive vanna); OTM puts lose it.
    assert otm_call_vanna > 0 > otm_put_vanna


def test_theta_and_vanna_skip_contracts_without_usable_inputs():
    rows, theta_summary, _, vanna_summary, skipped = _stacked_theta_vanna(
        chain_rows=[
            {"right": "call", "strike": 100.0, "dte": 14, "iv": None, "open_interest": 10},
            {"right": "put", "strike": 100.0, "dte": 0, "iv": 0.45, "open_interest": 10},
        ],
        spot=SPOT,
        rate=0.045,
    )
    assert rows == []
    assert skipped == 2
    assert theta_summary["source"] == "black_scholes_theta"
    assert vanna_summary["regime"] is None


def test_theta_flow_sums_by_strike_with_dealer_signs():
    rows, theta_summary, _, _, skipped = _stacked_theta_vanna(
        chain_rows=_chain([90, 100, 110]),
        spot=SPOT,
        rate=0.045,
    )
    assert skipped == 0
    strikes = [row["strike"] for row in rows]
    assert strikes == [90.0, 100.0, 110.0]
    for row in rows:
        # Long premium decays: call and put theta flows are both negative.
        assert row["call_theta_flow"] < 0 and row["put_theta_flow"] < 0
        assert row["net_theta_flow"] == pytest.approx(
            row["call_theta_flow"] + row["put_theta_flow"], abs=1e-6,
        )
    assert theta_summary["net_theta_flow"] < 0


def test_iv_surface_walls_and_skew():
    chain = [
        {"right": "put", "strike": 85.0, "iv": 0.62, "open_interest": 4_000, "volume": 100},
        {"right": "call", "strike": 115.0, "iv": 0.55, "open_interest": 3_000, "volume": 100},
        {"right": "call", "strike": 100.0, "iv": 0.40, "open_interest": 900, "volume": 900},
        {"right": "put", "strike": 100.0, "iv": 0.42, "open_interest": 900, "volume": 900},
    ]
    surface_rows, summary = _stacked_iv_surface(chain_rows=chain, spot=SPOT)
    by_strike = {row["strike"]: row for row in surface_rows}
    assert by_strike[100.0]["skew"] == pytest.approx(-0.02, abs=1e-9)  # mild put skew
    assert summary["available"] is True
    assert summary["atm_iv"] == pytest.approx(0.41, abs=1e-6)
    assert summary["peak_put_iv_strike"] == 85.0
    assert summary["peak_call_iv_strike"] == 115.0
    assert summary["put_iv_wall"] == 85.0
    assert summary["call_iv_wall"] == 115.0


def test_volume_profile_poc_value_area_and_lvns():
    bars = []
    # Heavy trading around 100, thin around 108.
    prices = [99.5] * 8 + [100.0] * 10 + [100.5] * 6 + [107.9] * 1 + [109.0] * 4
    for idx, close in enumerate(prices):
        bars.append({"close": close, "volume": 1_000_000 - idx * 1_000})
    profile, summary = _stacked_volume_profile(price_series=bars)
    assert summary["available"] is True
    assert summary["poc"] == pytest.approx(100.0, abs=0.6)
    assert summary["value_area_low"] <= summary["poc"] <= summary["value_area_high"]
    assert any(bin_["in_value_area"] for bin_ in profile)
    assert summary["lvn_count"] >= 1
    assert summary["method"].startswith("daily-bar")


def test_volume_profile_unavailable_without_enough_bars():
    profile, summary = _stacked_volume_profile(price_series=[{"close": 100, "volume": 10}])
    assert profile == []
    assert summary["available"] is False


def test_confluence_clusters_multi_lens_levels_only_descriptively():
    clusters = _stacked_confluence(
        spot=SPOT,
        call_wall=120.0, put_wall=80.0, gamma_flip=None, pin_strike=None,
        theta_decay_strike=119.6, vanna_pivot=None,
        call_iv_wall=120.4, put_iv_wall=None,
        poc=None, value_area_low=None, value_area_high=121.0,
    )
    top = clusters[0]
    assert top["lens_count"] == 3
    assert set(top["supporting_lenses"]) == {"gamma", "iv", "theta"}
    assert top["above_spot"] is True
    # Descriptive geometry only — never a probability or authorization.
    for cluster in clusters:
        assert abs(cluster["distance_pct"]) < 0.5
        assert "probability" not in cluster


def test_payload_carries_stacked_signals_block():
    payload = build_options_intelligence(
        symbol="TEST",
        chain_rows=_chain([90, 95, 100, 105, 110]),
        flow_rows=[],
        price_series=[{"t": f"2026-07-{day:02d}T20:00:00+00:00", "close": 98 + (day % 5) * 0.7, "volume": 900_000}
                      for day in range(1, 29)],
        spot=SPOT,
        filters=OptionsFilters(range="1d", min_premium=50_000, min_volume=1),
        mode_requested="live",
        mode_resolved="live",
        chain_source="fixture",
        flow_source="unavailable",
        asof_utc=ASOF,
    )
    stack = payload["stacked_signals"]
    assert stack["theta_by_strike"], "theta rows must exist when IV+OI are present"
    assert stack["vanna_summary"]["net_vanna_flow"] is not None
    assert stack["iv_summary"]["available"] is True
    assert stack["quality"]["theta_vanna_contracts_measured"] > 0
    # Volume profile needs ≥5 priced bars; this fixture supplies 28 daily closes.
    assert stack["volume_profile_summary"]["available"] is True
    for cluster in stack["confluence"]:
        assert isinstance(cluster["lens_count"], int)
