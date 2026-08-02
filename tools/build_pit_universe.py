#!/usr/bin/env python3
"""Build the `pit30` point-in-time liquidity universe for edge/docs/GATE_XS2.md.

Why this exists
---------------
`GATE_XS_RESULT.md` found that universe construction moved the result more than
the model did: the seven names in xs47 but not xs40 (APLD ARM COIN IONQ PLTR RKLB
SNOW) *raised* portfolio return while *lowering* Rank IC. They were on the list
because someone in 2026 knew they worked.

`xs40` fixes that by hand — drop anything listed after 2016-08. This fixes it by
rule instead: membership is decided at each month end from data available at that
month end, so a name enters when it actually becomes liquid and leaves when it
stops. PLTR joins in the 2020s because it qualifies, not in 2016 because it won.

Rule (frozen by GATE_XS2.md, do not tune):
  - at each month end, require >= 252 trading days of prior price history
  - rank the qualifying names by trailing 60-day median dollar volume
  - take the top 30
  - membership applies from the next trading day until the next month end

Output is a qlib instruments file of dated intervals, which is exactly how qlib
represents a time-varying universe:

    AAPL\t2017-08-01\t2026-07-29
    PLTR\t2021-03-01\t2023-06-30
    PLTR\t2023-11-01\t2026-07-29

Usage (from alltrading/):
  edge/.venv-qlib/bin/python edge/tools/build_pit_universe.py
  edge/.venv-qlib/bin/python edge/tools/build_pit_universe.py --top-n 30 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]  # alltrading/
EDGE = ROOT / "edge"
PROVIDER = EDGE / "data" / "qlib_us_1d"
INSTRUMENTS = PROVIDER / "instruments"

# Frozen by GATE_XS2.md. Changing any of these changes the universe under test
# and therefore requires a new gate file, not an edit here.
TOP_N = 30
LIQUIDITY_LOOKBACK = 60      # trading days of dollar volume used for the ranking
MIN_HISTORY = 252            # trading days of prior history required to qualify

# The 13 ETFs, excluded for the same reason as GATE_XS.md: ranking an index
# against a single stock is not a meaningful cross-sectional comparison.
ETFS = {
    "SPY", "QQQ", "IWM", "DIA", "GLD", "TLT", "HYG",
    "LQD", "XBI", "XLE", "XLF", "XLP", "XLU",
}


def load_panel() -> pd.DataFrame:
    """Return a (datetime, instrument) frame with close, volume, dollar volume."""
    import qlib
    from qlib.data import D

    qlib.init(provider_uri=str(PROVIDER), region="us")

    insts = [s for s in D.list_instruments(
        D.instruments("all"), as_list=True) if s.upper() not in ETFS]

    df = D.features(insts, ["$close", "$volume"], freq="day")
    df = df.rename(columns={"$close": "close", "$volume": "volume"})
    # Ranking only needs a consistent size proxy, not a reconstructed notional,
    # so adjusted close x adjusted volume is sufficient and avoids depending on
    # how the ingest handled the split factor.
    df["dollar_volume"] = df["close"] * df["volume"]
    return df.swaplevel().sort_index()  # -> (datetime, instrument)


def month_end_dates(index: pd.DatetimeIndex) -> List[pd.Timestamp]:
    """Last trading day of each calendar month present in the calendar."""
    s = pd.Series(index, index=index)
    return [g.max() for _, g in s.groupby([index.year, index.month])]


def select_members(
    panel: pd.DataFrame,
    top_n: int,
    lookback: int,
    min_history: int,
) -> Dict[pd.Timestamp, List[str]]:
    """Point-in-time membership: at each month end, use only data <= that date."""
    dv = panel["dollar_volume"].unstack("instrument").sort_index()
    close = panel["close"].unstack("instrument").sort_index()

    # Trailing median dollar volume and cumulative history count, both computed
    # with pandas rolling/expanding windows that are right-aligned -- so the
    # value at date t uses t and earlier only. That is the PIT guarantee.
    med_dv = dv.rolling(lookback, min_periods=lookback).median()
    history = close.notna().cumsum()

    members: Dict[pd.Timestamp, List[str]] = {}
    for asof in month_end_dates(dv.index):
        eligible = (history.loc[asof] >= min_history) & med_dv.loc[asof].notna()
        if not eligible.any():
            members[asof] = []
            continue
        ranked = med_dv.loc[asof][eligible].sort_values(ascending=False)
        members[asof] = sorted(ranked.head(top_n).index.tolist())
    return members


def to_intervals(
    members: Dict[pd.Timestamp, List[str]],
    calendar: pd.DatetimeIndex,
) -> List[Tuple[str, pd.Timestamp, pd.Timestamp]]:
    """Convert month-end snapshots to contiguous (symbol, start, end) spans.

    A decision made at month end M takes effect on the *next* trading day -- using
    it on M itself would be same-bar lookahead on the liquidity screen.
    """
    asofs = sorted(members)
    cal = list(calendar)

    def next_trading_day(d: pd.Timestamp) -> Optional[pd.Timestamp]:
        i = np.searchsorted(cal, d, side="right")
        return cal[i] if i < len(cal) else None

    # effective_from -> members, plus the date each span stops applying
    spans: List[Tuple[pd.Timestamp, pd.Timestamp, List[str]]] = []
    for i, asof in enumerate(asofs):
        start = next_trading_day(asof)
        if start is None:
            continue
        if i + 1 < len(asofs):
            end_excl = next_trading_day(asofs[i + 1])
            end = cal[np.searchsorted(cal, end_excl, side="left") - 1] if end_excl else cal[-1]
        else:
            end = cal[-1]
        if end >= start:
            spans.append((start, end, members[asof]))

    # Merge each symbol's consecutive spans into the fewest intervals.
    out: List[Tuple[str, pd.Timestamp, pd.Timestamp]] = []
    open_span: Dict[str, Tuple[pd.Timestamp, pd.Timestamp]] = {}
    for start, end, syms in spans:
        present = set(syms)
        for sym in list(open_span):
            if sym not in present:
                out.append((sym, *open_span.pop(sym)))
        for sym in present:
            if sym in open_span:
                open_span[sym] = (open_span[sym][0], end)
            else:
                open_span[sym] = (start, end)
    for sym, (s, e) in open_span.items():
        out.append((sym, s, e))

    return sorted(out, key=lambda r: (r[0], r[1]))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top-n", type=int, default=TOP_N)
    ap.add_argument("--lookback", type=int, default=LIQUIDITY_LOOKBACK)
    ap.add_argument("--min-history", type=int, default=MIN_HISTORY)
    ap.add_argument("--name", default="pit30", help="instruments file basename")
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = ap.parse_args(argv)

    panel = load_panel()
    calendar = panel.index.get_level_values("datetime").unique().sort_values()
    print(f"loaded {panel.index.get_level_values('instrument').nunique()} names, "
          f"{len(calendar)} trading days "
          f"({calendar[0].date()} -> {calendar[-1].date()})")

    members = select_members(panel, args.top_n, args.lookback, args.min_history)
    intervals = to_intervals(members, calendar)

    non_empty = {k: v for k, v in members.items() if v}
    first_asof = min(non_empty) if non_empty else None
    all_syms = sorted({s for v in members.values() for s in v})

    # Turnover of the universe itself -- how often the screen swaps a name. High
    # values here would mean the screen is adding churn of its own, on top of the
    # strategy turnover the gate is trying to reduce.
    keys = sorted(non_empty)
    swaps = [len(set(non_empty[b]) ^ set(non_empty[a])) / 2
             for a, b in zip(keys, keys[1:])]

    print(f"month-end snapshots: {len(members)} ({len(non_empty)} non-empty, "
          f"first {first_asof.date() if first_asof is not None else 'n/a'})")
    print(f"distinct names ever in {args.name}: {len(all_syms)}")
    print(f"intervals emitted: {len(intervals)}")
    print(f"median names swapped per month: {np.median(swaps) if swaps else float('nan'):.1f}")

    if first_asof is not None:
        print(f"\nmembers at {first_asof.date()}: {', '.join(non_empty[first_asof])}")
        last = max(non_empty)
        print(f"members at {last.date()}: {', '.join(non_empty[last])}")

    # The names xs40 excluded by hand -- report when the rule lets each one in,
    # so the PIT screen can be checked against the survivorship story directly.
    cohort = ["APLD", "ARM", "COIN", "IONQ", "PLTR", "RKLB", "SNOW"]
    print("\n2020-23 listing cohort, first PIT entry:")
    for sym in cohort:
        firsts = [s for (n, s, _) in intervals if n == sym]
        print(f"  {sym:<6} {min(firsts).date() if firsts else 'never qualifies'}")

    if args.dry_run:
        print("\n[dry-run] nothing written")
        return 0

    INSTRUMENTS.mkdir(parents=True, exist_ok=True)
    path = INSTRUMENTS / f"{args.name}.txt"
    path.write_text(
        "".join(f"{sym}\t{s.strftime('%Y-%m-%d')}\t{e.strftime('%Y-%m-%d')}\n"
                for sym, s, e in intervals),
        encoding="utf-8",
    )
    print(f"\nwrote {path.relative_to(ROOT)}")

    meta = EDGE / "runs" / "qlib_xs2" / f"{args.name}_manifest.json"
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(json.dumps({
        "name": args.name,
        "rule": {
            "top_n": args.top_n,
            "liquidity_lookback_days": args.lookback,
            "min_history_days": args.min_history,
            "rank_by": "trailing median dollar volume (close x volume)",
            "rebalanced": "month end, effective next trading day",
            "etfs_excluded": sorted(ETFS),
        },
        "calendar": {"start": str(calendar[0].date()), "end": str(calendar[-1].date()),
                     "n_days": int(len(calendar))},
        "n_intervals": len(intervals),
        "n_distinct_symbols": len(all_syms),
        "symbols": all_syms,
        "median_monthly_swaps": float(np.median(swaps)) if swaps else None,
        "gate": "edge/docs/GATE_XS2.md",
    }, indent=2), encoding="utf-8")
    print(f"wrote {meta.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
