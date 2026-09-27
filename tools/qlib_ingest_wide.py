#!/usr/bin/env python3
"""Convert edge/data/1d_wide/*.parquet into a Qlib binary provider directory.

Usage (from alltrading/, with the qlib venv -- see edge/docs/GATE_XS3.md):
  edge/.venv-qlib/bin/python edge/tools/qlib_ingest_wide.py                 # stage -> dump -> universes -> verify
  edge/.venv-qlib/bin/python edge/tools/qlib_ingest_wide.py --stage-only
  edge/.venv-qlib/bin/python edge/tools/qlib_ingest_wide.py --top-n 250     # smaller pitwide, if the landed pool is thin
  edge/.venv-qlib/bin/python edge/tools/qlib_ingest_wide.py --verify        # round-trip + point-in-time sanity check

Produces:
  edge/data/qlib_stage_wide/<SYM>.csv     staging CSVs (dump_bin input)
  edge/data/qlib_us_1d_wide/               Qlib provider dir (calendars/ instruments/ features/)
  edge/data/qlib_us_1d_wide/instruments/   all.txt (dump_bin) + allwide.txt + pitwide.txt (this tool)

Adapted from edge/tools/qlib_ingest.py (read-only reference; NOT modified). Same
hard-won solutions reused verbatim: factor=1.0 (prices already
yfinance auto_adjust=True), vwap approximated as typical price, dump via
dump_bin.py, ETF exclusion from the ranked universe. New in this tool: a
POINT-IN-TIME universe (``pitwide``), because edge/docs/GATE_XS3.md's
hypothesis is specifically that breadth *and* a rule-based, non-hindsight
universe together fix what GATE_XS.md's hand-picked 47/60 could not.

Honest limits
-------------
  - Source prices are yfinance ``auto_adjust=True``, so they are already
    split/dividend adjusted and ``factor`` is written as 1.0. Retroactive
    adjustment is a mild dividend-lookahead; consistent with prior work in this
    repo (edge/tools/qlib_ingest.py), not a new compromise. Recorded in the
    manifest, not silently assumed.
  - ``vwap`` is APPROXIMATED as typical price (high+low+close)/3 -- Alpha158
    references ``$vwap`` in several expressions and would otherwise silently
    degrade whole feature groups to NaN. Flagged in the manifest.
  - The point-in-time liquidity rank uses dollar volume = adjusted close *
    volume, as an approximation of true (unadjusted) dollar volume. This can
    misrank very recently split/adjusted names slightly; flagged in the
    manifest, not hidden.
  - The point-in-time rule needs >=252 trading days of PRIOR history before a
    name is eligible. Because the fetch window itself starts 2016-08-01, NO
    name can satisfy that requirement until roughly 252 trading days later
    (~2017 Q3) -- there is no data before the window to draw "prior history"
    from. ``pitwide`` is therefore genuinely empty (0 names) for the first
    ~13 months of the sample. This is a real, honest consequence of the rule
    as specified, not a bug, and it is recorded in the manifest, not smoothed
    over.
  - The candidate pool this universe is built from was assembled in 2026 (see
    edge/tools/fetch_universe_wide.py). The point-in-time liquidity rule below
    decides *when* a surviving name enters the ranked universe; it does not
    and cannot recover names that delisted, went bankrupt, or were acquired
    and are no longer retrievable from Yahoo Finance. Per GATE_XS3.md, this is
    "reduced via a point-in-time liquidity rule over a 2026-assembled
    candidate pool; delisted names remain absent" -- never "fixed".
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]  # alltrading/
EDGE = ROOT / "edge"

SRC = EDGE / "data" / "1d_wide"
STAGE = EDGE / "data" / "qlib_stage_wide"
QLIB_DIR = EDGE / "data" / "qlib_us_1d_wide"
DUMP_BIN = EDGE / ".qlib-src" / "scripts" / "dump_bin.py"
MANIFEST = QLIB_DIR / "QLIB_INGEST_MANIFEST_WIDE.json"

# Sole ETF in the wide pool (see fetch_universe_wide.py): excluded from both
# ranked universes, still dumped because SPY is the backtest benchmark.
ETFS = {"SPY"}

FIELDS = ["open", "high", "low", "close", "volume", "vwap", "factor"]

# Point-in-time universe rule (edge/docs/GATE_XS3.md). Not exposed as flags
# except --top-n: the history/lookback windows are part of the frozen rule,
# not a knob to be tuned per run.
DEFAULT_TOP_N = 300
MIN_HISTORY_DAYS = 252   # trading days of PRIOR history required to be eligible
LOOKBACK_DAYS = 60       # trailing window for the median-dollar-volume rank


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


def write_allwide() -> Dict[str, object]:
    """allwide = every dumped single name, fixed span, ETFs excluded.

    Analogous to GATE_XS.md's xs47 (all singles, no listing-date filter) --
    this is the "breadth alone, no liquidity rule" comparison universe.
    """
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
    (inst / "allwide.txt").write_text(
        "".join("\t".join(r) + "\n" for r in singles), encoding="utf-8"
    )
    return {"all": len(rows), "allwide": len(singles), "etfs_excluded": sorted(ETFS)}


def build_pitwide(
    top_n: int, min_history: int = MIN_HISTORY_DAYS, lookback: int = LOOKBACK_DAYS
) -> Tuple[List[Tuple[str, str, str]], Dict[str, object]]:
    """Point-in-time universe: top `top_n` by trailing median dollar volume.

    At each calendar month end: require >=`min_history` trading days of PRIOR
    history (no lookahead), rank eligible names by trailing `lookback`-day
    median dollar volume (close * volume), take the top `top_n`. Emitted as
    dated intervals -- a name enters the qlib instrument file only once it
    actually qualifies, and may appear on multiple disjoint lines if it drops
    out and later re-qualifies.
    """
    close_cols: Dict[str, pd.Series] = {}
    vol_cols: Dict[str, pd.Series] = {}
    for path in sorted(SRC.glob("*.parquet")):
        symbol = path.stem
        if symbol.upper() in ETFS:
            continue
        df = pd.read_parquet(path)
        if df.empty:
            continue
        idx = pd.to_datetime(df.index).normalize()
        close_cols[symbol] = pd.Series(df["close"].astype(float).to_numpy(), index=idx)
        vol_cols[symbol] = pd.Series(df["volume"].astype(float).to_numpy(), index=idx)

    close = pd.DataFrame(close_cols).sort_index()
    vol = pd.DataFrame(vol_cols).sort_index()
    close = close[~close.index.duplicated(keep="last")]
    vol = vol[~vol.index.duplicated(keep="last")]
    dvol = close * vol  # approx dollar volume; see module docstring

    all_dates = dvol.index
    # PRIOR history count strictly before each row (shift(1) keeps it point-in-time).
    hist_count = dvol.notna().cumsum().shift(1).fillna(0)
    roll_med = dvol.rolling(lookback, min_periods=lookback).median()

    month_ends = pd.date_range(all_dates.min(), all_dates.max(), freq="ME")
    rebal_dates: List[pd.Timestamp] = []
    for me in month_ends:
        cand = all_dates[all_dates <= me]
        if len(cand):
            d = cand.max()
            if not rebal_dates or rebal_dates[-1] != d:
                rebal_dates.append(d)

    members: Dict[pd.Timestamp, List[str]] = {}
    for d in rebal_dates:
        elig = hist_count.loc[d] >= min_history
        rm = roll_med.loc[d]
        elig = elig & rm.notna()
        ranked = rm[elig].sort_values(ascending=False)
        members[d] = list(ranked.index[:top_n])

    pos = {d: i for i, d in enumerate(all_dates)}
    mem_df = pd.DataFrame(False, index=rebal_dates, columns=close.columns)
    for d, syms in members.items():
        if syms:
            mem_df.loc[d, syms] = True

    intervals: List[Tuple[str, str, str]] = []
    for sym in mem_df.columns:
        s = mem_df[sym]
        in_run = False
        run_start_idx = None
        for i, d in enumerate(rebal_dates):
            val = bool(s.loc[d])
            if val and not in_run:
                in_run, run_start_idx = True, i
            elif not val and in_run:
                in_run = False
                start_d = rebal_dates[run_start_idx]
                end_d = all_dates[pos[rebal_dates[i]] - 1]  # day before it dropped out
                if end_d >= start_d:
                    intervals.append((sym, start_d.strftime("%Y-%m-%d"), end_d.strftime("%Y-%m-%d")))
        if in_run:
            start_d = rebal_dates[run_start_idx]
            end_d = all_dates[-1]
            intervals.append((sym, start_d.strftime("%Y-%m-%d"), end_d.strftime("%Y-%m-%d")))

    sizes = [len(v) for v in members.values()]
    nonzero_sizes = [n for n in sizes if n > 0]
    first_nonzero = next((d for d in rebal_dates if members[d]), None)
    stats: Dict[str, object] = {
        "rule": (
            f"month-end rebalance; eligible if >= {min_history} trading days of "
            f"PRIOR history exist; ranked by trailing {lookback}-trading-day "
            f"median dollar volume (close*volume, adjusted-price approximation); "
            f"top {top_n} taken; emitted as dated intervals"
        ),
        "top_n": top_n,
        "min_history_days": min_history,
        "lookback_days": lookback,
        "n_rebalance_dates": len(rebal_dates),
        "first_rebalance_date": rebal_dates[0].strftime("%Y-%m-%d") if rebal_dates else None,
        "last_rebalance_date": rebal_dates[-1].strftime("%Y-%m-%d") if rebal_dates else None,
        "first_nonempty_rebalance_date": first_nonzero.strftime("%Y-%m-%d") if first_nonzero is not None else None,
        "n_rebalance_dates_with_zero_members": int(sum(1 for n in sizes if n == 0)),
        "median_universe_size_over_time": float(np.median(nonzero_sizes)) if nonzero_sizes else None,
        "min_universe_size_nonzero": int(min(nonzero_sizes)) if nonzero_sizes else None,
        "max_universe_size": int(max(sizes)) if sizes else None,
        "n_intervals": len(intervals),
        "n_distinct_symbols": len(set(r[0] for r in intervals)),
        "note_warmup_gap": (
            "Rebalance dates before the first date with >=min_history trading "
            "days of prior history have ZERO eligible members -- there is no "
            "data before the fetch window (2016-08-01) to draw prior history "
            "from. This is expected, not a bug; see module docstring."
        ),
    }
    return intervals, stats


def verify(sample: str = "AAPL", top_n: int = DEFAULT_TOP_N) -> bool:
    """Round-trip against source parquet, plus a point-in-time sanity check."""
    try:
        import qlib
        from qlib.data import D
    except ModuleNotFoundError:
        print(
            "ERROR: qlib is not importable in this interpreter.\n"
            "  This tool must run under the isolated qlib venv, not system python3:\n"
            "    edge/.venv-qlib/bin/python edge/tools/qlib_ingest_wide.py --verify",
            file=sys.stderr,
        )
        return False

    qlib.init(provider_uri=str(QLIB_DIR), region="us", expression_cache=None, dataset_cache=None)

    ok = True
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
        ok = False

    dc = (got.loc[common, "$close"].astype(float) - src.loc[common, "close"].astype(float)).abs()
    tol = 1e-3 * src.loc[common, "close"].astype(float).abs()
    close_ok = bool((dc <= tol).all())
    print(f"  {sample}: {len(common):,} bars aligned, max close delta {dc.max():.6f} -> {'OK' if close_ok else 'FAIL'}")
    ok = ok and close_ok

    cal = sorted((QLIB_DIR / "calendars").glob("day.txt"))
    if cal:
        n = len(cal[0].read_text(encoding="utf-8").split())
        print(f"  calendar: {n:,} trading days")
    for name in ("allwide", "pitwide"):
        p = QLIB_DIR / "instruments" / f"{name}.txt"
        if p.exists():
            print(f"  instrument file {name}: {len(p.read_text(encoding='utf-8').splitlines())} lines")

    # Point-in-time sanity check, as required before this universe is ever fed
    # to a model: universe size must be close to top_n at sampled dates well
    # past the warmup gap, and membership must actually change over time.
    sample_dates = ["2018-06-29", "2019-06-28", "2020-06-30", "2021-06-30",
                     "2022-06-30", "2023-06-30", "2024-06-28", "2025-06-30"]
    sizes_by_date: Dict[str, int] = {}
    members_by_date: Dict[str, set] = {}
    inst_obj = D.instruments(market="pitwide")
    for d in sample_dates:
        try:
            names = D.list_instruments(inst_obj, start_time=d, end_time=d, as_list=True)
        except Exception as exc:  # noqa: BLE001 - report, never fabricate
            print(f"  FAIL: D.list_instruments errored at {d}: {exc}")
            ok = False
            continue
        sizes_by_date[d] = len(names)
        members_by_date[d] = set(names)
        flag = "OK" if abs(len(names) - top_n) <= max(5, int(0.05 * top_n)) else "FAR FROM N"
        print(f"  pitwide @ {d}: {len(names)} names ({flag}, target N={top_n})")
        if flag == "FAR FROM N":
            ok = False

    changed = False
    prev = None
    for d in sample_dates:
        if d not in members_by_date:
            continue
        if prev is not None and members_by_date[d] != members_by_date[prev]:
            changed = True
        prev = d
    print(f"  membership genuinely changes across sample dates: {'YES' if changed else 'NO -- SUSPECT'}")
    ok = ok and changed

    return ok


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage-only", action="store_true")
    ap.add_argument("--verify", action="store_true", help="only run the round-trip + point-in-time check")
    ap.add_argument("--sample", default="AAPL", help="symbol used for the round-trip check")
    ap.add_argument("--top-n", type=int, default=DEFAULT_TOP_N, help="pitwide universe size at each rebalance")
    args = ap.parse_args(argv)

    if args.verify:
        return 0 if verify(args.sample, args.top_n) else 1

    print(f"staging  {SRC.relative_to(ROOT)} -> {STAGE.relative_to(ROOT)}")
    st = stage()
    print(f"  {st['n_symbols']} symbols staged")
    if args.stage_only:
        return 0

    print(f"dumping  -> {QLIB_DIR.relative_to(ROOT)}")
    dump()

    print("universes")
    aw = write_allwide()
    print(f"  all={aw['all']}  allwide={aw['allwide']}")

    intervals, pit_stats = build_pitwide(args.top_n)
    inst_dir = QLIB_DIR / "instruments"
    (inst_dir / "pitwide.txt").write_text(
        "".join("\t".join(r) + "\n" for r in intervals), encoding="utf-8"
    )
    print(
        f"  pitwide: N={args.top_n} target, {pit_stats['n_intervals']} intervals, "
        f"{pit_stats['n_distinct_symbols']} distinct symbols, "
        f"median size over time={pit_stats['median_universe_size_over_time']}"
    )
    print(f"  pitwide first non-empty rebalance: {pit_stats['first_nonempty_rebalance_date']}")

    QLIB_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(
            {
                "generated_utc": pd.Timestamp.utcnow().isoformat(),
                "source": str(SRC.relative_to(ROOT)),
                "qlib_dir": str(QLIB_DIR.relative_to(ROOT)),
                "fields": FIELDS,
                "adjustment": "yfinance auto_adjust=True; factor=1.0 (already adjusted)",
                "vwap": "APPROXIMATED as typical price (high+low+close)/3 -- not true VWAP",
                "dollar_volume": "APPROXIMATED as adjusted close * volume, not true unadjusted dollar volume",
                "universes": {"all_wide": aw, "pitwide": pit_stats},
                "staged": st,
                "survivorship": (
                    "reduced via a point-in-time liquidity rule over a 2026-assembled "
                    "candidate pool; delisted names remain absent"
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {MANIFEST.relative_to(ROOT)}")

    print("verifying")
    return 0 if verify(args.sample, args.top_n) else 1


if __name__ == "__main__":
    raise SystemExit(main())
