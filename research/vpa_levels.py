"""Support/resistance zones and volume-at-price for the VPA engine.

Fixes two verified defects (contract §0):

* **D5** -- the old engine reported ``min()``/``max()`` over the last 30 bars
  and labelled the result a "30-bar fractal". There was no pivot detection, no
  clustering, no touch counting and no role reversal. A single spike low became
  "the floor of support" no matter how briefly price visited it.
* **D6** -- volume-at-price put each bar's **entire** volume into the single bin
  containing its close. A bar spanning six bins contributed to one, so the POC
  was an artefact of where closes happened to land rather than of where volume
  actually traded.

Everything here is numeric and drawable: `detect_levels` emits the contract §4
``levels[]`` and ``vap`` blocks so the frontend can render bands, a POC line and
value-area shading instead of parsing prose.

Zones are ATR-scaled bands rather than single prices. A breakout needs a close
beyond the zone plus rising volume. A ceiling closed through on rising volume
can later act as support. Volume at price distributes each bar across its range.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from research.vpa_thresholds import BOOK_REFS, VPA_THRESHOLDS


def _cfg() -> Dict[str, Any]:
    return VPA_THRESHOLDS["levels"]


# ------------------------------------------------------------------- ATR ---

def average_true_range(bars: Sequence[Dict[str, Any]], period: Optional[int] = None) -> float:
    """Wilder true range averaged over `period` bars (simple mean).

    ATR is the unit every tolerance here is expressed in, so that a $2 band on
    a $600 stock and a $0.02 band on a $3 stock are both "half a bar's range" --
    a relative reading, not an absolute one.
    """
    if not bars:
        return 0.0
    period = int(period or _cfg()["atr_period"])
    trs: List[float] = []
    prev_close = bars[0]["close"]
    for b in bars:
        tr = max(
            b["high"] - b["low"],
            abs(b["high"] - prev_close),
            abs(b["low"] - prev_close),
        )
        trs.append(float(tr))
        prev_close = b["close"]
    window = trs[-period:] if len(trs) > period else trs
    if not window:
        return 0.0
    atr = sum(window) / len(window)
    if atr > 0:
        return atr
    # Degenerate (flat) series: fall back to a fraction of price so downstream
    # ATR-scaled tolerances stay finite instead of collapsing to zero-width.
    last = bars[-1]["close"]
    return abs(last) * 0.001 if last else 1e-6


# ---------------------------------------------------------------- pivots ---

def find_pivots(
    bars: Sequence[Dict[str, Any]],
    left: Optional[int] = None,
    right: Optional[int] = None,
) -> Dict[str, List[int]]:
    """Fractal pivots with n-bar left/right confirmation.

    A pivot high at ``i`` is a bar whose high is >= every high in
    ``[i-left, i+right]`` and strictly greater than at least one neighbour on
    each side, so a flat shelf does not emit a pivot on every bar of the shelf.
    """
    cfg = _cfg()
    left = int(left if left is not None else cfg["pivot_left"])
    right = int(right if right is not None else cfg["pivot_right"])
    n = len(bars)
    highs: List[int] = []
    lows: List[int] = []
    if n < left + right + 1:
        return {"highs": highs, "lows": lows}

    for i in range(left, n - right):
        h = bars[i]["high"]
        l = bars[i]["low"]
        window = range(i - left, i + right + 1)
        if all(bars[j]["high"] <= h for j in window):
            if any(bars[j]["high"] < h for j in range(i - left, i)) and any(
                bars[j]["high"] < h for j in range(i + 1, i + right + 1)
            ):
                highs.append(i)
        if all(bars[j]["low"] >= l for j in window):
            if any(bars[j]["low"] > l for j in range(i - left, i)) and any(
                bars[j]["low"] > l for j in range(i + 1, i + right + 1)
            ):
                lows.append(i)
    return {"highs": highs, "lows": lows}


# --------------------------------------------------------------- zones -----

def _cluster(
    bars: Sequence[Dict[str, Any]],
    pivot_idx: Sequence[int],
    kind: str,
    atr: float,
) -> List[Dict[str, Any]]:
    """Group nearby pivots of one kind into ATR-scaled zones."""
    cfg = _cfg()
    if not pivot_idx:
        return []
    price_of = (lambda i: bars[i]["high"]) if kind == "resistance" else (lambda i: bars[i]["low"])
    tol = max(atr * float(cfg["cluster_atr_mult"]), 1e-9)

    ordered = sorted(pivot_idx, key=price_of)
    clusters: List[List[int]] = [[ordered[0]]]
    for idx in ordered[1:]:
        current = clusters[-1]
        anchor = sum(price_of(j) for j in current) / len(current)
        if abs(price_of(idx) - anchor) <= tol:
            current.append(idx)
        else:
            clusters.append([idx])

    return [
        _zone_from_members([(j, price_of(j), kind) for j in members], atr)
        for members in clusters
    ]


def _zone_from_members(
    members: Sequence[Tuple[int, float, str]], atr: float
) -> Dict[str, Any]:
    """Build a zone from ``(bar_idx, price, origin)`` triples.

    The band is always re-derived from the pivots it contains, so merging two
    zones is the same operation as building one. Unioning two boxes instead
    would let a merged band grow wider than the prices that justify it.
    """
    cfg = _cfg()
    pad = atr * float(cfg["min_zone_atr_mult"])
    prices = [p for _, p, _ in members]
    origins = [o for _, _, o in members]
    # Majority origin decides how the zone is cited. A tie goes to the more
    # recent pivot: that is the role the market last used the band in.
    counts = {o: origins.count(o) for o in set(origins)}
    top = max(counts.values())
    tied = [o for o, c in counts.items() if c == top]
    origin = tied[0] if len(tied) == 1 else max(members, key=lambda m: m[0])[2]
    return {
        "price": sum(prices) / len(prices),
        "low": min(prices) - pad,
        "high": max(prices) + pad,
        "origin": origin,
        "origins": sorted(set(origins)),
        "members": sorted(members),
        "pivot_bars": sorted({int(i) for i, _, _ in members}),
        "pivot_count": len(members),
    }


def _band_overlap(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Overlap of two bands as a fraction of the narrower one."""
    inter = min(a["high"], b["high"]) - max(a["low"], b["low"])
    if inter <= 0:
        return 0.0
    narrower = min(a["high"] - a["low"], b["high"] - b["low"])
    return (inter / narrower) if narrower > 0 else 0.0


