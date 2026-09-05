#!/usr/bin/env python3
"""Fetch and build 15-year Volatility Complex dataset for Track 1 Volatility Timing.

Downloads:
  - ^VIX    (CBOE Volatility Index, 30-day)
  - ^VIX3M  (CBOE 3-Month Volatility Index)
  - ^VVIX   (CBOE Volatility of VIX Index)
  - ^VIX9D  (CBOE 9-Day Volatility Index)
  - ^SKEW   (CBOE Skew Index)
  - SPY     (SPDR S&P 500 ETF Trust)
  - QQQ     (Invesco QQQ Trust)

Computes:
  - term_slope: VIX / VIX3M
  - short_stress: VIX9D / VIX
  - vol_of_vol_ratio: VVIX / VIX
  - tail_risk: SKEW
  - spy_ret_5d, qqq_ret_5d
  - spy_realized_vol_20d (annualized)
  - vix_vrp: VIX - spy_realized_vol_20d

Usage:
  python3 edge/tools/fetch_vol_complex.py
"""
import argparse
from datetime import date, timedelta
from pathlib import Path
import pandas as pd


def _default_end() -> str:
    """Tomorrow, so today's close is inside yfinance's half-open window.

    This used to be the literal "2026-07-30". Every later run re-truncated the
    volatility complex back to that date, so the regime read's VIX, term slope
    and tail risk silently froze in July while the header still labelled the
    row as the current vol regime -- and a "refresh" moved the data backwards.
    """
    return (date.today() + timedelta(days=1)).isoformat()
import numpy as np
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
OUT_FILE = ROOT / "edge" / "data" / "vol_complex.csv"

VOL_TICKERS = {
    "VIX": "^VIX",
    "VIX3M": "^VIX3M",
    "VVIX": "^VVIX",
    "VIX9D": "^VIX9D",
    "SKEW": "^SKEW",
    "SPY": "SPY",
    "QQQ": "QQQ",
}

def fetch_vol_data(start_date: str = "2010-01-01", end_date: str | None = None) -> pd.DataFrame:
    end_date = end_date or _default_end()
    print(f"Fetching volatility complex from yfinance ({start_date} to {end_date})...")
    data_frames = {}
    
    for name, ticker in VOL_TICKERS.items():
        try:
            df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df = df['Close']
            else:
                df = df[['Close']]
            if isinstance(df, pd.DataFrame):
                s = df.iloc[:, 0]
            else:
                s = df
            s.name = name
            data_frames[name] = s
            print(f"  [✓] {name} ({ticker}): {len(s)} rows ({s.index[0].strftime('%Y-%m-%d')} -> {s.index[-1].strftime('%Y-%m-%d')})")
        except Exception as e:
            print(f"  [X] Failed fetching {name} ({ticker}): {e}")
            
    df_all = pd.DataFrame(data_frames).ffill().dropna(subset=["VIX", "SPY"])
    
    # Compute derived features
    df_all["term_slope"] = df_all["VIX"] / df_all["VIX3M"]
    df_all["short_stress"] = df_all["VIX9D"] / df_all["VIX"]
    df_all["vol_of_vol_ratio"] = df_all["VVIX"] / df_all["VIX"]
    df_all["tail_risk"] = df_all["SKEW"]
    
    # Returns & Realized Volatility
    df_all["spy_ret_1d"] = df_all["SPY"].pct_change()
    df_all["qqq_ret_1d"] = df_all["QQQ"].pct_change()
    df_all["spy_ret_5d"] = df_all["SPY"].pct_change(5)
    df_all["qqq_ret_5d"] = df_all["QQQ"].pct_change(5)
    df_all["spy_ret_20d"] = df_all["SPY"].pct_change(20)
    df_all["qqq_ret_20d"] = df_all["QQQ"].pct_change(20)
    
    df_all["spy_realized_vol_20d"] = df_all["spy_ret_1d"].rolling(20).std() * np.sqrt(252) * 100
    df_all["vix_vrp"] = df_all["VIX"] - df_all["spy_realized_vol_20d"]
    
    # Clean up index
    df_all.index.name = "Date"
    df_all = df_all.reset_index()
    return df_all

def main():
    parser = argparse.ArgumentParser(description="Fetch Volatility Complex Dataset")
    parser.add_argument("--start", type=str, default="2010-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date YYYY-MM-DD (default: tomorrow, so today's close is included)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print summary without writing CSV")
    args = parser.parse_args()

    df = fetch_vol_data(start_date=args.start, end_date=args.end)
    print(f"\nDataset shape: {df.shape}")
    print("Sample rows:")
    print(df.tail(5)[["Date", "VIX", "term_slope", "short_stress", "vol_of_vol_ratio", "tail_risk", "vix_vrp"]])

    if not args.dry_run:
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(OUT_FILE, index=False)
        print(f"\nSaved Volatility Complex dataset to {OUT_FILE}")

if __name__ == "__main__":
    main()
