#!/usr/bin/env python3
"""Fetch and build FINRA Daily Short Volume dataset for Track 2 Factor Engine.

Ingests daily FINRA consolidated short volume files (RegSho CNMS):
  URL pattern: http://regsho.finra.org/CNMSshvol{YYYYMMDD}.txt

Fields extracted:
  - Date (YYYY-MM-DD)
  - Symbol
  - ShortVolume
  - ShortExemptVolume
  - TotalVolume
  - short_ratio: ShortVolume / TotalVolume

Computes cross-sectional and temporal factors:
  - short_ratio_5d_sma: 5-day moving average of short_ratio
  - short_ratio_z: Cross-sectional z-score of short_ratio
  - short_ratio_mom5: 5-day change in short_ratio

Usage:
  python3 edge/tools/fetch_finra_short_vol.py --days 30
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import io
from pathlib import Path
import urllib.request
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_FILE = ROOT / "edge" / "data" / "finra_short_vol.csv"

import ssl
import time

def fetch_finra_day(date_str: str) -> pd.DataFrame | None:
    url = f"http://regsho.finra.org/CNMSshvol{date_str}.txt"
    ctx = ssl._create_unverified_context()
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                content = resp.read().decode("utf-8", errors="ignore")
            if content.startswith("<!DOCTYPE") or "Too Many Requests" in content:
                time.sleep(1.0 * (attempt + 1))
                continue
            df = pd.read_csv(io.StringIO(content), sep="|")
            if "Symbol" in df.columns and "ShortVolume" in df.columns and "TotalVolume" in df.columns:
                df = df.dropna(subset=["Symbol", "ShortVolume", "TotalVolume"])
                df["ShortVolume"] = pd.to_numeric(df["ShortVolume"], errors="coerce").fillna(0)
                df["TotalVolume"] = pd.to_numeric(df["TotalVolume"], errors="coerce").fillna(1)
                df = df[df["TotalVolume"] > 0]
                df["short_ratio"] = df["ShortVolume"] / df["TotalVolume"]
                df["Date"] = pd.to_datetime(date_str, format="%Y%m%d")
                return df[["Date", "Symbol", "ShortVolume", "TotalVolume", "short_ratio"]]
        except Exception:
            time.sleep(1.0 * (attempt + 1))
    return None

def fetch_finra_range(days: int = 30) -> pd.DataFrame:
    print(f"Fetching FINRA short volume data for the last {days} calendar days...")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    records = []
    curr = start_date
    succ_count = 0
    
    while curr <= end_date:
        if curr.weekday() < 5: # Weekdays only
            ds = curr.strftime("%Y%m%d")
            df_day = fetch_finra_day(ds)
            if df_day is not None and not df_day.empty:
                records.append(df_day)
                succ_count += 1
                print(f"  [✓] {curr.strftime('%Y-%m-%d')}: {len(df_day)} symbols loaded")
        curr += timedelta(days=1)
        
    if not records:
        print("Warning: No daily FINRA files retrieved.")
        return pd.DataFrame()
        
    df_all = pd.concat(records, ignore_index=True)
    df_all["Symbol"] = df_all["Symbol"].astype(str).str.upper()
    return df_all

def main():
    parser = argparse.ArgumentParser(description="Fetch FINRA Daily Short Volume Data")
    parser.add_argument("--days", type=int, default=30, help="Number of calendar days to fetch")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and summarize without saving")
    args = parser.parse_args()

    df = fetch_finra_range(days=args.days)
    if df.empty:
        print("No data fetched.")
        return

    print(f"\nTotal FINRA short volume records: {len(df)}")
    print(f"Unique symbols: {df['Symbol'].nunique()}")
    print(f"Date range: {df['Date'].min().strftime('%Y-%m-%d')} -> {df['Date'].max().strftime('%Y-%m-%d')}")
    print("\nSample records:")
    print(df.head(10).to_string(index=False))

    if not args.dry_run:
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(OUT_FILE, index=False)
        print(f"\nSaved FINRA short volume data to {OUT_FILE}")

if __name__ == "__main__":
    main()
