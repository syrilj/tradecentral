#!/usr/bin/env python3
"""
Reproducible proof that the Kronos "selective model" headline numbers
(71% all-days / 82-84% actionable) were a lookahead artifact — and that the
2026-07-29 fix to Kronos/bakeoff_trend_v5.py removes it.

Run:
    python3 edge/tools/verify_no_lookahead.py

What it does
------------
1. Loads the leak-free walk-forward artifact produced by Kronos/eval_walkforward.py,
   which stores `selective_ret` computed from strictly-prior bars.
2. Prints the CLEAN accuracy of that selective signal.
3. Re-runs the exact same selective model but feeding `last_ret = actual_ret`,
   which is what Kronos/bakeoff_trend_v5.py used to do by accident (see proof
   below) before the 2026-07-29 fix. This section is a standing mechanism
   demonstration — it deliberately hardcodes the leak to show that
   point_bias.py's anti-fade branches are "correct" by construction whenever
   they are fed the realized return — it does not call bakeoff_trend_v5.py
   and its output does not change when bakeoff_trend_v5.py is fixed.
4. Reconstructs `last_ret`/`ret_3d` the way the FIXED bakeoff_trend_v5.py now
   does — strictly-prior closes only — using nothing but this JSON (chaining
   consecutive days' `last_close` fields; no network/yfinance call needed)
   and shows this now lands back in the leak-free ~49-52% range, matching
   section 1 instead of section 3.

The leak, algebraically (as it was before the 2026-07-29 fix)
---------------------------------------------------------------
    eval_walkforward.py:440   date         = df.iloc[t].timestamps      <- TARGET day
    eval_walkforward.py:374   actual_close = df.iloc[t].close
    eval_walkforward.py:375   last_close   = df.iloc[t-1].close
    bakeoff_trend_v5.py:43-45 closes       = hist[timestamps <= date]   <- INCLUDES bar t (FIXED: now `< date`)
    bakeoff_trend_v5.py:65    last_ret     = closes[-1]/closes[-2] - 1
                                           = actual_close/last_close - 1
                                           == actual_ret          (identically)

`last_ret` is then fed to point_bias.correct_point_return(), whose anti-fade
branches emit a return with the same sign as `last_ret` whenever |last_ret| >= 4%.
Feeding it the realized return makes those branches correct by construction.
See edge/docs/AUDIT.md §2 for the full writeup.
"""
from __future__ import annotations

import json
import os
import sys
from math import comb

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KRONOS = os.path.join(ROOT, "Kronos")
sys.path.insert(0, KRONOS)

WF = os.path.join(KRONOS, "forecasts", "walkforward_metrics_exp1_kronos.json")

# Published claims from Kronos/forecasts/TREND_V5_REPORT.md
CLAIM_ALL_DAYS = 0.7135
CLAIM_ACTIONABLE_N = 283
CLAIM_ACTIONABLE_ACC = 0.8233


def binom_p(k: int, n: int) -> float:
    """One-sided binomial p-value vs a fair coin."""
    if n == 0:
        return float("nan")
    return sum(comb(n, i) for i in range(k, n + 1)) / 2 ** n


def hit(pred: float, actual: float) -> int:
    return int(np.sign(pred) == np.sign(actual))


