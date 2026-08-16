#!/usr/bin/env python3
"""xs_v3_live_signals.py — Forward paper-trading signal generator for the FROZEN
xs_v3 configuration. This is a SIGNAL GENERATOR + LOGGER ONLY.

It does not place orders, does not call any network/broker API, and contains
no tuning, threshold search, or model selection. Backtesting for this
strategy is DONE — the holdout is burned (see
edge/runs/xs_v3/holdout_final.json and edge/runs/xs_v3/DECISION_RECORD.md).
This script's only job is to generate today's target portfolio under the
frozen configuration and log it, so real forward evidence can accumulate.

=== FROZEN CONFIG ===
See the CONFIG dict below. These values are frozen as of 2026-08-01 per
edge/runs/xs_v3/DECISION_RECORD.md (the pre-registered SECONDARY
configuration from edge/runs/xs_v3/holdout_final.json: model signal,
min_hold_days buffering, entry_pct=0.10). Do not change any value in CONFIG
without running a fresh, pre-registered holdout evaluation first.

=== USAGE ===
    python3 edge/tools/xs_v3_live_signals.py                      # as-of = latest date in data
    python3 edge/tools/xs_v3_live_signals.py --asof 2026-07-15    # as-of a specific (historical) date
    python3 edge/tools/xs_v3_live_signals.py --asof 2026-07-15 --retrain
    python3 edge/tools/xs_v3_live_signals.py --evaluate           # report realized paper P&L to date

=== SAFETY ===
This script writes ONLY inside edge/runs/xs_v3/live/. It reads price data
from edge/data/1d_wide/ and writes nowhere else. No network calls. No order
placement.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "edge" / "data" / "1d_wide"
XS_V3_DIR = ROOT / "edge" / "runs" / "xs_v3"
LIVE_DIR = XS_V3_DIR / "live"                    # the ONLY directory this script ever writes to
POSITIONS_PATH = LIVE_DIR / "positions.json"
SIGNAL_LOG_PATH = LIVE_DIR / "signal_log.parquet"

# ─────────────────────────────────────────────────────────────────────────────
# FROZEN CONFIG — frozen as of 2026-08-01 per edge/runs/xs_v3/DECISION_RECORD.md.
# This is the pre-registered SECONDARY configuration from
# edge/runs/xs_v3/holdout_final.json (the only cell whose holdout result was
# examined and adopted). DO NOT CHANGE ANY VALUE HERE WITHOUT A FRESH,
# PRE-REGISTERED HOLDOUT EVALUATION. This script must not parameterize these
# for search — there is no CLI flag to override CONFIG.
# ─────────────────────────────────────────────────────────────────────────────
CONFIG = dict(
    feature_cols=[
        "mom21", "mom63", "mom126_21", "rev5", "vol20", "atr_pct", "gap",
        "gap_atr", "vol_surge", "dollar_vol", "dist_sma50", "dist_high252", "illiq",
    ],
    xgb_params=dict(
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
    ),
    entry_pct=0.10,             # top/bottom decile by cross-sectional predicted-return rank
    exit_pct=0.10,              # no separate rank-based exit band — min_hold_days is the only buffer
    min_hold_days=20,           # a name cannot be exited before 20 trading days from its entry
    hold_days_horizon=5,        # the feature/target timing horizon the model was trained around
    entry_lag=1,                # entry at O_{t+1}
    exit_lag=6,                 # exit at O_{t+6} (5-bar hold horizon baked into training labels)
    cost_bps_round_trip=10,     # REPORTING ONLY — both-legs (net_gross2) convention
    return_hygiene_threshold=0.50,   # |1-day return| > this -> treated as bad print, masked to NaN
    min_rows_per_symbol=400,
    min_symbols_per_date=50,
    model_cache_max_age_days=21,
    # Reference Sharpe for the statistical-power note in --evaluate, taken
    # verbatim from edge/runs/xs_v3/holdout_final.json, SECONDARY config,
    # holdout period, net@10bps Sharpe (0.3794, printed here as 0.379 to
    # match the pre-registration report). Hardcoded (not re-read at runtime)
    # so this script has no runtime dependency on that file.
    frozen_holdout_reference_sharpe=0.3794,
    frozen_as_of="2026-08-01",
    decision_record="edge/runs/xs_v3/DECISION_RECORD.md",
    pre_registration_source="edge/runs/xs_v3/holdout_final.json (label=SECONDARY)",
)


# ─────────────────────────────────────────────────────────────────────────────
# Feature / target construction — IDENTICAL to run_xs_alpha_v3.py.
# Duplicated (not imported) to keep this script standalone and self-contained.
# ─────────────────────────────────────────────────────────────────────────────

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """13 raw (non-ranked) features for a single symbol. Trailing-only —
    every quantity uses only the current bar or bars strictly earlier."""
    c = df["close"]; o = df["open"]; h = df["high"]; lo = df["low"]; v = df["volume"]
    prev_c = c.shift(1)

    mom21 = c.pct_change(21)
    mom63 = c.pct_change(63)
    mom126_21 = c.shift(21) / c.shift(126) - 1.0
    rev5 = c.pct_change(5)
    vol20 = c.pct_change().rolling(20).std()

    tr_components = pd.concat([h - lo, (h - prev_c).abs(), (lo - prev_c).abs()], axis=1)
    tr = tr_components.max(axis=1, skipna=False)
    atr_pct = tr.rolling(20).mean() / c

    gap = (o - prev_c) / prev_c.replace(0, np.nan)
    gap_atr = (gap / atr_pct.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    vol_20_prior = v.shift(1).rolling(20).mean()
    vol_surge = v / vol_20_prior.replace(0, np.nan)

    dollar = (c * v).clip(lower=1e-9)
    dollar_vol = np.log(dollar).rolling(20).mean()

    sma50 = c.rolling(50).mean()
    dist_sma50 = c / sma50.replace(0, np.nan) - 1.0

    high252 = c.rolling(252).max()
    dist_high252 = c / high252.replace(0, np.nan) - 1.0

    illiq_daily = c.pct_change().abs() / dollar
    illiq = illiq_daily.rolling(20).mean()

    return pd.DataFrame(
        {
            "mom21": mom21, "mom63": mom63, "mom126_21": mom126_21, "rev5": rev5,
            "vol20": vol20, "atr_pct": atr_pct, "gap": gap, "gap_atr": gap_atr,
            "vol_surge": vol_surge, "dollar_vol": dollar_vol, "dist_sma50": dist_sma50,
            "dist_high252": dist_high252, "illiq": illiq,
        },
        index=df.index,
    )


def build_target(open_s: pd.Series) -> pd.Series:
    """fwd_ret = O_{t+6}/O_{t+1} - 1. Uses forward shifts DELIBERATELY (it is
    the training label, not a feature)."""
    entry = open_s.shift(-CONFIG["entry_lag"])
    exit_ = open_s.shift(-CONFIG["exit_lag"])
    return exit_ / entry.replace(0, np.nan) - 1.0


def clean_extreme_returns(returns, threshold: float = None) -> Tuple[object, int]:
    threshold = CONFIG["return_hygiene_threshold"] if threshold is None else threshold
    bad = returns.abs() > threshold
    n_masked = int(np.asarray(bad).sum())
    return returns.mask(bad), n_masked


# ─────────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────────

def load_panel(truncate_at: Optional[pd.Timestamp]) -> Tuple[pd.DataFrame, Optional[pd.Timestamp]]:
    """Load all symbols, build features + target.

    If `truncate_at` is given (an explicit --asof), every file is truncated
    to `index <= truncate_at` IMMEDIATELY on read, before anything else
    touches it — this makes a historical --asof run a true "what would we
    have known as of that date" simulation rather than merely relying on
    features being trailing-only. If `truncate_at` is None (no --asof given),
    the full available range is loaded and the caller determines as_of as the
    latest date present.
    """
    files = sorted(DATA_DIR.glob("*.parquet"))
    rows_frames: List[pd.DataFrame] = []
    n_kept, n_dropped_short = 0, 0

    for p in files:
        sym = p.stem
        df = pd.read_parquet(p)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        if truncate_at is not None:
            df = df[df.index <= truncate_at]
        if len(df) < CONFIG["min_rows_per_symbol"]:
            n_dropped_short += 1
            continue

        feats = build_features(df)
        fwd_ret_raw = build_target(df["open"])
        fwd_ret, _ = clean_extreme_returns(fwd_ret_raw)

        sym_df = feats.copy()
        sym_df["open"] = df["open"]
        sym_df["fwd_ret"] = fwd_ret
        sym_df["date"] = df.index
        sym_df["symbol"] = sym
        sym_df = sym_df.reset_index(drop=True)
        rows_frames.append(sym_df)
        n_kept += 1

    panel_raw = pd.concat(rows_frames, ignore_index=True)
    panel_raw["date"] = pd.to_datetime(panel_raw["date"])
    print(f"[data] {n_kept} symbols loaded ({n_dropped_short} dropped for <{CONFIG['min_rows_per_symbol']} rows), "
          f"{len(panel_raw):,} rows, {panel_raw['date'].min().date()}..{panel_raw['date'].max().date()}")
    return panel_raw, None


def rank_normalize(panel_raw: pd.DataFrame) -> pd.DataFrame:
    date_counts = panel_raw.groupby("date").size()
    qualifying_dates = date_counts[date_counts >= CONFIG["min_symbols_per_date"]].index
    panel = panel_raw[panel_raw["date"].isin(qualifying_dates)].copy()
    for feat in CONFIG["feature_cols"]:
        ranked = panel.groupby("date")[feat].rank(pct=True) - 0.5
        panel[feat] = ranked.fillna(0.0)
    panel["y"] = panel["fwd_ret"] - panel.groupby("date")["fwd_ret"].transform("mean")
    return panel


# ─────────────────────────────────────────────────────────────────────────────
# Model cache
# ─────────────────────────────────────────────────────────────────────────────

def get_or_train_model(train_df: pd.DataFrame, train_max_date: pd.Timestamp, retrain: bool):
    from xgboost import XGBRegressor

    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = LIVE_DIR / f"model_{train_max_date.strftime('%Y%m%d')}.json"

    use_cache = False
    if cache_path.exists() and not retrain:
        age_days = (time.time() - cache_path.stat().st_mtime) / 86400.0
        if age_days <= CONFIG["model_cache_max_age_days"]:
            use_cache = True
        else:
            print(f"[model] cache {cache_path.name} is {age_days:.1f} days old "
                  f"(> {CONFIG['model_cache_max_age_days']}) — retraining.")

    if use_cache:
        model = XGBRegressor(**CONFIG["xgb_params"])
        model.load_model(str(cache_path))
        print(f"[model] reusing cached model {cache_path.name} (trained through {train_max_date.date()}).")
        return model, True

    X = train_df[CONFIG["feature_cols"]].values.astype(np.float32)
    y = train_df["y"].values.astype(np.float64)
    model = XGBRegressor(**CONFIG["xgb_params"])
    model.fit(X, y)
    model.save_model(str(cache_path))
    print(f"[model] trained fresh model on {len(train_df):,} rows through {train_max_date.date()}, "
          f"cached to {cache_path.name}.")
    return model, False


# ─────────────────────────────────────────────────────────────────────────────
# Persistent position state
# ─────────────────────────────────────────────────────────────────────────────

def load_positions() -> Dict:
    if not POSITIONS_PATH.exists():
        return {"last_asof": None, "positions": {}}
    with open(POSITIONS_PATH) as fh:
        return json.load(fh)


def already_processed(as_of: pd.Timestamp) -> bool:
    """Source of truth for idempotence: the append-only signal_log."""
    if not SIGNAL_LOG_PATH.exists():
        return False
    existing = pd.read_parquet(SIGNAL_LOG_PATH, columns=["date"])
    existing_dates = pd.to_datetime(existing["date"]).unique()
    return np.datetime64(as_of) in existing_dates


def rebalance(
    held: Dict[str, Dict], ranks: pd.Series, as_of: pd.Timestamp, master_calendar: pd.DatetimeIndex,
) -> Tuple[Dict[str, Dict], List[Dict]]:
    """Apply min_hold_days-buffered rebalance. Returns (new_held, log_rows)."""
    entry_pct = CONFIG["entry_pct"]
    exit_pct = CONFIG["exit_pct"]
    min_hold = CONFIG["min_hold_days"]
    entry_thresh_long = 1.0 - entry_pct
    exit_thresh_long = 1.0 - exit_pct
    entry_thresh_short = entry_pct
    exit_thresh_short = exit_pct

    as_of_pos = master_calendar.get_indexer([as_of])[0]

    def days_held(entry_date_str: str) -> int:
        entry_pos = master_calendar.get_indexer([pd.Timestamp(entry_date_str)])[0]
        if entry_pos == -1:
            return 10**9   # entry date not in current calendar (shouldn't happen) -> treat as long-held/unlocked
        return as_of_pos - entry_pos

    new_held: Dict[str, Dict] = {}
    forced_closes: List[str] = []

    for sym, pos in held.items():
        if sym not in ranks.index:
            # Symbol has no data as of today (delisted / data gap). Conservative
            # choice: force-close it (can't mark or hold an unscoreable name),
            # even if still within its lock window. This is documented as the
            # conservative pick for an ambiguous edge case.
            forced_closes.append(sym)
            continue
        dh = days_held(pos["entry_date"])
        locked = dh < min_hold
        r = ranks[sym]
        if pos["side"] == "long":
            survives = locked or (r >= exit_thresh_long)
        else:
            survives = locked or (r <= exit_thresh_short)
        if survives:
            new_held[sym] = {"side": pos["side"], "entry_date": pos["entry_date"]}

    # New entries: top/bottom decile, not already held (after exits applied above).
    for sym in ranks.index[ranks >= entry_thresh_long]:
        if sym not in new_held:
            new_held[sym] = {"side": "long", "entry_date": str(as_of.date())}
    for sym in ranks.index[ranks <= entry_thresh_short]:
        if sym not in new_held:
            new_held[sym] = {"side": "short", "entry_date": str(as_of.date())}

    n_long = sum(1 for p in new_held.values() if p["side"] == "long")
    n_short = sum(1 for p in new_held.values() if p["side"] == "short")

    for sym, pos in new_held.items():
        w = (1.0 / n_long) if pos["side"] == "long" else (-1.0 / n_short)
        pos["weight"] = w

    old_syms = set(held.keys())
    new_syms = set(new_held.keys())
    log_rows = []
    for sym in sorted(old_syms | new_syms):
        was_held = sym in held
        is_held = sym in new_held
        if not was_held and is_held:
            action = "open"
        elif was_held and not is_held:
            action = "close"
        elif was_held and is_held:
            action = "hold"
        else:
            continue
        side = new_held[sym]["side"] if is_held else held[sym]["side"]
        weight = new_held[sym]["weight"] if is_held else 0.0
        y_pred = float(ranks.get(sym, np.nan)) if sym in ranks.index else np.nan
        log_rows.append({
            "date": as_of, "symbol": sym, "side": side, "weight": weight,
            "y_pred_rank": y_pred, "action": action,
        })

    if forced_closes:
        print(f"[WARNING] {len(forced_closes)} held symbol(s) missing from today's universe; "
              f"force-closed despite min_hold lock (conservative choice): {forced_closes}")

    return new_held, log_rows


# ─────────────────────────────────────────────────────────────────────────────
# Signal generation entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_signals(asof_arg: Optional[str], retrain: bool) -> None:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)

    explicit_asof = pd.Timestamp(asof_arg) if asof_arg else None
    panel_raw, _ = load_panel(truncate_at=explicit_asof)
    as_of = explicit_asof if explicit_asof is not None else pd.Timestamp(panel_raw["date"].max())

    # Idempotence check — as early as possible, before any expensive work.
    if already_processed(as_of):
        print(f"[no-op] signal_log.parquet already has rows for {as_of.date()}. "
              f"Idempotence guard: no state, log, or file changes made. Exiting.")
        return

    panel = rank_normalize(panel_raw)
    master_calendar = pd.DatetimeIndex(sorted(panel_raw["date"].unique()))

    if as_of not in set(panel_raw["date"]):
        print(f"ERROR: {as_of.date()} is not a trading date present in the data "
              f"(check for weekend/holiday or a date past the available range).", file=sys.stderr)
        sys.exit(1)

    train_df = panel[(panel["date"] < as_of) & panel["fwd_ret"].notna() & panel["y"].notna()].copy()
    if train_df.empty:
        print(f"ERROR: no valid training rows with date < {as_of.date()}.", file=sys.stderr)
        sys.exit(1)
    train_max_date = pd.Timestamp(train_df["date"].max())
    assert train_max_date < as_of, (
        f"Training data max date {train_max_date.date()} is not < as-of date {as_of.date()} — aborting."
    )
    print(f"[timing] training data max date {train_max_date.date()} < as-of {as_of.date()} — OK.")

    score_df = panel[panel["date"] == as_of].copy()
    if len(score_df) < CONFIG["min_symbols_per_date"]:
        print(f"ERROR: only {len(score_df)} symbols available on {as_of.date()} "
              f"(< {CONFIG['min_symbols_per_date']} required).", file=sys.stderr)
        sys.exit(1)

    model, was_cached = get_or_train_model(train_df, train_max_date, retrain)

    X_score = score_df[CONFIG["feature_cols"]].values.astype(np.float32)
    y_pred = model.predict(X_score)
    pred_series = pd.Series(y_pred, index=score_df["symbol"].values)
    ranks = pred_series.rank(pct=True)   # 0..1, used for entry/exit-band decisions

    state = load_positions()
    held = state.get("positions", {})
    old_weights = {s: p.get("weight", 0.0) for s, p in held.items()}

    new_held, log_rows = rebalance(held, ranks, as_of, master_calendar)

    all_syms = set(old_weights) | set(new_held)
    turnover_today = sum(
        abs(new_held.get(s, {}).get("weight", 0.0) - old_weights.get(s, 0.0)) for s in all_syms
    ) / 2.0

    n_long = sum(1 for p in new_held.values() if p["side"] == "long")
    n_short = sum(1 for p in new_held.values() if p["side"] == "short")
    n_opened = sum(1 for r in log_rows if r["action"] == "open")
    n_closed = sum(1 for r in log_rows if r["action"] == "close")

    # ── Write outputs (live/ subdirectory only) ────────────────────────────
    new_state = {
        "last_asof": str(as_of.date()),
        "positions": {
            sym: {"side": p["side"], "weight": round(p["weight"], 6), "entry_date": p["entry_date"]}
            for sym, p in new_held.items()
        },
    }
    with open(POSITIONS_PATH, "w") as fh:
        json.dump(new_state, fh, indent=2)

    log_df = pd.DataFrame(log_rows)
    log_df["date"] = pd.to_datetime(log_df["date"])
    log_df["weight"] = log_df["weight"].round(6)

    csv_path = LIVE_DIR / f"signals_{as_of.date()}.csv"
    log_df.rename(columns={"y_pred_rank": "y_pred"}).to_csv(csv_path, index=False)

    if SIGNAL_LOG_PATH.exists():
        existing = pd.read_parquet(SIGNAL_LOG_PATH)
        combined = pd.concat([existing, log_df], ignore_index=True)
    else:
        combined = log_df
    combined.to_parquet(SIGNAL_LOG_PATH, index=False)

    # ── Human summary ───────────────────────────────────────────────────────
    top_longs = pred_series.reindex(
        [s for s in new_held if new_held[s]["side"] == "long"]
    ).sort_values(ascending=False).head(5)
    top_shorts = pred_series.reindex(
        [s for s in new_held if new_held[s]["side"] == "short"]
    ).sort_values(ascending=True).head(5)

    print(f"\n{'=' * 72}")
    print(f"xs_v3 LIVE SIGNALS — as-of {as_of.date()}")
    print(f"{'=' * 72}")
    print(f"  Model train max date : {train_max_date.date()}  (cached={was_cached})")
    print(f"  n_long / n_short     : {n_long} / {n_short}")
    print(f"  n_opened / n_closed  : {n_opened} / {n_closed}")
    print(f"  Turnover vs prev day : {turnover_today:.4f}")
    print("  Top 5 longs (y_pred) : " + ", ".join(f"{s}={v:+.5f}" for s, v in top_longs.items()))
    print("  Top 5 shorts (y_pred): " + ", ".join(f"{s}={v:+.5f}" for s, v in top_shorts.items()))
    print(f"  Wrote: {POSITIONS_PATH.relative_to(ROOT)}")
    print(f"  Wrote: {csv_path.relative_to(ROOT)}")
    print(f"  Wrote: {SIGNAL_LOG_PATH.relative_to(ROOT)}  ({len(combined):,} total rows)")
    print(f"{'=' * 72}")


# ─────────────────────────────────────────────────────────────────────────────
# Evaluate mode — realized paper P&L from signal_log.parquet
# ─────────────────────────────────────────────────────────────────────────────

def evaluate() -> None:
    if not SIGNAL_LOG_PATH.exists():
        print("No signal_log.parquet found yet — no live evidence has been generated. Run without "
              "--evaluate first to produce signals.")
        return

    log = pd.read_parquet(SIGNAL_LOG_PATH)
    log["date"] = pd.to_datetime(log["date"])
    signal_dates = sorted(log["date"].unique())
    symbols = sorted(log["symbol"].unique())

    open_frames = []
    for sym in symbols:
        p = DATA_DIR / f"{sym}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df.columns = [c.lower() for c in df.columns]
        o = df["open"].copy(); o.name = sym
        open_frames.append(o)
    open_wide = pd.concat(open_frames, axis=1).sort_index()
    open_wide.index = pd.to_datetime(open_wide.index)
    master_calendar = open_wide.index

    ret1d_wide_raw = open_wide.shift(-1) / open_wide - 1.0
    ret1d_wide, n_bad = clean_extreme_returns(ret1d_wide_raw)
    print(f"[return-hygiene] masked {n_bad} realized 1-day returns with "
          f"|return| > {CONFIG['return_hygiene_threshold']:.0%}.")

    # Wide weight matrix (only 'open'/'hold' rows carry live weight going forward;
    # 'close' rows already carry weight=0.0 by construction).
    w_long = log.pivot_table(index="date", columns="symbol", values="weight", aggfunc="last").fillna(0.0)
    w_full = w_long.reindex(columns=open_wide.columns).fillna(0.0)

    records = []
    for i, t in enumerate(signal_dates):
        pos_t = master_calendar.get_indexer([t])
        pos_t = int(pos_t[0]) if len(pos_t) and pos_t[0] != -1 else None
        if pos_t is None or pos_t + 1 >= len(master_calendar):
            continue
        entry_date = master_calendar[pos_t + 1]
        if entry_date not in ret1d_wide.index:
            continue
        w_t = w_full.loc[t]
        ret_today = ret1d_wide.loc[entry_date].reindex(w_t.index).fillna(0.0)
        gross = float((w_t * ret_today).sum())

        if i == 0:
            turnover = float(w_t.abs().sum()) / 2.0
        else:
            w_prev = w_full.loc[signal_dates[i - 1]]
            turnover = float((w_t - w_prev).abs().sum()) / 2.0

        records.append({"date": entry_date, "gross": gross, "turnover": turnover})

    if not records:
        print("No realized (date, return) pairs yet — the most recent signal date's forward "
              "return isn't available (either no next trading day in price data, or too recent).")
        return

    daily = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    rate = CONFIG["cost_bps_round_trip"] / 10_000.0
    daily["net10bps"] = daily["gross"] - rate * daily["turnover"]

    def stats(series: pd.Series, label: str) -> Dict:
        n = len(series)
        if n < 2:
            return {f"cum_return_{label}": float(series.sum()) if n else 0.0,
                    f"sharpe_{label}": 0.0, f"max_drawdown_{label}": 0.0, f"hit_rate_{label}": 0.0}
        vals = series.values
        std = np.std(vals, ddof=1)
        sharpe = float(np.mean(vals) / std * np.sqrt(252)) if std > 1e-12 else 0.0
        cum = np.cumprod(1.0 + vals)
        cum_return = float(cum[-1] - 1.0)
        running_max = np.maximum.accumulate(cum)
        max_dd = float((cum / running_max - 1.0).min())
        hit_rate = float((vals > 0).mean())
        return {
            f"cum_return_{label}": round(cum_return, 6),
            f"sharpe_{label}": round(sharpe, 4),
            f"max_drawdown_{label}": round(max_dd, 4),
            f"hit_rate_{label}": round(hit_rate, 4),
        }

    gross_stats = stats(daily["gross"], "gross")
    net_stats = stats(daily["net10bps"], "net10bps")
    n_days = len(daily)

    ref_sharpe = CONFIG["frozen_holdout_reference_sharpe"]
    years_needed_t2 = (2.0 / ref_sharpe) ** 2

    print(f"\n{'=' * 72}")
    print("xs_v3 LIVE PAPER P&L — realized evidence to date")
    print(f"{'=' * 72}")
    print(f"  n_days (realized)      : {n_days}")
    print(f"  Date range             : {daily['date'].min().date()} .. {daily['date'].max().date()}")
    print(f"  Cum return  gross      : {gross_stats['cum_return_gross']*100:+.3f}%")
    print(f"  Cum return  net@10bps  : {net_stats['cum_return_net10bps']*100:+.3f}%")
    print(f"  Ann. Sharpe gross      : {gross_stats['sharpe_gross']:+.4f}")
    print(f"  Ann. Sharpe net@10bps  : {net_stats['sharpe_net10bps']:+.4f}")
    print(f"  Max drawdown gross     : {gross_stats['max_drawdown_gross']*100:+.3f}%")
    print(f"  Max drawdown net@10bps : {net_stats['max_drawdown_net10bps']*100:+.3f}%")
    print(f"  Hit rate    gross      : {gross_stats['hit_rate_gross']:.1%}")
    print(f"  Hit rate    net@10bps  : {net_stats['hit_rate_net10bps']:.1%}")
    print()
    print(f"  LIVE EVIDENCE ACCUMULATED: {n_days} trading day(s).")
    print(f"  STATISTICAL POWER NOTE: the pre-registered holdout Sharpe for this frozen "
          f"configuration was {ref_sharpe:.3f} (net@10bps). Under the standard IID approximation "
          f"(t-stat ~= Sharpe_annualized * sqrt(years)), distinguishing a Sharpe of {ref_sharpe:.3f} "
          f"from zero at t=2 would require roughly {years_needed_t2:.1f} years of daily data "
          f"(~{years_needed_t2*252:.0f} trading days). {n_days} day(s) of live evidence is "
          f"nowhere near sufficient to confirm or refute the strategy — this P&L is reported "
          f"for record-keeping, not as a verdict.")
    print(f"{'=' * 72}")

    out = {
        "n_days": n_days,
        "date_range": [str(daily["date"].min().date()), str(daily["date"].max().date())],
        "gross": gross_stats,
        "net10bps": net_stats,
        "frozen_holdout_reference_sharpe": ref_sharpe,
        "years_needed_to_distinguish_from_zero_at_t2": round(years_needed_t2, 2),
        "note": "Reported honestly regardless of sign. Live evidence sample size is far below "
                "what's needed for statistical confirmation; see console note.",
    }
    eval_path = LIVE_DIR / "evaluate_report.json"
    with open(eval_path, "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print(f"Wrote {eval_path.relative_to(ROOT)}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="xs_v3 frozen-config live paper-trading signal generator")
    parser.add_argument("--asof", type=str, default=None, help="YYYY-MM-DD; default = latest date in data")
    parser.add_argument("--retrain", action="store_true", help="Force retrain even if a fresh cache exists")
    parser.add_argument("--evaluate", action="store_true", help="Report realized paper P&L from signal_log.parquet")
    args = parser.parse_args(argv)

    if args.evaluate:
        evaluate()
        return 0

    generate_signals(args.asof, args.retrain)
    return 0


if __name__ == "__main__":
    sys.exit(main())
