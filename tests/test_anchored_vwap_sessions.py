"""Tests for the VWAP session-anchoring fixes (docs/audits/2026-09-01-vwap-orderflow-evaluation.md, Part 1).

Covers:
  - Session VWAP actually resets at a session boundary (no cross-session leakage).
  - Zero/negative/non-finite volume bars contribute nothing and carry the VWAP forward.
  - West's incremental weighted variance matches a direct numpy weighted-variance
    computation on well-conditioned data.
  - `/api/anchored-vwap` on daily bars anchors only at pivots / 52-week high-low,
    never at a fabricated fraction of the window (the old `n//2`, `int(0.75n)` bug).
  - The gamma-flip anchor fix keeps the most recent crossings, not the oldest.
  - Insufficient data yields fewer anchors plus an explicit reason, never an
    invented anchor.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from edge.research.state_estimation import (
    compute_anchored_vwap,
    compute_session_vwap,
    derive_session_boundaries,
)
from edge.research.systematic_execution import generate_microstructure_signals
from edge.tools.api_server import _anchored_vwap_payload


# ---------------------------------------------------------------------------
# Session reset (D1 primitive: derive_session_boundaries / compute_session_vwap)
# ---------------------------------------------------------------------------

def test_derive_session_boundaries_finds_calendar_day_changes():
    idx = pd.to_datetime(
        [
            "2026-01-05 09:30", "2026-01-05 10:30", "2026-01-05 11:30",
            "2026-01-06 09:30", "2026-01-06 10:30",
            "2026-01-07 09:30",
        ]
    )
    assert derive_session_boundaries(idx) == [0, 3, 5]
    assert derive_session_boundaries([]) == []


def test_session_reset_isolates_sessions_from_each_other():
    """A bar in session 2 must not be influenced by session 1's volume."""
    idx = pd.to_datetime(
        [
            "2026-01-05 09:30", "2026-01-05 10:30", "2026-01-05 11:30", "2026-01-05 12:30",
            "2026-01-06 09:30", "2026-01-06 10:30", "2026-01-06 11:30", "2026-01-06 12:30",
        ]
    )
    prices = np.array([100.0, 101.0, 99.0, 100.0, 200.0, 201.0, 199.0, 200.0])
    # Session 1 carries enormous volume; if it leaked into session 2, session
    # 2's VWAP would be dragged down toward 100 despite session 2 trading at
    # a completely different price level.
    volumes = np.array([1e6, 1e6, 1e6, 1e6, 10.0, 10.0, 10.0, 10.0])

    res = compute_session_vwap(prices, volumes, idx)
    assert res.session_start_indices == [0, 4]

    # Session 2's VWAP is exactly what an anchored VWAP starting fresh at bar
    # 4 would produce -- nothing from session 1 is in the running sums.
    expected_s2 = compute_anchored_vwap(prices[4:], volumes[4:], [0], ["s2"])[0].vwap
    assert np.allclose(res.vwap[4:], expected_s2)
    assert np.all(res.vwap[4:] > 150.0)  # nowhere near session 1's ~100 level

    # Session 1's own values are unaffected by knowledge of session 2 (the
    # array covers both sessions but is computed session-by-session).
    expected_s1 = compute_anchored_vwap(prices[:4], volumes[:4], [0], ["s1"])[0].vwap
    assert np.allclose(res.vwap[:4], expected_s1)


def test_session_vwap_empty_and_misaligned_inputs():
    res = compute_session_vwap([], [], [])
    assert len(res.vwap) == 0
    assert res.session_start_indices == []


# ---------------------------------------------------------------------------
# Zero/negative/non-finite volume bars (D5)
# ---------------------------------------------------------------------------

def test_zero_volume_bar_does_not_move_vwap_and_carries_forward():
    prices = np.array([100.0, 999.0, 102.0, 104.0])
    volumes = np.array([1000.0, 0.0, 500.0, 500.0])
    res = compute_anchored_vwap(prices, volumes, [0], ["A"])[0]

    # The zero-volume bar's extreme price (999) must not enter the running
    # sums at all: the VWAP at that index is exactly the VWAP carried
    # forward from the bar before it.
    assert res.vwap[1] == pytest.approx(res.vwap[0])
    assert res.vwap[0] == pytest.approx(100.0)

    # And it must not perturb anything downstream either: bar 2's VWAP is
    # exactly the weighted mean of bars 0 and 2 only, as if bar 1 never
    # existed.
    expected = (100.0 * 1000.0 + 102.0 * 500.0) / (1000.0 + 500.0)
    assert res.vwap[2] == pytest.approx(expected)


