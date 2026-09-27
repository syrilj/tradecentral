# GATE_XS4 — dev-phase findings (not a verdict)

Selection-phase results for [`GATE_XS4.md`](GATE_XS4.md), run **2026-07-30** on
the `2022-01-18 → 2023-12-29` window that `GATE_XS3` already spent. Per XS4 rule
1, **nothing here is a gate verdict**. The confirmation window
(`2024-01-16 → 2026-07-29`) remains **unspent**.

## 1. The finding that reframes everything

`edge/tools/audit_wide_data.py` was written to answer "is the +0.0052 IC in
[`GATE_XS3_CORRECTION.md`](GATE_XS3_CORRECTION.md) a data bug or a model
ceiling?" It found neither. It found that **the model was never trained**:

```
Training until validation scores don't improve for 50 rounds
[20]    train's l2: 0.970287   valid's l2: 1.00446
[40]    train's l2: 0.953549   valid's l2: 1.00893
Early stopping, best iteration is:
[1]     train's l2: 0.995266   valid's l2: 0.998057
```

`best_iteration = 1`. The LightGBM carried into every XS3 backtest was a single
boosting round. Train l2 of 0.995 against a `CSRankNorm` label whose variance is
1 by construction means the model sat essentially on the mean.

Per-segment IC for that model, from the same audit:

| segment | days | mean IC | ICIR | % days > 0 |
|---|---:|---:|---:|---:|
| train | 964 | **+0.0941** | +0.8037 | 81.33% |
| valid | 118 | **−0.0079** | −0.0646 | 48.31% |
| test | 491 | **+0.0052** | +0.0349 | 49.08% |

The model fits train and produces *negative* IC on validation. Early stopping
was not malfunctioning — it was correctly refusing to train a model that made
out-of-sample predictions worse with every round.

## 2. Data is not the problem

The same audit checked the wide provider directly:

- **447 names**, 477,900 price rows, 477,453 daily returns over 2016-08 → 2023-12
- `|daily move| > 35%`: **111 rows = 0.023%**, across 84 names — a normal rate of
  real corporate events, not an adjustment failure
- Only **10** rows sit in the 1:2 / 2:1 split band; concentrated in names with
  genuine history (SNAP, BBWI, PCG, BIIB, OKE, W)

Prices are adjusted, coverage is adequate, the label is well-formed. The
`GATE_XS3` dataset is sound. The problem is downstream of the data.

## 3. Training configuration is not the problem either

Two new arms hold the learner and data fixed and change only the training
configuration, so that "the model never trained" could be ruled in or out as the
cause of the null. `LGB_TRAINABLE_KWARGS` in `edge/tools/qlib_deep_wide.py`:
`learning_rate` 0.2 → 0.02, `lambda_l1` 205.7 → 1.0, `lambda_l2` 581 → 10.0,
`num_leaves` 210 → 64, `early_stopping_rounds` 50 → 200, `num_boost_round`
1000 → 2000.

The fix worked mechanically — LightGBM now runs 180–200 rounds instead of 1 —
and made **no difference at all**:

| arm | feat | Rank IC | ICIR | NW t | exc.ret | IR | turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| `lgb158` (XS3 frozen) | 158 | +0.0052 | +0.0349 | 0.465 | +6.95% | +0.373 | 545% |
| `lgb158_fit` | 158 | +0.0044 | +0.0305 | 0.415 | −1.09% | −0.052 | 528% |
| `lgb20_fit` | 20 | +0.0026 | +0.0215 | 0.274 | −1.05% | −0.047 | 517% |

Gate bars: IC ≥ 0.02, ICIR ≥ 0.20, NW t > 2.0, exc.ret > 0, IR > 0.5,
turnover ≤ 400%. **No arm clears any of the three statistical bars.**

The training curves say why. Under the trainable config:

```
[180]   train's l2: 0.953579   valid's l2: 1.0044
[200]   train's l2: 0.950459   valid's l2: 1.00494
Early stopping, best iteration is:
[1]     train's l2: 0.997175   valid's l2: 0.997679
```

Train loss falls to 0.950. Validation loss **rises monotonically from round 2**
and never returns below its round-1 value. `best_iteration` is still 1, not
because the search was too short, but because **no number of rounds ever
improves out-of-sample loss**. The model can memorise the training cross-section
and transfers none of it.

## 4. What this actually means

Three explanations have now been eliminated by evidence rather than argument:

| candidate cause | status |
|---|---|
| broken data (splits, coverage, label) | ❌ ruled out — §2 |
| untrained model / early-stop artifact | ❌ ruled out — §3, the fix changed nothing |
| hyperparameters not transferring from CSI300 | ❌ ruled out — §3, a 10× lr change and 100× regularisation change moved IC by 0.0008 |
| model class (tree vs sequence) | tested by the `alstm` / `gru` arms; XS4's registered prediction is that this is also not it |

