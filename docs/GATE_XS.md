# GO/NO-GO gate — cross-sectional hypothesis — pre-registered 2026-07-30

Written **before** any Qlib model has been fit or any Qlib metric produced. This
is a **new** gate for a **new** hypothesis on a **new** holdout, as authorized by
[`GATE_RESULT.md`](GATE_RESULT.md) "Paths forward" item 1. It does **not** amend
[`GATE.md`](GATE.md) — that gate is closed, and its NO-GO stands.

## The hypothesis under test

Every model in this stack so far asks an **absolute, per-symbol** question: *"will
this symbol rise over the next H bars?"* v90_wide answered it honestly (holdout
ECE 0.0088) and unprofitably (expectancy −0.03%/trade, Sharpe −0.73).

The new hypothesis is **cross-sectional**: *"which names in the universe will
outperform the others?"* Features are normalized across the cross-section each
bar (`CSRankNorm`), which removes the market-wide component by construction. A
model trained this way cannot express "everything goes up" — the exact
proposition that flattered v90 during the 2024-26 melt-up.

Substrate: `edge/data/1d/`, daily bars 2016-08 → 2026-07. Unlike the ~730-day 1H
window, this spans COVID, the 2022 bear market and the 2024-26 melt-up, and so
can satisfy the multi-regime condition `GATE.md` asked for and 1H never could.

## Baseline: what "no signal" reads like on this data

Established **before** this gate by `edge/tools/rank_ic.py` against the
already-failed v90_wide bundle (`edge/runs/v90_wide_ic.json`) — a negative
control, run so the thresholds below are calibrated against a measured null
rather than an abstract number:

| score | mean Rank IC | Rank ICIR | t (Newey-West) | bars IC>0 |
|---|---:|---:|---:|---:|
| `raw_long` | −0.00081 | −0.0045 | −0.09 | 50.5% |
| `signed` | −0.00524 | −0.0286 | −0.60 | 49.3% |

Forward-return quintiles were flat and uniformly positive
(q1 +0.1215% … q5 +0.1490%, spread +0.028%): every bucket earned the same drift,
so the score carried no ordering information. **That is the null this gate must
beat.**

## Trigger

A single **frozen** spec — LightGBM on `Alpha158` with `CSRankNorm`, long-only
`TopkDropoutStrategy` — fit once and evaluated **once** on the locked test
segment, must clear **all** of:

| Criterion | Threshold | Rationale |
|---|---|---|
| Test mean **Rank IC** | ≥ 0.02 | ~25× the measured null; still below published equity signals (0.03–0.05) |
| **Rank ICIR** | ≥ 0.20 | null measured at −0.005 |
| IC **t-stat, Newey-West** (lags = label horizon) | > 2.0 | naive t is optimistic under overlapping labels; NW is the binding form |
| Top-k portfolio annualized excess return vs SPY, after 10bp round-trip | > 0 | signal must survive costs, not just correlate |
| Information ratio vs SPY | > 0.5 | |
| Configurations evaluated against the test segment | recorded; **1** intended | deflated-Sharpe honesty, per `GATE.md` rule 2 |

Reported but **not** gating: max drawdown, turnover, per-quintile forward returns,
long-short spread. These inform the write-up; they cannot rescue a failed
criterion.

## Universe and segments (locked before the run)

- **47 single names.** The 13 ETFs (SPY QQQ IWM DIA GLD TLT HYG LQD XBI XLE XLF
  XLP XLU) are excluded from the ranked cross-section — ranking an index against
  a single stock is not a meaningful comparison. SPY is retained as `benchmark`.
- **Segments** with a purge gap at each boundary, because the forward label
  otherwise straddles the split (Qlib's `DatasetH` does no purging, unlike the
  v90 CV): train 2016-08-01→2022-12-30, valid 2023-01-17→2023-12-29,
  **test 2024-01-16→2026-07-29 (locked; touched once)**.

  > **Revision 2026-07-30, before any model was fit.** The gap was first written
  > as 5 calendar days with segments starting 2023-01-09 / 2024-01-09. That is
  > too narrow: the label `Ref($close,-6)/Ref($close,-1)-1` reads the *sixth*
  > forward trading day, so the last train row's label still reached into the
  > valid segment. Widened to ≥10 trading days at each boundary. Recorded here
  > per rule 3 — made before the first run, not after seeing a result.
  >
  > **Revision 2026-07-30 (second), before any gate metric was read.** The
  > *portfolio backtest* ends 2026-07-28 rather than 2026-07-29. Qlib's
  > `TradeCalendarManager.get_step_time` reads `calendar_index + 1` on every
  > step, so the last step requires a trading day to exist after it and the run
  > raises `IndexError` when the window ends on the final calendar day. This
  > costs one day of backtest and changes no criterion; **Rank IC is still
  > measured over the full test segment**. Mechanical fix, made before any
  > metric was observed.

## Mandatory dual reporting — survivorship

The 60 tickers were chosen in 2026 with full knowledge of which ones worked.
Qlib's `instruments/` files handle *listing* bias correctly (ARM starts 2023-09,
COIN/IONQ/RKLB/PLTR/SNOW 2020-21), but nothing here corrects for the fact that
NVDA and PLTR are on the list while the 2016 names that went nowhere are not.

The result **must** therefore report every gating metric twice: on all 47 names,
and on the **40** listed before 2016-08. The gap is a survivorship premium and is
to be stated plainly whatever the verdict.

## Rules

Carried verbatim from [`GATE.md`](GATE.md):

1. **No re-tuning against this holdout.** If any criterion fails, the hypothesis
   goes back for a fresh window or a fresh label — it does not get a second
   attempt on the same test segment.
2. **Record the trial count.** Any deflated statistic is only honest if the number
   of configurations searched is written down beside the result.
3. **This file does not get edited to fit a result.** Revisions are recorded here
   with a timestamp and a reason, *before* the next evaluation run — never after
   seeing its output.

## What passing authorizes

A pass authorizes **further research on a fresh window** — a second
cross-sectional experiment, 1H porting, or label variants. It does **not**
authorize live capital, and it does **not** unblock Step 8 / GPU spend, which
remain governed by `GATE.md`'s closed NO-GO and the user's explicit go-ahead.

A failure closes the cross-sectional hypothesis on this universe. Combined with
the null baseline above, two independent paradigms failing on the same 47 names
would be evidence about the **data** — universe, horizon, and free-Yahoo
resolution — not about model capacity. That conclusion is to be written down
rather than answered with a third model.

## Status

**Not yet evaluated.** Result will be recorded in `GATE_XS_RESULT.md`.

---

*Simulated backtests only. Not financial advice.*
