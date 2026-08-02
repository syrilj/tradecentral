#!/usr/bin/env python3
"""run_xs_alpha_v3_turnover_grid.py — Buffered (hysteresis) portfolio construction,
turnover-reduction grid. DEVELOPMENT PERIOD ONLY.

=== HARD RULE: THE HOLDOUT IS FROZEN ===
This script never loads, scores, evaluates, prints, or computes any metric for
any date >= HOLDOUT_START (2024-08-01). Every parquet file is truncated to
`date < HOLDOUT_START` IMMEDIATELY after being read, before any other line of
code touches it. The variable `holdout` does not exist anywhere in this file.
Two runtime self-checks assert this before any output is produced.

Standalone script. Does NOT import from run_walkforward_backtest.py or from
run_xs_alpha_v3.py. It reuses ALREADY-COMPUTED, holdout-safe artifacts from
the prior v3 run instead of recomputing them:
  - edge/runs/xs_v3/predictions.parquet, filtered to period=='dev', supplies
    the out-of-sample model predictions (y_pred) for the entire development
    walk-forward — these were produced with the same fixed XGBoost
    hyperparameters and feature set as before; NOTHING about the model is
    re-tuned or re-derived here. IC for the model signal is likewise pulled
    directly from edge/runs/xs_v3/results.json's dev.ic block (IC depends
    only on y_pred vs y, not on portfolio construction, so recomputing it
    would just reproduce the same number).
  - Raw open/close prices are reloaded (truncated to dev) only to (a) build
    the 1-day open-to-open return matrix for portfolio marking and (b) build
    the plain rev5 reversal baseline signal.

=== WHAT'S NEW: buffered (hysteresis) portfolio construction ===
Replaces the fixed-5-day-tranche scheme with a single persistent long book
and a single persistent short book:
  - A name ENTERS the long book when its cross-sectional score rank is in
    the top `entry_pct`. Once held, it STAYS until its rank falls below the
    top `exit_pct` (exit_pct >= entry_pct -> wider band -> lower turnover).
    Symmetric for the short book at the bottom.
  - Weights are equal-weight within each leg, dollar-neutral (long sums to
    +1, short sums to -1), rebalanced daily.
  - Turnover on day d = sum|w_d - w_{d-1}| / 2. Cost = COST_RATE * turnover_d
    (both legs charged — the conservative net_gross2 convention from the
    prior iteration).
  - Timing: a rebalance decided using the cross-sectional rank of the score
    as of the close of signal date t is deployed at OPEN of t+1 (same
    ENTRY_LAG=1 used everywhere else in this project) and earns the
    open-to-open return from t+1 to t+2, i.e. ret1d_wide.loc[t+1]. Turnover
    from the t -> t+1 rebalance decision is charged on that same portfolio
    day (t+1). This keeps the buffered scheme on the identical timing
    convention as the tranche control, so exit_pct=entry_pct is a fair
    "roughly reproduces current behaviour" comparison.
  - Mark-to-market returns use the same open.shift(-1)/open - 1 series, with
    the same |return| > 50% unadjusted-split/bad-print hygiene mask as
    before.

A `min_hold_days` variant keeps entry_pct=exit_pct=0.10 (i.e. no rank-band
buffer) but locks a newly-entered name from being removed for N days
regardless of its current rank.

The old tranche machinery is kept (duplicated, not imported) as the
"tranche_control" row in the grid, computed via the identical formulas used
in run_xs_alpha_v3.py's dev portfolio (net_gross2 turnover convention).

Usage:
    python3 edge/tools/run_xs_alpha_v3_turnover_grid.py
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
OUT_PATH = XS_V3_DIR / "turnover_grid.json"

# ── Frozen split boundary — HARD RULE for this script ───────────────────────
HOLDOUT_START = pd.Timestamp("2024-08-01")

# ── Timing (matches run_xs_alpha_v3.py, unchanged) ───────────────────────────
HOLD_DAYS = 5             # tranche control only
ENTRY_LAG = 1

# ── Return hygiene (identical threshold to the prior iteration) ─────────────
RETURN_HYGIENE_THRESHOLD = 0.50

# ── Cost / bootstrap constants (unchanged from run_xs_alpha_v3.py) ──────────
BPS_GRID = (5, 10, 20)
DECILE_FRAC = 0.10   # tranche-control entry/exit (top/bottom decile, no buffer)
BOOT_BLOCK = 21
BOOT_DRAWS = 1000
BOOT_SEED = 42


# ─────────────────────────────────────────────────────────────────────────────
# Return hygiene (identical to run_xs_alpha_v3.py)
# ─────────────────────────────────────────────────────────────────────────────

def clean_extreme_returns(returns, threshold: float = RETURN_HYGIENE_THRESHOLD) -> Tuple[object, int]:
    bad = returns.abs() > threshold
    n_masked = int(np.asarray(bad).sum())
    cleaned = returns.mask(bad)
    return cleaned, n_masked


# ─────────────────────────────────────────────────────────────────────────────
# Load holdout-safe artifacts from the prior v3 run (dev rows only)
# ─────────────────────────────────────────────────────────────────────────────

def load_dev_predictions() -> pd.DataFrame:
    pred = pd.read_parquet(XS_V3_DIR / "predictions.parquet")
    dev = pred[pred["period"] == "dev"].copy()
    dev["date"] = pd.to_datetime(dev["date"])
    # HARD-RULE self-check: this file must contain no holdout rows once filtered.
    assert (dev["date"] < HOLDOUT_START).all(), "dev predictions contain a date >= HOLDOUT_START — aborting."
    print(f"[holdout-freeze self-check 1] PASS: loaded {len(dev):,} dev-period prediction rows, "
          f"max date {dev['date'].max().date()} < {HOLDOUT_START.date()}. No holdout rows present.")
    return dev


def load_dev_ic_from_v3_results() -> Dict:
    with open(XS_V3_DIR / "results.json") as fh:
        results = json.load(fh)
    return results["dev"]["ic"]


def load_open_close(symbols: List[str], truncate_before: pd.Timestamp) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load open & close for the given symbols, truncated to date < truncate_before
    IMMEDIATELY upon read. No row with date >= truncate_before is ever kept
    in memory beyond the two lines that read and slice each file.
    """
    open_frames, close_frames = [], []
    for sym in symbols:
        p = DATA_DIR / f"{sym}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        df = df[df.index < truncate_before]   # HARD RULE enforced here, before anything else touches df
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


