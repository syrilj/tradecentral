"""Auction Market Theory (AMT) engine for range-bound / choppy markets.

Dalton (*Mind Over Markets*, *Markets in Profile*) and Steidlmayer's Market
Profile reduce a market to one question: **is the auction in balance or out of
balance?** In balance, price rotates around a fair value the market has agreed
on; the edges of that value area are where responsive traders step in and the
edge trade is to *fade* the extremes back to the point of control. Out of
balance, initiative traders drive price to find new value and fading is how
accounts get destroyed. Almost every "choppy market" loss is a trend tactic
applied inside balance, or a balance tactic applied to a breakout.

This module answers that question from OHLCV bars and turns the answer into a
concrete plan. Every number is computed from the bars handed in; there are no
placeholder constants. When a level, statistic, or plan cannot be derived the
field is ``None`` with a stated reason, never a plausible-looking default.

Pipeline
--------
* ``build_profile``        -- volume + TPO profile: POC, value area (70%),
                              shape, HVN/LVN, excess, poor highs/lows.
* ``session_profiles``     -- the same profile per session so value migration
                              (overlap between consecutive value areas) is
                              measurable rather than eyeballed.
* ``balance_score``        -- five components (value-area overlap, close
                              containment, Choppiness Index, Kaufman efficiency
                              ratio, rotation factor) into one 0..1 score and a
                              BALANCE / TRANSITION / IMBALANCE label.
* ``locate_price``         -- where the last close sits relative to value,
                              consecutive closes outside value (acceptance) and
                              look-above/below-and-fail.
* ``rotation_statistics``  -- empirical hit-rate of value-area edge touches
                              rotating back to the prior POC, over the loaded
                              sessions. This is the honest replacement for the
                              folkloric "80% rule".
* ``build_trade_plan``     -- responsive plan (entry / stop / targets / R:R)
                              only when the regime and location give an edge.
* ``analyze_amt``          -- orchestrator; shapes the API response.

Bars are ``{date, open, high, low, close, volume}`` dicts, oldest first, as
produced by ``research.vpa_bars.load_bars``.
"""

from __future__ import annotations

import math
from datetime import date as _date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from research.vpa_bars import (
    DEFAULT_TIMEFRAME,
    bars_meta_from_series,
    load_bars,
    normalize_timeframe,
)
from research.vpa_levels import average_true_range

# ------------------------------------------------------------------ thresholds
#: The single retunable dict. Every tolerance is expressed in ATR or as a
#: fraction so a $3 stock and a $600 stock get the same *relative* reading.
AMT_THRESHOLDS: Dict[str, Any] = {
    # Profile construction
    "composite_bins": 40,
    "session_bins": 24,
    "value_area_pct": 0.70,
    # HVN / LVN relative to the POC bin's volume
    "hvn_ratio": 0.60,
    "lvn_ratio": 0.20,
    # Shape: POC position within the range
    "shape_p_skew": 0.65,
    "shape_b_skew": 0.35,
    # Double distribution: a trough between two peaks below this share of POC
    "double_dist_trough_ratio": 0.35,
    # Excess: single-print bins at an extreme (TPO count == 1) needed
    "excess_min_single_bins": 2,
    # Poor high/low: extreme bars whose highs/lows sit within this ATR band
    "poor_extreme_atr": 0.10,
    "poor_extreme_min_bars": 2,
    # Location: "at the edge" tolerance
    "edge_tolerance_atr": 0.25,
    # Acceptance outside value: consecutive closes outside the value area
    "acceptance_bars": 2,
    # Balance score
    "weights": {
        "va_overlap": 0.30,
        "containment": 0.20,
        "chop_index": 0.20,
        "efficiency": 0.15,
        "rotation": 0.15,
    },
    "balance_min": 0.60,
    "imbalance_max": 0.40,
    "chop_upper": 61.8,
    "chop_lower": 38.2,
    # Recent window used for containment / chop / efficiency / rotation
    "recent_sessions": 2,
    "overlap_sessions": 6,
    # Composite balance window: walk backward from the most recent session
    # while consecutive session value areas keep overlapping by at least this
    # much; below it value has migrated and that session starts a new balance.
    "balance_window_min_overlap": 0.35,
    "balance_window_min_sessions": 3,
    # Trade plan
    "stop_beyond_range_atr": 0.50,
    "min_reward_multiple": 1.0,
    "min_rotation_attempts": 5,
}

#: Sessions are how value migration is measured. Intraday bars group by the
#: calendar day, daily bars by ISO week, weekly bars by four-bar blocks.
_SESSION_RULE: Dict[str, str] = {
    "1h": "day",
    "2h": "day",
    "4h": "day",
    "1D": "week",
    "1W": "block4",
}

AMT_PLAYBOOK: List[Dict[str, str]] = [
    {
        "rule": "Trade responsive in balance, initiative out of it.",
        "detail": (
            "Inside a balance area the higher-probability trade is against the "
            "extreme: buy the value-area low, sell the value-area high, target the "
            "point of control. Once price is accepted outside value, stop fading."
        ),
    },
    {
        "rule": "Acceptance is time, not a print.",
        "detail": (
            "One close outside value is a probe. Two or more consecutive closes "
            "outside value is acceptance and voids the balance plan."
        ),
    },
    {
        "rule": "Look above and fail is the best chop trade there is.",
        "detail": (
            "A push through the value-area high that closes back inside traps "
            "breakout buyers. Sell it with the stop above the failed high and the "
            "point of control as the first target; mirror for a failed low."
        ),
    },
    {
        "rule": "Poor highs and lows get revisited; excess does not.",
        "detail": (
            "A flat, multi-bar extreme is an unfinished auction and acts as a "
            "magnet. A single-print tail (excess) means the other side stepped in "
            "aggressively and the auction there is complete."
        ),
    },
    {
        "rule": "Inside value, at the POC, you have no edge.",
        "detail": (
            "Price at fair value is where both sides agree. Wait for a rotation to "
            "an edge instead of guessing direction in the middle."
        ),
    },
    {
        "rule": "Size the stop off the range, not off the entry.",
        "detail": (
            "In balance the invalidation is acceptance beyond the range extreme, "
            "so the stop lives beyond the extreme plus a fraction of ATR, not a "
            "fixed number of points from the fill."
        ),
    },
]


