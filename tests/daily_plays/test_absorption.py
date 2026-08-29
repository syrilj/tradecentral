"""Unit tests for the streaming absorption detector (daily_plays/absorption.py)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from edge.daily_plays.absorption import (
    CLV_PROXY_SCAN_CONFIG,
    AbsorptionConfig,
    AbsorptionDetector,
    AbsorptionObservation,
    build_absorption_scan,
    detect_absorption_series,
    observations_from_bars,
    observations_from_flow_prints,
)


def _obs(price, volume, signed=0.0, high=None, low=None, ts=None):
    return AbsorptionObservation(
        ts=ts or datetime(2026, 1, 1, tzinfo=timezone.utc),
        price=price,
        volume=volume,
        signed_flow=signed,
        high=high,
        low=low,
    )


def _bars(closes, volumes, opens=None):
    n = len(closes)
    opens = opens if opens is not None else closes
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {
            "open": opens,
            "high": [c * 1.001 for c in closes],
            "low": [c * 0.999 for c in closes],
            "close": closes,
            "volume": volumes,
        },
        index=idx,
    )


def test_config_rejects_bad_thresholds():
    with pytest.raises(ValueError):
        AbsorptionConfig(window=1)
    with pytest.raises(ValueError):
        AbsorptionConfig(vol_surge_min=0)
    with pytest.raises(ValueError):
        AbsorptionConfig(imbalance_min=1.5)
    with pytest.raises(ValueError):
        AbsorptionConfig(min_baseline_observations=0)
    with pytest.raises(ValueError):
        AbsorptionConfig(baseline_window=60, min_baseline_observations=61)
    with pytest.raises(ValueError):
        AbsorptionConfig(imbalance_percentile=1.0)
    with pytest.raises(ValueError):
        AbsorptionConfig(imbalance_percentile=-0.1)


def test_warmup_readout_is_never_a_signal():
    detector = AbsorptionDetector(AbsorptionConfig(min_observations=20, window=20))
    for i in range(19):
        readout = detector.update(_obs(100.0, 1000.0, signed=-500.0))
        assert readout.signal is False
        assert readout.signal_kind is None


def test_sell_absorption_flags_reversal_up():
    # Heavy selling (negative signed flow) with price holding -> sell absorption.
    detector = AbsorptionDetector(AbsorptionConfig(min_observations=20, window=20))
    for _ in range(60):
        detector.update(_obs(100.0, 1000.0, signed=0.0, high=100.2, low=99.8))
    readout = detector.update(_obs(100.0, 50000.0, signed=-45000.0, high=100.2, low=99.8))
    assert readout.signal is True
    assert readout.signal_kind == "sell_absorption"
    assert readout.flow_direction == -1
    assert readout.reversal_direction == 1
    assert readout.absorption_score < 0


def test_buy_absorption_flags_reversal_down():
    detector = AbsorptionDetector(AbsorptionConfig(min_observations=20, window=20))
    for _ in range(60):
        detector.update(_obs(100.0, 1000.0, signed=0.0, high=100.2, low=99.8))
    readout = detector.update(_obs(100.0, 50000.0, signed=45000.0, high=100.2, low=99.8))
    assert readout.signal is True
    assert readout.signal_kind == "buy_absorption"
    assert readout.flow_direction == 1
    assert readout.reversal_direction == -1
    assert readout.absorption_score > 0


def test_unsigned_flow_has_magnitude_but_no_direction():
    detector = AbsorptionDetector(AbsorptionConfig(min_observations=20, window=20))
    for _ in range(60):
        detector.update(_obs(100.0, 1000.0, signed=0.0, high=100.2, low=99.8))
    readout = detector.update(_obs(100.0, 50000.0, signed=0.0, high=100.2, low=99.8))
    assert readout.flow_direction == 0
    assert readout.signal is False
    assert readout.absorption_magnitude > 0
    assert readout.absorption_score == 0.0


def test_price_move_breaks_the_stall():
    # Same heavy selling but price actually falls -> not absorption.
    detector = AbsorptionDetector(AbsorptionConfig(min_observations=20, window=20))
    for _ in range(60):
        detector.update(_obs(100.0, 1000.0, signed=0.0, high=100.2, low=99.8))
    readout = detector.update(_obs(98.0, 50000.0, signed=-45000.0, high=98.2, low=97.8))
    assert readout.signal is False


def test_incremental_matches_batch():
    observations = [
        _obs(100.0, 1000.0, signed=0.0, high=100.2, low=99.8) for _ in range(60)
    ] + [_obs(100.0, 50000.0, signed=-45000.0, high=100.2, low=99.8)]
    batch = detect_absorption_series(observations)
    detector = AbsorptionDetector()
    incremental = [detector.update(obs) for obs in observations]
    assert [r.signal for r in batch] == [r.signal for r in incremental]
    assert [r.absorption_score for r in batch] == [r.absorption_score for r in incremental]
    assert [r.absorption_magnitude for r in batch] == [r.absorption_magnitude for r in incremental]


def test_observations_from_bars_uses_clv_proxy():
    bars = _bars([100.0] * 5, [1000.0] * 5)
    observations = observations_from_bars(bars)
    assert len(observations) == 5
    # CLV is 0 for a bar that closes exactly at its midpoint (high/low symmetric).
    assert observations[0].signed_flow == pytest.approx(0.0)


def test_observations_from_flow_prints_forward_fill_price():
    prints = [
        {"timestamp": "2026-08-11T15:00:00Z", "underlying_price": 100.0, "premium": 50_000, "signed_premium": 50_000},
        {"timestamp": "2026-08-11T15:00:01Z", "premium": 20_000, "signed_premium": -20_000},
    ]
    observations = observations_from_flow_prints(prints)
    assert len(observations) == 2
    assert observations[1].price == 100.0  # forward-filled
    assert observations[0].signed_flow == 50_000
    assert observations[1].signed_flow == -20_000


def test_observations_from_flow_prints_skips_unsigned_missing_price():
    prints = [
        {"timestamp": "2026-08-11T15:00:00Z", "premium": 50_000},
    ]
    assert observations_from_flow_prints(prints) == []


def test_observations_from_flow_prints_sorts_regardless_of_caller_order():
    """Regression test: the LSE flow tape is sorted newest-first (``ts.desc``),
    but ``AbsorptionDetector`` is strictly causal -- it assumes index 0 is the
    OLDEST observation. ``observations_from_flow_prints`` must sort ascending
    by timestamp itself so the resulting observations (and every downstream
    readout) do not depend on the order the caller happens to hand prints in.
    """
    base = datetime(2026, 8, 11, 15, 0, 0, tzinfo=timezone.utc)
    n = 40
    prints: list[dict] = []
    for i in range(n):
        ts = base + timedelta(seconds=i)
        price = 100.00 if i % 2 == 0 or i >= 37 else 100.02
        if i == n - 1:
            premium, signed = 50_000.0, 45_000.0
        else:
            premium, signed = 1_000.0, 0.0
        prints.append(
            {
                "timestamp": ts.isoformat(),
                "underlying_price": price,
                "premium": premium,
                "signed_premium": signed,
            }
        )

    prints_ascending = list(prints)
    prints_descending = list(reversed(prints))
    assert prints_ascending != prints_descending  # sanity: inputs actually differ in order

    obs_from_ascending = observations_from_flow_prints(prints_ascending)
    obs_from_descending = observations_from_flow_prints(prints_descending)
    assert obs_from_ascending == obs_from_descending

    cfg = AbsorptionConfig(
        window=20, min_observations=20, baseline_window=20, min_baseline_observations=1
    )
    readouts_ascending = detect_absorption_series(obs_from_ascending, cfg)
    readouts_descending = detect_absorption_series(obs_from_descending, cfg)
    assert readouts_ascending == readouts_descending
    # Not a vacuous comparison: with correct ordering this scenario does
    # produce a real (buy-absorption) signal on the final observation.
    assert readouts_ascending[-1].signal is True
    assert readouts_ascending[-1].signal_kind == "buy_absorption"


def test_build_absorption_scan_ranks_by_magnitude_and_skips_bad_frames():
    good = _bars([100.0] * 60, [1000.0] * 60)
    # A frame with too little history is skipped, not fabricated.
    short = _bars([100.0] * 5, [1000.0] * 5)
    result = build_absorption_scan({"GOOD": good, "SHORT": short})
    assert result["universe_size"] == 2
    assert result["evaluated"] == 1
    assert result["rows"][0]["symbol"] == "GOOD"


def test_build_absorption_scan_ranks_by_abs_score_not_bare_magnitude():
    """A flow_direction == 0 row must not outrank a genuine directional
    signal purely because it has larger absorption_magnitude (the KO bug:
    magnitude 0.966, score 0.0, signal False ranked #1 on live data).
    """
    n = 60
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz=timezone.utc)

    # UNSIGNED: heavy volume surge on the final bar, but close stays pinned
    # to the midpoint of high/low (CLV == 0) on every bar, so signed flow is
    # 0 throughout -> flow_direction == 0 and absorption_score == 0, despite
    # a large absorption_magnitude from the volume surge alone.
    closes_u = [100.0] * n
    vols_u = [1000.0] * (n - 1) + [80_000.0]
    unsigned = pd.DataFrame(
        {
            "open": closes_u,
            "high": [c * 1.001 for c in closes_u],
            "low": [c * 0.999 for c in closes_u],
            "close": closes_u,
            "volume": vols_u,
        },
        index=idx,
    )

    # DIRECTIONAL: a much smaller volume surge, but close is pinned to the
    # bar's low on the surge bar (maximal negative CLV) -> a real, if small,
    # sell-absorption signal (flow_direction != 0, absorption_score != 0).
    closes_d = [100.0] * n
    vols_d = [1000.0] * (n - 1) + [40_000.0]
    highs_d = [c * 1.001 for c in closes_d]
    lows_d = [c * 0.999 for c in closes_d]
    directional = pd.DataFrame(
        {"open": closes_d, "high": highs_d, "low": lows_d, "close": closes_d, "volume": vols_d},
        index=idx,
    )
    directional.iloc[-1, directional.columns.get_loc("close")] = lows_d[-1]

    result = build_absorption_scan({"UNSIGNED": unsigned, "DIRECTIONAL": directional})
    rows_by_symbol = {row["symbol"]: row for row in result["rows"]}

    assert rows_by_symbol["UNSIGNED"]["flow_direction"] == 0
    assert rows_by_symbol["UNSIGNED"]["absorption_score"] == 0.0
    assert rows_by_symbol["UNSIGNED"]["signal"] is False
    assert rows_by_symbol["DIRECTIONAL"]["flow_direction"] != 0
    assert rows_by_symbol["DIRECTIONAL"]["absorption_score"] != 0.0

    # The undirected row has a strictly larger magnitude, yet must rank
    # below the genuine (if smaller-magnitude) directional signal.
    assert (
        rows_by_symbol["UNSIGNED"]["absorption_magnitude"]
        > rows_by_symbol["DIRECTIONAL"]["absorption_magnitude"]
    )
    assert [row["symbol"] for row in result["rows"]] == ["DIRECTIONAL", "UNSIGNED"]


def test_absorption_magnitude_breaks_ties_when_scores_match():
    # Two rows with the same nonzero |absorption_score| are ordered by
    # absorption_magnitude, the documented tiebreaker.
    detector = AbsorptionDetector(AbsorptionConfig(min_observations=20, window=20))
    for _ in range(60):
        detector.update(_obs(100.0, 1000.0, signed=0.0, high=100.2, low=99.8))
    small = detector.update(_obs(100.0, 50_000.0, signed=-25_000.0, high=100.2, low=99.8))

    detector2 = AbsorptionDetector(AbsorptionConfig(min_observations=20, window=20))
    for _ in range(60):
        detector2.update(_obs(100.0, 1000.0, signed=0.0, high=100.2, low=99.8))
    large = detector2.update(_obs(100.0, 50_000.0, signed=-40_000.0, high=100.2, low=99.8))

    assert small.flow_direction == large.flow_direction == -1
    assert abs(large.absorption_score) >= abs(small.absorption_score)


def test_signal_never_fires_while_baseline_is_immature():
    """FIX 4: baseline_window=60 but the warm gate never checked baseline
    size, so the very first non-warm readout could judge "heavy" volume
    against as little as 1 historical baseline sample. A minimum baseline
    sample count must gate ``signal``, and immaturity must be reported
    through an explicit field distinguishable from a mature "evaluated,
    nothing found" readout.
    """
    cfg = AbsorptionConfig(
        min_observations=20, window=20, baseline_window=60, min_baseline_observations=30
    )

    # Scenario A: only 20 warm-up bars -> baseline has just 1 sample at the
    # first non-warm readout. Feed a bar that would otherwise clear every
    # surge/stall/direction gate.
    immature = AbsorptionDetector(cfg)
    for _ in range(20):
        immature.update(_obs(100.0, 1000.0, signed=0.0, high=100.2, low=99.8))
    readout_immature = immature.update(
        _obs(100.0, 50_000.0, signed=-45_000.0, high=100.2, low=99.8)
    )
    assert readout_immature.baseline_warming is True
    assert readout_immature.signal is False
    # The surge/direction/stall math itself is satisfied -- it is only the
    # baseline gate holding signal back.
    assert readout_immature.vol_ratio >= cfg.vol_surge_min
    assert readout_immature.flow_direction != 0

    # Scenario B: same heavy bar, but preceded by enough history for the
    # baseline to mature -> signal now fires, and baseline_warming is False.
    mature = AbsorptionDetector(cfg)
    for _ in range(80):
        mature.update(_obs(100.0, 1000.0, signed=0.0, high=100.2, low=99.8))
    readout_mature = mature.update(_obs(100.0, 50_000.0, signed=-45_000.0, high=100.2, low=99.8))
    assert readout_mature.baseline_warming is False
    assert readout_mature.signal is True

    # Scenario C: mature baseline, but nothing unusual happens -> signal is
    # False for a *different* reason than scenario A. baseline_warming must
    # tell these two False readouts apart.
    quiet = AbsorptionDetector(cfg)
    for _ in range(80):
        readout_quiet = quiet.update(_obs(100.0, 1000.0, signed=0.0, high=100.2, low=99.8))
    assert readout_quiet.baseline_warming is False
    assert readout_quiet.signal is False
    assert readout_immature.baseline_warming != readout_quiet.baseline_warming


# ---------------------------------------------------------------------------
# ISSUE 2 follow-up: the imbalance gate's calibration for the CLV proxy.
#
# Root-cause check on the "0.3 is near-unreachable for the CLV proxy"
# hypothesis: measured across all 59 tracked symbols' full local history in
# edge/data/1h (296,937 mature, non-warming hourly readouts), the plain
# absolute imbalance_min=0.3 clears 6.5% of readouts individually and 0.50%
# jointly with every other gate (1,492 real signals -- about one per symbol
# every ~6 weeks of hourly bars). That refutes "near-unreachable": it is a
# real, rare event, and a single 59-symbol snapshot showing zero hits is
# exactly what a ~0.5%-rate event looks like sampled once (~74% chance of
# zero hits by chance alone). So these tests do not assert the old absolute
# default was "wrong" -- they pin the actual fix: an opt-in, self-calibrating
# relative gate (Option (a)) that build_absorption_scan turns on by default
# for its CLV-proxy input, bounded so it can only relax the gate (never
# tighten it) and floored so a flat/quiet symbol can never trip it on noise.
# ---------------------------------------------------------------------------


def test_imbalance_percentile_relaxes_gate_below_absolute_floor():
    """Once a symbol's own trailing |imbalance| history is mature, a value
    that never clears the absolute imbalance_min can still clear the
    distribution-relative threshold -- but only when imbalance_percentile
    is actually enabled. Same observation sequence, only the config knob
    differs.
    """

    def _feed(imbalance_percentile: float):
        cfg = AbsorptionConfig(
            window=5,
            min_observations=5,
            baseline_window=10,
            min_baseline_observations=4,
            imbalance_min=0.3,
            imbalance_percentile=imbalance_percentile,
        )
        detector = AbsorptionDetector(cfg)
        for _ in range(5):
            detector.update(_obs(100.0, 1000.0, signed=0.0, high=100.2, low=99.8))
        # window=5, volume=1000/bar -> gross settles at 5000; these signed
        # values settle the rolling imbalance around 0.20-0.23, always below
        # the absolute imbalance_min=0.3.
        last = None
        for signed in (220.0, 240.0, 200.0, 260.0, 210.0, 230.0):
            last = detector.update(_obs(100.0, 1000.0, signed=signed, high=100.2, low=99.8))
        return last

    strict = _feed(imbalance_percentile=0.0)
    assert strict.imbalance == pytest.approx(0.228)
    assert strict.imbalance_threshold == pytest.approx(0.3)  # unchanged absolute floor
    assert strict.flow_direction == 0  # 0.228 < 0.3

    relaxed = _feed(imbalance_percentile=0.85)
    assert relaxed.imbalance == pytest.approx(0.228)
    assert relaxed.imbalance_threshold < 0.3  # relative bar, below the absolute ceiling
    assert relaxed.imbalance_threshold == pytest.approx(0.226)
    assert relaxed.flow_direction == 1  # 0.228 now clears its own relaxed bar


def test_imbalance_percentile_never_drops_below_half_of_imbalance_min():
    """A flat/near-zero trailing imbalance history must not let the relative
    gate collapse toward zero -- it is floored at 0.5 * imbalance_min, so a
    genuinely quiet symbol can never trip "directional" on pure noise.
    """
    cfg = AbsorptionConfig(
        window=5,
        min_observations=5,
        baseline_window=10,
        min_baseline_observations=4,
        imbalance_min=0.3,
        imbalance_percentile=0.5,
    )
    detector = AbsorptionDetector(cfg)
    for _ in range(5):
        detector.update(_obs(100.0, 1000.0, signed=0.0, high=100.2, low=99.8))
    # Small, low signed flow -> trailing |imbalance| history stays well under
    # the floor (0.15), so percentile(history, 0.5) alone would be tiny.
    last = None
    for signed in (20.0, 40.0, 60.0, 80.0, 100.0, 100.0):
        last = detector.update(_obs(100.0, 1000.0, signed=signed, high=100.2, low=99.8))
    assert last.imbalance_threshold == pytest.approx(0.5 * cfg.imbalance_min)
    assert last.imbalance_threshold == pytest.approx(0.15)
    # The observed imbalance (0.10) never gets close to even the floored
    # threshold, so it correctly stays non-directional.
    assert last.flow_direction == 0


def test_imbalance_percentile_inactive_until_history_is_mature():
    """Percentile mode must not activate on a handful of samples -- it falls
    back to the plain absolute imbalance_min until at least
    min_baseline_observations of trailing history exist, matching the same
    fail-closed philosophy as ``baseline_warming`` (FIX 4).
    """
    cfg = AbsorptionConfig(
        window=5,
        min_observations=5,
        baseline_window=10,
        min_baseline_observations=4,
        imbalance_min=0.3,
        imbalance_percentile=0.85,
    )
    detector = AbsorptionDetector(cfg)
    for _ in range(5):
        detector.update(_obs(100.0, 1000.0, signed=0.0, high=100.2, low=99.8))
    # First three non-warm steps: fewer than min_baseline_observations (4) of
    # prior imbalance history exist, so the gate must stay purely absolute.
    for signed in (220.0, 240.0, 200.0):
        readout = detector.update(_obs(100.0, 1000.0, signed=signed, high=100.2, low=99.8))
        assert readout.imbalance_threshold == pytest.approx(0.3)


def test_clv_proxy_scan_config_pins_calibration_decision():
    """Regression test for the calibration decision itself: build_absorption_
    scan's default must stay a deliberate, documented choice, not silently
    drift. imbalance_min/vol_surge_min are the measured-reachable absolute
    defaults (see AbsorptionConfig docstring); imbalance_percentile=0.85 is
    what makes the gate self-calibrate per symbol for the CLV proxy.
    """
    assert CLV_PROXY_SCAN_CONFIG.imbalance_min == 0.3
    assert CLV_PROXY_SCAN_CONFIG.vol_surge_min == 1.5
    assert CLV_PROXY_SCAN_CONFIG.imbalance_percentile == 0.85


def test_build_absorption_scan_default_uses_clv_proxy_calibration():
    """Same bars, only the config differs: build_absorption_scan's default
    (CLV_PROXY_SCAN_CONFIG) must produce a directional read where a bare
    AbsorptionConfig() would not, for an imbalance that sits below the
    absolute floor but at/above its own (constant, in this case) trailing
    history.
    """
    n = 90
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz=timezone.utc)
    high = [101.0] * n
    low = [99.0] * n
    close = [100.23] * n  # CLV = (2*100.23 - 101 - 99) / (101-99) = 0.23, every bar
    bars = pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": [1000.0] * n},
        index=idx,
    )

    strict = build_absorption_scan({"X": bars}, cfg=AbsorptionConfig())
    relaxed = build_absorption_scan({"X": bars})  # cfg omitted -> CLV_PROXY_SCAN_CONFIG

    strict_row = strict["rows"][0]
    relaxed_row = relaxed["rows"][0]
    assert strict_row["imbalance"] == relaxed_row["imbalance"] == pytest.approx(0.23)
    assert strict_row["imbalance_threshold"] == pytest.approx(0.3)
    assert strict_row["flow_direction"] == 0
    assert strict_row["absorption_score"] == 0.0

    assert relaxed_row["imbalance_threshold"] == pytest.approx(0.23)
    assert relaxed_row["flow_direction"] == 1
    assert relaxed_row["absorption_score"] != 0.0


def test_build_absorption_scan_rows_and_gate_summary_are_explicable():
    """ISSUE 1 + the visibility requirement: every row must carry
    ``baseline_warming`` (so 'not yet evaluable' is distinguishable from
    'evaluated, nothing found') and ``imbalance_threshold`` (so an operator
    can see how close a row came). The scan must also report a top-level
    ``gate_summary`` -- observed distribution and per-gate pass counts --
    so a board with few/zero signals is explicable rather than a silent
    blank screen (AGENTS.md fail-closed / explicit-missing-state).
    """
    # WARMING: enough bars to be evaluated (>= min_observations) but not
    # enough for the baseline to mature (< min_baseline_observations).
    warming = _bars([100.0] * 25, [1000.0] * 25)

    # QUIET: mature, flat, unsigned throughout -> flow_direction 0, no surge.
    quiet = _bars([100.0] * 90, [1000.0] * 90)

    # DIRECTIONAL: mature, constant CLV = 0.23 (below the absolute floor,
    # clears its own relaxed trailing threshold) -- see test above.
    n = 90
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz=timezone.utc)
    close = [100.23] * n
    directional = pd.DataFrame(
        {
            "open": close,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": close,
            "volume": [1000.0] * n,
        },
        index=idx,
    )

    result = build_absorption_scan(
        {"WARMING": warming, "QUIET": quiet, "DIRECTIONAL": directional}
    )
    assert result["evaluated"] == 3
    rows_by_symbol = {row["symbol"]: row for row in result["rows"]}

    for row in result["rows"]:
        assert "baseline_warming" in row
        assert "imbalance_threshold" in row

    assert rows_by_symbol["WARMING"]["baseline_warming"] is True
    # Immature -> percentile mode cannot have activated yet, plain absolute.
    assert rows_by_symbol["WARMING"]["imbalance_threshold"] == pytest.approx(0.3)

    assert rows_by_symbol["QUIET"]["baseline_warming"] is False
    assert rows_by_symbol["QUIET"]["flow_direction"] == 0
    assert rows_by_symbol["QUIET"]["signal"] is False

    assert rows_by_symbol["DIRECTIONAL"]["baseline_warming"] is False
    assert rows_by_symbol["DIRECTIONAL"]["flow_direction"] == 1

    summary = result["gate_summary"]
    assert summary["rows_baseline_warming"] == 1  # WARMING only
    assert summary["rows_clearing_direction_gate"] == 1  # DIRECTIONAL only
    assert summary["rows_signal"] == 0  # none clear the volume-surge gate too
    assert summary["imbalance_min"] == 0.3
    assert summary["imbalance_percentile"] == 0.85
    # The reported distribution must bracket what was actually observed.
    observed_imbalances = [abs(row["imbalance"]) for row in result["rows"]]
    assert min(observed_imbalances) <= summary["imbalance_abs_p50"] <= max(observed_imbalances)
    assert summary["imbalance_abs_max"] == pytest.approx(max(observed_imbalances))
