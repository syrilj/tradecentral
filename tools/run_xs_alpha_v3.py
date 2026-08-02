#!/usr/bin/env python3
"""run_xs_alpha_v3.py — Cross-Sectional Alpha, XGBoost Regression, Purged Walk-Forward (v3).

Standalone script. Does NOT import from run_walkforward_backtest.py.

Timing contract
----------------
  Signal computed at CLOSE of bar t (using only data through bar t).
  Entry  = OPEN of bar t+1.
  Exit   = OPEN of bar t+6   (HOLD = 5 bars).

Every feature is computed per-symbol on that symbol's own bar sequence, using
only non-negative shifts / trailing rolling windows (verified by a source-code
self-check at runtime — see `selfcheck_no_negative_shift`). Features are then
converted to cross-sectional percentile ranks per date, in [-0.5, +0.5].

Target: y = fwd_ret - cross_sectional_mean(fwd_ret) per date (dollar-neutral
book's relative return). fwd_ret itself intentionally uses forward opens
(open.shift(-1), open.shift(-6)) — that is the label, not a feature, so it is
built in a separate function that is not subject to the no-negative-shift
check.

Split: all model development / walk-forward / metric reporting happens on
dates < HOLDOUT_START. Data on/after HOLDOUT_START is scored exactly once, at
the end, by a single final model trained on the full development period.

Usage:
    python3 edge/tools/run_xs_alpha_v3.py --smoke
    python3 edge/tools/run_xs_alpha_v3.py
"""
from __future__ import annotations

import argparse
import inspect
import json
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "edge" / "data" / "1d_wide"
OUT_DIR = ROOT / "edge" / "runs" / "xs_v3"

# ── Timing / execution contract (fixed, pre-declared) ───────────────────────
HOLD_DAYS = 5                       # bars held
ENTRY_LAG = 1                       # entry at O_{t+1}
EXIT_LAG = ENTRY_LAG + HOLD_DAYS    # exit at O_{t+6}
COST_BPS = 20                       # 20 bps charged on tranche entry-day turnover
COST_RATE = COST_BPS / 10_000.0

# ── Universe / data-quality gates ────────────────────────────────────────────
MIN_ROWS_PER_SYMBOL = 400
MIN_SYMBOLS_PER_DATE = 50
SMOKE_N_SYMBOLS = 120

# ── Split ─────────────────────────────────────────────────────────────────────
HOLDOUT_START = pd.Timestamp("2024-08-01")

# ── Walk-forward parameters (development period only) ───────────────────────
TRAIN_YEARS = 3
TEST_MONTHS = 6
PURGE_DAYS = 10   # horizon is HOLD_DAYS=5 trading bars; 10 calendar days is sufficient
                   # buffer (covers weekends) to guarantee no train row's label
                   # window overlaps the test window.

# ── Portfolio construction ───────────────────────────────────────────────────
DECILE_FRAC = 0.10   # top/bottom 10% by cross-sectional rank of prediction

# ── Return hygiene ────────────────────────────────────────────────────────────
# Some source parquet files contain unadjusted-split / bad-print bars (e.g. a
# bankruptcy-reorg reverse split recorded as a raw price jump instead of being
# back-adjusted). A single such bar can produce a fabricated >100x 1-day
# return that swamps a decile-weighted book. Any bar whose 1-day open-to-open
# return (portfolio marking) or forward return (target) exceeds this in
# absolute value is treated as a bad print and set to NaN rather than a
# genuine return.
RETURN_HYGIENE_THRESHOLD = 0.50

# ── Bootstrap ─────────────────────────────────────────────────────────────────
BOOT_BLOCK = 21
BOOT_DRAWS = 1000
BOOT_SEED = 42

# ── Feature list (order matters — matches X column order fed to the model) ──
FEATURE_COLS = [
    "mom21", "mom63", "mom126_21", "rev5", "vol20", "atr_pct", "gap",
    "gap_atr", "vol_surge", "dollar_vol", "dist_sma50", "dist_high252", "illiq",
]

# ── XGBoost hyperparameters — FIXED A PRIORI, do not tune ───────────────────
XGB_PARAMS_BASE = dict(
    objective="reg:squarederror",
    max_depth=4,
    learning_rate=0.03,
    n_estimators=300,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=20,
    reg_alpha=1.0,
    reg_lambda=10.0,
    random_state=42,
    n_jobs=4,
    verbosity=0,
)


