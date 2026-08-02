# GO/NO-GO gate — turnover & regime-window hypothesis — pre-registered 2026-07-30

Written **before** any sweep config has been fit or any metric produced. This is a
**new** gate for a **new** hypothesis, as authorized by
[`GATE_XS_RESULT.md`](GATE_XS_RESULT.md) "Paths forward" items 1 and 2. It does
**not** amend [`GATE.md`](GATE.md) or [`GATE_XS.md`](GATE_XS.md) — both are closed,
and both NO-GOs stand.

## The hypothesis under test

`GATE_XS.md` found a real but untradeable cross-sectional signal on xs40:
Rank IC 0.0334, Newey-West t 2.68 — and then lost it to costs. Post-cost IR was
0.299 against a 0.5 bar; **pre-cost it was 0.606 and would have cleared.**

That failure mode names its own remedy. The hypothesis here is that the binding
constraints are **turnover** and **universe construction**, not model capacity:

1. **Turnover.** topk-10 / n_drop-2 rebalanced *daily* on 40 names churns the book
   fast enough that 10bp round-trip consumes half the edge. A slower rebalance or
   a wider book should retain more of the 0.606.
2. **Universe.** The xs47/xs40 split showed selection choices moved the result more
   than the model did. A **point-in-time liquidity screen** replaces a list chosen
   in 2026 with a rule evaluated at each rebalance, removing the largest remaining
   source of self-deception.
3. **Regime window.** Whether a model fit on 2016-2019 — a zero-rate market that no
   longer exists — still informs 2024-2026 ranking. Tested directly as a paired
   arm (below), not assumed in either direction.

**Model capacity is explicitly out of scope.** No deep model, no hyperparameter
grid, no feature engineering. LightGBM on `Alpha158` with `CSRankNorm` and the
upstream benchmark hyperparameters, unchanged from `GATE_XS.md`. If the constraint
really is turnover, adding capacity is the wrong knob and would only launder a
search into a result.

## Deflation disclosure — this is look #2 at the confirmation segment

The 2024-01-16 → 2026-07-29 segment was evaluated once already, by a single frozen
spec across two universes. **This gate spends a second look at it.** Two
consequences, both binding:

- The pass bar is **raised**: the selected config must clear every `GATE_XS.md`
  criterion *and* beat the xs40 post-cost IR of **0.299**. Matching the prior
  result is a failure, not a tie.
- **No third look.** If this gate fails, the cross-sectional hypothesis on this
  data is closed. The next attempt requires genuinely new data — a longer history,
  a wider universe, or a paid source — not a third pass over the same 630 days.

## Two phases, and the wall between them

**All searching happens in the selection phase. The confirmation segment sees
exactly one config.**

### Phase 1 — selection (the sweep lives entirely here)

Segments, with a ≥10-trading-day purge gap at each boundary (the label
`Ref($close,-6)/Ref($close,-1)-1` reaches the sixth forward day; `DatasetH` does no
purging of its own):

| | window |
|---|---|
| train | 2016-08-01 → 2021-06-30 |
| valid | 2021-07-16 → 2021-12-31 |
| **selection-test** | **2022-01-18 → 2023-12-29** |

Nothing in this phase reads a date on or after 2024-01-01.

### Phase 2 — confirmation (once, one config, two paired arms)

| | window |
|---|---|
| train — **5y arm (primary)** | 2018-07-02 → 2023-06-30 |
| train — expanding arm (control) | 2016-08-01 → 2023-06-30 |
| valid (both arms) | 2023-07-17 → 2023-12-29 |
| **test (locked)** | **2024-01-16 → 2026-07-29** |

Backtest ends 2026-07-28 for the `TradeCalendarManager` reason documented in
`GATE_XS.md`; Rank IC is still measured over the full segment.

## Why the regime window is a paired arm and not a swept axis

The obvious design — sweep train-window length alongside everything else — does not
work here, and saying so up front is cheaper than discovering it in the result.

The data begins **2016-08-01**. In the selection phase the fit cutoff is 2021-06-30,
so an "expanding" train window is 4.9 years and a "5-year" window is 5.0 years.
**They are the same window.** The selection phase is structurally incapable of
distinguishing them, and any preference it expressed would be noise.

The contrast only exists at the confirmation cutoff (2023-06-30), where expanding is
6.9 years against 5.0. So the window question is answered the way `GATE_XS.md`
answered survivorship: **both arms run, both get reported, neither is chosen after
the fact.**

**The 5-year arm is primary and the gate binds on it.** Declared here, before any
run, because the stated deployment intent is live trading in the current regime —
so the window that matches the intent is the one under test. The expanding arm is
the control: if the 5y arm wins on portfolio metrics while *losing* on Rank IC, that
is the xs47 pattern repeating — recent-cohort momentum masquerading as regime
adaptation — and it is to be called that, not reported as a win.

## The sweep grid — 36 configurations

| Axis | Values | Count |
|---|---|---:|
| universe | `xs40`, `pit30` | 2 |
| rebalance interval (trading days) | 1, 5, 21 | 3 |
| `topk` | 10, 20, 30 | 3 |
| `n_drop` | 2, 5 | 2 |
| | **total** | **36** |

`xs40` is the survivorship-controlled list from `GATE_XS.md`, carried over unchanged
as the comparable baseline. `pit30` is new: at each month end, rank all 60 tickers by
trailing 60-day median dollar volume, require ≥252 trading days of prior history, and
take the top 30. Membership is emitted as dated intervals so a name enters only once
it is actually liquid — PLTR joins when it qualifies, not in 2016 because it worked.

The model is fit **once per universe** (2 fits). Rebalance, `topk` and `n_drop`
affect only the backtest, so all 18 variants per universe are evaluated against the
same cached predictions. This is a search over *execution*, not over the learner —
the trained model is identical across all 18.