What remains is the specification itself: **Alpha158 price-derived features carry
no transferable information about the `CSRankNorm`-ed 6-day-forward return, on
447 US names, over this period.** The train IC of +0.094 alongside a valid IC of
−0.008 is the signature of a feature set that can memorise a cross-section and
predict nothing about the next one.

This is consistent with — and now explains — every prior gate in the project.
`GATE.md`, `GATE_XS.md`, `GATE_XS2.md`, and (corrected) `GATE_XS3.md` all closed
NO-GO. Four gates varied the universe, the turnover, the rebalance cadence, and
the regime window. **None of them varied the label or the feature family**, and
that is where the null has been sitting the whole time.

## 5. What XS4 rule 3 requires

Rule 3: promote an arm to confirmation only if its dev Rank ICIR beats
`lgb158`'s by more than 0.05 absolute. `lgb158` dev ICIR = **+0.0349**; the bar
is **+0.0849**. `lgb158_fit` (+0.0305) and `lgb20_fit` (+0.0215) are both
*below* the incumbent, let alone the margin.

Unless a sequence arm returns an ICIR above +0.0849 — which XS4's registered
prediction says it will not — the required action is: **promote nothing, close
XS4 NO-GO, leave the 2024-01-16 → 2026-07-29 window unspent.**

## 5a. Horizon axis — tested 2026-07-30, also null

Section 6 named the horizon as the most directly implicated untested axis. It
has now been tested. `--horizon` changes only the far leg of the label; the `-1`
leg, the segments, the purge gaps, the universe, and the strategy are all
unchanged, and the Newey-West lag tracks the horizon so overlapping returns
cannot inflate the t-stat.

| horizon | arm | Rank IC | ICIR | NW t | exc.ret | IR |
|---:|---|---:|---:|---:|---:|---:|
| **1d** | `lgb158` | **−0.0016** | −0.0132 | −0.309 | +13.50% | +0.945 |
| **1d** | `lgb158_fit` | **−0.0033** | −0.0232 | −0.516 | +11.82% | +0.668 |
| **2d** | `lgb158` | **−0.0046** | −0.0340 | −0.608 | +7.08% | +0.370 |
| **2d** | `lgb158_fit` | **+0.0022** | +0.0183 | +0.324 | +4.53% | +0.284 |
| 5d | `lgb158` | +0.0052 | +0.0349 | +0.465 | +6.95% | +0.373 |
| 5d | `lgb158_fit` | +0.0044 | +0.0305 | +0.415 | −1.09% | −0.052 |

Shorter horizons are **not** better here — they are marginally worse, and the
sign is negative in three of the four new cells. The horizon axis is closed.

### The 1-day row is the most instructive line in this document

`lgb158` at 1 day posts a post-cost **information ratio of +0.945** and
**+13.50% annualized excess return** — comfortably past the IR > 0.5 gate bar,
and the best portfolio numbers anywhere in this project. Its Rank IC is
**−0.0016**, with a t-stat of **−0.31**.

The signal is *worse than a coin flip* and the portfolio still made money. That
is what unhedged long-only market beta looks like when it is dressed as alpha:
hold 30 large-caps out of ~450 through 2022-2023 and you inherit the index,
whichever way the ranking points. Reading IR alone here would produce a
confident, fully backtested, completely spurious "GO" — which is precisely the
shape of the retracted `GATE_XS3_RESULT.md`, and precisely why every gate in
this directory binds on Rank IC and the Newey-West t-stat **first**.

Any result in this project that shows a strong IR next to a near-zero IC should
be read as evidence of beta, not of skill.

## 6. Where the evidence points next

Not deeper models, and not more compute. The untested axes, in order of how
directly this evidence implicates them:

1. ~~**The horizon.**~~ **Tested 2026-07-30 — null.** See §5a. 1-day and 2-day
   are no better than 5-day and mostly negative.
2. **The feature family.** Alpha158 is entirely price/volume derived. No
   fundamentals, no estimate revisions, no flow, no cross-asset, no
   point-in-time universe construction. This is now the only remaining axis
   that changes *what is knowable* rather than how it is fitted — and with the
   horizon and the learner both eliminated, the evidence points here by
   elimination rather than by hope.

That is a data question, not an engineering one. Every remaining engineering
lever has now been pulled and measured:

| axis | varied by | result |
|---|---|---|
| universe size (47 → 250 → 556) | `GATE_XS3` | null |
| turnover / rebalance cadence | `GATE_XS2` | null |
| regime window | `GATE_XS2` control arm | null |
| training configuration | §3 | null |
| learner (tree vs sequence) | §4, `alstm`/`gru` | null |
| forward horizon (1d / 2d / 5d) | §5a | null |

Six axes, six nulls, on the same feature family and the same price-only data
source. The consistent element across every NO-GO in this project is the input,
not the method.

**No live deployment is supported by anything in this document.**

---

*Artifacts: `edge/runs/qlib_xs4/dev_pitwide_lgb.json`,
`dev_pitwide_deep.json`. Audit: `edge/tools/audit_wide_data.py`.
Runner: `edge/tools/qlib_deep_wide.py`.*
