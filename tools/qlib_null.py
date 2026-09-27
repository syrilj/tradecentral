#!/usr/bin/env python3
"""Permutation null for the GATE_XS2.md selection procedure.

The problem this exists to solve
--------------------------------
The phase-1 sweep selected xs40 / 21d / topk10 / n_drop2 at IR +2.518. But in the
same sweep, `pit30` scored Rank IC 0.0062 with Newey-West t = 0.37 -- no
measurable ranking skill whatsoever -- and still produced IR +1.396. A ranking
model that cannot rank should not earn an information ratio of 1.4.

That is the signature of the portfolio metric measuring something other than the
signal: with topk=10 out of 40 names rebalanced monthly over 491 days, the book
makes ~23 concentrated bets, and a long-only concentrated book measured against
SPY through the 2022 drawdown has enormous variance whatever the ranking is. The
"best of 36 configs" is then a maximum over 36 noisy draws, which is biased high
by construction.

So: what IR does this exact procedure produce when the signal is known to be
worthless? Anything the real run scores below that is not evidence.

The null used here
------------------
Permute the predicted scores within each trading day, leaving the real prices,
real universe, real costs and real book shape untouched. It isolates the
question that matters: **how much of the IR is the shape of the book rather than
the ranking?** No refit is needed, which is what makes it affordable.

A stricter variant -- permute the *training labels* and refit, so the null covers
the learner as well as the book -- is roughly 40x the compute and is deliberately
not implemented here. If the cheap null already explains the observed IR, the
expensive one cannot rescue it.

The reported statistic is the distribution of `max IR over the config grid`,
because that maximum is what the selection rule actually uses. Comparing the real
run's best IR against a null distribution of *single* IRs would understate the
bar by exactly the multiple-comparisons factor the gate exists to control.

Nothing here reads a date on or after 2024-01-01: this is a phase-1 diagnostic
and the confirmation segment stays untouched.

Usage (from alltrading/):
  edge/.venv-qlib/bin/python edge/tools/qlib_null.py --n-perm 2 --workers 1   # smoke
  edge/.venv-qlib/bin/python edge/tools/qlib_null.py --n-perm 200 --workers 8
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import product
from pathlib import Path
from typing import Dict, List, Optional

os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "edge" / "tools"))

from qlib_sweep import (  # noqa: E402  - path set above
    N_DROP, PROVIDER, REBALANCE_DAYS, SEGMENTS, TOPK, assert_selection_wall, build_and_fit, rank_ic_metrics, run_backtest,
)

OUTDIR = ROOT / "edge" / "runs" / "qlib_xs2"
GRID = list(product(REBALANCE_DAYS, TOPK, N_DROP))

_CACHE: Dict[str, object] = {}


def permute_within_day(s: pd.Series, seed: int) -> pd.Series:
    """Shuffle values inside each trading day, preserving the panel's shape.

    Cross-sectional shuffling (not global) is the right null here: it destroys
    *which name* is ranked where while preserving how many names trade each day,
    the calendar, and the marginal distribution of scores.
    """
    rng = np.random.default_rng(seed)
    out = s.copy()
    for _, idx in s.groupby(level="datetime").groups.items():
        vals = s.loc[idx].to_numpy()
        rng.shuffle(vals)
        out.loc[idx] = vals
    return out


def _prepare(universe: str):
    """Fit the real model once per worker process and cache it."""
    if universe not in _CACHE:
        import qlib
        if not _CACHE.get("_init"):
            qlib.init(provider_uri=str(PROVIDER), region="us")
            _CACHE["_init"] = True
        seg = SEGMENTS["selection"]["expanding"]
        assert_selection_wall(seg)
        _model, _ds, pred, label = build_and_fit(universe, seg)
        _CACHE[universe] = (pred, label, seg)
    return _CACHE[universe]


def one_permutation(universe: str, seed: int, null: str) -> Dict[str, object]:
    """Run the full 36-config grid once under the null; return its max IR."""
    pred, label, seg = _prepare(universe)

    scores = permute_within_day(pred, seed)
    ic = rank_ic_metrics(scores, label)

    irs: List[float] = []
    rows: List[Dict[str, object]] = []
    for rebalance, topk, n_drop in GRID:
        try:
            bt = run_backtest(scores, seg, rebalance, topk, n_drop)
            ir = float(bt["excess_return_with_cost"]["information_ratio"])
            turnover = float(bt["turnover"]["annualized_one_way"])
        except Exception:  # noqa: BLE001 - a failed config is not a null draw
            continue
        rows.append({"rebalance_days": rebalance, "topk": topk, "n_drop": n_drop,
                     "ir": ir, "turnover": turnover})
        # The selection rule filters on turnover BEFORE taking the argmax, so the
        # null must apply the same filter or it is not the same procedure.
        if turnover <= 4.0:
            irs.append(ir)

    return {
        "seed": seed, "universe": universe, "null": null,
        "n_configs": len(rows), "n_after_turnover_filter": len(irs),
        "max_ir": max(irs) if irs else None,
        "median_ir": float(np.median([r["ir"] for r in rows])) if rows else None,
        "rank_ic": ic.get("mean_rank_ic"),
        "t_stat_newey_west": ic.get("t_stat_newey_west"),
    }


def _worker(task):
    universe, seed, null = task
    try:
        return one_permutation(universe, seed, null)
    except Exception as exc:  # noqa: BLE001 - report, never fabricate a draw
        return {"seed": seed, "universe": universe, "null": null,
                "error": f"{type(exc).__name__}: {exc}"}


def summarize(draws: List[Dict[str, object]], observed: Optional[float]) -> Dict[str, object]:
    vals = np.array([d["max_ir"] for d in draws
                     if d.get("max_ir") is not None], dtype=float)
    if not len(vals):
        return {"n_draws": 0}
    out = {
        "n_draws": int(len(vals)),
        "null_max_ir": {
            "mean": float(vals.mean()), "std": float(vals.std(ddof=1)) if len(vals) > 1 else None,
            "p50": float(np.percentile(vals, 50)), "p90": float(np.percentile(vals, 90)),
            "p95": float(np.percentile(vals, 95)), "p99": float(np.percentile(vals, 99)),
            "max": float(vals.max()),
        },
    }
    if observed is not None:
        # One-sided empirical p-value with the +1 correction, so a p of exactly
        # zero is never reported off a finite number of draws.
        out["observed_max_ir"] = float(observed)
        out["empirical_p_value"] = float((np.sum(vals >= observed) + 1) / (len(vals) + 1))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-perm", type=int, default=500)
    ap.add_argument("--universe", default="xs40")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--observed-ir", type=float, default=None,
                    help="real run's selected max IR, for the p-value")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    if args.observed_ir is None:
        sel = OUTDIR / "selection.json"
        if sel.exists():
            payload = json.loads(sel.read_text(encoding="utf-8"))
            cands = [r["excess_return_with_cost"]["information_ratio"]
                     for r in payload["results"]
                     if r["universe"] == args.universe and "error" not in r
                     and r["turnover"]["annualized_one_way"] <= 4.0]
            args.observed_ir = max(cands) if cands else None

    print(f"null=score universe={args.universe} n_perm={args.n_perm} "
          f"workers={args.workers} observed_max_ir={args.observed_ir}", flush=True)

    tasks = [(args.universe, s, "score") for s in range(args.n_perm)]
    draws: List[Dict[str, object]] = []
    t0 = time.time()

    if args.workers <= 1:
        for t in tasks:
            draws.append(_worker(t))
            print(f"  [{len(draws)}/{len(tasks)}] max_ir={draws[-1].get('max_ir')} "
                  f"({time.time() - t0:.0f}s)", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futs = [pool.submit(_worker, t) for t in tasks]
            for f in as_completed(futs):
                draws.append(f.result())
                if len(draws) % 10 == 0 or len(draws) == len(tasks):
                    done = [d["max_ir"] for d in draws if d.get("max_ir") is not None]
                    if done:
                        p50_str = f"{np.percentile(done, 50):.3f}"
                        p95_str = f"{np.percentile(done, 95):.3f}"
                    else:
                        p50_str = p95_str = "N/A"
                    print(f"  [{len(draws)}/{len(tasks)}] "
                          f"null max IR p50={p50_str} "
                          f"p95={p95_str} "
                          f"({time.time() - t0:.0f}s)", flush=True)

    summary = summarize(draws, args.observed_ir)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else OUTDIR / f"null_score_{args.universe}.json"
    out_path.write_text(json.dumps({
        "gate": "edge/docs/GATE_XS2.md",
        "diagnostic": "permutation null for the phase-1 selection procedure",
        "null_type": "score",
        "universe": args.universe,
        "grid_size": len(GRID),
        "turnover_cap_annualized_one_way": 4.0,
        "summary": summary,
        "draws": draws,
    }, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 68)
    if summary.get("n_draws"):
        n = summary["null_max_ir"]
        print(f"null distribution of max-IR-over-{len(GRID)} ({summary['n_draws']} draws)")
        print(f"  p50 {n['p50']:+.3f}   p90 {n['p90']:+.3f}   "
              f"p95 {n['p95']:+.3f}   p99 {n['p99']:+.3f}   max {n['max']:+.3f}")
        if "empirical_p_value" in summary:
            p = summary["empirical_p_value"]
            print(f"  observed {summary['observed_max_ir']:+.3f}  ->  empirical p = {p:.4f}")
            print(f"  {'SIGNAL survives the null' if p < 0.05 else 'NOT distinguishable from the null'}")
    else:
        print("no valid null draws -- check errors in the output JSON")
    print("=" * 68)
    print(f"wrote {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