def _merge_overlapping(zones: List[Dict[str, Any]], atr: float) -> List[Dict[str, Any]]:
    """Fold zones whose bands substantially overlap into single levels.

    Highs and lows are clustered independently, so a ceiling and a floor
    discovered at the same price arrive as two zones. They are one level: left
    unmerged, one bar crossing them emits one piece of evidence per copy,
    which both inflates the score and fills the ledger with duplicate rows.
    """
    threshold = float(_cfg()["zone_merge_overlap"])
    pool = sorted(zones, key=lambda z: z["price"])
    changed = True
    while changed and len(pool) > 1:
        changed = False
        for i in range(len(pool)):
            for j in range(i + 1, len(pool)):
                if _band_overlap(pool[i], pool[j]) >= threshold:
                    combined = _zone_from_members(
                        list(pool[i]["members"]) + list(pool[j]["members"]), atr
                    )
                    pool = [z for k, z in enumerate(pool) if k not in (i, j)]
                    pool.append(combined)
                    pool.sort(key=lambda z: z["price"])
                    changed = True
                    break
            if changed:
                break
    return pool


def _count_touches(bars: Sequence[Dict[str, Any]], zone: Dict[str, Any]) -> Dict[str, Any]:
    """A touch is any bar whose high-low range intersects the zone band."""
    touches = 0
    last_touch = None
    for i, b in enumerate(bars):
        if b["low"] <= zone["high"] and b["high"] >= zone["low"]:
            touches += 1
            last_touch = i
    return {"touches": touches, "last_touch_bar": last_touch}


