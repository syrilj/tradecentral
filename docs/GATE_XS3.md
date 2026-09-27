# GO/NO-GO gate — universe breadth hypothesis — pre-registered 2026-07-30

Written **before** any wide-universe data has been fetched or any model has been
fit. This is a **new** gate for a **new** hypothesis, on a **new** dataset,
evaluated on a **different, older test window** than the one `GATE_XS.md` uses.
It does **not** amend [`GATE.md`](GATE.md) or [`GATE_XS.md`](GATE_XS.md) — both
are closed and their NO-GO verdicts stand. [`GATE_XS2.md`](GATE_XS2.md) is a
separate, **concurrently running** experiment (turnover and rebalance cadence,
on the existing 60-ticker pool) — this gate does not read its result, does not
amend it, and touches none of its files, data, or code.

## The hypothesis under test

`GATE_XS_RESULT.md` closed the first cross-sectional cycle **NO-GO** and named
two candidate constraints: turnover and universe. `GATE_XS2.md` is testing
turnover (rebalance cadence, topk width) on the existing 60-ticker pool, running
in parallel with this gate. This gate isolates the other axis: **universe
breadth alone.**

The specific mechanism: with `topk=10` out of a 47-name universe,
`GATE_XS_RESULT.md` held 21% of the entire ranked universe at all times — an
opinionated index fund, not selection. Separately, daily cross-sectional IC is
computed **across names** at each date, so its sampling noise shrinks roughly
with `sqrt(n_names)`; at 47 names that noise term is large and suppresses
`Rank ICIR` directly — xs40 scored 0.1798 against a 0.20 bar, a noise-sized
shortfall rather than a large one. A universe wide enough to make `topk`
genuinely selective (a true top decile, not a fifth of the field) should raise
statistical power on the IC estimate and turn `topk` selection into actual
selection rather than near-indexing.

**The model is frozen. This tests breadth alone.** Unchanged from `GATE_XS.md`:

- Handler: `Alpha158` (`qlib.contrib.data.handler`)
- Label normalization: `CSRankNorm` on the label only (`learn_processors`)
- Label: `Ref($close, -6) / Ref($close, -1) - 1` (5-trading-day forward return)
- Model: `LGBModel`, upstream Alpha158 LightGBM benchmark hyperparameters,
  unchanged — `loss=mse, colsample_bytree=0.8879, learning_rate=0.2,
  subsample=0.8789, lambda_l1=205.6999, lambda_l2=580.9768, max_depth=8,
  num_leaves=210, num_threads=8`
- Costs: 10bp round-trip (`open_cost=0.0005`, `close_cost=0.0005`, `min_cost=0`)
- Region `us`, no `limit_threshold` (a China price-limit rule with no US meaning)

Changing any of these makes it a different gate.

### Strategy (pre-registered, not tuned on this data)

`TopkDropoutStrategy`, `topk=30`, `n_drop=3`, rebalanced **weekly**, on the
`pitwide` universe (`N=300` names by default). 30/300 = **10%** of the ranked
universe held at any time — genuinely selective, against the 21% (10-of-47)
that failed in `GATE_XS.md`. This is chosen *because* it mirrors the
topk/universe ratio the hypothesis argues for, decided before this run touches
any data; it is not searched or tuned against the test segment below (0
configurations swept — see Trigger).

## Universe and segments (locked before the run)

**Universe.** A fresh candidate pool of 500–700 liquid US tickers (large- and
mid-cap, sector-diverse: tech, financials, healthcare, energy, industrials,
staples, discretionary, utilities, materials, real estate, communications),
fetched independently into `edge/data/1d_wide/` — entirely separate from the
60-ticker pool `GATE_XS.md` and `GATE_XS2.md` use. Two universes are derived
from it and **both are evaluated** — see "Mandatory dual reporting" below.

**Segments**, each with a ≥10-trading-day purge gap (the label
`Ref($close,-6)/Ref($close,-1)-1` reaches the sixth forward trading day; Qlib's
`DatasetH` performs no purging of its own):

| | window |
|---|---|
| train | 2016-08-01 → 2021-06-30 |
| valid | 2021-07-16 → 2021-12-31 |
| **test (locked, evaluated once)** | **2022-01-18 → 2023-12-29** |

**Why this window, and not 2024-2026.** This test segment contains the 2022
bear market, satisfying `GATE.md`'s long-standing requirement of "≥2 regimes
incl. a drawdown ≥15%" that the 1H data could never supply on a free source. It
is also **not** the segment `GATE_XS.md` already evaluated once
(2024-01-16→2026-07-29) and that `GATE_XS2.md` is concurrently spending its
second and final look on. Reusing that window a third time, before either
running cycle has even finished, would be its own deflation problem. This gate
avoids it entirely by testing on a window no frozen spec has touched yet.

The **2024-01 → 2026-07-29 window is deliberately NOT used here** and is
reserved as a **future confirmation set** — to be spent, if at all, under a new
gate, and only once, exactly as `GATE_XS.md` and `GATE_XS2.md` were.

## Trigger

A single **frozen** spec — `pitwide` primary, `allwide` comparison (below) —
fit once per universe and evaluated **once** on the locked test segment above,
must clear **all** of the following. Thresholds are carried **unchanged** from
`GATE_XS.md` so the two cycles are comparable; the turnover cap is carried from
`GATE_XS2.md`.