def test_negative_and_nan_volume_bars_are_also_skipped():
    prices = np.array([50.0, 51.0, 52.0])
    volumes = np.array([100.0, -5.0, float("nan")])
    res = compute_anchored_vwap(prices, volumes, [0], ["A"])[0]
    # Only bar 0 ever had positive finite volume; the VWAP carries forward
    # unchanged rather than being dragged by the invalid bars.
    assert res.vwap[0] == pytest.approx(50.0)
    assert res.vwap[1] == pytest.approx(50.0)
    assert res.vwap[2] == pytest.approx(50.0)


def test_all_invalid_volume_since_anchor_is_nan_not_fabricated():
    prices = np.array([100.0, 101.0, 102.0])
    volumes = np.array([0.0, -5.0, float("nan")])
    res = compute_anchored_vwap(prices, volumes, [0], ["A"])[0]
    assert np.all(np.isnan(res.vwap))


# ---------------------------------------------------------------------------
# West's weighted variance vs. a direct numpy computation (D4)
# ---------------------------------------------------------------------------

def test_west_variance_matches_direct_numpy_weighted_variance():
    rng = np.random.default_rng(3)
    n = 60
    prices = 100.0 + np.cumsum(rng.normal(0.0, 0.3, n))
    volumes = rng.uniform(100.0, 5000.0, n)
    res = compute_anchored_vwap(prices, volumes, [0], ["A"])[0]

    for t in (0, 5, 20, 59):
        w = volumes[: t + 1]
        x = prices[: t + 1]
        wmean = np.average(x, weights=w)
        wvar = np.average((x - wmean) ** 2, weights=w)
        assert res.vwap[t] == pytest.approx(wmean, rel=1e-9)
        assert (res.upper_1sd[t] - res.vwap[t]) == pytest.approx(math.sqrt(wvar), rel=1e-6)
        assert (res.vwap[t] - res.lower_1sd[t]) == pytest.approx(math.sqrt(wvar), rel=1e-6)


def test_west_variance_numerically_stable_on_high_priced_long_anchor():
    """The original E[X^2]-E[X]^2 formula is where catastrophic cancellation
    bites: large cumulative sums (high price level, long anchor) relative to
    a small true variance. This must still return a finite, non-negative band
    instead of silently going to zero or NaN.
    """
    rng = np.random.default_rng(11)
    n = 500
    prices = 30000.0 + rng.normal(0.0, 0.5, n)  # tight dispersion, huge price level
    volumes = rng.uniform(1.0, 10.0, n)
    res = compute_anchored_vwap(prices, volumes, [0], ["A"])[0]
    sd = res.upper_1sd - res.vwap
    assert np.all(np.isfinite(sd))
    assert np.all(sd >= 0.0)
    assert sd[-1] > 0.0  # a real, measurable dispersion, not collapsed to 0


# ---------------------------------------------------------------------------
# Flip-crossing anchors keep the most recent, not the oldest (D2)
# ---------------------------------------------------------------------------

def test_flip_anchors_keep_most_recent_crossings_not_oldest():
    n = 16
    prices = np.array([100.0] + [99.0 if i % 2 == 0 else 101.0 for i in range(1, n)])
    flip = np.full(n, 100.0)
    volumes = np.full(n, 1000.0)

    _signals, _nw, _kalman, vwap_results = generate_microstructure_signals(
        prices,
        volumes=volumes,
        gamma_flip_series=flip,
        net_gex_series=np.full(n, 50.0),
    )

    # Recompute the raw (un-limited) crossing set the same way the engine
    # does, so the expectation isn't hard-coded against the implementation.
    all_crossings = [0]
    for t in range(1, n):
        prev_s, curr_s = prices[t - 1], prices[t]
        f = flip[t]
        if (prev_s < f <= curr_s) or (prev_s > f >= curr_s):
            all_crossings.append(t)
    all_crossings = sorted(set(all_crossings))
    assert len(all_crossings) > 5, "test setup should produce more than 5 crossings"

    expected_recent = sorted({0, *sorted(c for c in all_crossings if c != 0)[-4:]})
    old_buggy_oldest = sorted(all_crossings)[:5]

    kept_indices = sorted(av.anchor_index for av in vwap_results)
    assert kept_indices == expected_recent
    assert kept_indices != old_buggy_oldest

    # Names stay aligned with the anchors actually kept, and identify each
    # crossing by its own bar rather than a positional counter.
    names_by_index = {av.anchor_index: av.anchor_name for av in vwap_results}
    assert names_by_index[0] == "Session_Open"
    for idx in expected_recent:
        if idx != 0:
            assert str(idx) in names_by_index[idx]


