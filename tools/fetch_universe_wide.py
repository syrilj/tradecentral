#!/usr/bin/env python3
"""Fetch daily OHLCV for the GATE_XS3 wide candidate pool into edge/data/1d_wide/.

Usage (from alltrading/, with the qlib venv -- see edge/docs/GATE_XS3.md):
  edge/.venv-qlib/bin/python edge/tools/fetch_universe_wide.py
  edge/.venv-qlib/bin/python edge/tools/fetch_universe_wide.py --limit 30   # smoke test
  edge/.venv-qlib/bin/python edge/tools/fetch_universe_wide.py --force

Writes parquet files with DatetimeIndex and columns open/high/low/close/volume --
schema-identical to edge/data/1d/ (READ-ONLY, untouched by this tool; this is a
wholly separate wide pool built for edge/docs/GATE_XS3.md's universe-breadth
test, alongside the existing 60-name pool, not a replacement for it). Does not
overwrite a file unless the new pull has more rows or --force is set.

Honest limits
-------------
  - This is a *candidate pool assembled in 2026*: the tickers below are chosen
    today, with full knowledge of which companies are still listed and liquid.
    Any company that delisted, went bankrupt, or was acquired and is no longer
    tracked by Yahoo Finance is absent from this list, and no amount of
    resilience in this script can recover it. GATE_XS3.md's point-in-time
    universe rule (edge/tools/qlib_ingest_wide.py) fixes *when* a surviving
    name enters the ranked universe -- it does not fix this. See GATE_XS3.md's
    "Survivorship" section: reduced, not eliminated.
  - A few tickers below have since been renamed (e.g. Block Inc: SQ -> XYZ) and
    are listed under their CURRENT symbol so Yahoo's continuous history is
    retrieved. A few others were delisted via acquisition during the sample
    (e.g. Pioneer Natural Resources / PXD into XOM in 2024; Activision / ATVI
    into MSFT in 2023) and are left in deliberately: yfinance either returns
    their history up to delisting or fails cleanly, and either outcome is
    reported honestly in the manifest below, never silently dropped.
  - Real listing dates are expected and correct: ARM (2023-09), PLTR (2020-09),
    RBLX (2021-03), ABNB (2020-12), COIN (2021-04), and similar recent IPOs
    will have short histories. This script does NOT pad or forward-fill to a
    common start date -- a short history is correct data, not a bug.
  - Failures (rate limits, bad symbols, delistings, empty responses) are
    recorded per-symbol in FETCH_MANIFEST_WIDE.json, never silently dropped.
    Partial success is fine: report the real landed count everywhere rather
    than padding it, and let downstream tooling (qlib_ingest_wide.py) adjust
    its default point-in-time universe size N if the landed pool is
    materially smaller than requested.
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
OUT = EDGE / "data" / "1d_wide"
MANIFEST = OUT / "FETCH_MANIFEST_WIDE.json"

START = "2016-08-01"
END = datetime.now(timezone.utc).strftime("%Y-%m-%d")
FETCH_END_EXCLUSIVE = (pd.Timestamp(END) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

CHUNK_SIZE = 40
SLEEP_BETWEEN_CHUNKS = 1.5
MAX_RETRIES = 3
RETRY_SLEEP = 2.0
NEED = ["open", "high", "low", "close", "volume"]

# Sole ETF in this pool: dumped for the backtest benchmark by
# qlib_ingest_wide.py, excluded from the ranked (pitwide / allwide) universes.
BENCHMARK_TICKERS = ["SPY"]

# ---------------------------------------------------------------------------
# Candidate pool: 500-700 liquid US large/mid caps, sector-diverse. Chosen for
# genuine breadth, not just megacaps -- this is the entire point of the
# GATE_XS3 hypothesis (see edge/docs/GATE_XS3.md). Organized by sector purely
# for readability / manifest bookkeeping; the ranking pipeline does not use
# these labels. A ticker landing in more than one bucket is harmless -- the
# pool is de-duplicated below.
# ---------------------------------------------------------------------------
SECTORS: Dict[str, List[str]] = {
    "technology": [
        "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "META", "AVGO", "ORCL", "CRM",
        "ADBE", "CSCO", "ACN", "IBM", "TXN", "QCOM", "INTC", "AMD", "INTU",
        "NOW", "AMAT", "MU", "LRCX", "KLAC", "SNPS", "CDNS", "ADI", "PANW",
        "ANET", "FTNT", "MRVL", "ROP", "CTSH", "ADSK", "MSI", "APH", "TEL",
        "GLW", "HPQ", "DELL", "WDC", "STX", "NTAP", "JNPR", "KEYS", "TER",
        "ON", "SWKS", "QRVO", "MPWR", "ENPH", "FSLR", "ZBRA", "TYL", "PTC",
        "ANSS", "GDDY", "AKAM", "EPAM", "FFIV", "NTNX", "PSTG", "DDOG", "SNOW",
        "PLTR", "NET", "CRWD", "ZS", "OKTA", "TEAM", "WDAY", "HUBS", "MDB",
        "DOCU", "TWLO", "PAYC", "PCTY", "VEEV", "U", "RBLX", "ARM", "SMCI",
        "DOCN", "GTLB", "ESTC", "CFLT", "PATH", "APPN", "BILL", "BOX", "DBX",
        "ZM", "HPE", "JBL", "FICO", "GEN", "VRSN", "CDW", "NXPI", "MCHP",
        "GRMN", "MSCI", "SPGI", "VRSK", "FI", "GPN", "JKHY", "MKTX",
    ],
    "financials": [
        "JPM", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC", "COF",
        "SCHW", "BK", "STT", "AXP", "BLK", "BX", "KKR", "APO", "ARES", "CG",
        "TROW", "BEN", "IVZ", "AMP", "RJF", "NTRS", "CBOE", "CME", "ICE",
        "NDAQ", "MET", "PRU", "AFL", "ALL", "TRV", "PGR", "CB", "AIG", "HIG",
        "LNC", "PFG", "GL", "WRB", "CINF", "MTB", "FITB", "HBAN", "RF", "KEY",
        "CFG", "ZION", "CMA", "SYF", "DFS", "PYPL", "XYZ", "WU", "EFX", "V",
        "MA", "AON", "MMC", "AJG", "BRO", "WTW", "ORI", "L", "RGA", "UNM",
        "GNW", "BRK-B",
    ],
    "healthcare": [
        "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR", "BMY",
        "AMGN", "GILD", "MDT", "ISRG", "SYK", "BSX", "BDX", "ZBH", "EW",
        "IDXX", "IQV", "A", "RMD", "DXCM", "ALGN", "HOLX", "BAX", "VTRS",
        "ZTS", "REGN", "VRTX", "BIIB", "MRNA", "INCY", "ILMN", "BMRN", "ALNY",
        "SGEN", "EXAS", "NBIX", "UTHR", "RGEN", "TECH", "CRL", "MTD", "WAT",
        "RVTY", "CTLT", "CAH", "MCK", "COR", "HCA", "UHS", "THC", "CNC",
        "ELV", "CI", "HUM", "CVS", "MOH", "GEHC", "DGX", "LH", "CHE", "ENSG",
        "ACHC", "DVA", "XRAY", "COO", "PODD", "TFX", "STE",
    ],
    "energy": [
        "XOM", "CVX", "COP", "EOG", "SLB", "PXD", "OXY", "MPC", "PSX", "VLO",
        "WMB", "KMI", "OKE", "HES", "DVN", "FANG", "CTRA", "MRO", "APA",
        "HAL", "BKR", "TRGP", "LNG", "EQT", "AR", "RRC", "EXE", "SM", "MTDR",
        "PR", "CIVI", "NOV", "FTI", "CHRD", "TPL", "NFG", "OVV",
    ],
    "industrials": [
        "BA", "HON", "UPS", "RTX", "LMT", "GE", "CAT", "DE", "UNP", "CSX",
        "NSC", "GD", "NOC", "TDG", "EMR", "ETN", "ITW", "PH", "ROK", "DOV",
        "XYL", "IR", "AME", "FTV", "CMI", "PCAR", "WAB", "JCI", "CARR",
        "OTIS", "TT", "IEX", "GGG", "NDSN", "SNA", "SWK", "ALLE", "MAS",
        "FAST", "PWR", "EME", "J", "FLR", "ACM", "URI", "HEI", "TXT", "HWM",
        "LHX", "HII", "AXON", "TDY", "GNRC", "ALK", "DAL", "UAL", "LUV",
        "AAL", "CHRW", "JBHT", "ODFL", "XPO", "KNX", "LSTR", "EXPD", "IT",
        "CACI", "LDOS", "SAIC",
    ],
    "staples": [
        "PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "MDLZ", "CL", "KMB",
        "GIS", "KHC", "STZ", "SYY", "KR", "ADM", "HSY", "MKC", "CHD", "CLX",
        "CAG", "CPB", "SJM", "HRL", "TSN", "K", "TAP", "BF-B", "KDP", "MNST",
        "COTY", "WBA", "DG", "DLTR",
    ],
    "discretionary": [
        "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "TJX", "BKNG",
        "CMG", "ORLY", "AZO", "ROST", "YUM", "MAR", "HLT", "RCL", "CCL",
        "NCLH", "LVS", "WYNN", "MGM", "DRI", "DPZ", "QSR", "EBAY", "ETSY",
        "W", "ULTA", "BBY", "TGT", "GPC", "AAP", "TSCO", "FIVE", "LULU",
        "DECK", "CROX", "VFC", "RL", "PVH", "GPS", "ANF", "URBN", "BBWI",
        "KSS", "M", "JWN", "F", "GM", "RIVN", "LCID", "APTV", "LEA", "BWA",
        "THO", "WHR", "NVR", "LEN", "DHI", "PHM", "KBH", "POOL", "CHDN",
        "EXPE", "ABNB", "UBER", "LYFT", "EL",
    ],
    "utilities": [
        "NEE", "DUK", "SO", "D", "AEP", "EXC", "XEL", "SRE", "PEG", "ED",
        "WEC", "ES", "FE", "AEE", "CMS", "DTE", "ATO", "CNP", "NI", "LNT",
        "EVRG", "PNW", "PPL", "AES", "NRG", "VST", "CEG", "PCG", "EIX",
    ],
    "materials": [
        "LIN", "APD", "SHW", "ECL", "FCX", "NEM", "NUE", "STLD", "DOW", "DD",
        "LYB", "PPG", "ALB", "CE", "IFF", "MOS", "CF", "FMC", "EMN", "VMC",
        "MLM", "PKG", "IP", "WRK", "SEE", "AVY", "CCK", "BALL", "SON", "RS",
        "X", "CLF", "AA",
    ],
    "real_estate": [
        "PLD", "AMT", "EQIX", "PSA", "SPG", "O", "WELL", "DLR", "VICI",
        "AVB", "EQR", "ESS", "MAA", "INVH", "VTR", "ARE", "BXP", "KIM",
        "REG", "FRT", "UDR", "CPT", "HST", "EXR", "CUBE", "IRM", "CCI",
        "SBAC", "WY", "PCH", "DOC", "OHI", "MPW", "NNN", "ADC", "KRC",
        "HIW", "DEI", "SLG",
    ],
    "communications": [
        "T", "VZ", "TMUS", "CMCSA", "CHTR", "DIS", "NFLX", "WBD", "PARA",
        "FOXA", "FOX", "NWSA", "NWS", "LYV", "OMC", "IPG", "TTWO", "EA",
        "ATVI", "MTCH", "PINS", "SNAP", "SPOT", "ROKU", "LBRDK", "NYT",
    ],
}


def all_candidates() -> List[str]:
    """Flatten SECTORS + BENCHMARK_TICKERS, de-duplicated, order preserved."""
    seen = set()
    out: List[str] = []
    for syms in list(SECTORS.values()) + [BENCHMARK_TICKERS]:
        for s in syms:
            s = s.upper().strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out


def _sector_of(symbol: str) -> str:
    if symbol in BENCHMARK_TICKERS:
        return "benchmark"
    for name, syms in SECTORS.items():
        if symbol in syms:
            return name
    return "unknown"


def _chunks(seq: List[str], n: int) -> List[List[str]]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Match edge/data/1d/ schema: DatetimeIndex, open/high/low/close/volume."""
    if df is None or df.empty:
        return pd.DataFrame(columns=NEED)
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [str(c[0]).lower() for c in out.columns]
    else:
        out.columns = [str(c).lower() for c in out.columns]
    rename = {}
    for c in list(out.columns):
        if c in ("adj close", "adj_close"):
            rename[c] = "close"
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
    out = out[out.index <= pd.Timestamp(END)]  # hard-trim to the locked end date
    return out