# ─────────────────────────────────────────────────────────────────────────────
# Feature construction (per symbol). NO NEGATIVE SHIFTS ALLOWED IN THIS FUNCTION.
# Self-checked at runtime via inspect.getsource — keep the source clean of the
# literal substring "shift(-" (including in comments).
# ─────────────────────────────────────────────────────────────────────────────

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build the 13 raw (non-ranked) features for a single symbol.

    `df` must have columns open/high/low/close/volume, sorted ascending by
    date. Every quantity below uses only the current bar or bars strictly
    earlier in the sequence (forward-looking shifts are never used here —
    only trailing shift/pct_change/rolling, all with non-negative lookback).
    """
    c = df["close"]
    o = df["open"]
    h = df["high"]
    lo = df["low"]
    v = df["volume"]
    prev_c = c.shift(1)

    mom21 = c.pct_change(21)
    mom63 = c.pct_change(63)
    mom126_21 = c.shift(21) / c.shift(126) - 1.0
    rev5 = c.pct_change(5)
    vol20 = c.pct_change().rolling(20).std()

    # True Range: needs h, l, AND prev_c all valid — use skipna=False so the
    # first bar (prev_c undefined) correctly yields NaN rather than silently
    # falling back to h-l alone.
    tr_components = pd.concat(
        [h - lo, (h - prev_c).abs(), (lo - prev_c).abs()], axis=1
    )
    tr = tr_components.max(axis=1, skipna=False)
    atr_pct = tr.rolling(20).mean() / c

    gap = (o - prev_c) / prev_c.replace(0, np.nan)
    # gap is a price-delta divided by a price -> dimensionless fraction.
    # atr_pct is an average price-range divided by a price -> also a
    # dimensionless fraction. Their ratio is therefore dimensionless too.
    gap_atr = gap / atr_pct.replace(0, np.nan)
    gap_atr = gap_atr.replace([np.inf, -np.inf], np.nan)

    vol_20_prior = v.shift(1).rolling(20).mean()   # average ends at bar t-1
    vol_surge = v / vol_20_prior.replace(0, np.nan)

    dollar = (c * v).clip(lower=1e-9)
    dollar_vol = np.log(dollar).rolling(20).mean()

    sma50 = c.rolling(50).mean()
    dist_sma50 = c / sma50.replace(0, np.nan) - 1.0

    high252 = c.rolling(252).max()
    dist_high252 = c / high252.replace(0, np.nan) - 1.0

    illiq_daily = c.pct_change().abs() / dollar
    illiq = illiq_daily.rolling(20).mean()

    feats = pd.DataFrame(
        {
            "mom21": mom21,
            "mom63": mom63,
            "mom126_21": mom126_21,
            "rev5": rev5,
            "vol20": vol20,
            "atr_pct": atr_pct,
            "gap": gap,
            "gap_atr": gap_atr,
            "vol_surge": vol_surge,
            "dollar_vol": dollar_vol,
            "dist_sma50": dist_sma50,
            "dist_high252": dist_high252,
            "illiq": illiq,
        },
        index=df.index,
    )
    return feats


def build_target(open_s: pd.Series) -> pd.Series:
    """Forward return label. Uses forward-looking shifts DELIBERATELY — this
    is the label being predicted, not a feature, so it is exempt from the
    no-negative-shift self-check (which only inspects build_features).

    entry = O_{t+1}, exit = O_{t+6}  ->  fwd_ret = O_{t+6}/O_{t+1} - 1
    """
    entry = open_s.shift(-ENTRY_LAG)
    exit_ = open_s.shift(-EXIT_LAG)
    return exit_ / entry.replace(0, np.nan) - 1.0


def clean_extreme_returns(
    returns, threshold: float = RETURN_HYGIENE_THRESHOLD
) -> Tuple[object, int]:
    """Mask |return| > threshold to NaN (unadjusted-split / bad-print guard).

    Works on either a Series (per-symbol) or a DataFrame (wide date x symbol
    matrix). Pre-existing NaNs are left alone (NaN > threshold is False).
    Returns (cleaned, n_masked).
    """
    bad = returns.abs() > threshold
    n_masked = int(np.asarray(bad).sum())
    cleaned = returns.mask(bad)
    return cleaned, n_masked


# ─────────────────────────────────────────────────────────────────────────────
# Self-checks
# ─────────────────────────────────────────────────────────────────────────────

def selfcheck_no_negative_shift() -> None:
    src = inspect.getsource(build_features)
    assert "shift(-" not in src, "Negative shift found in build_features() — lookahead bug!"
    print("[self-check 1] PASS: build_features() contains no negative shift.")


def selfcheck_fold_purge(folds: List[Dict]) -> None:
    for f in folds:
        assert f["train_max_date"] < f["test_min_date"], (
            f"Fold {f['fold']}: train_max_date {f['train_max_date']} >= "
            f"test_min_date {f['test_min_date']}"
        )
        gap_days = (f["test_min_date"] - f["train_max_date"]).days
        assert gap_days >= PURGE_DAYS, (
            f"Fold {f['fold']}: purge gap {gap_days}d < required {PURGE_DAYS}d"
        )
    print(
        f"[self-check 2] PASS: {len(folds)} folds all satisfy "
        f"max(train_date) < min(test_date) with purge gap >= {PURGE_DAYS}d."
    )


def selfcheck_holdout_model(train_max_date: pd.Timestamp) -> None:
    assert train_max_date < HOLDOUT_START, (
        f"Final model trained through {train_max_date}, which is not < "
        f"HOLDOUT_START {HOLDOUT_START} — holdout leakage!"
    )
    print(
        f"[self-check 3] PASS: final model's training data max date "
        f"({train_max_date.date()}) < HOLDOUT_START ({HOLDOUT_START.date()})."
    )


def print_panel_shape(name: str, df: pd.DataFrame) -> None:
    n_dates = df["date"].nunique()
    n_symbols = df["symbol"].nunique()
    n_obs = len(df)
    print(f"[self-check 4] {name}: n_dates={n_dates:,}  n_symbols={n_symbols:,}  n_observations={n_obs:,}")


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

def load_universe(smoke: bool) -> Tuple[pd.DataFrame, pd.DataFrame, int]:
    """Load all parquet files, compute per-symbol features + target.

    Returns (panel_raw, open_wide):
      panel_raw : long DataFrame [date, symbol, open] + FEATURE_COLS + [fwd_ret],
                  BEFORE the >=MIN_SYMBOLS_PER_DATE date filter.
      open_wide : date x symbol wide table of open price, full calendar
                  coverage (used to build the 1-day open-to-open return
                  matrix for portfolio P&L, independent of any later
                  date-qualification filtering).
    """
    files = sorted(DATA_DIR.glob("*.parquet"))
    if smoke:
        files = files[:SMOKE_N_SYMBOLS]
    print(f"[data] {len(files)} parquet files found in {DATA_DIR}")

    rows_frames: List[pd.DataFrame] = []
    open_frames: List[pd.Series] = []
    n_kept, n_dropped_short = 0, 0
    n_bad_target_total = 0

    for p in files:
        sym = p.stem
        df = pd.read_parquet(p)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        if len(df) < MIN_ROWS_PER_SYMBOL:
            n_dropped_short += 1
            continue

        feats = build_features(df)
        fwd_ret_raw = build_target(df["open"])
        # CHANGE 1 (return hygiene): the target is a forward return built from
        # raw opens; an unadjusted-split bar inside its window fabricates a
        # huge fwd_ret. Mask it the same way as the 1-day marking return.
        fwd_ret, n_bad = clean_extreme_returns(fwd_ret_raw)
        n_bad_target_total += n_bad

        sym_df = feats.copy()
        sym_df["open"] = df["open"]
        sym_df["fwd_ret"] = fwd_ret
        sym_df["date"] = df.index
        sym_df["symbol"] = sym
        sym_df = sym_df.reset_index(drop=True)
        rows_frames.append(sym_df)

        os_ = df["open"].copy()
        os_.name = sym
        open_frames.append(os_)
        n_kept += 1

    panel_raw = pd.concat(rows_frames, ignore_index=True)
    panel_raw["date"] = pd.to_datetime(panel_raw["date"])

    open_wide = pd.concat(open_frames, axis=1).sort_index()
    open_wide.index = pd.to_datetime(open_wide.index)

    print(f"[data] kept {n_kept} symbols ({n_dropped_short} dropped for <{MIN_ROWS_PER_SYMBOL} rows)")
    print(f"[data] panel_raw: {len(panel_raw):,} rows spanning {panel_raw['date'].min().date()} to {panel_raw['date'].max().date()}")
    print(
        f"[return-hygiene] target fwd_ret: masked {n_bad_target_total} observations with "
        f"|fwd_ret| > {RETURN_HYGIENE_THRESHOLD:.0%} across all symbols (unadjusted-split / bad-print guard)."
    )
    return panel_raw, open_wide, n_bad_target_total


# ─────────────────────────────────────────────────────────────────────────────
# Cross-sectional normalization + target demeaning
# ─────────────────────────────────────────────────────────────────────────────

def build_panel(panel_raw: pd.DataFrame) -> pd.DataFrame:
    date_counts = panel_raw.groupby("date").size()
    qualifying_dates = date_counts[date_counts >= MIN_SYMBOLS_PER_DATE].index
    n_dropped_dates = date_counts.shape[0] - len(qualifying_dates)
    panel = panel_raw[panel_raw["date"].isin(qualifying_dates)].copy()
    print(
        f"[xs-norm] {len(qualifying_dates):,} qualifying dates (>= {MIN_SYMBOLS_PER_DATE} symbols); "
        f"{n_dropped_dates} dates dropped."
    )

    for feat in FEATURE_COLS:
        ranked = panel.groupby("date")[feat].rank(pct=True) - 0.5
        panel[feat] = ranked.fillna(0.0)

    panel["y"] = panel["fwd_ret"] - panel.groupby("date")["fwd_ret"].transform("mean")

    n_before = len(panel)
    panel = panel.dropna(subset=["fwd_ret", "y"]).reset_index(drop=True)
    print(
        f"[xs-norm] dropped {n_before - len(panel):,} rows with undefined fwd_ret "
        f"(tail of series, no future data available)."
    )
    return panel


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward fold generation (development period only)
# ─────────────────────────────────────────────────────────────────────────────

def generate_folds(dev: pd.DataFrame) -> List[Dict]:
    dates = np.sort(dev["date"].unique())
    min_date = pd.Timestamp(dates.min())
    max_date = pd.Timestamp(dates.max())

    folds = []
    test_start = min_date + pd.DateOffset(years=TRAIN_YEARS)
    fold_id = 1
    while test_start <= max_date:
        test_end = test_start + pd.DateOffset(months=TEST_MONTHS)
        purge_boundary = test_start - pd.Timedelta(days=PURGE_DAYS)

        train_mask = (dev["date"] >= min_date) & (dev["date"] < purge_boundary)
        test_mask = (dev["date"] >= test_start) & (dev["date"] < test_end)

        n_train = int(train_mask.sum())
        n_test = int(test_mask.sum())

        if n_train >= 1000 and n_test >= 100:
            train_dates = dev.loc[train_mask, "date"]
            test_dates = dev.loc[test_mask, "date"]
            folds.append(
                dict(
                    fold=fold_id,
                    train_start=min_date,
                    train_end=purge_boundary,
                    test_start=test_start,
                    test_end=test_end,
                    train_mask=train_mask,
                    test_mask=test_mask,
                    train_max_date=train_dates.max(),
                    test_min_date=test_dates.min(),
                    n_train=n_train,
                    n_test=n_test,
                )
            )
            fold_id += 1
        test_start = test_end

    print(f"[wf] {len(folds)} walk-forward folds generated on development period.")
    return folds


# ─────────────────────────────────────────────────────────────────────────────
# IC statistics
# ─────────────────────────────────────────────────────────────────────────────

def compute_ic_series(pred_df: pd.DataFrame) -> pd.Series:
    def _ic(g: pd.DataFrame) -> float:
        if len(g) < 5 or g["y_pred"].std(ddof=1) < 1e-12 or g["y"].std(ddof=1) < 1e-12:
            return np.nan
        return g["y_pred"].corr(g["y"], method="spearman")

    ic = pred_df.groupby("date")[["y_pred", "y"]].apply(_ic)
    ic.name = "ic"
    return ic.dropna().sort_index()


def block_bootstrap_ci(
    values: np.ndarray, block_size: int = BOOT_BLOCK, n_boot: int = BOOT_DRAWS,
    ci: float = 0.95, seed: int = BOOT_SEED,
) -> Tuple[float, float]:
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
# Portfolio construction — overlapping tranches
# ─────────────────────────────────────────────────────────────────────────────

def build_decile_weights(pred_df: pd.DataFrame) -> Dict[pd.Timestamp, pd.Series]:
    """Per date: top decile long (+1/n_long), bottom decile short (-1/n_short)."""
    weights: Dict[pd.Timestamp, pd.Series] = {}
    for date, g in pred_df.groupby("date"):
        ranks = g["y_pred"].rank(pct=True)
        long_mask = ranks >= (1.0 - DECILE_FRAC)
        short_mask = ranks <= DECILE_FRAC
        n_long = int(long_mask.sum())
        n_short = int(short_mask.sum())
        if n_long == 0 or n_short == 0:
            continue
        w = pd.Series(0.0, index=g["symbol"].values)
        w.loc[g.loc[long_mask, "symbol"].values] = 1.0 / n_long
        w.loc[g.loc[short_mask, "symbol"].values] = -1.0 / n_short
        weights[pd.Timestamp(date)] = w
    return weights


def build_portfolio_daily_series(
    weights: Dict[pd.Timestamp, pd.Series],
    ret1d_wide: pd.DataFrame,
    master_calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Aggregate overlapping HOLD_DAYS-day tranches into a contiguous daily
    gross/net/turnover series.

    Each signal date t contributes a tranche that enters at position t+1 and
    is "active" (contributes one realized 1-day open-to-open return) on the
    HOLD_DAYS calendar positions t+1 .. t+HOLD_DAYS. On any given day d, the
    portfolio return is the MEAN (not sum) of the day's return across
    whichever tranches are currently active — this is what §PORTFOLIO
    CONSTRUCTION calls "run 5 overlapping tranches, each day deploy 1/5 of
    capital". A tranche's turnover cost is charged once, on its own entry
    day (t+1), not on the signal day t itself.

    CHANGE 2 (cost convention, report both): each tranche's weight vector
    sums to +1 on the long leg and -1 on the short leg, i.e. sum(|w|) = 2
    (a two-legged book). Two cost conventions are computed:
      turnover_capital = has_entry / HOLD_DAYS                     (capital-share only)
      turnover_gross2  = has_entry * sum(|w|)_tranche / HOLD_DAYS  (both legs, = 2x capital in steady state)
    net_gross2 (both legs charged) is the conservative, headline convention;
    net_capital is reported alongside for comparison/audit.
    """
    empty_cols = ["date", "gross", "net_capital", "net_gross2", "turnover_capital", "turnover_gross2"]
    if not weights:
        return pd.DataFrame(columns=empty_cols)

    signal_dates = sorted(weights.keys())
    symbols = ret1d_wide.columns

    records = []
    for d, w in weights.items():
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

    # per-tranche gross exposure sum(|w|) on its own signal date (0 elsewhere).
    # By construction (long leg sums to +1, short leg to -1) this is exactly
    # 2.0 for every signal date, but it is computed from the actual weight
    # vectors rather than hardcoded, so it stays correct/auditable if the
    # portfolio construction ever changes.
    gross_exposure_signal = pd.Series(0.0, index=master_calendar)
    for d, w in weights.items():
        gross_exposure_signal.loc[d] = float(w.abs().sum())

    # sum of weight vectors over the trailing HOLD_DAYS signal dates, "as of"
    # the day being evaluated (shift(1) excludes the current day itself,
    # since a signal at t only becomes active starting the NEXT day, t+1).
    roll_w = Wfull.rolling(window=HOLD_DAYS, min_periods=1).sum().shift(1).fillna(0.0)
    n_active = has_signal.rolling(window=HOLD_DAYS, min_periods=1).sum().shift(1).fillna(0.0)

    ret_aligned = ret1d_wide.reindex(index=master_calendar, columns=symbols).fillna(0.0)
    tranche_sum_return = (roll_w * ret_aligned).sum(axis=1)

    gross = tranche_sum_return / n_active.replace(0.0, np.nan)
    gross = gross.fillna(0.0)   # zero-fill days with no active positions

    has_entry = has_signal.shift(1).fillna(0.0)              # entry day = signal day + 1
    gross_exposure_entry = gross_exposure_signal.shift(1).fillna(0.0)   # tranche's own sum|w|, on its entry day

    turnover_capital = has_entry / HOLD_DAYS                       # coordinator's original convention
    turnover_gross2 = (has_entry * gross_exposure_entry) / HOLD_DAYS  # both legs charged

    cost_capital = COST_RATE * turnover_capital
    cost_gross2 = COST_RATE * turnover_gross2

    net_capital = gross - cost_capital
    net_gross2 = gross - cost_gross2

    # Trim to the contiguous window actually touched by these tranches:
    # from the first entry day through the last active day.
    first_signal_pos = master_calendar.get_indexer([signal_dates[0]])[0]
    last_signal_pos = master_calendar.get_indexer([signal_dates[-1]])[0]
    start_pos = min(first_signal_pos + 1, len(master_calendar) - 1)
    end_pos = min(last_signal_pos + HOLD_DAYS, len(master_calendar) - 1)

    idx = master_calendar[start_pos:end_pos + 1]
    out = pd.DataFrame(
        {
            "date": idx,
            "gross": gross.loc[idx].values,
            "net_capital": net_capital.loc[idx].values,
            "net_gross2": net_gross2.loc[idx].values,
            "turnover_capital": turnover_capital.loc[idx].values,
            "turnover_gross2": turnover_gross2.loc[idx].values,
        }
    ).reset_index(drop=True)
    return out


