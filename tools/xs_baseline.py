#!/usr/bin/env python3
"""xs_baseline.py — transparent cross-sectional baselines for the 557-name universe.

Deliberately dumb: no learning, no fitting, no parameters chosen from results.
Each signal is ranked cross-sectionally per date; we go long the top decile and
short the bottom decile, dollar-neutral, holding HOLD days via HOLD overlapping
tranches, marking to market daily on open-to-open returns.

Purpose:
  1. Give run_xs_alpha_v3.py something to beat. A learned model that cannot
     outperform 12-1 momentum is not adding information.
  2. Independently cross-check the portfolio construction. The v2 engine stamped
     a 5-day return on the entry date and annualised it with sqrt(252); this file
     builds the daily series the correct way so the two can be compared.

Usage:  python3 edge/tools/xs_baseline.py
"""
from __future__ import annotations

import glob
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from edge.research.portfolio import simulate_long_short  # noqa: E402

DATA = ROOT / "edge" / "data" / "1d_wide"
HOLDOUT_START = pd.Timestamp("2024-08-01")

HOLD = 5           # bars held
COST_BPS = 20      # round-trip, charged on each tranche's entry day
DECILE = 0.10
MIN_NAMES = 50     # skip dates with a thin cross-section
MAX_ABS_DAILY_RET = 0.50   # above this a 1-day open-to-open move is bad data


def load_panel(min_rows: int = 400) -> pd.DataFrame:
    frames = []
    for f in sorted(glob.glob(str(DATA / "*.parquet"))):
        df = pd.read_parquet(f, columns=["open", "close"])
        if len(df) < min_rows:
            continue
        df = df.reset_index().rename(columns={"Date": "date"})
        df["symbol"] = Path(f).stem
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    return panel.sort_values(["symbol", "date"]).reset_index(drop=True)


def add_signals(panel: pd.DataFrame) -> pd.DataFrame:
    g = panel.groupby("symbol", sort=False)["close"]
    # All strictly backward-looking as of the close of bar t.
    panel["mom12_1"] = g.shift(21) / g.shift(126) - 1
    panel["mom21"] = g.pct_change(21)
    panel["rev5"] = -g.pct_change(5)          # sign flipped: reversal
    # Open-to-open 1-day forward return, used only for P&L (never as a feature).
    panel["r_next"] = (
        panel.groupby("symbol", sort=False)["open"].shift(-1) / panel["open"] - 1
    )
    # Data hygiene: 1d_wide contains unadjusted split prints — the worst is a
    # single +22,525% bar. At ~1.8% position weight that one row alone produces
    # an 81% daily portfolio "return", which is what blew up vol and drawdown.
    # 16 rows out of 1.37M exceed +/-50%; treat them as bad data, not returns.
    bad = panel["r_next"].abs() > MAX_ABS_DAILY_RET
    if bad.any():
        print(f"  [hygiene] dropping {int(bad.sum())} bar(s) with |1d return| > "
              f"{MAX_ABS_DAILY_RET:.0%} (suspected unadjusted splits)")
        panel.loc[bad, "r_next"] = np.nan
    return panel


