#!/usr/bin/env python3
"""Fetch a bounded rolling-window daily OHLCV panel for a broad small-cap
candidate universe into edge/data/1d_smallcap/.

Universe comes from NASDAQ Trader's public symbol directory (no auth) --
NASDAQ-listed + NYSE/AMEX-listed common stock, ETFs and test issues
excluded. Unlike edge/tools/fetch_universe_wide.py (which keeps full
history for the qlib factor pipeline), this keeps only the trailing
~70 sessions per symbol: this pipeline feeds a nightly momentum pre-scan
(edge/tools/momentum_scan.py), not a backtest, and bounding the window
keeps runtime and storage flat regardless of universe size.

Usage:
  edge/.venv-qlib/bin/python edge/tools/fetch_smallcap_universe.py
  edge/.venv-qlib/bin/python edge/tools/fetch_smallcap_universe.py --limit 30   # smoke test
  edge/.venv-qlib/bin/python edge/tools/fetch_smallcap_universe.py --force
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "edge" / "data" / "1d_smallcap"
MANIFEST = OUT / "FETCH_MANIFEST_SMALLCAP.json"

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

LOOKBACK_SESSIONS = 70
CHUNK_SIZE = 100
MAX_RETRIES = 3
RETRY_SLEEP = 2.0
NEED = ["open", "high", "low", "close", "volume"]

START = (datetime.now(timezone.utc) - timedelta(days=int(LOOKBACK_SESSIONS * 1.6))).strftime("%Y-%m-%d")


def _parse_symbol_directory(text: str, *, symbol_col: str, exchange_note: str) -> List[str]:
    """Pipe-delimited NASDAQ Trader format: header row, data rows, a
    'File Creation Time' footer row. Column-name lookup, not positional --
    tolerates minor column reordering."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    header = lines[0].split("|")
    try:
        sym_idx = header.index(symbol_col)
    except ValueError:
        print(f"  {exchange_note}: unexpected header {header!r}, skipping")
        return []
    etf_idx = header.index("ETF") if "ETF" in header else None
    test_idx = header.index("Test Issue") if "Test Issue" in header else None
    out = []
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            continue
        fields = line.split("|")
        if len(fields) <= sym_idx:
            continue
        if etf_idx is not None and etf_idx < len(fields) and fields[etf_idx].strip().upper() == "Y":
            continue
        if test_idx is not None and test_idx < len(fields) and fields[test_idx].strip().upper() == "Y":
            continue
        symbol = fields[sym_idx].strip()
        if symbol and "$" not in symbol and "." not in symbol:
            out.append(symbol)
    return out


def download_symbol_directory() -> List[str]:
    """Union of NASDAQ-listed + NYSE/AMEX-listed common stock symbols.
    Raises if BOTH sources fail -- an empty universe must never be mistaken
    for 'market has zero small caps today', matching the return-real-data-
    or-raise rule in edge/tools/data_sources.py."""
    symbols: set[str] = set()
    sources = [
        (NASDAQ_LISTED_URL, "Symbol", "nasdaqlisted"),
        (OTHER_LISTED_URL, "ACT Symbol", "otherlisted"),
    ]
    failures = []
    for url, symbol_col, note in sources:
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            text = resp.text
            found = _parse_symbol_directory(text, symbol_col=symbol_col, exchange_note=note)
            print(f"  {note}: {len(found)} symbols")
            symbols.update(found)
        except Exception as e:
            failures.append(f"{note}: {e}")
    if not symbols:
        raise RuntimeError("Could not fetch any symbol directory -- " + "; ".join(failures))
    if failures:
        print(f"  WARNING: partial symbol directory ({'; '.join(failures)})")
    return sorted(symbols)


def _chunks(seq: List[str], n: int) -> List[List[str]]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Match edge/data/1d_wide/ schema: DatetimeIndex, open/high/low/close/volume."""
    if df is None or df.empty:
        return pd.DataFrame(columns=NEED)
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [str(c[0]).lower() for c in out.columns]
    else:
        out.columns = [str(c).lower() for c in out.columns]
    rename = {c: "close" for c in out.columns if c in ("adj close", "adj_close")}
    if rename:
        out = out.rename(columns=rename)
    missing = [c for c in NEED if c not in out.columns]
    if missing:
        return pd.DataFrame(columns=NEED)
    out = out[NEED].astype(float)
    out.index = pd.to_datetime(out.index)
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.dropna(subset=["close"])
    return out.tail(LOOKBACK_SESSIONS)


def fetch_chunk(symbols: List[str]) -> Dict[str, pd.DataFrame]:
    import yfinance as yf

    if len(symbols) == 1:
        raw = yf.download(symbols[0], start=START, interval="1d", auto_adjust=True, progress=False, threads=False)
        return {symbols[0]: _normalize(raw)}

    raw = yf.download(
        symbols, start=START, interval="1d",
        auto_adjust=True, group_by="ticker", threads=True, progress=False,
    )
    out: Dict[str, pd.DataFrame] = {}
    top = set(raw.columns.get_level_values(0)) if isinstance(raw.columns, pd.MultiIndex) else set()
    for sym in symbols:
        out[sym] = _normalize(raw[sym]) if sym in top else pd.DataFrame(columns=NEED)
    return out


def fetch_one_retry(symbol: str, max_retries: int = MAX_RETRIES) -> pd.DataFrame:
    import yfinance as yf

    for attempt in range(1, max_retries + 1):
        try:
            raw = yf.download(symbol, start=START, interval="1d", auto_adjust=True, progress=False, threads=False)
            df = _normalize(raw)
            if not df.empty:
                return df
        except Exception:
            pass
        time.sleep(RETRY_SLEEP * attempt)
    return pd.DataFrame(columns=NEED)


def maybe_write(path: Path, df: pd.DataFrame, force: bool) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        old = pd.read_parquet(path)
        if len(df) <= len(old):
            return "kept_existing"
    df.to_parquet(path)
    return "written"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="smoke-test: only fetch the first N symbols")
    parser.add_argument("--force", action="store_true", help="overwrite even if the new pull has fewer rows")
    args = parser.parse_args(argv)

    print("Downloading NASDAQ Trader symbol directory...")
    symbols = download_symbol_directory()
    if args.limit:
        symbols = symbols[: args.limit]
    print(f"Universe: {len(symbols)} symbols")

    manifest: Dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expected_universe_size": len(symbols),
        "results": {},
    }

    landed = 0
    missed: List[str] = []
    for i, chunk in enumerate(_chunks(symbols, CHUNK_SIZE)):
        print(f"  chunk {i + 1}: {len(chunk)} symbols")
        fetched = fetch_chunk(chunk)
        for sym in chunk:
            df = fetched.get(sym, pd.DataFrame(columns=NEED))
            if df.empty:
                missed.append(sym)
                continue
            status = maybe_write(OUT / f"{sym}.parquet", df, args.force)
            manifest["results"][sym] = {"status": status, "n_rows": len(df)}
            landed += 1

    for sym in missed:
        df = fetch_one_retry(sym)
        if df.empty:
            manifest["results"][sym] = {"status": "empty_or_failed"}
            continue
        status = maybe_write(OUT / f"{sym}.parquet", df, args.force)
        manifest["results"][sym] = {"status": status, "n_rows": len(df)}
        landed += 1

    manifest["summary"] = {
        "landed": landed,
        "expected": len(symbols),
        "landed_fraction": landed / len(symbols) if symbols else 0.0,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nlanded {landed} / {len(symbols)} ({manifest['summary']['landed_fraction']:.1%})")
    print(f"Manifest -> {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
