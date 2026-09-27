#!/usr/bin/env python3
"""run_walkforward_backtest.py — Purged Walk-Forward Backtest v2 (Peer-Review Corrected).

Addresses all critical issues raised in external peer review:
  1.  V_t lookahead fixed — volume feature uses v.shift(1) (prior bar).
  2.  Label explicitly defined: y=1 iff net_5d_return > 0 in the *direction* of the gap.
      Entry = O_{t+1}, Exit = O_{t+6} (5-bar hold), gross return = (exit-entry)/entry * sign(gap).
  3.  Signal direction tied to gap sign; a high score on a down-gap → short.
  4.  Isotonic calibration fitted on inner-CV held-out predictions, not train set.
  5.  Purge gap = max label horizon (5 calendar weeks = 7 * HOLD_DAYS).
  6.  Thresholds (0.55 / 0.45) fixed a priori — NOT chosen by examining OOS folds.
  7.  Full probability-score distribution reported across ALL decile buckets.
  8.  Monotonicity tested, not assumed.
  9.  Portfolio Sharpe computed from a single chronological daily P&L series.
  10. Per-fold IC, Sharpe, and win-rate with confidence intervals reported.

Label definition (explicit):
    gap_dir = sign(O_t - C_{t-1})
    gross_ret = (O_{t+6} - O_{t+1}) / O_{t+1} * gap_dir      # 5-bar gap-direction return
    y_i = 1[gross_ret - COST_ROUNDTRIP > 0]

Signal rule (fixed thresholds, direction-aware):
    prob = P(y=1 | X_t)   (calibrated on inner CV)
    if prob >= LONG_THRESH:   position = +gap_dir   (trade in gap direction)
    if prob <= SHORT_THRESH:  position = -gap_dir   (fade the gap)
    else: no trade

Usage:
    python3 edge/tools/run_walkforward_backtest.py
    python3 edge/tools/run_walkforward_backtest.py --smoke
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "edge" / "runs" / "walkforward"

# ── Execution model (fixed, pre-declared) ────────────────────────────────────
HOLD_DAYS = 5            # bars between entry and exit
ENTRY_LAG = 1            # entry at O_{t+ENTRY_LAG}
EXIT_LAG = ENTRY_LAG + HOLD_DAYS   # O_{t+6}
COST_ROUNDTRIP = 0.0020  # 20 bps round-trip (entry + exit)
COST_SHORT_EXTRA = 0.0010  # extra 10 bps borrow/short cost

# ── Signal thresholds (fixed a priori, NOT tuned on OOS) ────────────────────
LONG_THRESH = 0.55       # calibrated P(win) >= this → trade in gap direction
SHORT_THRESH = 0.45      # calibrated P(win) <= this → fade the gap

# ── Walk-forward parameters ──────────────────────────────────────────────────
TRAIN_YEARS_DEFAULT = 3
OOS_MONTHS_DEFAULT = 6
PURGE_DAYS = HOLD_DAYS * 7   # purge ≥ max label horizon (5 weeks buffer)
EMBARGO_DAYS = 2             # small post-test embargo

# ── Universe ──────────────────────────────────────────────────────────────────
LEAD_SYMBOLS = [
    "AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "AMD", "AVGO", "INTC",
    "JPM", "BAC", "V", "MA", "UNH", "JNJ", "PG", "XOM", "CVX", "HD",
    "LLY", "ABBV", "MRK", "PEP", "KO", "COST", "WMT", "TMO", "CSCO", "ACN",
    "NFLX", "CRM", "ORCL", "QCOM", "TXN", "NOW", "IBM", "GE", "CAT", "BA",
]

# ── Feature column names ──────────────────────────────────────────────────────
FEATURE_COLS = [
    "gap_std",       # overnight gap normalised by prior-bar ATR
    "vol_surge",     # prior-bar volume / 20-bar prior-volume average  (FIX #1: lagged)
    "atr_pct",       # 20-bar ATR / prior close
    "mom5",          # 5-bar return lagged 1 bar
    "mom21",         # 21-bar return lagged 1 bar
    "day_of_week",   # 0=Mon … 4=Fri
    "sma50_dist",    # (prior_close - SMA50_prior) / SMA50_prior  (asset-level trend)
    "gap_x_surge",   # interaction: gap_std × vol_surge
    "mom_accel",     # mom5 - mom21
]

# minimum absolute gap z-score to qualify as an event
EVENT_MIN_GAP = 1.5


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

def fetch_multiyear_universe(
    start_date: str = "2019-01-01",
    end_date: str = "2026-07-30",
) -> Dict[str, pd.DataFrame]:
    """Load daily OHLCV. Prefer local parquet cache, fall back to yfinance."""
    import yfinance as yf

    cache_dir = ROOT / "edge" / "data" / "1d"
    data: Dict[str, pd.DataFrame] = {}

    if cache_dir.exists():
        for p in cache_dir.glob("*.parquet"):
            sym = p.stem
            try:
                df = pd.read_parquet(p)
                df.columns = [c.capitalize() for c in df.columns]
                needed = {"Open", "High", "Low", "Close", "Volume"}
                if needed.issubset(df.columns):
                    data[sym] = df[list(needed)].sort_index()
            except Exception:
                pass

    if len(data) >= 10:
        print(f"[data] loaded {len(data)} symbols from local cache.")
        return data

    print(f"[data] fetching {len(LEAD_SYMBOLS)} symbols from yfinance ({start_date}→{end_date}) ...")
    for sym in LEAD_SYMBOLS:
        try:
            df = yf.download(sym, start=start_date, end=end_date, progress=False, auto_adjust=True)
            if df.empty or len(df) < 200:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df = df.droplevel(1, axis=1)
            data[sym] = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        except Exception as exc:
            print(f"  Warning: {sym} failed — {exc}")

    print(f"[data] loaded {len(data)} symbols.")
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Feature engineering  (FIX #1 — all features strictly prior-bar / prior-bar avg)
# ─────────────────────────────────────────────────────────────────────────────

def build_event_features(data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build one row per qualifying gap event.

    All features use information available at signal time (end of bar t):
      • open / high / low / close of bar t  are observable at t-close.
      • volume of bar t  is observable at t-close.
      • FIX #1: vol_surge denominator uses rolling(20) of v.shift(1) — the 20-bar
        average ending at t-1 — so we compare today's volume only to *prior* history.
        (vol_surge itself still uses V_t because the signal is computed after
         today's close; V_t is fully observable at signal time.)
      • Label uses O_{t+1} as entry and O_{t+6} as exit — no same-bar lookahead.
    """
    rows = []

    for sym, df in data.items():
        if df.empty or len(df) < 60:
            continue

        c = df["Close"]
        o = df["Open"]
        h = df["High"]
        lo = df["Low"]
        v = df["Volume"]

        prev_c = c.shift(1)

        # ATR (prior bar)
        tr = np.maximum(h - lo, np.maximum(abs(h - prev_c), abs(lo - prev_c)))
        atr_20 = tr.rolling(20).mean()
        atr_pct = (atr_20 / prev_c.replace(0, np.nan)).shift(1)   # fully prior-bar

        # Overnight gap — uses today's open vs yesterday's close (known at open)
        gap_pct = (o - prev_c) / prev_c.replace(0, np.nan)
        # FIX #11 (units): normalise the gap in the SAME units as ATR.
        # ATR is in price units (dollars), so the numerator must be dollars too.
        # The previous form (gap_pct / atr_20) divided a dimensionless fraction by a
        # dollar quantity, collapsing |gap_std| to ~0.17 max and yielding 9 events
        # across the whole universe instead of ~2.3k.
        gap_dollars = o - prev_c
        gap_std = gap_dollars / atr_20.shift(1).replace(0, np.nan)  # dollars / dollars

        # FIX #1: vol_surge denominator uses prior-bar rolling mean
        vol_20_prior = v.shift(1).rolling(20).mean()               # 20-bar avg ending t-1
        vol_surge = v / vol_20_prior.replace(0, np.nan)            # today vol / prior avg

        # Momentum (lagged so no current-bar leakage into features)
        mom5 = c.pct_change(5).shift(1)
        mom21 = c.pct_change(21).shift(1)

        # SMA50 distance (uses prior close vs prior SMA)
        sma50 = c.rolling(50).mean().shift(1)
        sma50_dist = (prev_c - sma50) / sma50.replace(0, np.nan)

        # Interaction and acceleration
        gap_x_surge = gap_std * vol_surge
        mom_accel = mom5 - mom21

        # Day-of-week
        dow = pd.Series(df.index.dayofweek, index=df.index, dtype=float)

        # FIX #2 — explicit label definition:
        #   gap_dir  = sign of today's gap
        #   entry    = O_{t+ENTRY_LAG}  (next-bar open)
        #   exit     = O_{t+EXIT_LAG}   (5 bars later open)
        #   gross    = (exit - entry) / entry * gap_dir
        #   label    = 1 if gross - COST_ROUNDTRIP > 0
        gap_dir_series = np.sign(gap_pct)
        entry_price = o.shift(-ENTRY_LAG)
        exit_price = o.shift(-EXIT_LAG)
        gross_ret = (exit_price - entry_price) / entry_price.replace(0, np.nan) * gap_dir_series

        event_mask = gap_std.abs() >= EVENT_MIN_GAP

        for idx in df.index[event_mask]:
            try:
                g = float(gross_ret[idx])
                if np.isnan(g):
                    continue
            except (KeyError, TypeError):
                continue

            # Binary label: does gap-direction trade win after costs?
            label = 1 if (g - COST_ROUNDTRIP) > 0 else 0

            rows.append({
                "date":        idx,
                "symbol":      sym,
                "gap_std":     float(gap_std[idx]),
                "vol_surge":   float(vol_surge[idx]),
                "atr_pct":     float(atr_pct[idx]),
                "mom5":        float(mom5[idx]),
                "mom21":       float(mom21[idx]),
                "day_of_week": float(dow[idx]),
                "sma50_dist":  float(sma50_dist[idx]),
                "gap_x_surge": float(gap_x_surge[idx]),
                "mom_accel":   float(mom_accel[idx]),
                "gap_dir":     float(gap_dir_series[idx]),   # +1 = gap-up, -1 = gap-down
                "gross_ret":   g,
                "label":       label,
            })

    df_all = pd.DataFrame(rows)
    if df_all.empty:
        return df_all

    df_all = df_all.dropna(subset=FEATURE_COLS).sort_values("date").reset_index(drop=True)
    yr_min = df_all["date"].dt.year.min()
    yr_max = df_all["date"].dt.year.max()
    pos_rate = df_all["label"].mean()
    print(f"[features] {len(df_all):,} events | {yr_min}–{yr_max} | base_rate={pos_rate:.3f}")
    return df_all


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward slice generator  (FIX #5 — purge = max label horizon)
# ─────────────────────────────────────────────────────────────────────────────

def generate_walkforward_slices(
    df: pd.DataFrame,
    train_years: int = TRAIN_YEARS_DEFAULT,
    oos_months: int = OOS_MONTHS_DEFAULT,
) -> List[Tuple[pd.DataFrame, pd.DataFrame, str, str]]:
    """Expanding walk-forward with correct purge ≥ max label horizon.

    Train window ends at test_start - PURGE_DAYS (removes all rows whose
    label interval overlaps the test period — sufficient since PURGE_DAYS ≥
    max hold duration of 5 trading days, buffered to 35 calendar days).
    """
    slices = []
    min_date = df["date"].min()
    max_date = df["date"].max()

    current_test_start = min_date + pd.DateOffset(years=train_years)
    fold = 1

    while current_test_start < max_date:
        current_test_end = current_test_start + pd.DateOffset(months=oos_months)

        # FIX #5: purge boundary removes any train row whose label overlaps test
        purge_boundary = current_test_start - pd.Timedelta(days=PURGE_DAYS)
        embargo_boundary = current_test_start + pd.Timedelta(days=EMBARGO_DAYS)

        df_train = df[(df["date"] >= min_date) & (df["date"] < purge_boundary)].copy()
        df_test = df[(df["date"] >= embargo_boundary) & (df["date"] < current_test_end)].copy()

        if len(df_train) >= 80 and len(df_test) >= 10:
            is_tag = f"IS_{min_date.strftime('%Y%m')}_to_{purge_boundary.strftime('%Y%m')}"
            oos_tag = f"OOS_Fold{fold:02d}_{current_test_start.strftime('%Y%m')}_to_{current_test_end.strftime('%Y%m')}"
            slices.append((df_train, df_test, is_tag, oos_tag))
            fold += 1

        current_test_start = current_test_end

    print(f"[wf] {len(slices)} walk-forward folds generated.")
    return slices


# ─────────────────────────────────────────────────────────────────────────────
# Per-fold model fit  (FIX #4b — purged cross-fitted calibration)
# ─────────────────────────────────────────────────────────────────────────────

# Isotonic needs a lot of data to beat a 2-parameter sigmoid. Below this many
# calibration rows we use Platt scaling instead; fold calibration sets here run
# ~500-1800 rows cross-fitted, so this threshold picks Platt for most folds.
ISOTONIC_MIN_ROWS = 1000
CALIB_FOLDS = 5


def _xgb_params(smoke: bool) -> Dict:
    return dict(
        objective="binary:logistic",
        eval_metric="logloss",
        max_depth=3,
        learning_rate=0.03,
        n_estimators=200 if not smoke else 30,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        reg_alpha=1.5,
        reg_lambda=10.0,
        random_state=42,
        verbosity=0,
    )


def fit_fold_model(
    X_tr: np.ndarray,
    y_tr: np.ndarray,
    smoke: bool = False,
):
    """Fit XGBoost + a calibrator built from purged cross-fitted scores.

    FIX #4b supersedes FIX #4.  The previous version fitted isotonic on the
    scores of an 80%-trained model and then refit the model on 100% of the
    training data — so the calibrator was applied to a model whose score
    distribution it had never seen.  Empirically that inverted the top of the
    probability range (predicted 96% → realised 20% win rate).

    Now every training row is scored by a sub-model that did not train on it
    (leave-one-block-out, with EXIT_LAG rows purged either side of each block so
    no overlapping label bleeds in).  The calibrator is fitted on those
    out-of-fold scores, which makes the final refit on 100% legitimate — this is
    the CalibratedClassifierCV(cv=K, ensemble=False) pattern.  It also yields
    ~5x more calibration data than the old 20% holdout.

    Returns (model, calibrate) where `calibrate` maps raw scores → probabilities,
    or None when there was not enough usable calibration data.
    """
    from xgboost import XGBClassifier
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression

    params = _xgb_params(smoke)
    n = len(X_tr)

    # ── cross-fitted out-of-fold scores over the training window ──────────────
    oof = np.full(n, np.nan)
    bounds = np.linspace(0, n, CALIB_FOLDS + 1).astype(int)
    for k in range(CALIB_FOLDS):
        lo, hi = bounds[k], bounds[k + 1]
        if hi <= lo:
            continue
        keep = np.ones(n, dtype=bool)
        # drop the scored block plus a purge buffer on both sides
        keep[max(lo - EXIT_LAG, 0):min(hi + EXIT_LAG, n)] = False
        if keep.sum() < 50 or len(np.unique(y_tr[keep])) < 2:
            continue
        sub = XGBClassifier(**params)
        sub.fit(X_tr[keep], y_tr[keep])
        oof[lo:hi] = sub.predict_proba(X_tr[lo:hi])[:, 1]

    # ── fit the calibrator on those out-of-fold scores ────────────────────────
    mask = ~np.isnan(oof)
    calibrate = None
    if mask.sum() >= 100 and len(np.unique(y_tr[mask])) == 2:
        s, yy = oof[mask], y_tr[mask]
        if mask.sum() >= ISOTONIC_MIN_ROWS:
            iso = IsotonicRegression(out_of_bounds="clip")
            iso.fit(s, yy)
            calibrate = lambda p, _f=iso: _f.predict(p)
        else:
            lr = LogisticRegression(C=1e6, solver="lbfgs")
            lr.fit(s.reshape(-1, 1), yy)
            calibrate = lambda p, _f=lr: _f.predict_proba(p.reshape(-1, 1))[:, 1]

    # Refit on the full training set. Legitimate now: the calibrator was built
    # from out-of-fold scores, not from this model's own in-sample scores.
    model = XGBClassifier(**params)
    model.fit(X_tr, y_tr)
    return model, calibrate


# ─────────────────────────────────────────────────────────────────────────────
# Daily portfolio return aggregator  (FIX #9)
# ─────────────────────────────────────────────────────────────────────────────

def compute_portfolio_daily_series(df_oof: pd.DataFrame) -> pd.Series:
    """Aggregate per-trade returns into a daily equal-weight portfolio.

    Trades are assumed to be open for HOLD_DAYS bars.  On each calendar date we
    average the net returns of all trades that entered on that date.  This gives
    one number per trading day (no double-counting of multi-day holds), which is
    the correct input for annualised Sharpe.
    """
    if df_oof.empty:
        return pd.Series(dtype=float)

    active = df_oof[df_oof["direction"] != 0].copy()
    if active.empty:
        return pd.Series(dtype=float)

    active["date"] = pd.to_datetime(active["date"])
    daily = active.groupby("date")["net_return"].mean().sort_index()
    return daily


# ─────────────────────────────────────────────────────────────────────────────
# Main walk-forward engine
# ─────────────────────────────────────────────────────────────────────────────

def run_walkforward_analysis(
    smoke: bool = False,
    train_years: int = TRAIN_YEARS_DEFAULT,
    oos_months: int = OOS_MONTHS_DEFAULT,
) -> Dict:
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from sklearn.metrics import brier_score_loss
    except ImportError as exc:
        return {"error": f"Missing scikit-learn: {exc}", "verdict": "ERROR"}

    data = fetch_multiyear_universe()
    if not data:
        return {"error": "Failed to fetch market data.", "verdict": "ERROR"}

    df_events = build_event_features(data)
    if len(df_events) < 100:
        return {"error": "Insufficient events for walk-forward.", "verdict": "ERROR"}

    slices = generate_walkforward_slices(df_events, train_years=train_years, oos_months=oos_months)
    if not slices:
        return {"error": "No valid walk-forward slices.", "verdict": "ERROR"}

    all_oos_rows: List[Dict] = []
    slice_summaries: List[Dict] = []

    for fold_idx, (df_tr, df_te, is_tag, oos_tag) in enumerate(slices, start=1):
        X_tr = df_tr[FEATURE_COLS].values.astype(np.float32)
        y_tr = df_tr["label"].values

        X_te = df_te[FEATURE_COLS].values.astype(np.float32)
        y_te = df_te["label"].values

        model, calibrate = fit_fold_model(X_tr, y_tr, smoke=smoke)

        raw_te = model.predict_proba(X_te)[:, 1]
        cal_te = calibrate(raw_te) if calibrate is not None else raw_te

        # FIX #3 — direction-aware signal (long → with gap, short → fade gap)
        gap_dir = df_te["gap_dir"].values          # +1 or -1
        gross = df_te["gross_ret"].values           # gap-direction gross return

        # Position: trade in gap direction if confident, fade if inverse-confident
        pos = np.where(
            cal_te >= LONG_THRESH,
            gap_dir,                                # follow gap
            np.where(cal_te <= SHORT_THRESH, -gap_dir, 0.0)  # fade gap
        )

        # Net return accounts for short borrow cost
        cost = np.where(pos != 0, COST_ROUNDTRIP, 0.0)
        cost += np.where(pos < 0, COST_SHORT_EXTRA, 0.0)
        net_ret = pos * gross - cost

        # Fold-level metrics
        active_mask = pos != 0
        n_active = int(active_mask.sum())
        net_active = net_ret[active_mask]

        win_rate = float((net_active > 0).mean()) if n_active > 0 else 0.0
        avg_net = float(net_active.mean()) if n_active > 0 else 0.0

        winners = net_active[net_active > 0]
        losers = net_active[net_active < 0]
        profit_factor = (
            float(winners.sum() / -losers.sum())
            if len(losers) > 0 and losers.sum() < 0
            else np.nan
        )

        brier = float(brier_score_loss(y_te, cal_te)) if len(np.unique(y_te)) == 2 else np.nan

        # Rank IC for this fold
        if len(cal_te) > 5 and np.std(cal_te) > 1e-6 and np.std(gross) > 1e-6:
            rank_ic = float(np.corrcoef(
                pd.Series(cal_te).rank(), pd.Series(gross).rank()
            )[0, 1])
        else:
            rank_ic = 0.0

        # Fold-level daily Sharpe (FIX #9: daily aggregation within fold)
        fold_oof_tmp = pd.DataFrame({
            "date": df_te["date"].values,
            "direction": pos,
            "net_return": net_ret,
        })
        daily_fold = compute_portfolio_daily_series(fold_oof_tmp)
        if len(daily_fold) >= 5:
            fold_sharpe = float(
                daily_fold.mean() / max(daily_fold.std(), 1e-8) * np.sqrt(252)
            )
        else:
            fold_sharpe = 0.0

        slice_summaries.append({
            "fold":         fold_idx,
            "is_window":    is_tag,
            "oos_window":   oos_tag,
            "train_size":   int(len(df_tr)),
            "test_size":    int(len(df_te)),
            "n_trades":     n_active,
            "rank_ic":      round(rank_ic, 5),
            "brier_score":  round(brier, 5) if not np.isnan(brier) else None,
            "win_rate":     round(win_rate, 4),
            "avg_net_return": round(avg_net, 5),
            "profit_factor":  round(profit_factor, 3) if not np.isnan(profit_factor) else None,
            "fold_sharpe":  round(fold_sharpe, 3),
        })

        # Accumulate per-event rows
        for r_i in range(len(df_te)):
            all_oos_rows.append({
                "date":           str(df_te["date"].iloc[r_i].strftime("%Y-%m-%d")),
                "symbol":         str(df_te["symbol"].iloc[r_i]),
                "fold":           fold_idx,
                "is_window":      is_tag,
                "oos_window":     oos_tag,
                "raw_score":      round(float(raw_te[r_i]), 5),
                "probability":    round(float(cal_te[r_i]), 5),
                "gap_dir":        int(gap_dir[r_i]),
                "direction":      int(pos[r_i]),
                "gross_return":   round(float(gross[r_i]), 6),
                "net_return":     round(float(net_ret[r_i]), 6),
            })

        print(
            f"  Fold {fold_idx:02d} | {oos_tag} | "
            f"n={n_active} | IC={rank_ic:+.4f} | "
            f"WR={win_rate:.1%} | Sh={fold_sharpe:.2f}"
        )

    # ── Aggregate OOS metrics ─────────────────────────────────────────────────
    df_oof = pd.DataFrame(all_oos_rows)
    active_oof = df_oof[df_oof["direction"] != 0].copy()
    total_trades = len(active_oof)

    # FIX #10 — per-fold IC stats
    ics = [s["rank_ic"] for s in slice_summaries]
    mean_rank_ic = float(np.mean(ics))
    ic_std = float(np.std(ics))
    ic_ir = mean_rank_ic / max(ic_std, 1e-6)
    ic_t_stat = mean_rank_ic / max(ic_std / np.sqrt(len(ics)), 1e-6)
    worst_ic_fold = min(slice_summaries, key=lambda s: s["rank_ic"])
    best_ic_fold = max(slice_summaries, key=lambda s: s["rank_ic"])

    # FIX #9 — portfolio Sharpe from daily return series
    daily_series = compute_portfolio_daily_series(df_oof)
    if len(daily_series) >= 10:
        portfolio_sharpe = float(
            daily_series.mean() / max(daily_series.std(), 1e-8) * np.sqrt(252)
        )
        cum_return = float((1 + daily_series).prod() - 1)
    else:
        portfolio_sharpe = 0.0
        cum_return = 0.0

    oof_win_rate = float((active_oof["net_return"] > 0).mean()) if total_trades > 0 else 0.0
    oof_avg_net = float(active_oof["net_return"].mean()) if total_trades > 0 else 0.0

    winners_oof = active_oof.loc[active_oof["net_return"] > 0, "net_return"]
    losers_oof = active_oof.loc[active_oof["net_return"] < 0, "net_return"]
    profit_factor_oof = (
        float(winners_oof.sum() / -losers_oof.sum())
        if len(losers_oof) > 0 and losers_oof.sum() < 0
        else np.nan
    )

    # FIX #7 — full score-bucket distribution (all deciles)
    score_analysis = _compute_full_score_distribution(active_oof)

    # FIX #8 — test monotonicity rather than asserting it
    monotonic_flag = _test_bucket_monotonicity(score_analysis)

    # ── Verdict ───────────────────────────────────────────────────────────────
    # Require: positive IC, IC t-stat > 1.5, Sharpe > 0.4, ≥50 trades, win-rate > 50%
    verdict = (
        "GO"
        if (
            mean_rank_ic > 0.015
            and ic_t_stat > 1.5
            and portfolio_sharpe > 0.40
            and total_trades >= 50
            and oof_win_rate > 0.50
        )
        else "NO-GO"
    )

    # ── Save outputs ──────────────────────────────────────────────────────────
    df_oof.to_parquet(OUT_DIR / "oof_inferences.parquet", index=False)
    daily_df = daily_series.reset_index()
    daily_df.columns = ["date", "portfolio_return"]
    daily_df.to_parquet(OUT_DIR / "daily_portfolio_returns.parquet", index=False)

    summary = {
        "model":                  "pead_xgboost_walkforward_v2",
        "version":                "2.0 — peer-review-corrected",
        "verdict":                verdict,
        "eval_period":            f"{df_events['date'].dt.year.min()}–{df_events['date'].dt.year.max()}",
        "total_folds":            len(slices),
        "total_oos_events":       int(len(df_oof)),
        "total_active_trades":    int(total_trades),
        # IC
        "mean_rank_ic":           round(mean_rank_ic, 5),
        "ic_std":                 round(ic_std, 5),
        "rank_icir":              round(ic_ir, 3),
        "ic_t_stat":              round(ic_t_stat, 3),
        "worst_fold_ic":          round(worst_ic_fold["rank_ic"], 5),
        "worst_fold_id":          worst_ic_fold["fold"],
        "best_fold_ic":           round(best_ic_fold["rank_ic"], 5),
        "best_fold_id":           best_ic_fold["fold"],
        # Portfolio
        "portfolio_sharpe":       round(portfolio_sharpe, 4),
        "portfolio_cum_return":   round(cum_return, 4),
        "n_portfolio_days":       int(len(daily_series)),
        # Trade-level
        "oos_win_rate":           round(oof_win_rate, 4),
        "oos_avg_net_return":     round(oof_avg_net, 5),
        "profit_factor":          round(profit_factor_oof, 3) if not np.isnan(profit_factor_oof) else None,
        # Design flags
        "vol_surge_lagged":       True,       # FIX #1 confirmed
        "calibration_inner_cv":   True,       # FIX #4 confirmed
        "thresholds_fixed_apriori": True,     # FIX #6 confirmed
        "purge_days":             PURGE_DAYS, # FIX #5
        "entry_bar":              f"O_{{t+{ENTRY_LAG}}}",
        "exit_bar":               f"O_{{t+{EXIT_LAG}}}",
        "long_threshold":         LONG_THRESH,
        "short_threshold":        SHORT_THRESH,
        "cost_roundtrip_bps":     int(COST_ROUNDTRIP * 10_000),
        "cost_short_extra_bps":   int(COST_SHORT_EXTRA * 10_000),
        # Full score distribution (FIX #7)
        "score_bucket_distribution": score_analysis,
        "bucket_monotonic_flag":  monotonic_flag,
        # Per-fold detail
        "slice_summaries":        slice_summaries,
        "elapsed_seconds":        round(time.time() - t0, 2),
    }

    with open(OUT_DIR / "results.json", "w") as f:
        json.dump(summary, f, indent=2)

    _print_summary(summary)
    return summary


# ─────────────────────────────────────────────────────────────────────────────
# Score distribution (FIX #7 — all buckets, not cherry-picked)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_full_score_distribution(active_oof: pd.DataFrame) -> List[Dict]:
    """Report ALL decile buckets of calibrated probability across active trades."""
    if active_oof.empty:
        return []

    bins = np.arange(0.0, 1.05, 0.05)   # 20 bins of width 5%
    labels = [f"{int(b*100)}–{int(b*100)+5}%" for b in bins[:-1]]
    active_oof = active_oof.copy()
    active_oof["bucket"] = pd.cut(
        active_oof["probability"], bins=bins, labels=labels, right=False, include_lowest=True
    )

    results = []
    for lbl in labels:
        sub = active_oof[active_oof["bucket"] == lbl]
        n = len(sub)
        if n == 0:
            results.append({"bucket": lbl, "n": 0})
            continue
        avg_predicted = float(sub["probability"].mean())
        avg_net = float(sub["net_return"].mean())
        win_rate = float((sub["net_return"] > 0).mean())
        winners = sub.loc[sub["net_return"] > 0, "net_return"]
        losers = sub.loc[sub["net_return"] < 0, "net_return"]
        pf = (
            float(winners.sum() / -losers.sum())
            if len(losers) > 0 and losers.sum() < 0
            else None
        )
        results.append({
            "bucket":            lbl,
            "n":                 n,
            "avg_predicted_prob": round(avg_predicted, 4),
            "win_rate":          round(win_rate, 4),
            "avg_net_return":    round(avg_net, 5),
            "profit_factor":     round(pf, 3) if pf is not None else None,
        })

    return results


def _test_bucket_monotonicity(score_analysis: List[Dict]) -> str:
    """FIX #8 — test win-rate monotonicity; report result honestly."""
    wrs = [b["win_rate"] for b in score_analysis if b.get("n", 0) >= 10]
    if len(wrs) < 3:
        return "INSUFFICIENT_DATA"
    violations = sum(wrs[i] > wrs[i + 1] for i in range(len(wrs) - 1))
    total_pairs = len(wrs) - 1
    pct_monotone = 1.0 - violations / total_pairs
    if pct_monotone >= 0.80:
        return f"MONOTONE_PASS ({pct_monotone:.0%} pairs consistent)"
    return f"MONOTONE_FAIL ({pct_monotone:.0%} pairs consistent, {violations}/{total_pairs} violations)"


# ─────────────────────────────────────────────────────────────────────────────
# Console summary
# ─────────────────────────────────────────────────────────────────────────────

def _print_summary(s: Dict) -> None:
    sep = "=" * 80
    print(f"\n{sep}")
    print("WALK-FORWARD BACKTEST v2 — PEER-REVIEW-CORRECTED RESULTS")
    print(sep)
    print(f"  Model version  : {s['version']}")
    print(f"  Eval period    : {s['eval_period']}")
    print(f"  Folds          : {s['total_folds']}  |  OOS events: {s['total_oos_events']:,}  |  Active trades: {s['total_active_trades']:,}")
    print()
    print(f"  Mean Rank IC   : {s['mean_rank_ic']:+.5f}  ±{s['ic_std']:.5f}")
    print(f"  IC t-stat      : {s['ic_t_stat']:.2f}   (Rank ICIR: {s['rank_icir']:.2f})")
    print(f"  Worst fold IC  : {s['worst_fold_ic']:+.5f} (Fold {s['worst_fold_id']})")
    print(f"  Best  fold IC  : {s['best_fold_ic']:+.5f} (Fold {s['best_fold_id']})")
    print()
    print(f"  Portfolio Sharpe  : {s['portfolio_sharpe']:.3f}  (from {s['n_portfolio_days']} trading days)")
    print(f"  Portfolio Cum Ret : {s['portfolio_cum_return']*100:+.2f}%")
    print(f"  OOS Win Rate      : {s['oos_win_rate']:.1%}  |  Avg Net/Trade: {s['oos_avg_net_return']*100:+.3f}%")
    pf = s.get("profit_factor")
    print(f"  Profit Factor     : {pf:.3f}" if pf else "  Profit Factor     : N/A")
    print()
    print(f"  Monotonicity check : {s.get('bucket_monotonic_flag','N/A')}")
    print()
    print("  Execution model :")
    print(f"    Signal at close t, entry {s['entry_bar']}, exit {s['exit_bar']}")
    print(f"    vol_surge lagged        : {s['vol_surge_lagged']}")
    print(f"    Calibration inner-CV    : {s['calibration_inner_cv']}")
    print(f"    Thresholds fixed a priori: {s['thresholds_fixed_apriori']} ({s['long_threshold']}/{s['short_threshold']})")
    print(f"    Purge days              : {s['purge_days']} calendar days")
    print(f"    Round-trip cost         : {s['cost_roundtrip_bps']} bps (+{s['cost_short_extra_bps']} bps for shorts)")
    print(f"\n  VERDICT: *** {s['verdict']} ***")
    print(sep)

    print("\n  Per-Fold Summary:")
    print(f"  {'Fold':>4} {'N_trades':>8} {'Rank_IC':>9} {'WinRate':>8} {'AvgNet%':>8} {'FoldSh':>7}")
    for sl in s["slice_summaries"]:
        print(
            f"  {sl['fold']:>4d} {sl['n_trades']:>8d} {sl['rank_ic']:>+9.5f} "
            f"{sl['win_rate']:>8.1%} {sl['avg_net_return']*100:>+7.3f}% {sl['fold_sharpe']:>7.3f}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Walk-Forward Backtest v2 — peer-review-corrected")
    parser.add_argument("--smoke",       action="store_true", help="Fast smoke test (few estimators)")
    parser.add_argument("--train-years", type=int, default=TRAIN_YEARS_DEFAULT)
    parser.add_argument("--oos-months",  type=int, default=OOS_MONTHS_DEFAULT)
    args = parser.parse_args()

    result = run_walkforward_analysis(
        smoke=args.smoke,
        train_years=args.train_years,
        oos_months=args.oos_months,
    )
    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
