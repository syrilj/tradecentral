#!/usr/bin/env python3
"""Backtest Track 1 Level-2 Option Volatility Timing Strategy.

Evaluates long SPY / QQQ option positions driven by volatility term structure signals:
  - term_slope: VIX / VIX3M
  - short_stress: VIX9D / VIX
  - vol_of_vol_ratio: VVIX / VIX
  - tail_risk: SKEW
  - vix_vrp: VIX - SPY_20d_realized_vol

Option Pricing & Execution Engine:
  - Uses Black-Scholes valuation with VIX as base IV.
  - Option spread cost: $0.01 per side ($0.02 round-trip) per contract (penny-wide SPY/QQQ option market standard).
  - Risk-free rate: 0.03 (3% annual).

Evaluates GO/NO-GO gate defined in `edge/docs/GATE_VOL_TIMING.md`.

Usage:
  python3 edge/tools/backtest_vol_timing.py
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = ROOT / "edge" / "data" / "vol_complex.csv"
OUT_DIR = ROOT / "edge" / "runs" / "vol_timing"

# Black-Scholes Option Pricing
def bs_price(spot: float, strike: float, t_years: float, r: float, iv: float, option_type: str = "call") -> float:
    if t_years <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return max(0.0, spot - strike) if option_type == "call" else max(0.0, strike - spot)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv ** 2) * t_years) / (iv * math.sqrt(t_years))
    d2 = d1 - iv * math.sqrt(t_years)
    if option_type == "call":
        price = spot * norm.cdf(d1) - strike * math.exp(-r * t_years) * norm.cdf(d2)
    else:
        price = strike * math.exp(-r * t_years) * norm.cdf(-d2) - spot * norm.cdf(-d1)
    return max(0.0, price)

REGIMES = {
    "2011-2015": ("2011-01-03", "2015-12-31"),
    "2016-2018": ("2016-01-01", "2018-12-31"),
    "2018-2020": ("2019-01-01", "2020-12-31"),
    "2020-2022": ("2021-01-01", "2022-12-31"),
    "2022-2026": ("2023-01-01", "2026-07-29"),
}

def run_vol_timing_backtest(
    df: pd.DataFrame,
    underlying: str = "SPY",
    holding_days: int = 15,
    cost_per_side: float = 0.01, # $0.01 per contract side ($1 per 100-share contract)
    enter_call_term_slope: float = 1.02,
    enter_put_skew: float = 142.0,
    enter_put_term_slope: float = 0.85,
) -> dict:
    df = df.copy().sort_values("Date").reset_index(drop=True)
    df["Date"] = pd.to_datetime(df["Date"])
    
    trades = []
    daily_equity = [10000.0]
    cash = 10000.0
    position = None
    
    dates = df["Date"].values
    prices = df[underlying].values
    vixes = df["VIX"].values
    slopes = df["term_slope"].values
    stresses = df["short_stress"].values
    skews = df["tail_risk"].values
    vrps = df["vix_vrp"].values
    
    portfolio_history = []
    
    # EXECUTION-LAG CORRECTION (2026-08-16): signals are formed from bar i's
    # end-of-day vol-complex data (VIX, term_slope, SKEW, ...), so the earliest
    # honest entry is the NEXT bar's open. The previous version entered on bar
    # i itself, pricing the option with the same bar's spot and VIX that formed
    # the signal -- the same one-bar lookahead shape the rest of this repo
    # treats as unrepresentable (edge/docs/LOOKAHEAD_CORRECTION.md,
    # edge/research/portfolio.py). Pending entries are queued on bar i and
    # filled at bar i+1's open.
    pending_entry = None  # {"option_type", "strike", "dte", "signal_date"}
    
    for i in range(len(df)):
        dt = pd.to_datetime(dates[i])
        spot = prices[i]
        vix = vixes[i] / 100.0 if not np.isnan(vixes[i]) else 0.20
        slope = slopes[i] if not np.isnan(slopes[i]) else 1.0
        skew = skews[i] if not np.isnan(skews[i]) else 120.0
        
        # Check current position
        if position is not None:
            days_held = i - position["entry_idx"]
            t_remaining = max(0.001, (position["dte"] - days_held) / 365.0)
            
            # Current option value via Black-Scholes
            curr_opt_price = bs_price(
                spot=spot,
                strike=position["strike"],
                t_years=t_remaining,
                r=0.03,
                iv=vix,
                option_type=position["option_type"]
            )
            
            # Liquidation value minus closing cost
            net_close_price = max(0.0, curr_opt_price - cost_per_side)
            position_value = position["contracts"] * 100.0 * net_close_price
            current_portfolio_value = cash + position_value
            
            # Check exit condition
            if days_held >= holding_days or t_remaining <= 0.01:
                pnl = position_value - position["capital_allocated"]
                ret_pct = pnl / position["capital_allocated"]
                trades.append({
                    "entry_date": position["entry_date"],
                    "exit_date": dt.strftime("%Y-%m-%d"),
                    "underlying": underlying,
                    "type": position["option_type"],
                    "entry_spot": float(position["entry_spot"]),
                    "exit_spot": float(spot),
                    "holding_days": int(days_held),
                    "capital": float(position["capital_allocated"]),
                    "pnl": float(pnl),
                    "return_pct": float(ret_pct),
                })
                cash = current_portfolio_value
                position = None
        else:
            current_portfolio_value = cash
            
            # Fill a pending entry at THIS bar's open (signal was formed at
            # the prior bar's close -- one full bar of execution lag).
            if pending_entry is not None:
                opt_type = pending_entry["option_type"]
                strike = pending_entry["strike"]
                dte = pending_entry["dte"]
                t_years = dte / 365.0
                raw_opt_price = bs_price(spot=spot, strike=strike, t_years=t_years, r=0.03, iv=vix, option_type=opt_type)
                ask_price = raw_opt_price + cost_per_side # Charge $0.01 ask spread
                
                # Allocate 5% of account cash per position
                alloc_cash = cash * 0.05
                if ask_price > 0.05 and alloc_cash >= ask_price * 100:
                    n_contracts = max(1, int(alloc_cash / (ask_price * 100)))
                    actual_cost = n_contracts * 100 * ask_price
                    cash -= actual_cost
                    position = {
                        "entry_idx": i,
                        "entry_date": dt.strftime("%Y-%m-%d"),
                        "option_type": opt_type,
                        "strike": strike,
                        "dte": dte,
                        "entry_spot": spot,
                        "ask_price": ask_price,
                        "contracts": n_contracts,
                        "capital_allocated": actual_cost,
                    }
                pending_entry = None
            
            # Entry Signals (formed at this bar's close; executed next bar)
            # 1. Long CALL: Volatility backwardation panic -> expected mean reversion rally
            is_call_signal = (slope >= enter_call_term_slope) or (stresses[i] >= 1.08 if not np.isnan(stresses[i]) else False)
            # 2. Long PUT: Extreme market complacency + elevated tail risk demand -> hedge crash
            is_put_signal = (skew >= enter_put_skew) and (slope <= enter_put_term_slope)
            
            if is_call_signal or is_put_signal:
                opt_type = "call" if is_call_signal else "put"
                # Select At-The-Money (ATM) strike
                strike = round(spot, 0)
                dte = 45 # 45 DTE target
                pending_entry = {
                    "option_type": opt_type,
                    "strike": strike,
                    "dte": dte,
                    "signal_date": dt.strftime("%Y-%m-%d"),
                }
                    
        portfolio_history.append({"Date": dt, "portfolio_value": current_portfolio_value})

    df_port = pd.DataFrame(portfolio_history)
    df_port["daily_return"] = df_port["portfolio_value"].pct_change().fillna(0.0)
    
    # Calculate performance metrics
    total_days = (df_port["Date"].iloc[-1] - df_port["Date"].iloc[0]).days
    ann_factor = 365.25 / max(1, total_days)
    
    total_return = (df_port["portfolio_value"].iloc[-1] / df_port["portfolio_value"].iloc[0]) - 1.0
    cagr = (1.0 + total_return) ** ann_factor - 1.0
    
    daily_std = df_port["daily_return"].std()
    sharpe = (df_port["daily_return"].mean() / daily_std * np.sqrt(252)) if daily_std > 0 else 0.0
    
    # Information Ratio vs Benchmark Buy-and-Hold
    benchmark_ret = (df[underlying].iloc[-1] / df[underlying].iloc[0]) - 1.0
    df_port["bench_return"] = df[underlying].pct_change().fillna(0.0)
    diff_ret = df_port["daily_return"] - df_port["bench_return"]
    ir = (diff_ret.mean() / diff_ret.std() * np.sqrt(252)) if diff_ret.std() > 0 else 0.0
    
    # Max Drawdown
    cum_max = df_port["portfolio_value"].cummax()
    drawdowns = (df_port["portfolio_value"] - cum_max) / cum_max
    max_dd = abs(drawdowns.min())
    
    # Regime breakdown
    regime_results = {}
    for r_name, (r_start, r_end) in REGIMES.items():
        sub = df_port[(df_port["Date"] >= r_start) & (df_port["Date"] <= r_end)]
        if len(sub) > 10:
            sub_ret = (sub["portfolio_value"].iloc[-1] / sub["portfolio_value"].iloc[0]) - 1.0
            sub_std = sub["daily_return"].std()
            sub_sharpe = (sub["daily_return"].mean() / sub_std * np.sqrt(252)) if sub_std > 0 else 0.0
            regime_results[r_name] = {"net_return": float(sub_ret), "sharpe": float(sub_sharpe)}
        else:
            regime_results[r_name] = {"net_return": 0.0, "sharpe": 0.0}

    # Trade statistics
    df_trades = pd.DataFrame(trades)
    n_trades = len(df_trades)
    win_rate = float((df_trades["pnl"] > 0).mean()) if n_trades > 0 else 0.0
    avg_trade_pnl = float(df_trades["pnl"].mean()) if n_trades > 0 else 0.0
    
    # Gate check (GATE_VOL_TIMING.md)
    positive_regimes = sum(1 for r in regime_results.values() if r["net_return"] > 0)
    
    gate_checks = {
        "sharpe_gt_1": bool(sharpe > 1.0),
        "ir_gt_05": bool(ir > 0.5),
        "max_dd_lt_20": bool(max_dd < 0.20),
        "positive_all_5_regimes": bool(positive_regimes == 5),
        "cagr_gt_8": bool(cagr > 0.08),
    }
    is_go = all(gate_checks.values())

    return {
        "underlying": underlying,
        "holding_days": holding_days,
        "total_return": float(total_return),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "information_ratio": float(ir),
        "max_drawdown": float(max_dd),
        "n_trades": n_trades,
        "win_rate": float(win_rate),
        "avg_trade_pnl": float(avg_trade_pnl),
        "trades": trades,
        "regime_breakdown": regime_results,
        "positive_regimes_count": positive_regimes,
        "gate_checks": gate_checks,
        "verdict": "GO" if is_go else "NO-GO",
    }

def main():
    parser = argparse.ArgumentParser(description="Backtest Track 1 Volatility Timing Option Strategy")
    parser.add_argument("--holding-days", type=int, default=15, help="Holding period in trading days")
    parser.add_argument("--sweep", action="store_true", help="Run 36-cell parameter grid search")
    args = parser.parse_args()

    if not DATA_FILE.exists():
        print(f"Error: {DATA_FILE} not found. Run fetch_vol_complex.py first.")
        return

    df = pd.read_csv(DATA_FILE)
    print(f"Loaded Volatility Complex data: {len(df)} rows.")

    print("\n" + "=" * 60)
    print("  TRACK 1: VOLATILITY TIMING STRATEGY BACKTEST (LEVEL 2 OPTIONS)")
    print("=" * 60)

    if args.sweep:
        print("\nRunning pre-registered parameter sweep (36 cells)...")
        sweep_results = []
        for h in [5, 10, 15, 20]:
            for slope in [0.98, 1.02, 1.05]:
                for skew in [135.0, 140.0, 145.0]:
                    res = run_vol_timing_backtest(
                        df, underlying="SPY", holding_days=h,
                        enter_call_term_slope=slope, enter_put_skew=skew
                    )
                    sweep_results.append({
                        "holding_days": h, "slope_thresh": slope, "skew_thresh": skew,
                        "cagr": res["cagr"], "sharpe": res["sharpe"], "ir": res["information_ratio"],
                        "max_dd": res["max_drawdown"], "win_rate": res["win_rate"], "verdict": res["verdict"]
                    })
        df_sweep = pd.DataFrame(sweep_results)
        print(df_sweep.sort_values("sharpe", ascending=False).to_string(index=False))
        
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        sweep_file = OUT_DIR / "grid_sweep.json"
        df_sweep.to_json(sweep_file, orient="records", indent=2)
        print(f"\nGrid sweep results saved to {sweep_file}")
        return

    res_spy = run_vol_timing_backtest(df, underlying="SPY", holding_days=args.holding_days)
    res_qqq = run_vol_timing_backtest(df, underlying="QQQ", holding_days=args.holding_days)

    print("\n[SPY VOLATILITY TIMING RESULTS]")
    print(f"  CAGR:               {res_spy['cagr']*100:.2f}%")
    print(f"  Sharpe Ratio:       {res_spy['sharpe']:.2f}")
    print(f"  Information Ratio:  {res_spy['information_ratio']:.2f}")
    print(f"  Max Drawdown:       {res_spy['max_drawdown']*100:.2f}%")
    print(f"  Total Trades:       {res_spy['n_trades']} (Win Rate: {res_spy['win_rate']*100:.1f}%)")
    print(f"  Regimes Positive:   {res_spy['positive_regimes_count']} / 5")
    print(f"  Verdict:            {res_spy['verdict']}")

    print("\n[QQQ VOLATILITY TIMING RESULTS]")
    print(f"  CAGR:               {res_qqq['cagr']*100:.2f}%")
    print(f"  Sharpe Ratio:       {res_qqq['sharpe']:.2f}")
    print(f"  Information Ratio:  {res_qqq['information_ratio']:.2f}")
    print(f"  Max Drawdown:       {res_qqq['max_drawdown']*100:.2f}%")
    print(f"  Total Trades:       {res_qqq['n_trades']} (Win Rate: {res_qqq['win_rate']*100:.1f}%)")
    print(f"  Regimes Positive:   {res_qqq['positive_regimes_count']} / 5")
    print(f"  Verdict:            {res_qqq['verdict']}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "results.json"
    with open(out_file, "w") as f:
        json.dump({"spy": res_spy, "qqq": res_qqq}, f, indent=2)
    print(f"\nArtifact written to {out_file}")

if __name__ == "__main__":
    main()
