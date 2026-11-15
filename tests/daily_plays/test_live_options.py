"""The live panel reads gamma levels and the chart. Missing stays missing."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from edge.daily_plays.gamma_resistance import (
    _Leg,
    _net_revalued,
    _net_revalued_grid,
    gamma_resistance_from_chain,
)
from edge.daily_plays.live_options import build_live_options, chart_stance, levels_to_watch

ASOF = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
RATE = 0.045


def _contract(right: str, strike: float, *, oi: float = 1000, iv: float | None = 0.25) -> dict:
    return {
        "right": right,
        "strike": strike,
        "open_interest": oi,
        "iv": iv,
        "dte": 30,
        "expiry": (ASOF.date() + timedelta(days=30)).isoformat(),
        "multiplier": 100,
        "spot": 100.0,
        "captured_utc": ASOF.isoformat(),
    }


def _book() -> dict:
    return gamma_resistance_from_chain(
        [
            _contract("call", 110, oi=2_000),
            _contract("put", 96, oi=800),
            _contract("put", 91, oi=40_000),
        ],
        spot=100.0,
        asof=ASOF,
        now=ASOF,
        rate=RATE,
    )


def _closes(start: float, step: float, n: int = 6) -> list[dict]:
    return [{"date": f"2026-11-{day:02d}", "close": start + step * day} for day in range(1, n + 1)]


def test_nearby_support_stays_the_close_shelf_and_zero_stays_off_when_unpriced():
    panel = build_live_options(_book(), _closes(99.0, 0.05))
    roles = {level["role"]: level["level"] for level in panel["levels"]}
    assert roles["nearby_support"] == 96
    assert roles["put_wall"] == 91
    assert 0 not in roles.values()
    assert panel["decision_authorized"] is False
    assert "order" not in panel

    priced = [
        _contract("call", 110, oi=50_000),
        _contract("put", 90, oi=50_000),
    ]
    quoted = [
        {
            "right": "call",
            "strike": strike,
            "open_interest": 10,
            "gamma": 0.01,
            "dte": 30,
            "spot": 100,
            "captured_utc": ASOF.isoformat(),
        }
        for strike in (98, 100, 102)
    ]
    thin = gamma_resistance_from_chain(
        [*priced, *quoted], spot=100.0, asof=ASOF, now=ASOF, rate=RATE
    )
    assert thin["zero_gamma"] is None
    watched = levels_to_watch(thin)
    assert all(level["role"] != "zero_gamma" for level in watched)
    assert all(level["level"] != 0 for level in watched)


def test_chart_agrees_when_price_holds_the_pin():
    stance = chart_stance(
        spot=100,
        closes=[100.1, 99.9, 100.05, 99.95, 100.0, 100.02],
        call_resistance=105,
        nearby_support=96,
        zero_gamma=99,
        absolute_gamma_strike=100,
        regime="positive",
    )
    assert stance["stance"] == "agrees"
    assert stance["sentence"] == "The chart is holding near the gamma pin."
    assert stance["move_pct"] == 0 or abs(stance["move_pct"]) <= 0.0025


def test_chart_is_opposite_when_it_leaves_the_pin():
    stance = chart_stance(
        spot=100,
        closes=[100, 100.4, 100.8, 101.2, 101.6, 102.0],
        call_resistance=110,
        nearby_support=96,
        zero_gamma=99,
        absolute_gamma_strike=100,
        regime="positive",
    )
    assert stance["stance"] == "opposite"
    assert stance["sentence"] == "The chart is moving away from the gamma pin."


def test_negative_gamma_agrees_when_the_move_extends():
    stance = chart_stance(
        spot=100,
        closes=[100, 99.6, 99.2, 98.8, 98.4, 98.0],
        call_resistance=110,
        nearby_support=90,
        zero_gamma=103,
        absolute_gamma_strike=100,
        regime="negative",
    )
    assert stance["stance"] == "agrees"
    assert "extending away from zero gamma" in stance["sentence"]


def test_spot_above_call_resistance_is_stretched():
    stance = chart_stance(
        spot=112,
        closes=[108, 109, 110, 111, 111.5, 112],
        call_resistance=105,
        nearby_support=96,
        zero_gamma=100,
        absolute_gamma_strike=100,
        regime="positive",
    )
    assert stance["stance"] == "stretched"
    assert stance["sentence"] == "Spot is above call resistance."


def test_missing_chart_stays_blank():
    stance = chart_stance(
        spot=100,
        closes=None,
        call_resistance=105,
        nearby_support=96,
        zero_gamma=99,
        absolute_gamma_strike=100,
        regime="positive",
    )
    assert stance["stance"] is None
    assert stance["reason"] == "chart_missing"
    assert stance["move_pct"] is None


def test_missing_spot_is_not_a_zero():
    stance = chart_stance(
        spot=None,
        closes=[100, 101],
        call_resistance=105,
        nearby_support=96,
        zero_gamma=99,
        absolute_gamma_strike=100,
        regime="positive",
    )
    assert stance["stance"] is None
    assert stance["reason"] == "spot_missing"
    assert levels_to_watch({"spot": None, "zero_gamma": 0, "absolute_gamma_strike": 0}) == []


def test_revalued_grid_matches_scalar_and_is_faster():
    """The panel's zero-gamma scan is the hot path. The broadcast has to match
    the scalar Black-Scholes loop and cost less. Rust stays out unless it wins
    this comparison; this test is the Python side of that measurement."""
    legs = []
    for index in range(400):
        strike = 50.0 + (index % 80)
        legs.append(
            _Leg(
                strike=strike,
                right="call" if index % 2 == 0 else "put",
                oi=100 + (index % 50) * 20,
                gamma=0.02,
                iv=0.15 + (index % 20) * 0.01,
                years=(7 + (index % 40)) / 365.0,
                yield_rate=0.0 if index % 5 else 0.015,
                multiplier=100,
                revaluable=True,
            )
        )
    spots = [80.0 + step * 0.25 for step in range(201)]
    scalar = [_net_revalued(legs, spot, RATE) for spot in spots]
    grid = _net_revalued_grid(legs, spots, RATE)
    assert grid is not None
    assert all(value is not None for value in scalar)
    for left, right in zip(scalar, grid):
        assert abs(left - right) <= 1e-6 * max(1.0, abs(left))

    def _elapsed(fn, repeats: int) -> float:
        start = time.perf_counter()
        for _ in range(repeats):
            fn()
        return time.perf_counter() - start

    _net_revalued_grid(legs, spots, RATE)
    vector = _elapsed(lambda: _net_revalued_grid(legs, spots, RATE), 3)
    scalar_once = _elapsed(lambda: [_net_revalued(legs, spot, RATE) for spot in spots], 1)
    assert scalar_once > (vector / 3.0) * 2.0
