"""Signed evidence ledger and derived probabilities for the VPA engine.

This module exists to kill defects D4 and D7 (contract §0):

* **D4** -- `confidence_score` was a single hardcoded float on every path,
  `probability_pct` was a fixed pair of integers, and `risk_reward_ratio` was a
  fixed ``"1 : N"`` string. All three were invariant across symbol, timeframe
  and data. (The exact values are deliberately not repeated in this file: the
  regression guard below greps for them.)
* **D7** -- ``test_candles.detected`` and the ``stopping_or_topping`` fields
  were hardcoded ``True`` everywhere, including the no-data fallback.

Everything below is derived. Each detector emits a signed evidence item
``(signal, direction, weight, bars, book_ref, detail)``; the ledger aggregates
to `bull_score`/`bear_score`; a bounded logistic maps the net to a probability
which is then **squashed into [50, 80]** (complement in [20, 50]) because VPA
reads direction and is not a calibrated forecaster -- a 92% claim derived from
candle geometry is not defensible. Confidence is a function of bar count, signal agreement, data
recency and the timeframe-downgrade penalty. Risk/reward comes from the actual
entry/stop/target numbers and is ``None`` when any of them is unavailable.

Regression guard (contract §5): none of the four old constants may appear as a
literal on any code path. `tests/test_vpa_engine.py::
test_d4_no_old_constants_as_literals_in_derived_modules` asserts this by
scanning the source of every module in this package.

Thresholds live in `research/vpa_thresholds.py`; every rule carries an internal id.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from research.vpa_thresholds import BOOK_REFS, VPA_THRESHOLDS

# Timeframe codes this repo serves that are genuinely intraday (contract §2:
# there is no data below 1h). Daily and weekly bars have no hour-of-day slot
# to normalise against.
_INTRADAY_TIMEFRAMES = {"1h", "2h", "4h"}


def _sig() -> Dict[str, Any]:
    return VPA_THRESHOLDS["signals"]


def _w(name: str) -> float:
    return float(VPA_THRESHOLDS["weights"][name])


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ------------------------------------------------------------ bar metrics --

def _hour_slot(date_str: str) -> Optional[int]:
    """Hour-of-day slot for an intraday bar, or ``None`` for a date-only bar.

    `research/vpa_bars.py:_frame_to_bars` always calls ``ts.isoformat()``, and
    pandas emits a ``T00:00:00`` suffix even for a midnight (date-only)
    timestamp -- so the presence of ``"T"`` alone does NOT distinguish an
    intraday bar from a daily one; both contain it. A non-midnight clock is
    what actually means "this bar sits at a specific hour of the session".
    """
    if not date_str or "T" not in date_str:
        return None
    _, _, clock = date_str.partition("T")
    if len(clock) < 2:
        return None
    try:
        hour = int(clock[:2])
    except ValueError:
        return None
    return hour


def _is_intraday(bars: Sequence[Dict[str, Any]], timeframe: Optional[str]) -> bool:
    """Decide whether `bars` should be read with hour-of-day slot baselines.

    An explicit `timeframe` (e.g. from ``bars_meta["timeframe_served"]``) is
    trusted outright. Without one, fall back to scanning the bars themselves:
    any bar whose clock is not exactly midnight means real intraday
    timestamps are present (a genuine 00:00 bar never occurs in the hourly
    session grid -- hours 9-15 -- so this is unambiguous in practice).
    """
    if timeframe:
        return timeframe in _INTRADAY_TIMEFRAMES
    for b in bars:
        hour = _hour_slot(str(b.get("date", "")))
        if hour is not None and hour != 0:
            return True
    return False


def _central(values: Sequence[float], use_median: bool) -> float:
    return float(statistics.median(values)) if use_median else float(sum(values) / len(values))


def _baseline(
    values: Sequence[float],
    slots: Sequence[Optional[int]],
    i: int,
    window: int,
    sessions: int,
    min_slot_samples: int,
    use_median: bool,
) -> Tuple[float, str, int]:
    """Trailing baseline for `values[i]`, strictly exclusive of index i.

    Tries the same-hour-slot baseline first (median or mean of the trailing
    `sessions` same-slot occurrences, positive values only). Falls back to the
    legacy trailing all-bar mean over `window` bars when there is no slot for
    this bar, or too few same-slot samples to trust -- so behaviour degrades
    gracefully instead of emitting nothing.
    """
    slot = slots[i]
    if slot is not None:
        same_slot: List[float] = []
        for j in range(i - 1, -1, -1):
            if slots[j] != slot:
                continue
            v = values[j]
            if v > 0:
                same_slot.append(v)
            if len(same_slot) >= sessions:
                break
        if len(same_slot) >= min_slot_samples:
            base = _central(same_slot, use_median)
            kind = "slot_median" if use_median else "slot_mean"
            return base, kind, len(same_slot)

    start = max(0, i - window)
    prior = [v for v in values[start:i] if v > 0]
    if not prior:
        return 0.0, "trailing_mean", 0
    # Fallback path is deliberately always the mean -- it is the exact old
    # baseline, so daily/weekly bars (and thin-history intraday bars) are
    # provably unaffected by this fix.
    return float(sum(prior) / len(prior)), "trailing_mean", len(prior)


def bar_metrics(
    bars: Sequence[Dict[str, Any]],
    timeframe: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Per-bar geometry and *relative* volume/spread.

    Principle #3: volume is always read relative to the bars that came
    before it. Both baselines here are therefore trailing and **exclusive** of
    the bar under judgement -- including the current bar in its own average is
    what makes a genuine climax look merely "above average".

    On intraday bars (1h/2h/4h), volume and session range both carry a strong
    time-of-day U-shape, so a flat trailing window mixes hour-of-day slots and
    makes "ultra high volume" fire structurally at the open (docs/audits/
    2026-09-01-vwap-orderflow-evaluation.md §2.1). When the bar under judgement
    is intraday, its baseline is instead the trailing same-hour-slot values,
    never a later bar and never the current one; `timeframe` (typically
    `bars_meta["timeframe_served"]`) lets a caller state this explicitly, and
    absent that it is detected from the bar dates themselves. Daily/weekly
    bars have no slot and always use the legacy trailing-all-bar baseline.
    """
    cfg = _sig()
    window = int(cfg["volume_baseline_bars"])
    sessions = int(cfg["volume_baseline_sessions"])
    min_slot_samples = int(cfg["volume_baseline_min_slot_samples"])
    use_median = str(cfg.get("volume_baseline_estimator", "mean")).lower() == "median"

    intraday = _is_intraday(bars, timeframe)
    slots: List[Optional[int]] = (
        [_hour_slot(str(b.get("date", ""))) for b in bars] if intraday else [None] * len(bars)
    )
    raw_vol = [float(b.get("volume") or 0.0) for b in bars]
    raw_rng = [max(b["high"] - b["low"], 0.0) for b in bars]

    out: List[Dict[str, Any]] = []
    for i, b in enumerate(bars):
        rng = raw_rng[i]
        body = abs(b["close"] - b["open"])
        upper = b["high"] - max(b["open"], b["close"])
        lower = min(b["open"], b["close"]) - b["low"]

        vol_base, vol_kind, vol_n = _baseline(
            raw_vol, slots, i, window, sessions, min_slot_samples, use_median
        )
        rng_base, rng_kind, rng_n = _baseline(
            raw_rng, slots, i, window, sessions, min_slot_samples, use_median
        )
        out.append(
            {
                "i": i,
                "date": b.get("date", ""),
                "range": rng,
                "body": body,
                "upper_wick": max(upper, 0.0),
                "lower_wick": max(lower, 0.0),
                "is_up": b["close"] >= b["open"],
                "close_pos": ((b["close"] - b["low"]) / rng) if rng > 0 else 0.5,
                "vol_base": vol_base,
                "vol_base_kind": vol_kind,
                "vol_base_n": vol_n,
                "vol_ratio": (b["volume"] / vol_base) if vol_base > 0 else 0.0,
                "range_base": rng_base,
                "range_base_kind": rng_kind,
                "range_base_n": rng_n,
                "spread_ratio": (rng / rng_base) if rng_base > 0 else 0.0,
                "volume": b["volume"],
                "close": b["close"],
                "open": b["open"],
                "high": b["high"],
                "low": b["low"],
            }
        )
    return out


