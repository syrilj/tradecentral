"""Regression tests for the intraday volume/spread baseline fix.

`docs/audits/2026-09-01-vwap-orderflow-evaluation.md` §2.1 documents the
defect: `research/vpa_score.py::bar_metrics` computed `vol_ratio` (and
`spread_ratio`) as the bar's value over a flat trailing 20-bar mean. On
intraday (1h/2h/4h) bars this mixes hour-of-day slots -- volume has a strong
intraday U-shape, so the 09:30 bar's ratio was structurally inflated and the
midday bars' ratios were structurally deflated, regardless of what the market
actually did. Every detector in `build_evidence` that gates on `vol_ratio`
inherited that time-of-day bias.

The fix makes the baseline slot-aware for intraday bars: the trailing median
of the SAME hour-of-day slot over prior sessions, strictly exclusive of the
bar under judgement, with a fallback to the legacy trailing all-bar mean when
there is too little same-slot history (or the bars are daily/weekly, which
have no slot at all).

Each test below is written to demonstrate the specific claim in its name --
most also compute a `_legacy_ratio` reference (the exact pre-fix formula) to
show the old code actually would have misfired or missed, not just that the
new code produces *some* number.
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from research.vpa_score import bar_metrics, build_evidence
from research.vpa_thresholds import VPA_THRESHOLDS

HOURS = [9, 10, 11, 12, 13, 14, 15]
ULTRA = float(VPA_THRESHOLDS["signals"]["vol_ultra_high"])
MIN_SLOT_SAMPLES = int(VPA_THRESHOLDS["signals"]["volume_baseline_min_slot_samples"])
BASELINE_BARS = int(VPA_THRESHOLDS["signals"]["volume_baseline_bars"])


def _session_dates(n: int) -> List[date]:
    """`n` weekday calendar dates, so every session has a distinct date."""
    d = date(2024, 1, 2)
    out: List[date] = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _intraday_bar(d: date, hour: int, volume: float, close: float = 100.0) -> Dict[str, Any]:
    return {
        "date": f"{d.isoformat()}T{hour:02d}:30:00",
        "open": close,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": volume,
    }


def _u_shaped_intraday_bars(
    n_sessions: int,
    open_mult: float = 2.5,
    base_vol: float = 1_000_000.0,
    spike: Optional[tuple] = None,
) -> List[Dict[str, Any]]:
    """A synthetic 1h series with a real, structural (every-day) U-shape at the
    open but otherwise no anomaly -- i.e. exactly the shape the audit
    describes, and nothing a detector should legitimately fire on once it is
    normalised away. `spike` is an optional one-off ``(session_idx, hour,
    mult)`` genuine anomaly layered on top.
    """
    bars: List[Dict[str, Any]] = []
    for s, d in enumerate(_session_dates(n_sessions)):
        for h in HOURS:
            vol = base_vol * (open_mult if h == 9 else 1.0)
            if spike is not None and spike[0] == s and spike[1] == h:
                vol = base_vol * spike[2]
            bars.append(_intraday_bar(d, h, vol))
    return bars


def _legacy_ratio(bars: List[Dict[str, Any]], window: int = BASELINE_BARS) -> List[float]:
    """The exact pre-fix formula: trailing `window`-bar mean, exclusive of the
    current bar, mixing whatever hours happen to fall in that window."""
    out = []
    for i, b in enumerate(bars):
        start = max(0, i - window)
        prior = bars[start:i]
        vols = [p["volume"] for p in prior if p["volume"] > 0]
        base = (sum(vols) / len(vols)) if vols else 0.0
        out.append((b["volume"] / base) if base > 0 else 0.0)
    return out


def _day_bar(i: int, volume: float, close: float = 100.0) -> Dict[str, Any]:
    # Mirrors tests/test_vpa_engine.py::_day -- a date-only bar whose ISO
    # string still carries "T00:00:00" (pandas emits that for midnight
    # timestamps), which is exactly why "contains a T" cannot be used to
    # detect intraday bars.
    return {
        "date": f"2024-01-{(i % 28) + 1:02d}T00:00:00",
        "open": close, "high": close + 1.0, "low": close - 1.0, "close": close,
        "volume": volume,
    }


# ---------------------------------------------------------------------------
# 1. Structural U-shape must NOT read as an anomaly once slots have history.
# ---------------------------------------------------------------------------

def test_structural_open_volume_produces_no_ultra_high_reading_once_normalised():
    """A 2.5x-every-day open bar is not news -- it is the market's daily
    shape. Once the slot baseline has enough history, the open bar's
    `vol_ratio` must sit near 1.0, not trip `vol_ultra_high` (2.0x). The old
    trailing-mean formula, computed on the exact same bars, DOES trip it on
    (almost) every single occurrence -- that is the defect this test pins.
    """
    bars = _u_shaped_intraday_bars(n_sessions=40, open_mult=2.5)
    metrics = bar_metrics(bars, "1h")
    legacy = _legacy_ratio(bars)

    open_positions = [i for i, b in enumerate(bars) if b["date"].endswith("T09:30:00")]
    # Only look past the warm-up window where the slot baseline has taken
    # over (see test_min_sample_fallback_engages_for_short_slot_history for
    # the warm-up period itself).
    matured = [i for i in open_positions if metrics[i]["vol_base_kind"] == "slot_median"]
    assert len(matured) >= 20, "expected most open bars to reach the slot-median path"

    for i in matured:
        assert metrics[i]["vol_ratio"] < 1.2, (
            f"open bar at {bars[i]['date']} still reads as elevated after normalisation: "
            f"vol_ratio={metrics[i]['vol_ratio']}"
        )
        assert metrics[i]["vol_ratio"] < ULTRA
        assert legacy[i] >= ULTRA, (
            "the legacy trailing-mean formula was expected to trip vol_ultra_high on this "
            "structurally-elevated open bar -- if it didn't, the test fixture no longer "
            "demonstrates the defect"
        )

    # And the new code must trip ultra-high-volume on essentially none of the
    # matured open bars, versus almost all of them under the legacy formula.
    new_trigger_rate = sum(1 for i in matured if metrics[i]["vol_ratio"] >= ULTRA) / len(matured)
    legacy_trigger_rate = sum(1 for i in matured if legacy[i] >= ULTRA) / len(matured)
    assert new_trigger_rate == 0.0
    assert legacy_trigger_rate > 0.9


def test_structural_open_bias_does_not_leak_into_build_evidence_as_absorption_churn():
    """End-to-end: the same U-shaped series must not make `build_evidence`
    report absorption/churn (narrow spread + ultra volume) at the open purely
    because of the time of day. Bars are flat-range by construction, so
    `spread_ratio` stays ~1.0 (not narrow) regardless -- this test isolates
    the volume side of the ledger specifically.
    """
    bars = _u_shaped_intraday_bars(n_sessions=40, open_mult=2.5)
    evidence = build_evidence(bars, timeframe="1h")
    open_dates = {b["date"] for b in bars if b["date"].endswith("T09:30:00")}
    flagged_open_bars = [
        e for e in evidence
        if any(bd in open_dates for bd in e.get("bar_dates", []) or [])
    ]
    # No evidence item at all should be anchored on an open bar in this
    # pure-U-shape series -- there is no real signal here, only clock.
    assert not flagged_open_bars, f"open-bar evidence fired on a purely structural U-shape: {flagged_open_bars}"


# ---------------------------------------------------------------------------
# 2. A genuine anomaly at a non-open slot must still be detected.
# ---------------------------------------------------------------------------

def test_genuine_midday_spike_is_still_detected_after_normalisation():
    """A real, one-off 3.2x spike at the 12:30 slot -- on a day with a mature
    slot history -- must read as ultra-high volume. Normalising away the
    time-of-day artefact must not also suppress real anomalies.
    """
    n_sessions = 40
    spike_session = n_sessions - 1
    bars = _u_shaped_intraday_bars(
        n_sessions=n_sessions, open_mult=2.5, spike=(spike_session, 12, 3.2)
    )
    metrics = bar_metrics(bars, "1h")

    spike_date = f"{_session_dates(n_sessions)[spike_session].isoformat()}T12:30:00"
    spike_i = next(i for i, b in enumerate(bars) if b["date"] == spike_date)

    m = metrics[spike_i]
    assert m["vol_base_kind"] == "slot_median"
    assert m["vol_base_n"] >= MIN_SLOT_SAMPLES
    assert m["vol_ratio"] >= ULTRA, f"genuine midday spike was not flagged: vol_ratio={m['vol_ratio']}"
    assert abs(m["vol_ratio"] - 3.2) < 0.05, "slot baseline should read the spike at ~3.2x cleanly"


# ---------------------------------------------------------------------------
# 3. Strict causality: never the current bar, never a later one.
# ---------------------------------------------------------------------------

def test_slot_baseline_never_uses_the_current_or_a_later_bar():
    """Perturbing bars strictly after index t must not change the metrics
    computed at t -- for both the slot path and the vanilla trailing-mean
    fallback path.
    """
    bars = _u_shaped_intraday_bars(n_sessions=40, open_mult=2.5)
    t = 9 * len(HOURS) + 2  # well past warm-up, mid-series, arbitrary slot
    before = bar_metrics(bars, "1h")[t]

    perturbed = [dict(b) for b in bars]
    for j in range(t + 1, len(perturbed)):
        perturbed[j] = dict(perturbed[j])
        perturbed[j]["volume"] = perturbed[j]["volume"] * 37.0 + 12345.0
        perturbed[j]["high"] = perturbed[j]["high"] * 3.0
        perturbed[j]["low"] = max(perturbed[j]["low"] * 0.2, 0.01)
    # Also mutate the bar under judgement's own volume/range -- the baseline
    # must be exclusive of bar t too.
    perturbed[t] = dict(perturbed[t])
    perturbed[t]["volume"] = perturbed[t]["volume"] * 5.0

    after = bar_metrics(perturbed, "1h")[t]

    assert after["vol_base"] == before["vol_base"]
    assert after["vol_base_kind"] == before["vol_base_kind"]
    assert after["vol_base_n"] == before["vol_base_n"]
    assert after["range_base"] == before["range_base"]
    assert after["range_base_kind"] == before["range_base_kind"]
    # vol_ratio itself is allowed to change (bar t's own volume changed), but
    # the baseline it was measured against must not have.
    assert after["vol_ratio"] != before["vol_ratio"]


def test_short_slot_history_fallback_is_also_causal():
    """Same causality guarantee, exercised on the trailing-mean fallback path
    (short slot history) rather than the mature slot path."""
    bars = _u_shaped_intraday_bars(n_sessions=15, open_mult=2.5)
    t = 5 * len(HOURS) + 1  # in the fallback window (see fallback-timing test)
    before = bar_metrics(bars, "1h")[t]
    assert before["vol_base_kind"] == "trailing_mean"

    perturbed = [dict(b) for b in bars]
    for j in range(t + 1, len(perturbed)):
        perturbed[j] = dict(perturbed[j])
        perturbed[j]["volume"] *= 50.0

    after = bar_metrics(perturbed, "1h")[t]
    assert after["vol_base"] == before["vol_base"]
    assert after["vol_base_n"] == before["vol_base_n"]


# ---------------------------------------------------------------------------
# 4. Daily/weekly bars keep the old trailing-baseline path unchanged.
# ---------------------------------------------------------------------------

def test_daily_bars_keep_the_trailing_all_bar_baseline():
    """Daily bars have no hour-of-day slot to normalise against -- even
    though `_frame_to_bars` gives them a 'T00:00:00' suffix that superficially
    looks like a clock. `bar_metrics` must fall straight to the legacy
    trailing-mean path and reproduce it exactly, bar for bar.
    """
    bars = [_day_bar(i, 1_000_000.0 + (i % 5) * 10_000.0) for i in range(60)]
    metrics = bar_metrics(bars)  # no explicit timeframe -- auto-detect path
    legacy = _legacy_ratio(bars)

    for i in range(BASELINE_BARS, len(bars)):
        assert metrics[i]["vol_base_kind"] == "trailing_mean"
        assert metrics[i]["vol_base_n"] == BASELINE_BARS
        assert abs(metrics[i]["vol_ratio"] - legacy[i]) < 1e-9

    # Same story with an explicit non-intraday timeframe passed through.
    metrics_1d = bar_metrics(bars, "1D")
    for i in range(BASELINE_BARS, len(bars)):
        assert metrics_1d[i]["vol_base_kind"] == "trailing_mean"
        assert metrics_1d[i]["vol_ratio"] == metrics[i]["vol_ratio"]


# ---------------------------------------------------------------------------
# 5. Thin same-slot history degrades gracefully rather than emitting nothing.
# ---------------------------------------------------------------------------

def test_min_sample_fallback_engages_for_short_slot_history():
    """Below `volume_baseline_min_slot_samples` (10) same-slot occurrences, a
    bar must still get a usable (non-zero, non-null) baseline via the
    trailing-mean fallback -- not silence. Once history matures past the
    threshold, the same slot flips over to the slot baseline.
    """
    bars = _u_shaped_intraday_bars(n_sessions=15, open_mult=2.5)
    metrics = bar_metrics(bars, "1h")
    open_positions = [i for i, b in enumerate(bars) if b["date"].endswith("T09:30:00")]

    thin, matured = [], []
    for rank, i in enumerate(open_positions):
        if rank < MIN_SLOT_SAMPLES:
            thin.append(i)
        else:
            matured.append(i)

    assert thin and matured, "fixture must straddle the min-sample threshold"
    for i in thin:
        m = metrics[i]
        assert m["vol_base_kind"] == "trailing_mean"
        if i > 0:
            # The very first bar in the whole series has no prior bars at
            # all, in any scheme -- that is a real "no data yet" case, not
            # the fallback under test.
            assert m["vol_base"] > 0.0
            assert m["vol_base_n"] > 0

    for i in matured:
        m = metrics[i]
        assert m["vol_base_kind"] == "slot_median"
        assert m["vol_base_n"] >= MIN_SLOT_SAMPLES
