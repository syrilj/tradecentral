#!/usr/bin/env python3
"""Capture option-chain open-interest snapshots for the options dashboard.

The live LSE chain (``/vault/options/chain``) carries greeks, IV, volume and
premium but **no open-interest field at all** — for any symbol. Every GEX number
on the Options tab is therefore built from OI backfilled by exact OCC match out
of ``edge/data/option_chains/date=<D>/<SYMBOL>.parquet`` (see
``_fetch_live_option_inputs`` in ``tools/api_server.py``).

A symbol with no snapshot gets ``open_interest: "unavailable"``, every contract
keeps OI 0, the ``min_open_interest`` filter then rejects the whole chain, and
the tab renders empty walls / flip / GEX. That is the ORCL failure mode.

This writes those snapshots. The schema matches the existing captures exactly
(a yfinance chain dump plus asof/spot/right/dte columns), so the reader needs no
changes.

Usage:
  python edge/tools/backfill_option_oi.py ORCL
  python edge/tools/backfill_option_oi.py --universe          # every covered name
  python edge/tools/backfill_option_oi.py AAPL NVDA --max-dte 90
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from pathlib import Path
import sys

import pandas as pd

EDGE_DIR = Path(__file__).resolve().parents[1]
CHAIN_ROOT = EDGE_DIR / "data" / "option_chains"

# Column order and dtypes of the existing snapshots. Kept explicit so a schema
# drift here fails loudly instead of silently producing unreadable captures.
COLUMNS = [
    "asof_date", "captured_utc", "symbol", "spot", "right", "expiry", "dte",
    "strike", "bid", "ask", "lastPrice", "volume", "openInterest",
    "impliedVolatility", "inTheMoney", "contractSymbol", "lastTradeDate",
]


def _existing_universe() -> list[str]:
    """Every symbol ever captured, across all snapshot days.

    Deliberately not "the latest day": once this tool writes a partial capture
    for today, that day becomes the latest and a naive read would shrink the
    universe to whatever was just written.
    """
    return sorted({p.stem for p in CHAIN_ROOT.glob("date=*/*.parquet")})


def _spot_from(ticker) -> float:
    """Last close. yfinance fast_info is cheapest; fall back to a 1d history."""
    try:
        value = float(ticker.fast_info["last_price"])
        if value > 0:
            return value
    except Exception:
        pass
    hist = ticker.history(period="1d")
    if hist.empty:
        raise RuntimeError("no price history")
    return float(hist["Close"].iloc[-1])


def capture(symbol: str, *, asof: date, max_dte: int) -> pd.DataFrame:
    import yfinance as yf

    symbol = symbol.upper()
    ticker = yf.Ticker(symbol)
    expiries = list(ticker.options or [])
    if not expiries:
        raise RuntimeError("provider returned no expiries")

    spot = _spot_from(ticker)
    captured = datetime.now(timezone.utc).isoformat()
    frames: list[pd.DataFrame] = []

    for expiry in expiries:
        dte = (date.fromisoformat(expiry) - asof).days
        if dte < 0 or dte > max_dte:
            continue
        chain = ticker.option_chain(expiry)
        for right, side in (("C", chain.calls), ("P", chain.puts)):
            if side is None or side.empty:
                continue
            frame = side.copy()
            frame["asof_date"] = asof.isoformat()
            frame["captured_utc"] = captured
            frame["symbol"] = symbol
            frame["spot"] = spot
            frame["right"] = right
            frame["expiry"] = expiry
            frame["dte"] = dte
            frames.append(frame)

    if not frames:
        raise RuntimeError(f"no expiries within {max_dte}d")

    out = pd.concat(frames, ignore_index=True)
    for column in COLUMNS:
        if column not in out.columns:
            out[column] = pd.NA
    out = out[COLUMNS]
    out["dte"] = out["dte"].astype("int64")
    for column in ("spot", "strike", "bid", "ask", "lastPrice", "volume",
                   "openInterest", "impliedVolatility"):
        out[column] = pd.to_numeric(out[column], errors="coerce").astype("float64")
    out["inTheMoney"] = out["inTheMoney"].fillna(False).astype(bool)
    out["lastTradeDate"] = pd.to_datetime(out["lastTradeDate"], utc=True, errors="coerce")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="*", help="symbols to capture")
    parser.add_argument("--universe", action="store_true",
                        help="capture every symbol in the latest existing snapshot")
    parser.add_argument("--max-dte", type=int, default=60)
    parser.add_argument("--asof", default=None, help="YYYY-MM-DD (default: today UTC)")
    args = parser.parse_args(argv)

    asof = date.fromisoformat(args.asof) if args.asof else datetime.now(timezone.utc).date()
    symbols = [s.upper() for s in args.symbols]
    if args.universe:
        symbols = sorted(set(symbols) | set(_existing_universe()))
    if not symbols:
        parser.error("pass symbols, or --universe")

    out_dir = CHAIN_ROOT / f"date={asof.isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    ok, failed = 0, []
    for symbol in symbols:
        try:
            frame = capture(symbol, asof=asof, max_dte=args.max_dte)
        except Exception as exc:  # provider gaps are per-symbol, not fatal
            failed.append(symbol)
            print(f"[skip] {symbol}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        frame.to_parquet(out_dir / f"{symbol}.parquet")
        with_oi = int((frame["openInterest"] > 0).sum())
        ok += 1
        print(f"[ok]   {symbol}: {len(frame)} contracts, {with_oi} with OI>0 -> {out_dir.name}")

    print(f"\n{ok} captured, {len(failed)} failed{': ' + ', '.join(failed) if failed else ''}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
