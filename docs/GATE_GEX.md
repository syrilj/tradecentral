# GO/NO-GO Gate: Dealer Gamma Exposure (GEX) & Option Positioning Model

Pre-registered 2026-07-31.

## The Economic Hypothesis

Dealer option positioning dictates market liquidity dynamics:
- **Positive Net GEX (Long Gamma)**: Dealers buy weakness and sell strength to delta-hedge, causing price mean-reversion and reduced volatility.
- **Negative Net GEX (Short Gamma)**: Dealers sell weakness and buy strength, amplifying price momentum and increasing tail risk.
- **Distance to Zero-Gamma Flip (`dist_to_flip_pct`)**: As price nears the zero-gamma threshold, market regime shifts rapidly from mean-reverting to trending.

By modeling the forward outcomes of 75,000+ signals joined with native `gex_regime` and `dist_to_flip_pct` positioning features, we capture non-linear structural shifts that standard price/volume features cannot detect.

---

## Data & Strategy Protocol

- **Universe**: Liquid US Equities & Option Chains (Signal Journal 75,335 signals / 293,729 outcomes).
- **Features**:
  - `gex_regime`: Categorical dealer gamma regime (`POSITIVE_GEX`, `NEGATIVE_GEX`, `NEAR_FLIP`).
  - `dist_to_flip_pct`: Distance from current spot price to dealer zero-gamma flip point.
  - `score`: Raw signal strength score.
  - `trend`: Directional trend classifier.
- **Leakage Control**: 5-Fold Purged & Embargoed Cross-Validation.
- **Holding Period**: 1, 5, and 10 trading days.
- **Cost Model**: 10bp per side (20bp round-trip).

---

## Pre-Registered GO/NO-GO Criteria

| Metric | Required GO Threshold | Economic Motivation |
|---|---|---|
| **Mean Rank IC** | `> 0.035` | Positive rank correlation for GEX-conditioned signals |
| **Rank ICIR** | `> 0.50` | Consistency across market regimes |
| **Net Annual Return** | `> +6.0%` | Real return post 10bp transaction costs |
| **Sharpe Ratio** | `> 0.60` | Risk-adjusted excess return |
| **Max Drawdown** | `< 18.0%` | Tail-risk boundary |

If any criterion fails, the verdict is **NO-GO**.
