# GATE_XS5 Result — FAIL_DEVELOPMENT

Formal outcome for [`GATE_XS5.md`](GATE_XS5.md), evaluated **2026-08-16**.

---

## 1. Summary of Execution

- **Panel**: pit30 universe, authoritative PIT membership filtering, 46 symbols,
  2,260 trading dates (2017-08-01 → 2026-07-29). The runner asserted it never
  read a bar after 2026-07-29 (GATE_XS5 rule 3).
- **Specs run**: 4 recorded trials (mom12_1, mom21, rev5, each as
  optimizer+vol-target and frozen decile baseline). No fitting, no search.
- **Accounting**: `edge.research.portfolio.simulate_long_short`,
  `execution_lag=1`, 10bp per side charged per bar of realized turnover.
- **OOF construction**: expanding purged/embargoed walk-forward folds on the
  trading-date axis (label_horizon=1, embargo=5, initial_train=504,
  validation=126, step=126, partial final fold ≥60 dates) → 1,750 OOF days.

## 2. Development Results

| Trial | OOF days | Net expectancy | CI95 lower | Deflated Sharpe lower |
|---|---:|---:|---:|---:|
| **mom12_1 opt+vol (primary)** | 1,750 | +0.002%/day | **−0.031%/day** | **−0.814** |
| mom12_1 decile (frozen baseline) | 1,750 | −0.085%/day | −0.158%/day | −1.741 |
| mom21 opt+vol | 1,750 | −0.014%/day | −0.047%/day | −1.149 |
| mom21 decile | 1,750 | −0.026%/day | −0.084%/day | −1.200 |
| rev5 opt+vol | 1,750 | −0.034%/day | −0.067%/day | −1.600 |
| rev5 decile | 1,750 | −0.122%/day | −0.179%/day | −2.433 |

## 3. Gate Checks

| Criterion | Threshold | Observed | Verdict |
| :--- | :--- | :---: | :---: |
| OOF net expectancy CI95 lower | > 0 | −0.031%/day | ❌ FAIL |
| Deflated Sharpe lower (trial_count=4) | > 0 | −0.814 | ❌ FAIL |
| Paired difference vs decile baseline, CI95 lower | > 0 | **+0.054%/day** | ✅ PASS |
| Annualized one-way turnover | ≤ 400% | 96.4% | ✅ PASS |

**Verdict: FAIL_DEVELOPMENT.** No partial credit, as preregistered.

## 4. What this result says

The hypothesis was that cost-aware execution retains more of the pre-cost edge
than the book that lost it in `GATE_XS2.md`. That part is **confirmed**: the
cost-aware optimizer plus volatility targeting beats the frozen decile baseline
with a positive paired confidence bound (+0.054%/day lower bound), at 96%
annualized turnover against the baseline's higher churn. The execution lever
works exactly as designed.

But the edge it retains is not positive with confidence. The primary spec's own
expectancy CI lower bound is negative, and the deflated Sharpe is negative. The
optimizer cannot manufacture alpha that the signal does not contain — and on
this price-only data, on this universe, over this window, the signal contains
none. This is the seventh null on the same feature family, and it is consistent
with `GATE_XS4_DEV.md`'s conclusion: the remaining axis is the feature family
itself, which is a data question, not an engineering one.

## 5. Operational consequence

- `verdict = FAIL_DEVELOPMENT`
- `holdout.status = SEALED_UNEVALUATED` (2026-07-30 → 2027-02-12, ≥120 sessions)
- `shadow_collection_authorized = false`
- `live_capital_authorized = false`
- `broker_connectivity_authorized = false`

The terminal holdout remains sealed and is not opened by this result. Per
GATE_XS5 rule 1, the hypothesis is closed on this data: no re-tuning against
development.

## 6. What would be required for a future attempt

The evidence across seven gates now points at the input, not the method. A
future attempt requires **new data** — fundamentals, estimate revisions, flow,
or cross-asset features with point-in-time availability — not another model or
another execution tweak on the same price series. Any such attempt must begin
with a new economically motivated hypothesis and a new pre-registered gate.

---

*Artifacts: `edge/runs/xs5/results.json`. Runner: `edge/tools/xs5_pit_optimizer.py`.
Simulated backtests only. Not financial advice.*
