# Is more GCP training justified? — evidence-based answer

**Short answer: no. Not yet, and not for compute.** The binding constraint on this system
is cross-sectional data breadth, not GPU hours. Spending on training now buys faster
overfitting, not accuracy.

## What the existing validation actually shows
From `runs/squeeze_validation/summary.json` and `panel.parquet` (read directly):

| Measure | Value | Verdict |
|---|---|---|
| Distinct asof dates | 10 (8 usable after error rows drop 2) | far too few |
| Scored rows | 175 of 187 (12 errored) | 17.5 rows/date |
| Signals at production threshold (15), 1d | 25 | too few to test |
| `theory_hit` 1d | 13/25 = 0.52 | Wilson 95% CI **[0.335, 0.700]** — spans 0.5 |
| `rank_ic_theory` 1d / 3d | −0.140 (t=−1.40) / −0.193 (t=−1.36) | not significant, and negative |
| Score's own top-minus-bottom quartile return | −0.28% (1d), −1.26% (3d) | wrong sign |
| Amplification `rank_ic_sr_vs_abs_ret` | **−0.239, t = −2.45, p < 0.05** | significant, and backwards |
| Walk-forward OOS folds | **0** | the gate has evaluated nothing |

The one statistically significant result in the entire validation contradicts the
screener's premise: mean |return| is **1.10%** for HIGH squeeze-risk names versus **2.12%**
for LOW. High squeeze-risk names move *less*, not more.

Note this is a verdict on the *signal*, not the *code*. The GEX and Black-Scholes math was
audited term by term and is correct.

## Why compute is not the bottleneck — the arithmetic
Power analysis, one-sample proportion test against p=0.50, two-sided α=0.05, 80% power:

| True hit rate you want to detect | Qualifying signals needed |
|---|---|
| 0.55 | 783 |
| 0.57 | 399 |
| 0.60 | 194 |
| 0.65 | 85 |

You currently have **25**. At today's 17.5 scored rows/date and a 33% fire rate, reaching
784 signals takes ~135 trading days — **6.4 months of waiting**.

But breadth substitutes for calendar time, and breadth is cheap:

| Symbols scored per date | Trading days to 784 signals |
|---|---|
| 17.5 (today) | ~135 (6.4 months) |
| 50 | ~47 (2.3 months) |
| 200 | ~12 (0.6 months) |
| 500 | ~5 (0.2 months) |

`data/1d_wide` already holds **558 symbols**. The universe exists. The validation only
scores 17.5 per date because `data/option_chains` has just **17 date partitions**, and the
run's own caveats admit the OI snapshot is "often single date; OI assumed sticky."

## What to spend on instead — ranked
1. **Widen daily option-chain capture.** Go from ~17 symbols/day toward 200-500. This is
   an API-quota and storage cost, not a training cost, and it compresses time-to-answer
   from 6 months to under a month.
2. **Run the capture on a schedule so the panel accumulates.** The panel spans
   2026-07-31..2026-08-13. Without a standing daily job there is nothing to train on later
   regardless of compute.
3. **Fix the stale-data shadowing first.** `data/1d` is 13 sessions stale (max 2026-08-05)
   across all 194 symbols while `data/1d_wide` is current (2026-08-18) across 558.
   `research/squeeze_validation.py:34` checks `data/1d` first, so the stale copy wins.
   This is why `fwd_5d` has **0 non-null values in 187 rows** — no row had 5 sessions of
   forward data. Any GCP run launched today would inherit this and produce a confident
   result from stale prices.
4. **Only then** consider compute — and even then, note that the previous GCP run
   (`runs/squeeze_validation_gcp/summary.json`, 2026-08-04) scored 33 rows with 21 errors
   and returned all-zero hit rates and null ICs. It was *less* informative than the local
   run. More of that is not worth paying for.

## What would justify GCP spend later
Once the panel reaches roughly 400+ qualifying signals across 60+ distinct dates with a
working walk-forward split, GCP becomes worth it for: hyperparameter sweeps over the
squeeze weights (currently undocumented magic numbers: 30/15/10/10/5 in `gex_core.py`),
vol-normalizing `mom_ref` (currently one global 0.03 for every symbol), and bootstrap
confidence intervals. All of those are embarrassingly parallel and genuinely compute-bound.
None of them are worth running against 25 signals.
