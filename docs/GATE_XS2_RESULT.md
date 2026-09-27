# GATE_XS2 Result — NO-GO

Formal outcome for [`GATE_XS2.md`](GATE_XS2.md), evaluated **2026-07-30**.

---

## 1. Summary of Execution

- **Phase 1 Selection**: Evaluated **36 configurations** (2 universes × 3 rebalance intervals × 3 topk values × 2 n_drop values) across the selection-test window (`2022-01-18` → `2023-12-29`).
  - **Selected Config**: `xs40 / 21d / topk10 / n_drop2` (Selection IR: +2.518, Annualized Turnover: 265%).
- **Phase 1 Permutation Null**: Executed **200 cross-sectional permutation draws** (`edge/runs/qlib_xs2/null_score_xs40.json`).
  - **Null Distribution of Max IR**: p50 = +1.921, p95 = +2.425, Max = +2.673.
  - **Observed Selection IR**: +2.518 (Empirical p = 0.0150 < 0.05).
- **Phase 2 Confirmation**: Evaluated once on the locked confirmation segment (`2024-01-16` → `2026-07-29`, 630 trading days).

---

## 2. Phase 2 Confirmation Results

| Criterion | Target Threshold | Primary Arm (5y Train) | Control Arm (Expanding Train) | Verdict |
| :--- | :--- | :---: | :---: | :---: |
| **Mean Rank IC** | ≥ 0.020 | **0.0120** | 0.0214 | ❌ **FAIL** |
| **Rank ICIR** | ≥ 0.200 | **0.0718** | 0.1022 | ❌ **FAIL** |
| **Newey-West t-stat (lags=6)** | > 2.000 | **1.069** | 1.546 | ❌ **FAIL** |
| **Post-Cost Excess Return** | > 0.0% | **+2.04%** | +11.22% | ✅ PASS |
| **Post-Cost Info Ratio (IR)** | > 0.500 & **> 0.299** | **0.193** | 0.708 | ❌ **FAIL** |
| **Annualized One-Way Turnover**| ≤ 400% | **264.8%** | 249.2% | ✅ PASS |

---

## 3. Analysis & Key Takeaways

1. **Primary Arm Fails Binding Criteria**: The 5-year regime-trained primary arm achieved a post-cost Information Ratio of only **0.193** (failing the > 0.299 hurdle) and a Rank IC of **0.0120** (t-stat = 1.069, failing the > 2.0 significance hurdle).
2. **Control Arm Pattern Match**: While the expanding control arm registered a post-cost IR of 0.708, its Newey-West t-statistic was only 1.546 (statistically indistinguishable from noise). This confirms the pattern documented in `GATE_XS2.md`: concentrated long-only portfolio returns on a 40-name universe reflect macro market beta noise rather than genuine cross-sectional ranking skill.
3. **Decisive Conclusion**: Per Rule 1 of `GATE_XS2.md`, no re-tuning or third look at the confirmation segment is permitted. The cross-sectional hypothesis on this 40-name dataset is closed.

---

## 4. Next Operational Steps

As outlined in the strategic roadmap:
1. **Widen the Universe**: Ingest 500–1,000 names (S&P 500 / Russell 1000) using `qlib_ingest.py` to shrink the daily Rank IC variance by several fold.
2. **Market-Neutral Long-Short Evaluation**: Transition evaluation metrics from long-only (market beta dependent) to dollar-neutral long-short spread.
3. **Compute Allocation**: Reserve Vertex AI compute credits for deep model benchmarks (`ALSTM`, `GATs`, `TRA`, `HIST`) evaluated against `LightGBM` on the expanded universe.

---

*GATE_XS2 is officially closed with a **NO-GO** verdict. No further evaluations on this confirmation segment.*
