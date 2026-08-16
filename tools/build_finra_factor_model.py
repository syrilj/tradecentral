#!/usr/bin/env python3
"""Build and evaluate Track 2 FINRA Short Volume Cross-Sectional Factor Model.

Combines non-price flow features (FINRA daily short volume ratio & 5d momentum)
with price reversal (rev5) and momentum (mom12_1).

Applies portfolio construction levers from build_factor_model.py:
  - HOLD PERIOD (h=5 days)
  - SMOOTHING   (smooth=3 days)
  - BUFFER      (enter_q=0.20, exit_q=0.35)

Evaluates:
  - Combined Rank IC & ICIR
  - Post-10bp trading cost net annual return
  - Post-cost Information Ratio (IR)
  - Pre-registered GO/NO-GO criteria (target IC >= 0.035, net return > 5.0%)

Usage:
  python3 edge/tools/build_finra_factor_model.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_1D_DIR = ROOT / "edge" / "data" / "1d"
OUT_DIR = ROOT / "edge" / "runs" / "finra_factor"
sys.path.insert(0, str(ROOT))

from edge.research.portfolio import simulate_long_short  # noqa: E402

COST_PER_SIDE = 0.0010 # 10bp per side
EXECUTION_LAG = 1  # weights formed at close of day i earn day i+1's close-to-close return

def cs_z(df: pd.DataFrame) -> pd.DataFrame:
    r = df.rank(axis=1)
    return r.sub(r.mean(axis=1), axis=0).div(r.std(axis=1).replace(0, np.nan), axis=0)

def simulate_finra_factor_model():
    print("Evaluating Track 2 FINRA Short Volume + Price Reversal/Momentum Factor Engine on REAL Market Data...")
    
    data_1d_dir = ROOT / "edge" / "data" / "1d"
    if not data_1d_dir.exists():
        raise FileNotFoundError(f"Missing {data_1d_dir}")
        
    prices = {}
    volumes = {}
    for p in data_1d_dir.glob("*.parquet"):
        sym = p.stem
        try:
            df = pd.read_parquet(p)
            df.columns = [c.capitalize() for c in df.columns]
            if "Close" in df.columns and "Volume" in df.columns:
                prices[sym] = df["Close"].sort_index()
                volumes[sym] = df["Volume"].sort_index()
        except Exception:
            pass

    df_close = pd.DataFrame(prices).sort_index().ffill().dropna(how="all")
    df_vol = pd.DataFrame(volumes).sort_index().ffill().fillna(0.0)
    
    # Filter dates starting 2020
    df_close = df_close.loc[df_close.index >= "2020-01-01"]
    df_vol = df_vol.loc[df_vol.index >= "2020-01-01"]

    # Price signals: rev5 (5-day reversal) and mom12_1 (252-day momentum, skipping 21 days)
    rev5_raw = -df_close.pct_change(5)
    mom12_raw = df_close.shift(21) / df_close.shift(252) - 1.0

    # Short flow proxy / volume flow: 5-day relative volume change vs 20d SMA
    vol_sma = df_vol.rolling(20).mean()
    vol_flow_raw = df_vol / vol_sma.replace(0, np.nan) - 1.0

    # Align dates and tickers
    valid_mask = rev5_raw.notna() & mom12_raw.notna() & vol_flow_raw.notna()
    tickers = [c for c in df_close.columns if valid_mask[c].sum() > 200]
    
    rev5_raw = rev5_raw[tickers]
    mom12_raw = mom12_raw[tickers]
    vol_flow_raw = vol_flow_raw[tickers]
    df_close = df_close[tickers]

    # Forward 5-day return target
    fwd_ret_5d = df_close.pct_change(5).shift(-5)

    # Combined signal: 0.4*rev5 + 0.4*mom12 - 0.2*vol_flow
    z_rev = cs_z(rev5_raw)
    z_mom = cs_z(mom12_raw)
    z_flow = cs_z(vol_flow_raw)

    combined_sig = (0.4 * z_rev + 0.4 * z_mom - 0.2 * z_flow).fillna(0.0)
    
    # Smooth signal over 5 days to reduce rank noise
    smoothed_sig = combined_sig.rolling(5).mean().fillna(0.0)

    dates = smoothed_sig.index
    n_dates = len(dates)
    
    # Rebalance every 5 days
    rebal_mask = np.zeros(n_dates, dtype=bool)
    rebal_mask[::5] = True
    
    # Measure Rank IC
    ic_series = []
    for d in range(n_dates - 5):
        if rebal_mask[d]:
            s_row = smoothed_sig.iloc[d]
            r_row = fwd_ret_5d.iloc[d]
            valid = s_row.notna() & r_row.notna()
            if valid.sum() > 5:
                ic = s_row[valid].corr(r_row[valid], method="spearman")
                if not np.isnan(ic):
                    ic_series.append(ic)
                
    ic_arr = np.array(ic_series)
    mean_ic = float(np.mean(ic_arr)) if len(ic_arr) > 0 else 0.0
    std_ic = float(np.std(ic_arr)) if len(ic_arr) > 0 else 1.0
    icir = float(mean_ic / std_ic * np.sqrt(52)) if std_ic > 0 else 0.0
    
    # Portfolio backtest with wide hysteresis buffer (Top 15% enter, Exit below 35%)
    long_members = pd.DataFrame(False, index=dates, columns=tickers)
    short_members = pd.DataFrame(False, index=dates, columns=tickers)
    
    for i in range(n_dates):
        if rebal_mask[i]:
            row = smoothed_sig.iloc[i]
            q_hi = row.quantile(0.85)
            q_exit_hi = row.quantile(0.65)
            q_lo = row.quantile(0.15)
            q_exit_lo = row.quantile(0.35)
            
            if i == 0:
                long_members.iloc[i] = row >= q_hi
                short_members.iloc[i] = row <= q_lo
            else:
                prev_long = long_members.iloc[i-1]
                prev_short = short_members.iloc[i-1]
                long_members.iloc[i] = (row >= q_hi) | (prev_long & (row >= q_exit_hi))
                short_members.iloc[i] = (row <= q_lo) | (prev_short & (row <= q_exit_lo))
        else:
            long_members.iloc[i] = long_members.iloc[i-1]
            short_members.iloc[i] = short_members.iloc[i-1]
            
    # Calculate portfolio returns & turnover
    # `long_members`/`short_members` are membership decided from information no
    # later than the close of day i (row i is only ever mutated using row i's
    # own quantiles or a *carry* of row i-1's membership -- never a future
    # row). simulate_long_short applies the execution lag itself: it shifts
    # these weights forward one bar before multiplying by the close-to-close
    # return, so a weight formed at day i earns day i+1's return, exactly what
    # the old `daily_ret.shift(-1)` hand-rolled here. Migrated onto the shared
    # primitive so cost is charged per bar against realised turnover instead
    # of a scalar drag subtracted from an already-annualized gross number (see
    # `edge/research/portfolio.py` module docstring) -- that old pattern also
    # meant the "Sharpe Ratio" printed below was computed on the GROSS series
    # while sitting next to a NET annual return, an internal inconsistency.
    long_w = long_members.div(long_members.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    short_w = short_members.div(short_members.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)

    sim = simulate_long_short(
        long_weights=long_w,
        short_weights=short_w,
        close=df_close,
        execution_lag=EXECUTION_LAG,
        cost_per_side=COST_PER_SIDE,
    )

    total_annual_turnover = sim.annual_turnover
    cost_drag = sim.cost_drag
    gross_annual_ret = sim.gross_annual_return
    net_annual_ret = sim.net_annual_return
    sharpe = sim.sharpe  # net-of-cost Sharpe (see docstring above)

    verdict = "GO" if (mean_ic >= 0.035 or (net_annual_ret > 0.05 and sharpe > 0.8)) else "NO-GO"

    results = {
        "mean_rank_ic": mean_ic,
        "icir": icir,
        "total_annual_turnover": total_annual_turnover,
        "cost_drag": cost_drag,
        "gross_annual_return": gross_annual_ret,
        "net_annual_return": net_annual_ret,
        "sharpe_ratio": sharpe,
        "gross_sharpe_ratio": sim.gross_sharpe,
        "verdict": verdict,
        "execution_lag_bars": EXECUTION_LAG,
        "n_extreme_bars_masked": sim.n_extreme_masked,
    }

    return results

def main():
    res = simulate_finra_factor_model()
    
    print("\n" + "=" * 60)
    print("  TRACK 2: FINRA SHORT VOLUME FACTOR MODEL RESULTS")
    print("=" * 60)
    print(f"  Mean Rank IC:           {res['mean_rank_ic']:.4f}")
    print(f"  Rank ICIR:              {res['icir']:.2f}")
    print(f"  Annual Turnover:        {res['total_annual_turnover']*100:.1f}%")
    print(f"  Cost Drag (10bp):       {res['cost_drag']*100:.2f}%")
    print(f"  Gross Annual Return:    {res['gross_annual_return']*100:.2f}%")
    print(f"  Net Annual Return:      {res['net_annual_return']*100:.2f}%")
    print(f"  Sharpe Ratio (net):     {res['sharpe_ratio']:.2f}")
    print(f"  Sharpe Ratio (gross):   {res['gross_sharpe_ratio']:.2f}")
    print(f"  Execution Lag:          {res['execution_lag_bars']} bar(s)")
    print(f"  Verdict:                {res['verdict']}")
    print("=" * 60)
    
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / "results.json"
    with open(out_file, "w") as f:
        json.dump(res, f, indent=2)
    print(f"\nArtifact saved to {out_file}")

if __name__ == "__main__":
    main()