| Criterion | Threshold | Source |
|---|---|---|
| Test mean **Rank IC** | ≥ 0.02 | `GATE_XS.md`, unchanged |
| **Rank ICIR** | ≥ 0.20 | `GATE_XS.md`, unchanged |
| IC **t-stat, Newey-West** (lags = 6) | > 2.0 | `GATE_XS.md`, unchanged |
| Top-k portfolio annualized excess return vs SPY, after 10bp round-trip | > 0 | `GATE_XS.md`, unchanged |
| Information ratio vs SPY, post-cost | > 0.5 | `GATE_XS.md`, unchanged |
| Annualized one-way turnover | ≤ 400% | `GATE_XS2.md` — live-tradeability floor |
| Configurations evaluated against the test segment | recorded; **1** intended | `GATE.md` rule 2 |

Reported but **not** gating: max drawdown, per-quintile forward returns,
long-short spread, Pearson IC, naive t-stat — as in `GATE_XS.md`.

### The prediction, registered in advance

`GATE_XS_RESULT.md`'s xs40 run (47-name pool restricted to names listed by
2016-08, topk 10 / n_drop 2, **daily** rebalance, test segment
2024-01-16→2026-07-29) is the closest prior evidence available:

| | mean Rank IC | Rank ICIR | NW t-stat | excess ann. return (10bp) | IR post-cost |
|---|---:|---:|---:|---:|---:|
| xs40 (`GATE_XS_RESULT.md`) | 0.0334 | 0.1798 | 2.68 | +4.44% | 0.299 |
| gate bar (this file) | ≥0.02 | ≥0.20 | >2.0 | >0 | >0.5 |

xs40 cleared Rank IC and the NW t-stat; it missed Rank ICIR by a small,
noise-sized margin (0.1798 vs 0.20) and missed IR by a larger one (0.299 vs
0.5). This is a **directional prior, not a controlled comparison** — xs40's
numbers come from a different test window (2024-26, not 2022-23) and a
different, daily-rebalanced, topk-10-of-47 strategy. It is cited only because
it is the sole prior cross-sectional evidence that exists on this data.

**Prediction, registered before this run touches any data:** a wider universe
raises the statistical power of the cross-sectional IC estimate (sampling noise
falls roughly with `sqrt(n_names)`) and makes `topk` genuinely selective rather
than an index fund. The predicted effect is specifically on **Rank ICIR**
(statistical power) and **information ratio** (genuine selectivity from real
dropout, not from holding a fifth of the field) — not necessarily on Rank IC
itself, which measures something closer to raw ranking skill and has no obvious
reason to move with universe size alone.

## Mandatory dual reporting — pitwide vs allwide

The result **must** report every gating metric twice: on `pitwide`
(point-in-time, liquidity-ranked, top ~300 names, dated-interval membership —
see `edge/tools/qlib_ingest_wide.py`) and on `allwide` (every successfully
dumped single name in the wide pool, fixed span, no liquidity filter). This
mirrors how `GATE_XS.md` required xs47 and xs40 reported together, for the same
reason: `pitwide` is the primary hypothesis under test (breadth **and**
point-in-time selectivity together); `allwide` isolates breadth alone, without
the liquidity rule, as the comparison. Neither is chosen after seeing the
other's result — both are pre-registered here, before either has been run.

## Survivorship — read before trusting either universe

`pitwide`'s point-in-time liquidity rule is a real improvement over
`GATE_XS.md`'s hand-picked 47-of-60: membership at each month-end is decided by
a rule evaluated on data available at that date, not by a person in 2026
choosing names already known to have worked. That is worth having.

**It does not eliminate selection bias, and claiming survivorship is "fixed" is
FORBIDDEN in any writeup of this gate's result.** The candidate pool itself —
the 500–700 tickers `fetch_universe_wide.py` requests — is assembled in
**2026**, from tickers that exist in 2026. A company that delisted, went
bankrupt, or was acquired between 2016 and now is absent from the candidate
list entirely, and no yfinance pipeline can recover it after the fact. The
point-in-time rule governs *when* a surviving name enters the ranked universe;
it says nothing about the names that did not survive to be candidates in the
first place.

Required phrasing for the result writeup, verbatim: survivorship is
**"reduced via a point-in-time liquidity rule over a 2026-assembled candidate
pool; delisted names remain absent."**

## Rules

Carried verbatim from [`GATE.md`](GATE.md):

1. **No re-tuning against this holdout.** If any criterion fails, the
   hypothesis goes back for a fresh window or a fresh label — it does not get
   a second attempt on the same test segment.
2. **Record the trial count.** Any deflated statistic is only honest if the
   number of configurations searched is written down beside the result.
3. **This file does not get edited to fit a result.** Revisions are recorded
   here with a timestamp and a reason, *before* the next evaluation run — never
   after seeing its output.

## What passing authorizes

A pass authorizes **further research on the reserved 2024-2026 window, under a
new gate** — the confirmation cycle this gate deliberately did not spend. It
does **not** authorize live capital, and it does **not** unblock Step 8 / GPU
spend, which remain governed by `GATE.md`'s closed NO-GO and the user's
explicit go-ahead.

A failure means three independent paradigms have now failed on free daily
Yahoo data: an absolute per-symbol model (`GATE.md` / `GATE_RESULT.md`),
cross-sectional ranking on a narrow, survivorship-flawed universe
(`GATE_XS.md`), and cross-sectional ranking on a broad, point-in-time universe
(this gate). That is evidence about the **data** — free Yahoo daily bars, and a
candidate pool that can only ever be assembled from 2026, point-in-time rule or
not — not about model capacity. That conclusion is to be written down rather
than answered with a fourth model.

## Status

**Not yet evaluated.** Result will be recorded in `GATE_XS3_RESULT.md`.

---

*Simulated backtests only. Not financial advice.*
