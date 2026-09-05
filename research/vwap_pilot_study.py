"""Pilot study: does session VWAP carry information on the 1h bars we actually have?

Purpose: a cheap, causal, pre-registered-style check of the VWAP / volume
hypotheses in the 2026-09-01 audit, run on ``data/1h`` (yfinance, 7 bars per
regular session, ~730 trading days). It is a *screen*, not a backtest: no
position sizing, no path-dependent exits, close-to-close forward returns.

Everything at bar ``t`` uses bars ``<= t`` only:

* session VWAP  = cum(typical_price * volume) / cum(volume) within the day
* VWAP z        = (close - vwap) / volume-weighted sd of typical price so far
* rvol_slot     = volume / trailing median of the *same hour slot* over the
                  prior 20 sessions (exclusive of today)
* range_ratio   = session range so far / trailing median of session range at
                  the same slot over the prior 20 sessions
* rvol20        = trailing 140-bar std of 1h returns, shifted one bar
* trend20       = 140-bar close-to-close return, shifted one bar

Targets (never visible to the features):

* ret1    = next bar's close / this close - 1, same session only
* ret_eod = session's last close / this close - 1

Standard errors use a cluster bootstrap over *sessions* because every symbol
on the same day shares the market move; pooled binomial SEs would overstate
the evidence several-fold.

Run: ``python3 research/vwap_pilot_study.py [--symbols 120] [--json out.json]``
"""
from __future__ import annotations

import argparse
import glob
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HOURLY = ROOT / "data" / "1h"
MIN_BARS = 4900
LOOKBACK_SESSIONS = 20
BARS_PER_SESSION = 7
Z_EDGES = [-np.inf, -2.0, -1.0, -0.5, 0.5, 1.0, 2.0, np.inf]
Z_LABELS = ["<-2", "-2..-1", "-1..-0.5", "-0.5..0.5", "0.5..1", "1..2", ">2"]
BP = 1e4


def features_for_symbol(path: Path) -> pd.DataFrame | None:
    df = pd.read_parquet(path)
    if len(df) < MIN_BARS or "volume" not in df.columns:
        return None
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[(df["volume"] > 0) & (df["high"] >= df["low"])]
    day = df.index.normalize()
    counts = day.value_counts()
    full_days = counts[counts == BARS_PER_SESSION].index
    df = df[day.isin(full_days)]
    if df.empty:
        return None
    day = df.index.normalize()
    slot = df.index.hour
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    v = df["volume"].astype(float)
    g = pd.Series(day, index=df.index)
    cum_v = v.groupby(g).cumsum()
    cum_pv = (tp * v).groupby(g).cumsum()
    cum_pv2 = (tp * tp * v).groupby(g).cumsum()
    vwap = cum_pv / cum_v
    var = (cum_pv2 / cum_v - vwap * vwap).clip(lower=0.0)
    sd = np.sqrt(var)
    close = df["close"].astype(float)
    z = (close - vwap) / sd.replace(0.0, np.nan)
    dist_bp = (close / vwap - 1.0) * BP

    out = pd.DataFrame(index=df.index)
    out["symbol"] = path.stem
    out["day"] = day
    out["slot"] = slot
    out["vwap_z"] = z
    out["dist_bp"] = dist_bp
    out["above"] = (close > vwap).astype(int)

    # Same-slot trailing baselines, exclusive of the current session.
    vol_slot_med = v.groupby(slot).transform(
        lambda s: s.shift(1).rolling(LOOKBACK_SESSIONS, min_periods=10).median()
    )
    out["rvol_slot"] = v / vol_slot_med
    sess_range = (df["high"].groupby(g).cummax() - df["low"].groupby(g).cummin()) / close
    range_med = sess_range.groupby(slot).transform(
        lambda s: s.shift(1).rolling(LOOKBACK_SESSIONS, min_periods=10).median()
    )
    out["range_ratio"] = sess_range / range_med

    r = close.pct_change()
    out["rvol20"] = r.rolling(LOOKBACK_SESSIONS * BARS_PER_SESSION, min_periods=70).std().shift(1)
    out["trend20"] = (close / close.shift(LOOKBACK_SESSIONS * BARS_PER_SESSION) - 1.0).shift(1)

    prev_above = out["above"].shift(1)
    same_day = g.shift(1) == g
    out["cross_up"] = ((out["above"] == 1) & (prev_above == 0) & same_day).astype(int)
    out["cross_dn"] = ((out["above"] == 0) & (prev_above == 1) & same_day).astype(int)
    # Bars since the session's last cross (acceptance proxy).
    side_change = (out["above"] != prev_above) | ~same_day
    run_id = side_change.cumsum()
    out["bars_on_side"] = out.groupby(run_id).cumcount() + 1

    nxt = close.shift(-1)
    out["ret1_bp"] = np.where(g.shift(-1) == g, (nxt / close - 1.0) * BP, np.nan)
    last_close = close.groupby(g).transform("last")
    out["ret_eod_bp"] = (last_close / close - 1.0) * BP
    out.loc[out["slot"] == 15, "ret_eod_bp"] = np.nan  # last bar has no remaining session
    return out


