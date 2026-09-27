# GEX & Option Positioning Meta-Model Gate Result

**Evaluation Date**: 2026-07-31  
**Artifact SHA256**: `df7d78ac0a23b00060cd11dd26ec436f442621764db8583c54ca1a3d657e8d52`  
**Verdict**: 🔴 **NO-GO**

---

## Performance Summary (Purged & Embargoed Cross-Validation)

| Metric | Target Threshold | Measured Value | Pass / Fail |
|---|---|---|---|
| **Mean Rank IC** | `> 0.035` | `-0.1063` | ❌ FAIL |
| **Rank ICIR** | `> 0.50` | `-1.69` | ❌ FAIL |
| **Net Annual Return** | `> +6.0%` | `-2.00%` | ❌ FAIL |
| **Sharpe Ratio** | `> 0.60` | `0.00` | ❌ FAIL |
| **Max Drawdown** | `< 18.0%` | `0.00%` | ✅ PASS |

---

## Dataset & Training Environment

- **Source Database**: `TradingWork/data/signal_journal.db` (221,301 signal-outcome pairs).
- **Features Included**: `gex_regime`, `dist_to_flip_pct`, `score`, `direction`, `feature_score`.
- **Validation**: 5-Fold Purged & Embargoed Cross Validation on trading dates.

---

## Final Status

**Verdict**: **NO-GO**