def _strength(zone: Dict[str, Any], n_bars: int) -> float:
    """Blend touch count, recency and pivot count into [0, 1].

    Recency matters because a ceiling nobody has tested in a year is a fact
    about history, not about the current auction. Older tests count for less.
    """
    cfg = _cfg()
    touch_component = min(1.0, zone["touches"] / float(cfg["touch_saturation"]))
    last = zone.get("last_touch_bar")
    if last is None:
        recency_component = 0.0
    else:
        age = max(0, (n_bars - 1) - int(last))
        recency_component = 0.5 ** (age / float(cfg["strength_half_life"]))
    pivot_component = min(1.0, zone["pivot_count"] / 3.0)
    raw = (
        float(cfg["strength_touch_weight"]) * touch_component
        + float(cfg["strength_recency_weight"]) * recency_component
        + float(cfg["strength_pivot_weight"]) * pivot_component
    )
    return round(max(0.0, min(1.0, raw)), 3)


def _volume_baseline(bars: Sequence[Dict[str, Any]], idx: int, window: int) -> float:
    start = max(0, idx - window)
    prior = [b["volume"] for b in bars[start:idx]]
    prior = [v for v in prior if v > 0]
    if not prior:
        return 0.0
    return sum(prior) / len(prior)


def _has_clear_water(
    zone: Dict[str, Any],
    direction: str,
    siblings: Sequence[Dict[str, Any]],
    clear: float,
) -> bool:
    """Is there open space beyond the band, or just the next shelf up?

    A breakout is price leaving
    congestion for an area with no overhead supply. Breaking one band only to
    land inside the next one is price moving *within* congestion. Grading that
    on volume manufactures a breakout (or a fakeout) on almost every bar of a
    range, which drowns the bar-derived signals that carry the actual read.
    """
    if direction == "up":
        ahead = [z["low"] for z in siblings if z["low"] > zone["high"]]
        return (not ahead) or (min(ahead) - zone["high"]) >= clear
    ahead = [z["high"] for z in siblings if z["high"] < zone["low"]]
    return (not ahead) or (zone["low"] - max(ahead)) >= clear


def _classify_break(
    bars: Sequence[Dict[str, Any]],
    zone: Dict[str, Any],
    atr: float,
    vol_window: int,
    siblings: Sequence[Dict[str, Any]] = (),
) -> Optional[Dict[str, Any]]:
    """Find the most recent close beyond the zone.

    A valid breakout needs both a distinct close beyond the band **and**
    rising volume. A close beyond the band on falling volume is the book's
    fakeout/trap, and is reported as such rather than as strength.

    The event is the bar that *crossed*, not merely the latest bar that happens
    to sit outside. Judging the volume of a quiet bar three days after the break
    would grade the drift, not the break, and would fail to confirm breakouts
    that plainly happened.
    """
    cfg = _cfg()
    clear = atr * float(cfg["clear_water_atr_mult"])
    scan = int(cfg["breakout_scan_bars"])
    n = len(bars)
    start = max(1, n - scan)
    latest: Optional[Dict[str, Any]] = None
    for i in range(start, n):
        c = bars[i]["close"]
        prev = bars[i - 1]["close"]
        if c > zone["high"] + clear and prev <= zone["high"] + clear:
            direction = "up"
        elif c < zone["low"] - clear and prev >= zone["low"] - clear:
            direction = "down"
        else:
            continue
        if not _has_clear_water(zone, direction, siblings, clear):
            # Moved out of one band and straight into the next: congestion,
            # not a breakout. Nothing to grade.
            continue
        base = _volume_baseline(bars, i, vol_window)
        ratio = (bars[i]["volume"] / base) if base > 0 else 0.0
        latest = {
            "bar": i,
            "direction": direction,
            "volume_ratio": round(ratio, 2),
            "confirmed": ratio >= float(cfg["breakout_volume_ratio"]),
            "fakeout_risk": ratio > 0 and ratio <= float(cfg["breakout_fakeout_volume_ratio"]),
            "clear_water": round(abs(c - (zone["high"] if direction == "up" else zone["low"])), 4),
        }
    return latest


