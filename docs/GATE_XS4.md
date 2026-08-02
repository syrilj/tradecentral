# GO/NO-GO gate — model-class hypothesis — pre-registered 2026-07-30

Written **before** any deep model has been fit on this dataset. This is a new
gate for a new hypothesis on the **same** data [`GATE_XS3.md`](GATE_XS3.md)
built. It does **not** amend `GATE.md`, `GATE_XS.md`, `GATE_XS2.md`, or
`GATE_XS3.md` — all four are closed and their verdicts stand.

> **Premise revised 2026-07-30, before any arm was run.** This gate was first
> drafted citing `GATE_XS3_RESULT.md`'s **GO**. That verdict has since been
> retracted — see [`GATE_XS3_CORRECTION.md`](GATE_XS3_CORRECTION.md). XS3's real
> numbers are mean Rank IC **+0.0052**, NW t **+0.47**, and it fails 5 of 6
> criteria. The question below is restated accordingly. Nothing else in this
> file changed, and no arm had been fit when it was revised.

## The hypothesis under test

`GATE_XS3` set out to show that a wide universe carries cross-sectional ranking
signal. On its actual artifacts it **did not**: mean Rank IC **+0.0052**, Rank
ICIR **+0.0349**, Newey-West t **+0.47** on `pitwide`, with the model ranking
correctly on 49.1% of the 491 test days. That result was produced by a
**gradient-boosted tree on same-day features** — LightGBM on Alpha158, with no
notion of sequence.

The question this gate asks: **is the learner the reason?** Could a model that
sees temporal structure find signal that a same-day tree cannot?

The honest prior is no, on two grounds. First, Alpha158 already hand-encodes
lookback windows (ROC60, STD5, CORR20, WVMA60 — the window length is baked into
the feature name), so a sequence model over those features is partly
re-deriving structure the handler already handed it. Second, when a baseline
lands this close to zero, the binding constraint is far more often the label,
the horizon, or the feature set than the architecture. A learner swap does not
usually rescue an IC of 0.005.

This gate is worth running anyway because it is cheap and it **closes the
question with evidence instead of assertion** — and because a negative result
here redirects effort to the label and the horizon, which is where it should go
next.

**The data, universe, label, costs, strategy, and segments are frozen. This
tests model class alone.** Unchanged from `GATE_XS3.md`:

- Provider: `edge/data/qlib_us_1d_wide`, region `us`
- Universe: `pitwide` primary, `allwide` comparison — dual reporting as in XS3
- Label: `Ref($close, -6) / Ref($close, -1) - 1`, `CSRankNorm` on the label only
- Costs: 10bp round-trip (`open_cost=0.0005`, `close_cost=0.0005`, `min_cost=0`)
- Strategy: `IntervalTopkDropoutStrategy`, `topk=30`, `n_drop=3`, weekly
  (`rebalance_days=5`)
- Benchmark: SPY

Changing any of these makes it a different gate.

## Arms

Every hyperparameter is an **upstream qlib benchmark value**, copied verbatim
from `edge/.qlib-src/examples/benchmarks/*/workflow_config_*_Alpha158.yaml`.
They were fixed by qlib's authors on CSI300 — Chinese equities, a different
market, years before this dataset existed. **Nothing here was searched against
any window of the US wide data.**

| arm | model | features | dataset | role |
|---|---|---:|---|---|
| `lgb158` | LGBModel | 158 | `DatasetH` | **incumbent** — the frozen XS3 spec, reproduced |
| `lgb20` | LGBModel | 20 | `DatasetH` | **control** — same learner, deep arms' feature set |
| `alstm` | ALSTM (`pytorch_alstm_ts`) | 20 | `TSDatasetH` step_len 20 | challenger |
| `gru` | GRU (`pytorch_gru_ts`) | 20 | `TSDatasetH` step_len 20 | challenger |
| `lstm` | LSTM (`pytorch_lstm_ts`) | 20 | `TSDatasetH` step_len 20 | challenger |
| `transformer` | TransformerModel (`pytorch_transformer_ts`) | 20 | `TSDatasetH` step_len 20 | challenger |

### Why `lgb20` exists, and why the gate is unreadable without it

Upstream's Alpha158 configs for the sequence models do **not** feed all 158
features. They prepend a `FilterCol` processor selecting 20 named columns
(`RESI5, WVMA5, RSQR5, KLEN, RSQR10, CORR5, CORD5, CORR10, ROC60, RESI10,
VSTD5, RSQR60, CORR60, WVMA60, STD5, RSQR20, CORD60, CORD10, CORR20, KLOW`) and
set `d_feat: 20`. LightGBM's upstream config uses all 158.

So a naive "ALSTM vs LightGBM" comparison confounds **model class** with
**feature count**, and any result would be uninterpretable. `lgb20` is the same
frozen LightGBM learner on the deep arms' exact 20 columns. The three-way read:

| observed | conclusion |
|---|---|
| `alstm` > `lgb20` **and** > `lgb158` | sequence modelling is doing real work |
| `alstm` > `lgb20` but < `lgb158` | the 138 dropped features mattered more than the architecture |
| `alstm` ≈ `lgb20` ≈ `lgb158` | model class is not the binding constraint — stop spending compute here |
| `alstm` < `lgb20` | the sequence model is underfitting or the recipe does not transfer from CSI300 |

