# edge/ — plan to a live-tradeable, high-confidence model

Source of truth for the current state: [`AUDIT.md`](AUDIT.md).  
**Wave status (done / in progress / blocked):** [`STATUS.md`](STATUS.md).

Principle: **one harness, one contract, one pre-registered gate.** Every claim in
this repo must be reproducible by a single command against a single evaluation
path with a lookahead test in CI. The failure that cost us the 71%/84% number was
a second, unversioned evaluation path — never again.

Steps 1–6 are CPU-only. Step 7 runs in wall-clock time, not compute. Step 8 is
the only one that needs a GPU and is gated on Step 6 passing.

---

## Step 1. Build the single leak-free evaluation harness

Port the leak-free day loop from `Kronos/eval_walkforward.py::_day_gate` and the
split-conformal calibrator from `Kronos/conformal.py` into `edge/eval/`. Every
feature at bar `t` must be computed from `df.iloc[:t]` only — never `df.iloc[:t+1]`.
Add a `test_no_lookahead` property test that shuffles all bars from `t` forward
and asserts every emitted feature, signal and confidence value is bit-identical.
That test is the thing that would have caught the leak. Delete no existing repo;
`edge/` reads from them.

Acceptance: `pytest edge/eval` green; the lookahead test fails when a deliberate
`df.iloc[t]` reference is injected; `edge/tools/verify_no_lookahead.py` exits 0.

## Step 2. Fix and regenerate the contaminated Kronos reports

Fix `Kronos/bakeoff_trend_v5.py` so `asof` resolves to the **prior** bar
(`date` in the walk-forward artifact is the target day, not the forecast origin).
Regenerate `TREND_V5_REPORT.md` and `ULTRA_BEAT_REPORT.md` through the Step 1
harness. Add a `SUPERSEDED` banner to the current files pointing at the corrected
output, matching how `MLE_CONFIDENCE_REPORT.md` was already superseded. Also
regenerate the `WINRATE{}` tier table in `Kronos/edge_filter.py` — those numbers
are printed to the operator on every live screen and are currently wrong.

Out of scope: changing the Kronos model, the conformal calibrator, or the HIGH
confidence gates.

Acceptance: regenerated reports show leak-free numbers; `edge_filter.WINRATE`
values are traceable to a committed artifact; the old numbers appear nowhere
without a SUPERSEDED banner.

## Step 3. Rebuild one comparable evidence base

Regenerate every `TradingAlgoWork/models/poc_va_macdha/*/results.json` under a
single data contract (one starting cash, one universe, one window, one cost
model). Today they mix $1k and $1M runs and mixed windows, so the cross-model
tables in `README.md` and `MODEL_REVIEW_AND_HIGH_WINRATE_PLAN.md` compare runs
that were never comparable. Emit one `LEADERBOARD.json` with per-model
expectancy (avg R), skew, Wilson CI on WR, deflated Sharpe, and trade count.

Acceptance: all `results.json` share one `contract` block; README tables
regenerate from `LEADERBOARD.json`; no hand-typed performance numbers remain.

## Step 4. Port v90_meta_confidence into edge/ as the baseline champion

`v90` is the methodological high-water mark of the stack — purged+embargoed
5-fold, isotonic calibration (holdout ECE 0.0048), triple-barrier labels, real
two-sided head. Port it into `edge/models/v90/` unchanged in logic. Fix two
defects: the `results.json` Sharpe values of 13.8 and 29.3 (artifacts of
annualizing 1764 bars/yr over 34 and 11 trades — remove or recompute per-trade),
and make the operating-point choice explicit rather than selected on holdout PF.

Acceptance: v90 reproduces its holdout calibration numbers through the Step 1
harness; no Sharpe is reported on n < 50; the shipped threshold is named in
config before evaluation, not chosen after.

## Step 5. Widen the universe and the regime coverage

The single largest source of overfit risk is 152 versions searched on 7 symbols
in one 2024–2026 melt-up. Expand to ≥40 liquid symbols across ≥4 sectors and
≥8 years of history, so the sample spans at least one drawdown ≥15% and one
non-trending regime. Re-fit v90 on the widened data with the same purged CV.
Report per-regime breakdown, not just pooled.

Acceptance: ≥40 symbols, ≥2 distinct regimes with ≥1 drawdown ≥15%; v90 refit
with identical hyperparameters; per-regime expectancy table produced.

## Step 6. Pre-register the GO/NO-GO gate — this is the VM trigger

Write the decision spec **before** running Step 5's evaluation, commit it, then
run once. Gate: n ≥ 200 holdout trades, expectancy ≥ +0.15R after 10bp costs,
Wilson 95% lower bound on win rate > 50%, ECE ≤ 0.05, deflated Sharpe > 0.
Record the number of configurations tried so the deflation is honest. A model
that fails is not re-tuned against this holdout — it goes back to Step 5 with a
fresh holdout window.

Acceptance: gate committed before results exist; single evaluation run; verdict
recorded with the trial count used for deflation.

## Step 7. Forward paper / shadow trading

No backtest substitutes for a forward record. Wire v90 into a shadow decision log
(the pattern already exists at `runs/live_confidence/shadow_decisions.jsonl`) and
merge in the `TradingWork/data/signal_journal.db` flow signals, which are the
only genuinely forward-recorded outcomes in the stack. Log calibration drift
daily: predicted probability vs realized outcome, bucketed.

Acceptance: shadow log records every decision with its calibrated probability and
realized outcome; a daily reliability plot regenerates from it; ≥60 sessions
accumulated before any live capital decision.

## Step 8. (Conditional — GPU) Fine-tune Kronos on the widened universe

**Run only if Step 6 passed.** Kronos-base is 102M params; fine-tuning it on the
7-symbol/2-year set would be ~3,500 bars per ticker, which overfits. With the
Step 5 universe it becomes defensible. Use `Kronos/finetune/train_tokenizer.py`
then `train_predictor.py`, evaluate through the Step 1 harness only, and compare
against the frozen v90 champion on the same locked holdout.

Acceptance: fine-tuned Kronos beats frozen v90 on the Step 6 gate metrics on the
same holdout, or is discarded; GPU spend and wall-clock recorded.

---

*Simulated results only. Nothing in this plan is financial advice.*