# ─────────────────────────────────────────────────────────────────────────────
# rev5 baseline signal: rank of -1 * close.pct_change(5)
# ─────────────────────────────────────────────────────────────────────────────

def build_rev5_score_df(dev_predictions: pd.DataFrame, close_wide: pd.DataFrame) -> pd.DataFrame:
    rev5_raw_wide = -1.0 * close_wide.pct_change(5)   # per-symbol, trailing only
    rev5_raw_wide.index.name = "date"
    rev5_raw_wide.columns.name = "symbol"
    rev5_long = rev5_raw_wide.stack(dropna=False).reset_index(name="rev5_raw")

    # Restrict to the EXACT (date, symbol) universe of the model's dev
    # predictions, so model vs. rev5 are compared on an identical sample —
    # required for "does buffering help the model specifically, or any
    # signal generically" to be a fair question.
    base = dev_predictions[["date", "symbol", "y_true"]].rename(columns={"y_true": "y"})
    df = base.merge(rev5_long, on=["date", "symbol"], how="inner")

    ranked = df.groupby("date")["rev5_raw"].rank(pct=True) - 0.5
    df["score"] = ranked.fillna(0.0)
    n_missing = int(df["rev5_raw"].isna().sum())
    print(f"[rev5] built reversal score for {len(df):,} (date,symbol) rows "
          f"(matches model's dev universe exactly); {n_missing} had undefined "
          f"5-day pct_change (filled to neutral rank 0.0).")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# IC statistics (identical formulas to run_xs_alpha_v3.py)
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Tranche control (duplicated from run_xs_alpha_v3.py, gross2 turnover convention)
# ─────────────────────────────────────────────────────────────────────────────

