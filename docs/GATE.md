# GO/NO-GO gate — pre-registered 2026-07-29

Written **before** Step 5 (widened-universe evaluation) has produced any
results. Purpose: the decision to spend on GPU compute must not be fit to the
result. This file is the trigger referenced by [`PLAN.md`](PLAN.md) Step 6 and
[`AUDIT.md`](AUDIT.md) §5.

## Trigger

A single **frozen** v90-class spec, evaluated **once** on the Step 5 locked
holdout (≥40 symbols, ≥2 distinct regimes, incl. one drawdown ≥15%), must clear
**all** of:

| Criterion | Threshold |
|---|---|
| Holdout trade count | n ≥ 200 |
| Expectancy after 10bp round-trip costs | ≥ +0.15R |
| Win rate, Wilson 95% lower bound | > 50% |
| Calibration (ECE) | ≤ 0.05 |
| Deflated Sharpe (record configs tried) | > 0 |

## Rules

1. **No re-tuning against this holdout.** If any criterion fails, the spec goes
   back to Step 5 with a fresh holdout window or regime slice — it does not get
   a second attempt on the same data.
2. **Record the trial count.** Deflated Sharpe is only honest if the number of
   configurations searched to reach this spec is written down alongside the
   result.
3. **This file does not get edited to fit a result.** If the criteria
   themselves later need revision, the revision is recorded here with a
   timestamp and a reason, made *before* the next evaluation run — never after
   seeing its output.

## What passing authorizes

If all criteria clear, Step 8 (Kronos fine-tune) is authorized **from a
modeling standpoint only**. Actual GPU/VM spend is a separate decision that
still requires the user's explicit go-ahead — this gate authorizes the work,
not the purchase.

## Status

**Evaluated 2026-07-30 → NO-GO.** See [`GATE_RESULT.md`](GATE_RESULT.md).
This file's criteria were **not** edited after seeing results.

---

*Simulated backtests only. Not financial advice.*