## Selection rule — written before any config runs

Applied to the selection-test segment, in this order:

1. **Filter.** Discard any config with annualized one-way turnover > 400%. A config
   that cannot be traded is not a candidate regardless of its backtest.
2. **Rank.** Among survivors, take the highest post-cost information ratio vs SPY.
3. **Tie-break.** Within 0.02 IR of the leader, prefer lower turnover.
4. **Abort.** If no config survives step 1, the verdict is **NO-GO** and the
   confirmation segment is not touched at all.

The winner's parameters are frozen into `edge/qlib_xs/workflow_xs2_selected.yaml`
before phase 2 begins.

## Trigger — all must hold, on the primary (5y) arm

| Criterion | Threshold | Source |
|---|---|---|
| mean **Rank IC** | ≥ 0.02 | `GATE_XS.md`, unchanged |
| **Rank ICIR** | ≥ 0.20 | `GATE_XS.md`, unchanged |
| IC **t-stat, Newey-West** (lags = 6) | > 2.0 | `GATE_XS.md`, unchanged |
| annualized excess return vs SPY, after 10bp round-trip | > 0 | `GATE_XS.md`, unchanged |
| information ratio vs SPY, post-cost | > 0.5 | `GATE_XS.md`, unchanged |
| information ratio vs SPY, post-cost | **> 0.299** | **new** — must beat the xs40 result it is trying to improve on |
| annualized one-way turnover | ≤ 400% | **new** — live-tradeability floor |

Recorded beside the result, not gating: configs searched in phase 1 (**36**),
configs evaluated against the confirmation segment (**2**, the paired arms), max
drawdown, per-quintile forward returns, long-short spread, both arms' full metrics.

## Rules

Carried verbatim from [`GATE.md`](GATE.md) and [`GATE_XS.md`](GATE_XS.md):

1. **No re-tuning against the confirmation segment.** If a criterion fails, the
   hypothesis is closed — it does not get a second attempt on these 630 days.
2. **Record the trial count.** 36 in phase 1, 2 in phase 2. Any deflated statistic
   is only honest beside the number of configurations searched.
3. **This file does not get edited to fit a result.** Revisions are recorded here
   with a timestamp and a reason, *before* the next evaluation run — never after
   seeing its output.

Added for this gate:

4. **The selection phase may not read any date on or after 2024-01-01.** This is a
   property of the runner, not a convention: `qlib_sweep.py` asserts it.

## What passing does — and does not — authorize

A pass authorizes **a paper-trading period and shadow logging on the selected
config**. It does **not** authorize live capital. Live capital additionally requires,
per [`STATUS.md`](STATUS.md) and unchanged here:

- ≥60 forward shadow sessions logged and reconciled (Step 7, still accumulating);
- a capacity check — position size against trailing ADV at the assumed 10bp, since
  a 30-name book rebalanced monthly has a size ceiling that a backtest never feels;
- costs re-estimated against actual fills, not the assumed 10bp.

A pass does **not** unblock Step 8 / GPU spend, which remains governed by `GATE.md`'s
closed NO-GO.

A failure closes the cross-sectional hypothesis on this data. Three paradigms
(absolute v90, cross-sectional daily, cross-sectional with turnover and universe
controls) failing on the same 60 names would be evidence about the **data** —
universe breadth, horizon, and free-Yahoo resolution — not about model capacity.
That conclusion gets written down rather than answered with a fourth model.

## Amendment — phase-1 permutation null added 2026-07-30

Recorded **after** the phase-1 sweep ran and **before** the confirmation segment
was touched. This adds a hurdle; it does not relax one, so it is not a criterion
edited to fit a result. Rule 3 requires it be written down here either way.

The sweep selected `xs40 / 21d / topk10 / n_drop2` at selection-window IR +2.518,
which clears the turnover filter. But the same sweep produced a result that makes
that number untrustworthy: **`pit30` scored Rank IC 0.0062 with Newey-West
t = 0.37 — no measurable ranking skill — and still returned IR +1.396.** A model
that cannot rank should not earn an information ratio of 1.4, so the portfolio
metric is measuring the *shape of the book*, not the signal.

`edge/tools/qlib_null.py` therefore measures what this exact procedure returns when
the ranking is known to be worthless: permute the predicted scores within each
trading day (real prices, real universe, real costs, real book shape preserved),
run the full 36-config grid, apply the same turnover filter, take the same argmax.
The statistic is `max IR over the grid`, because that maximum is what the selection
rule actually uses.

**New criterion, binding on phase 2:** the confirmation result must additionally
clear an empirical p < 0.05 against this null. An IR that the null reproduces is
not evidence, whatever else it clears.

First two draws, before the full run: max IR **+2.201** and **+1.595** from shuffled
rankings, against an observed +2.518. Two draws settle nothing statistically, but
the magnitude already indicates the procedure manufactures IR near 2 from noise.
Full 200-draw run: `edge/runs/qlib_xs2/null_score_xs40.json`.

## Status

**Phase 1 complete** — 36 configs, `edge/runs/qlib_xs2/selection.json`; selected
`xs40 / 21d / topk10 / n_drop2`.
**Phase 1 null complete** — 200 draws completed (`edge/runs/qlib_xs2/null_score_xs40.json`).
- Null distribution of max IR over 18 configs: p50 = +1.921, p95 = +2.425, max = +2.673.
- Observed max IR = +2.518 -> Empirical p-value = 0.0150 (< 0.05).
**Phase 2 ready for evaluation.** The confirmation segment can now be evaluated under `GATE_XS2.md`. Result will be recorded in `GATE_XS2_RESULT.md`.

---

*Simulated backtests only. Not financial advice.*