def build_tranche_daily_series(
    score_df: pd.DataFrame, ret1d_wide: pd.DataFrame, master_calendar: pd.DatetimeIndex,
    hold_days: int = HOLD_DAYS, decile_frac: float = DECILE_FRAC,
) -> pd.DataFrame:
    weights_by_date: Dict[pd.Timestamp, pd.Series] = {}
    for date, g in score_df.groupby("date"):
        ranks = g.set_index("symbol")["score"].rank(pct=True)
        long_mask = ranks >= (1.0 - decile_frac)
        short_mask = ranks <= decile_frac
        n_long, n_short = int(long_mask.sum()), int(short_mask.sum())
        if n_long == 0 or n_short == 0:
            continue
        w = pd.Series(0.0, index=ranks.index)
        w[long_mask] = 1.0 / n_long
        w[short_mask] = -1.0 / n_short
        weights_by_date[pd.Timestamp(date)] = w[w != 0]

    if not weights_by_date:
        return pd.DataFrame(columns=["date", "gross", "turnover"])

    signal_dates = sorted(weights_by_date.keys())
    symbols = ret1d_wide.columns
    records = []
    for d, w in weights_by_date.items():
        for sym, val in w.items():
            records.append((d, sym, val))
    wdf = pd.DataFrame.from_records(records, columns=["date", "symbol", "weight"])
    Wfull = (
        wdf.pivot_table(index="date", columns="symbol", values="weight", aggfunc="sum")
        .reindex(index=master_calendar, columns=symbols)
        .fillna(0.0)
    )

    has_signal = pd.Series(0.0, index=master_calendar)
    has_signal.loc[has_signal.index.isin(signal_dates)] = 1.0

    gross_exposure_signal = pd.Series(0.0, index=master_calendar)
    for d, w in weights_by_date.items():
        gross_exposure_signal.loc[d] = float(w.abs().sum())

    roll_w = Wfull.rolling(window=hold_days, min_periods=1).sum().shift(1).fillna(0.0)
    n_active = has_signal.rolling(window=hold_days, min_periods=1).sum().shift(1).fillna(0.0)

    ret_aligned = ret1d_wide.reindex(index=master_calendar, columns=symbols).fillna(0.0)
    tranche_sum_return = (roll_w * ret_aligned).sum(axis=1)
    gross = (tranche_sum_return / n_active.replace(0.0, np.nan)).fillna(0.0)

    has_entry = has_signal.shift(1).fillna(0.0)
    gross_exposure_entry = gross_exposure_signal.shift(1).fillna(0.0)
    turnover = (has_entry * gross_exposure_entry) / hold_days   # gross2 (both legs) convention

    first_signal_pos = master_calendar.get_indexer([signal_dates[0]])[0]
    last_signal_pos = master_calendar.get_indexer([signal_dates[-1]])[0]
    start_pos = min(first_signal_pos + 1, len(master_calendar) - 1)
    end_pos = min(last_signal_pos + hold_days, len(master_calendar) - 1)
    idx = master_calendar[start_pos:end_pos + 1]

    out = pd.DataFrame(
        {"date": idx, "gross": gross.loc[idx].values, "turnover": turnover.loc[idx].values}
    ).reset_index(drop=True)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Buffered (hysteresis) persistent-book portfolio construction — NEW
# ─────────────────────────────────────────────────────────────────────────────

