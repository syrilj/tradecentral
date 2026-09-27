#!/usr/bin/env python3
"""tools/backtest_drift_tab.py — Drift Tab Empirical & Microstructure Backtest Engine.

Backtests the core analytics and execution strategies surfaced in TradeCentral's
Drift Tab (DriftView.vue, daily_plays/options_intelligence.py, and
research/systematic_execution.py):

  Tier 1 — Empirical Snapshot Backtest:
    Evaluates point-in-time option chain snapshots (BS charm flow by strike,
    dealer pressure gauge, GEX walls) against forward 1d, 3d, 5d, and 10d returns.
    Verifies directional predictability, wall-pinning behavior, and signal hit rates.

  Tier 2 — Systematic Microstructure Execution Backtest:
    Runs sequential event-driven backtesting over full historical OHLCV series
    (Nadaraya-Watson dynamic envelopes, Kinematic Kalman filter, Anchored VWAP,
    bar-risk sizing, trailing stops, 2 bps slippage, $0.005/share commissions)
    to measure the performance of the 3 Drift strategies:
      - Strategy 1: Mean-Reversion Channeling (+GEX)
      - Strategy 2: Breakout Expansion & Charm Inflow (Long Bias)
      - Strategy 3: Breakdown Expansion Below Key Support (Short Bias)

Usage:
    python3 edge/tools/backtest_drift_tab.py --symbols CRDO,TSLA,SPY,ASTS
    python3 edge/tools/backtest_drift_tab.py --symbols SPY --window 1y --out-dir edge/runs/drift_backtests
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge.daily_plays.options_intelligence import (
    OptionsFilters,
    build_options_intelligence,
)
from edge.research.systematic_execution import (
    BacktestTearsheet,
    run_microstructure_backtest,
)
from edge.tools.api_server import _cached_option_chain_rows

CHAIN_ROOT = ROOT / "data" / "option_chains"
DEFAULT_OUT_DIR = ROOT / "runs" / "drift_backtests"


# ---------------------------------------------------------------------------
# Data Loading Utilities
# ---------------------------------------------------------------------------

def load_symbol_daily_bars(symbol: str) -> Optional[pd.DataFrame]:
    """Load daily OHLCV from parquet data caches."""
    candidates = [
        ROOT / "data" / "1d" / f"{symbol}.parquet",
        ROOT / "data" / "1d_wide" / f"{symbol}.parquet",
        ROOT / "data" / "1d_smallcap" / f"{symbol}.parquet",
    ]
    for p in candidates:
        if p.exists():
            df = pd.read_parquet(p)
            if not isinstance(df.index, pd.DatetimeIndex) and "date" in [c.lower() for c in df.columns]:
                date_col = [c for c in df.columns if c.lower() == "date"][0]
                df[date_col] = pd.to_datetime(df[date_col])
                df = df.set_index(date_col)
            elif not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            df.columns = [c.lower() for c in df.columns]
            if "close" in df.columns and len(df) >= 10:
                return df
    return None


def get_available_snapshot_dates(symbol: str) -> List[str]:
    """Get sorted list of YYYY-MM-DD dates where an option chain snapshot exists."""
    if not CHAIN_ROOT.exists():
        return []
    matches = sorted([
        p.parent.name.replace("date=", "")
        for p in CHAIN_ROOT.glob(f"date=*/{symbol}.parquet")
    ])
    return matches


def load_snapshot_chain(symbol: str, date_str: str) -> Tuple[List[dict], float]:
    """Load option chain rows and spot price for a given snapshot date."""
    parquet_path = CHAIN_ROOT / f"date={date_str}" / f"{symbol}.parquet"
    if not parquet_path.exists():
        return [], 0.0
    rows = _cached_option_chain_rows(parquet_path)
    df_p = pd.read_parquet(parquet_path)
    spot = 0.0
    if "spot" in df_p.columns and len(df_p) > 0:
        spot = float(df_p["spot"].iloc[0])
    elif len(rows) > 0:
        spots = [float(r["spot"]) for r in rows if r.get("spot")]
        if spots:
            spot = float(np.median(spots))
    return rows, spot


# ---------------------------------------------------------------------------
# Tier 1: Snapshot Empirical Charm & Pressure Backtest
# ---------------------------------------------------------------------------

def evaluate_snapshot_signals(
    symbol: str,
    df_daily: pd.DataFrame,
) -> Dict[str, Any]:
    """Evaluate all available option chain snapshots and subsequent price drift."""
    snapshot_dates = get_available_snapshot_dates(symbol)
    if not snapshot_dates:
        return {
            "symbol": symbol,
            "snapshot_count": 0,
            "snapshots": [],
            "summary": "No historical option chain snapshots available.",
        }

    records: List[Dict[str, Any]] = []
    df_daily = df_daily.copy().sort_index()

    for d_str in snapshot_dates:
        rows, spot = load_snapshot_chain(symbol, d_str)
        if not rows or spot <= 0:
            continue

        res = build_options_intelligence(
            symbol=symbol,
            chain_rows=rows,
            flow_rows=[],
            price_series=[],
            spot=spot,
            filters=OptionsFilters(range="5d", min_premium=0, min_open_interest=0, min_volume=0),
            mode_requested="history",
            mode_resolved="history",
            chain_source="parquet",
            flow_source="none",
        )

        charm_summary = res.get("charm_summary") or {}
        summary = res.get("summary") or {}
        pressure = res.get("pressure") or {}

        net_charm_flow = charm_summary.get("net_charm_flow", 0.0)
        abs_charm_flow = charm_summary.get("abs_charm_flow", 0.0)
        charm_pressure = charm_summary.get("pressure", "balanced")

        total_gex_m = summary.get("total_gex_m", 0.0)
        call_wall = summary.get("call_wall")
        put_wall = summary.get("put_wall")
        gamma_flip = summary.get("gamma_flip")

        imbalance = pressure.get("imbalance", 0.0)
        pressure_direction = pressure.get("direction", "balanced")
        actionable = pressure.get("actionable", False)
        confidence_band = pressure.get("confidence", {}).get("band", "low")

        structural_breakdown = (
            (put_wall is not None and spot <= put_wall)
            or (gamma_flip is not None and spot < gamma_flip and (total_gex_m or 0) < 0)
        )
        s1_active = (
            (total_gex_m or 0) >= 0
            and put_wall is not None
            and call_wall is not None
            and spot >= put_wall
            and spot <= call_wall
            and (abs(imbalance) <= 0.25 or not actionable)
        )
        s2_active = (
            not structural_breakdown
            and (
                (call_wall is not None and spot >= call_wall)
                or (actionable and imbalance > 0.25 and (call_wall is None or spot < call_wall))
                or net_charm_flow < -10_000
            )
        )
        s3_active = structural_breakdown or (actionable and imbalance < -0.25) or net_charm_flow > 10_000

        if s3_active:
            primary_strat = "STRAT_3_BREAKDOWN_SHORT"
            primary_dir = "short"
        elif s1_active:
            primary_strat = "STRAT_1_RANGE_MEAN_REV"
            primary_dir = "range"
        elif s2_active:
            primary_strat = "STRAT_2_BREAKOUT_LONG"
            primary_dir = "long"
        else:
            primary_strat = "NEUTRAL_PIVOT_WATCH"
            primary_dir = "neutral"

        fwd_1d_ret: Optional[float] = None
        fwd_3d_ret: Optional[float] = None
        fwd_5d_ret: Optional[float] = None
        fwd_10d_ret: Optional[float] = None

        snap_dt = pd.to_datetime(d_str)
        eligible_indices = [i for i, ts in enumerate(df_daily.index) if ts >= snap_dt]
        if eligible_indices:
            idx_curr = eligible_indices[0]
            close_curr = float(df_daily["close"].iloc[idx_curr])
            n_bars = len(df_daily)

            if idx_curr + 1 < n_bars:
                c_1d = float(df_daily["close"].iloc[idx_curr + 1])
                fwd_1d_ret = (c_1d - close_curr) / close_curr

            if idx_curr + 3 < n_bars:
                c_3d = float(df_daily["close"].iloc[idx_curr + 3])
                fwd_3d_ret = (c_3d - close_curr) / close_curr

            if idx_curr + 5 < n_bars:
                c_5d = float(df_daily["close"].iloc[idx_curr + 5])
                fwd_5d_ret = (c_5d - close_curr) / close_curr

            if idx_curr + 10 < n_bars:
                c_10d = float(df_daily["close"].iloc[idx_curr + 10])
                fwd_10d_ret = (c_10d - close_curr) / close_curr

        charm_hit_1d = (
            (net_charm_flow < 0 and fwd_1d_ret is not None and fwd_1d_ret > 0)
            or (net_charm_flow > 0 and fwd_1d_ret is not None and fwd_1d_ret < 0)
            or (net_charm_flow == 0 and fwd_1d_ret is not None and abs(fwd_1d_ret) < 0.015)
        ) if fwd_1d_ret is not None else None

        charm_hit_5d = (
            (net_charm_flow < 0 and fwd_5d_ret is not None and fwd_5d_ret > 0)
            or (net_charm_flow > 0 and fwd_5d_ret is not None and fwd_5d_ret < 0)
            or (net_charm_flow == 0 and fwd_5d_ret is not None and abs(fwd_5d_ret) < 0.025)
        ) if fwd_5d_ret is not None else None

        records.append({
            "date": d_str,
            "spot": spot,
            "net_charm_flow": round(net_charm_flow, 2),
            "abs_charm_flow": round(abs_charm_flow, 2),
            "charm_pressure": charm_pressure,
            "imbalance": round(imbalance, 4),
            "pressure_direction": pressure_direction,
            "actionable": actionable,
            "confidence_band": confidence_band,
            "total_gex_m": round(total_gex_m, 2) if total_gex_m is not None else None,
            "call_wall": call_wall,
            "put_wall": put_wall,
            "gamma_flip": gamma_flip,
            "primary_strategy": primary_strat,
            "primary_direction": primary_dir,
            "fwd_1d_return_pct": round(fwd_1d_ret * 100, 2) if fwd_1d_ret is not None else None,
            "fwd_3d_return_pct": round(fwd_3d_ret * 100, 2) if fwd_3d_ret is not None else None,
            "fwd_5d_return_pct": round(fwd_5d_ret * 100, 2) if fwd_5d_ret is not None else None,
            "fwd_10d_return_pct": round(fwd_10d_ret * 100, 2) if fwd_10d_ret is not None else None,
            "charm_hit_1d": charm_hit_1d,
            "charm_hit_5d": charm_hit_5d,
        })

    hits_1d = [r["charm_hit_1d"] for r in records if r["charm_hit_1d"] is not None]
    hits_5d = [r["charm_hit_5d"] for r in records if r["charm_hit_5d"] is not None]
    fwd_5d_vals = [r["fwd_5d_return_pct"] for r in records if r["fwd_5d_return_pct"] is not None]

    win_rate_1d = (sum(1 for h in hits_1d if h) / len(hits_1d) * 100) if hits_1d else 0.0
    win_rate_5d = (sum(1 for h in hits_5d if h) / len(hits_5d) * 100) if hits_5d else 0.0

    return {
        "symbol": symbol,
        "snapshot_count": len(records),
        "hit_rate_1d_pct": round(win_rate_1d, 1),
        "hit_rate_5d_pct": round(win_rate_5d, 1),
        "avg_fwd_5d_pct": round(float(np.mean(fwd_5d_vals)), 2) if fwd_5d_vals else 0.0,
        "snapshots": records,
    }


# ---------------------------------------------------------------------------
# Tier 2: Systematic Microstructure Execution Backtest
# ---------------------------------------------------------------------------

def evaluate_systematic_execution(
    symbol: str,
    df_daily: pd.DataFrame,
    window: str = "full",
    initial_capital: float = 100_000.0,
    risk_pct: float = 0.02,
    slippage_bps: float = 2.0,
) -> Dict[str, Any]:
    """Run event-driven microstructure backtest across daily bars."""
    df = df_daily.copy().sort_index()
    if window == "1y":
        df = df.tail(252)
    elif window == "3y":
        df = df.tail(756)

    prices = df["close"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float) if "high" in df else None
    lows = df["low"].to_numpy(dtype=float) if "low" in df else None
    volumes = df["volume"].to_numpy(dtype=float) if "volume" in df else None
    timestamps = [
        idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
        for idx in df.index
    ]

    tearsheet: BacktestTearsheet = run_microstructure_backtest(
        prices,
        timestamps=timestamps,
        symbol=symbol,
        volumes=volumes,
        highs=highs,
        lows=lows,
        initial_capital=initial_capital,
        risk_per_trade_pct=risk_pct,
        slippage_bps=slippage_bps,
    )

    out = asdict(tearsheet)
    out["window"] = window
    out["start_date"] = timestamps[0] if timestamps else ""
    out["end_date"] = timestamps[-1] if timestamps else ""
    return out


# ---------------------------------------------------------------------------
# Main Runner & CLI
# ---------------------------------------------------------------------------

def run_drift_tab_backtests(
    symbols: List[str],
    out_dir: Optional[Path] = None,
    window: str = "full",
) -> Dict[str, Any]:
    """Execute complete two-tier backtest suite across specified symbols."""
    results: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "window": window,
        "tier1_snapshots": {},
        "tier2_systematic": {},
    }

    for sym in symbols:
        sym = sym.upper().strip()
        df = load_symbol_daily_bars(sym)
        if df is None:
            results["tier1_snapshots"][sym] = {"error": f"No daily bars found for {sym}"}
            results["tier2_systematic"][sym] = {"error": f"No daily bars found for {sym}"}
            continue

        t1 = evaluate_snapshot_signals(sym, df)
        results["tier1_snapshots"][sym] = t1

        t2 = evaluate_systematic_execution(sym, df, window=window)
        results["tier2_systematic"][sym] = t2

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        summary_path = out_dir / "drift_tab_backtest_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"Results successfully persisted to {summary_path}")

    return results


def print_cli_summary(results: Dict[str, Any]) -> None:
    """Print clean terminal report comparing all symbols."""
    print("\n" + "=" * 92)
    print("           TRADECENTRAL DRIFT TAB QUANTITATIVE BACKTEST REPORT")
    print("=" * 92)

    symbols = results.get("symbols", [])

    print("\n[TIER 1] OPTION CHAIN EMPIRICAL SNAPSHOTS (CHARM & PRESSURE DRIFT)")
    print("-" * 92)
    print(f"{'SYMBOL':<8} | {'SNAPS':<6} | {'1D HIT %':<9} | {'5D HIT %':<9} | {'AVG 5D RET':<11} | {'LATEST SIGNAL & CHARM':<36}")
    print("-" * 92)

    for sym in symbols:
        t1 = results["tier1_snapshots"].get(sym, {})
        if "error" in t1:
            print(f"{sym:<8} | {'ERROR':<6} | {t1['error']}")
            continue
        count = t1.get("snapshot_count", 0)
        h1 = f"{t1.get('hit_rate_1d_pct', 0.0):.1f}%"
        h5 = f"{t1.get('hit_rate_5d_pct', 0.0):.1f}%"
        avg5 = f"{t1.get('avg_fwd_5d_pct', 0.0):+.2f}%"

        latest = t1.get("snapshots", [])[-1] if t1.get("snapshots") else None
        latest_desc = "None"
        if latest:
            flow = latest.get("net_charm_flow", 0.0)
            strat = latest.get("primary_strategy", "")
            latest_desc = f"{latest['date']}: {flow:+.0f} sh/d ({strat})"
        print(f"{sym:<8} | {count:<6} | {h1:<9} | {h5:<9} | {avg5:<11} | {latest_desc:<36}")

    print("-" * 92)

    print("\n[TIER 2] SYSTEMATIC MICROSTRUCTURE EXECUTION TEARSHEET (EVENT-DRIVEN)")
    print("-" * 92)
    print(f"{'SYMBOL':<8} | {'BARS':<6} | {'RETURN':<9} | {'SHARPE':<8} | {'MAX DD':<8} | {'WIN %':<7} | {'TRADES':<7} | {'PROFIT FAC':<10}")
    print("-" * 92)

    for sym in symbols:
        t2 = results["tier2_systematic"].get(sym, {})
        if "error" in t2:
            print(f"{sym:<8} | {'ERROR':<6} | {t2['error']}")
            continue
        bars = t2.get("n_bars", 0)
        ret = f"{t2.get('total_return_pct', 0.0):+.2f}%"
        sharpe = f"{t2.get('sharpe_ratio', 0.0):.2f}"
        max_dd = f"{t2.get('max_drawdown_pct', 0.0):.2f}%"
        win_rate = f"{t2.get('win_rate', 0.0):.1f}%"
        trades = t2.get("total_trades", 0)
        pf = f"{t2.get('profit_factor', 0.0):.2f}"

        print(f"{sym:<8} | {bars:<6} | {ret:<9} | {sharpe:<8} | {max_dd:<8} | {win_rate:<7} | {trades:<7} | {pf:<10}")

    print("-" * 92)
    print("Attribution Note: Realistic 2 bps half-spread slippage, $0.005/sh commissions, ATR stops.")
    print("=" * 92 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest TradeCentral Drift Tab across symbols.")
    parser.add_argument("--symbols", type=str, default="CRDO,TSLA,SPY,ASTS", help="Comma-separated symbols")
    parser.add_argument("--window", type=str, default="full", choices=["1y", "3y", "full"], help="History window for Tier 2")
    parser.add_argument("--out-dir", type=str, default=str(DEFAULT_OUT_DIR), help="Output directory for JSON summary")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    out_dir = Path(args.out_dir)

    results = run_drift_tab_backtests(symbols, out_dir=out_dir, window=args.window)
    print_cli_summary(results)


if __name__ == "__main__":
    main()