def fetch_chunk(symbols: List[str]) -> Dict[str, pd.DataFrame]:
    import yfinance as yf

    if len(symbols) == 1:
        raw = yf.download(
            symbols[0], start=START, end=FETCH_END_EXCLUSIVE, interval="1d",
            auto_adjust=True, progress=False, threads=False,
        )
        return {symbols[0]: _normalize(raw)}

    raw = yf.download(
        symbols, start=START, end=FETCH_END_EXCLUSIVE, interval="1d",
        auto_adjust=True, group_by="ticker", threads=True, progress=False,
    )
    out: Dict[str, pd.DataFrame] = {}
    top = set(raw.columns.get_level_values(0)) if isinstance(raw.columns, pd.MultiIndex) else set()
    for sym in symbols:
        out[sym] = _normalize(raw[sym]) if sym in top else pd.DataFrame(columns=NEED)
    return out


def fetch_one_retry(symbol: str, max_retries: int = MAX_RETRIES) -> pd.DataFrame:
    """Sequential, slower, single-symbol retry for anything a batch missed."""
    import yfinance as yf

    for attempt in range(1, max_retries + 1):
        try:
            raw = yf.download(
                symbol, start=START, end=FETCH_END_EXCLUSIVE, interval="1d",
                auto_adjust=True, progress=False, threads=False,
            )
            df = _normalize(raw)
            if not df.empty:
                return df
        except Exception:
            pass
        time.sleep(RETRY_SLEEP * attempt)
    return pd.DataFrame(columns=NEED)


