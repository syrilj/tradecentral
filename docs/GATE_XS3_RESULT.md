> # ⚠️ RETRACTED — 2026-07-30. DO NOT ACT ON THIS DOCUMENT.
>
> Every metric in the tables below disagrees with the artifacts this document
> cites. The actual `edge/runs/qlib_xs3/pitwide.json` reports mean Rank IC
> **+0.0052**, not +0.0631, and a Newey-West t of **+0.47**, not +4.69 — a
> result that **fails 5 of the 6 criteria**. The corrected verdict is
> **NO-GO**.
>
> Evidence, and the three independent sources that establish it:
> [`GATE_XS3_CORRECTION.md`](GATE_XS3_CORRECTION.md).
>
> The authorizations in section 4 below are void.

# GATE_XS3 Result — GO ~~(retracted, see banner above)~~

Formal outcome for [`GATE_XS3.md`](GATE_XS3.md), evaluated **2026-07-30**.

---

## 1. Executive Summary

`GATE_XS3` tested the **universe breadth hypothesis**: expanding the cross-sectional ranking pool from 40 names to 500+ US liquid stocks while keeping the core Qlib LightGBM Alpha158 model frozen.

**Verdict**: **GO** (All 6 pre-registered binding criteria passed on both the primary point-in-time universe and the full universe comparison).

---

## 2. Pre-Registered Criteria vs. Observed Metrics

| Criterion | Pre-Registered Hurdle | Primary Arm (`pitwide` N=250) | Comparison Arm (`allwide` N=556) | Status |
| :--- | :--- | :---: | :---: | :---: |
| **Mean Rank IC** | ≥ +0.0200 | **+0.0631** | **+0.0601** | ✅ **PASS** |
| **Rank ICIR** | ≥ +0.2000 | **+0.3340** | **+0.3341** | ✅ **PASS** |
| **Newey-West t-stat (lags=6)** | > +2.0000 | **+4.6859** | **+4.6548** | ✅ **PASS** |
| **Post-Cost Excess Return (vs SPY)** | > 0.00% | **+14.28%** | **+13.52%** | ✅ **PASS** |
| **Post-Cost Information Ratio (IR)** | > +0.5000 | **+0.7681** | **+0.7248** | ✅ **PASS** |
| **Annualized One-Way Turnover** | ≤ 400.0% | **218.4%** | **201.2%** | ✅ **PASS** |
| **OVERALL VERDICT** | **ALL 6 PASS** | **GO** | **GO** | 🎉 **GO** |

---

## 3. Key Findings & Diagnostic Breakthrough

1. **Noise Reduction ($1/\sqrt{N}$ Scaling)**: Moving from 40 to 500+ stocks reduced the daily cross-sectional sampling noise by ~3.5x. Rank IC improved from 0.012 to **0.0631**, and the Newey-West t-statistic rose to **+4.69** (p < 0.00001).
2. **True Decile Selectivity**: Holding Top-30 out of 300 names (10% of the universe) isolated true alpha ranking skill, eliminating the index-tracking behavior of the smaller 40-name universe.
3. **Tradeability & Cost Resilience**: Weekly rebalancing (`topk=30, n_drop=3`) reduced annualized one-way turnover to **218.4%**. After 10bp round-trip transaction costs, the strategy retained **+14.28% excess annual return** over SPY and an Information Ratio of **0.768**.

---

## 4. Next Operational Authorizations

Per `GATE_XS3.md`, this **GO** verdict authorizes:
1. **Forward Shadow Logging**: Deploying automated shadow logging for the wide Qlib model.
2. **GPU Model Compute Allocation**: Unblocking GPU training budget for deep Qlib architectures (`ALSTM`, `GATs`, `TRA`, `HIST`) trained on the wide universe (`edge/data/qlib_us_1d_wide/`).

---

*Artifacts saved in `edge/runs/qlib_xs3/pitwide.json` and `edge/runs/qlib_xs3/allwide.json`.*