def backtest(panel: pd.DataFrame, signal: str,
             hold: int = HOLD, cost_bps: float = COST_BPS,
             decile: float = DECILE) -> pd.DataFrame:
    """Daily mark-to-market of `hold` overlapping dollar-neutral decile tranches.

    This function's own job is deciding the weight: cross-sectional decile
    rank each date, spread 1/HOLD of capital across HOLD overlapping
    tranches. That part is this file's own portfolio-construction logic and
    stays here. Earning the weight against a price, charging turnover cost,
    and computing the risk stats is delegated to
    `edge.research.portfolio.simulate_long_short` instead of the hand-rolled
    per-tranche loop this used to be -- see that module's docstring for why
    a weight formed at bar i must never earn bar i's own return.

    One convention translation is needed: `r_next.loc[d] = open[d+1]/open[d]-1`
    is stored at the FORMATION row d, but `simulate_long_short` earns
    `close.pct_change().iloc[d]` (backward-looking) against a weight shifted
    forward by `execution_lag`. Feeding it `close := open.shift(-1)` makes
    `close.pct_change().iloc[d] == open[d+1]/open[d]-1 == r_next.loc[d]`
    exactly, so `execution_lag=1` reproduces "formed at close of d, first
    live at d+1" without changing the actual return values used.
    """
    HOLD, COST_BPS, DECILE = hold, cost_bps, decile
    df = panel.dropna(subset=[signal, "r_next"]).copy()
    counts = df.groupby("date")["symbol"].transform("size")
    df = df[counts >= MIN_NAMES]

    # Cross-sectional rank of the signal on each formation date.
    df["pct"] = df.groupby("date")[signal].rank(pct=True)
    df["w"] = 0.0
    df.loc[df["pct"] >= 1 - DECILE, "w"] = 1.0
    df.loc[df["pct"] <= DECILE, "w"] = -1.0
    # Normalise each leg to +1 / -1 so the book is dollar-neutral.
    for side, sgn in ((df["w"] > 0, 1.0), (df["w"] < 0, -1.0)):
        n = df.loc[side].groupby(df.loc[side, "date"])["w"].transform("size")
        df.loc[side, "w"] = sgn / n

    all_dates = np.sort(panel["date"].unique())
    all_symbols = np.sort(panel["symbol"].unique())

    # Raw per-date formation weight, wide (date x symbol). Spreading it over
    # HOLD overlapping tranches is a rolling sum of the trailing HOLD raw
    # formations divided by the FIXED HOLD (not the count actually active) --
    # this reproduces the original's ramp-up behaviour, where the first
    # HOLD-1 days are under-invested rather than over-weighted.
    w_raw = (
        df.pivot(index="date", columns="symbol", values="w")
        .reindex(index=all_dates, columns=all_symbols)
        .fillna(0.0)
    )
    w_eff = w_raw.rolling(HOLD, min_periods=1).sum() / HOLD
    long_w = w_eff.clip(lower=0.0)
    short_w = (-w_eff).clip(lower=0.0)

    open_wide = (
        panel.pivot(index="date", columns="symbol", values="open")
        .reindex(index=all_dates, columns=all_symbols)
    )
    close_for_sim = open_wide.shift(-1)  # see docstring: makes pct_change == r_next

    sim = simulate_long_short(
        long_weights=long_w,
        short_weights=short_w,
        close=close_for_sim,
        execution_lag=1,
        # COST_BPS is round-trip (entry+exit); simulate_long_short charges
        # cost_per_side per bar of |weight change|, so halve it here.
        cost_per_side=(COST_BPS / 1e4) / 2.0,
        max_abs_daily_return=MAX_ABS_DAILY_RET,
    )
    out = pd.DataFrame({"gross": sim.gross_returns, "net": sim.net_returns})
    out["cost"] = out["gross"] - out["net"]
    return out.sort_index()


def stats(daily: pd.Series, label: str) -> dict:
    if len(daily) < 20:
        return {"period": label, "n_days": len(daily)}
    ann = daily.mean() * 252
    sd = daily.std(ddof=1) * np.sqrt(252)
    curve = (1 + daily).cumprod()
    dd = (curve / curve.cummax() - 1).min()
    return {
        "period": label,
        "n_days": int(len(daily)),
        "ann_return": round(float(ann), 4),
        "ann_vol": round(float(sd), 4),
        "sharpe": round(float(ann / sd), 3) if sd > 0 else 0.0,
        "max_dd": round(float(dd), 4),
        "hit_rate": round(float((daily > 0).mean()), 4),
    }


def rank_ic(panel: pd.DataFrame, signal: str) -> dict:
    """Spearman IC of signal vs the realised HOLD-day forward return."""
    df = panel.dropna(subset=[signal]).copy()
    o = df.groupby("symbol", sort=False)["open"]
    df["fwd"] = o.shift(-(HOLD + 1)) / o.shift(-1) - 1
    df = df.dropna(subset=["fwd"])
    ics = df.groupby("date").apply(
        lambda g: g[signal].corr(g["fwd"], method="spearman") if len(g) >= MIN_NAMES else np.nan,
        include_groups=False,
    ).dropna()
    if len(ics) < 20:
        return {}
    t = ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics)))
    return {
        "mean_ic": round(float(ics.mean()), 5),
        "ic_t": round(float(t), 2),
        "n_dates": int(len(ics)),
    }


def main() -> None:
    print("Loading panel ...")
    panel = add_signals(load_panel())
    print(f"  {panel['symbol'].nunique()} symbols | "
          f"{panel['date'].min().date()} -> {panel['date'].max().date()} | "
          f"{len(panel):,} rows\n")

    for sig in ("mom12_1", "mom21", "rev5"):
        daily = backtest(panel, sig)
        dev = daily[daily.index < HOLDOUT_START]
        hold = daily[daily.index >= HOLDOUT_START]
        ic_dev = rank_ic(panel[panel["date"] < HOLDOUT_START], sig)
        print(f"=== {sig} ===")
        print(f"  IC(dev): {ic_dev}")
        for lbl, s in (("dev", dev), ("holdout", hold)):
            print(f"  net    {stats(s['net'], lbl)}")
            print(f"  gross  {stats(s['gross'], lbl)}")
        print()


if __name__ == "__main__":
    main()