## Segments

**Selection / dev phase.** Test on `2022-01-18 → 2023-12-29`.

This is the window `GATE_XS3.md` already spent its single look on. It cannot be
un-spent, and that is precisely what qualifies it for selection: a window you
have already burned is the *only* honest place to compare arms, because you are
not spending anything you still need. Arms may be compared, ranked, re-run, and
argued over freely on dev. **No result on dev is a gate verdict.**

| | window |
|---|---|
| train | 2016-08-01 → 2021-06-30 |
| valid | 2021-07-16 → 2021-12-31 |
| dev test (already spent by XS3, free to re-use for selection) | 2022-01-18 → 2023-12-29 |

**Confirmation phase.** Test on `2024-01-16 → 2026-07-29`.

`GATE_XS3.md` states this window is "deliberately NOT used here and is reserved
as a **future confirmation set** — to be spent, if at all, under a new gate, and
only once, exactly as `GATE_XS.md` and `GATE_XS2.md` were." **This gate is that
new gate.** No prior run has touched it.

| | window |
|---|---|
| train | 2016-08-01 → 2023-06-30 |
| valid | 2023-07-17 → 2023-12-29 |
| **confirmation test (locked, ONE look, ONE arm)** | **2024-01-16 → 2026-07-29** |

Each split carries a ≥10-trading-day purge gap; the label reads 6 trading days
forward, so contiguous splits would leak across the boundary.

## Rules

1. **Dev selects, confirmation decides.** Exactly **one** arm is promoted from
   dev to confirmation. `edge/tools/qlib_deep_wide.py --phase confirm` refuses
   more than one arm at the argument parser, before qlib initialises.
2. **One look.** The confirmation segment is evaluated once, for that one arm.
   No re-tune, no second arm, no "let me just also check" — whatever the number
   is, it is the verdict. If it fails, `GATE_XS4` closes NO-GO and the
   confirmation window is gone for good.
3. **Promotion rule, fixed in advance.** The arm promoted is the one with the
   highest **dev Rank ICIR**, and it is promoted **only if** it beats `lgb158`'s
   dev Rank ICIR by more than **0.05 absolute**. If no arm clears that margin,
   the correct action is to promote **nothing**, close XS4 NO-GO on the grounds
   that model class is not the binding constraint, leave the 2024-26 window
   unspent for a future gate, and keep `lgb158` as the incumbent.
   *Rationale for the margin: an ICIR difference smaller than 0.05 on a ~490-day
   dev window is inside the noise band, and promoting on it would be selecting
   on noise — the exact failure `GATE_XS2_RESULT.md` documented.*
4. **Dual reporting.** `pitwide` and `allwide` both reported, as in XS3.
5. **Trial count is recorded.** `trial_count_vs_confirm_segment` is written into
   the result JSON. It must read 1.

## Trigger — confirmation thresholds

Carried **unchanged** from `GATE_XS3.md` so the cycles stay comparable.

| Criterion | Threshold | Source |
|---|---|---|
| Test mean **Rank IC** | ≥ 0.02 | `GATE_XS.md`, unchanged |
| **Rank ICIR** | ≥ 0.20 | `GATE_XS.md`, unchanged |
| IC **t-stat, Newey-West** (lags = 6) | > 2.0 | `GATE_XS.md`, unchanged |
| Annualized excess return vs SPY, post-10bp | > 0 | `GATE_XS.md`, unchanged |
| Information ratio vs SPY, post-cost | > 0.5 | `GATE_XS.md`, unchanged |
| Annualized one-way turnover | ≤ 400% | `GATE_XS2.md`, unchanged |
| Configurations evaluated against the confirmation segment | **1** | `GATE.md` rule 2 |

Reported but **not** gating: max drawdown, Pearson IC, naive t-stat, long-short
spread, per-arm wall-clock.

### The prediction, registered in advance

Alpha158 already encodes multi-horizon lookbacks as named features, so a
sequence model over those same features is partly re-deriving structure the
handler handed it. The registered prediction is therefore: **the sequence arms
do not clear rule 3's +0.05 ICIR margin over `lgb158` on dev**, and the correct
outcome of this gate is that nothing is promoted and the confirmation window
stays unspent.

Registering the null as the expected outcome is the point. If the deep arms do
clear it, that is informative *because* it was predicted not to happen.

## What a GO would and would not authorize

A GO authorizes forward **shadow logging** of the promoted model — recording
what it would have done, alongside the existing `lgb158` shadow, with no capital
at risk — and nothing else. It does not authorize live deployment, position
sizing, or any change to `edge/daily_plays/`. Live capital is out of scope for
every gate in this directory and remains so.

---

*Runner: `edge/tools/qlib_deep_wide.py`. Artifacts:
`edge/runs/qlib_xs4/dev_pitwide.json`, `dev_allwide.json`, and — if and only if
rule 3 promotes an arm — `confirm_pitwide.json`.*
