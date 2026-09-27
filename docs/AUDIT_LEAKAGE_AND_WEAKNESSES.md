# Audit of Temporal Leakage and Live Execution Weaknesses

**Date**: 2026-08-03  
**Scope**: `edge/` research engines, backtesting harnesses, and live/shadow pipelines.

---

## 1. Executive Summary

Historical backtest results across several model candidates (notably Kronos selective models, PEAD catalyst, and PEAD factor hybrid) exhibited inflated performance metrics primarily due to **temporal lookahead leakage** and **execution timing mismatches**. When execution lag, filing availability timestamps, point-in-time universe boundaries, and realistic transaction costs are introduced, raw alpha signals drop significantly or turn negative.

This audit documents the specific mechanisms of failure discovered in the legacy backtests and establishes the requirements for production readiness.

---

## 2. Leakage Mechanisms Identified

### 2.1 Same-Bar Fill & Execution Lag Violation
- **Mechanism**: In legacy evaluation scripts (e.g. `bakeoff_trend_v5.py`, `build_pead_catalyst_model.py`, and `build_pead_factor_hybrid.py`), target day $t$ predictions or weight assignments were multiplied directly by day $t$'s own price returns ($R_t = P_t / P_{t-1} - 1$).
- **Impact**:
  - `Kronos selective` reported 71.35% (82.33% actionable) directional win rate; under leak-free $t-1$ cutoff, true performance was **49.3%** (indistinguishable from a coin flip).
  - `PEAD catalyst` reported +502.98% return in naive backtests; when forced to wait for bar completion ($t+1$ execution), performance dropped to **-10.38%** net.
- **Remediation**: Signals generated on completed bar $t$ must execute on subsequent events ($t+1$ open or bid/ask quote cross). Fills on bar $t$'s close using bar $t$'s signal are strictly forbidden.

### 2.2 Fundamental Data Filing Date Leakage
- **Mechanism**: Fundamental indicators (e.g. EPS surprises, balance sheet metrics) were frequently assigned to the fiscal quarter-end date (e.g. 12/31) rather than the SEC filing date (SEC Form 10-K / 10-Q availability date, often 45–60 days later).
- **Impact**: Feature vectors for January trading days used financial results that were not publicly filed until late February.
- **Remediation**: Every fundamental record must store `available_ts` corresponding to public SEC EDGAR ingestion time or vendor release timestamp.

### 2.3 Unfinished Bar & Full-Day Volume Contamination
- **Mechanism**: Intraday or daily indicators (e.g. RVOL, daily volume percentiles) calculated feature statistics using the final total day's volume $V_{\text{total}}$ while evaluating intraday decisions at time $t < t_{\text{close}}$.
- **Impact**: Predicted volume ratio $V_t / V_{\text{total}}$ used future volume that had not yet occurred.
- **Remediation**: Intraday features must only normalize volume against historical time-of-day medians computed strictly prior to $t$.

### 2.4 Hindsight Universe Survivorship Bias
- **Mechanism**: Backtests executed across 2016–2026 used the active ticker list from 2026 (e.g. `xs47` universe), ignoring companies that delisted, went bankrupt, or were acquired during 2016–2025.
- **Impact**: As demonstrated in `GATE_XS_RESULT.md`, removing hindsight-selected 2020–2023 listing cohorts dropped portfolio excess returns significantly while increasing Rank IC. Backtest returns were heavily driven by holding names that succeeded in hindsight.
- **Remediation**: Universe membership must be determined point-in-time using an `InstrumentMaster` database with explicit `listing_date` and `delisting_date` bounds.

### 2.5 Cost-Blind Rebalancing & Alpha Erosion
- **Mechanism**: Strategies rebalanced portfolios whenever relative asset rankings shifted minutely, incurring 10–20 bps of transaction costs per trade on zero-edge noise.
- **Impact**: On `xs40`, introducing a 10 bps round-trip transaction cost cut the Information Ratio in half (0.606 $\rightarrow$ 0.299). On FINRA short volume signals, 10 bps costs turned +0.029 Mean IC into a -13.39% net drawdown.
- **Remediation**: Implement net edge filtering ($|\hat{\alpha}| > \widehat{C} + k \sigma_{\alpha}$) and dynamic cost-aware no-trade buffers.

---

## 3. Operational & Live Execution Weaknesses

1. **State Ambiguity Under Broker Disconnect**: Legacy scripts did not reconcile local position ledgers with broker REST API state prior to order generation.
2. **Missing Market Data Sequence Validation**: Live feeds lacked explicit sequence gap detection; missing ticks or stale quotes could trigger orders on stale prices.
3. **Coupled Order Submission Logic**: Strategy decision code directly called order submission APIs, preventing deterministic replay and shadow testing.

---

## 4. Remediation Checklist

| Issue | Remediation Module | Status |
|---|---|---|
| Temporal Leakage & Availability | `edge/research/temporal.py` | Implemented in Step 2 |
| Point-In-Time Universe | `edge/research/universe.py` | Implemented in Step 4 |
| Transaction Cost & Net Edge | `edge/research/costs.py`, `portfolio.py` | Implemented in Step 5-6 |
| Microstructure Features & Ablations | `edge/research/microstructure.py`, `ablation.py` | Implemented in Step 8 |
| Scenario GEX & IV Features | `edge/research/gex_model.py`, `options_features.py` | Implemented in Step 9 |
| Deterministic Decision Interface | `edge/research/decision.py` | Implemented in Step 10 |
| Live Safety & Reconciler | `edge/research/safety.py` | Implemented in Step 10 |
| Shadow-Live Runner | `edge/tools/run_shadow_live.py` | Implemented in Step 10 |
