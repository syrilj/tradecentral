#!/usr/bin/env python3
"""Convert edge/data/1d/*.parquet into a Qlib binary provider directory.

Usage (from alltrading/):
  python3 edge/tools/qlib_ingest.py              # stage -> dump -> universes -> verify
  python3 edge/tools/qlib_ingest.py --stage-only
  python3 edge/tools/qlib_ingest.py --verify     # round-trip check against source parquet

Produces:
  edge/data/qlib_stage/<SYM>.csv     staging CSVs (dump_bin input)
  edge/data/qlib_us_1d/              Qlib provider dir (calendars/ instruments/ features/)
  edge/data/qlib_us_1d/instruments/  all.txt (dump_bin) + xs47.txt + xs40.txt (this tool)

The two extra instrument files exist because docs/GATE_XS.md requires every
gating metric reported twice -- on all 47 single names, and on the 40 that were
already listed at the start of the sample. The gap between them is a
survivorship premium, not a result.

Honest limits
-------------
  - Source prices are yfinance ``auto_adjust=True`` (see models/v90/MODEL.md), so
    they are already split/dividend adjusted and ``factor`` is written as 1.0.
    Retroactive adjustment is a mild dividend-lookahead; the existing edge/
    harness has the same property, so this is consistent with prior work rather
    than a new compromise. It is not silently assumed -- it is recorded in the
    manifest.
  - ``vwap`` is not available from the source. Alpha158 references ``$vwap`` in
    several expressions, so typical price (H+L+C)/3 is written explicitly rather
    than letting whole feature groups silently degrade to NaN. This is an
    approximation and is flagged as such in the manifest.
  - The 13 ETFs are excluded from the ranked universes but still dumped, because
    SPY is needed as the backtest benchmark.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]  # alltrading/
EDGE = ROOT / "edge"

SRC = EDGE / "data" / "1d"
STAGE = EDGE / "data" / "qlib_stage"
QLIB_DIR = EDGE / "data" / "qlib_us_1d"
DUMP_BIN = EDGE / ".qlib-src" / "scripts" / "dump_bin.py"
MANIFEST = EDGE / "data" / "QLIB_INGEST_MANIFEST.json"

# Excluded from the ranked cross-section: ranking an index against a single
# stock is not a meaningful comparison. Still dumped -- SPY is the benchmark.
ETFS = {"SPY", "QQQ", "IWM", "DIA", "GLD", "TLT", "HYG", "LQD", "XBI", "XLE", "XLF", "XLP", "XLU"}

# Sample start. A name whose first bar is later than this listed mid-sample.
SAMPLE_START = pd.Timestamp("2016-08-02")

FIELDS = ["open", "high", "low", "close", "volume", "vwap", "factor"]


def stage() -> Dict[str, object]:
    """parquet -> dump_bin-shaped CSV (date, symbol, OHLCV, vwap, factor)."""
    STAGE.mkdir(parents=True, exist_ok=True)
    for old in STAGE.glob("*.csv"):
        old.unlink()

    spans: Dict[str, List[str]] = {}
    for path in sorted(SRC.glob("*.parquet")):
        symbol = path.stem
        df = pd.read_parquet(path).sort_index()
        if df.empty:
            continue
        out = pd.DataFrame(index=df.index)
        for c in ("open", "high", "low", "close", "volume"):
            out[c] = df[c].astype(float)
        out["vwap"] = (out["high"] + out["low"] + out["close"]) / 3.0
        out["factor"] = 1.0  # prices already auto_adjust=True
        out.insert(0, "symbol", symbol)
        out.index.name = "date"
        out = out.reset_index()
        out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
        out.to_csv(STAGE / f"{symbol}.csv", index=False)
        spans[symbol] = [out["date"].iloc[0], out["date"].iloc[-1], str(len(out))]

    return {"n_symbols": len(spans), "spans": spans}


def dump() -> None:
    if not DUMP_BIN.exists():
        raise FileNotFoundError(
            f"{DUMP_BIN} not found. Fetch it with:\n"
            f"  git clone --depth 1 --filter=blob:none --sparse "
            f"https://github.com/microsoft/qlib.git edge/.qlib-src && "
            f"cd edge/.qlib-src && git sparse-checkout set scripts examples"
        )
    py = EDGE / ".venv-qlib" / "bin" / "python"
    cmd = [
        str(py if py.exists() else sys.executable),
        str(DUMP_BIN),
        "dump_all",
        "--data_path", str(STAGE),
        "--qlib_dir", str(QLIB_DIR),
        "--freq", "day",
        "--date_field_name", "date",
        "--symbol_field_name", "symbol",
        "--include_fields", ",".join(FIELDS),
        "--file_suffix", ".csv",
    ]
    print("  $ " + " ".join(cmd[:3]) + " ...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(res.stdout[-2000:])
    if res.returncode != 0:
        sys.stderr.write(res.stderr[-4000:])
        raise RuntimeError(f"dump_bin failed (exit {res.returncode})")


def write_universes() -> Dict[str, object]:
    """Derive xs47 / xs40 instrument files from dump_bin's all.txt."""
    inst = QLIB_DIR / "instruments"
    all_txt = inst / "all.txt"
    if not all_txt.exists():
        raise FileNotFoundError(f"{all_txt} missing -- run the dump step first")

    rows: List[List[str]] = []
    for line in all_txt.read_text(encoding="utf-8").splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 3:
            rows.append(parts[:3])

    singles = [r for r in rows if r[0].upper() not in ETFS]
    early = [r for r in singles if pd.Timestamp(r[1]) <= SAMPLE_START]

    (inst / "xs47.txt").write_text("".join("\t".join(r) + "\n" for r in singles), encoding="utf-8")
    (inst / "xs40.txt").write_text("".join("\t".join(r) + "\n" for r in early), encoding="utf-8")

    late = sorted(r[0] for r in singles if pd.Timestamp(r[1]) > SAMPLE_START)
    return {
        "all": len(rows),
        "xs47": len(singles),
        "xs40": len(early),
        "late_listings": late,
        "etfs_excluded": sorted(ETFS),
    }


