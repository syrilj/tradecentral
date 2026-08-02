# GO/NO-GO Gate: Track 1 Index Options Volatility Timing (Level 2 Live Strategy)

Pre-registered 2026-07-31.

## Objective & Hypothesis

Level 2 options trading permits long call and put purchases only. Buying options on a subtle equity factor signal (+0.21 IR) fails due to option spread drag and theta decay. 

Track 1 tests a low-frequency volatility regime timing strategy on index ETFs (**SPY**, **QQQ**) using the full 15-year volatility complex (`^VIX`, `^VIX3M`, `^VVIX`, `^VIX9D`, `^SKEW`). 

**Hypothesis**: Volatility term structure inversion (`VIX / VIX3M > 1.05`), elevated near-term stress (`VIX9D / VIX > 1.10`), and tail risk pricing (`SKEW > 135`) identify convex long premium opportunities with positive expectancy post-option spread and decay costs.

---

## Data & Backtest Protocol

- **Underlyings**: SPY, QQQ options (penny-wide bid/ask spread constraint: $0.01 per side, $0.02 round-trip).
- **History Window**: 2011-01-03 → 2026-07-29 (15.5 years, 3,900+ daily sessions covering 5 distinct market regimes).
- **Execution**: Rebalance / entry signal evaluated daily at close; position holding period: 20 to 60 DTE.
- **Option Pricing Engine**: Black-Scholes simulation with IV derived from VIX term structure and moneyness skew.

---

## Pre-Registered GO/NO-GO Criteria

To achieve a **GO** verdict, the Volatility Timing model must satisfy **all 5 criteria** across the 2011–2026 evaluation window:

| Metric | Required GO Threshold | Economic Motivation |
|---|---|---|
| **Net Sharpe Ratio** | `> 1.00` | Demonstrates strong risk-adjusted returns after options spreads & theta bleed |
| **Information Ratio (IR)** | `> 0.50` | Proves consistent outperformance vs buy-and-hold benchmark |
| **Max Drawdown** | `< 20.0%` | Prevents tail risk / option premium erosion |
| **Positive Regime Count** | `5 / 5 regimes` | Positive net return across 2011-15, 2016-18, 2018-20, 2020-22, 2022-26 |
| **Annualized Net Return** | `> 8.0%` | Ensures real capital growth above risk-free rate after cost |

If any criterion fails, the verdict is **NO-GO** and the model cannot be authorized for live capital deployment.
