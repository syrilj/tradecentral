#!/usr/bin/env python3
"""Fetch float / shares-outstanding for the small-cap scan universe into
edge/data/float_data/float.csv.

Reads edge/data/1d_smallcap/ (written by fetch_smallcap_universe.py) to find
symbols whose last close is at or under FLOAT_FETCH_PRICE_CEILING, then
looks up float via yfinance's .info for just that subset -- the full
universe is ~8-11k tickers and .info is slow/rate-limited, so this narrows
to the price band the momentum scan cares about before paying that cost. A
symbol whose float can't be resolved is written with an empty float_shares
cell, never silently dropped or coerced to a number -- same rule as
edge/tools/data_sources.py's load_finra_short_vol().

Usage:
  edge/.venv-qlib/bin/python edge/tools/fetch_float_data.py
  edge/.venv-qlib/bin/python edge/tools/fetch_float_data.py --limit 30   # smoke test
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SMALLCAP_DIR = ROOT / "edge" / "data" / "1d_smallcap"
OUT_DIR = ROOT / "edge" / "data" / "float_data"
OUT_CSV = OUT_DIR / "float.csv"

FLOAT_FETCH_PRICE_CEILING = 25.0
MAX_RETRIES = 2
RETRY_SLEEP = 1.5
FIELDS = ["symbol", "float_shares", "shares_outstanding", "as_of_date"]


def candidates_under_ceiling() -> list[str]:
    out = []
    for path in sorted(SMALLCAP_DIR.glob("*.parquet")):
        try:
            df = pd.read_parquet(path, columns=["close"])
        except Exception:
            continue
        if df.empty:
            continue
        if float(df["close"].iloc[-1]) <= FLOAT_FETCH_PRICE_CEILING:
            out.append(path.stem)
    return out


def fetch_float(symbol: str) -> tuple[Optional[float], Optional[float]]:
    """Returns (float_shares, shares_outstanding); either may be None if
    yfinance has no value -- a missing value is real information (unknown),
    never coerced to 0 or dropped."""
    import yfinance as yf

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            info = yf.Ticker(symbol).get_info()
            float_shares = info.get("floatShares")
            shares_out = info.get("sharesOutstanding")
            return (
                float(float_shares) if float_shares is not None else None,
                float(shares_out) if shares_out is not None else None,
            )
        except Exception:
            time.sleep(RETRY_SLEEP * attempt)
    return (None, None)


def load_float_data(csv_path: Path = OUT_CSV) -> dict[str, Optional[float]]:
    """symbol -> float_shares, or None if unresolved. Never coerces a
    missing value to 0 or drops the row."""
    if not csv_path.exists():
        return {}
    out: dict[str, Optional[float]] = {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = row.get("float_shares", "")
            out[row["symbol"]] = float(raw) if raw not in ("", None) else None
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    symbols = candidates_under_ceiling()
    if args.limit:
        symbols = symbols[: args.limit]
    print(f"Fetching float for {len(symbols)} symbols at or under ${FLOAT_FETCH_PRICE_CEILING:.0f}")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = []
    known = 0
    for i, sym in enumerate(symbols):
        float_shares, shares_out = fetch_float(sym)
        if float_shares is not None:
            known += 1
        rows.append({
            "symbol": sym,
            "float_shares": "" if float_shares is None else float_shares,
            "shares_outstanding": "" if shares_out is None else shares_out,
            "as_of_date": today,
        })
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(symbols)} ({known} resolved)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nresolved {known} / {len(symbols)} floats")
    print(f"-> {OUT_CSV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