def verify(sample: str = "AAPL") -> bool:
    """Round-trip: Qlib's view of a symbol must match the source parquet."""
    try:
        import qlib
        from qlib.data import D
    except ModuleNotFoundError:
        print(
            "ERROR: qlib is not importable in this interpreter.\n"
            "  This tool must run under the isolated qlib venv, not system python3:\n"
            "    edge/.venv-qlib/bin/python edge/tools/qlib_ingest.py --verify",
            file=sys.stderr,
        )
        return False

    qlib.init(provider_uri=str(QLIB_DIR), region="us", expression_cache=None, dataset_cache=None)

    got = D.features([sample], ["$close", "$volume", "$vwap"], freq="day")
    if got is None or got.empty:
        print(f"  FAIL: Qlib returned nothing for {sample}")
        return False
    got = got.droplevel(0).sort_index()

    src = pd.read_parquet(SRC / f"{sample}.parquet").sort_index()
    src.index = pd.to_datetime(src.index).normalize()

    common = got.index.intersection(src.index)
    if len(common) < 0.95 * len(src):
        print(f"  FAIL: only {len(common)} of {len(src)} source bars round-tripped")
        return False

    dc = (got.loc[common, "$close"].astype(float) - src.loc[common, "close"].astype(float)).abs()
    tol = 1e-3 * src.loc[common, "close"].astype(float).abs()
    ok = bool((dc <= tol).all())
    print(f"  {sample}: {len(common):,} bars aligned, max close delta {dc.max():.6f} -> {'OK' if ok else 'FAIL'}")

    cal = sorted((QLIB_DIR / "calendars").glob("day.txt"))
    if cal:
        n = len(cal[0].read_text(encoding="utf-8").split())
        print(f"  calendar: {n:,} trading days")
    for name in ("xs47", "xs40"):
        p = QLIB_DIR / "instruments" / f"{name}.txt"
        if p.exists():
            print(f"  universe {name}: {len(p.read_text(encoding='utf-8').splitlines())} names")
    return ok


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage-only", action="store_true")
    ap.add_argument("--verify", action="store_true", help="only run the round-trip check")
    ap.add_argument("--sample", default="AAPL", help="symbol used for the round-trip check")
    args = ap.parse_args(argv)

    if args.verify:
        return 0 if verify(args.sample) else 1

    print(f"staging  {SRC.relative_to(ROOT)} -> {STAGE.relative_to(ROOT)}")
    st = stage()
    print(f"  {st['n_symbols']} symbols staged")
    if args.stage_only:
        return 0

    print(f"dumping  -> {QLIB_DIR.relative_to(ROOT)}")
    dump()

    print("universes")
    uni = write_universes()
    print(f"  all={uni['all']}  xs47={uni['xs47']}  xs40={uni['xs40']}")
    print(f"  late listings excluded from xs40: {', '.join(uni['late_listings'])}")

    MANIFEST.write_text(
        json.dumps(
            {
                "generated_utc": pd.Timestamp.utcnow().isoformat(),
                "source": str(SRC.relative_to(ROOT)),
                "qlib_dir": str(QLIB_DIR.relative_to(ROOT)),
                "fields": FIELDS,
                "adjustment": "yfinance auto_adjust=True; factor=1.0 (already adjusted)",
                "vwap": "APPROXIMATED as typical price (high+low+close)/3 -- not true VWAP",
                "universes": uni,
                "staged": st,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {MANIFEST.relative_to(ROOT)}")

    print("verifying")
    return 0 if verify(args.sample) else 1


if __name__ == "__main__":
    raise SystemExit(main())
