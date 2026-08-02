# Hybrid PEAD-Factor Strategy Gate Result

**Rendered**: 2026-08-02T01:33:19.251963+00:00
**Artifact**: `/Users/syriljacob/Desktop/alltrading/edge/runs/pead_factor_hybrid/results.json` (sha256 `78ae7086358fa03162be38e9584cff0e6d4991e3549af7d1c95dd67256ac8a07`)
**Verdict**: 🔴 **NO-GO**

---

## Performance Summary (Purged & Embargoed Cross-Validation)

| Metric | Target Threshold | Measured Value | Pass / Fail |
|---|---|---|---|
| **Mean Rank IC** | `> 0.040` | `+0.0270` | ❌ FAIL |
| **Rank ICIR** | `> 0.50` | `+0.49` | ❌ FAIL |
| **Net Annual Return** | `> +8.0%` | `1.53%` | ❌ FAIL |
| **Sharpe / IR** | `> 0.60` | `+0.08` | ❌ FAIL |
| **Max Drawdown** | `< 15.0%` | `36.18%` | ❌ FAIL |

---

## Key Improvements Applied

1. **Signal Synthesis**: Composite of PEAD Gap (50%), Short-Term Reversal `rev5` (25%), and 12-Month Momentum `mom12_1` (25%).
2. **Turnover Damping**: Daily overlapping cohorts (20% daily rebalancing) cut annual turnover from 116.5x to `+146.55x`.
3. **Volatility Regime Scaling**: Dynamic inverse-ATR risk scaling damped peak portfolio drawdown from 35.76% to `36.18%`.
4. **Data Inputs**: PEAD gap score's short-interest multiplier (`short_pressure`,
   FINRA short ratio) — **INACTIVE: FINRA data absent, multiplier neutralized to 1.0**.
   See `edge/tools/data_sources.py::load_finra_short_vol` and
   `edge/docs/LOOKAHEAD_CORRECTION.md` for why this is now stated explicitly
   instead of assumed.

---

## Final Status

PEAD Hybrid Strategy has been evaluated under 5-Fold Purged & Embargoed Cross-Validation.
**Verdict**: 🔴 **NO-GO**