def detect_levels(
    bars: Sequence[Dict[str, Any]],
    pivot_left: Optional[int] = None,
    pivot_right: Optional[int] = None,
) -> Dict[str, Any]:
    """Full level set: zones, VAP, breakout state and the nearest actionable levels."""
    cfg = _cfg()
    n = len(bars)
    if n == 0:
        return {
            "levels": [],
            "vap": None,
            "atr": 0.0,
            "pivot_highs": [],
            "pivot_lows": [],
            "nearest_support": None,
            "nearest_resistance": None,
            "breakouts": [],
        }

    atr = average_true_range(bars)
    pivots = find_pivots(bars, pivot_left, pivot_right)
    last_close = bars[-1]["close"]
    vol_window = int(VPA_THRESHOLDS["signals"]["volume_baseline_bars"])

    raw_zones = _merge_overlapping(
        _cluster(bars, pivots["highs"], "resistance", atr)
        + _cluster(bars, pivots["lows"], "support", atr),
        atr,
    )

    # Two passes: a break can only be judged against the bands around it, so
    # every surviving zone has to exist before any of them is classified.
    surviving: List[Dict[str, Any]] = []
    for zone in raw_zones:
        zone.update(_count_touches(bars, zone))
        if zone["touches"] >= int(cfg["min_touches"]):
            surviving.append(zone)

    levels: List[Dict[str, Any]] = []
    breakouts: List[Dict[str, Any]] = []
    for zone in surviving:
        siblings = [z for z in surviving if z is not zone]
        brk = _classify_break(bars, zone, atr, vol_window, siblings)
        role_reversed = False
        kind = "support" if zone["price"] < last_close else "resistance"
        if brk and brk["confirmed"] and ((n - 1) - brk["bar"]) >= int(cfg["role_reversal_min_bars"]):
            # A ceiling closed through on rising volume can later act as support.
            if brk["direction"] == "up" and zone["origin"] == "resistance" and last_close > zone["high"]:
                role_reversed = True
                kind = "support"
            elif brk["direction"] == "down" and zone["origin"] == "support" and last_close < zone["low"]:
                role_reversed = True
                kind = "resistance"
        entry = {
            "price": round(zone["price"], 4),
            "low": round(zone["low"], 4),
            "high": round(zone["high"], 4),
            "kind": kind,
            "origin": zone["origin"],
            "strength": _strength(zone, n),
            "touches": int(zone["touches"]),
            "source": "pivot_cluster",
            "role_reversed": role_reversed,
            "last_touch_bar": zone["last_touch_bar"],
            "pivot_bars": zone["pivot_bars"],
            "origins": zone.get("origins", [zone["origin"]]),
            "book_ref": BOOK_REFS["role_reversal"] if role_reversed else BOOK_REFS["support_resistance"],
        }
        if brk:
            entry["breakout"] = brk
        levels.append(entry)

    levels.sort(key=lambda z: (-z["strength"], abs(z["price"] - last_close)))
    levels = levels[: int(cfg["max_zones"])]
    levels.sort(key=lambda z: z["price"])

    # Breakouts are read off the *surviving* levels, then gated and collapsed
    # per bar. One bar crossing several bands is one market event, not one per
    # band; and a band broken long ago and left several ATR behind is history,
    # not a live signal. Each level keeps its own `breakout` for role reversal,
    # which is precisely the case where the break is meant to be old.
    max_age = int(cfg["breakout_max_age_bars"])
    max_distance = atr * float(cfg["breakout_max_distance_atr"])
    by_bar: Dict[int, Dict[str, Any]] = {}
    for entry in levels:
        brk = entry.get("breakout")
        if not brk:
            continue
        if ((n - 1) - int(brk["bar"])) > max_age:
            continue
        if abs(entry["price"] - last_close) > max_distance:
            continue
        candidate = {
            **brk,
            "price": entry["price"],
            "zone_kind": entry["kind"],
            "origin": entry["origin"],
            "strength": entry["strength"],
        }
        prior = by_bar.get(int(brk["bar"]))
        if prior is None or candidate["strength"] > prior["strength"]:
            by_bar[int(brk["bar"])] = candidate
    breakouts = [by_bar[k] for k in sorted(by_bar)]

    # "Nearest" means nearest *actionable*: a band the last bar is sitting
    # inside is not a floor to lean on or a ceiling to aim at.
    min_dist = atr * float(cfg["min_actionable_distance_atr"])
    supports = [z for z in levels if z["price"] < last_close - min_dist]
    resistances = [z for z in levels if z["price"] > last_close + min_dist]
    nearest_support = max(supports, key=lambda z: z["price"]) if supports else None
    nearest_resistance = min(resistances, key=lambda z: z["price"]) if resistances else None

    return {
        "levels": levels,
        "vap": compute_vap(bars),
        "atr": round(atr, 4),
        "pivot_highs": pivots["highs"],
        "pivot_lows": pivots["lows"],
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "breakouts": breakouts,
        "last_close": last_close,
    }