def maybe_write(path: Path, df: pd.DataFrame, force: bool) -> str:
    """Merge the new pull into whatever is on disk, newest bar wins.

    Same rule as `fetch_universe.maybe_write`, and for the same reason: row
    count is not evidence of freshness. This fetcher's window is anchored at a
    fixed START so its count does grow, but a chunked multi-symbol pull that
    comes back short for one name would otherwise be silently discarded even
    when it carried bars the file is missing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if df is None or getattr(df, "empty", True):
        return "kept_existing"

    if path.exists() and not force:
        try:
            old = pd.read_parquet(path)
        except Exception:
            old = None
        if old is not None and not old.empty and list(old.columns) == list(df.columns):
            merged = pd.concat([old[~old.index.isin(df.index)], df]).sort_index()
            merged = merged[~merged.index.duplicated(keep="last")]
            if merged.equals(old):
                return "kept_existing"
            merged.to_parquet(path)
            return "merged"
        if old is not None and not old.empty and len(df) <= len(old):
            if df.index.max() <= old.index.max():
                return "kept_existing"

    df.to_parquet(path)
    return "wrote"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=None, help="only fetch the first N candidates (smoke test)")
    ap.add_argument("--force", action="store_true", help="overwrite even if the existing file has more rows")
    ap.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    ap.add_argument("--sleep", type=float, default=SLEEP_BETWEEN_CHUNKS, help="seconds between chunk downloads")
    args = ap.parse_args(argv)

    symbols = all_candidates()
    if args.limit is not None:
        symbols = symbols[: args.limit]

    print(f"requested: {len(symbols)} tickers ({len(SECTORS)} sectors + benchmark)")
    print(f"window   : {START} -> {END}")
    print(f"output   : {OUT.relative_to(ROOT)}")

    manifest: Dict[str, object] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance",
        "requested_start": START,
        "requested_end": END,
        "n_requested": len(symbols),
        "chunk_size": args.chunk_size,
        "sector_counts": {k: len(v) for k, v in SECTORS.items()},
        "results": {},
    }

    ok = 0
    failed: List[str] = []
    chunks = _chunks(symbols, args.chunk_size)
    for ci, chunk in enumerate(chunks, start=1):
        print(f"\nchunk {ci}/{len(chunks)}  ({len(chunk)} symbols)", flush=True)
        try:
            batch = fetch_chunk(chunk)
        except Exception as e:
            print(f"  ERROR (whole chunk): {e}", file=sys.stderr)
            batch = {s: pd.DataFrame(columns=NEED) for s in chunk}

        retry_needed = [s for s in chunk if batch.get(s, pd.DataFrame()).empty]
        for sym in retry_needed:
            df = fetch_one_retry(sym)
            if not df.empty:
                batch[sym] = df

        for sym in chunk:
            df = batch.get(sym, pd.DataFrame(columns=NEED))
            key = sym
            if df.empty:
                manifest["results"][key] = {"status": "empty_or_failed", "sector": _sector_of(sym)}
                failed.append(sym)
                print(f"  EMPTY  {sym}")
            else:
                path = OUT / f"{sym}.parquet"
                action = maybe_write(path, df, args.force)
                manifest["results"][key] = {
                    "status": "ok",
                    "action": action,
                    "sector": _sector_of(sym),
                    "n": int(len(df)),
                    "start": str(df.index.min().date()),
                    "end": str(df.index.max().date()),
                    "path": str(path.relative_to(EDGE)),
                }
                ok += 1
                print(f"  OK     {sym:<7} n={len(df):>4} {df.index.min().date()} -> {df.index.max().date()} ({action})")

        time.sleep(args.sleep)

    manifest["summary"] = {
        "n_requested": len(symbols),
        "n_ok": ok,
        "n_empty_or_failed": len(failed),
        "landed_fraction": round(ok / len(symbols), 4) if symbols else 0.0,
        "failed_symbols": sorted(failed),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nlanded {ok} / {len(symbols)} ({manifest['summary']['landed_fraction']:.1%})")
    if failed:
        print(f"failed ({len(failed)}): {', '.join(failed[:30])}" + (" ..." if len(failed) > 30 else ""))
    print(f"\nManifest -> {MANIFEST.relative_to(ROOT)}")

    if ok < 300:
        print(
            "WARNING: fewer than 300 symbols landed. GATE_XS3.md's default "
            "point-in-time universe size (N=300) may need lowering -- report "
            "the real landed count, do not pad.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
