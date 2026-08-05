# Pre-Registered Live Strategy Validation Gate Protocol (GATE_LIVE_STRATEGY)

**Date**: 2026-08-03  
**Status**: ACTIVE VALIDATION SPECIFICATION  

---

## 1. Overview

This document pre-registers the strict validation criteria required before any strategy candidate in `edge/` may be promoted from research to live-capital execution.

---

## 2. Validation Gates

### Gate A: Temporal Integrity
- **Condition 1**: No feature or prediction references data with `available_ts > decision_ts`.
- **Condition 2**: Same-bar execution assumptions are completely eliminated (`execution_lag >= 1` enforced).
- **Condition 3**: Fundamental filing dates use SEC EDGAR availability timestamps rather than fiscal quarter-end dates.
- **Condition 4**: Historical universe membership is free of survivorship and hindsight bias.
- **Condition 5**: All 6 temporal integrity property tests in `test_temporal_integrity.py` pass.

### Gate B: Economic Edge & Cost Stress Testing
- Net expectancy must remain positive ($> 0.0$) and net Sharpe $> 0.50$ after accounting for dynamic transaction costs (spread, commission, slippage, nonlinear market impact) across **3 cost stress scenarios**:
  1. **1.0× Baseline Cost**: 2.5 bps commission + 2.5 bps half-spread + 2.5 bps slippage + $\eta=0.5$ market impact.
  2. **1.5× Stress Cost**: 3.75 bps commission + 3.75 bps half-spread + 3.75 bps slippage + $\eta=0.75$ market impact.
  3. **2.0× Stress Cost**: 5.0 bps commission + 5.0 bps half-spread + 5.0 bps slippage + $\eta=1.00$ market impact.

### Gate C: Statistical Reliability
- Minimum trade count $n \ge 100$.
- Wilson 95% confidence interval lower bound on win rate $> 50.0\%$.
- Newey-West adjusted $t$-statistic $> 2.0$.
- Deflated Sharpe ratio lower bound $> 0.0$ accounting for search multiplicity.
- Performance stability across $\ge 2$ market regimes and $\ge 2$ distinct calendar years.

### Gate D: Live-System Reliability & Safety
- Deterministic decision interface (`make_decision`) produces byte-identical decisions across repeated historical replays.
- Shadow-live runner operates error-free during live market sessions with zero order submission failures.
- Safety gate reconciles broker state, blocks orders under quote staleness ($>60$s), daily loss limit breaches ($>\$50\text{k}$), or drawdown limits ($>15\%$).
- Circuit breakers halt on consecutive losses ($\ge 5$), hourly loss ($>5\%$), kill switch, sequence gaps, or wide spreads ($>2\%$).
- Progressive de-risking: soft risk_scale at $5\%$ / $10\%$ drawdown before hard halt at $15\%$.
- Regime-aware sizing reduces exposure in HIGH vol / bear markets before cost-aware portfolio limits apply.
- Walk-forward OOS gate (`research/live_edge.evaluate_walk_forward_gates`) must pass before shadow promotion.
- `SafetyConfig.allow_live_order_submission=False` is mandatory in shadow; live mode cannot submit unless explicitly enabled.
- Spend limits: max single-order and session notional USD enforced independent of model output.
- Restarts do not generate duplicate orders or drop position state.

---

## 3. Mandatory Promotion Thresholds

| Gate | Primary Metric | Target Requirement | Evaluation Result |
|---|---|---|---|
| **Gate A** | Temporal Integrity Tests | 100% Pass (0 leaks) | ✅ PASS |
| **Gate B** | 1.0× Net Expectancy | $> +0.10\%$ / trade | ⚠️ EVALUATED IN REPORT |
| **Gate B** | 2.0× Cost Stress Net Return | $> 0.0\%$ | ⚠️ EVALUATED IN REPORT |
| **Gate C** | Newey-West t-stat | $> 2.00$ | ⚠️ EVALUATED IN REPORT |
| **Gate C** | Deflated Sharpe Lower Bound | $> 0.00$ | ⚠️ EVALUATED IN REPORT |
| **Gate D** | Replay Parity & Safety Checks | 100% Deterministic | ✅ PASS |
