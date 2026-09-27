#!/usr/bin/env python3
"""tools/backtest_regimes.py — Live-Trading Grade Market Regime Backtest Engine.

Empirically evaluates the discriminative power, hazard anticipation, and strategy
performance of TradeCentral causal market regimes across high-volatility equities
and macro indices without lookahead.

Usage:
    python3 edge/tools/backtest_regimes.py --symbols ASTS,IONQ,TSLA,CRDO,SPY,QQQ
    python3 edge/tools/backtest_regimes.py --symbols ASTS --out-dir edge/runs/regime_backtests
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "runs" / "regime_backtests"

if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge.research.kalman_trend import kalman_trend
from edge.research.regimes import (
    compute_rolling_volatility_regime,
    compute_market_structure,
    compute_cusum_transition_risk,
)
from edge.research.regime_engine import (
    reconcile_market_regime,
    compute_calibrated_confidence,
    compute_q_data,
    compute_d_boundary,
    compute_s_persistence,
    PrimaryRegime,
    VolatilityState,
    MarketStructure,
)


def load_symbol_prices(symbol: str) -> Optional[pd.DataFrame]:
    """Load daily OHLCV from parquet data caches."""
    candidates = [
        ROOT / "data" / "1d" / f"{symbol}.parquet",
        ROOT / "data" / "1d_wide" / f"{symbol}.parquet",
        ROOT / "data" / "1d_smallcap" / f"{symbol}.parquet",
    ]
    for p in candidates:
        if p.exists():
            df = pd.read_parquet(p).sort_index()
            df.columns = [c.lower() for c in df.columns]
            if "close" in df.columns and len(df) >= 30:
                return df
    return None


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """True Range rolling average."""
    high = df["high"] if "high" in df.columns else df["close"]
    low = df["low"] if "low" in df.columns else df["close"]
    close = df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=5).mean()


def calculate_metrics(eq: pd.Series, rets: pd.Series) -> Dict[str, float]:
    """Standard quantitative metrics dictionary."""
    total_ret = float(eq.iloc[-1] - 1.0) if len(eq) > 0 else 0.0
    n_years = max(0.2, len(rets) / 252.0)
    cagr = float((eq.iloc[-1]) ** (1.0 / n_years) - 1.0) if eq.iloc[-1] > 0 else -1.0
    ann_vol = float(rets.std() * np.sqrt(252.0))
    sharpe = float((rets.mean() * 252.0) / ann_vol) if ann_vol > 0.001 else 0.0
    downside = rets[rets < 0]
    sortino = (
        float((rets.mean() * 252.0) / (downside.std() * np.sqrt(252.0)))
        if len(downside) > 0 and downside.std() > 0.001
        else 0.0
    )
    cummax = eq.cummax()
    drawdown = (eq - cummax) / cummax
    max_dd = float(drawdown.min())
    calmar = float(cagr / abs(max_dd)) if abs(max_dd) > 0.001 else 0.0
    win_rate = float((rets > 0).mean() * 100.0) if len(rets) > 0 else 0.0
    return {
        "total_return_pct": round(total_ret * 100.0, 1),
        "cagr_pct": round(cagr * 100.0, 1),
        "ann_vol_pct": round(ann_vol * 100.0, 1),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 1),
        "calmar": round(calmar, 2),
        "win_rate_pct": round(win_rate, 1),
    }


def simulate_institutional_strategy(
    df: pd.DataFrame,
    regimes: List[str],
    confidences: List[float],
    kt_res: Any,
    ext_z_s: pd.Series,
    dist_sma50_s: pd.Series,
    dist_sma200_s: pd.Series,
    downside_hazard: pd.Series,
    atr_s: pd.Series,
    ann_vol_s: pd.Series,
    *,
    use_vol_target: bool = False,
    target_vol: float = 0.25,
    cost_roundtrip_bps: float = 10.0,
    allow_short: bool = False,
) -> Tuple[pd.Series, pd.Series, pd.Series, Dict[str, Any]]:
    """Execute risk-managed causal trading strategy."""
    n = len(df)
    close_s = df["close"]
    pos = np.zeros(n, dtype=float)
    in_trade = False
    entry_p = 0.0
    highest_p = 0.0
    stop_p = 0.0
    trades: List[Dict[str, Any]] = []
    entry_idx = 0

    for i in range(1, n):
        r = regimes[i - 1]
        c = confidences[i - 1]
        kz = float(kt_res.velocity_zscore[i - 1]) if pd.notna(kt_res.velocity_zscore[i - 1]) else 0.0
        z_ext = float(ext_z_s.iloc[i - 1]) if pd.notna(ext_z_s.iloc[i - 1]) else 0.0
        d_sma = float(dist_sma50_s.iloc[i - 1]) if pd.notna(dist_sma50_s.iloc[i - 1]) else 0.0
        d_sma200 = float(dist_sma200_s.iloc[i - 1]) if pd.notna(dist_sma200_s.iloc[i - 1]) else None
        macro_uptrend = (d_sma200 > 0.0) if d_sma200 is not None and i >= 200 else (d_sma > 0.0)
        atr = float(atr_s.iloc[i - 1]) if pd.notna(atr_s.iloc[i - 1]) and atr_s.iloc[i - 1] > 0 else (close_s.iloc[i - 1] * 0.02)
        r_vol = float(ann_vol_s.iloc[i - 1]) if pd.notna(ann_vol_s.iloc[i - 1]) and ann_vol_s.iloc[i - 1] > 0.05 else 0.25
        dh = float(downside_hazard.iloc[i - 1]) if pd.notna(downside_hazard.iloc[i - 1]) else 0.0
        curr_p = float(close_s.iloc[i])

        base_size = min(1.0, target_vol / r_vol) if use_vol_target else 1.0

        if in_trade:
            highest_p = max(highest_p, curr_p)
            gain = (highest_p - entry_p) / entry_p
            
            # Dynamic Trailing Stop Ladder:
            # 1. Big profit (>= 20%): trail by 2.5 ATR
            # 2. Modest profit (>= 8% or gain >= 1.5 ATR): lock breakeven or trail by 2.0 ATR
            # 3. Initial stop: max(entry - 2.0 ATR, entry * 0.92) [hard 8% stop]
            if gain >= 0.20:
                trailing_stop = highest_p - 2.5 * atr
            elif gain >= 0.08 or (highest_p - entry_p) >= 1.5 * atr:
                trailing_stop = max(entry_p, highest_p - 2.0 * atr)
            else:
                trailing_stop = max(entry_p - 2.0 * atr, entry_p * 0.92)

            stop_p = max(stop_p, trailing_stop)

            # Invalidation triggers:
            # A) Stop breached
            # B) Trend reversal: BEARISH_TREND with negative velocity
            # C) Downside hazard spike (dh >= 0.65) with negative velocity
            trend_dead = (r == "BEARISH_TREND" and kz < -0.25) or (dh >= 0.65 and kz < 0.0)

            if curr_p < stop_p or trend_dead:
                pnl = (curr_p - entry_p) / entry_p
                trades.append({
                    "entry_idx": entry_idx,
                    "exit_idx": i,
                    "pnl": pnl,
                    "reason": "stop" if curr_p < stop_p else "trend_dead",
                })
                in_trade = False
                pos[i] = 0.0
            else:
                # Overextension de-risking: trim 50% if z_ext > 2.5
                if z_ext > 2.5:
                    pos[i] = base_size * 0.5
                else:
                    pos[i] = base_size
        else:
            # Entry logic:
            is_bull_regime = (r == "BULLISH_TREND" and kz >= 0.25)
            is_breakout = (r == "VOL_EXPANSION_BREAKOUT" and kz >= 0.50)
            is_dip_buy = (r == "MEAN_REVERTING" and d_sma > 0.0 and kz >= 0.0)

            # Never enter when severely overextended (z_ext <= 2.5)
            can_enter = (is_bull_regime or is_breakout or is_dip_buy) and macro_uptrend and (z_ext <= 2.5) and (c >= 0.35)

            if can_enter:
                in_trade = True
                entry_idx = i
                entry_p = curr_p
                highest_p = curr_p
                stop_p = max(curr_p - 2.0 * atr, curr_p * 0.92)
                pos[i] = base_size
            elif allow_short and r == "BEARISH_TREND" and kz <= -0.75 and d_sma < 0.0:
                pos[i] = -base_size
            else:
                pos[i] = 0.0

    pos_s = pd.Series(pos, index=df.index)
    bar_rets = df["close"].pct_change().fillna(0.0)
    turnover = pos_s.diff().abs().fillna(0.0)
    cost = turnover * (cost_roundtrip_bps / 10000.0 / 2.0)
    strat_rets = pos_s.shift(1).fillna(0.0) * bar_rets - cost
    strat_equity = (1.0 + strat_rets).cumprod()

    trade_stats = {
        "count": len(trades),
        "win_rate": round(float(np.mean([t["pnl"] > 0 for t in trades]) * 100.0), 1) if trades else 0.0,
        "avg_pnl_pct": round(float(np.mean([t["pnl"] * 100.0 for t in trades])), 2) if trades else 0.0,
    }

    return pos_s, strat_rets, strat_equity, trade_stats


def run_regime_backtest(
    symbol: str,
    df: pd.DataFrame,
    *,
    holding_days: int = 5,
    cost_roundtrip_bps: float = 10.0,
    allow_short: bool = False,
    target_vol: float = 0.25,
) -> Dict[str, Any]:
    """Execute point-in-time regime classification and calculate full empirical metrics."""
    df = df.copy().sort_index()
    close_s = df["close"]
    log_ret = np.log(close_s / close_s.shift(1)).dropna()

    # 1. Specialized Models (strictly causal)
    vol_res = compute_rolling_volatility_regime(df)
    kt_res = kalman_trend(close_s, adaptive_vol_scaling=True)
    kz_s = pd.Series(kt_res.velocity_zscore, index=df.index)
    struct_res = compute_market_structure(df, kalman_z_series=kz_s)
    c_res = compute_cusum_transition_risk(log_ret, vol_shock_mask=vol_res.volatility_shock)

    # Directional CUSUM & extension metrics
    down_hazard = c_res.downside_hazard if c_res.downside_hazard is not None else c_res.transition_risk
    up_expansion = c_res.upside_expansion if c_res.upside_expansion is not None else pd.Series(0.0, index=df.index)
    ext_z_s = pd.Series(kt_res.extension_zscore, index=df.index) if kt_res.extension_zscore is not None else pd.Series(0.0, index=df.index)

    # Macro 50-day SMA for trend retest conditioning
    sma50_s = close_s.rolling(50, min_periods=20).mean()
    dist_sma50_s = (close_s - sma50_s) / sma50_s

    # Reconcile historical regimes
    n = len(df)
    regimes: List[str] = []
    confidences: List[float] = []

    for i in range(n):
        dt = df.index[i]
        kz = float(kt_res.velocity_zscore[i]) if pd.notna(kt_res.velocity_zscore[i]) else 0.0
        ts = str(kt_res.trend_state[i]) if kt_res.trend_state is not None else "UNCERTAIN"
        vp = float(vol_res.volatility_percentile.iloc[i]) if pd.notna(vol_res.volatility_percentile.iloc[i]) else 0.50
        
        try:
            vs = VolatilityState(str(vol_res.volatility_state.iloc[i]))
        except Exception:
            vs = VolatilityState.NORMAL_MEDIUM
            
        try:
            ms = MarketStructure(str(struct_res.market_structure.iloc[i]))
        except Exception:
            ms = MarketStructure.RANGE_BOUND

        vr = float(struct_res.variance_ratio_5.iloc[i]) if pd.notna(struct_res.variance_ratio_5.iloc[i]) else 1.0
        ou = float(struct_res.ou_half_life.iloc[i]) if pd.notna(struct_res.ou_half_life.iloc[i]) else 50.0
        dh = float(down_hazard.loc[dt]) if dt in down_hazard.index and pd.notna(down_hazard.loc[dt]) else 0.0
        ue = float(up_expansion.loc[dt]) if dt in up_expansion.index and pd.notna(up_expansion.loc[dt]) else 0.0
        z_ext = float(ext_z_s.loc[dt]) if dt in ext_z_s.index and pd.notna(ext_z_s.loc[dt]) else 0.0
        d_sma = float(dist_sma50_s.loc[dt]) if dt in dist_sma50_s.index and pd.notna(dist_sma50_s.loc[dt]) else None

        reg = reconcile_market_regime(
            kalman_z=kz,
            trend_state=ts,
            vol_percentile=vp,
            vol_state=vs,
            market_structure=ms,
            variance_ratio=vr,
            ou_half_life=ou,
            flow_mad_z=0.0,
            t_risk=dh,
            delta_flip=None,
            agreement_ratio=0.85,
            has_model_conflict=False,
            is_measurable=True,
            upside_expansion=ue,
            downside_hazard=dh,
            z_extension=z_ext,
            dist_sma50=d_sma,
        )
        regimes.append(reg.value)

        # Point-in-time calibrated confidence
        q_data = compute_q_data(n_bars=i + 1, has_flip=False, has_options=False)
        d_bnd = compute_d_boundary(spot=float(close_s.iloc[i]), gamma_flip=None, kalman_z=kz)
        s_pers = compute_s_persistence(n_unbroken_bars=int(kt_res.persistence[i]))
        conf = compute_calibrated_confidence(
            q_data=q_data,
            a_models=0.85,
            d_boundary=d_bnd,
            s_persistence=s_pers,
            t_risk=dh,
            z_extension=z_ext,
        )
        confidences.append(conf)

    df["regime"] = regimes
    df["confidence"] = confidences
    df["z_extension"] = ext_z_s

    # Forward horizon returns
    df["fwd_ret_1d"] = df["close"].pct_change().shift(-1)
    df["fwd_ret_5d"] = (df["close"].shift(-holding_days) - df["close"]) / df["close"]
    df["fwd_ret_20d"] = (df["close"].shift(-20) - df["close"]) / df["close"]

    # Statistical Separation per regime
    regime_stats = []
    for r_name in [
        "BULLISH_TREND",
        "VOL_EXPANSION_BREAKOUT",
        "UNCERTAIN_TRANSITIONAL",
        "BEARISH_TREND",
        "COMPRESSION_RANGE",
        "MEAN_REVERTING",
    ]:
        sub = df[df["regime"] == r_name]
        cnt = len(sub)
        if cnt == 0:
            continue
        r1 = sub["fwd_ret_1d"].dropna()
        r5 = sub["fwd_ret_5d"].dropna()
        r20 = sub["fwd_ret_20d"].dropna()

        ann_ret = float(r1.mean() * 252.0) if len(r1) > 0 else 0.0
        ann_vol = float(r1.std() * np.sqrt(252.0)) if len(r1) > 0 else 0.0
        sharpe = float(ann_ret / ann_vol) if ann_vol > 0.001 else 0.0

        regime_stats.append({
            "regime": r_name,
            "bars": cnt,
            "pct_share": round(cnt / n * 100.0, 1),
            "mean_1d_bps": round(float(r1.mean() * 10000.0), 1) if len(r1) > 0 else 0.0,
            "ann_return_pct": round(ann_ret * 100.0, 1),
            "ann_vol_pct": round(ann_vol * 100.0, 1),
            "sharpe": round(sharpe, 2),
            "mean_5d_bps": round(float(r5.mean() * 10000.0), 1) if len(r5) > 0 else 0.0,
            "win_rate_5d": round(float((r5 > 0).mean() * 100.0), 1) if len(r5) > 0 else 0.0,
            "mean_20d_bps": round(float(r20.mean() * 10000.0), 1) if len(r20) > 0 else 0.0,
        })

    # Markov Transition Matrix P(S_{t+1} | S_t)
    reg_series = pd.Series(regimes)
    reg_next = reg_series.shift(-1)
    trans_df = pd.crosstab(reg_series, reg_next, normalize="index")
    transition_matrix = {
        from_st: {to_st: round(float(trans_df.loc[from_st, to_st]), 4) for to_st in trans_df.columns}
        for from_st in trans_df.index
    }

    # Moving averages & Volatility metrics
    sma200_s = close_s.rolling(200, min_periods=50).mean()
    dist_sma200_s = (close_s - sma200_s) / sma200_s
    atr_s = compute_atr(df, 14)
    ann_vol_s = close_s.pct_change().rolling(20, min_periods=10).std() * np.sqrt(252.0)

    # Benchmark: Buy-and-Hold
    bnh_rets = df["close"].pct_change().fillna(0.0)
    bnh_equity = (1.0 + bnh_rets).cumprod()
    bnh_perf = calculate_metrics(bnh_equity, bnh_rets)

    # Strategy 1: Unscaled Full Capital (Signal Alpha)
    pos_unscaled, rets_unscaled, eq_unscaled, trades_unscaled = simulate_institutional_strategy(
        df, regimes, confidences, kt_res, ext_z_s, dist_sma50_s, dist_sma200_s,
        down_hazard, atr_s, ann_vol_s,
        use_vol_target=False,
        cost_roundtrip_bps=cost_roundtrip_bps,
        allow_short=allow_short,
    )
    unscaled_perf = calculate_metrics(eq_unscaled, rets_unscaled)

    # Strategy 2: Volatility-Targeted Risk Parity
    pos_voltgt, rets_voltgt, eq_voltgt, trades_voltgt = simulate_institutional_strategy(
        df, regimes, confidences, kt_res, ext_z_s, dist_sma50_s, dist_sma200_s,
        down_hazard, atr_s, ann_vol_s,
        use_vol_target=True,
        target_vol=target_vol,
        cost_roundtrip_bps=cost_roundtrip_bps,
        allow_short=allow_short,
    )
    voltgt_perf = calculate_metrics(eq_voltgt, rets_voltgt)

    # Walk-Forward Cross-Validation: 60% In-Sample / 40% Out-Of-Sample
    split_idx = int(n * 0.60)
    is_rets = rets_voltgt.iloc[:split_idx]
    oos_rets = rets_voltgt.iloc[split_idx:]
    is_eq = (1.0 + is_rets).cumprod()
    oos_eq = (1.0 + oos_rets).cumprod()
    is_perf = calculate_metrics(is_eq, is_rets)
    oos_perf = calculate_metrics(oos_eq, oos_rets)

    return {
        "symbol": symbol,
        "bars": n,
        "date_start": str(df.index[0]),
        "date_end": str(df.index[-1]),
        "regime_statistics": regime_stats,
        "transition_matrix": transition_matrix,
        "strategy_performance_unscaled": unscaled_perf,
        "strategy_performance_vol_targeted": voltgt_perf,
        "benchmark_performance": bnh_perf,
        "walk_forward_cross_validation": {
            "in_sample": is_perf,
            "out_of_sample": oos_perf,
            "split_date": str(df.index[split_idx]),
        },
        "safety_diagnostics": {
            "exposure_unscaled_pct": round(float((pos_unscaled != 0).mean() * 100.0), 1),
            "exposure_voltgt_pct": round(float((pos_voltgt != 0).mean() * 100.0), 1),
            "trades_unscaled": trades_unscaled,
            "trades_voltgt": trades_voltgt,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Live-Trading Market Regime Backtest Engine")
    parser.add_argument("--symbols", type=str, default="ASTS,IONQ,TSLA,CRDO,SPY,QQQ", help="Comma-separated symbols")
    parser.add_argument("--holding-days", type=int, default=5, help="Forward holding horizon in bars")
    parser.add_argument("--cost-bps", type=float, default=10.0, help="Round-trip transaction cost in bps")
    parser.add_argument("--target-vol", type=float, default=0.25, help="Annualized target volatility for risk parity")
    parser.add_argument("--allow-short", action="store_true", help="Allow shorting in BEARISH_TREND")
    parser.add_argument("--out-dir", type=str, default=str(DEFAULT_OUT_DIR), help="Output directory for JSON reports")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 90)
    print("  TRADECENTRAL QUANTITATIVE MARKET REGIME BACKTEST ENGINE")
    print(f"  Hold Horizon: {args.holding_days}d | Cost: {args.cost_bps} bps | Vol Target: {args.target_vol*100:.0f}% | Symbols: {', '.join(symbols)}")
    print("=" * 90 + "\n")

    all_results = {}

    for sym in symbols:
        df = load_symbol_prices(sym)
        if df is None:
            print(f"[WARN] Could not load price data for {sym}, skipping.")
            continue

        res = run_regime_backtest(
            sym,
            df,
            holding_days=args.holding_days,
            cost_roundtrip_bps=args.cost_bps,
            allow_short=args.allow_short,
            target_vol=args.target_vol,
        )
        all_results[sym] = res

        print(f"=== {sym} Empirical Separation ({res['bars']} bars: {res['date_start'][:10]} to {res['date_end'][:10]}) ===")
        tbl_data = []
        for r in res["regime_statistics"]:
            tbl_data.append({
                "Regime": r["regime"],
                "Bars": r["bars"],
                "Share": f"{r['pct_share']}%",
                "Mean 1d": f"{r['mean_1d_bps']:>5.1f} bps",
                "Ann Vol": f"{r['ann_vol_pct']:>4.1f}%",
                "Sharpe": f"{r['sharpe']:>5.2f}",
                f"Mean {args.holding_days}d": f"{r['mean_5d_bps']:>6.1f} bps",
                f"Win {args.holding_days}d": f"{r['win_rate_5d']:>4.1f}%",
            })
        print(pd.DataFrame(tbl_data).to_string(index=False))

        unscaled = res["strategy_performance_unscaled"]
        voltgt = res["strategy_performance_vol_targeted"]
        bnh = res["benchmark_performance"]
        wf = res["walk_forward_cross_validation"]
        safe = res["safety_diagnostics"]

        print("\n  Strategy vs Benchmark Performance Comparison:")
        print(f"    {'Benchmark (BnH)':<22}: CAGR: {bnh['cagr_pct']:>6.1f}% | Sharpe: {bnh['sharpe']:>5.2f} | MaxDD: {bnh['max_drawdown_pct']:>6.1f}% | WinRate: {bnh['win_rate_pct']}%")
        print(f"    {'Regime (Unscaled)':<22}: CAGR: {unscaled['cagr_pct']:>6.1f}% | Sharpe: {unscaled['sharpe']:>5.2f} | MaxDD: {unscaled['max_drawdown_pct']:>6.1f}% | WinRate: {unscaled['win_rate_pct']}% | Exp: {safe['exposure_unscaled_pct']}%")
        print(f"    {'Regime (Vol-Targeted)':<22}: CAGR: {voltgt['cagr_pct']:>6.1f}% | Sharpe: {voltgt['sharpe']:>5.2f} | MaxDD: {voltgt['max_drawdown_pct']:>6.1f}% | WinRate: {voltgt['win_rate_pct']}% | Exp: {safe['exposure_voltgt_pct']}%")
        print(f"    Walk-Forward Split ({wf['split_date'][:10]}):")
        print(f"      In-Sample  (60%): CAGR: {wf['in_sample']['cagr_pct']:>6.1f}% | Sharpe: {wf['in_sample']['sharpe']:>5.2f} | MaxDD: {wf['in_sample']['max_drawdown_pct']:>6.1f}%")
        print(f"      Out-Of-Sample(40%): CAGR: {wf['out_of_sample']['cagr_pct']:>6.1f}% | Sharpe: {wf['out_of_sample']['sharpe']:>5.2f} | MaxDD: {wf['out_of_sample']['max_drawdown_pct']:>6.1f}%\n")

    out_file = out_dir / "regime_backtest_summary.json"
    with open(out_file, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"[SUCCESS] Saved comprehensive backtest report to {out_file}\n")


if __name__ == "__main__":
    main()