def _trend_return(bars: Sequence[Dict[str, Any]], i: int, window: int) -> float:
    j = max(0, i - window)
    base = bars[j]["close"]
    if base <= 0:
        return 0.0
    return (bars[i]["close"] - base) / base


def _recency(i: int, n: int) -> float:
    half = float(_sig()["evidence_half_life"])
    age = max(0, (n - 1) - i)
    return 0.5 ** (age / half) if half > 0 else 1.0


def _short_date(value: str) -> str:
    if not value:
        return ""
    if "T" in value:
        day, _, clock = value.partition("T")
        return f"{day[5:]} {clock[:5]}"
    return value[:10]


# -------------------------------------------------------------- detectors --

def build_evidence(
    bars: Sequence[Dict[str, Any]],
    levels: Optional[Dict[str, Any]] = None,
    timeframe: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Run every detector over the recent window and return the ledger.

    Each item is ``{signal, direction, weight, bars, book_ref, detail}``.
    Weight = base weight (from the thresholds dict) x an intensity multiplier
    for how extreme the trigger was x a recency decay, so a climax on the last
    bar outweighs the same climax forty bars ago.

    `timeframe` (typically ``bars_meta["timeframe_served"]``) tells
    `bar_metrics` whether to use hour-of-day slot baselines; omitted, it is
    detected from the bar dates themselves.
    """
    cfg = _sig()
    n = len(bars)
    if n < 3:
        return []
    metrics = bar_metrics(bars, timeframe)
    levels = levels or {}
    atr = float(levels.get("atr") or 0.0)
    scan_from = max(1, n - int(cfg["scan_window"]))
    ev: List[Dict[str, Any]] = []

    def add(signal: str, direction: str, base: float, idxs: List[int], ref_key: str,
            detail: str, intensity: float = 1.0) -> None:
        anchor = max(idxs)
        weight = base * _clamp(intensity, 0.55, 1.6) * _recency(anchor, n)
        if weight < float(cfg["min_evidence_weight"]):
            return
        ev.append(
            {
                "signal": signal,
                "direction": direction,
                "weight": round(weight, 4),
                "bars": idxs,
                "bar_dates": [_short_date(bars[k].get("date", "")) for k in idxs],
                "book_ref": BOOK_REFS[ref_key],
                "detail": detail,
            }
        )

    ultra = float(cfg["vol_ultra_high"])
    high_v = float(cfg["vol_high"])
    low_v = float(cfg["vol_low"])
    ultra_low = float(cfg["vol_ultra_low"])
    wide = float(cfg["spread_wide"])
    narrow = float(cfg["spread_narrow"])
    dominant = float(cfg["wick_dominant"])
    suppressed = float(cfg["wick_suppressed"])
    trend_window = int(cfg["trend_window"])
    trend_move = float(cfg["trend_move_pct"])

    for m in metrics[scan_from:]:
        i = m["i"]
        rng = m["range"]
        if rng <= 0 or m["vol_base"] <= 0 or m["range_base"] <= 0:
            continue
        vr = m["vol_ratio"]
        sr = m["spread_ratio"]
        up_frac = m["upper_wick"] / rng
        low_frac = m["lower_wick"] / rng
        body_frac = m["body"] / rng
        trend = _trend_return(bars, i, trend_window)
        intensity = vr / ultra if ultra > 0 else 1.0

        # --- Ch.6 Stopping volume: a down move decelerating on huge volume with
        # deep lower wicks. Effort (volume) without downward result = buying.
        if trend < -trend_move and vr >= ultra and low_frac >= dominant and m["close_pos"] >= 0.5:
            add("stopping_volume", "bullish", _w("stopping_volume"), [i], "stopping_volume",
                f"Volume {vr:.1f}x the 20-bar average with a lower wick {low_frac*100:.0f}% of the "
                f"bar's range while the {trend_window}-bar trend was {trend*100:.1f}%. Effort down, "
                "no downward result: buyers absorbing.", intensity)

        # --- Ch.6 Topping out volume: mirror image at the end of an up move.
        if trend > trend_move and vr >= ultra and up_frac >= dominant and m["close_pos"] <= 0.5:
            add("topping_out_volume", "bearish", _w("topping_out_volume"), [i], "topping_volume",
                f"Volume {vr:.1f}x average with an upper wick {up_frac*100:.0f}% of range after a "
                f"{trend*100:.1f}% advance. Effort up, price arcing over: supply hitting demand.",
                intensity)

        # --- Ch.6 Climaxes: wide-spread capitulation bars on ultra volume that
        # close away from the extreme.
        if vr >= ultra and sr >= wide and not m["is_up"] and m["close_pos"] >= float(cfg["close_upper_third"]):
            add("selling_climax", "bullish", _w("selling_climax"), [i], "selling_climax",
                f"Wide down bar ({sr:.1f}x average spread) on {vr:.1f}x volume closing in the top "
                f"{100-m['close_pos']*100:.0f}% of its range: sellers exhausted into buying.", intensity)
        if vr >= ultra and sr >= wide and m["is_up"] and m["close_pos"] <= float(cfg["close_lower_third"]):
            add("buying_climax", "bearish", _w("buying_climax"), [i], "buying_climax",
                f"Wide up bar ({sr:.1f}x average spread) on {vr:.1f}x volume closing in the bottom "
                f"{m['close_pos']*100:.0f}% of its range: demand met by heavy supply.", intensity)

        # --- Ch.5 No demand / no supply: narrow-spread bars whose volume is
        # lower than both preceding bars. The move has no participation.
        if i >= 2:
            prev1, prev2 = metrics[i - 1]["volume"], metrics[i - 2]["volume"]
            thinner = m["volume"] < prev1 and m["volume"] < prev2
            if m["is_up"] and sr <= narrow and vr <= low_v and thinner:
                add("no_demand", "bearish", _w("no_demand"), [i - 2, i - 1, i], "no_demand",
                    f"Up bar on a narrow spread ({sr:.2f}x) and {vr:.2f}x volume, lower than each of "
                    "the two prior bars: no professional buying behind the rise.", 1.0)
            if (not m["is_up"]) and sr <= narrow and vr <= low_v and thinner:
                add("no_supply", "bullish", _w("no_supply"), [i - 2, i - 1, i], "no_supply",
                    f"Down bar on a narrow spread ({sr:.2f}x) and {vr:.2f}x volume, lower than each of "
                    "the two prior bars: sellers have withdrawn.", 1.0)

        # --- Ch.5 Candle signatures read against volume.
        if low_frac >= dominant and up_frac <= suppressed and body_frac <= 0.45:
            if vr >= high_v:
                add("hammer", "bullish", _w("hammer"), [i], "hammer",
                    f"Hammer with a {low_frac*100:.0f}% lower wick on {vr:.1f}x volume: buying "
                    "absorption defending the level.", intensity)
            elif vr <= ultra_low:
                add("low_volume_test", "bullish", _w("low_volume_test"), [i], "testing",
                    f"Price probed lower and closed back up on only {vr:.2f}x volume: a successful "
                    "test -- the supply that would have met the probe is not there.", 1.0)
        if up_frac >= dominant and low_frac <= suppressed and body_frac <= 0.45:
            if vr >= high_v:
                signal = "hanging_man" if trend > trend_move else "shooting_star"
                ref = "hanging_man" if signal == "hanging_man" else "shooting_star"
                add(signal, "bearish", _w(signal), [i], ref,
                    f"{signal.replace('_', ' ').title()} with a {up_frac*100:.0f}% upper wick on "
                    f"{vr:.1f}x volume: buyers rejected at the highs.", intensity)
            elif vr <= ultra_low:
                add("low_volume_test", "bearish", _w("low_volume_test"), [i], "testing",
                    f"Rally probe rejected on {vr:.2f}x volume: no demand behind the test of higher "
                    "prices.", 1.0)
        if body_frac <= float(cfg["doji_body"]) and up_frac >= 0.30 and low_frac >= 0.30:
            direction = "bearish" if trend > trend_move else "bullish"
            add("long_legged_doji", direction, _w("long_legged_doji"), [i], "long_legged_doji",
                f"Long-legged doji on {vr:.1f}x volume after a {trend*100:.1f}% move: two-sided "
                "battle at an inflection.", 1.0)

        # --- Ch.2 Effort vs Result on wide-spread bars.
        if sr >= wide and m["is_up"]:
            if vr >= high_v:
                add("effort_result_validation", "bullish", _w("effort_result_validation"), [i],
                    "effort_result",
                    f"Wide up spread ({sr:.1f}x) matched by {vr:.1f}x volume: effort and result agree.",
                    1.0)
            elif vr <= low_v:
                add("effort_result_anomaly", "bearish", _w("effort_result_anomaly"), [i],
                    "effort_result",
                    f"Wide up spread ({sr:.1f}x) on only {vr:.2f}x volume: result without effort, the "
                    "book's trap up move.", 1.0)
        if sr >= wide and not m["is_up"]:
            if vr >= high_v:
                add("effort_result_validation", "bearish", _w("effort_result_validation"), [i],
                    "effort_result",
                    f"Wide down spread ({sr:.1f}x) matched by {vr:.1f}x volume: genuine liquidation.",
                    1.0)
            elif vr <= low_v:
                add("effort_result_anomaly", "bullish", _w("effort_result_anomaly"), [i],
                    "effort_result",
                    f"Wide down spread ({sr:.1f}x) on only {vr:.2f}x volume: falling without selling "
                    "pressure behind it.", 1.0)

        # --- Ch.6 Absorption / churning: maximum effort, minimal result.
        if sr <= narrow and vr >= ultra:
            direction = "bearish" if trend > trend_move else "bullish"
            add("absorption_churn", direction, _w("absorption_churn"), [i], "absorption",
                f"{vr:.1f}x volume produced only a {sr:.2f}x spread: heavy churning as one side "
                "absorbs the other.", intensity)

    # --- Ch.7 Breakouts, fakeouts and role reversal (level-derived, not bar-derived).
    for brk in levels.get("breakouts", []) or []:
        i = brk["bar"]
        direction = "bullish" if brk["direction"] == "up" else "bearish"
        if brk.get("confirmed"):
            add("breakout_confirmed", direction, _w("breakout_confirmed"), [i], "breakout",
                f"Close {brk['clear_water']:.2f} beyond the {brk['zone_kind']} band at "
                f"{brk['price']:.2f} on {brk['volume_ratio']:.1f}x volume, with volume "
                "confirming the break.", brk["volume_ratio"] / float(VPA_THRESHOLDS["levels"]["breakout_volume_ratio"]))
        elif brk.get("fakeout_risk"):
            # Deliberately signed *against* the breakout: a low-volume break is
            # the book's trap, not strength (contract §6).
            add("fakeout_risk", "bearish" if direction == "bullish" else "bullish",
                _w("fakeout_risk"), [i], "breakout",
                f"Price closed {'above' if brk['direction'] == 'up' else 'below'} the "
                f"{brk['zone_kind']} band at {brk['price']:.2f}, but on only "
                f"{brk['volume_ratio']:.1f}x volume. A break without rising volume is read "
                f"against the {brk['direction']}-move, not with it.", 1.0)

    for lvl in levels.get("levels", []) or []:
        if lvl.get("role_reversed"):
            anchor = lvl.get("breakout", {}).get("bar", n - 1)
            direction = "bullish" if lvl["kind"] == "support" else "bearish"
            add("role_reversal", direction, _w("role_reversal"), [anchor], "role_reversal",
                f"The {lvl['origin']} band at {lvl['price']:.2f} was closed through on rising volume "
                f"and is now acting as {lvl['kind']}: the ceiling has become the floor.", 1.0)

    # --- Ch.9 Where price sits relative to the volume that actually traded.
    vap = levels.get("vap")
    if vap and atr >= 0:
        last_close = bars[-1]["close"]
        if last_close > vap["value_area_high"]:
            add("value_area_position", "bullish", _w("value_area_position"), [n - 1],
                "volume_at_price",
                f"Price {last_close:.2f} is above the value area high {vap['value_area_high']:.2f}; "
                f"the volume shelf at the POC {vap['poc']:.2f} sits beneath as support.", 1.0)
        elif last_close < vap["value_area_low"]:
            add("value_area_position", "bearish", _w("value_area_position"), [n - 1],
                "volume_at_price",
                f"Price {last_close:.2f} is below the value area low {vap['value_area_low']:.2f}; "
                f"the volume shelf at the POC {vap['poc']:.2f} sits overhead as resistance.", 1.0)

    # --- Ch.2 Aggregate supply/demand: the trend is the net result.
    net_trend = _trend_return(bars, n - 1, min(trend_window * 2, n - 1))
    if abs(net_trend) >= trend_move:
        add("trend_context", "bullish" if net_trend > 0 else "bearish", _w("trend_context"),
            [n - 1], "supply_demand",
            f"Net {net_trend*100:.1f}% over the last {min(trend_window*2, n-1)} bars: "
            f"{'demand' if net_trend > 0 else 'supply'} has been winning in aggregate.",
            min(1.5, abs(net_trend) / max(trend_move, 1e-9) / 3.0))

    ev.sort(key=lambda e: -e["weight"])
    return ev[: int(cfg["max_evidence_items"])]


# ---------------------------------------------------------------- scoring --

def _bars_per_day(timeframe: Optional[str]) -> float:
    return {"1h": 7.0, "2h": 3.5, "4h": 2.0, "1D": 1.0, "1W": 0.2}.get(timeframe or "1D", 1.0)


def _staleness_days(last_bar: Optional[str]) -> Optional[float]:
    if not last_bar:
        return None
    try:
        ts = datetime.fromisoformat(str(last_bar).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - ts
    return max(0.0, delta.total_seconds() / 86400.0)


def compute_confidence(
    bars: Sequence[Dict[str, Any]],
    evidence: Sequence[Dict[str, Any]],
    bull: float,
    bear: float,
    bars_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """confidence = f(bar count, signal agreement, data recency, downgrade penalty).

    Contract §5. Every component is observable, and a downgraded timeframe must
    lower confidence -- if the user asked for 15m and got 1h, the read is about
    a different market than the one they selected.
    """
    cfg = VPA_THRESHOLDS["confidence"]
    meta = bars_meta or {}
    n = len(bars)

    coverage = _clamp(n / float(cfg["full_coverage_bars"]), 0.0, 1.0)
    total = bull + bear
    agreement = (abs(bull - bear) / total) if total > 0 else 0.0
    density = _clamp(len(evidence) / float(cfg["full_density_items"]), 0.0, 1.0)

    served = meta.get("timeframe_served") or "1D"
    stale_after = float(cfg["stale_after_days"].get(served, 5))
    days = _staleness_days(meta.get("last_bar") or (bars[-1].get("date") if bars else None))
    if days is None:
        recency = 0.5
    elif days <= stale_after:
        recency = 1.0
    else:
        recency = 0.5 ** ((days - stale_after) / float(cfg["stale_decay_days"]))

    raw = (
        float(cfg["weight_coverage"]) * coverage
        + float(cfg["weight_agreement"]) * agreement
        + float(cfg["weight_recency"]) * recency
        + float(cfg["weight_density"]) * density
    )
    penalty = float(cfg["downgrade_penalty"]) if meta.get("downgraded") else 1.0
    method_ceiling = float(cfg["method_ceiling"])
    score = _clamp(raw * penalty * method_ceiling, float(cfg["floor"]), float(cfg["ceiling"]))

    return {
        "confidence_score": round(score, 3),
        "components": {
            "coverage": round(coverage, 3),
            "agreement": round(agreement, 3),
            "recency": round(recency, 3),
            "evidence_density": round(density, 3),
            "downgrade_penalty": round(penalty, 3),
            "method_ceiling": method_ceiling,
            "bar_count": n,
            "data_age_days": round(days, 1) if days is not None else None,
        },
        "method": "weighted components x downgrade penalty x method ceiling",
    }


def build_trade_plan(
    bars: Sequence[Dict[str, Any]],
    levels: Dict[str, Any],
    direction: str,
) -> Dict[str, Any]:
    """Entry / stop / target from real levels, and the R:R that follows.

    places stops beyond natural market-defined barriers rather than at
    round numbers, so the stop sits a fraction of an ATR outside the level's
    band. If there is no level to target -- price at the top of the window with
    no overhead pivot cluster -- the target is **unavailable** and the ratio is
    ``None``. It is never a stand-in string.
    """
    cfg = VPA_THRESHOLDS["trade"]
    if not bars:
        return {"entry": None, "stop": None, "target": None, "risk_reward_ratio": None,
                "basis": "no bars"}
    atr = float(levels.get("atr") or 0.0)
    entry = float(bars[-1]["close"])
    support = levels.get("nearest_support")
    resistance = levels.get("nearest_resistance")
    pad = atr * float(cfg["stop_atr_pad"])
    # Swing fallbacks must clear the same "is this actually a level price has to
    # travel to" bar as the pivot zones, otherwise a fresh-lows symbol gets a
    # stop one tick under the last bar and an absurd ratio falls out.
    min_dist = atr * float(VPA_THRESHOLDS["levels"]["min_actionable_distance_atr"])

    def _swing(kind: str) -> Optional[tuple]:
        for width in (20, len(bars)):
            window = bars[-min(len(bars), width):]
            if kind == "low":
                value = min(b["low"] for b in window)
                if value < entry - min_dist:
                    return value, f"the {len(window)}-bar swing low {value:.2f}"
            else:
                value = max(b["high"] for b in window)
                if value > entry + min_dist:
                    return value, f"the {len(window)}-bar swing high {value:.2f}"
        return None

    stop = target = None
    stop_basis = target_basis = None

    if direction == "BULLISH":
        if support:
            stop, stop_basis = support["low"] - pad, f"below support band {support['low']:.2f}"
        else:
            swing = _swing("low")
            if swing:
                stop, stop_basis = swing[0] - pad, f"below {swing[1]}"
        if resistance:
            target, target_basis = resistance["price"], f"nearest resistance band {resistance['price']:.2f}"
        else:
            swing = _swing("high")
            if swing:
                target, target_basis = swing[0], swing[1]
    elif direction == "BEARISH":
        if resistance:
            stop, stop_basis = resistance["high"] + pad, f"above resistance band {resistance['high']:.2f}"
        else:
            swing = _swing("high")
            if swing:
                stop, stop_basis = swing[0] + pad, f"above {swing[1]}"
        if support:
            target, target_basis = support["price"], f"nearest support band {support['price']:.2f}"
        else:
            swing = _swing("low")
            if swing:
                target, target_basis = swing[0], swing[1]

    rr = None
    if stop is not None and target is not None:
        risk = abs(entry - stop)
        reward = abs(target - entry)
        min_risk = max(atr * float(cfg["min_risk_atr"]), 1e-9)
        wrong_side = (
            (direction == "BULLISH" and (stop >= entry or target <= entry))
            or (direction == "BEARISH" and (stop <= entry or target >= entry))
        )
        if risk >= min_risk and reward >= atr * float(cfg["min_target_atr"]) and not wrong_side:
            rr = round(reward / risk, int(cfg["rr_round"]))

    return {
        "entry": round(entry, 4),
        "stop": round(stop, 4) if stop is not None else None,
        "target": round(target, 4) if target is not None else None,
        "risk_reward_ratio": rr,
        "stop_basis": stop_basis,
        "target_basis": target_basis,
        "book_ref": BOOK_REFS["support_resistance"],
        "unavailable_reason": None if rr is not None else (
            "no overhead level to target" if target is None else
            "no level below to place a stop" if stop is None else
            "risk or reward too small to quote a meaningful ratio"
        ),
    }


def _cause_bars(bars: Sequence[Dict[str, Any]], levels: Dict[str, Any]) -> int:
    """How long price has been building a cause inside the value area (Ch.2)."""
    vap = levels.get("vap")
    if not vap:
        return min(len(bars), 20)
    lo, hi = vap["value_area_low"], vap["value_area_high"]
    count = 0
    for b in reversed(bars):
        if lo <= b["close"] <= hi:
            count += 1
        else:
            break
    return count or min(len(bars), 10)


def score_evidence(
    bars: Sequence[Dict[str, Any]],
    levels: Optional[Dict[str, Any]] = None,
    bars_meta: Optional[Dict[str, Any]] = None,
    extra_evidence: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Aggregate the ledger into direction, probabilities, confidence and a plan."""
    cfg = VPA_THRESHOLDS["scoring"]
    levels = levels or {}
    timeframe = (bars_meta or {}).get("timeframe_served")
    evidence = list(build_evidence(bars, levels, timeframe))
    if extra_evidence:
        evidence.extend(extra_evidence)
        evidence.sort(key=lambda e: -e["weight"])

    bull = sum(e["weight"] for e in evidence if e["direction"] == "bullish")
    bear = sum(e["weight"] for e in evidence if e["direction"] == "bearish")
    net = bull - bear
    k = float(cfg["logistic_k"])
    prior = float(cfg["prior_mass"])
    # Balance, not accumulation: a ledger of 20 mildly bullish items must not
    # outrank a ledger of 3 unanimously bullish ones simply by being longer.
    balance = net / (bull + bear + prior)
    p_bull = 1.0 / (1.0 + math.exp(-k * balance))

    ceil_pct = int(cfg["probability_ceiling"])
    neutral = float(cfg["neutral_band"])

    if abs(p_bull - 0.5) < neutral:
        direction = "SIDEWAYS"
    elif p_bull > 0.5:
        direction = "BULLISH"
    else:
        direction = "BEARISH"

    # `primary_raw` is max(p, 1-p), so it is always >= 50 -- a hard clamp at
    # `ceil_pct` therefore flattened every strongly-directional read onto the
    # exact same number (9 of 30 real runs pinned at 80), destroying the
    # ordering the ledger had just computed. Squash the [50, 100] range onto
    # [50, ceil_pct] instead: 50 stays 50, the ceiling is still never breached,
    # and two different ledgers keep two different numbers.
    primary_raw = max(p_bull, 1.0 - p_bull) * 100.0
    span = max(1.0, float(ceil_pct) - 50.0)
    squashed = 50.0 + (primary_raw - 50.0) / 50.0 * span
    primary_pct = int(round(_clamp(squashed, 50.0, float(ceil_pct))))
    alternative_pct = 100 - primary_pct

    conf = compute_confidence(bars, evidence, bull, bear, bars_meta)
    plan = build_trade_plan(bars, levels, direction)

    # D7: these must reflect what the ledger actually found, not a constant.
    stopping_signals = [e for e in evidence if e["signal"] in
                        ("stopping_volume", "selling_climax", "absorption_churn")]
    topping_signals = [e for e in evidence if e["signal"] in
                       ("topping_out_volume", "buying_climax", "hanging_man")]
    test_signals = [e for e in evidence if e["signal"] in ("low_volume_test", "no_supply", "no_demand")]

    if stopping_signals or topping_signals:
        lead = max(stopping_signals + topping_signals, key=lambda e: e["weight"])
        stopping = {
            "detected": True,
            "type": "Stopping Volume" if lead in stopping_signals else "Topping Out Volume",
            "details": lead["detail"],
            "bars": lead["bars"],
            "book_ref": lead["book_ref"],
        }
    else:
        stopping = {
            "detected": False,
            "type": "None",
            "details": "No climactic or absorption volume found in the scanned window.",
            "bars": [],
            "book_ref": BOOK_REFS["stopping_volume"],
        }

    if test_signals:
        lead = max(test_signals, key=lambda e: e["weight"])
        kind = {
            "low_volume_test": "Low Volume Test",
            "no_supply": "No Supply (Low Volume Down Bar)",
            "no_demand": "No Demand (Low Volume Up Bar)",
        }[lead["signal"]]
        tests = {
            "detected": True,
            "type": kind,
            "result": "Successful" if lead["direction"] == "bullish" else "Failed / bearish test",
            "details": lead["detail"],
            "bars": lead["bars"],
            "book_ref": lead["book_ref"],
        }
    else:
        tests = {
            "detected": False,
            "type": "None",
            "result": "None",
            "details": "No low-volume test of supply or demand in the scanned window.",
            "bars": [],
            "book_ref": BOOK_REFS["testing"],
        }

    validations = sum(1 for e in evidence if e["signal"] in
                      ("effort_result_validation", "breakout_confirmed", "hammer", "shooting_star"))
    anomalies = sum(1 for e in evidence if e["signal"] in
                    ("effort_result_anomaly", "fakeout_risk", "absorption_churn",
                     "no_demand", "no_supply", "stopping_volume", "topping_out_volume"))
    if anomalies > validations:
        verdict = "ANOMALY"
    elif validations >= max(1, anomalies * 2):
        verdict = "VALIDATION"
    else:
        verdict = "MIXED"

    return {
        "evidence": evidence,
        "bull_score": round(bull, 4),
        "bear_score": round(bear, 4),
        "direction": direction,
        "primary_probability_pct": primary_pct,
        "alternative_probability_pct": alternative_pct,
        "confidence": conf,
        "trade_plan": plan,
        "stopping_or_topping": stopping,
        "test_candles": tests,
        "effort_vs_result_verdict": verdict,
        "cause_bars": _cause_bars(bars, levels),
        "probability_basis": {
            "bull_score": round(bull, 4),
            "bear_score": round(bear, 4),
            "net_score": round(net, 4),
            "method": "logistic + linear squash",
            "logistic_k": k,
            "balance": round(balance, 4),
            "prior_mass": prior,
            "raw_probability_pct": round(primary_raw, 1),
            # The primary read is max(p, 1-p), so it cannot fall below 50.
            # Its band is [50, ceiling]; the alternative takes the complement.
            "band": [50, ceil_pct],
            "alternative_band": [100 - ceil_pct, 50],
            "clamped": False,
            "evidence_count": len(evidence),
            "note": (
                "VPA is directional evidence, not a calibrated forecast. The "
                "percentage ranks the weight of signals for and against; "
                "it is not a modelled hit rate. The scale is compressed into "
                f"50-{ceil_pct}% because candle geometry does not support "
                "confident extremes."
            ),
        },
    }
