"""Per-signal event study and trade-plan simulation for the VPA engine.

`research/vpa_backtest.py` answers "does the aggregate direction carry
information?". This harness answers the questions a live trader actually acts
on, which that one never touched:

* **Does each signal, the bar it fires, predict anything?** Every read
  is taken on every bar (stride 1) and only *fresh* evidence -- anchored on the
  last bar of the window -- is scored, because that is the moment the signal
  appears on the live tab.
* **Does the trade plan (entry / stop / target) make money?** Each directional
  read with a quoted R:R is simulated bar by bar.
* **Do level signals repaint?** A breakout judged against a zone whose pivots
  formed *after* the break is visible on a later read but was not visible live.

Live parity, which is the point of this file:

* The engine sees exactly the window live sees: the trailing
  ``default_lookback(timeframe)`` bars, not an ever-growing history.
* Entry is the **next bar's open**. The read is only knowable once the as-of
  bar has closed, so the as-of close is not a price anyone could have traded.
* Excess return is measured against the **same-date cross-sectional mean**, so
  a market-wide up day does not read as bullish skill.
* Confidence intervals resample whole dates (cluster bootstrap), because every
  symbol on a date shares that date's market move.
* The trade simulation is conservative: a bar touching both stop and target is
  a stop; a gap through the stop fills at the open, not at the stop.

CLI:
    python3 -m research.vpa_signal_backtest --universe 80 --jobs 4 --json runs/vpa_signal_bt.json
    python3 -m research.vpa_signal_backtest --timeframe 1h --universe 40 --jobs 4
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

EDGE_ROOT = Path(__file__).resolve().parents[1]
if str(EDGE_ROOT) not in sys.path:
    sys.path.insert(0, str(EDGE_ROOT))

from research.vpa_bars import HOURLY_DIR, DAILY_DIRS, default_lookback, load_bars  # noqa: E402
from research.vpa_levels import detect_levels  # noqa: E402
from research.vpa_score import _trend_return, score_evidence  # noqa: E402
from research.vpa_thresholds import VPA_THRESHOLDS  # noqa: E402

HORIZONS: Tuple[int, ...] = (1, 5, 10)
MAX_HOLD_BARS = 20
LEVEL_SIGNALS = {"breakout_confirmed", "fakeout_risk", "role_reversal"}
DEFAULT_COST_BP = 10.0
DEFAULT_SPLIT_DATE = "2022-01-01"


def _sim_trade(
    bars: Sequence[Dict[str, Any]], t: int, direction: str, stop: float, target: float, cost_bp: float
) -> Optional[Dict[str, Any]]:
    """Walk forward from the open of bar `t`. Returns R multiple, or None if untradeable."""
    if t >= len(bars):
        return None
    entry = float(bars[t]["open"])
    long = direction == "BULLISH"
    risk = (entry - stop) if long else (stop - entry)
    if risk <= 0:
        # Gapped through the stop before the entry could be placed.
        return {"gap_through_stop": True}
    if (long and entry >= target) or ((not long) and entry <= target):
        return {"gap_through_target": True}
    exit_px = None
    outcome = "time"
    last = min(len(bars) - 1, t + MAX_HOLD_BARS - 1)
    for j in range(t, last + 1):
        b = bars[j]
        hit_stop = b["low"] <= stop if long else b["high"] >= stop
        hit_tgt = b["high"] >= target if long else b["low"] <= target
        if hit_stop:
            # A later bar that opens beyond the stop fills at the open.
            gap_fill = (j > t) and ((b["open"] < stop) if long else (b["open"] > stop))
            exit_px = b["open"] if gap_fill else stop
            outcome = "stop"
            break
        if hit_tgt:
            exit_px = target
            outcome = "target"
            break
    if exit_px is None:
        if last - t + 1 < MAX_HOLD_BARS:
            return None  # ran out of history, not a real time exit
        exit_px = float(bars[last]["close"])
    pnl = (exit_px - entry) if long else (entry - exit_px)
    cost = entry * cost_bp / 10000.0
    return {"r": pnl / risk, "r_net": (pnl - cost) / risk, "outcome": outcome}


def _symbol_reads(args: Tuple[str, str, int, float]) -> Tuple[str, List[Dict[str, Any]]]:
    symbol, timeframe, max_bars, cost_bp = args
    bars, meta = load_bars(symbol, timeframe, max_bars)
    window = default_lookback(meta.get("timeframe_served") or timeframe)
    if not bars or len(bars) < window + MAX_HOLD_BARS + 5:
        return symbol, []
    served = meta.get("timeframe_served") or timeframe
    trend_window = int(VPA_THRESHOLDS["signals"]["trend_window"])
    rows: List[Dict[str, Any]] = []
    for t in range(window, len(bars) - 1):
        w = bars[t - window:t]
        n = len(w)
        levels = detect_levels(w)
        scored = score_evidence(w, levels, {"timeframe_served": served, "last_bar": w[-1]["date"]})
        o = float(bars[t]["open"])
        if o <= 0:
            continue
        fwd = {}
        for h in HORIZONS:
            if t + h - 1 < len(bars):
                fwd[h] = float(bars[t + h - 1]["close"]) / o - 1.0
        fresh = []
        level_items = []
        for e in scored["evidence"]:
            anchor = max(e["bars"])
            if anchor == n - 1:
                fresh.append((e["signal"], e["direction"]))
            if e["signal"] in LEVEL_SIGNALS and anchor < n - 1:
                level_items.append((e["signal"], e["direction"], w[anchor]["date"]))
        plan = scored["trade_plan"]
        trade = None
        if scored["direction"] != "SIDEWAYS" and plan.get("risk_reward_ratio") is not None:
            trade = _sim_trade(bars, t, scored["direction"], plan["stop"], plan["target"], cost_bp)
            if trade is not None:
                trade["rr_quoted"] = plan["risk_reward_ratio"]
        last = w[-1]
        rng = last["high"] - last["low"]
        rows.append({
            "date": last["date"],
            "fwd": fwd,
            "dir": scored["direction"],
            "prob": scored["primary_probability_pct"],
            "fresh": fresh,
            "level_items": level_items,
            "trend": _trend_return(w, n - 1, trend_window),
            "atr_pct": (levels["atr"] / last["close"]) if last["close"] else None,
            "lower_frac": ((min(last["open"], last["close"]) - last["low"]) / rng) if rng > 0 else 0.0,
            "upper_frac": ((last["high"] - max(last["open"], last["close"])) / rng) if rng > 0 else 0.0,
            "trade": trade,
        })
    return symbol, rows


# ------------------------------------------------------------ statistics --

def _cluster_ci(pairs: Sequence[Tuple[str, float]], n_boot: int, seed: int) -> Tuple[float, float, float]:
    """Mean with a 95% CI from resampling whole dates."""
    if not pairs:
        return (float("nan"),) * 3
    by_date: Dict[str, List[float]] = defaultdict(list)
    for d, v in pairs:
        by_date[d].append(v)
    sums = np.array([sum(v) for v in by_date.values()])
    cnts = np.array([len(v) for v in by_date.values()])
    mean = float(sums.sum() / cnts.sum())
    if len(sums) < 5:
        return mean, float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(sums), size=(n_boot, len(sums)))
    boots = sums[idx].sum(axis=1) / np.maximum(cnts[idx].sum(axis=1), 1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return mean, float(lo), float(hi)


def _summarise(pairs: Sequence[Tuple[str, float]], n_boot: int, seed: int, split: str) -> Dict[str, Any]:
    def block(sub):
        mean, lo, hi = _cluster_ci(sub, n_boot, seed)
        hits = sum(1 for _, v in sub if v > 0)
        return {
            "n": len(sub),
            "mean_bp": round(mean * 1e4, 1) if not math.isnan(mean) else None,
            "ci_bp": [round(lo * 1e4, 1), round(hi * 1e4, 1)] if not math.isnan(lo) else None,
            "hit": round(hits / len(sub), 3) if sub else None,
        }
    is_ = [p for p in pairs if p[0] < split]
    oos = [p for p in pairs if p[0] >= split]
    return {"all": block(pairs), "is": block(is_), "oos": block(oos)}


def _verdict(s: Dict[str, Any]) -> str:
    a, i, o = s["all"], s["is"], s["oos"]
    if not a["ci_bp"] or a["n"] < 30:
        return "too few"
    if a["ci_bp"][0] > 0 and (o["mean_bp"] or 0) > 0 and (i["mean_bp"] or 0) > 0:
        return "EDGE"
    if a["ci_bp"][1] < 0 and (o["mean_bp"] or 0) < 0 and (i["mean_bp"] or 0) < 0:
        return "INVERTED"
    return "noise"


def analyse(rows: List[Dict[str, Any]], horizon: int, n_boot: int, seed: int, split: str) -> Dict[str, Any]:
    # Same-date cross-sectional benchmark: strips the market move out of every read.
    date_sum: Dict[str, float] = defaultdict(float)
    date_n: Dict[str, int] = defaultdict(int)
    for r in rows:
        if horizon in r["fwd"]:
            date_sum[r["date"]] += r["fwd"][horizon]
            date_n[r["date"]] += 1

    def excess(r) -> Optional[float]:
        if horizon not in r["fwd"] or date_n[r["date"]] < 5:
            return None
        return r["fwd"][horizon] - date_sum[r["date"]] / date_n[r["date"]]

    sign = {"bullish": 1.0, "bearish": -1.0, "BULLISH": 1.0, "BEARISH": -1.0}
    trend_move = float(VPA_THRESHOLDS["signals"]["trend_move_pct"])

    def trend_state(r) -> str:
        return "up" if r["trend"] > trend_move else "down" if r["trend"] < -trend_move else "flat"

    per_signal: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    per_signal_ctx: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    shape_ctx: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    per_dir: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    fire_counts: Dict[str, int] = defaultdict(int)
    for r in rows:
        x = excess(r)
        if x is None:
            continue
        if r["dir"] in ("BULLISH", "BEARISH"):
            per_dir[r["dir"]].append((r["date"], sign[r["dir"]] * x))
            per_dir[f"{r['dir']}@p>={70}" if r["prob"] >= 70 else f"{r['dir']}@p<70"].append(
                (r["date"], sign[r["dir"]] * x))
        seen = set()
        for sig, d in r["fresh"]:
            key = f"{sig}:{d}"
            if key in seen:
                continue
            seen.add(key)
            fire_counts[key] += 1
            per_signal[key].append((r["date"], sign[d] * x))
            per_signal_ctx[f"{key}|trend={trend_state(r)}"].append((r["date"], sign[d] * x))
        # Candle shape vs trend, independent of how the ledger names it: the
        # raw (unsigned-by-label) excess, so the label choice can be checked.
        if r["lower_frac"] >= 0.5 and r["upper_frac"] <= 0.28:
            shape_ctx[f"lower_wick_shape|trend={trend_state(r)}"].append((r["date"], x))
        if r["upper_frac"] >= 0.5 and r["lower_frac"] <= 0.28:
            shape_ctx[f"upper_wick_shape|trend={trend_state(r)}"].append((r["date"], x))

    total_reads = sum(1 for r in rows if excess(r) is not None)
    signals = {}
    for key, pairs in sorted(per_signal.items(), key=lambda kv: -len(kv[1])):
        s = _summarise(pairs, n_boot, seed, split)
        s["verdict"] = _verdict(s)
        s["fire_rate"] = round(fire_counts[key] / max(total_reads, 1), 4)
        signals[key] = s
    ctx = {k: _summarise(v, n_boot, seed, split) for k, v in sorted(per_signal_ctx.items()) if len(v) >= 30}
    shapes = {k: _summarise(v, n_boot, seed, split) for k, v in sorted(shape_ctx.items())}
    directions = {k: _summarise(v, n_boot, seed, split) for k, v in sorted(per_dir.items())}
    for v in directions.values():
        v["verdict"] = _verdict(v)
    return {"horizon": horizon, "reads": total_reads, "signals": signals,
            "signal_by_trend": ctx, "raw_shape_by_trend": shapes, "aggregate_direction": directions}


def analyse_trades(rows: List[Dict[str, Any]], split: str) -> Dict[str, Any]:
    trades = [(r["date"], r["dir"], r["trade"]) for r in rows if r.get("trade")]
    gaps = sum(1 for _, _, t in trades if t.get("gap_through_stop"))
    gap_t = sum(1 for _, _, t in trades if t.get("gap_through_target"))
    done = [(d, dr, t) for d, dr, t in trades if "r" in t]

    def block(sub):
        if not sub:
            return {"n": 0}
        r = np.array([t["r"] for _, _, t in sub])
        rn = np.array([t["r_net"] for _, _, t in sub])
        q = np.array([t["rr_quoted"] for _, _, t in sub])
        outc = defaultdict(int)
        for _, _, t in sub:
            outc[t["outcome"]] += 1
        # The quoted R:R implies a breakeven target-hit rate of 1/(1+RR).
        return {
            "n": len(sub),
            "mean_r": round(float(r.mean()), 3),
            "mean_r_net": round(float(rn.mean()), 3),
            "win_rate": round(float((r > 0).mean()), 3),
            "target_rate": round(outc["target"] / len(sub), 3),
            "stop_rate": round(outc["stop"] / len(sub), 3),
            "time_rate": round(outc["time"] / len(sub), 3),
            "median_quoted_rr": round(float(np.median(q)), 2),
            "breakeven_target_rate_at_median_rr": round(1.0 / (1.0 + float(np.median(q))), 3),
        }

    by_rr = {}
    for lo, hi in ((0, 1), (1, 2), (2, 3), (3, 99)):
        by_rr[f"rr[{lo},{hi})"] = block([x for x in done if lo <= x[2]["rr_quoted"] < hi])
    return {
        "plans_quoted": len(trades),
        "gap_through_stop": gaps,
        "gap_through_target": gap_t,
        "all": block(done),
        "is": block([x for x in done if x[0] < split]),
        "oos": block([x for x in done if x[0] >= split]),
        "long": block([x for x in done if x[1] == "BULLISH"]),
        "short": block([x for x in done if x[1] == "BEARISH"]),
        "by_quoted_rr": by_rr,
    }


def analyse_repaint(by_symbol: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Level signals shown on a past bar that were not there when that bar was live."""
    shown = defaultdict(int)
    repainted = defaultdict(int)
    for rows in by_symbol.values():
        fresh_at = {r["date"]: set(r["fresh"]) for r in rows}
        first_read = rows[0]["date"] if rows else None
        seen_pairs = set()
        for r in rows:
            for sig, d, anchor_date in r["level_items"]:
                if first_read is None or anchor_date < first_read:
                    continue
                pair = (sig, d, anchor_date)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                shown[sig] += 1
                if (sig, d) not in fresh_at.get(anchor_date, set()):
                    repainted[sig] += 1
    return {sig: {"shown_on_past_bars": shown[sig], "not_visible_live": repainted[sig],
                  "repaint_rate": round(repainted[sig] / shown[sig], 3) if shown[sig] else None}
            for sig in sorted(shown)}