def _sharpe(x: np.ndarray) -> float:
    std = np.std(x, ddof=1)
    return float(np.mean(x) / std * np.sqrt(252)) if std > 1e-12 else 0.0


def cost_sensitivity(daily: pd.DataFrame, bps_list=(5, 10, 20)) -> Dict[str, float]:
    """Headline net_gross2 Sharpe recomputed at alternate round-trip cost
    rates, holding gross returns and the gross2 turnover series fixed. The
    bps=20 entry must equal the headline Sharpe exactly (same formula, same
    COST_BPS default) — used as an internal consistency check.
    """
    if daily.empty or len(daily) < 2:
        return {f"{bps}bps": 0.0 for bps in bps_list}
    gross = daily["gross"].values
    turnover_gross2 = daily["turnover_gross2"].values
    out = {}
    for bps in bps_list:
        rate = bps / 10_000.0
        net = gross - rate * turnover_gross2
        out[f"{bps}bps"] = round(_sharpe(net), 4)
    return out


def perf_stats(daily: pd.DataFrame) -> Dict:
    if daily.empty or len(daily) < 2:
        return dict(
            sharpe_gross=0.0, sharpe_net_capital=0.0, sharpe_net_gross2=0.0,
            annualized_return_net_gross2=0.0, annualized_vol_net_gross2=0.0,
            annualized_vol_net_capital=0.0,
            max_drawdown_net_gross2=0.0, hit_rate_net_gross2=0.0,
            avg_daily_turnover_capital=0.0, avg_daily_turnover_gross2=0.0,
            n_days=int(len(daily)),
        )
    gross = daily["gross"].values
    net_capital = daily["net_capital"].values
    net_gross2 = daily["net_gross2"].values   # headline "net" — conservative, both legs charged

    sharpe_gross = _sharpe(gross)
    sharpe_net_capital = _sharpe(net_capital)
    sharpe_net_gross2 = _sharpe(net_gross2)   # headline

    ann_return_gross2 = float(np.mean(net_gross2) * 252)
    ann_vol_gross2 = float(np.std(net_gross2, ddof=1) * np.sqrt(252))
    ann_vol_capital = float(np.std(net_capital, ddof=1) * np.sqrt(252))

    cum = np.cumprod(1.0 + net_gross2)
    running_max = np.maximum.accumulate(cum)
    drawdown = cum / running_max - 1.0
    max_dd = float(drawdown.min())

    hit_rate = float((net_gross2 > 0).mean())
    avg_turnover_capital = float(daily["turnover_capital"].mean())
    avg_turnover_gross2 = float(daily["turnover_gross2"].mean())

    # Internal-consistency check computed from RAW (unrounded) mean/std, since
    # ann_return/ann_vol == Sharpe is an exact algebraic identity when all
    # three come from the same mean/std — rounding each to 4dp independently
    # for display would otherwise make this look like a false mismatch.
    implied_sharpe = ann_return_gross2 / ann_vol_gross2 if ann_vol_gross2 > 1e-9 else 0.0
    internally_consistent = bool(abs(implied_sharpe - sharpe_net_gross2) < 1e-6)

    return dict(
        sharpe_gross=round(sharpe_gross, 4),
        sharpe_net_capital=round(sharpe_net_capital, 4),
        sharpe_net_gross2=round(sharpe_net_gross2, 4),   # headline
        annualized_return_net_gross2=round(ann_return_gross2, 4),
        annualized_vol_net_gross2=round(ann_vol_gross2, 4),
        annualized_vol_net_capital=round(ann_vol_capital, 4),
        max_drawdown_net_gross2=round(max_dd, 4),
        hit_rate_net_gross2=round(hit_rate, 4),
        avg_daily_turnover_capital=round(avg_turnover_capital, 4),
        avg_daily_turnover_gross2=round(avg_turnover_gross2, 4),
        n_days=int(len(daily)),
        cost_sensitivity_sharpe_net_gross2=cost_sensitivity(daily),
        internally_consistent=internally_consistent,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run(smoke: bool) -> Dict:
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    from xgboost import XGBRegressor

    selfcheck_no_negative_shift()

    panel_raw, open_wide, n_bad_target_total = load_universe(smoke)
    ret1d_wide_raw = open_wide.shift(-1) / open_wide - 1.0   # portfolio P&L only, not a feature
    # CHANGE 1 (return hygiene): mask bad-print / unadjusted-split 1-day
    # open-to-open returns before they enter portfolio marking.
    ret1d_wide, n_bad_ret1d = clean_extreme_returns(ret1d_wide_raw)
    print(
        f"[return-hygiene] portfolio-marking 1-day returns: masked {n_bad_ret1d} bars with "
        f"|return| > {RETURN_HYGIENE_THRESHOLD:.0%} (unadjusted-split / bad-print guard)."
    )
    master_calendar = open_wide.index

    panel = build_panel(panel_raw)

    dev = panel[panel["date"] < HOLDOUT_START].reset_index(drop=True)
    holdout = panel[panel["date"] >= HOLDOUT_START].reset_index(drop=True)
    print_panel_shape("dev", dev)
    print_panel_shape("holdout", holdout)

    xgb_params = dict(XGB_PARAMS_BASE)
    if smoke:
        xgb_params["n_estimators"] = 50

    # ── Walk-forward over development period ─────────────────────────────────
    folds = generate_folds(dev)
    selfcheck_fold_purge(folds)

    dev_pred_frames = []
    fold_summaries = []

    for f in folds:
        X_train = dev.loc[f["train_mask"], FEATURE_COLS].values.astype(np.float32)
        y_train = dev.loc[f["train_mask"], "y"].values.astype(np.float64)
        test_df = dev.loc[f["test_mask"]].copy()
        X_test = test_df[FEATURE_COLS].values.astype(np.float32)

        model = XGBRegressor(**xgb_params)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        pred_df = pd.DataFrame(
            {
                "date": test_df["date"].values,
                "symbol": test_df["symbol"].values,
                "y_pred": y_pred,
                "y": test_df["y"].values,
                "fwd_ret": test_df["fwd_ret"].values,
                "fold": f["fold"],
                "period": "dev",
            }
        )
        dev_pred_frames.append(pred_df)

        fold_ic = compute_ic_series(pred_df)
        fold_ic_stats = ic_stats(fold_ic)

        fold_weights = build_decile_weights(pred_df)
        fold_daily = build_portfolio_daily_series(fold_weights, ret1d_wide, master_calendar)
        fold_perf = perf_stats(fold_daily)

        fold_summaries.append(
            {
                "fold": f["fold"],
                "train_start": str(f["train_start"].date()),
                "train_end": str(f["train_end"].date()),
                "test_start": str(f["test_start"].date()),
                "test_end": str(f["test_end"].date()),
                "n_train": f["n_train"],
                "n_test": f["n_test"],
                **fold_ic_stats,
                **fold_perf,
            }
        )
        print(
            f"  Fold {f['fold']:02d} | test {f['test_start'].date()}..{f['test_end'].date()} | "
            f"n_train={f['n_train']:,} n_test={f['n_test']:,} | "
            f"IC={fold_ic_stats['mean_ic']:+.4f} t={fold_ic_stats['t_stat']:+.2f} | "
            f"SharpeNetGross2={fold_perf['sharpe_net_gross2']:.2f}"
        )

    dev_predictions = pd.concat(dev_pred_frames, ignore_index=True)

    dev_ic_series = compute_ic_series(dev_predictions)
    dev_ic_stats = ic_stats(dev_ic_series)

    dev_weights = build_decile_weights(dev_predictions)
    dev_daily = build_portfolio_daily_series(dev_weights, ret1d_wide, master_calendar)
    dev_daily["period"] = "dev"
    dev_perf = perf_stats(dev_daily)

    print(
        f"[dev] overall: n_dates={dev_ic_stats['n_dates']} mean_IC={dev_ic_stats['mean_ic']:+.5f} "
        f"t={dev_ic_stats['t_stat']:+.3f} SharpeNetGross2(headline)={dev_perf['sharpe_net_gross2']:.3f} "
        f"SharpeNetCapital={dev_perf['sharpe_net_capital']:.3f} SharpeGross={dev_perf['sharpe_gross']:.3f}"
    )

    # ── Final model: trained on ALL development-period data ─────────────────
    X_dev_full = dev[FEATURE_COLS].values.astype(np.float32)
    y_dev_full = dev["y"].values.astype(np.float64)
    final_train_max_date = pd.Timestamp(dev["date"].max())
    selfcheck_holdout_model(final_train_max_date)

    final_model = XGBRegressor(**xgb_params)
    final_model.fit(X_dev_full, y_dev_full)

    # ── Holdout — scored EXACTLY ONCE ────────────────────────────────────────
    X_holdout = holdout[FEATURE_COLS].values.astype(np.float32)
    y_holdout_pred = final_model.predict(X_holdout)

    holdout_predictions = pd.DataFrame(
        {
            "date": holdout["date"].values,
            "symbol": holdout["symbol"].values,
            "y_pred": y_holdout_pred,
            "y": holdout["y"].values,
            "fwd_ret": holdout["fwd_ret"].values,
            "fold": -1,
            "period": "holdout",
        }
    )

    holdout_ic_series = compute_ic_series(holdout_predictions)
    holdout_ic_stats = ic_stats(holdout_ic_series)

    holdout_weights = build_decile_weights(holdout_predictions)
    holdout_daily = build_portfolio_daily_series(holdout_weights, ret1d_wide, master_calendar)
    holdout_daily["period"] = "holdout"
    holdout_perf = perf_stats(holdout_daily)

    print(
        f"[holdout] n_dates={holdout_ic_stats['n_dates']} mean_IC={holdout_ic_stats['mean_ic']:+.5f} "
        f"t={holdout_ic_stats['t_stat']:+.3f} SharpeNetGross2(headline)={holdout_perf['sharpe_net_gross2']:.3f} "
        f"SharpeNetCapital={holdout_perf['sharpe_net_capital']:.3f} SharpeGross={holdout_perf['sharpe_gross']:.3f}"
    )

    # Internal-consistency guard requested by coordinator: ann_return / ann_vol
    # must equal Sharpe (same mean/std feed both — checked on raw, unrounded
    # values inside perf_stats), and after Change 1 the CHRD-driven ~185%
    # implied vol should be gone. If it's still wildly elevated (i.e. not a
    # plausible dollar-neutral daily-rebalanced book), stop rather than
    # report numbers that still hide a data problem.
    for label, perf in (("dev", dev_perf), ("holdout", holdout_perf)):
        implied_sharpe = (
            perf["annualized_return_net_gross2"] / perf["annualized_vol_net_gross2"]
            if perf["annualized_vol_net_gross2"] > 1e-9 else 0.0
        )
        print(
            f"[consistency-check] {label}: ann_return={perf['annualized_return_net_gross2']*100:+.2f}% "
            f"ann_vol={perf['annualized_vol_net_gross2']*100:.2f}% -> implied Sharpe {implied_sharpe:.4f} "
            f"vs reported {perf['sharpe_net_gross2']:.4f} | {'OK' if perf['internally_consistent'] else 'MISMATCH'}"
        )
        if not perf["internally_consistent"]:
            raise AssertionError(
                f"{label}: ann_return/ann_vol does not match reported Sharpe — internal inconsistency, stopping."
            )
        if perf["annualized_vol_net_gross2"] > 0.60:
            print(
                f"[consistency-check] WARNING: {label} annualized vol "
                f"{perf['annualized_vol_net_gross2']*100:.1f}% is still implausibly high for a "
                f"dollar-neutral daily-rebalanced book — possible remaining data contamination."
            )

    # ── Assemble outputs ──────────────────────────────────────────────────────
    all_predictions = pd.concat(
        [dev_predictions.rename(columns={"y": "y_true"}), holdout_predictions.rename(columns={"y": "y_true"})],
        ignore_index=True,
    )
    all_predictions.to_parquet(OUT_DIR / "predictions.parquet", index=False)

    daily_cols = ["date", "gross", "net_capital", "net_gross2", "turnover_capital", "turnover_gross2", "period"]
    all_daily = pd.concat([dev_daily[daily_cols], holdout_daily[daily_cols]], ignore_index=True)
    all_daily.to_parquet(OUT_DIR / "daily_returns.parquet", index=False)

    elapsed = round(time.time() - t0, 2)

    config = dict(
        xgb_params=xgb_params,
        hold_days=HOLD_DAYS,
        entry_lag=ENTRY_LAG,
        exit_lag=EXIT_LAG,
        cost_bps=COST_BPS,
        min_rows_per_symbol=MIN_ROWS_PER_SYMBOL,
        min_symbols_per_date=MIN_SYMBOLS_PER_DATE,
        holdout_start=str(HOLDOUT_START.date()),
        train_years=TRAIN_YEARS,
        test_months=TEST_MONTHS,
        purge_days=PURGE_DAYS,
        decile_frac=DECILE_FRAC,
        bootstrap_block=BOOT_BLOCK,
        bootstrap_draws=BOOT_DRAWS,
        feature_cols=FEATURE_COLS,
        smoke=smoke,
        n_symbols_loaded=int(panel_raw["symbol"].nunique()),
        return_hygiene_threshold=RETURN_HYGIENE_THRESHOLD,
        n_bad_ret1d_masked=n_bad_ret1d,
        n_bad_target_masked=n_bad_target_total,
        cost_convention_note=(
            "net_capital = gross - COST_RATE*(1/HOLD) [capital-share only]; "
            "net_gross2 = gross - COST_RATE*(sum|w|_tranche)/HOLD [both legs charged, headline]"
        ),
        cost_sensitivity_bps_grid=[5, 10, 20],
    )

    summary = {
        "model": "xs_alpha_xgb_regression_v3",
        "config": config,
        "dev": {
            "n_dates": int(dev["date"].nunique()),
            "n_symbols": int(dev["symbol"].nunique()),
            "n_observations": int(len(dev)),
            "n_folds": len(folds),
            "ic": dev_ic_stats,
            "portfolio": dev_perf,
            "fold_summaries": fold_summaries,
        },
        "holdout": {
            "n_dates": int(holdout["date"].nunique()),
            "n_symbols": int(holdout["symbol"].nunique()),
            "n_observations": int(len(holdout)),
            "final_model_train_max_date": str(final_train_max_date.date()),
            "ic": holdout_ic_stats,
            "portfolio": holdout_perf,
        },
        "elapsed_seconds": elapsed,
    }

    with open(OUT_DIR / "results.json", "w") as fh:
        json.dump(summary, fh, indent=2, default=str)

    print_summary(summary)
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Console summary
# ─────────────────────────────────────────────────────────────────────────────

def print_summary(s: Dict) -> None:
    sep = "=" * 80
    print(f"\n{sep}")
    print("CROSS-SECTIONAL ALPHA v3 — XGBoost Regression, Purged Walk-Forward")
    print(sep)
    c = s["config"]
    print(f"  Smoke mode        : {c['smoke']}")
    print(f"  Symbols loaded    : {c['n_symbols_loaded']}")
    print(f"  Holdout start     : {c['holdout_start']}")
    print(f"  Hold / entry/exit : {c['hold_days']} bars | O_t+{c['entry_lag']} -> O_t+{c['exit_lag']}")
    print(f"  Cost (COST_BPS)   : {c['cost_bps']} bps round-trip")
    print(f"  Cost conventions  : {c['cost_convention_note']}")
    print(f"  Return hygiene    : masked {c['n_bad_ret1d_masked']} portfolio-marking bars, "
          f"{c['n_bad_target_masked']} target (fwd_ret) obs, |return| > {c['return_hygiene_threshold']:.0%}")
    print(f"  XGB params        : {c['xgb_params']}")
    print()

    def _print_period(label: str, blk: Dict) -> None:
        p = blk["portfolio"]
        print(f"  {label}  (n_dates={blk['n_dates']:,} n_symbols={blk['n_symbols']:,} n_obs={blk['n_observations']:,}" + (f", {blk['n_folds']} folds)" if "n_folds" in blk else ")"))
        print(f"    Mean Rank IC     : {blk['ic']['mean_ic']:+.5f}  (std {blk['ic']['ic_std']:.5f}, n_dates={blk['ic']['n_dates']})")
        print(f"    ICIR / t-stat    : {blk['ic']['icir']:.3f} / {blk['ic']['t_stat']:.3f}")
        print(f"    IC 95% boot CI   : [{blk['ic']['ci_lo']:+.5f}, {blk['ic']['ci_hi']:+.5f}]  (block={c['bootstrap_block']}, draws={c['bootstrap_draws']})  spans_zero={blk['ic']['ci_lo'] <= 0 <= blk['ic']['ci_hi']}")
        print(f"    Sharpe gross              : {p['sharpe_gross']:.3f}")
        print(f"    Sharpe net_capital        : {p['sharpe_net_capital']:.3f}   (COST_RATE*(1/HOLD) — capital-share only)")
        print(f"    Sharpe net_gross2 HEADLINE: {p['sharpe_net_gross2']:.3f}   (COST_RATE*sum|w|/HOLD — both legs, conservative)")
        print(f"    Ann. return (net_gross2)  : {p['annualized_return_net_gross2']*100:+.2f}%")
        print(f"    Ann. vol (net_gross2)     : {p['annualized_vol_net_gross2']*100:.2f}%   |  Ann. vol (net_capital): {p['annualized_vol_net_capital']*100:.2f}%")
        print(f"    Max drawdown (net_gross2) : {p['max_drawdown_net_gross2']*100:.2f}%")
        print(f"    Hit rate (net_gross2)     : {p['hit_rate_net_gross2']:.1%}")
        print(f"    Avg daily turnover        : capital={p['avg_daily_turnover_capital']:.3f}  gross2={p['avg_daily_turnover_gross2']:.3f}")
        print(f"    Cost sensitivity (net_gross2 Sharpe): " + "  ".join(f"{k}={v:.3f}" for k, v in p["cost_sensitivity_sharpe_net_gross2"].items()))
        print(f"    Portfolio days            : {p['n_days']:,}")

    d = s["dev"]
    _print_period("DEVELOPMENT PERIOD", d)
    print()
    print("  Per-Fold Summary:")
    print(f"  {'Fold':>4} {'TestStart':>11} {'TestEnd':>11} {'n_test':>8} {'MeanIC':>9} {'t-stat':>7} {'ShNetG2':>8}")
    for fl in d["fold_summaries"]:
        print(
            f"  {fl['fold']:>4d} {fl['test_start']:>11} {fl['test_end']:>11} {fl['n_test']:>8,} "
            f"{fl['mean_ic']:>+9.5f} {fl['t_stat']:>+7.2f} {fl['sharpe_net_gross2']:>8.2f}"
        )
    print()

    h = s["holdout"]
    print(f"    Final model trained through : {h['final_model_train_max_date']}")
    _print_period("HOLDOUT PERIOD", h)
    print()
    print(f"  Elapsed: {s['elapsed_seconds']:.1f}s")
    print(sep)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Cross-Sectional Alpha v3 — XGBoost regression, purged walk-forward")
    parser.add_argument("--smoke", action="store_true", help=f"Fast path: limit to {SMOKE_N_SYMBOLS} symbols, n_estimators=50")
    args = parser.parse_args()

    result = run(smoke=args.smoke)
    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