def cluster_boot(sub: pd.DataFrame, col: str, reps: int = 400, seed: int = 0) -> tuple[float, float, float, int]:
    """Mean and 95% CI of ``col`` with a bootstrap over sessions."""
    s = sub[[col, "day"]].dropna()
    n = len(s)
    if n == 0:
        return (math.nan, math.nan, math.nan, 0)
    per_day = s.groupby("day")[col].agg(["sum", "count"])
    sums = per_day["sum"].to_numpy()
    cnts = per_day["count"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(sums), size=(reps, len(sums)))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    return (float(s[col].mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)), n)


def hit_rate(sub: pd.DataFrame, col: str) -> float:
    s = sub[col].dropna()
    return float((s > 0).mean()) if len(s) else math.nan


def table(panel: pd.DataFrame, key: str, target: str, title: str, order=None) -> list[dict]:
    rows = []
    groups = panel.groupby(key, observed=True)
    keys = order if order is not None else list(groups.groups.keys())
    for k in keys:
        if k not in groups.groups:
            continue
        sub = groups.get_group(k)
        m, lo, hi, n = cluster_boot(sub, target)
        rows.append({"bucket": str(k), "n": n, "mean_bp": round(m, 2), "ci_lo": round(lo, 2),
                     "ci_hi": round(hi, 2), "hit": round(hit_rate(sub, target), 4)})
    print(f"\n## {title}  (target={target})")
    print(f"{'bucket':>12} {'n':>8} {'mean_bp':>8} {'95% CI':>18} {'hit>0':>7}")
    for r in rows:
        print(f"{r['bucket']:>12} {r['n']:>8} {r['mean_bp']:>8.2f} [{r['ci_lo']:>7.2f},{r['ci_hi']:>7.2f}] {r['hit']:>7.3f}")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=120)
    ap.add_argument("--json", type=str, default=None)
    args = ap.parse_args()

    forced = ["SPY", "QQQ", "IWM"]
    paths = sorted(HOURLY.glob("*.parquet"))
    chosen: list[Path] = [HOURLY / f"{s}.parquet" for s in forced if (HOURLY / f"{s}.parquet").exists()]
    for p in paths:
        if len(chosen) >= args.symbols:
            break
        if p.stem in forced:
            continue
        chosen.append(p)

    frames = []
    for p in chosen:
        f = features_for_symbol(p)
        if f is not None:
            frames.append(f)
    panel = pd.concat(frames)
    panel = panel.dropna(subset=["vwap_z", "rvol_slot", "range_ratio", "rvol20"])
    days = np.sort(panel["day"].unique())
    cut = days[int(len(days) * 0.6)]
    panel["sample"] = np.where(panel["day"] < cut, "IS", "OOS")
    panel["z_bucket"] = pd.cut(panel["vwap_z"], Z_EDGES, labels=Z_LABELS)
    panel["vol_regime"] = pd.qcut(panel["rvol20"], 3, labels=["lowvol", "midvol", "highvol"])
    panel["trend_regime"] = np.where(panel["trend20"] > 0, "up20", "down20")

    results: dict = {
        "symbols": sorted(panel["symbol"].unique().tolist()),
        "n_obs": int(len(panel)),
        "sessions": int(len(days)),
        "first_day": str(pd.Timestamp(days[0]).date()),
        "split_day": str(pd.Timestamp(cut).date()),
        "last_day": str(pd.Timestamp(days[-1]).date()),
    }
    print(f"symbols={len(results['symbols'])} obs={results['n_obs']} sessions={results['sessions']} "
          f"{results['first_day']} .. {results['last_day']} (OOS from {results['split_day']})")
    base1 = cluster_boot(panel, "ret1_bp")
    base_eod = cluster_boot(panel, "ret_eod_bp")
    print(f"unconditional ret1 mean {base1[0]:.2f}bp CI[{base1[1]:.2f},{base1[2]:.2f}]  "
          f"ret_eod mean {base_eod[0]:.2f}bp CI[{base_eod[1]:.2f},{base_eod[2]:.2f}]")
    results["unconditional"] = {"ret1": base1, "ret_eod": base_eod}

    results["A_z_next_bar"] = table(panel, "z_bucket", "ret1_bp", "A. Next-bar return by VWAP z bucket", Z_LABELS)
    results["B_z_eod"] = table(panel, "z_bucket", "ret_eod_bp", "B. Rest-of-session return by VWAP z bucket", Z_LABELS)

    print("\n## C. Extreme z buckets, in-sample vs out-of-sample (ret_eod_bp)")
    results["C_oos"] = {}
    for samp in ("IS", "OOS"):
        sub = panel[panel["sample"] == samp]
        results["C_oos"][samp] = table(sub, "z_bucket", "ret_eod_bp", f"   {samp}", ["<-2", "-2..-1", "1..2", ">2"])

    print("\n## D. Extreme z buckets by volatility regime (ret_eod_bp)")
    results["D_vol"] = {}
    for reg in ("lowvol", "midvol", "highvol"):
        sub = panel[panel["vol_regime"] == reg]
        results["D_vol"][reg] = table(sub, "z_bucket", "ret_eod_bp", f"   {reg}", ["<-2", "-2..-1", "1..2", ">2"])

    print("\n## D2. Extreme z buckets by 20-day trend (ret_eod_bp)")
    results["D_trend"] = {}
    for reg in ("up20", "down20"):
        sub = panel[panel["trend_regime"] == reg]
        results["D_trend"][reg] = table(sub, "z_bucket", "ret_eod_bp", f"   {reg}", ["<-2", "-2..-1", "1..2", ">2"])

    print("\n## E. By hour slot, z < -1 vs z > 1 (ret_eod_bp)")
    results["E_slot"] = {}
    for lab, mask in (("z<-1", panel["vwap_z"] < -1), ("z>1", panel["vwap_z"] > 1)):
        results["E_slot"][lab] = table(panel[mask], "slot", "ret_eod_bp", f"   {lab}", [9, 10, 11, 12, 13, 14])

    print("\n## F. VWAP crosses (ret1_bp / ret_eod_bp)")
    results["F_cross"] = {}
    for lab, mask in (("cross_up", panel["cross_up"] == 1), ("cross_dn", panel["cross_dn"] == 1),
                      ("no_cross_above", (panel["cross_up"] == 0) & (panel["above"] == 1)),
                      ("no_cross_below", (panel["cross_dn"] == 0) & (panel["above"] == 0))):
        sub = panel[mask]
        r1 = cluster_boot(sub, "ret1_bp")
        re = cluster_boot(sub, "ret_eod_bp")
        results["F_cross"][lab] = {"ret1": r1, "ret_eod": re}
        print(f"{lab:>16} n={r1[3]:>7} ret1 {r1[0]:>6.2f} [{r1[1]:.2f},{r1[2]:.2f}]  ret_eod {re[0]:>6.2f} [{re[1]:.2f},{re[2]:.2f}]")

    print("\n## G. Acceptance: bars on the same side of VWAP (ret_eod_bp), above vs below")
    results["G_accept"] = {}
    panel["side_run"] = pd.cut(panel["bars_on_side"], [0, 1, 2, 3, 7], labels=["1", "2", "3", "4+"])
    for lab, mask in (("above", panel["above"] == 1), ("below", panel["above"] == 0)):
        results["G_accept"][lab] = table(panel[mask], "side_run", "ret_eod_bp", f"   {lab}", ["1", "2", "3", "4+"])

    print("\n## H. 'Something building': slot rvol >= 1.5 and range_ratio <= 0.7, vs the rest")
    build = (panel["rvol_slot"] >= 1.5) & (panel["range_ratio"] <= 0.7)
    panel["abs_eod"] = panel["ret_eod_bp"].abs()
    results["H_build"] = {}
    for lab, mask in (("building", build), ("rest", ~build)):
        sub = panel[mask]
        a = cluster_boot(sub, "abs_eod")
        d = cluster_boot(sub, "ret_eod_bp")
        results["H_build"][lab] = {"abs_eod": a, "ret_eod": d}
        print(f"{lab:>10} n={a[3]:>7} |ret_eod| {a[0]:>6.2f} [{a[1]:.2f},{a[2]:.2f}]   signed {d[0]:>6.2f} [{d[1]:.2f},{d[2]:.2f}]")
    # Same test conditioned on the side of VWAP.
    for lab, mask in (("building & above", build & (panel["above"] == 1)), ("building & below", build & (panel["above"] == 0))):
        sub = panel[mask]
        d = cluster_boot(sub, "ret_eod_bp")
        results["H_build"][lab] = {"ret_eod": d}
        print(f"{lab:>18} n={d[3]:>7} signed ret_eod {d[0]:>6.2f} [{d[1]:.2f},{d[2]:.2f}]")

    print("\n## I. Relative volume alone (slot-normalised), ret_eod_bp and |ret_eod|")
    panel["rv_bucket"] = pd.cut(panel["rvol_slot"], [0, 0.5, 0.8, 1.2, 2.0, 3.0, np.inf],
                                labels=["<0.5", "0.5-0.8", "0.8-1.2", "1.2-2", "2-3", ">3"])
    results["I_rvol_signed"] = table(panel, "rv_bucket", "ret_eod_bp", "   signed", ["<0.5", "0.5-0.8", "0.8-1.2", "1.2-2", "2-3", ">3"])
    results["I_rvol_abs"] = table(panel, "rv_bucket", "abs_eod", "   absolute", ["<0.5", "0.5-0.8", "0.8-1.2", "1.2-2", "2-3", ">3"])

    print("\n## J. Interaction: z < -1 split by slot rvol (ret_eod_bp)")
    sub = panel[panel["vwap_z"] < -1]
    results["J_z_rvol"] = table(sub, "rv_bucket", "ret_eod_bp", "   z<-1", ["<0.5", "0.5-0.8", "0.8-1.2", "1.2-2", "2-3", ">3"])
    sub = panel[panel["vwap_z"] > 1]
    results["J_z_rvol_pos"] = table(sub, "rv_bucket", "ret_eod_bp", "   z>1", ["<0.5", "0.5-0.8", "0.8-1.2", "1.2-2", "2-3", ">3"])

    print("\n## K. SPY / QQQ / IWM only, z buckets (ret_eod_bp)")
    idx = panel[panel["symbol"].isin(["SPY", "QQQ", "IWM"])]
    results["K_index"] = table(idx, "z_bucket", "ret_eod_bp", "   index ETFs", Z_LABELS)

    if args.json:
        Path(args.json).write_text(json.dumps(results, default=str, indent=1))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
