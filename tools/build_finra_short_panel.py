#!/usr/bin/env python3
"""Aggregate the raw FINRA daily short-volume mirror into the processed panel
that `edge.tools.data_sources.load_finra_short_vol()` expects.

`edge/data/finra_shortvol/raw/` holds one gzip per session
(`CNMSshvol{YYYYMMDD}.txt.gz`, pipe-delimited `Date|Symbol|ShortVolume|
ShortExemptVolume|TotalVolume|Market`, plus a numeric trailer row giving the
row count). That raw mirror is not the `(date, symbol, short_ratio)` panel
`load_finra_short_vol()` reads — this script builds it, writing to the
canonical path `edge/data/finra_shortvol/short_vol.csv` with exactly the
columns `_FINRA_REQUIRED_COLUMNS` in `data_sources.py` names.

Usage:
  python3 edge/tools/build_finra_short_panel.py
  python3 edge/tools/build_finra_short_panel.py --incremental
"""

from __future__ import annotations

import argparse
import gzip
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "edge" / "data" / "finra_shortvol" / "raw"
OUT_CSV = ROOT / "edge" / "data" / "finra_shortvol" / "short_vol.csv"

_REQUIRED_RAW_COLUMNS = ("Date", "Symbol", "ShortVolume", "TotalVolume")


def parse_finra_daily_file(path: Path) -> pd.DataFrame:
    """Parse one `CNMSshvol*.txt.gz` mirror file into tidy rows.

    Returns columns `date, symbol, short_volume, total_volume`. Malformed
    rows (wrong field count, non-numeric volumes, the trailing row-count
    line) are skipped rather than raising — one bad file should not stop a
    multi-year backfill. An unreadable or empty file returns an empty frame
    with the correct columns, never `None`.
    """
    empty = pd.DataFrame(columns=["date", "symbol", "short_volume", "total_volume"])
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()
    except OSError:
        return empty
    if not lines:
        return empty

    header = lines[0].rstrip("\n").split("|")
    try:
        idx = {name: header.index(name) for name in _REQUIRED_RAW_COLUMNS}
    except ValueError:
        return empty
    need = max(idx.values()) + 1

    dates: list[str] = []
    symbols: list[str] = []
    short_vols: list[float] = []
    total_vols: list[float] = []
    for line in lines[1:]:
        fields = line.rstrip("\n").split("|")
        if len(fields) < need:
            continue
        symbol = fields[idx["Symbol"]].strip()
        if not symbol:
            continue
        try:
            short_vol = float(fields[idx["ShortVolume"]])
            total_vol = float(fields[idx["TotalVolume"]])
        except ValueError:
            continue
        if total_vol <= 0:
            continue
        date_raw = fields[idx["Date"]].strip()
        try:
            date_str = pd.to_datetime(date_raw, format="%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            continue
        dates.append(date_str)
        symbols.append(symbol.upper())
        short_vols.append(short_vol)
        total_vols.append(total_vol)

    if not dates:
        return empty
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": symbols,
            "short_volume": short_vols,
            "total_volume": total_vols,
        }
    )


def build_short_panel(
    raw_dir: Path,
    out_csv: Path,
    start: str | None = None,
    end: str | None = None,
    incremental: bool = False,
) -> dict:
    """Aggregate every raw daily file in `raw_dir` into `out_csv`.

    Rows are grouped by (date, symbol) and volumes are summed before the
    ratio is computed — defensive against a raw file ever carrying more than
    one row per symbol per day, even though the current mirror does not.
    When `incremental` is True and `out_csv` already exists, only dates not
    already present in it are (re)parsed and appended.

    Returns a QC summary dict: n_files, n_days, n_symbols, n_rows,
    out_of_range_ratio_count, gap_dates (raw files present but unparseable
    or empty).
    """
    files = sorted(raw_dir.glob("CNMSshvol*.txt.gz"))
    if start is not None:
        files = [f for f in files if _file_date(f) >= start]
    if end is not None:
        files = [f for f in files if _file_date(f) <= end]

    existing_dates: set[str] = set()
    prior = None
    if incremental and out_csv.exists():
        prior = pd.read_csv(out_csv, dtype={"symbol": str})
        existing_dates = set(prior["date"].astype(str))
        files = [f for f in files if _file_date(f) not in existing_dates]

    frames: list[pd.DataFrame] = []
    gap_dates: list[str] = []
    for f in files:
        day = parse_finra_daily_file(f)
        if day.empty:
            gap_dates.append(_file_date(f))
            continue
        frames.append(day)

    if frames:
        raw = pd.concat(frames, ignore_index=True)
        grouped = raw.groupby(["date", "symbol"], as_index=False)[
            ["short_volume", "total_volume"]
        ].sum()
        dup_check = grouped.groupby(["date", "symbol"]).size()
        if (dup_check > 1).any():
            raise ValueError("duplicate (date, symbol) rows survived aggregation")
        grouped["short_ratio"] = grouped["short_volume"] / grouped["total_volume"]
        panel = grouped[["date", "symbol", "short_ratio"]]
    else:
        panel = pd.DataFrame(columns=["date", "symbol", "short_ratio"])

    if prior is not None and not prior.empty:
        panel = pd.concat([prior[["date", "symbol", "short_ratio"]], panel], ignore_index=True)

    panel = panel.sort_values(["date", "symbol"]).reset_index(drop=True)

    out_of_range = int(((panel["short_ratio"] < 0) | (panel["short_ratio"] > 1)).sum())
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(out_csv, index=False)

    return {
        "n_files": len(files),
        "n_days": int(panel["date"].nunique()) if not panel.empty else 0,
        "n_symbols": int(panel["symbol"].nunique()) if not panel.empty else 0,
        "n_rows": int(len(panel)),
        "out_of_range_ratio_count": out_of_range,
        "gap_dates": gap_dates,
        "out_csv": str(out_csv),
    }


def _file_date(path: Path) -> str:
    stem = path.name.removeprefix("CNMSshvol").removesuffix(".txt.gz")
    return f"{stem[0:4]}-{stem[4:6]}-{stem[6:8]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--out", type=Path, default=OUT_CSV)
    parser.add_argument("--start", type=str, default=None, help="YYYY-MM-DD, inclusive")
    parser.add_argument("--end", type=str, default=None, help="YYYY-MM-DD, inclusive")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only parse raw files for dates not already in --out",
    )
    args = parser.parse_args()

    if not args.raw_dir.is_dir():
        print(f"Raw directory not found: {args.raw_dir}", file=sys.stderr)
        return 1

    summary = build_short_panel(
        args.raw_dir, args.out, start=args.start, end=args.end, incremental=args.incremental
    )

    print(f"Wrote {summary['out_csv']}")
    print(f"  files parsed:  {summary['n_files']}")
    print(f"  days:          {summary['n_days']}")
    print(f"  symbols:       {summary['n_symbols']}")
    print(f"  rows:          {summary['n_rows']}")
    print(f"  out-of-range:  {summary['out_of_range_ratio_count']}")
    if summary["gap_dates"]:
        print(f"  gap dates ({len(summary['gap_dates'])}): {summary['gap_dates'][:10]}"
              + (" ..." if len(summary["gap_dates"]) > 10 else ""))

    if summary["n_rows"] == 0:
        print("No rows written.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