# ------------------------------------------------------------------- helpers
def _f(x: Any) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def _round(x: Optional[float], nd: int = 4) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return round(float(x), nd)


def _clip01(x: float) -> float:
    if not math.isfinite(x):
        return 0.0
    return max(0.0, min(1.0, x))


def _parse_day(raw: Any) -> Optional[_date]:
    s = str(raw or "")[:10]
    try:
        return _date.fromisoformat(s)
    except ValueError:
        return None


def session_key(bar: Dict[str, Any], rule: str, index: int) -> str:
    """The grouping key a bar belongs to under `rule`."""
    if rule == "block4":
        return f"block-{index // 4}"
    d = _parse_day(bar.get("date"))
    if d is None:
        return f"bar-{index}"
    if rule == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return d.isoformat()


def split_sessions(bars: Sequence[Dict[str, Any]], timeframe: str) -> List[List[Dict[str, Any]]]:
    rule = _SESSION_RULE.get(normalize_timeframe(timeframe), "week")
    groups: List[List[Dict[str, Any]]] = []
    current_key: Optional[str] = None
    for i, b in enumerate(bars):
        k = session_key(b, rule, i)
        if k != current_key:
            groups.append([])
            current_key = k
        groups[-1].append(b)
    return groups


# ------------------------------------------------------------------- profile
def build_profile(
    bars: Sequence[Dict[str, Any]],
    n_bins: Optional[int] = None,
    atr: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Volume-at-price and TPO profile with value area, shape and extremes.

    Volume is distributed uniformly across each bar's high-low range (the same
    assumption the VPA engine uses when intra-bar prints are unavailable). TPO
    count is the number of bars whose range touches the bin. The value area is
    grown outward from the POC by taking, at each step, the side whose next
    pair of bins carries more volume -- the standard Market Profile procedure.
    """
    cfg = AMT_THRESHOLDS
    if not bars:
        return None
    n_bins = int(n_bins or cfg["composite_bins"])
    lo_all = min(_f(b["low"]) for b in bars)
    hi_all = max(_f(b["high"]) for b in bars)
    if not (math.isfinite(lo_all) and math.isfinite(hi_all)) or hi_all <= lo_all:
        return None
    width = (hi_all - lo_all) / n_bins
    if width <= 0:
        return None

    volume = [0.0] * n_bins
    tpo = [0] * n_bins

    def bin_of(p: float) -> int:
        return min(n_bins - 1, max(0, int((p - lo_all) / width)))

    for b in bars:
        lo, hi = _f(b["low"]), _f(b["high"])
        vol = max(0.0, _f(b["volume"]) if math.isfinite(_f(b["volume"])) else 0.0)
        lo_i, hi_i = bin_of(lo), bin_of(hi)
        for i in range(lo_i, hi_i + 1):
            tpo[i] += 1
        if hi <= lo or lo_i == hi_i:
            volume[lo_i] += vol
            continue
        span = hi - lo
        for i in range(lo_i, hi_i + 1):
            b_lo = lo_all + i * width
            b_hi = b_lo + width
            covered = max(0.0, min(hi, b_hi) - max(lo, b_lo))
            volume[i] += vol * (covered / span)

    total = sum(volume)
    if total <= 0:
        # No volume at all (some feeds ship zero volume): fall back to TPO so
        # the profile is still an honest time-at-price picture.
        volume = [float(t) for t in tpo]
        total = sum(volume)
        basis = "tpo"
    else:
        basis = "volume"
    if total <= 0:
        return None

    poc_i = max(range(n_bins), key=lambda i: (volume[i], -abs(i - n_bins // 2)))
    target = cfg["value_area_pct"] * total
    va_lo_i = va_hi_i = poc_i
    accum = volume[poc_i]
    while accum < target and (va_lo_i > 0 or va_hi_i < n_bins - 1):
        up = sum(volume[va_hi_i + 1 : va_hi_i + 3]) if va_hi_i < n_bins - 1 else -1.0
        down = sum(volume[max(0, va_lo_i - 2) : va_lo_i]) if va_lo_i > 0 else -1.0
        if up >= down and up >= 0:
            step = min(2, n_bins - 1 - va_hi_i)
            accum += sum(volume[va_hi_i + 1 : va_hi_i + 1 + step])
            va_hi_i += step
        else:
            step = min(2, va_lo_i)
            accum += sum(volume[va_lo_i - step : va_lo_i])
            va_lo_i -= step

    def centre(i: int) -> float:
        return lo_all + (i + 0.5) * width

    poc = centre(poc_i)
    val = lo_all + va_lo_i * width
    vah = lo_all + (va_hi_i + 1) * width
    peak = volume[poc_i]

    hvn = [centre(i) for i in range(n_bins) if i != poc_i and volume[i] >= cfg["hvn_ratio"] * peak]
    lvn = [
        centre(i)
        for i in range(1, n_bins - 1)
        if volume[i] <= cfg["lvn_ratio"] * peak and volume[i] < volume[i - 1] and volume[i] < volume[i + 1]
    ]

    # Shape ---------------------------------------------------------------
    skew = (poc - lo_all) / (hi_all - lo_all)
    peaks = [
        i
        for i in range(n_bins)
        if volume[i] >= 0.5 * peak
        and (i == 0 or volume[i] >= volume[i - 1])
        and (i == n_bins - 1 or volume[i] >= volume[i + 1])
    ]
    double = False
    if len(peaks) >= 2:
        a, b2 = peaks[0], peaks[-1]
        if b2 - a >= 3:
            trough = min(volume[a : b2 + 1])
            double = trough <= cfg["double_dist_trough_ratio"] * peak
    if double:
        shape = "double_distribution"
    elif skew >= cfg["shape_p_skew"]:
        shape = "p"
    elif skew <= cfg["shape_b_skew"]:
        shape = "b"
    else:
        shape = "d"

    # Excess (single prints at the extremes) ------------------------------
    n_single_top = 0
    for i in range(n_bins - 1, -1, -1):
        if tpo[i] <= 1:
            n_single_top += 1
        else:
            break
    n_single_bot = 0
    for i in range(n_bins):
        if tpo[i] <= 1:
            n_single_bot += 1
        else:
            break
    excess_high = n_single_top >= cfg["excess_min_single_bins"]
    excess_low = n_single_bot >= cfg["excess_min_single_bins"]

    # Poor high / low (flat, multi-bar extremes) ---------------------------
    atr_v = float(atr) if atr and atr > 0 else average_true_range(list(bars))
    band = cfg["poor_extreme_atr"] * atr_v if atr_v > 0 else width
    n_at_high = sum(1 for b in bars if hi_all - _f(b["high"]) <= band)
    n_at_low = sum(1 for b in bars if _f(b["low"]) - lo_all <= band)
    poor_high = n_at_high >= cfg["poor_extreme_min_bars"] and not excess_high
    poor_low = n_at_low >= cfg["poor_extreme_min_bars"] and not excess_low

    return {
        "basis": basis,
        "bin_width": _round(width, 6),
        "low": _round(lo_all),
        "high": _round(hi_all),
        "poc": _round(poc),
        "vah": _round(vah),
        "val": _round(val),
        "va_width": _round(vah - val),
        "va_volume_share": _round(accum / total, 4),
        "skew": _round(skew, 4),
        "shape": shape,
        "hvn": [_round(p) for p in hvn],
        "lvn": [_round(p) for p in lvn],
        "excess_high": excess_high,
        "excess_low": excess_low,
        "single_prints_top": n_single_top,
        "single_prints_bottom": n_single_bot,
        "poor_high": poor_high,
        "poor_low": poor_low,
        "bars_at_high": n_at_high,
        "bars_at_low": n_at_low,
        "bar_count": len(bars),
        "bins": [
            {
                "lo": _round(lo_all + i * width),
                "hi": _round(lo_all + (i + 1) * width),
                "volume": _round(volume[i], 2),
                "tpo": tpo[i],
                "in_value": va_lo_i <= i <= va_hi_i,
                "is_poc": i == poc_i,
            }
            for i in range(n_bins)
        ],
    }


def _overlap_ratio(a: Dict[str, Any], b: Dict[str, Any]) -> Optional[float]:
    """Intersection-over-union of two value areas. 1 = identical, 0 = disjoint."""
    if not a or not b:
        return None
    lo = max(a["val"], b["val"])
    hi = min(a["vah"], b["vah"])
    inter = max(0.0, hi - lo)
    union = max(a["vah"], b["vah"]) - min(a["val"], b["val"])
    if union <= 0:
        return None
    return inter / union


def rotation_factor(bars: Sequence[Dict[str, Any]]) -> int:
    """Dalton's rotation factor: +1/-1 per higher/lower high and low, summed."""
    rf = 0
    for prev, cur in zip(bars, bars[1:]):
        if _f(cur["high"]) > _f(prev["high"]):
            rf += 1
        elif _f(cur["high"]) < _f(prev["high"]):
            rf -= 1
        if _f(cur["low"]) > _f(prev["low"]):
            rf += 1
        elif _f(cur["low"]) < _f(prev["low"]):
            rf -= 1
    return rf


