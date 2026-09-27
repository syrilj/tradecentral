# GATE_XS result — single evaluation, 2026-07-30

Pre-registered criteria: [`GATE_XS.md`](GATE_XS.md), written **before** any model
was fit. Spec: `edge/qlib_xs/workflow_alpha158_lgb.yaml` — LightGBM on Alpha158
with `CSRankNorm`, long-only `TopkDropoutStrategy` (topk 10, n_drop 2), 10bp
round-trip, benchmark SPY. Artifacts: `edge/runs/qlib_xs/{xs47,xs40}.json`.

## Trial count (deflation honesty)

| Item | Count |
|---|---:|
| Configurations evaluated against the test segment | **1** (frozen spec, run once per universe) |
| Hyperparameter grid searched against the test segment | 0 (upstream Alpha158 LightGBM benchmark values, unchanged) |
| Universes reported | 2 (**both required** by `GATE_XS.md`, not selected after the fact) |

## Holdout metrics vs gate

Test segment 2024-01-16 → 2026-07-29, 630 days.

| Criterion | Threshold | **xs47** (all singles) | **xs40** (listed by 2016-08) | Pass? |
|---|---|---:|---:|---|
| mean **Rank IC** | ≥ 0.02 | 0.0126 | **0.0334** | xs40 **YES**, xs47 **NO** |
| **Rank ICIR** | ≥ 0.20 | 0.0850 | 0.1798 | **NO** (xs40 marginal\*) |
| IC **t-stat, Newey-West** | > 2.0 | 1.35 | **2.68** | xs40 **YES**, xs47 **NO** |
| Excess ann. return vs SPY, after 10bp | > 0 | **+9.13%** | **+4.44%** | **YES** both |
| Information ratio vs SPY | > 0.5 | **0.627** | 0.299 | xs47 **YES**, xs40 **NO** |

\*0.1798 against a 0.20 threshold. Treated as a fail, per rule 3 — the threshold
was written down first and is not adjusted to admit a near miss.

Supporting numbers (reported, **not** gating):

| | xs47 | xs40 |
|---|---:|---:|
| Pearson IC | 0.0008 | 0.0273 |
| days with IC > 0 | 52.7% | 55.9% |
| naive IC t-stat | 2.13 | 4.51 |
| excess ann. return, **no** cost | +13.55% | +9.00% |
| information ratio, **no** cost | 0.931 | 0.606 |
| max drawdown, after cost | −19.1% | −27.5% |
| long-short ann. return / Sharpe | +15.7% / 0.63 | +54.0% / 2.22 |

# Verdict: **NO-GO**

Neither universe clears all five criteria. `Rank ICIR` fails on both.

## What actually happened — and it is not what was predicted

`GATE_XS.md` anticipated that the survivorship-controlled **xs40** would look
*worse* than xs47, with the gap reported as a survivorship premium. **The
opposite occurred, on one axis and not the other:**

- **xs40 has the stronger signal** — Rank IC 0.0334 vs 0.0126, NW t 2.68 vs 1.35.
- **xs47 has the stronger portfolio** — IR 0.627 vs 0.299, +9.13% vs +4.44%
  excess, and a shallower drawdown (−19.1% vs −27.5%).

The seven names in xs47 but not xs40 (APLD, ARM, COIN, IONQ, PLTR, RKLB, SNOW)
are the 2020-23 listing cohort, and they ran hard through the test window. Adding
them **raises portfolio return while lowering ranking skill**: `TopkDropout` gets
to hold them, but Alpha158 cannot predict them, so they dilute the IC.

The honest reading: **xs47's portfolio advantage is substantially the payoff from
holding hindsight-selected winners, not evidence of ranking skill.** The universe
was chosen in 2026 knowing PLTR and COIN worked. Strip that cohort out and the
ranking signal gets *better* while the money gets worse — which is what a
survivorship premium looks like when you measure both halves instead of one.

## Costs are the second binding constraint

On xs40, cost consumes **half** the edge: excess return 9.00% → 4.44%, IR
0.606 → 0.299. A topk-10 / n_drop-2 daily rebalance on 40 names is high turnover.
The pre-cost IR of 0.606 would have cleared the 0.5 bar; the post-cost 0.299 does
not. **Rule 1 forbids re-running with a lower turnover on this test segment** —
that is a new hypothesis needing a new gate and a fresh window.

## Is this better than the v90 baseline? Yes — and it still fails.

Against the negative control in `edge/runs/v90_wide_ic.json` (Rank IC −0.0008,
NW t −0.09, flat quintiles), the cross-sectional model is a real improvement:
xs40's Rank IC is ~40× the null in magnitude and positive, with NW t = 2.68.
**The cross-sectional hypothesis is measurably less dead than the absolute one.**
It is still not, at the pre-registered bar, a tradeable edge.

Note the gap between Pearson IC (0.0273) and Rank IC (0.0334) on xs40: the signal
is ordinal, not linear. Any future use should rank, never size on raw score.

## What this authorizes / blocks

| Action | Status |
|---|---|
| Live capital on this signal | **No** |
| Step 8 Kronos fine-tune / GPU VM | **Still blocked** (governed by `GATE.md`) |
| Re-tune topk / n_drop / label on this test segment | **Forbidden** by rule 1 |
| Lower-turnover variant on a **new** gate + fresh window | Allowed as a new cycle |
| 1H port of the cross-sectional spec | **Not yet** — daily did not clear |
| Keep `edge/models/v90` baseline + shadow logging | Yes, unchanged |
| Report xs47 numbers without the xs40 comparison | **Forbidden** — misleading alone |

## Paths forward (none require a VM)

1. **Turnover, not model.** The binding constraint on xs40 is cost, not capacity.
   A weekly rebalance or a wider topk is the single most promising next test —
   under a new gate, on a fresh window.
2. **Universe construction is now a first-class problem.** The xs47/xs40 split
   showed selection choices move the result more than the model does. A
   rules-based universe (liquidity screen applied point-in-time) would remove the
   largest remaining source of self-deception.
3. **Do not add model capacity.** Deep models were out of scope for this gate and
   should stay out: the evidence says the constraint is turnover and universe, not
   the learner.

---

*Simulated holdout only. Not financial advice. Gate criteria were not edited after
seeing these numbers; the two revisions in `GATE_XS.md` are both timestamped
before any metric was read.*