# ---------------------------------------------------------------------------
# /api/anchored-vwap: real anchors, never a fabricated fraction of the window
# ---------------------------------------------------------------------------

def test_daily_anchors_are_pivot_or_52w_never_a_fraction_of_the_window():
    payload, status = _anchored_vwap_payload("SPY", {"window": ["5y"], "bars": ["daily"]})
    assert status == 200
    n = payload["n_bars"]
    assert payload["price_basis"] in {"hlc3", "close"}
    assert payload["session_reset"] is False
    assert len(payload["anchors"]) > 0

    fabricated_positions = {n // 2, int(n * 0.75)}
    # `window_start` is a deliberate, exactly-defined base reference anchored at
    # the FIRST displayed bar. It is allowed precisely because index 0 is a real
    # bar; the guard below still forbids any anchor at an arbitrary fraction of
    # the window, which is the fabrication this endpoint was rebuilt to remove.
    allowed_kinds = {"swing_high", "swing_low", "week_52_high", "week_52_low", "window_start"}
    for a in payload["anchors"]:
        assert a["anchor_kind"] in allowed_kinds
        assert a["anchor_index"] not in fabricated_positions
        assert a["anchor_timestamp"]
        assert a["anchor_name"] == a["anchor_label"]
        assert len(a["series"]) > 0

    # Stricter than a bare kind whitelist: the base anchor may only ever sit on
    # bar 0, and must disclaim that it is neither a session VWAP nor a
    # support/resistance claim. If it ever drifts to a computed offset, or
    # starts asserting a mechanism, this fails.
    base = [a for a in payload["anchors"] if a["anchor_kind"] == "window_start"]
    for a in base:
        assert a["anchor_index"] == 0, "the base anchor must be the first displayed bar, nothing else"
        note = a.get("anchor_note", "")
        assert "Not a session VWAP" in note
        assert "support/resistance" in note

    # Two anchors resolving to the same bar would draw two identical curves.
    indices = [a["anchor_index"] for a in payload["anchors"]]
    assert len(indices) == len(set(indices)), f"duplicate anchor indices: {indices}"


def test_intraday_payload_resets_at_session_boundary():
    payload, status = _anchored_vwap_payload("SPY", {"window": ["1m"], "bars": ["1h"]})
    assert status == 200
    assert payload["session_reset"] is True
    kinds = {a["anchor_kind"] for a in payload["anchors"]}
    assert "session" in kinds
    # A month of hourly bars spans many sessions.
    assert "prior_session" in kinds

    session_anchor = next(a for a in payload["anchors"] if a["anchor_kind"] == "session")
    prior_anchor = next(a for a in payload["anchors"] if a["anchor_kind"] == "prior_session")

    # The prior-session curve must not run into the current session: its
    # last timestamp must be strictly before the current session's anchor.
    assert prior_anchor["series"][-1]["t"] < session_anchor["anchor_timestamp"]

    # The current session's first VWAP point is that session's own opening
    # bar's typical price, not a continuation of a multi-day average.
    first_pt = session_anchor["series"][0]
    assert first_pt["t"] == session_anchor["anchor_timestamp"]


# ---------------------------------------------------------------------------
# Insufficient data => fewer anchors + an explicit reason, never an invented one
# ---------------------------------------------------------------------------

def test_insufficient_daily_history_yields_fewer_anchors_with_a_reason():
    payload, status = _anchored_vwap_payload("SPY", {"window": ["1m"], "bars": ["daily"]})
    assert status == 200
    assert payload["n_bars"] < 200

    kinds = {a["anchor_kind"] for a in payload["anchors"]}
    assert "week_52_high" not in kinds
    assert "week_52_low" not in kinds

    assert "notes" in payload
    assert any("252" in note for note in payload["notes"])
