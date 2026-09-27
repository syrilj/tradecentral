"""0DTE intraday tape engine — the session clock, the magnets, and the bar read.

The bugs these lock down were all found by running the engine against the real
2026-09-04 SPY session (425 same-day contracts, 390 one-minute bars) rather
than against fixtures, so each one is a thing that actually went wrong:

  * an intraday `asof` scored its levels against bars that had not printed yet
  * the gamma flip wandered 144 points into the wings as T went to zero
  * pin / put wall / max pain triple-listed the same strike as three magnets
  * session VWAP borrowed a neighbouring strike's gamma mass
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from edge.research.zero_dte import (
    compute_zero_dte_tape,
    gamma_regime,
    rth_bars,
    session_minutes_remaining,
    year_fraction_remaining,
)


# ---------------------------------------------------------------------------
# Builders


def _bar(ts: datetime, o: float, h: float, low: float, c: float, v: float = 1000.0) -> dict:
    return {"ts": ts, "open": o, "high": h, "low": low, "close": c, "volume": v}


def _session(day: date, closes: list[float], *, start_utc: int = 13, start_min: int = 30) -> list[dict]:
    """One bar per minute from the open, tracing `closes`."""
    base = datetime(day.year, day.month, day.day, start_utc, start_min, tzinfo=timezone.utc)
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        out.append(_bar(base + timedelta(minutes=i), prev, max(prev, c) + 0.05, min(prev, c) - 0.05, c))
        prev = c
    return out


def _chain(expiry: str, rows: list[tuple[float, str, float, float]]) -> list[dict]:
    """(strike, right, volume, iv) -> provider-shaped chain rows."""
    return [
        {"strike": k, "right": r, "volume": v, "openInterest": v, "impliedVolatility": iv,
         "expiry": expiry}
        for k, r, v, iv in rows
    ]


# ---------------------------------------------------------------------------
# Session clock


def test_minutes_remaining_is_dst_correct_in_both_halves_of_the_year():
    # September is EDT (UTC-4): the close is 20:00Z.
    sep = session_minutes_remaining(
        datetime(2026, 9, 4, 19, 0, tzinfo=timezone.utc), expiry=date(2026, 9, 4)
    )
    assert sep == pytest.approx(60.0)
    # January is EST (UTC-5): the same clock time is an hour further from the close.
    jan = session_minutes_remaining(
        datetime(2026, 1, 15, 19, 0, tzinfo=timezone.utc), expiry=date(2026, 1, 15)
    )
    assert jan == pytest.approx(120.0)


def test_minutes_remaining_clamps_outside_the_session():
    day = date(2026, 9, 4)
    assert session_minutes_remaining(datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc), expiry=day) == 390.0
    assert session_minutes_remaining(datetime(2026, 9, 4, 23, 0, tzinfo=timezone.utc), expiry=day) == 0.0


def test_year_fraction_uses_the_trading_clock_not_the_calendar():
    # A full session is one trading day out of 252, not one day out of 365.
    assert year_fraction_remaining(390.0) == pytest.approx(1.0 / 252.0)
    # And it shrinks through the day, which is the whole point for 0DTE.
    assert year_fraction_remaining(30.0) < year_fraction_remaining(300.0)


def test_year_fraction_floors_so_gamma_stays_finite_at_the_bell():
    assert year_fraction_remaining(0.0) > 0.0


def test_rth_bars_drops_extended_hours():
    day = date(2026, 9, 4)
    bars = [
        _bar(datetime(2026, 9, 4, 9, 0, tzinfo=timezone.utc), 770, 771, 769, 770),   # pre-market
        _bar(datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc), 770, 771, 769, 770),  # RTH
        _bar(datetime(2026, 9, 4, 22, 0, tzinfo=timezone.utc), 770, 771, 769, 770),  # post
    ]
    kept = rth_bars(bars, day=day)
    assert len(kept) == 1
    assert kept[0]["ts"].startswith("2026-09-04T14:00")


# ---------------------------------------------------------------------------
# Lookahead


def test_asof_truncates_the_session_so_an_intraday_read_cannot_see_later_bars():
    day = date(2026, 9, 4)
    # Flat until 12:00Z+, then a sharp rally the morning read must not know about.
    closes = [770.0] * 60 + [790.0] * 60
    bars = _session(day, closes)
    chain = _chain("2026-09-04", [(770, "c", 5000, 0.10), (770, "p", 5000, 0.10)])

    early = compute_zero_dte_tape(
        "SPY", bars, chain, expiry="2026-09-04",
        asof=datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc),
    )
    assert early["measurable"]
    assert early["spot"] == pytest.approx(770.0)
    assert early["session"]["high"] == pytest.approx(770.05, abs=0.01)
    assert early["session"]["bars_shown"] == 31

    late = compute_zero_dte_tape(
        "SPY", bars, chain, expiry="2026-09-04",
        asof=datetime(2026, 9, 4, 15, 30, tzinfo=timezone.utc),
    )
    assert late["spot"] == pytest.approx(790.0)
    assert late["session"]["bars_shown"] > early["session"]["bars_shown"]


# ---------------------------------------------------------------------------
# Gamma sharpens through the session


def test_the_same_chain_concentrates_on_the_atm_strike_as_the_close_approaches():
    day = date(2026, 9, 4)
    bars = _session(day, [770.0] * 300)
    chain = _chain(
        "2026-09-04",
        [(k, r, 2000, 0.10) for k in (765, 770, 775) for r in ("c", "p")],
    )

    def atm_mass(asof_hour: int, asof_min: int) -> float:
        out = compute_zero_dte_tape(
            "SPY", bars, chain, expiry="2026-09-04",
            asof=datetime(2026, 9, 4, asof_hour, asof_min, tzinfo=timezone.utc),
        )
        # Look the strike up by price: 770 is also the flip/max-pain here, so
        # the merge legitimately leads it with a different label.
        at_770 = next(lv for lv in out["levels"] if abs(lv["price"] - 770.0) < 0.6)
        return at_770["components"]["mass"]

    # Same chain, same bars — only the clock moves. Gamma goes as 1/sqrt(T), so
    # the at-the-money strike must own strictly more of the profile late.
    assert atm_mass(19, 30) > atm_mass(14, 0)


def test_expected_move_shrinks_through_the_session():
    day = date(2026, 9, 4)
    bars = _session(day, [770.0] * 300)
    chain = _chain("2026-09-04", [(770, "c", 2000, 0.10), (770, "p", 2000, 0.10)])
    early = compute_zero_dte_tape("SPY", bars, chain, expiry="2026-09-04",
                                  asof=datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc))
    late = compute_zero_dte_tape("SPY", bars, chain, expiry="2026-09-04",
                                 asof=datetime(2026, 9, 4, 19, 30, tzinfo=timezone.utc))
    assert late["gamma"]["expected_move"] < early["gamma"]["expected_move"]


# ---------------------------------------------------------------------------
# Flip


def test_flip_ignores_wing_noise_far_from_spot():
    day = date(2026, 9, 4)
    bars = _session(day, [770.0] * 120)
    # Real mass at 769/771; a token contract 150 points away that a naive
    # nearest-crossing search would happily latch onto.
    chain = _chain(
        "2026-09-04",
        [(769, "p", 9000, 0.10), (771, "c", 9000, 0.10), (920, "c", 1, 0.10), (919, "p", 1, 0.10)],
    )
    out = compute_zero_dte_tape("SPY", bars, chain, expiry="2026-09-04",
                                asof=datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc))
    flip = out["gamma"]["flip"]
    assert flip is None or abs(flip - out["spot"]) < 50


def test_gamma_regime_reads_off_the_flip_not_an_aggregate_sign():
    assert gamma_regime(775.0, 770.0)[0] == "above_flip"
    assert gamma_regime(765.0, 770.0)[0] == "below_flip"
    assert gamma_regime(770.0, None)[0] == "unmeasured"


def test_tilt_is_scale_free():
    day = date(2026, 9, 4)
    bars = _session(day, [770.0] * 120)
    calls_only = _chain("2026-09-04", [(771, "c", 9000, 0.10), (772, "c", 4000, 0.10)])
    out = compute_zero_dte_tape("SPY", bars, calls_only, expiry="2026-09-04",
                                asof=datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc))
    assert out["gamma"]["tilt"] == pytest.approx(1.0)
    assert -1.0 <= out["gamma"]["tilt"] <= 1.0


# ---------------------------------------------------------------------------
# Levels


def test_colocated_levels_merge_into_one_magnet_with_its_confluence_named():
    day = date(2026, 9, 4)
    bars = _session(day, [772.0] * 120)
    # One dominant strike below spot: it is the pin, the put wall and max pain.
    chain = _chain(
        "2026-09-04",
        [(770, "p", 40000, 0.10), (770, "c", 200, 0.10), (780, "c", 300, 0.10)],
    )
    out = compute_zero_dte_tape("SPY", bars, chain, expiry="2026-09-04",
                                asof=datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc))
    at_770 = [lv for lv in out["levels"] if abs(lv["price"] - 770.0) < 0.5]
    assert len(at_770) == 1, "the same strike must not be listed as several magnets"
    assert at_770[0]["lens_count"] > 1
    assert at_770[0]["confluence"]


def test_vwap_does_not_borrow_gamma_mass_from_a_nearby_strike():
    day = date(2026, 9, 4)
    bars = _session(day, [770.0] * 120)
    chain = _chain("2026-09-04", [(770, "c", 9000, 0.10), (770, "p", 9000, 0.10)])
    out = compute_zero_dte_tape("SPY", bars, chain, expiry="2026-09-04",
                                asof=datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc))
    vwap = [lv for lv in out["levels"] if lv["kind"] == "vwap"]
    if vwap:  # merged away when it lands on the pin, which is fine
        assert vwap[0]["components"]["mass"] == 0.0
        assert vwap[0]["gex_at_strike_m"] is None


def test_pull_falls_off_with_distance_measured_in_expected_moves():
    day = date(2026, 9, 4)
    bars = _session(day, [770.0] * 120)
    chain = _chain(
        "2026-09-04",
        [(771, "c", 5000, 0.10), (771, "p", 5000, 0.10), (800, "c", 5000, 0.10), (800, "p", 5000, 0.10)],
    )
    out = compute_zero_dte_tape("SPY", bars, chain, expiry="2026-09-04",
                                asof=datetime(2026, 9, 4, 19, 0, tzinfo=timezone.utc))
    near = [lv for lv in out["levels"] if abs(lv["price"] - 771) < 1]
    far = [lv for lv in out["levels"] if abs(lv["price"] - 800) < 1]
    assert near, "the near strike should be a level"
    if far:
        assert near[0]["pull"] > far[0]["pull"]


# ---------------------------------------------------------------------------
# Bar interaction and intent


def test_touches_and_rejections_are_counted_off_the_actual_bars():
    day = date(2026, 9, 4)
    base = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)
    # Every bar wicks up through 771 and closes back at the bottom of its range.
    bars = [_bar(base + timedelta(minutes=i), 770.0, 771.5, 769.9, 770.0) for i in range(40)]
    chain = _chain("2026-09-04", [(771, "c", 30000, 0.10), (765, "p", 500, 0.10)])
    out = compute_zero_dte_tape("SPY", bars, chain, expiry="2026-09-04",
                                asof=base + timedelta(minutes=39))
    at_771 = next(lv for lv in out["levels"] if abs(lv["price"] - 771.0) < 0.5)
    ix = at_771["interaction"]
    assert ix["touches"] == 40
    assert ix["rejections"] == 40, "a wick through that closes back is a rejection"


def test_acceptance_is_counted_when_price_sits_on_the_level():
    day = date(2026, 9, 4)
    base = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)
    bars = [_bar(base + timedelta(minutes=i), 771.0, 771.1, 770.9, 771.0) for i in range(40)]
    chain = _chain("2026-09-04", [(771, "c", 30000, 0.10), (771, "p", 30000, 0.10)])
    out = compute_zero_dte_tape("SPY", bars, chain, expiry="2026-09-04",
                                asof=base + timedelta(minutes=39))
    at_771 = next(lv for lv in out["levels"] if abs(lv["price"] - 771.0) < 0.5)
    assert at_771["interaction"]["accept_ratio"] > 0.9
    assert out["intent"]["state"] in {"pinning", "magnetized", "ranging"}


def test_intent_carries_its_evidence_and_never_a_bare_verdict():
    day = date(2026, 9, 4)
    bars = _session(day, [770.0 + i * 0.02 for i in range(60)])
    chain = _chain("2026-09-04", [(772, "c", 20000, 0.10), (768, "p", 20000, 0.10)])
    out = compute_zero_dte_tape("SPY", bars, chain, expiry="2026-09-04",
                                asof=datetime(2026, 9, 4, 14, 59, tzinfo=timezone.utc))
    assert out["intent"]["headline"]
    assert out["intent"]["evidence"], "a verdict with nothing behind it is not usable"


# ---------------------------------------------------------------------------
# Refusals — the engine must say it cannot measure rather than invent


def test_empty_chain_is_unmeasurable_not_a_fabricated_level():
    bars = _session(date(2026, 9, 4), [770.0] * 60)
    out = compute_zero_dte_tape("SPY", bars, [], expiry="2026-09-04")
    assert out["measurable"] is False
    assert out["levels"] == []
    assert out["reason"]


def test_no_bars_is_unmeasurable():
    chain = _chain("2026-09-04", [(770, "c", 1000, 0.10)])
    out = compute_zero_dte_tape("SPY", [], chain, expiry="2026-09-04")
    assert out["measurable"] is False


def test_chain_without_volume_falls_back_to_open_interest_and_says_so():
    bars = _session(date(2026, 9, 4), [770.0] * 60)
    chain = [
        {"strike": 770, "right": "c", "volume": 0, "openInterest": 5000, "impliedVolatility": 0.1},
        {"strike": 770, "right": "p", "volume": 0, "openInterest": 5000, "impliedVolatility": 0.1},
    ]
    out = compute_zero_dte_tape("SPY", bars, chain, expiry="2026-09-04",
                                asof=datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc))
    assert out["gamma"]["weight_basis"] == "open_interest"
    assert any("open interest" in w for w in out["warnings"])


def test_bars_from_a_different_session_are_flagged_not_passed_off_as_the_expiry():
    # Chain expires Tuesday; the only bars available are Friday's.
    bars = _session(date(2026, 9, 4), [770.0] * 60)
    chain = _chain("2026-09-08", [(770, "c", 5000, 0.10), (770, "p", 5000, 0.10)])
    out = compute_zero_dte_tape("SPY", bars, chain, expiry="2026-09-08")
    assert out["measurable"] is True
    assert any("2026-09-04" in w for w in out["warnings"])


def test_bars_are_returned_so_the_caller_can_draw_the_actual_candles():
    bars = _session(date(2026, 9, 4), [770.0, 770.5, 771.0])
    chain = _chain("2026-09-04", [(770, "c", 5000, 0.10), (770, "p", 5000, 0.10)])
    out = compute_zero_dte_tape("SPY", bars, chain, expiry="2026-09-04",
                                asof=datetime(2026, 9, 4, 13, 32, tzinfo=timezone.utc))
    assert len(out["bars"]) == 3
    assert set(out["bars"][0]) == {"ts", "open", "high", "low", "close", "volume"}


# ---------------------------------------------------------------------------
# Implied-vol fallback
#
# Yahoo quotes 0.0 implied vol for most near-the-money SPX *calls* while its
# puts are fine. Dropping those rows does not give a thin profile, it gives a
# put-only one — and a flip and tilt that are artefacts of the gap.


def _split_iv_chain() -> list[dict]:
    """Calls with a broken IV, puts quoted properly — the Yahoo SPX shape."""
    rows = []
    for k in (7700, 7710, 7715, 7720, 7730):
        rows.append({"strike": k, "right": "c", "volume": 4000, "openInterest": 4000,
                     "impliedVolatility": 0.0})
        rows.append({"strike": k, "right": "p", "volume": 4000, "openInterest": 4000,
                     "impliedVolatility": 0.15})
    return rows


def test_contracts_with_a_broken_iv_borrow_the_expiry_vol_instead_of_vanishing():
    bars = _session(date(2026, 9, 4), [7715.0] * 60, )
    out = compute_zero_dte_tape("SPX", bars, _split_iv_chain(), expiry="2026-09-04",
                                asof=datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc),
                                spot_override=7715.0)
    assert out["measurable"]
    # Both sides present: a call wall can only exist if the calls survived.
    kinds = {lv["kind"] for lv in out["levels"]} | {
        k for lv in out["levels"] for k in lv["confluence"]
    }
    assert "call_wall" in kinds or out["gamma"]["tilt"] > -0.9
    assert out["quality"]["iv_fallback_rows"] > 0


def test_the_borrowed_iv_count_is_reported_so_the_caller_can_caveat_it():
    bars = _session(date(2026, 9, 4), [7715.0] * 60)
    out = compute_zero_dte_tape("SPX", bars, _split_iv_chain(), expiry="2026-09-04",
                                asof=datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc),
                                spot_override=7715.0)
    assert out["quality"]["iv_fallback_rows"] == 5, "one per broken call"


def test_a_chain_with_no_usable_iv_anywhere_is_unmeasurable_not_invented():
    bars = _session(date(2026, 9, 4), [7715.0] * 60)
    rows = [
        {"strike": k, "right": r, "volume": 100, "openInterest": 100, "impliedVolatility": 0.0}
        for k in (7700, 7715, 7730)
        for r in ("c", "p")
    ]
    out = compute_zero_dte_tape("SPX", bars, rows, expiry="2026-09-04",
                                asof=datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc),
                                spot_override=7715.0)
    assert out["measurable"] is False