def build_buffered_daily_series(
    score_df: pd.DataFrame, ret1d_wide: pd.DataFrame, master_calendar: pd.DatetimeIndex,
    entry_pct: float, exit_pct: float, min_hold_days: int = 0,
) -> pd.DataFrame:
    """Single persistent long book + single persistent short book with
    rank-band hysteresis and an optional time-based lock (min_hold_days).

    Timing: the rebalance decided from date t's cross-sectional rank is
    deployed at open(t+1) (ENTRY_LAG=1, same convention as the tranche
    control) and earns ret1d_wide.loc[t+1] = open(t+2)/open(t+1) - 1.
    Turnover from the t -> t+1 rebalance is charged on that same portfolio
    day (t+1).
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

        # LONG leg: survivors (held + still inside the exit band, or locked) ...
        new_held_long: Dict[str, int] = {}
        for sym, entered_at in held_long.items():
            if sym not in ranks.index:
                continue
            days_held = i - entered_at
            if days_held < min_hold_days or ranks[sym] >= exit_thresh_long:
                new_held_long[sym] = entered_at
        # ... plus fresh entries clearing the (stricter) entry band.
        for sym in ranks.index[ranks >= entry_thresh_long]:
            if sym not in new_held_long:
                new_held_long[sym] = i

        # SHORT leg, symmetric.
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
# Per-cell performance stats
# ─────────────────────────────────────────────────────────────────────────────

def perf_from_daily(daily: pd.DataFrame, bps_list=BPS_GRID) -> Dict:
    if daily.empty or len(daily) < 2:
        return dict(
            n_days=int(len(daily)), turnover_yr=0.0, ann_vol_gross=0.0,
            sharpe_gross=0.0, sharpe_net={f"{b}bps": 0.0 for b in bps_list},
            max_drawdown_gross=0.0,
        )
    gross = daily["gross"].values
    turnover = daily["turnover"].values

    std_g = np.std(gross, ddof=1)
    sharpe_gross = float(np.mean(gross) / std_g * np.sqrt(252)) if std_g > 1e-12 else 0.0
    ann_vol_gross = float(std_g * np.sqrt(252))
    turnover_yr = float(np.mean(turnover) * 252)

    cum = np.cumprod(1.0 + gross)
    running_max = np.maximum.accumulate(cum)
    drawdown = cum / running_max - 1.0
    max_dd = float(drawdown.min())

    sharpe_net = {}
    for bps in bps_list:
        rate = bps / 10_000.0
        net = gross - rate * turnover
        std_n = np.std(net, ddof=1)
        sharpe_net[f"{bps}bps"] = round(float(np.mean(net) / std_n * np.sqrt(252)) if std_n > 1e-12 else 0.0, 4)

    return dict(
        n_days=int(len(daily)),
        turnover_yr=round(turnover_yr, 3),
        ann_vol_gross=round(ann_vol_gross, 4),
        sharpe_gross=round(sharpe_gross, 4),
        sharpe_net=sharpe_net,
        max_drawdown_gross=round(max_dd, 4),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

CELLS = [
    dict(kind="tranche_control", entry_pct=DECILE_FRAC, exit_pct=DECILE_FRAC, min_hold_days=None),
    dict(kind="buffered", entry_pct=0.10, exit_pct=0.10, min_hold_days=0),
    dict(kind="buffered", entry_pct=0.10, exit_pct=0.20, min_hold_days=0),
    dict(kind="buffered", entry_pct=0.10, exit_pct=0.30, min_hold_days=0),
    dict(kind="buffered", entry_pct=0.10, exit_pct=0.40, min_hold_days=0),
    dict(kind="min_hold", entry_pct=0.10, exit_pct=0.10, min_hold_days=5),
    dict(kind="min_hold", entry_pct=0.10, exit_pct=0.10, min_hold_days=10),
    dict(kind="min_hold", entry_pct=0.10, exit_pct=0.10, min_hold_days=20),
]


def run() -> Dict:
    t0 = time.time()

    dev_predictions = load_dev_predictions()
    model_ic = load_dev_ic_from_v3_results()

    symbols = sorted(dev_predictions["symbol"].unique())
    open_wide, close_wide = load_open_close(symbols, truncate_before=HOLDOUT_START)
    master_calendar = open_wide.index

    # HARD-RULE self-check 2: the freshly (re)loaded price panel itself must
    # never contain a holdout date either.
    assert master_calendar.max() < HOLDOUT_START, "open_wide contains a date >= HOLDOUT_START — aborting."
    print(f"[holdout-freeze self-check 2] PASS: price panel max date "
          f"{master_calendar.max().date()} < {HOLDOUT_START.date()}. "
          f"{len(symbols)} symbols, {len(master_calendar):,} trading days loaded, all dev-only.")

    ret1d_wide_raw = open_wide.shift(-1) / open_wide - 1.0
    ret1d_wide, n_bad_ret1d = clean_extreme_returns(ret1d_wide_raw)
    print(f"[return-hygiene] masked {n_bad_ret1d} portfolio-marking 1-day returns with "
          f"|return| > {RETURN_HYGIENE_THRESHOLD:.0%} (dev-only price panel).")

    rev5_df = build_rev5_score_df(dev_predictions, close_wide)
    rev5_ic_series = compute_ic_series(rev5_df, score_col="score", y_col="y")
    rev5_ic = ic_stats(rev5_ic_series)

    model_score_df = dev_predictions[["date", "symbol"]].copy()
    model_score_df["score"] = dev_predictions["y_pred"].values
    rev5_score_df = rev5_df[["date", "symbol", "score"]].copy()

    signals = {
        "model": (model_score_df, model_ic),
        "rev5": (rev5_score_df, rev5_ic),
    }

    grid_rows = []
    for signal_name, (score_df, ic) in signals.items():
        for cell in CELLS:
            if cell["kind"] == "tranche_control":
                daily = build_tranche_daily_series(score_df, ret1d_wide, master_calendar)
            else:
                daily = build_buffered_daily_series(
                    score_df, ret1d_wide, master_calendar,
                    entry_pct=cell["entry_pct"], exit_pct=cell["exit_pct"],
                    min_hold_days=cell["min_hold_days"] or 0,
                )
            perf = perf_from_daily(daily)
            row = {
                "signal": signal_name,
                "kind": cell["kind"],
                "entry_pct": cell["entry_pct"],
                "exit_pct": cell["exit_pct"],
                "min_hold_days": cell["min_hold_days"],
                **perf,
                "ic": ic,
            }
            grid_rows.append(row)
            print(
                f"  [{signal_name:5s}] {cell['kind']:16s} entry={cell['entry_pct']:.2f} "
                f"exit={cell['exit_pct']:.2f} min_hold={str(cell['min_hold_days']):>4s} | "
                f"turnover/yr={perf['turnover_yr']:6.2f} ann_vol={perf['ann_vol_gross']:.3f} "
                f"ShGross={perf['sharpe_gross']:+.3f} ShNet5={perf['sharpe_net']['5bps']:+.3f} "
                f"ShNet10={perf['sharpe_net']['10bps']:+.3f} ShNet20={perf['sharpe_net']['20bps']:+.3f} "
                f"maxDD={perf['max_drawdown_gross']:+.3f} meanIC={ic['mean_ic']:+.5f}"
            )

    elapsed = round(time.time() - t0, 2)

    output = {
        "note": "DEVELOPMENT PERIOD ONLY. No date >= HOLDOUT_START was loaded, scored, or evaluated in this run.",
        "holdout_start": str(HOLDOUT_START.date()),
        "holdout_frozen_confirmed": True,
        "cost_convention": "turnover_d = sum|w_d - w_{d-1}|/2 (both legs); cost = COST_RATE * turnover_d",
        "return_hygiene_threshold": RETURN_HYGIENE_THRESHOLD,
        "n_bad_ret1d_masked": n_bad_ret1d,
        "bps_grid": list(BPS_GRID),
        "n_symbols": len(symbols),
        "grid": grid_rows,
        "elapsed_seconds": elapsed,
    }

    XS_V3_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as fh:
        json.dump(output, fh, indent=2, default=str)

    print(f"\n[HOLDOUT FREEZE] confirmed: no date >= {HOLDOUT_START.date()} was loaded, scored, "
          f"evaluated, or used in any computation in this run.")
    print(f"Wrote {OUT_PATH}")
    print(f"Elapsed: {elapsed:.1f}s")
    return output


if __name__ == "__main__":
    run()
