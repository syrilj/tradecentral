#!/usr/bin/env python3
"""Build a tradeable factor model: attack turnover, not the signal.

FACTOR_PROBE_RESULT.md sections 2-3 established the signal is real -- rev5 and
mom12_1 hold their predicted sign in 12 of 12 cells, combined IC ~+0.02. Section
7 established it loses money at 10bp because annualized turnover is 65x (1d) and
30x (5d) against a 400% cap.

That is an IMPLEMENTATION failure, not a signal failure, and it has standard
fixes that this project has never tried. mom12_1 is a twelve-month signal;
rebalancing it daily is throwing away money for no informational gain.

Three levers, all standard portfolio construction, none of which touch the
signal formulas:

  HOLD PERIOD   rebalance every h days instead of every 1 or 5. Turnover falls
                roughly as 1/h while a slow signal's information decays much
                more slowly than that.

  SMOOTHING     average the raw signal over `smooth` days before ranking. Kills
                day-to-day rank jitter that causes names to flip across the
                quintile boundary without any real change in view.

  BUFFER        hysteresis. Enter the long book at the top `enter` quantile, but
                only EXIT when a name falls below the wider `exit` quantile. A
                name sitting at the boundary stops churning in and out. This is
                the single highest-leverage fix: it typically removes 40-60% of
                turnover for a few basis points of signal.

Costs are charged on both legs of a dollar-neutral book: a rebalance replacing
fraction t of each leg costs 2*t*cost_per_side.

SELECTION HONESTY. This searches a grid of IMPLEMENTATION parameters, so it is a
search and the trial count is recorded in the output JSON. It is a much smaller
search surface than a model fit -- 4 hold periods x 3 smoothings x 2 buffer
settings = 24 cells, all on parameters with a mechanical justification and a
predicted direction (more holding, more smoothing, wider buffer -> less
turnover). Selection uses train+test only. The 2024-01..2026-07 window is
reported for every cell but is NOT used to choose, and is already compromised
per FACTOR_PROBE_RESULT.md section 1.

Usage (from alltrading/):
  edge/.venv-qlib/bin/python edge/tools/build_factor_model.py
  edge/.venv-qlib/bin/python edge/tools/build_factor_model.py --emit-signal
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
EDGE = ROOT / "edge"
OUTDIR = EDGE / "runs" / "factor_model"
sys.path.insert(0, str(EDGE / "tools"))
sys.path.insert(0, str(ROOT))

from edge.research.portfolio import simulate_long_short  # noqa: E402

SELECT = {                       # used to choose the configuration
    "train": ("2016-08-01", "2021-06-30"),
    "test": ("2022-01-18", "2023-12-29"),
}
HOLDOUT = {"recent": ("2024-01-16", "2026-07-29")}   # reported, never selected on

COST_PER_SIDE = 0.0010           # 10bp per side = 20bp round trip, deliberately harsh


def cs_z(df: pd.DataFrame) -> pd.DataFrame:
    r = df.rank(axis=1)
    return r.sub(r.mean(axis=1), axis=0).div(r.std(axis=1).replace(0, np.nan), axis=0)


def book_with_buffer(sig: pd.DataFrame, idx, enter_q: float, exit_q: float,
                     long_side: bool) -> pd.DataFrame:
    """Membership with hysteresis, evaluated only on rebalance dates.

    A name joins when it is past `enter_q` and stays until it falls past
    `exit_q`. With enter==exit this reduces exactly to a plain quantile cut, so
    the no-buffer arm shares this code path and stays comparable.
    """
    s = sig.loc[idx]
    if long_side:
        strong = s.ge(s.quantile(enter_q, axis=1), axis=0) & s.notna()
        weak = s.ge(s.quantile(exit_q, axis=1), axis=0) & s.notna()
    else:
        strong = s.le(s.quantile(1 - enter_q, axis=1), axis=0) & s.notna()
        weak = s.le(s.quantile(1 - exit_q, axis=1), axis=0) & s.notna()

    if enter_q == exit_q:
        return strong

    held = strong.iloc[0]
    rows = [held]
    for i in range(1, len(strong)):
        # carry yesterday's members that are still inside the wider exit band,
        # then admit anyone newly inside the tighter entry band
        held = (held & weak.iloc[i]) | strong.iloc[i]
        rows.append(held)
    return pd.DataFrame(rows, index=strong.index, columns=strong.columns)


def evaluate(sig: pd.DataFrame, close: pd.DataFrame, h: int,
             enter_q: float, exit_q: float, windows: dict) -> dict:
    """Buffered top/bottom-quantile book, rebalanced every h bars.

    Deciding the book (`book_with_buffer`'s hysteresis membership) stays
    here -- that is this file's own portfolio-construction logic. Earning
    the book's return, charging turnover cost, and computing the risk
    stats is delegated to `simulate_long_short` instead of the old
    "sample the h-bar forward return only at rebalance points" shortcut,
    which produced one point observation per rebalance rather than a real
    daily P&L series.

    Lag note: the old convention, `close.shift(-1-h)/close.shift(-1)-1`,
    measured at a rebalance formed using data through close t, spans the h
    price intervals from close(t+1) to close(t+1+h) -- realised ON bars
    t+2 .. t+h+1. `execution_lag=2` (not 1) reproduces that: the book is
    tradeable no earlier than t+1, and is not credited with that first
    bar's own move either, so it first earns on t+2, matching the h-bar
    forward window this function always reported.
    """
    out = {}
    for name, (lo, hi) in windows.items():
        m = (sig.index >= lo) & (sig.index <= hi)
        s = sig.loc[m]
        idx = s.index[::h]
        H = book_with_buffer(s, idx, enter_q, exit_q, True)
        L = book_with_buffer(s, idx, enter_q, exit_q, False)

        n_long = H.sum(axis=1).replace(0, np.nan)
        n_short = L.sum(axis=1).replace(0, np.nan)
        if n_long.isna().all() or n_short.isna().all() or len(idx) < 10:
            continue

        w_long_sparse = H.div(n_long, axis=0).fillna(0.0)
        w_short_sparse = L.div(n_short, axis=0).fillna(0.0)

        # Hold each h-spaced rebalance's book flat until the next one -- a
        # plain ffill reproduces this exactly because `idx` covers the
        # window at a constant h-row cadence.
        close_win = close.loc[lo:hi]
        w_long = w_long_sparse.reindex(close_win.index).ffill().fillna(0.0)
        w_short = w_short_sparse.reindex(close_win.index).ffill().fillna(0.0)

        sim = simulate_long_short(
            long_weights=w_long, short_weights=w_short,
            close=close_win, execution_lag=2, cost_per_side=COST_PER_SIDE,
        )

        tl = 1 - (H & H.shift(1)).sum(axis=1).iloc[1:] / H.sum(axis=1).iloc[1:].clip(lower=1)
        ts = 1 - (L & L.shift(1)).sum(axis=1).iloc[1:] / L.sum(axis=1).iloc[1:].clip(lower=1)
        turn = float(((tl + ts) / 2).mean())
        per_yr = 252.0 / h

        out[name] = {
            "n_rebalances": int(len(idx)),
            "turnover_per_rebalance": turn,
            "annualized_turnover_one_way": turn * per_yr,
            "gross_annual": sim.gross_annual_return,
            "net_annual": sim.net_annual_return,
            "net_ir": sim.sharpe,
            "avg_names_per_side": float(H.sum(axis=1).mean()),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="pitwide")
    ap.add_argument("--emit-signal", action="store_true",
                    help="write today's ranked signal for the selected config")
    args = ap.parse_args()

    import qlib
    from qlib.data import D
    from qlib_run_wide import load_spec

    cfg = load_spec(args.market)
    qlib.init(**cfg["qlib_init"])
    raw = D.features(D.instruments(market=args.market), ["$close"],
                     start_time="2015-06-01", end_time="2026-07-29", freq="day")
    close = raw["$close"].unstack("instrument").sort_index()

    base = (cs_z(-close.pct_change(5, fill_method=None))
            + cs_z(close.shift(21) / close.shift(252) - 1.0)) / 2.0
    mom_only = cs_z(close.shift(21) / close.shift(252) - 1.0)

    grid = []
    for sig_name, sig0 in (("combo", base), ("mom_only", mom_only)):
        for smooth in (1, 5, 20):
            sig = sig0.rolling(smooth).mean() if smooth > 1 else sig0
            for h in (5, 20, 60):
                for enter_q, exit_q in ((0.80, 0.80), (0.80, 0.60)):
                    sel = evaluate(sig, close, h, enter_q, exit_q, SELECT)
                    if len(sel) < 2:
                        continue
                    hold = evaluate(sig, close, h, enter_q, exit_q, HOLDOUT)
                    # selection objective: WORST net IR across train and test.
                    # Optimising the mean would let one strong window carry a
                    # broken one; the worst-case forces consistency, which is
                    # the property that failed in FACTOR_PROBE_RESULT.md s7.
                    score = min(v["net_ir"] for v in sel.values())
                    grid.append({
                        "signal": sig_name, "smooth": smooth, "hold_days": h,
                        "enter_q": enter_q, "exit_q": exit_q,
                        "worst_net_ir_selection": score,
                        "selection": sel, "holdout": hold,
                    })

    grid.sort(key=lambda r: r["worst_net_ir_selection"], reverse=True)

    print(f"\nnet of {COST_PER_SIDE*1e4:.0f}bp/side. Selection = worst net IR over train+test.")
    print(f"{'signal':<9}{'sm':>3}{'hold':>5}{'buf':>5}"
          f"{'annTurn':>9}{'netTR':>8}{'netTE':>8}{'WORST':>8}   {'netRECENT':>10}")
    print("-" * 78)
    for r in grid[:12]:
        s, ho = r["selection"], r["holdout"].get("recent", {})
        print(f"{r['signal']:<9}{r['smooth']:>3}{r['hold_days']:>5}"
              f"{'yes' if r['exit_q'] != r['enter_q'] else 'no':>5}"
              f"{s['test']['annualized_turnover_one_way']:>9.1f}"
              f"{s['train']['net_ir']:>+8.2f}{s['test']['net_ir']:>+8.2f}"
              f"{r['worst_net_ir_selection']:>+8.2f}   {ho.get('net_ir', float('nan')):>+10.2f}")

    best = grid[0]
    print("\n" + "=" * 78)
    print(f"SELECTED  {best['signal']}  smooth={best['smooth']}  hold={best['hold_days']}d  "
          f"buffer={'yes' if best['exit_q'] != best['enter_q'] else 'no'}")
    for w, v in list(best["selection"].items()) + list(best["holdout"].items()):
        print(f"  {w:<8} net {v['net_annual']:>+7.2%}/yr  IR {v['net_ir']:>+5.2f}  "
              f"gross {v['gross_annual']:>+7.2%}  turn {v['annualized_turnover_one_way']:>5.1f}x  "
              f"names/side {v['avg_names_per_side']:.0f}")
    print("=" * 78)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "grid.json").write_text(json.dumps({
        "cost_per_side_bps": COST_PER_SIDE * 1e4,
        "trial_count": len(grid),
        "selection_windows": SELECT,
        "holdout_window_NOT_used_for_selection": HOLDOUT,
        "selected": {k: best[k] for k in
                     ("signal", "smooth", "hold_days", "enter_q", "exit_q")},
        "results": grid,
    }, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUTDIR/'grid.json'}  ({len(grid)} configurations evaluated)")

    if args.emit_signal:
        sig0 = base if best["signal"] == "combo" else mom_only
        sig = sig0.rolling(best["smooth"]).mean() if best["smooth"] > 1 else sig0
        today = sig.dropna(how="all").iloc[-1].dropna().sort_values(ascending=False)
        n = int(len(today) * 0.20)
        out = {
            "asof": str(sig.dropna(how="all").index[-1].date()),
            "config": {k: best[k] for k in ("signal", "smooth", "hold_days", "enter_q", "exit_q")},
            "long": today.head(n).round(4).to_dict(),
            "short": today.tail(n).round(4).to_dict(),
        }
        (OUTDIR / "signal_latest.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"wrote {OUTDIR/'signal_latest.json'}  "
              f"({n} long / {n} short as of {out['asof']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