def main() -> int:
    if not os.path.exists(WF):
        print(f"missing artifact: {WF}", file=sys.stderr)
        return 2

    from selective_model import build_selective_decision  # noqa: E402

    wf = json.load(open(WF))
    rows = [r for v in wf["tickers"].values() for r in v["days"]]
    n = len(rows)

    # ---------- 1. clean: selective_ret as computed inside eval_walkforward ----
    clean_hits = [hit(r["selective_ret"], r["actual_ret"]) for r in rows]
    clean_act = [
        hit(r["selective_ret"], r["actual_ret"]) for r in rows if r.get("actionable")
    ]
    clean_all = float(np.mean(clean_hits))
    clean_a = float(np.mean(clean_act)) if clean_act else float("nan")
    kronos_raw = float(np.mean([r["dir_hit"] for r in rows]))
    persist = float(np.mean([r["persist_hit"] for r in rows]))

    # ---------- 2. leaked: last_ret := actual_ret (what the bakeoff does) -----
    leak_hits, leak_act = [], []
    for r in rows:
        a = r["actual_ret"]
        sel = build_selective_decision(
            last_close=r["last_close"],
            kronos_ret=r["pred_ret_p50"],
            last_ret=a,          # <-- the leak
            ret_3d=a,            # <-- also contaminated in the bakeoff
            path_closes=np.linspace(r["pred_p10"], r["pred_p90"], 24),
            vol_c=r.get("vol_c"),
            conf_score=r.get("conf_score"),
            coverage_ok=bool(r.get("high_confidence")),
            closes=None,
        )
        h = hit(sel.selective_ret, a)
        leak_hits.append(h)
        if sel.actionable:
            leak_act.append(h)
    leak_all = float(np.mean(leak_hits))
    leak_a = float(np.mean(leak_act)) if leak_act else float("nan")

    # ---------- 3. FIXED: last_ret/ret_3d reconstructed strictly-prior --------
    # Mirrors the 2026-07-29 fix to bakeoff_trend_v5.hist_closes_asof (strict
    # `<` instead of `<=`). Needs per-ticker day order, so it iterates
    # wf["tickers"] instead of the flattened `rows`. Chains consecutive
    # `last_close` fields instead of re-fetching OHLCV: last_close[i] is the
    # close of the bar immediately before day i's target, and — for the
    # contiguous walk-forward day sequence eval_walkforward.py produces —
    # equals actual_close[i-1]. So last_close[i]/last_close[i-k]-1 is exactly
    # what the fixed `hist_closes_asof(ohlcv, asof=date[i])` would give from
    # real OHLCV, with no network call required. See verify_fix_by_hand-style
    # spot check in the audit report for a live-OHLCV cross-check.
    fixed_hits, fixed_act = [], []
    for days in (v["days"] for v in wf["tickers"].values()):
        lcs = [float(d["last_close"]) for d in days]
        for i, r in enumerate(days):
            a = r["actual_ret"]
            last_ret = float(lcs[i] / lcs[i - 1] - 1.0) if i >= 1 else 0.0
            ret_3d = float(lcs[i] / lcs[i - 3] - 1.0) if i >= 3 else last_ret
            sel = build_selective_decision(
                last_close=r["last_close"],
                kronos_ret=r["pred_ret_p50"],
                last_ret=last_ret,   # <-- strictly-prior, no leak
                ret_3d=ret_3d,       # <-- strictly-prior, no leak
                path_closes=np.linspace(r["pred_p10"], r["pred_p90"], 24),
                vol_c=r.get("vol_c"),
                conf_score=r.get("conf_score"),
                coverage_ok=bool(r.get("high_confidence")),
                closes=None,
            )
            h = hit(sel.selective_ret, a)
            fixed_hits.append(h)
            if sel.actionable:
                fixed_act.append(h)
    fixed_all = float(np.mean(fixed_hits))
    fixed_a = float(np.mean(fixed_act)) if fixed_act else float("nan")
    fixed_n = len(fixed_hits)

    # ---------- report -------------------------------------------------------
    print("=" * 74)
    print(f"Kronos selective model — lookahead audit   (n={n} walk-forward days)")
    print("=" * 74)
    print(f"  Kronos raw median      {kronos_raw:6.4f}")
    print(f"  Persistence baseline   {persist:6.4f}")
    print()
    print(f"  SELECTIVE, leak-free   {clean_all:6.4f}   "
          f"p(vs coin) = {binom_p(int(round(clean_all * n)), n):.3f}")
    print(f"    actionable subset    {clean_a:6.4f}   n={len(clean_act)}   "
          f"p = {binom_p(int(round(clean_a * len(clean_act))), len(clean_act)):.3f}")
    print()
    print(f"  SELECTIVE, with leak   {leak_all:6.4f}   (mechanism demo — hardcodes")
    print(f"    actionable subset    {leak_a:6.4f}   n={len(leak_act)}    last_ret=actual_ret by hand)")
    print()
    print(f"  SELECTIVE, FIXED bakeoff {fixed_all:6.4f}   "
          f"p(vs coin) = {binom_p(int(round(fixed_all * fixed_n)), fixed_n):.3f}   "
          f"(post 2026-07-29 fix)")
    print(f"    actionable subset      {fixed_a:6.4f}   n={len(fixed_act)}")
    print()
    print(f"  PUBLISHED claim        {CLAIM_ALL_DAYS:6.4f}   "
          f"actionable {CLAIM_ACTIONABLE_N}/{CLAIM_ACTIONABLE_ACC}")
    print("=" * 74)

    # ---------- 5. multi-year walk-forward backtest audit ------------------
    wf_res_path = os.path.join(ROOT, "edge", "runs", "walkforward", "results.json")
    if os.path.exists(wf_res_path):
        wf_data = json.load(open(wf_res_path))
        print("  MULTI-YEAR WALKFORWARD BACKTEST AUDIT:")
        print(f"    Eval Period:  {wf_data.get('eval_period', 'N/A')}")
        print(f"    Total Folds:  {wf_data.get('total_folds', 0)}")
        print(f"    Mean OOS IC:  {wf_data.get('mean_rank_ic', 0.0):+.4f}")
        print(f"    OOS Sharpe:   {wf_data.get('out_of_sample_sharpe', 0.0):.2f}")
        print(f"    Verdict:      {wf_data.get('verdict', 'N/A')}")
        print()

    leak_reproduces = abs(leak_all - CLAIM_ALL_DAYS) < 0.05
    clean_is_coinflip = binom_p(int(round(clean_all * n)), n) > 0.05
    fixed_is_coinflip = binom_p(int(round(fixed_all * fixed_n)), fixed_n) > 0.05
    fixed_no_longer_claim = abs(fixed_all - CLAIM_ALL_DAYS) > 0.10

    print(f"  leaked (mechanism demo) reproduces published number : {leak_reproduces}")
    print(f"  leak-free (eval_walkforward selective_ret) is a coin flip : {clean_is_coinflip}")
    print(f"  FIXED bakeoff reconstruction is a coin flip : {fixed_is_coinflip}")
    print(f"  FIXED bakeoff no longer reproduces published number : {fixed_no_longer_claim}")
    print()
    if leak_reproduces and clean_is_coinflip and fixed_is_coinflip and fixed_no_longer_claim:
        print("VERDICT: the published selective/actionable edge WAS a lookahead artifact")
        print("         (the leak section above proves the mechanism in isolation).")
        print("         bakeoff_trend_v5.py is fixed as of 2026-07-29: reconstructing")
        print("         last_ret/ret_3d strictly-prior now lands back at a coin flip,")
        print("         matching the leak-free eval_walkforward baseline. No directional")
        print("         edge survives once the leak is removed.")
        return 0
    print("VERDICT: inconclusive — inspect manually before trusting either number.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