def session_profiles(
    bars: Sequence[Dict[str, Any]],
    timeframe: str,
    atr: float,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    prev: Optional[Dict[str, Any]] = None
    for group in split_sessions(bars, timeframe):
        prof = build_profile(group, AMT_THRESHOLDS["session_bins"], atr)
        if not prof:
            continue
        entry = {
            "start": group[0].get("date"),
            "end": group[-1].get("date"),
            "bar_count": len(group),
            "open": _round(_f(group[0]["open"])),
            "close": _round(_f(group[-1]["close"])),
            "high": prof["high"],
            "low": prof["low"],
            "poc": prof["poc"],
            "vah": prof["vah"],
            "val": prof["val"],
            "shape": prof["shape"],
            "rotation_factor": rotation_factor(group),
            "overlap_prev": _round(_overlap_ratio(prev, prof), 4) if prev else None,
            "poc_shift_atr": _round((prof["poc"] - prev["poc"]) / atr, 3) if prev and atr > 0 else None,
        }
        out.append(entry)
        prev = prof
    return out


def find_balance_window(
    sessions: List[Dict[str, Any]],
    bars: Sequence[Dict[str, Any]],
    timeframe: str,
) -> Dict[str, Any]:
    """The CURRENT balance area, not the whole lookback.

    A composite profile built over an entire trending year produces one
    enormous value area price left months ago (Dalton's "composite" is always
    a specific, current balance, never an arbitrary lookback). Walk backward
    from the most recent session and keep extending the window while
    consecutive session value areas keep overlapping; stop the moment overlap
    drops below `balance_window_min_overlap`, because that is where value
    migrated to a different level and a new balance began.

    A floor of `balance_window_min_sessions` sessions and 20 bars is enforced
    so a single tight session cannot masquerade as "the balance"; if the floor
    cannot be met even after widening past the overlap break, the full window
    is used instead and `reason` says so.
    """
    cfg = AMT_THRESHOLDS
    total_bars = len(bars)
    if not sessions or not bars:
        return {
            "start": bars[0].get("date") if bars else None,
            "end": bars[-1].get("date") if bars else None,
            "sessions": len(sessions),
            "bars": total_bars,
            "bar_index_start": 0,
            "truncated": False,
            "reason": "no sessions available; using the full lookback",
        }

    min_overlap = cfg["balance_window_min_overlap"]
    min_sessions = cfg["balance_window_min_sessions"]
    n = len(sessions)

    # Walk backward while consecutive value areas keep overlapping.
    start_idx = n - 1
    while start_idx > 0:
        ov = sessions[start_idx].get("overlap_prev")
        if ov is None or ov < min_overlap:
            break
        start_idx -= 1

    def window_bars_from(idx: int) -> int:
        return sum(s["bar_count"] for s in sessions[idx:])

    window_bars = window_bars_from(start_idx)
    truncated = start_idx > 0
    reason: Optional[str] = None

    # Enforce the floor by widening past the overlap break if necessary.
    if len(sessions) - start_idx < min_sessions or window_bars < 20:
        while start_idx > 0 and (len(sessions) - start_idx < min_sessions or window_bars < 20):
            start_idx -= 1
            window_bars = window_bars_from(start_idx)
        if len(sessions) - start_idx < min_sessions or window_bars < 20:
            # Even the whole lookback cannot meet the floor: use it anyway.
            start_idx = 0
            window_bars = window_bars_from(0)
            truncated = False
            reason = (
                f"fewer than {min_sessions} sessions / 20 bars available even in "
                "the full lookback; using the full lookback"
            )
        else:
            truncated = start_idx > 0
            reason = (
                f"value migrated within the lookback; widened past the overlap "
                f"break to meet the minimum {min_sessions} sessions / 20 bars floor"
            )

    window_sessions = sessions[start_idx:]
    bar_index_start = max(0, min(total_bars, total_bars - window_bars))
    return {
        "start": window_sessions[0].get("start"),
        "end": window_sessions[-1].get("end"),
        "sessions": len(window_sessions),
        "bars": window_bars,
        "bar_index_start": bar_index_start,
        "truncated": truncated,
        "reason": reason,
    }


# ------------------------------------------------------------ balance score
def choppiness_index(bars: Sequence[Dict[str, Any]]) -> Optional[float]:
    """Dreiss' Choppiness Index over the whole window handed in.

    100 * log10(sum(TR) / (max(high) - min(low))) / log10(n). Values above
    61.8 mean price is going nowhere; below 38.2 means it is trending.
    """
    n = len(bars)
    if n < 3:
        return None
    trs: List[float] = []
    prev_close = _f(bars[0]["close"])
    for b in bars:
        h, l = _f(b["high"]), _f(b["low"])
        trs.append(max(h - l, abs(h - prev_close), abs(l - prev_close)))
        prev_close = _f(b["close"])
    rng = max(_f(b["high"]) for b in bars) - min(_f(b["low"]) for b in bars)
    s = sum(trs)
    if rng <= 0 or s <= 0:
        return None
    return 100.0 * math.log10(s / rng) / math.log10(n)


def efficiency_ratio(bars: Sequence[Dict[str, Any]]) -> Optional[float]:
    """Kaufman efficiency ratio: net move / sum of absolute moves. 1 = straight line."""
    if len(bars) < 3:
        return None
    closes = [_f(b["close"]) for b in bars]
    path = sum(abs(a - b) for a, b in zip(closes[1:], closes))
    if path <= 0:
        return None
    return abs(closes[-1] - closes[0]) / path


def balance_score(
    bars: Sequence[Dict[str, Any]],
    composite: Dict[str, Any],
    sessions: List[Dict[str, Any]],
    session_bars: int,
) -> Dict[str, Any]:
    cfg = AMT_THRESHOLDS
    w = cfg["weights"]
    recent_n = max(8, session_bars * cfg["recent_sessions"])
    recent = list(bars[-recent_n:])

    overlaps = [s["overlap_prev"] for s in sessions[-cfg["overlap_sessions"] :] if s.get("overlap_prev") is not None]
    va_overlap = sum(overlaps) / len(overlaps) if overlaps else None

    inside = sum(1 for b in recent if composite["val"] <= _f(b["close"]) <= composite["vah"])
    containment = inside / len(recent) if recent else None

    chop = choppiness_index(recent)
    chop_component = (
        _clip01((chop - cfg["chop_lower"]) / (cfg["chop_upper"] - cfg["chop_lower"])) if chop is not None else None
    )

    er = efficiency_ratio(recent)
    efficiency_component = (1.0 - er) if er is not None else None

    rf = rotation_factor(recent)
    rf_max = 2 * max(1, len(recent) - 1)
    rotation_component = 1.0 - abs(rf) / rf_max if recent else None

    components = {
        "va_overlap": va_overlap,
        "containment": containment,
        "chop_index": chop_component,
        "efficiency": efficiency_component,
        "rotation": rotation_component,
    }
    used = {k: v for k, v in components.items() if v is not None}
    if not used:
        score = None
    else:
        wsum = sum(w[k] for k in used)
        score = sum(w[k] * v for k, v in used.items()) / wsum if wsum > 0 else None

    if score is None:
        label = "UNKNOWN"
    elif score >= cfg["balance_min"]:
        label = "BALANCE"
    elif score <= cfg["imbalance_max"]:
        label = "IMBALANCE"
    else:
        label = "TRANSITION"

    return {
        "label": label,
        "score": _round(score, 4),
        "components": {k: _round(v, 4) for k, v in components.items()},
        "weights": dict(w),
        "raw": {
            "chop_index": _round(chop, 2),
            "efficiency_ratio": _round(er, 4),
            "rotation_factor": rf,
            "rotation_factor_max": rf_max,
            "closes_inside_value": inside,
            "recent_bars": len(recent),
            "sessions_compared": len(overlaps),
        },
    }


# ---------------------------------------------------------------- location
def locate_price(
    bars: Sequence[Dict[str, Any]],
    composite: Dict[str, Any],
    atr: float,
) -> Dict[str, Any]:
    cfg = AMT_THRESHOLDS
    last = bars[-1]
    close = _f(last["close"])
    tol = cfg["edge_tolerance_atr"] * atr if atr > 0 else 0.0
    poc, vah, val = composite["poc"], composite["vah"], composite["val"]

    if close > vah + tol:
        zone = "ABOVE_VALUE"
    elif close >= vah - tol:
        zone = "VAH_EDGE"
    elif close < val - tol:
        zone = "BELOW_VALUE"
    elif close <= val + tol:
        zone = "VAL_EDGE"
    elif abs(close - poc) <= tol:
        zone = "POC"
    elif close > poc:
        zone = "INSIDE_UPPER"
    else:
        zone = "INSIDE_LOWER"

    # Acceptance: consecutive closes outside value, counted from the last bar.
    above = below = 0
    for b in reversed(bars):
        c = _f(b["close"])
        if c > vah:
            if below:
                break
            above += 1
        elif c < val:
            if above:
                break
            below += 1
        else:
            break
    acceptance = "none"
    if above >= cfg["acceptance_bars"]:
        acceptance = "above"
    elif below >= cfg["acceptance_bars"]:
        acceptance = "below"

    # Failed auction: the last bar (or the one before) poked through a value
    # edge and closed back inside.
    failed = "none"
    failed_extreme: Optional[float] = None
    for b in list(bars[-2:])[::-1]:
        c, h, l = _f(b["close"]), _f(b["high"]), _f(b["low"])
        if h > vah and val <= c <= vah:
            failed, failed_extreme = "look_above_fail", h
            break
        if l < val and val <= c <= vah:
            failed, failed_extreme = "look_below_fail", l
            break

    def dist(level: float) -> Optional[float]:
        return _round((close - level) / atr, 3) if atr > 0 else None

    return {
        "close": _round(close),
        "date": last.get("date"),
        "zone": zone,
        "edge_tolerance": _round(tol),
        "dist_to_poc_atr": dist(poc),
        "dist_to_vah_atr": dist(vah),
        "dist_to_val_atr": dist(val),
        "closes_above_value": above,
        "closes_below_value": below,
        "acceptance": acceptance,
        "failed_auction": failed,
        "failed_auction_extreme": _round(failed_extreme),
    }


# ------------------------------------------------------------- activity
def activity_profile(bars: Sequence[Dict[str, Any]], composite: Dict[str, Any], n: int) -> Dict[str, Any]:
    """Initiative vs responsive activity over the last `n` bars.

    Without a tape we classify each bar by where it *closed* relative to value
    and which way it moved: an up-close below value is responsive buying (the
    market rejecting low prices), an up-close above value is initiative buying
    (the market seeking higher prices), and symmetrically for sellers. The
    close-location value (CLV) weighted by volume is the delta proxy.
    """
    recent = list(bars[-n:])
    ib = isl = rb = rs = 0
    delta = 0.0
    tot_vol = 0.0
    for b in recent:
        o, c, h, l = _f(b["open"]), _f(b["close"]), _f(b["high"]), _f(b["low"])
        v = max(0.0, _f(b["volume"]) if math.isfinite(_f(b["volume"])) else 0.0)
        mid = (composite["vah"] + composite["val"]) / 2
        up = c > o
        down = c < o
        if up:
            if c > composite["vah"] or (c > mid and c > composite["poc"]):
                ib += 1
            else:
                rb += 1
        elif down:
            if c < composite["val"] or (c < mid and c < composite["poc"]):
                isl += 1
            else:
                rs += 1
        if h > l:
            clv = ((c - l) - (h - c)) / (h - l)
            delta += clv * v
            tot_vol += v
    return {
        "bars": len(recent),
        "initiative_buying": ib,
        "initiative_selling": isl,
        "responsive_buying": rb,
        "responsive_selling": rs,
        "delta_proxy": _round(delta / tot_vol, 4) if tot_vol > 0 else None,
        "dominant": (
            "initiative"
            if ib + isl > rb + rs
            else "responsive"
            if rb + rs > ib + isl
            else "mixed"
        ),
    }


# ------------------------------------------------------- rotation statistics
def rotation_statistics(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """How often did a touch of the prior session's value-area edge rotate to
    the prior POC within the same session? Computed over the sessions that
    were actually loaded, so the number is this symbol's, this timeframe's,
    and this window's -- not a textbook figure.
    """
    cfg = AMT_THRESHOLDS
    val_att = val_hit = vah_att = vah_hit = 0
    breaks_up = breaks_down = 0
    for prev, cur in zip(sessions, sessions[1:]):
        # Value-area-low touch from inside: reached prior VAL, did it get back to prior POC?
        if cur["low"] <= prev["val"] and cur["open"] > prev["val"]:
            val_att += 1
            if cur["high"] >= prev["poc"]:
                val_hit += 1
            if cur["close"] < prev["low"]:
                breaks_down += 1
        if cur["high"] >= prev["vah"] and cur["open"] < prev["vah"]:
            vah_att += 1
            if cur["low"] <= prev["poc"]:
                vah_hit += 1
            if cur["close"] > prev["high"]:
                breaks_up += 1
    min_n = cfg["min_rotation_attempts"]

    def rate(hit: int, att: int) -> Optional[float]:
        return _round(hit / att, 3) if att >= min_n else None

    return {
        "sessions": len(sessions),
        "val_attempts": val_att,
        "val_rotations": val_hit,
        "val_rotation_rate": rate(val_hit, val_att),
        "vah_attempts": vah_att,
        "vah_rotations": vah_hit,
        "vah_rotation_rate": rate(vah_hit, vah_att),
        "range_breaks_up": breaks_up,
        "range_breaks_down": breaks_down,
        "min_attempts_for_rate": min_n,
        "note": (
            "Rate is null until at least "
            f"{min_n} attempts exist in the loaded window; widen the lookback for more."
        ),
    }


# ------------------------------------------------------------- evidence
def build_evidence(
    regime: Dict[str, Any],
    composite: Dict[str, Any],
    location: Dict[str, Any],
    activity: Dict[str, Any],
    sessions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    ev: List[Dict[str, Any]] = []
    comp = regime["components"]
    raw = regime["raw"]
    w = regime["weights"]

    def add(signal: str, direction: str, weight: float, detail: str) -> None:
        ev.append({"signal": signal, "direction": direction, "weight": _round(weight, 3), "detail": detail})

    if comp.get("va_overlap") is not None:
        v = comp["va_overlap"]
        add(
            "Value-area overlap",
            "balance" if v >= 0.5 else "imbalance",
            w["va_overlap"] * (v if v >= 0.5 else 1 - v),
            f"Consecutive session value areas share {v:.0%} of their union over "
            f"{raw['sessions_compared']} comparisons. Overlapping value is balance; migrating value is trend.",
        )
    if comp.get("containment") is not None:
        v = comp["containment"]
        add(
            "Close containment",
            "balance" if v >= 0.5 else "imbalance",
            w["containment"] * (v if v >= 0.5 else 1 - v),
            f"{raw['closes_inside_value']} of the last {raw['recent_bars']} closes sit inside the composite value area.",
        )
    if raw.get("chop_index") is not None:
        v = comp["chop_index"]
        add(
            "Choppiness index",
            "balance" if v >= 0.5 else "imbalance",
            w["chop_index"] * (v if v >= 0.5 else 1 - v),
            f"CHOP {raw['chop_index']:.1f} over {raw['recent_bars']} bars (61.8 = pure chop, 38.2 = pure trend).",
        )
    if raw.get("efficiency_ratio") is not None:
        v = comp["efficiency"]
        add(
            "Efficiency ratio",
            "balance" if v >= 0.5 else "imbalance",
            w["efficiency"] * (v if v >= 0.5 else 1 - v),
            f"Net move is {raw['efficiency_ratio']:.0%} of the path travelled; low efficiency is rotation, not direction.",
        )
    if comp.get("rotation") is not None:
        v = comp["rotation"]
        add(
            "Rotation factor",
            "balance" if v >= 0.5 else "imbalance",
            w["rotation"] * (v if v >= 0.5 else 1 - v),
            f"Rotation factor {raw['rotation_factor']:+d} of ±{raw['rotation_factor_max']}; near zero means highs and lows are alternating.",
        )

    # Structure and location: directional evidence.
    if location["failed_auction"] == "look_above_fail":
        add(
            "Look above and fail",
            "bearish",
            0.30,
            f"Pushed through VAH {composite['vah']} to {location['failed_auction_extreme']} and closed back inside value: breakout buyers are trapped.",
        )
    if location["failed_auction"] == "look_below_fail":
        add(
            "Look below and fail",
            "bullish",
            0.30,
            f"Pushed through VAL {composite['val']} to {location['failed_auction_extreme']} and closed back inside value: breakdown sellers are trapped.",
        )
    if location["acceptance"] == "above":
        add(
            "Acceptance above value",
            "bullish",
            0.25,
            f"{location['closes_above_value']} consecutive closes above VAH: the market is seeking higher value. Do not fade.",
        )
    if location["acceptance"] == "below":
        add(
            "Acceptance below value",
            "bearish",
            0.25,
            f"{location['closes_below_value']} consecutive closes below VAL: the market is seeking lower value. Do not fade.",
        )
    if composite["poor_high"]:
        add(
            "Poor high",
            "bullish",
            0.10,
            f"{composite['bars_at_high']} bars share the range high at {composite['high']}: an unfinished auction that tends to be revisited.",
        )
    if composite["poor_low"]:
        add(
            "Poor low",
            "bearish",
            0.10,
            f"{composite['bars_at_low']} bars share the range low at {composite['low']}: an unfinished auction that tends to be revisited.",
        )
    if composite["excess_high"]:
        add(
            "Excess high",
            "bearish",
            0.12,
            f"{composite['single_prints_top']} single-print bins at the top: sellers rejected the high aggressively; that auction is complete.",
        )
    if composite["excess_low"]:
        add(
            "Excess low",
            "bullish",
            0.12,
            f"{composite['single_prints_bottom']} single-print bins at the bottom: buyers rejected the low aggressively; that auction is complete.",
        )
    if composite["shape"] == "p":
        add("P-shaped profile", "bearish", 0.08, "Value built high in the range after a rally: short covering, not new buying, typically precedes a return to lower value.")
    if composite["shape"] == "b":
        add("b-shaped profile", "bullish", 0.08, "Value built low in the range after a decline: long liquidation, which tends to exhaust rather than extend.")
    if composite["shape"] == "double_distribution":
        add("Double distribution", "imbalance", 0.10, "Two separate value areas with a low-volume trough between them: the market has moved value once and the trough is where it will move fast again.")
    if activity["delta_proxy"] is not None and activity["bars"]:
        d = activity["delta_proxy"]
        if abs(d) >= 0.15:
            add(
                "Close-location delta",
                "bullish" if d > 0 else "bearish",
                min(0.15, abs(d) * 0.5),
                f"Volume-weighted close location {d:+.2f} over {activity['bars']} bars: {'buyers' if d > 0 else 'sellers'} are finishing bars in control.",
            )
    if sessions and sessions[-1].get("poc_shift_atr") is not None:
        s = sessions[-1]["poc_shift_atr"]
        if abs(s) >= 1.0:
            add(
                "POC migration",
                "bullish" if s > 0 else "bearish",
                min(0.15, abs(s) * 0.05),
                f"Latest session POC moved {s:+.2f} ATR versus the prior session: value is being relocated.",
            )
    return ev


# ------------------------------------------------------------- trade plan
def build_trade_plan(
    regime: Dict[str, Any],
    composite: Dict[str, Any],
    location: Dict[str, Any],
    atr: float,
) -> Dict[str, Any]:
    cfg = AMT_THRESHOLDS
    poc, vah, val = composite["poc"], composite["vah"], composite["val"]
    rng_hi, rng_lo = composite["high"], composite["low"]
    buf = cfg["stop_beyond_range_atr"] * atr
    close = location["close"]

    def plan(
        bias: str,
        setup: str,
        entry: Optional[float],
        stop: Optional[float],
        t1: Optional[float],
        t2: Optional[float],
        invalidation: str,
        rules: List[str],
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Structural guard, applied to every plan this helper builds: a LONG
        # must have stop < entry < target_1, a SHORT the mirror image. Levels
        # out of order are a bug and must never reach the UI as a tradeable
        # bias (see e.g. a failed-auction entry that lands on the wrong edge).
        if bias in ("LONG", "SHORT") and entry is not None and stop is not None and t1 is not None:
            ordered = (stop < entry < t1) if bias == "LONG" else (t1 < entry < stop)
            if not ordered:
                return {
                    "bias": "NEUTRAL / WAIT",
                    "setup": setup,
                    "entry": None,
                    "stop": None,
                    "target_1": None,
                    "target_2": None,
                    "risk_reward": None,
                    "risk_reward_unavailable_reason": (
                        f"computed levels are out of order for a {bias} "
                        f"(entry {_round(entry)}, stop {_round(stop)}, target_1 {_round(t1)}); "
                        "the plan is invalid and has been withheld"
                    ),
                    "risk_per_unit": None,
                    "invalidation": invalidation,
                    "rules_applied": rules,
                }

        rr: Optional[float] = None
        rr_reason = reason
        if entry is not None and stop is not None and t1 is not None:
            risk = abs(entry - stop)
            reward = abs(t1 - entry)
            if risk > 0:
                rr = reward / risk
                if rr < cfg["min_reward_multiple"]:
                    rr_reason = (
                        f"reward to the first target is only {rr:.2f}x the risk "
                        f"(minimum {cfg['min_reward_multiple']:.1f}x); the edge is too thin from here"
                    )
            else:
                rr_reason = "entry and stop coincide"
        elif rr_reason is None:
            rr_reason = "entry, stop and target are not all derivable from this location"

        # A setup below the minimum reward-to-risk is not tradeable: downgrade
        # the bias so a UI reading the bias chip can't present it as
        # actionable, but keep every computed level so the user can still see
        # and judge the numbers for themselves.
        out_bias = bias
        out_setup = setup
        if bias in ("LONG", "SHORT") and rr is not None and rr < cfg["min_reward_multiple"]:
            out_bias = "NEUTRAL / WAIT"
            out_setup = f"Setup present but below minimum R:R — {setup}"

        return {
            "bias": out_bias,
            "setup": out_setup,
            "entry": _round(entry),
            "stop": _round(stop),
            "target_1": _round(t1),
            "target_2": _round(t2),
            "risk_reward": _round(rr, 2),
            "risk_reward_unavailable_reason": None if rr is not None and rr >= cfg["min_reward_multiple"] else rr_reason,
            "risk_per_unit": _round(abs(entry - stop)) if entry is not None and stop is not None else None,
            "invalidation": invalidation,
            "rules_applied": rules,
        }

    label = regime["label"]
    if atr <= 0:
        return plan("NEUTRAL / WAIT", "No plan", None, None, None, None, "ATR is zero; bars are flat.", [], "ATR is zero")

    if location["acceptance"] != "none" or label == "IMBALANCE":
        side = "higher" if location["acceptance"] == "above" or close > poc else "lower"
        return plan(
            "NEUTRAL / WAIT",
            f"Imbalance: market is seeking {side} value",
            None,
            None,
            None,
            None,
            "Balance rules are suspended until a new value area forms (overlapping session value areas).",
            [
                "Do not fade an accepted move outside value.",
                "Measured-move target for the break is one value-area width beyond the edge: "
                f"{_round(vah + (vah - val)) if side == 'higher' else _round(val - (vah - val))}.",
                "Re-run once two sessions overlap; a new balance will present new edges.",
            ],
            "no responsive edge while the auction is out of balance",
        )

    fa = location["failed_auction"]
    zone = location["zone"]
    # A failed-auction setup only applies while price is still near the edge
    # that failed. If price has since moved away (e.g. a look-below-fail on a
    # bar or two ago, but the close has since run up to the opposite edge),
    # trading the trap at today's close puts the entry at the wrong edge and
    # the target on the wrong side of it. Fall through to the normal
    # zone-based logic instead.
    # The trap also dies the moment price trades back through the extreme that
    # failed: a look-below-fail whose low has since been taken out is not a
    # trapped-seller setup, it is a breakdown. Without this the engine offers a
    # long at the value-area low while the close sits below the failed low --
    # an entry the market has already left behind, on a thesis its own
    # invalidation line calls dead.
    ext_alive = (
        location["failed_auction_extreme"] is not None
        and (
            close < location["failed_auction_extreme"]
            if fa == "look_above_fail"
            else close > location["failed_auction_extreme"]
        )
    )
    if fa == "look_above_fail" and ext_alive and zone in ("VAH_EDGE", "ABOVE_VALUE", "INSIDE_UPPER"):
        ext = location["failed_auction_extreme"]
        # Enter where price actually is. Pinning the entry to VAH when the close
        # has already rotated away from it prices a fill you would never get.
        entry = close
        return plan(
            "SHORT",
            "Look above and fail at VAH",
            entry,
            ext + buf,
            poc,
            val,
            f"Acceptance (2 closes) above {_round(ext)} voids the trap thesis.",
            [
                "Breakout buyers above VAH are trapped; their stops fuel the rotation back to POC.",
                "First target is the point of control, second the value-area low.",
                "Stop sits beyond the failed high plus half an ATR, not a fixed distance from the fill.",
            ],
        )
    if fa == "look_below_fail" and ext_alive and zone in ("VAL_EDGE", "BELOW_VALUE", "INSIDE_LOWER"):
        ext = location["failed_auction_extreme"]
        entry = close
        return plan(
            "LONG",
            "Look below and fail at VAL",
            entry,
            ext - buf,
            poc,
            vah,
            f"Acceptance (2 closes) below {_round(ext)} voids the trap thesis.",
            [
                "Breakdown sellers below VAL are trapped; their covering fuels the rotation back to POC.",
                "First target is the point of control, second the value-area high.",
                "Stop sits beyond the failed low minus half an ATR.",
            ],
        )

    if zone in ("VAL_EDGE", "BELOW_VALUE"):
        return plan(
            "LONG",
            "Responsive buy at the value-area low",
            # Buy the edge or better. `close` when price has already dipped
            # through VAL, `val` when it is sitting just above it -- quoting the
            # edge while the close is below it prices a worse fill than the one
            # actually on offer.
            min(close, val),
            rng_lo - buf,
            poc,
            vah,
            f"Two closes below VAL {val} (acceptance) or a close below the range low {rng_lo}.",
            [
                "In balance the value-area low is where responsive buyers have repeatedly stepped in.",
                "Target the point of control first; only hold for VAH if the rotation is fast.",
                "Stop beyond the range low plus half an ATR: the invalidation is acceptance, not a wick.",
            ]
            + (["Price is already below value on one close: this is a probe until it closes back inside."] if zone == "BELOW_VALUE" else []),
        )
    if zone in ("VAH_EDGE", "ABOVE_VALUE"):
        return plan(
            "SHORT",
            "Responsive sell at the value-area high",
            # Sell the edge or better -- the mirror of the VAL case above.
            max(close, vah),
            rng_hi + buf,
            poc,
            val,
            f"Two closes above VAH {vah} (acceptance) or a close above the range high {rng_hi}.",
            [
                "In balance the value-area high is where responsive sellers have repeatedly stepped in.",
                "Target the point of control first; only hold for VAL if the rotation is fast.",
                "Stop beyond the range high plus half an ATR: the invalidation is acceptance, not a wick.",
            ]
            + (["Price is already above value on one close: this is a probe until it closes back inside."] if zone == "ABOVE_VALUE" else []),
        )

    # Inside value: no edge. Publish the bracket to wait for.
    return plan(
        "NEUTRAL / WAIT",
        "Inside value: wait for a rotation to an edge",
        None,
        None,
        None,
        None,
        "Regime change to imbalance (acceptance outside value).",
        [
            f"Resting bracket: buy near VAL {val} (stop {_round(rng_lo - buf)}), sell near VAH {vah} (stop {_round(rng_hi + buf)}), target POC {poc}.",
            "At fair value both sides agree; entering here is a coin flip with a wide stop.",
            "A look-above-and-fail or look-below-and-fail on arrival at the edge is the strongest entry.",
        ],
        "price is inside value; no responsive edge until it reaches VAH or VAL",
    )


# -------------------------------------------------------------- narrative
def _narrative(
    symbol: str,
    tf: str,
    regime: Dict[str, Any],
    composite: Dict[str, Any],
    location: Dict[str, Any],
    plan: Dict[str, Any],
) -> str:
    label = regime["label"]
    score = regime["score"]
    zone = location["zone"].replace("_", " ").lower()
    head = {
        "BALANCE": "is in balance",
        "IMBALANCE": "is out of balance",
        "TRANSITION": "is testing the edge of balance",
        "UNKNOWN": "has too few bars to classify",
    }[label]
    s = (
        f"{symbol} {tf} {head}"
        + (f" (balance score {score:.2f})" if score is not None else "")
        + f". Value sits between {composite['val']} and {composite['vah']} with the point of control at {composite['poc']}; "
        f"the last close {location['close']} is {zone}."
    )
    if location["acceptance"] != "none":
        s += f" Price has been accepted {location['acceptance']} value, so the balance playbook is suspended."
    elif location["failed_auction"] != "none":
        s += " The last push through the edge failed and closed back inside value: a trapped-trader rotation is the setup."
    if plan["bias"] != "NEUTRAL / WAIT":
        s += f" Plan: {plan['bias'].lower()} at {plan['entry']}, stop {plan['stop']}, first target {plan['target_1']}."
    else:
        s += f" Plan: {plan['setup'].lower()}."
    return s


# -------------------------------------------------------------- orchestrator
def evaluate_bars(
    bars: Sequence[Dict[str, Any]],
    symbol: str,
    timeframe: str,
) -> Dict[str, Any]:
    """Run the full AMT read on bars already in hand."""
    bars = [
        b
        for b in bars
        if all(math.isfinite(_f(b.get(k))) for k in ("open", "high", "low", "close"))
    ]
    if len(bars) < 20:
        return {
            "available": False,
            "reason": f"need at least 20 bars, got {len(bars)}",
            "symbol": symbol,
            "timeframe": timeframe,
        }
    atr = average_true_range(bars)
    context_profile = build_profile(bars, AMT_THRESHOLDS["composite_bins"], atr)
    if not context_profile:
        return {"available": False, "reason": "bars have no price range", "symbol": symbol, "timeframe": timeframe}

    sessions = session_profiles(bars, timeframe, atr)
    session_bars = max(1, round(len(bars) / max(1, len(sessions))))

    window = find_balance_window(sessions, bars, timeframe)
    balance_bars = bars[window["bar_index_start"] :]
    composite = build_profile(balance_bars, AMT_THRESHOLDS["composite_bins"], atr) or context_profile
    if composite is context_profile:
        balance_bars = bars

    regime = balance_score(balance_bars, composite, sessions, session_bars)
    location = locate_price(balance_bars, composite, atr)
    activity = activity_profile(balance_bars, composite, max(8, session_bars * AMT_THRESHOLDS["recent_sessions"]))
    stats = rotation_statistics(sessions)  # all sessions: more samples, a better hit-rate
    stats["sessions_in_balance"] = window["sessions"]
    evidence = build_evidence(regime, composite, location, activity, sessions)
    plan = build_trade_plan(regime, composite, location, atr)

    bull = sum(e["weight"] for e in evidence if e["direction"] == "bullish")
    bear = sum(e["weight"] for e in evidence if e["direction"] == "bearish")
    lean = "bullish" if bull > bear + 0.05 else "bearish" if bear > bull + 0.05 else "neutral"

    context_profile = dict(context_profile)
    context_profile.pop("bins", None)

    return {
        "available": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "as_of": bars[-1].get("date"),
        "atr": _round(atr),
        "composite": composite,
        "context_profile": context_profile,
        "balance_window": window,
        "sessions": sessions,
        "session_bars": session_bars,
        "regime": regime,
        "location": location,
        "activity": activity,
        "rotation_stats": stats,
        "evidence": evidence,
        "directional_lean": {"label": lean, "bullish_weight": _round(bull, 3), "bearish_weight": _round(bear, 3)},
        "trade_plan": plan,
        "narrative": _narrative(symbol, timeframe, regime, composite, location, plan),
        "playbook": AMT_PLAYBOOK,
        "thresholds": AMT_THRESHOLDS,
    }


def analyze_amt(
    symbol: Optional[str],
    timeframe: Optional[str] = None,
    lookback: Optional[int] = None,
    ohlcv_series: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Entry point for ``GET /api/amt/analyze``.

    Loads bars from disk for `symbol` at `timeframe` (or uses a caller-supplied
    series) and returns the full read plus ``bars_meta`` saying exactly what
    was served, downgraded, or missing.
    """
    tf_norm = normalize_timeframe(timeframe or DEFAULT_TIMEFRAME)
    sym = (symbol or "").strip().upper()
    if ohlcv_series:
        bars = list(ohlcv_series)
        meta = bars_meta_from_series(bars, tf_norm)
    else:
        bars, meta = load_bars(sym, tf_norm, lookback)
    served_tf = meta.get("timeframe_served") or tf_norm
    if not bars:
        return {
            "available": False,
            "reason": meta.get("downgrade_reason") or "no bars",
            "symbol": sym or None,
            "timeframe": served_tf,
            "bars_meta": meta,
        }
    res = evaluate_bars(bars, sym or "SERIES", served_tf)
    res["bars_meta"] = meta
    res["bars"] = [
        {
            "date": b.get("date"),
            "open": _round(_f(b["open"])),
            "high": _round(_f(b["high"])),
            "low": _round(_f(b["low"])),
            "close": _round(_f(b["close"])),
            "volume": _round(_f(b.get("volume")), 0),
        }
        for b in bars
    ]
    return res
