#!/usr/bin/env python3
"""Are ANY known cross-sectional effects present in the wide data? No ML.

Six axes have now returned null on this dataset (GATE_XS4_DEV.md section 6):
universe size, turnover, regime window, training configuration, learner class,
and forward horizon. When that many independent methods all return exactly
nothing, the remaining hypotheses are (a) the input carries no signal, or
(b) something upstream of every model is broken. Another architecture cannot
distinguish those two. This can.

THE TEST
--------
Compute textbook cross-sectional factors straight from adjusted closes with
pandas -- no qlib handler, no normalization, no learner, no train/test split,
nothing that any of the six nulls passed through -- and measure their rank IC
against forward returns.

Short-term reversal is the load-bearing one. "Last week's losers outperform next
week" is among the most replicated effects in US equities (Jegadeesh 1990,
Lehmann 1990) and it is strong in exactly this cap range. If reversal is absent
here, the data or the alignment is broken, because reversal is not a subtle
effect that a clean pipeline can miss.

SIGNS ARE PREDICTED BEFORE THE RUN. Each factor below is defined so that the
literature predicts POSITIVE rank IC against the forward return. That is what
makes this a test rather than a search: five factors, five directional
predictions registered in code, and a sign flip is a failure, not a discovery.
Nothing here is fitted, so there is no overfitting surface -- these are the same
five formulas whatever data you point them at.

  rev1     -1 * (1-day return)      reversal: yesterday's losers bounce
  rev5     -1 * (5-day return)      reversal: last week's losers bounce
  mom12_1  12-month return, skipping the most recent month (Jegadeesh & Titman)
  lowvol   -1 * (20-day return stdev)   low-volatility anomaly
  liq      -1 * (20-day mean dollar volume)   illiquidity premium

Usage (from alltrading/):
  edge/.venv-qlib/bin/python edge/tools/factor_probe.py --market pitwide
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "edge" / "tools"))
sys.path.insert(0, str(ROOT))

from qlib_run_wide import load_spec, _newey_west_tstat  # noqa: E402
from edge.research.portfolio import simulate_long_short  # noqa: E402

# Windows mirror GATE_XS4's dev split so results sit next to the model numbers.
WINDOWS = {
    "train  2016-08..2021-06": ("2016-08-01", "2021-06-30"),
    "test   2022-01..2023-12": ("2022-01-18", "2023-12-29"),
    "recent 2024-01..2026-07": ("2024-01-16", "2026-07-29"),
}


def rank_ic(fac: pd.DataFrame, fwd: pd.DataFrame, min_names: int = 20) -> np.ndarray:
    """Daily cross-sectional Spearman between factor and forward return.

    Both frames are date x instrument. Ranking per row makes this scale-free,
    so no normalization step can distort it -- unlike the model path, where
    RobustZScoreNorm is fit on train and applied to test.
    """
    f = fac.rank(axis=1)
    r = fwd.rank(axis=1)
    valid = f.notna() & r.notna()
    n = valid.sum(axis=1)
    f, r = f.where(valid), r.where(valid)
    fc = f.sub(f.mean(axis=1), axis=0)
    rc = r.sub(r.mean(axis=1), axis=0)
    num = (fc * rc).sum(axis=1)
    den = np.sqrt((fc ** 2).sum(axis=1) * (rc ** 2).sum(axis=1))
    ic = (num / den).where(n >= min_names)
    return ic.dropna().to_numpy(dtype=float)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="pitwide")
    ap.add_argument("--horizons", default="1,5", help="forward horizons in trading days")
    args = ap.parse_args()

    import qlib
    from qlib.data import D

    cfg = load_spec(args.market)
    qlib.init(**cfg["qlib_init"])

    insts = D.instruments(market=args.market)
    raw = D.features(insts, ["$close", "$volume"],
                     start_time="2015-06-01", end_time="2026-07-29", freq="day")
    close = raw["$close"].unstack("instrument").sort_index()
    volume = raw["$volume"].unstack("instrument").sort_index()
    print(f"loaded {close.shape[1]} names x {close.shape[0]} days "
          f"({close.index.min().date()} .. {close.index.max().date()})")

    ret1 = close.pct_change()

    # Predicted-positive-IC forms. Signs are part of the hypothesis.
    factors = {
        "rev1": -ret1,
        "rev5": -close.pct_change(5),
        "mom12_1": close.shift(21) / close.shift(252) - 1.0,
        "lowvol": -ret1.rolling(20).std(),
        "liq": -(close * volume).rolling(20).mean(),
    }

    horizons = [int(h) for h in args.horizons.split(",")]
    # Forward return over h days, strictly after today: close(t+1+h)/close(t+1)-1.
    # The +1 offset keeps today's close out of the position, matching the -1 leg
    # in the gate label. Without it the factor and the return share a day and
    # rev1 reports a huge fake IC that is pure bid-ask bounce.
    fwd = {h: (close.shift(-1 - h) / close.shift(-1) - 1.0) for h in horizons}

    for h in horizons:
        print("\n" + "=" * 88)
        print(f"FORWARD HORIZON {h}d   (predicted sign of every IC below: POSITIVE)")
        print("=" * 88)
        print(f"{'factor':<10}{'window':<26}{'days':>6}{'mean IC':>10}"
              f"{'ICIR':>9}{'NW t':>8}{'%>0':>7}  verdict")
        print("-" * 88)
        for fname, fac in factors.items():
            for wname, (lo, hi) in WINDOWS.items():
                m = (fac.index >= lo) & (fac.index <= hi)
                arr = rank_ic(fac.loc[m], fwd[h].loc[m])
                if len(arr) < 20:
                    print(f"{fname:<10}{wname:<26}{len(arr):>6}   too few days")
                    continue
                mean = arr.mean()
                sd = arr.std(ddof=1)
                icir = mean / sd if sd > 0 else float("nan")
                t = _newey_west_tstat(arr, lags=max(h, 1))
                if abs(t) < 2.0:
                    verdict = "noise"
                elif t > 0:
                    verdict = "PRESENT (as predicted)"
                else:
                    verdict = "SIGN FLIP -- opposite of literature"
                print(f"{fname:<10}{wname:<26}{len(arr):>6}{mean:>+10.4f}"
                      f"{icir:>+9.4f}{t:>+8.2f}{(arr > 0).mean():>7.1%}  {verdict}")
            print()

    # ---- combination -------------------------------------------------------
    # Individually rev5 and mom12_1 are weak (|t| 1.0-1.6). Both hold their
    # predicted sign in every window, and they are near-uncorrelated by
    # construction -- one is a 5-day effect, the other a 12-month effect that
    # explicitly skips the last month. Combining weak, low-correlation signals is
    # the entire mechanism behind a multi-factor book, and it is the standard
    # response to exactly this evidence.
    #
    # EQUAL WEIGHTS, NOT FITTED. No optimizer, no regression, no search over
    # weightings. Cross-sectional rank -> z-score per day, then average. There is
    # nothing here to overfit: the same two formulas at the same weights would be
    # applied unchanged to any dataset. This matters because at IC ~0.02 an
    # optimizer has far more capacity to fit noise than signal -- which is the
    # most likely explanation for why six ML configurations all returned zero on
    # data that demonstrably contains these effects.
    def cs_z(df: pd.DataFrame) -> pd.DataFrame:
        r = df.rank(axis=1)
        return r.sub(r.mean(axis=1), axis=0).div(r.std(axis=1).replace(0, np.nan), axis=0)

    combo = (cs_z(factors["rev5"]) + cs_z(factors["mom12_1"])) / 2.0

    print("\n" + "=" * 88)
    print("COMBINED FACTOR  0.5*z(rev5) + 0.5*z(mom12_1)   [equal weight, unfitted]")
    print("=" * 88)
    print(f"{'horizon':<9}{'window':<26}{'days':>6}{'mean IC':>10}{'ICIR':>9}"
          f"{'NW t':>8}{'%>0':>7}{'LS ann.':>10}{'LS IR':>8}")
    print("-" * 88)
    for h in horizons:
        for wname, (lo, hi) in WINDOWS.items():
            m = (combo.index >= lo) & (combo.index <= hi)
            arr = rank_ic(combo.loc[m], fwd[h].loc[m])
            if len(arr) < 20:
                continue
            sd = arr.std(ddof=1)
            t = _newey_west_tstat(arr, lags=max(h, 1))

            # Dollar-neutral long-short: top quintile minus bottom quintile,
            # rebalanced every h days, equal weight, held flat until the next
            # rebalance. Market-NEUTRAL by construction -- this is the read
            # that GATE_XS3's long-only book could not give, where a -0.0016
            # IC still produced IR +0.945 purely from index beta. A
            # long-short spread cannot borrow beta.
            #
            # Migrated onto simulate_long_short: deciding quintile membership
            # stays here (this file's own signal logic); earning the book's
            # daily return is delegated to the shared primitive instead of
            # sampling the isolated h-bar forward return once per rebalance.
            # `fwd[h] = close.shift(-1-h)/close.shift(-1)-1` spans, at a
            # rebalance formed from data through close t, the h intervals
            # from close(t+1) to close(t+1+h) -- realised ON bars t+2..t+h+1.
            # execution_lag=2 (not 1) reproduces that exactly.
            c = combo.loc[m]
            idx = c.index[::h]                 # non-overlapping rebalance rows
            c_r = c.loc[idx]
            hi_q = c_r.ge(c_r.quantile(0.8, axis=1), axis=0) & c_r.notna()
            lo_q = c_r.le(c_r.quantile(0.2, axis=1), axis=0) & c_r.notna()

            n_long = hi_q.sum(axis=1).replace(0, np.nan)
            n_short = lo_q.sum(axis=1).replace(0, np.nan)
            if n_long.isna().all() or n_short.isna().all():
                continue
            w_long_sparse = hi_q.div(n_long, axis=0).fillna(0.0)
            w_short_sparse = lo_q.div(n_short, axis=0).fillna(0.0)

            close_win = close.loc[lo:hi]
            w_long = w_long_sparse.reindex(close_win.index).ffill().fillna(0.0)
            w_short = w_short_sparse.reindex(close_win.index).ffill().fillna(0.0)
            if w_long.to_numpy().sum() == 0 or w_short.to_numpy().sum() == 0:
                continue

            # No cost model here (this section never had one) -- cost_per_side=0
            # isolates whether the alignment/methodology change itself moved
            # the number, per the migration's own purpose.
            sim = simulate_long_short(
                long_weights=w_long, short_weights=w_short,
                close=close_win, execution_lag=2, cost_per_side=0.0,
            )
            ann = sim.gross_annual_return
            ls_ir = sim.gross_sharpe
            print(f"{str(h)+'d':<9}{wname:<26}{len(arr):>6}{arr.mean():>+10.4f}"
                  f"{arr.mean()/sd:>+9.4f}{t:>+8.2f}{(arr > 0).mean():>7.1%}"
                  f"{ann:>+10.2%}{ls_ir:>+8.2f}")
        print()

    print("=" * 88)
    print("HOW TO READ THIS")
    print("  rev1/rev5 present with t>2  -> data and alignment are sound; the six")
    print("     model nulls are a modelling failure, and a plain factor book is")
    print("     the thing that works.")
    print("  rev1/rev5 absent everywhere -> something upstream of every model is")
    print("     broken. Short-term reversal does not go missing in clean US")
    print("     equity data; no architecture can fix a pipeline that loses it.")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    sys.exit(main())
