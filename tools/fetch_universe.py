#!/usr/bin/env python3
"""Fetch OHLCV for edge Step 5 widened universe into edge/data/{1h,1d}/.

Usage (from alltrading/):
  python3 edge/tools/fetch_universe.py              # 1h + 1d
  python3 edge/tools/fetch_universe.py --interval 1d
  python3 edge/tools/fetch_universe.py --symbols SPY,NVDA,AAPL

Writes parquet files with DatetimeIndex and columns open/high/low/close/volume.
Does not overwrite a file unless the new pull has more rows or --force is set.

Honest limits:
  - Yahoo 1h history is typically ~730 days. This script records the actual
    span per symbol in edge/data/FETCH_MANIFEST.json.
  - Failures are listed; partial success is OK so long as ≥40 1h names land.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]  # alltrading/
EDGE = ROOT / "edge"
CFG = EDGE / "config" / "universe_wide.json"
OUT = EDGE / "data"


def _load_symbols(path: Path) -> List[str]:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    # de-dupe preserving order
    seen = set()
    out: List[str] = []
    for s in cfg["symbols"]:
        s = s.upper().strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    # yfinance sometimes returns 'adj close'
    rename = {}
    for c in list(df.columns):
        if c in ("adj close", "adj_close"):
            rename[c] = "close"
    if rename:
        df = df.rename(columns=rename)
    need = ["open", "high", "low", "close", "volume"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns {missing}; got {list(df.columns)}")
    out = df[need].astype(float).copy()
    out.index = pd.to_datetime(out.index)
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.dropna(subset=["close"])
    return out


def fetch_one(symbol: str, interval: str) -> pd.DataFrame:
    import yfinance as yf

    # 1h: max practical free window ~730d; use period not start to avoid empty
    if interval == "1h":
        raw = yf.download(
            symbol,
            period="730d",
            interval="1h",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    elif interval == "1d":
        raw = yf.download(
            symbol,
            period="10y",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    else:
        raise ValueError(interval)
    return _normalize(raw)


def maybe_write(path: Path, df: pd.DataFrame, force: bool) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        old = pd.read_parquet(path)
        if len(df) <= len(old):
            return "kept_existing"
    df.to_parquet(path)
    return "wrote"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interval", choices=("1h", "1d", "both"), default="both")
    ap.add_argument("--symbols", default="", help="Comma list override")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.35, help="Seconds between Yahoo calls")
    ap.add_argument("--config", type=Path, default=CFG)
    args = ap.parse_args(argv)

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else _load_symbols(args.config)
    )
    intervals = ["1h", "1d"] if args.interval == "both" else [args.interval]

    manifest: Dict[str, object] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
        "symbols_requested": symbols,
        "intervals": intervals,
        "results": {},
    }

    ok_1h = 0
    for interval in intervals:
        for sym in symbols:
            key = f"{interval}:{sym}"
            try:
                df = fetch_one(sym, interval)
                if df.empty:
                    manifest["results"][key] = {"status": "empty"}
                    print(f"EMPTY  {key}")
                else:
                    path = OUT / interval / f"{sym}.parquet"
                    action = maybe_write(path, df, args.force)
                    span = {
                        "status": "ok",
                        "action": action,
                        "n": int(len(df)),
                        "start": str(df.index.min()),
                        "end": str(df.index.max()),
                        "path": str(path.relative_to(EDGE)),
                    }
                    manifest["results"][key] = span
                    if interval == "1h":
                        ok_1h += 1
                    print(f"OK     {key} n={len(df)} {df.index.min().date()}→{df.index.max().date()} ({action})")
            except Exception as e:
                manifest["results"][key] = {"status": "error", "error": str(e)}
                print(f"ERROR  {key}: {e}", file=sys.stderr)
            time.sleep(args.sleep)

    OUT.mkdir(parents=True, exist_ok=True)
    man_path = OUT / "FETCH_MANIFEST.json"
    man_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nManifest → {man_path}")
    print(f"1h successes: {ok_1h} / {len(symbols)}")
    if ok_1h < 40:
        print(
            "WARNING: fewer than 40 1h symbols landed. Re-run with --force after fixing "
            "network / rate limits before claiming Step 5 acceptance.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