# ------------------------------------------------------------------ VAP ----

def compute_vap(bars: Sequence[Dict[str, Any]], n_bins: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Volume at price, distributing each bar across its **high-low range**.

    This is the D6 fix. The old code did::

        bin_idx = int((bar["close"] - price_min) / bin_size)
        vap_bins[bin_idx] += bar["volume"]

    which credits a bar that traded through six bins to whichever bin its close
    fell in. Here each bin receives the share of the bar's volume proportional
    to how much of the bar's range it covers -- a uniform distribution across
    the range, which is the standard assumption when intra-bar prints are not
    available. Zero-range bars put their whole volume in their single bin.
    """
    cfg = VPA_THRESHOLDS["vap"]
    if not bars:
        return None
    n_bins = int(n_bins or cfg["bins"])
    price_min = min(b["low"] for b in bars)
    price_max = max(b["high"] for b in bars)
    if not math.isfinite(price_min) or not math.isfinite(price_max) or price_max <= price_min:
        return None
    bin_size = (price_max - price_min) / n_bins
    if bin_size <= 0:
        return None

    volumes = [0.0] * n_bins

    def bin_of(price: float) -> int:
        return min(n_bins - 1, max(0, int((price - price_min) / bin_size)))

    for b in bars:
        vol = float(b["volume"])
        if vol <= 0:
            continue
        lo, hi = float(b["low"]), float(b["high"])
        lo_i, hi_i = bin_of(lo), bin_of(hi)
        if hi <= lo or lo_i == hi_i:
            volumes[lo_i] += vol
            continue
        span = hi - lo
        for i in range(lo_i, hi_i + 1):
            b_lo = price_min + i * bin_size
            b_hi = b_lo + bin_size
            overlap = min(hi, b_hi) - max(lo, b_lo)
            if overlap > 0:
                volumes[i] += vol * (overlap / span)

    total = sum(volumes)
    if total <= 0:
        return None

    poc_idx = max(range(n_bins), key=lambda i: volumes[i])
    # Value area: expand outward from the POC, always taking the heavier
    # neighbour, until `value_area_pct` of total volume is enclosed.
    lo_i = hi_i = poc_idx
    covered = volumes[poc_idx]
    target = total * float(cfg["value_area_pct"])
    while covered < target and (lo_i > 0 or hi_i < n_bins - 1):
        below = volumes[lo_i - 1] if lo_i > 0 else -1.0
        above = volumes[hi_i + 1] if hi_i < n_bins - 1 else -1.0
        if above >= below:
            hi_i += 1
            covered += volumes[hi_i]
        else:
            lo_i -= 1
            covered += volumes[lo_i]

    bins = [
        {
            "low": round(price_min + i * bin_size, 4),
            "high": round(price_min + (i + 1) * bin_size, 4),
            "volume": round(volumes[i], 2),
            "pct_of_total": round(volumes[i] / total, 4),
        }
        for i in range(n_bins)
    ]

    return {
        "poc": round(price_min + (poc_idx + 0.5) * bin_size, 4),
        "poc_low": round(price_min + poc_idx * bin_size, 4),
        "poc_high": round(price_min + (poc_idx + 1) * bin_size, 4),
        "value_area_low": round(price_min + lo_i * bin_size, 4),
        "value_area_high": round(price_min + (hi_i + 1) * bin_size, 4),
        "value_area_pct": round(covered / total, 4),
        "total_volume": round(total, 2),
        "bin_size": round(bin_size, 6),
        "method": "range_distributed",
        "book_ref": BOOK_REFS["volume_at_price"],
        "bins": bins,
    }


# Trend lines and congestion geometry.
#
# A trend line joins successive pivots as price leaves a range. Congestion
# patterns measured here: falling triangle, rising triangle, pennant, triple
# top, and triple bottom.


def _slope_per_bar(points: Sequence[Tuple[int, float]]) -> Optional[float]:
    """Least-squares slope in price units per bar."""
    n = len(points)
    if n < 2:
        return None
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n
    denom = sum((p[0] - mean_x) ** 2 for p in points)
    if denom <= 0:
        return None
    return sum((p[0] - mean_x) * (p[1] - mean_y) for p in points) / denom


def detect_dynamic_trend(
    bars: Sequence[Dict[str, Any]],
    pivots: Optional[Dict[str, List[int]]] = None,
    lookback: int = 60,
) -> Optional[Dict[str, Any]]:
    """Ch.8: join the recent pivots and report the trend they describe.

    Bullish requires rising pivot lows, bearish falling pivot highs. The slope
    is normalised by ATR so it is comparable across instruments.
    """
    if len(bars) < 20:
        return None
    pivots = pivots or find_pivots(bars)
    atr = average_true_range(bars) or 0.0
    if atr <= 0:
        return None
    start = max(0, len(bars) - lookback)

    lows = [(i, bars[i]["low"]) for i in pivots["lows"] if i >= start]
    highs = [(i, bars[i]["high"]) for i in pivots["highs"] if i >= start]
    low_slope = _slope_per_bar(lows)
    high_slope = _slope_per_bar(highs)

    if low_slope is None and high_slope is None:
        return None

    # "Rising" / "falling" is measured against ATR so a 1c drift on a $500
    # stock is not mistaken for a trend.
    thresh = 0.02 * atr
    rising_lows = low_slope is not None and low_slope > thresh and len(lows) >= 2
    falling_highs = high_slope is not None and high_slope < -thresh and len(highs) >= 2

    if rising_lows and not falling_highs:
        direction, anchor, slope = "bullish", lows, low_slope
    elif falling_highs and not rising_lows:
        direction, anchor, slope = "bearish", highs, high_slope
    else:
        return {
            "direction": "none",
            "detail": "Pivots do not line up into a dynamic trend; structure is two-sided.",
            "pivot_count": len(lows) + len(highs),
            "book_ref": "rule.dynamic-trend",
        }

    return {
        "direction": direction,
        "slope_per_bar": round(slope, 6),
        "slope_atr_per_bar": round(slope / atr, 4),
        "pivot_count": len(anchor),
        "pivot_bars": [i for i, _ in anchor],
        "detail": (
            f"{len(anchor)} {'rising pivot lows' if direction == 'bullish' else 'falling pivot highs'} "
            f"join into a dynamic {direction} trend line "
            f"({abs(slope) / atr:.2f} ATR per bar)."
        ),
        "book_ref": "rule.dynamic-trend",
    }


def detect_congestion_patterns(
    bars: Sequence[Dict[str, Any]],
    pivots: Optional[Dict[str, List[int]]] = None,
    lookback: int = 70,
) -> List[Dict[str, Any]]:
    """Congestion patterns measured from pivot geometry.

    Each is defined off pivot geometry, tolerance scaled by ATR so "flat" means
    flat relative to the instrument's own volatility.
    """
    out: List[Dict[str, Any]] = []
    if len(bars) < 25:
        return out
    pivots = pivots or find_pivots(bars)
    atr = average_true_range(bars) or 0.0
    if atr <= 0:
        return out

    start = max(0, len(bars) - lookback)
    highs = [(i, bars[i]["high"]) for i in pivots["highs"] if i >= start][-4:]
    lows = [(i, bars[i]["low"]) for i in pivots["lows"] if i >= start][-4:]
    flat = 0.35 * atr  # within this of each other counts as a shelf

    def _is_flat(pts):
        return len(pts) >= 2 and (max(p[1] for p in pts) - min(p[1] for p in pts)) <= flat

    hs, ls = _slope_per_bar(highs), _slope_per_bar(lows)

    # Triangles are resolved first. A rising triangle also has a ceiling tested
    # three times, so reporting "Triple Top" alongside it would double-count the
    # same shelf and hand the scorer two contradictory directions.
    ceiling_is_triangle = (
        _is_flat(highs) and ls is not None and ls > 0.02 * atr and len(lows) >= 2
    )
    floor_is_triangle = (
        _is_flat(lows) and hs is not None and hs < -0.02 * atr and len(highs) >= 2
    )

    # Triple top / bottom: three tests of the same level.
    if not ceiling_is_triangle and len(highs) >= 3 and _is_flat(highs[-3:]):
        out.append({
            "pattern": "Triple Top",
            "direction": "bearish",
            "bars": [i for i, _ in highs[-3:]],
            "level": round(sum(p[1] for p in highs[-3:]) / 3, 4),
            "detail": "Three pivot highs rejected at the same ceiling; supply repeatedly overwhelms demand.",
            "book_ref": "rule.triple-top",
        })
    if not floor_is_triangle and len(lows) >= 3 and _is_flat(lows[-3:]):
        out.append({
            "pattern": "Triple Bottom",
            "direction": "bullish",
            "bars": [i for i, _ in lows[-3:]],
            "level": round(sum(p[1] for p in lows[-3:]) / 3, 4),
            "detail": "Three pivot lows held at the same floor; the market is testing support and finding buyers.",
            "book_ref": "rule.triple-bottom",
        })

    # Rising triangle: flat ceiling, rising floor.
    if ceiling_is_triangle:
        out.append({
            "pattern": "Rising Triangle",
            "direction": "bullish",
            "bars": [i for i, _ in highs] + [i for i, _ in lows],
            "level": round(sum(p[1] for p in highs) / len(highs), 4),
            "detail": "Flat ceiling with higher lows: demand is absorbing supply at a fixed level.",
            "book_ref": "rule.rising-triangle",
        })

    # Falling triangle: flat floor, falling ceiling.
    if floor_is_triangle:
        out.append({
            "pattern": "Falling Triangle",
            "direction": "bearish",
            "bars": [i for i, _ in lows] + [i for i, _ in highs],
            "level": round(sum(p[1] for p in lows) / len(lows), 4),
            "detail": "Flat floor with lower highs: supply is pressing into a fixed support shelf.",
            "book_ref": "rule.falling-triangle",
        })

    # Pennant: both boundaries converging. Direction comes from the
    # prior move, since a pennant is a continuation pattern.
    if (
        hs is not None and ls is not None
        and hs < -0.01 * atr and ls > 0.01 * atr
        and len(highs) >= 2 and len(lows) >= 2
    ):
        span = max(0, len(bars) - lookback)
        prior = bars[span]["close"] if span < len(bars) else bars[0]["close"]
        latest = bars[-1]["close"]
        direction = "bullish" if latest >= prior else "bearish"
        out.append({
            "pattern": "Pennant",
            "direction": direction,
            "bars": [i for i, _ in highs] + [i for i, _ in lows],
            "level": round((highs[-1][1] + lows[-1][1]) / 2, 4),
            "detail": (
                "Highs and lows converging into a pennant; a continuation of the "
                f"preceding {direction} move once volume confirms the break."
            ),
            "book_ref": "rule.pennant",
        })

    return out
