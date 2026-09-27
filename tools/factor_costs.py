#!/usr/bin/env python3
"""Does the rev5+mom12_1 combo survive transaction costs? FACTOR_PROBE_RESULT.md §6.3.

The long-short spreads in FACTOR_PROBE_RESULT.md are GROSS. That document flags
this as the open question: "at 5d rebalance the turnover is high enough that
10bp round-trip could consume much of a +2% spread. Nothing here has been
costed." This answers it.

A dollar-neutral book pays costs on BOTH legs, so a rebalance that replaces
fraction `t` of each leg costs `2 * t * cost_per_side`. At 1-day rebalance the
turnover is near-total every day, which is why a 1d signal with a good gross
number can still be untradeable.

Usage (from alltrading/):
  edge/.venv-qlib/bin/python edge/tools/factor_costs.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "edge" / "tools"))

WINDOWS = {
    "train  2016-08..2021-06": ("2016-08-01", "2021-06-30"),
    "test   2022-01..2023-12": ("2022-01-18", "2023-12-29"),
    "recent 2024-01..2026-07": ("2024-01-16", "2026-07-29"),
}


def cs_z(df: pd.DataFrame) -> pd.DataFrame:
    r = df.rank(axis=1)
    return r.sub(r.mean(axis=1), axis=0).div(r.std(axis=1).replace(0, np.nan), axis=0)


def main() -> int:
    import qlib
    from qlib.data import D
    from qlib_run_wide import load_spec

    cfg = load_spec("pitwide")
    qlib.init(**cfg["qlib_init"])
    raw = D.features(D.instruments(market="pitwide"), ["$close"],
                     start_time="2015-06-01", end_time="2026-07-29", freq="day")
    close = raw["$close"].unstack("instrument").sort_index()

    combo = (cs_z(-close.pct_change(5, fill_method=None))
             + cs_z(close.shift(21) / close.shift(252) - 1.0)) / 2.0

    print(f"{'h':>3} {'window':<26}{'turn/rb':>9}{'ann.turn':>10}"
          f"{'GROSS':>9}{'NET@5bp':>9}{'NET@10bp':>10}{'net IR':>9}")
    print("-" * 85)
    for h in (1, 5):
        fwd = close.shift(-1 - h) / close.shift(-1) - 1.0
        for wname, (lo, hi) in WINDOWS.items():
            m = (combo.index >= lo) & (combo.index <= hi)
            c, f = combo.loc[m], fwd.loc[m]
            hq = c.ge(c.quantile(0.8, axis=1), axis=0) & c.notna()
            lq = c.le(c.quantile(0.2, axis=1), axis=0) & c.notna()
            sp = (f.where(hq).mean(axis=1) - f.where(lq).mean(axis=1)).dropna()
            idx = sp.index[::h]                    # non-overlapping holds
            sp = sp.loc[idx]
            H, L = hq.loc[idx], lq.loc[idx]

            # fraction of each leg replaced between consecutive rebalances
            tl = 1 - (H & H.shift(1)).sum(axis=1).iloc[1:] / H.sum(axis=1).iloc[1:].clip(lower=1)
            ts = 1 - (L & L.shift(1)).sum(axis=1).iloc[1:] / L.sum(axis=1).iloc[1:].clip(lower=1)
            tr = float(((tl + ts) / 2).mean())

            per_yr = 252.0 / h
            mu, sd = sp.mean(), sp.std(ddof=1)
            gross = mu * per_yr
            net5 = (mu - 2 * tr * 0.0005) * per_yr    # both legs, 5bp per side
            net10 = (mu - 2 * tr * 0.0010) * per_yr
            ir = ((mu - 2 * tr * 0.0010) / sd * np.sqrt(per_yr)) if sd > 0 else float("nan")
            print(f"{h:>2}d {wname:<26}{tr:>9.1%}{tr*per_yr:>10.1f}"
                  f"{gross:>+9.2%}{net5:>+9.2%}{net10:>+10.2%}{ir:>+9.2f}")
        print()

    print("=" * 85)
    print("NET@10bp is the number that matters: 5bp per side is optimistic for a")
    print("450-name book, and options spreads are far wider than stock spreads.")
    print("=" * 85)
    return 0


if __name__ == "__main__":
    sys.exit(main())