def _universe(timeframe: str, n: int) -> List[str]:
    if timeframe in ("1h", "2h", "4h"):
        files = sorted(HOURLY_DIR.glob("*.parquet"))
    else:
        files = sorted(DAILY_DIRS[0].glob("*.parquet"))
    syms = [f.stem for f in files]
    return syms[:n] if n else syms


def main() -> None:
    ap = argparse.ArgumentParser(description="Per-signal event study + trade-plan simulation for VPA.")
    ap.add_argument("--symbols")
    ap.add_argument("--universe", type=int, default=60)
    ap.add_argument("--timeframe", default="1D")
    ap.add_argument("--max-bars", type=int, default=5000)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--cost-bp", type=float, default=DEFAULT_COST_BP)
    ap.add_argument("--n-boot", type=int, default=400)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--split-date", default=DEFAULT_SPLIT_DATE)
    ap.add_argument("--json")
    a = ap.parse_args()

    symbols = a.symbols.split(",") if a.symbols else _universe(a.timeframe, a.universe)
    tasks = [(s.strip().upper(), a.timeframe, a.max_bars, a.cost_bp) for s in symbols if s.strip()]
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    if a.jobs > 1:
        with ProcessPoolExecutor(max_workers=a.jobs) as ex:
            for fut in as_completed([ex.submit(_symbol_reads, t) for t in tasks]):
                sym, rows = fut.result()
                if rows:
                    by_symbol[sym] = rows
    else:
        for t in tasks:
            sym, rows = _symbol_reads(t)
            if rows:
                by_symbol[sym] = rows
    rows = [r for s in sorted(by_symbol) for r in by_symbol[s]]
    split = a.split_date if a.timeframe not in ("1h", "2h", "4h") else a.split_date

    report = {
        "timeframe": a.timeframe,
        "symbols": sorted(by_symbol),
        "reads": len(rows),
        "first_date": min((r["date"] for r in rows), default=None),
        "last_date": max((r["date"] for r in rows), default=None),
        "split_date": split,
        "cost_bp": a.cost_bp,
        "horizons": {h: analyse(rows, h, a.n_boot, a.seed, split) for h in HORIZONS},
        "trade_plan": analyse_trades(rows, split),
        "repaint": analyse_repaint(by_symbol),
    }
    out = json.dumps(report, indent=1, default=str)
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(out)
        print(f"wrote {a.json}: {len(rows)} reads over {len(by_symbol)} symbols")
    else:
        print(out)


if __name__ == "__main__":
    main()
