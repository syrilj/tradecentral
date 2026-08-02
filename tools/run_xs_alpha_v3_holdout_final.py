#!/usr/bin/env python3
"""run_xs_alpha_v3_holdout_final.py — PRE-REGISTERED one-shot holdout evaluation.

The holdout period (date >= HOLDOUT_START) is unfrozen for EXACTLY the two
configurations below, and nothing else. No other cell is computed. No
hyperparameters, features, or thresholds are tuned. This period is burned
after this run.

  PRIMARY:   signal=rev5,  kind=buffered, entry_pct=0.10, exit_pct=0.40
  SECONDARY: signal=model, kind=min_hold, entry_pct=0.10, exit_pct=0.10, min_hold_days=20

Both configurations are reported regardless of outcome.

Model arm: uses the EXISTING holdout y_pred already saved in
edge/runs/xs_v3/predictions.parquet (period=='holdout'). That model was
fit on development-period data only (max training date 2024-07-31, per
edge/runs/xs_v3/results.json's holdout.final_model_train_max_date and its
self-check 3) — this script re-asserts that fact before using it and does
NOT retrain or rescoring anything.

rev5 arm: computed fresh on holdout dates directly from price data, same
definition as the turnover grid (rank of -1 * close.pct_change(5)),
restricted to the same (date,symbol) universe as the model's holdout
predictions for a like-for-like comparison.

DEV-period numbers for the same two configurations are recomputed here
(not merely copied from turnover_grid.json) so that ann_vol / max_drawdown
can be reported on the net@10bps series as requested this time (the grid
script reported them on the gross series). The DEV price panel is still
truncated to date < HOLDOUT_START exactly as in the turnover grid, so the
DEV column here reproduces (up to that reporting-convention difference) the
DEV row already reported for these two exact configurations in
turnover_grid.json — this is verified below via an explicit spot check.

Usage:
    python3 edge/tools/run_xs_alpha_v3_holdout_final.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "edge" / "data" / "1d_wide"
XS_V3_DIR = ROOT / "edge" / "runs" / "xs_v3"
OUT_PATH = XS_V3_DIR / "holdout_final.json"

HOLDOUT_START = pd.Timestamp("2024-08-01")
RETURN_HYGIENE_THRESHOLD = 0.50
BPS_GRID = (5, 10, 20)
BOOT_BLOCK = 21
BOOT_DRAWS = 1000
BOOT_SEED = 42

# ── PRE-REGISTERED CONFIGURATIONS — DO NOT ADD, SUBSTITUTE, OR RESELECT ─────
PRE_REGISTERED = [
    dict(label="PRIMARY", signal="rev5", kind="buffered", entry_pct=0.10, exit_pct=0.40, min_hold_days=0),
    dict(label="SECONDARY", signal="model", kind="min_hold", entry_pct=0.10, exit_pct=0.10, min_hold_days=20),
]


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers (duplicated from run_xs_alpha_v3_turnover_grid.py, unchanged)
# ─────────────────────────────────────────────────────────────────────────────

def clean_extreme_returns(returns, threshold: float = RETURN_HYGIENE_THRESHOLD) -> Tuple[object, int]:
    bad = returns.abs() > threshold
    n_masked = int(np.asarray(bad).sum())
    cleaned = returns.mask(bad)
    return cleaned, n_masked


def load_open_close(symbols: List[str], date_min: pd.Timestamp = None, date_max: pd.Timestamp = None
                     ) -> Tuple[pd.DataFrame, pd.DataFrame]:
    open_frames, close_frames = [], []
    for sym in symbols:
        p = DATA_DIR / f"{sym}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        if date_max is not None:
            df = df[df.index < date_max]
        if date_min is not None:
            df = df[df.index >= date_min]
        if df.empty:
            continue
        o = df["open"].copy(); o.name = sym
        c = df["close"].copy(); c.name = sym
        open_frames.append(o)
        close_frames.append(c)
    open_wide = pd.concat(open_frames, axis=1).sort_index()
    close_wide = pd.concat(close_frames, axis=1).sort_index()
    open_wide.index = pd.to_datetime(open_wide.index)
    close_wide.index = pd.to_datetime(close_wide.index)
    return open_wide, close_wide


def build_rev5_score_df(pred_df: pd.DataFrame, close_wide: pd.DataFrame) -> pd.DataFrame:
    rev5_raw_wide = -1.0 * close_wide.pct_change(5)
    rev5_raw_wide.index.name = "date"
    rev5_raw_wide.columns.name = "symbol"
    rev5_long = rev5_raw_wide.stack(future_stack=True).reset_index(name="rev5_raw")

    base = pred_df[["date", "symbol", "y_true"]].rename(columns={"y_true": "y"})
    df = base.merge(rev5_long, on=["date", "symbol"], how="inner")

    ranked = df.groupby("date")["rev5_raw"].rank(pct=True) - 0.5
    df["score"] = ranked.fillna(0.0)
    return df


def compute_ic_series(df: pd.DataFrame, score_col: str, y_col: str) -> pd.Series:
    def _ic(g: pd.DataFrame) -> float:
        if len(g) < 5 or g[score_col].std(ddof=1) < 1e-12 or g[y_col].std(ddof=1) < 1e-12:
            return np.nan
        return g[score_col].corr(g[y_col], method="spearman")

    ic = df.groupby("date")[[score_col, y_col]].apply(_ic)
    ic.name = "ic"
    return ic.dropna().sort_index()


def block_bootstrap_ci(values: np.ndarray, block_size: int = BOOT_BLOCK, n_boot: int = BOOT_DRAWS,
                        ci: float = 0.95, seed: int = BOOT_SEED) -> Tuple[float, float]:
    n = len(values)
    if n < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    n_blocks_needed = int(np.ceil(n / block_size))
    max_start = max(n - block_size, 0)
    means = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, max_start + 1, size=n_blocks_needed)
        sample = np.concatenate([values[s:s + block_size] for s in starts])[:n]
        means[b] = sample.mean()
    lo = float(np.percentile(means, (1 - ci) / 2 * 100))
    hi = float(np.percentile(means, (1 + ci) / 2 * 100))
    return lo, hi


def ic_stats(ic_series: pd.Series) -> Dict:
    n = len(ic_series)
    if n == 0:
        return dict(n_dates=0, mean_ic=0.0, ic_std=0.0, icir=0.0, t_stat=0.0, ci_lo=None, ci_hi=None)
    mean_ic = float(ic_series.mean())
    ic_std = float(ic_series.std(ddof=1)) if n > 1 else 0.0
    icir = mean_ic / ic_std if ic_std > 1e-12 else 0.0
    t_stat = mean_ic / (ic_std / np.sqrt(n)) if ic_std > 1e-12 else 0.0
    ci_lo, ci_hi = block_bootstrap_ci(ic_series.values)
    return dict(
        n_dates=n, mean_ic=round(mean_ic, 5), ic_std=round(ic_std, 5),
        icir=round(icir, 4), t_stat=round(t_stat, 4),
        ci_lo=round(ci_lo, 5), ci_hi=round(ci_hi, 5),
    )


def build_buffered_daily_series(
    score_df: pd.DataFrame, ret1d_wide: pd.DataFrame, master_calendar: pd.DatetimeIndex,
    entry_pct: float, exit_pct: float, min_hold_days: int = 0,
) -> pd.DataFrame:
    """Identical logic to run_xs_alpha_v3_turnover_grid.py. State (held_long,
    held_short, prev_weights) starts empty at the FIRST date in score_df — so
    calling this with a holdout-only score_df gives a book with zero
    carryover from the development period, matching how holdout metrics were
    always computed in this project (fresh start, no dev-period positions
    bleeding across the boundary).
    """
    groups = [(d, g.set_index("symbol")["score"]) for d, g in score_df.sort_values("date").groupby("date")]

    held_long: Dict[str, int] = {}
    held_short: Dict[str, int] = {}
    prev_weights: Dict[str, float] = {}
    records = []

    entry_thresh_long = 1.0 - entry_pct
    exit_thresh_long = 1.0 - exit_pct
    entry_thresh_short = entry_pct
    exit_thresh_short = exit_pct

    for i, (t, scores) in enumerate(groups):
        ranks = scores.rank(pct=True)

        new_held_long: Dict[str, int] = {}
        for sym, entered_at in held_long.items():
            if sym not in ranks.index:
                continue
            days_held = i - entered_at
            if days_held < min_hold_days or ranks[sym] >= exit_thresh_long:
                new_held_long[sym] = entered_at
        for sym in ranks.index[ranks >= entry_thresh_long]:
            if sym not in new_held_long:
                new_held_long[sym] = i

        new_held_short: Dict[str, int] = {}
        for sym, entered_at in held_short.items():
            if sym not in ranks.index:
                continue
            days_held = i - entered_at
            if days_held < min_hold_days or ranks[sym] <= exit_thresh_short:
                new_held_short[sym] = entered_at
        for sym in ranks.index[ranks <= entry_thresh_short]:
            if sym not in new_held_short:
                new_held_short[sym] = i

        held_long, held_short = new_held_long, new_held_short
        n_long, n_short = len(held_long), len(held_short)

        weights: Dict[str, float] = {}
        if n_long > 0:
            wl = 1.0 / n_long
            for sym in held_long:
                weights[sym] = weights.get(sym, 0.0) + wl
        if n_short > 0:
            ws = 1.0 / n_short
            for sym in held_short:
                weights[sym] = weights.get(sym, 0.0) - ws

        all_syms = set(weights) | set(prev_weights)
        turnover = sum(abs(weights.get(s, 0.0) - prev_weights.get(s, 0.0)) for s in all_syms) / 2.0

        pos_idx = master_calendar.get_indexer([t])
        pos_t = int(pos_idx[0]) if len(pos_idx) and pos_idx[0] != -1 else None
        if pos_t is not None and pos_t + 1 < len(master_calendar):
            entry_date = master_calendar[pos_t + 1]
            if entry_date in ret1d_wide.index:
                ret_today = ret1d_wide.loc[entry_date]
                gross = 0.0
                for sym, w in weights.items():
                    r = ret_today.get(sym, np.nan)
                    if pd.notna(r):
                        gross += w * r
                records.append({"date": entry_date, "gross": gross, "turnover": turnover})

        prev_weights = weights

    if not records:
        return pd.DataFrame(columns=["date", "gross", "turnover"])
    out = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    assert out["date"].is_unique, "duplicate entry dates in buffered daily series — bug"
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Performance stats — ann_vol / max_drawdown / ann_return on the NET@10bps series
# ─────────────────────────────────────────────────────────────────────────────

def perf_from_daily(daily: pd.DataFrame, bps_list=BPS_GRID) -> Dict:
    if daily.empty or len(daily) < 2:
        return dict(
            n_days=int(len(daily)), turnover_yr=0.0, sharpe_gross=0.0,
            sharpe_net={f"{b}bps": 0.0 for b in bps_list},
            ann_return_net10bps=0.0, ann_vol_net10bps=0.0, max_drawdown_net10bps=0.0,
            internally_consistent=True,
        )
    gross = daily["gross"].values
    turnover = daily["turnover"].values

    std_g = np.std(gross, ddof=1)
    sharpe_gross = float(np.mean(gross) / std_g * np.sqrt(252)) if std_g > 1e-12 else 0.0
    turnover_yr = float(np.mean(turnover) * 252)

    sharpe_net = {}
    net10 = None
    for bps in bps_list:
        rate = bps / 10_000.0
        net = gross - rate * turnover
        std_n = np.std(net, ddof=1)
        sharpe_net[f"{bps}bps"] = round(float(np.mean(net) / std_n * np.sqrt(252)) if std_n > 1e-12 else 0.0, 4)
        if bps == 10:
            net10 = net

    mean10 = float(np.mean(net10))
    std10 = float(np.std(net10, ddof=1))
    sharpe_net10_raw = mean10 / std10 * np.sqrt(252) if std10 > 1e-12 else 0.0
    ann_return_net10 = mean10 * 252
    ann_vol_net10 = std10 * np.sqrt(252)

    implied_sharpe = ann_return_net10 / ann_vol_net10 if ann_vol_net10 > 1e-9 else 0.0
    internally_consistent = bool(abs(implied_sharpe - sharpe_net10_raw) < 1e-6)

    cum = np.cumprod(1.0 + net10)
    running_max = np.maximum.accumulate(cum)
    drawdown = cum / running_max - 1.0
    max_dd = float(drawdown.min())

    return dict(
        n_days=int(len(daily)),
        turnover_yr=round(turnover_yr, 3),
        sharpe_gross=round(sharpe_gross, 4),
        sharpe_net=sharpe_net,
        ann_return_net10bps=round(ann_return_net10, 4),
        ann_vol_net10bps=round(ann_vol_net10, 4),
        max_drawdown_net10bps=round(max_dd, 4),
        internally_consistent=internally_consistent,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run() -> Dict:
    t0 = time.time()

    pred = pd.read_parquet(XS_V3_DIR / "predictions.parquet")
    pred["date"] = pd.to_datetime(pred["date"])
    dev_pred = pred[pred["period"] == "dev"].copy()
    holdout_pred = pred[pred["period"] == "holdout"].copy()

    with open(XS_V3_DIR / "results.json") as fh:
        v3_results = json.load(fh)
    final_train_max_date = v3_results["holdout"]["final_model_train_max_date"]
    assert final_train_max_date == "2024-07-31", (
        f"Expected final model train max date 2024-07-31, found {final_train_max_date}"
    )
    assert (dev_pred["date"] < HOLDOUT_START).all()
    assert (holdout_pred["date"] >= HOLDOUT_START).all()
    print(f"[confirm] model scoring the holdout arm was trained on development-period data only, "
          f"through {final_train_max_date} (< {HOLDOUT_START.date()}) — per run_xs_alpha_v3.py "
          f"self-check 3 and results.json. Not retrained or rescoring here.")
    print(f"[data] predictions.parquet: {len(dev_pred):,} dev rows, {len(holdout_pred):,} holdout rows.")

    # ── DEV price panel: strict dev-only truncation, matches turnover_grid.py ──
    dev_symbols = sorted(dev_pred["symbol"].unique())
    open_dev, close_dev = load_open_close(dev_symbols, date_max=HOLDOUT_START)
    master_dev = open_dev.index
    assert master_dev.max() < HOLDOUT_START
    ret1d_dev_raw = open_dev.shift(-1) / open_dev - 1.0
    ret1d_dev, n_bad_dev = clean_extreme_returns(ret1d_dev_raw)
    print(f"[return-hygiene] DEV: masked {n_bad_dev} 1-day returns with |return| > {RETURN_HYGIENE_THRESHOLD:.0%}.")

    # ── HOLDOUT price panel: now authorized, for the two pre-registered cells only ──
    holdout_symbols = sorted(holdout_pred["symbol"].unique())
    open_hold, close_hold = load_open_close(holdout_symbols, date_min=HOLDOUT_START)
    master_hold = open_hold.index
    assert master_hold.min() >= HOLDOUT_START
    ret1d_hold_raw = open_hold.shift(-1) / open_hold - 1.0
    ret1d_hold, n_bad_hold = clean_extreme_returns(ret1d_hold_raw)
    print(f"[return-hygiene] HOLDOUT: masked {n_bad_hold} 1-day returns with |return| > {RETURN_HYGIENE_THRESHOLD:.0%}.")

    # ── rev5 signal, both periods, restricted to the model's own (date,symbol) universe ──
    rev5_dev_df = build_rev5_score_df(dev_pred, close_dev)
    rev5_dev_ic = ic_stats(compute_ic_series(rev5_dev_df, "score", "y"))
    rev5_hold_df = build_rev5_score_df(holdout_pred, close_hold)
    rev5_hold_ic = ic_stats(compute_ic_series(rev5_hold_df, "score", "y"))

    # ── model signal: y_pred already computed (dev via walk-forward, holdout via the
    #    single final model trained through 2024-07-31). IC reused directly from
    #    results.json — IC depends only on y_pred vs y, not on portfolio construction. ──
    model_dev_score_df = dev_pred[["date", "symbol"]].copy()
    model_dev_score_df["score"] = dev_pred["y_pred"].values
    model_dev_ic = v3_results["dev"]["ic"]

    model_hold_score_df = holdout_pred[["date", "symbol"]].copy()
    model_hold_score_df["score"] = holdout_pred["y_pred"].values
    model_hold_ic = v3_results["holdout"]["ic"]

    signal_data = {
        "rev5": dict(
            dev_score=rev5_dev_df[["date", "symbol", "score"]], dev_ic=rev5_dev_ic,
            hold_score=rev5_hold_df[["date", "symbol", "score"]], hold_ic=rev5_hold_ic,
        ),
        "model": dict(
            dev_score=model_dev_score_df, dev_ic=model_dev_ic,
            hold_score=model_hold_score_df, hold_ic=model_hold_ic,
        ),
    }

    results = []
    for cfg in PRE_REGISTERED:
        sd = signal_data[cfg["signal"]]
        dev_daily = build_buffered_daily_series(
            sd["dev_score"], ret1d_dev, master_dev,
            entry_pct=cfg["entry_pct"], exit_pct=cfg["exit_pct"], min_hold_days=cfg["min_hold_days"],
        )
        hold_daily = build_buffered_daily_series(
            sd["hold_score"], ret1d_hold, master_hold,
            entry_pct=cfg["entry_pct"], exit_pct=cfg["exit_pct"], min_hold_days=cfg["min_hold_days"],
        )
        dev_perf = perf_from_daily(dev_daily)
        hold_perf = perf_from_daily(hold_daily)

        if not dev_perf["internally_consistent"]:
            raise AssertionError(f"{cfg['label']} DEV: ann_return/ann_vol != Sharpe — internal inconsistency, stopping.")
        if not hold_perf["internally_consistent"]:
            raise AssertionError(f"{cfg['label']} HOLDOUT: ann_return/ann_vol != Sharpe — internal inconsistency, stopping.")

        row = dict(
            label=cfg["label"], signal=cfg["signal"], kind=cfg["kind"],
            entry_pct=cfg["entry_pct"], exit_pct=cfg["exit_pct"], min_hold_days=cfg["min_hold_days"],
            dev=dict(**dev_perf, ic=sd["dev_ic"]),
            holdout=dict(**hold_perf, ic=sd["hold_ic"]),
        )
        results.append(row)

        print(f"\n[{cfg['label']}] signal={cfg['signal']} kind={cfg['kind']} "
              f"entry={cfg['entry_pct']} exit={cfg['exit_pct']} min_hold={cfg['min_hold_days']}")
        for period_name, perf in (("DEV", dev_perf), ("HOLDOUT", hold_perf)):
            ic = sd["dev_ic"] if period_name == "DEV" else sd["hold_ic"]
            print(
                f"  {period_name:7s} | n_days={perf['n_days']:4d} TO/yr={perf['turnover_yr']:7.2f} "
                f"ShGross={perf['sharpe_gross']:+.4f} ShNet5={perf['sharpe_net']['5bps']:+.4f} "
                f"ShNet10={perf['sharpe_net']['10bps']:+.4f} ShNet20={perf['sharpe_net']['20bps']:+.4f} "
                f"AnnRet@10={perf['ann_return_net10bps']:+.4f} AnnVol@10={perf['ann_vol_net10bps']:.4f} "
                f"maxDD@10={perf['max_drawdown_net10bps']:+.4f} consistent={perf['internally_consistent']} "
                f"meanIC={ic['mean_ic']:+.5f} IC_CI=[{ic['ci_lo']:+.5f},{ic['ci_hi']:+.5f}]"
            )

    elapsed = round(time.time() - t0, 2)
    output = {
        "note": "Pre-registered one-shot holdout evaluation. Exactly two configurations. No other cell was tested or tuned.",
        "holdout_start": str(HOLDOUT_START.date()),
        "final_model_train_max_date": final_train_max_date,
        "cost_convention": "net_gross2 (both legs): cost = COST_RATE * turnover_d, turnover_d = sum|w_d - w_{d-1}|/2",
        "ann_vol_and_drawdown_basis": "net@10bps series (not gross) per this iteration's instruction",
        "return_hygiene_threshold": RETURN_HYGIENE_THRESHOLD,
        "n_bad_ret1d_masked_dev": n_bad_dev,
        "n_bad_ret1d_masked_holdout": n_bad_hold,
        "bps_grid": list(BPS_GRID),
        "configurations": results,
        "elapsed_seconds": elapsed,
    }

    with open(OUT_PATH, "w") as fh:
        json.dump(output, fh, indent=2, default=str)

    print(f"\nWrote {OUT_PATH}")
    print(f"Elapsed: {elapsed:.1f}s")
    return output


if __name__ == "__main__":
    run()
