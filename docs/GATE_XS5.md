# GO/NO-GO gate — cost-aware execution hypothesis — pre-registered 2026-08-16

Written **before** any run of the runner named below. This is a **new** gate for
a **new** hypothesis. It does **not** amend `GATE.md`, `GATE_XS.md`,
`GATE_XS2.md`, `GATE_XS3.md`, or `GATE_XS4.md` — all five are closed and their
verdicts stand.

## The hypothesis under test

`GATE_XS2.md` found the cross-sectional signal's failure mode precisely: the
pre-cost information ratio was **0.606** and post-cost it was **0.299** — 10bp
round-trip consumed half the edge. `GATE_XS4_DEV.md` then eliminated six axes
(universe size, turnover cadence, regime window, training configuration,
learner class, forward horizon) and concluded the remaining axis is the feature
family — a data question this repository cannot answer without new data.

This gate tests the **one execution lever that was never pulled**: putting the
trade-cost term *inside* the weight-formation objective.
`edge/research/optimizer.py` solves for the weight vector that maximizes alpha
net of a risk penalty and an L1 trade-cost penalty against the previous
holding, so the optimizer itself is cost-aware rather than cost-blind. It has
existed since 2026-08-03 and has **never been evaluated against a gate**. The
hypothesis: a cost-aware optimizer plus volatility targeting (the one Sharpe
lever that does not add turnover) retains more of the pre-cost edge than the
`TopkDropoutStrategy` book that lost it in XS2.

**Model capacity is explicitly out of scope.** No model is fit at all. The
signals are frozen price-momentum features carried over from
`edge/tools/xs_baseline.py`. If the constraint really is turnover, adding
capacity is the wrong knob — this is the same discipline as `GATE_XS2.md`.

## Deflation disclosure — this is a re-look at spent data

The cross-sectional price-data family has been looked at six times already
(`GATE.md`, `GATE_XS.md`, `GATE_XS2.md`, `GATE_XS3.md`, `GATE_XS4.md`, and the
daily directional program). The development window below overlaps windows those
gates spent. Two consequences, both binding:

- The pass bar is **raised**: the primary spec must clear every criterion below
  *and* beat the frozen decile baseline with a positive paired confidence
  bound. Matching the baseline is a failure, not a tie.
- **The only fresh evidence is the terminal holdout.** Development results are
  necessary but not sufficient; a development pass authorizes nothing except
  waiting for the sealed holdout to accumulate ≥120 sessions.

## Frozen spec (no search — changing any value changes the gate)

| axis | value |
|---|---|
| universe | `pit30` dated-interval instruments file, **authoritative** (a symbol absent from it is never a member) |
| signal | `mom12_1` = `close.shift(21) / close.shift(126) - 1` per symbol |
| rebalance | weekly (every 5 trading days) |
| optimizer | `risk_aversion=1.0`, `turnover_penalty=1.0`, `cost_per_side=10bp`, `max_weight=0.05`, `leverage=1.0`, `dollar_neutral=True`, `covariance_window=120` |
| vol targeting | `target_vol=10%`, `max_leverage=2.0`, `window=20`, method `realized` |
| execution | `execution_lag=1` (weights formed at close of bar i earn from bar i+1) |
| costs | 10bp per side, 20bp round-trip, charged per bar of realized turnover |
| accounting | `edge.research.portfolio.simulate_long_short` — the audited primitive, no hand-rolled weight-times-price arithmetic |

**Recorded trials (for deflation only, never selected):** `mom21`, `rev5`, and
`mom12_1` without vol targeting. `trial_count = 4`. The gate binds on the
primary spec alone; the other three are reported beside it so the deflated
statistic is honest.

**Frozen decile baseline (clarified 2026-08-16, before the run):** the same
`mom12_1` signal on the same PIT universe, same window, same costs, same weekly
rebalance cadence, same `execution_lag=1` accounting — but weights formed by
cross-sectional decile rank (long top decile, short bottom decile,
dollar-neutral) instead of the cost-aware optimizer, and no vol targeting. The
only difference between the primary spec and the baseline is the
weight-formation mechanism, which is exactly the hypothesis under test.

## Segments

| | window |
|---|---|
| development | 2018-01-02 → 2026-07-29 |
| **terminal holdout (sealed)** | **2026-07-30 → 2027-02-12** (126 sessions) |

Development is evaluated as expanding, purged, embargoed walk-forward folds on
the trading-date axis (`label_horizon=1`, `embargo=5`, `initial_train=504`,
`validation=126`, `step=126`, partial final fold ≥60 dates). The strategy is a
fixed spec with no fitting, so it is run once over the development window and
each fold's validation dates are sliced out as out-of-sample daily net returns.

The runner **never loads a bar after 2026-07-29** — this is asserted, not
conventional. The holdout is evaluated once, by a separate invocation, only
after ≥120 sessions have accumulated (earliest ~2027-01).

## Trigger — all must hold, no partial credit

| Criterion | Threshold |
|---|---|
| OOF daily net expectancy, 95% CI lower bound (date-block bootstrap, block=5) | > 0 |
| Deflated Sharpe lower bound (`trial_count=4`) | > 0 |
| Paired difference vs frozen decile baseline, 95% CI lower bound | > 0 |
| Annualized one-way turnover | ≤ 400% |
| Largest single-symbol share of positive OOF P&L | ≤ 50% |

Reported but not gating: max drawdown, gross vs net expectancy, per-trial
metrics, fold count, panel coverage.

## Rules

1. **No re-tuning against development after seeing results.** If a criterion
   fails, the hypothesis is closed on this data.
2. **This file does not get edited to fit a result.** Revisions are recorded
   here with a timestamp and a reason, *before* the next evaluation run.
3. **The runner may not read any date after 2026-07-29.** This is a property of
   the runner, not a convention: `xs5_pit_optimizer.py` asserts it.
4. **The holdout is evaluated once.** No second look, no re-run with a tweaked
   spec.

## What passing does — and does not — authorize

A development pass authorizes **waiting for the sealed terminal holdout** and
nothing else. A holdout pass authorizes **forward shadow collection only**,
with the same semantics as `edge/daily_plays/promotion.py`'s
`underlying_gate_authorization`: `shadow_collection_authorized=True`,
`live_capital_authorized=False`, `broker_connectivity_authorized=False`.

**No gate in this repository can authorize live capital.** The promotion gate
is fail-closed by construction and additionally requires ≥120 forward shadow
sessions, ≥200 completed trades, ≥2 regimes, ask-to-bid fills, and a drawdown
≤8% — evidence only forward time can produce.

## Status

Pre-registered 2026-08-16. Not yet run. Runner: `edge/tools/xs5_pit_optimizer.py`.
Artifacts: `edge/runs/xs5/results.json`, result doc `edge/docs/GATE_XS5_RESULT.md`.

---

*Simulated backtests only. Not financial advice.*
