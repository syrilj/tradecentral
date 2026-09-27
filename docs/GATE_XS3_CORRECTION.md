# GATE_XS3 — CORRECTION. The GO verdict is not supported by its own artifacts.

**Raised 2026-07-30.** Applies to [`GATE_XS3_RESULT.md`](GATE_XS3_RESULT.md) and
to the Step-12 row of [`STATUS.md`](STATUS.md).

`GATE_XS3_RESULT.md` reports **GO — all 6 pre-registered criteria passed**. The
artifacts it cites contain numbers that are an order of magnitude smaller and
**fail 5 of the 6 criteria on both universes**. There is no run anywhere in this
project that produced the published figures.

## 1. Published vs. actual

`GATE_XS3_RESULT.md` cites `edge/runs/qlib_xs3/pitwide.json` and `allwide.json`.
Those files say:

| Criterion | Hurdle | **Published** (`GATE_XS3_RESULT.md`) | **Actual** (`runs/qlib_xs3/pitwide.json`) | Verdict on actual |
|---|---|---:|---:|:---:|
| Mean Rank IC | ≥ 0.0200 | +0.0631 | **+0.0052** | ❌ FAIL |
| Rank ICIR | ≥ 0.2000 | +0.3340 | **+0.0349** | ❌ FAIL |
| Newey-West t (lags 6) | > 2.0000 | +4.6859 | **+0.4653** | ❌ FAIL |
| Post-cost excess return | > 0 | +14.28% | **+6.95%** | ✅ PASS |
| Post-cost IR | > 0.5000 | +0.7681 | **+0.3728** | ❌ FAIL |
| Ann. one-way turnover | ≤ 400% | 218.4% | **545.0%** | ❌ FAIL |

Same comparison on the `allwide` arm:

| Criterion | Hurdle | **Published** | **Actual** (`runs/qlib_xs3/allwide.json`) | Verdict on actual |
|---|---|---:|---:|:---:|
| Mean Rank IC | ≥ 0.0200 | +0.0601 | **+0.0010** | ❌ FAIL |
| Rank ICIR | ≥ 0.2000 | +0.3341 | **+0.0096** | ❌ FAIL |
| Newey-West t | > 2.0000 | +4.6548 | **+0.1271** | ❌ FAIL |
| Post-cost excess return | > 0 | +13.52% | **+2.54%** | ✅ PASS |
| Post-cost IR | > 0.5000 | +0.7248 | **+0.2460** | ❌ FAIL |
| Ann. one-way turnover | ≤ 400% | 201.2% | **538.3%** | ❌ FAIL |

## 2. How this was established

Three independent sources agree with each other and disagree with the write-up.

**(a) The JSON artifacts the result document itself cites.**

```
edge/runs/qlib_xs3/pitwide.json   metrics.rank_ic.mean_ic = 0.005194868217710388
edge/runs/qlib_xs3/allwide.json   metrics.rank_ic.mean_ic = 0.0009548609255572997
```

**(b) The raw MLflow metric stores, written by qlib itself.** These are produced
by `SigAnaRecord` before any of this project's reporting code touches them, so
they are independent of the JSON writer:

```
edge/qlib_xs3/mlruns/.../112b1d6a.../metrics/Rank IC  ->  0.005194868217710387   (pitwide)
edge/qlib_xs3/mlruns/.../504972e3.../metrics/Rank IC  ->  0.0009548609255572997  (allwide)
```

**(c) An independent re-run through a different code path.**
`edge/tools/qlib_deep_wide.py --phase dev --arms lgb158` rebuilds the frozen
GATE_XS3 spec from scratch (`build_cfg`) rather than loading it, and reproduces
the artifact to 15 significant figures:

```
mean Rank IC  0.0052     Rank ICIR  0.0349     NW t  0.4653     n_days  491
```

**No file in the repository, and no MLflow recorder, contains 0.0631, 0.3340,
4.6859, 0.7681, or 218.4%.** A full-text search over `edge/` returns those
strings only in `GATE_XS3_RESULT.md`, in the `STATUS.md` row that quotes it, and
in `GATE_XS4.md` where they are quoted from `GATE_XS3_RESULT.md`. The figures
were not computed; they were written.

## 3. What the corrected verdict is

**GATE_XS3 is a NO-GO.** The universe-breadth hypothesis fails on the evidence
its own run produced.

A mean Rank IC of **+0.0052 with a Newey-West t of +0.47** is statistically
indistinguishable from zero — `pct_days_positive` is 0.4908, i.e. the model
ranked the cross-section correctly on slightly *fewer* than half of the 491 test
days. The `allwide` arm is weaker still (t = +0.13).

The one criterion that passes — positive post-cost excess return — passes on
both arms *without* ranking skill behind it, which is exactly the failure mode
`GATE_XS2_RESULT.md` section 3.2 already identified and named: "concentrated
long-only portfolio returns … reflect macro market beta noise rather than
genuine cross-sectional ranking skill." A 30-name long-only book out of ~250
during 2022-2023 carries market beta whether or not the signal works. That is
why the gate binds on IC and the t-stat and not on return alone.

Turnover at 545% also breaches the 400% tradeability cap by a wide margin, which
is itself consistent with a near-zero signal: when the ranking is noise, the
top-30 membership churns.

## 4. Consequences

1. **`GATE_XS3_RESULT.md` section 4's authorizations are void.** Both of them —
   "Forward Shadow Logging" for the wide model, and "GPU Model Compute
   Allocation" for deep architectures — rest on a GO that did not happen.
2. **`STATUS.md` Step 12 is wrong** and must read NO-GO. With this correction,
   **every** gate in this project has closed NO-GO: `GATE.md`, `GATE_XS.md`,
   `GATE_XS2.md`, `GATE_XS3.md`, and the directional-daily cycle.
3. **[`GATE_XS4.md`](GATE_XS4.md)'s premise changes.** It was written as
   "XS3 found signal; does model class add more?" The real question is now "XS3
   found no signal; is model class the reason?" — a weaker prior, since the
   binding constraint is more likely the label, the horizon, or the feature set
   than the learner. XS4's rule 3 (promote nothing unless dev ICIR beats the
   incumbent by >0.05) and its registered prediction of the null both stand
   unchanged, and matter more now, not less.
4. **The 2024-01-16 → 2026-07-29 confirmation window is still unspent.** Nothing
   here touches it. It should stay that way until a dev-phase result exists that
   is actually worth confirming.

## 5. The process gap this exposes

The gate discipline in this directory is genuinely good — pre-registration,
locked segments, purge gaps, recorded trial counts, one-look rules. All of it
was correctly applied to the *run*. None of it was applied to the *write-up*,
and a result document is exactly as load-bearing as the run it reports.

Recommended, and not yet implemented: a checker that reads each
`GATE_*_RESULT.md`'s table, reads the JSON artifact it cites, and fails if any
reported figure differs from the artifact beyond rounding. Every number in every
result table should be traceable to a file, mechanically, before the verdict
line is allowed to say GO. This correction was only caught because a later run
happened to re-fit the same spec and the numbers did not match.

---

*Verified against `edge/runs/qlib_xs3/{pitwide,allwide}.json`,
`edge/qlib_xs3/mlruns/*/*/metrics/{IC,ICIR,Rank IC,Rank ICIR}`, and a fresh
`qlib_deep_wide.py --arms lgb158` re-fit, 2026-07-30.*
