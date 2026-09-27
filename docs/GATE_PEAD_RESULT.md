# Post-Earnings Announcement Drift (PEAD) Honest Re-Validation Result

**Rendered**: 2026-08-02T01:33:03.367117+00:00
**Artifact**: `runs/pead_catalyst/results.json` (sha256 `f074d75c0d559ae9423c046bed2db6b8183722b118da5d867f6305c620ec2699`)
**Verdict**: 🔴 **NO-GO**

---

## Performance Summary (Purged & Embargoed Cross-Validation)

| Metric | Target Threshold | Measured Value | Pass / Fail |
|---|---|---|---|
| **Mean Rank IC** | `> 0.040` | `-0.0027` | ❌ FAIL |
| **Rank ICIR** | `> 0.50` | `-0.12` | ❌ FAIL |
| **Net Annual Return** | `> +8.0%` | `-10.38%` | ❌ FAIL |
| **Sharpe / IR** | `> 0.60` | `-0.26` | ❌ FAIL |
| **Max Drawdown** | `< 15.0%` | `88.67%` | ❌ FAIL |

---

## Execution-Lag Sensitivity

The prior version of this artifact booked each bar's own return against a
weight formed from that same bar's features — a one-bar lookahead. It reported
**+502.98% net annual / Sharpe 5.38**. Corrected, the same signal and universe
give the figures above.

| Execution lag | Net annual | Sharpe |
|---|---:|---:|
| 1 bar (reported) | `-10.38%` | `-0.26` |
| 2 bars | `-13.31%` | `-0.37` |

Gross annual `1.26%` at annualised vol
`39.63%`; compounded
`-16.80%`. Exposure `75.3%` of bars.

---

## Validation Environment & Protocol

- **Universe**: Broad liquid equity universe (557 symbols evaluated).
- **Leakage Control**: 5-Fold Purged & Embargoed Cross Validation (`purged_embargoed_kfold_splits`);
  portfolio accounting via `edge.research.portfolio.simulate_long_short`
  (execution lag 1 bar, enforced).
- **Features**: `gap_std` (20d ATR normalized gap), `vol_surge` (20d SMA volume surge),
  `short_pressure` (FINRA short ratio) — **INACTIVE: FINRA data absent, contributes nothing**.
- **Cost Model**: 10bp per side (20bp round-trip), charged per bar on realised turnover.
- **Data hygiene**: 24 asset bars with |1-day return| > 50%
  masked as unadjusted corporate actions.
- **Isotonic Calibration Mean**: `+0.5039`

### Headline IC is unconditional

Mean Rank IC is measured on the full cross-section. Restricting to
`|signal| > 1.5` — the subset the strategy actually trades — gives
`+0.0397`. That conditional figure was
the previous headline; it is a self-selected subset and is not what
`GATE_PEAD.md`'s 0.040 threshold was written against. Both are reported so
neither can be quoted alone.

---

## Final Status

PEAD evaluation has been strictly re-validated under purged cross-validation
with enforced execution lag.
**Verdict**: 🔴 **NO-GO**
