# VWAP + Volume + Order-Flow System: Deep Evaluation

Date: 2026-09-01. Branch: `vpa/production-hardening`.
Scope: `research/state_estimation.py`, `research/systematic_execution.py`,
`research/vpa_*.py`, `research/volume_profile.py`, `research/flow_state.py`,
`daily_plays/absorption.py`, `research/regimes.py`, `tools/api_server.py`
(`_anchored_vwap_payload`, `_load_symbol_bars`), the data under `data/`, and a
new pilot study `research/vwap_pilot_study.py` run for this audit.

Bottom line first:

1. **The VWAP math is correct but the VWAP is anchored to nothing.** The API's
   "Session_Start" and "Event_Anchor" curves are anchored at bar 0, bar n/2 and
   bar 0.75n of whatever window was requested. There is no session reset, no
   session concept, and on the default daily bars the "session VWAP" is a
   multi-month cumulative average. This is the fabricated-data pattern the repo
   has already fought elsewhere.
2. **The data cannot support Parts 3 and 4 of the brief.** Everything on disk is
   yfinance: 1h bars (7 per session, ~730 days, 588 symbols) and daily bars.
   There are no trades, no quotes, no depth, no minute bars anywhere in `edge`
   or the sibling repos. Every "delta", "imbalance", "absorption" and "aggressor"
   number in the codebase is close-location-value times volume. The code labels
   this honestly; the dashboards do not always.
3. **A causal pilot on the 1h bars finds no directional information in session
   VWAP distance, crosses or acceptance**, in-sample or out-of-sample, in any
   volatility or trend regime, at any hour, on 119 symbols and 512k bar
   observations. Point estimates are 0–2 bp against 5–10 bp round-trip costs and
   every session-clustered 95% CI straddles zero.
4. **The one thing that does carry information is time-of-day-normalised
   relative volume, and what it predicts is the size of the move, not its
   sign.** Rest-of-session absolute move rises monotonically from ~44 bp at
   normal volume to ~96 bp above 3x slot volume. That is a usable input for a
   no-trade filter, barrier width and sizing. It is not an alpha.
5. **The existing walk-forward harness overstates its own precision** by
   treating 14,800 overlapping, cross-sectionally correlated observations as
   independent. The null it reported is still a null, but the same harness
   would also print "signal" on noise. Fix before trusting any future "signal"
   verdict from it.

The rest of this document is the evidence for those five statements, then the
proposed architecture, the test protocol for each candidate improvement, and a
staged roadmap.

---

## Part 1. VWAP implementation audit

### 1.1 What exists

| Location | What it does | Verdict |
|---|---|---|
| `research/state_estimation.py:415` `compute_anchored_vwap` | Cumulative VWAP from an anchor index, plus volume-weighted 1σ/2σ bands | Math correct |
| `tools/api_server.py:2177` `_anchored_vwap_payload` | Calls the above on `close` with anchors `[0, n//2, int(0.75n)]` | Anchors are fake |
| `research/systematic_execution.py:225` | Anchors at bar 0 and at gamma-flip crossings, keeps the **first** five | Wrong five |
| `research/vpa_*.py` | The whole VPA engine | Contains no VWAP at all |
| `dashboard/src/levelStructure.ts`, `RegimeView.vue`, `TrajectoryChart.vue` | Render the payload | Inherit the fake anchors |

### 1.2 Correctness

`compute_anchored_vwap` is a correct cumulative VWAP: Σ(p·v)/Σv from the anchor
forward, with weighted variance E[p²]−E[p]². Three small issues:

- **Price input.** The API passes `close`; the docstring suggests (H+L+C)/3. For
  1h bars, typical price is the better proxy for where volume traded. Choose one
  and state it in the payload.
- **Variance formula.** E[p²]−E[p]² suffers catastrophic cancellation when the
  cumulative sums are large relative to the variance. Fine for a $760 SPY over a
  session; fragile on high-priced names or long anchors. Use West's weighted
  incremental update (running mean and running M2). Cheap to change, removes a
  class of NaN/zero-band bugs.
- **Volume floor** `max(1e-4, v)` silently gives zero-volume bars a weight. It
  should skip them.

### 1.3 Session handling: the real defect

There is no session logic anywhere in the VWAP path.

- On the default `bars=daily` request, "Session_Start" is a cumulative VWAP
  over the whole requested window (e.g. 1y). That is not a session VWAP and not
  an anchored VWAP in any trader's sense.
- On `bars=1h`, the curve does not reset at 09:30. A "session VWAP" that carries
  yesterday's volume is a different object with different behaviour.
- The n/2 and 0.75n anchors are labelled `Event_Anchor_1/2`. No event is
  involved. Anyone reading the chart is being shown a made-up reference line.
- `systematic_execution.py:234` does `sorted(set(flip_crossings))[:5]`, which
  keeps the five **oldest** flip crossings and discards the recent ones that
  matter. Should be `[-5:]`.

Pre-market and after-hours: the data has none (yfinance regular hours, bars at
09:30..15:30, the last bar is 30 minutes). Nothing to handle today, but the
session model must have an explicit RTH/ETH flag before minute data arrives.

### 1.4 Which anchors are worth having

Keep the list short and only anchors with a mechanism behind them:

| Anchor | Mechanism | Keep? |
|---|---|---|
| Session (09:30 reset) | Institutional execution benchmark; the only VWAP with a documented behavioural reason to matter | Yes, primary |
| Prior-session high / low / close | Reference prices every desk uses; testable as level interaction | Yes, as levels, not VWAPs |
| Event-anchored (earnings, FOMC, gap open) | Cost basis of everyone who traded since the event | Yes, when an event calendar exists; test separately |
| Swing high / low anchored | Plausible but discretionary; anchor choice is a free parameter and invites overfitting | Only if a rule-based pivot (the repo's `find_pivots`) picks it |
| Weekly / monthly | On daily data these are just slow moving averages with volume weights; no distinct mechanism | No |
| Opening-range anchored | Redundant with session VWAP plus opening-range levels | No |

### 1.5 VWAP behaviour features (and what the pilot found)

The behavioural features the brief asks for were all implemented causally in
`research/vwap_pilot_study.py` and tested on 1h bars. Results are in Part 8.
Summary: distance, z-distance, crosses, time-on-side ("acceptance") and hour
of day carry no directional information at this resolution after clustering
by session. The features are worth keeping as *state descriptors* for the
confidence engine; they are not signals.

---

## Part 2. Volume and volume profile

### 2.1 Relative volume: a live defect in the VPA engine

`research/vpa_score.py:53` `bar_metrics` computes `vol_ratio` as the bar's
volume over the trailing 20-bar **mean**. On 1h bars that mixes slots: the
09:30 bar routinely carries two to three times a midday bar's volume, so
"ultra high volume" (2.0x) fires structurally at the open and "low volume"
(0.75x) fires structurally at 12:30–13:30. Every detector that gates
on `vol_ratio` (stopping volume, climaxes, no demand/supply, effort-vs-result,
absorption churn, breakout confirmation) inherits a time-of-day bias on the
intraday timeframes. The repo already has the right tool,
`research/microstructure.py:71` `compute_relative_volume(volume, time_of_day)`,
and `research/flow_state.py:139` `hourly_seasonal_adjust`; neither is used by
VPA.

Secondary: a mean baseline on a heavy-tailed series is dominated by the last
spike. Use the median (or a log-volume robust z) per slot.

### 2.2 Volume acceleration and "energy building"

Tested directly (Part 8, table H): slot-relative volume ≥ 1.5x with the
session range so far ≤ 0.7x its slot norm. The subsequent absolute move is
**smaller** (45 bp vs 49 bp), not larger, and the signed move is zero. On 1h
bars the compression-plus-volume hypothesis is not supported. It may still
hold at 1–5 minute resolution where the pattern is usually described; that is
untested because the data does not exist here.

### 2.3 Volume profile

Two implementations exist and they disagree:

- `research/vpa_levels.py:455` `compute_vap`: uniform distribution of each
  bar's volume across its high–low range, 24 bins, POC, 70% value area by
  expanding from POC. Correct and the D6 fix was right.
- `research/volume_profile.py`: triangular kernel with the mode at the close.
  Also defensible, arguably better.

Pick one, and make the bin count price-relative (ATR-scaled, not a fixed 24
over an arbitrary window) so a 300-bar window and a 60-bar window produce
comparable nodes. Predictive value of POC/VAH/VAL interaction is untested;
Part 9 gives the protocol. Note that on hourly and daily bars the profile is a
smoothed price histogram; the low-volume-node "air pocket" idea depends on
intra-bar prints that these bars do not have.

---

## Part 3. Order flow and microstructure: what is actually measurable

Data inventory, verified on disk:

| Data | Present | Consequence |
|---|---|---|
| 1h OHLCV, 588 symbols, 2023-10 to now | Yes (yfinance, `auto_adjust=True`) | Session features possible at coarse resolution |
| Daily OHLCV, ~560 symbols, 10y | Yes | Regimes, levels, daily studies |
| Minute bars | No | Cannot test intraday VWAP behaviour as traders describe it |
| Trades with aggressor side | No | No CVD, no delta, no large-trade detection |
| Quotes (NBBO) | No | No spread, no quote imbalance, no tick-rule classification |
| Depth (L2) | No | No book imbalance, no spoofing/iceberg analysis |
| Option chains (26 daily snapshots) | Yes, from 2026-08-07 | Dealer-gamma regime only; no aggressor |

What the code calls "signed flow" (`flow_state.signed_volume_proxy`,
`absorption.observations_from_bars`, `build_orderflow_matrix`) is
`((2C−H−L)/(H−L))·V`. It is the bar's close location times its volume. It is
mechanically correlated with the bar's own return, so any "delta divergence"
against price is largely a divergence of price against a transform of price.
The modules say so in their docstrings; the dashboard cards that show "BUY /
SELL side", "delta", "imbalance" should say so on the card.

Order-book features: `tools/api_server.py:189` already states "no order-book
depth anywhere in this repo". Nothing to audit; nothing to promise.

Verdict for Part 3: **not testable with current data.** The honest options are
(a) acquire minute bars plus trades and quotes for a small universe and test,
or (b) drop order-flow language from the product until (a) happens. The
robustness ranking the brief asks for, based on the microstructure literature
and on what survives in practice, is in Part 9 as hypotheses to test, not as
claims.

One further caveat that affects everything: `auto_adjust=True` means the 1h
and daily prices are dividend-adjusted retroactively. Adjusted prices drift
away from the prices that actually printed, so round-number and prior-level
logic is off by the adjustment factor, and the whole history shifts every
ex-dividend date. Store raw prices and adjust in the feature layer.

---

## Part 4. "Something is building": tested, not supported at 1h

See 2.2 and Part 8 table H. Absorption as the brief defines it (large
aggressive flow, no price progress) requires an aggressor side; the proxy in
`daily_plays/absorption.py` cannot distinguish "sellers hit bids and were
absorbed" from "the bar closed near its low". Divergence tests (price vs CVD,
price vs book imbalance) are blocked on the same data gap. Price-vs-VWAP
divergence is testable and was tested: null.

---

## Part 5. Regime detection

`research/regimes.py:10` `classify_regimes` is a clean, causal implementation:
20-day realised vol bucketed by expanding terciles, trend vs a 60-day mean,
drawdown-based bear flag. It is not wired into the VPA scoring or the VWAP
endpoints. The pilot used a comparable split (trailing 140-bar hourly vol
terciles, 20-day trend sign) and found no regime in which VWAP distance
becomes informative (Part 8, tables D and D2). The mid-vol / up-trend
bucket for z in 1..2 prints −2 bp with a CI that just excludes zero; with 24
cells tested that is what a false positive looks like, and it is below cost
anyway.

Recommended regime frame (all causal, all already computable from daily bars):

1. Volatility: realised vol tercile (existing) plus VIX term-structure slope
   when the vol-complex fetch is present.
2. Trend: sign and t-stat of the 20/60-day return; `kalman_trend.py` slope as an
   alternative with a single smoothing parameter.
3. Mean reversion vs persistence: variance ratio or lag-1 autocorrelation of
   1h returns over the trailing 20 sessions.
4. Liquidity: `flow_state.amihud_illiquidity` and `corwin_schultz_spread` (bar
   based, causal, already implemented).
5. Expansion: today's range so far vs slot norm (the pilot's `range_ratio`).

Regime membership should be an evaluation slice and a feature, never a
separate rulebook, until a slice shows a stable, cost-covering difference
across at least two rolling origins.

---

## Part 6. Confidence engine: what to keep from the current one

`vpa_score.score_evidence` produces `direction`, `primary_probability_pct`
(logistic on ledger balance, squashed to 50–80), and a `confidence` block.
Problems:

- Probability and confidence are near-duplicates. `agreement` in
  `compute_confidence` is |bull−bear|/(bull+bear), which is the same quantity
  the probability is a logistic of. The other confidence components (bar
  count, recency, evidence density, downgrade) describe data quantity, not
  predictive reliability.
- The probability is not calibrated and the doc says so; the OOS reliability
  table is non-monotonic (62–67% bucket hits 49.1%, 56–61% hits 50.6%).
- `SIDEWAYS` is the only no-trade path and it is a ±3.5% band around p=0.5,
  which the ledger rarely lands in.

Keep: the signed evidence ledger with citations, the em-dash-for-missing rule,
the explicit `bars_meta` honesty block. These are the right skeleton for the
output format in the brief.

Target output contract (deterministic, every number traceable):

```
regime:            {vol: mid, trend: up, persistence: mean_reverting, liquidity: normal}
horizon:           rest of session (next 3 bars)
p_up / p_down:     calibrated, from a logistic/GBM model, with the model's OOS Brier
p_no_trade:        1 − max(p_up, p_down) below the cost-covering threshold, OR
                   forecast |move| < 2x round-trip cost
expected |move|:   from the relative-volume / realised-vol model (this is the part
                   the pilot shows is forecastable)
evidence_for / evidence_against: ledger items, each with its feature value and
                   its marginal contribution in the model
confidence:        width of the bootstrap interval on p, NOT a data-quantity score
```

No-trade is the default state. A directional state requires p above the cost
threshold **and** expected |move| above 2x cost **and** the model's OOS
calibration within tolerance for that regime slice.

---

## Part 7. Feature architecture

Everything below is causal by construction (uses bars ≤ t) and is implemented
or trivially implementable from `research/vwap_pilot_study.py` and
`research/flow_state.py`:

| Group | Features | Status |
|---|---|---|
| Price | r_1, r_3, r_session-so-far; range so far / slot norm; realised vol 20-session; gap vs prior close | Pilot |
| VWAP | session VWAP (HLC/3), z-distance, bp-distance, bars on side, cross flags, VWAP slope over last 3 bars | Pilot |
| Volume | slot-relative volume (median, exclusive), cumulative session volume vs norm, log-volume robust z | Pilot / `microstructure.py` |
| Flow proxy | CLV·V and its session cumulative; label as proxy | `flow_state.py` |
| Structure | pivot-cluster levels with touch counts (`vpa_levels`), distance to nearest level in ATR, VAP POC/VAH/VAL distance | `vpa_levels.py` |
| Regime | vol tercile, trend sign/t-stat, variance ratio, Amihud, Corwin–Schultz | `regimes.py`, `flow_state.py` |

Leakage rules to enforce in code, not in review: every feature function takes
`bars[:t]`; every baseline is `shift(1)` before `rolling`; pivots require the
right-confirmation window to have elapsed; profiles are built on the window
ending at t−1. Add a property test that perturbs bars after t and asserts
features at t are unchanged (the repo already has this pattern in
`test_backtest_reads_cannot_see_the_future`).

---

## Part 8. Is there an edge? Pilot results

Script: `research/vwap_pilot_study.py`. Run:
`python3 -m research.vwap_pilot_study --symbols 120 --json runs/vwap_pilot.json`.
Universe: SPY, QQQ, IWM plus the first 116 symbols alphabetically with a full
1h history (no selection on outcome). 119 symbols, 736 sessions
(2023-09-14 → 2026-08-31), 512,065 bar observations. OOS = sessions after
2025-06-25 (last 40%). All CIs are 95% cluster bootstraps over sessions.
Targets: `ret1` = next bar close-to-close; `ret_eod` = close to session's last
close. Costs not subtracted; compare magnitudes to a 5–10 bp round trip.

Unconditional: ret1 +0.02 bp, ret_eod −0.31 bp.

**A/B. VWAP z-distance → direction: null.**

| z bucket | n | ret1 bp [CI] | ret_eod bp [CI] |
|---|---|---|---|
| < −2 | 53k | −0.8 [−2.4, 0.7] | −0.4 [−4.8, 3.8] |
| −2..−1 | 86k | −0.1 [−1.4, 1.0] | +0.3 [−2.5, 3.0] |
| −0.5..0.5 | 66k | +0.4 [−0.6, 1.4] | −0.4 [−2.3, 1.6] |
| 1..2 | 91k | −0.5 [−1.6, 0.6] | −1.2 [−3.7, 1.2] |
| > 2 | 54k | +1.1 [−0.6, 3.2] | −0.3 [−4.2, 4.3] |

No monotonic pattern, no bucket clears cost, no bucket's CI excludes zero.
The same holds in-sample and out-of-sample (table C), in all three vol
regimes and both trend regimes (D, D2), and at every hour (E). The early-session
z < −1 buckets show +2 to +4 bp point estimates with CIs of ±8 bp: not evidence.

**F. Crosses: null.** cross_up next bar +0.8 bp [−0.8, 2.9]; cross_dn −0.7 bp
[−2.0, 0.6].

**G. Acceptance (bars on the same side): null.** 4+ bars above VWAP → rest of
session −1.5 bp [−3.3, 0.5]; 4+ bars below → +0.2 bp [−2.1, 2.1].

**H. Compression + volume: not supported.** |ret_eod| 45.5 bp when "building"
vs 49.0 bp otherwise; signed 0.0 bp.

**I. Slot-relative volume → magnitude: strong and monotonic.**

| rvol_slot | n | \|ret_eod\| bp [CI] | signed bp |
|---|---|---|---|
| < 0.5 | 20k | 48 [46, 51] | −0.2 |
| 0.8–1.2 | 152k | 44 [43, 45] | −0.2 |
| 1.2–2 | 107k | 52 [50, 54] | −0.4 |
| 2–3 | 27k | 67 [64, 71] | −0.4 |
| > 3 | 12k | 96 [91, 103] | −0.1 |

This is the one robust finding: abnormal slot volume forecasts the size of
the remaining session move, with no directional content. It belongs in the
no-trade filter, the barrier width and position sizing.

**J. Interaction z × rvol:** a weak hint that deep-below-VWAP on very quiet
volume drifts up (+3 bp [−0.8, 7.0]) and on very heavy volume continues down
(−5 bp [−15, 6]). Both CIs include zero. Worth a pre-registered retest on
minute data, not worth acting on.

**K. Index ETFs alone:** same picture; the one cell outside zero (z in
−1..−0.5, +4 bp [0.4, 8.4]) is one of seven buckets and below cost.

Interpretation. Session VWAP on hourly bars is a 7-point series per day; the
behaviour traders describe (reclaims, rejections, mean reversion of extended
moves) happens on a 1–5 minute clock and the hourly sampling averages it away.
The test cannot see it; it also cannot confirm it. What it does show is that
the crude "distance from VWAP" indicator, as currently drawn on the dashboard,
should not be presented as having directional meaning.

### 8.1 Defects in the existing walk-forward harness (`research/vpa_backtest.py`)

The VPA validation doc's numbers (50.1% vs 50.2% expected, ±0.7%) are directionally
right and the null stands, but the harness itself needs fixing before its verdict
logic is trusted:

1. **Independence assumption.** SE = sqrt(0.25/n) with n = pooled rows. Stride 4
   with horizon 10 makes consecutive rows share 60% of their forward window, and
   60 symbols on the same date share the market move. Effective n is several
   times smaller; the pilot's session-clustered CIs are 3–5x wider than the
   binomial ones. Use a block bootstrap over dates.
2. **Purge is in rows, not time.** `purge_from/to = split ± horizon` counts pooled
   observations. With 60 symbols per date, ten rows is a fraction of one day.
   The embargo is effectively zero. Purge by date: drop every observation whose
   forward window ends after the cut, and embargo `horizon` **bars** after it.
3. **Single origin.** One 60/40 cut. Use at least 3–5 rolling origins and report
   the dispersion.
4. **Cost-free.** Signal quality only, stated honestly. Every table should carry
   a "net of X bp" column so nobody has to do the subtraction.
5. **Hit rate on skewed returns.** The pilot's rest-of-session hit rates sit at
   0.40–0.47 for *every* bucket because the distribution is left-skewed; hit
   rate vs 50% is misleading. Report mean and a base-rate-adjusted hit rate.
6. **Cost of one read.** Each observation re-runs pivots, clustering, VAP and
   the full ledger on a growing window; the 60-symbol run is slow enough that
   nobody will sweep horizons. Compute features incrementally.

---

## Part 9. Machine learning: not yet

The rule in the brief is right: no model until a feature shows information.
Today one feature does (slot-relative volume → magnitude), and it is a
variance feature. The appropriate first model is therefore a **magnitude
model**, not a direction model:

- Label: |ret_eod| or the first-passage of a vol-scaled barrier (triple-barrier
  with barriers at k·σ_slot, k chosen for a 2:1 cost cover).
- Baseline: quantile regression or a small GBM on {rvol_slot, range_ratio,
  rvol20, hour, regime}. Evaluate with pinball loss vs the unconditional
  quantile and with the realised coverage of the predicted barrier.
- Direction: logistic regression on the same features plus VWAP z, crosses,
  level distance. Expect Brier ≈ base-rate Brier. Report it anyway; it is the
  honest "no edge" number for the direction leg and the reason the engine
  emits no-trade.
- Calibration: reliability curve, Brier, ECE with ≥ 20 obs per bin, computed
  only on OOS folds with date-purged CV.

Order-flow ML is off the table until trades and quotes exist.

Hypothesis ledger to pre-register (each with entry, horizon, metric, kill rule):

| # | Hypothesis | Entry | Horizon | Metric | Kill if |
|---|---|---|---|---|---|
| H1 | Session VWAP z is informative at 5m resolution | \|z\| > 2 at bar t | 15/30/60 min | mean net return, cluster-bootstrap CI | CI includes 0 in 2 of 3 origins |
| H2 | VWAP reclaim after a ≥1σ excursion continues | close crosses back within 3 bars | to session end | same | same |
| H3 | Slot rvol forecasts \|move\| at 5m | continuous | 30/60 min | pinball loss vs unconditional | improvement < 5% |
| H4 | Compression + rvol precedes expansion at 5m | rvol ≥ 1.5, range ≤ 0.7 | 60 min | \|move\| ratio vs rest | ratio < 1.1 |
| H5 | Tick-rule CVD divergence from price predicts reversal | CVD slope and price slope disagree over 20 bars | 30 min | net mean, hit vs base rate | below cost |
| H6 | Absorption (large signed flow, no progress) precedes reversal | signed-flow z > 2, \|Δp\| < 0.3 ATR | 30 min | same | same |
| H7 | Quote imbalance predicts next-bar sign | QI > 0.3 | 1–5 min | AUC vs 0.5 | AUC < 0.53 |
| H8 | POC/VAH/VAL touch behaviour differs from random level | first touch of the session | 30 min | net mean vs matched random price level | no difference |

Robustness ranking to expect from the literature, for planning only: quote
imbalance and signed-flow persistence are the most robust short-horizon
features and decay within minutes; visible depth beyond the top of book is
unreliable (cancellation, spoofing); large-trade detection is noisy on the
consolidated tape because of odd-lot and dark prints; volume-profile levels
are weakly better than random levels in most published tests. All of that is
to be measured, not assumed.

---

## Part 10. Gemini

Not for the signal path, and not now. The deterministic pipeline has no
component where an LLM outperforms code, and the repo already carries one
non-reproducible term in the VPA ledger (`vision_agreement`, weight 0.20,
from `call_gemini_vision`). In "fused" mode that term changes the probability
between two runs on identical bars. Remove it from any path that feeds a
number, or fix its weight to zero until it is validated like every other
feature (it can be: label its directional read on the backtest windows and
score it in the same harness).

A justified use exists later, off the hot path:

1. Input: headline text and filing snippets for the symbol, plus the model's
   structured state (regime, p_up, p_down, expected move, evidence lists).
2. Task: classify the event type (earnings, guidance, M&A, macro, regulatory,
   none) into a fixed enum, and render the structured state as a short
   explanation.
3. Why an LLM: unstructured text classification and prose generation are
   things regexes and rules do badly; nothing numeric is delegated.
4. Latency: seconds; acceptable because it never gates an order.
5. Cost: per call on text; negligible against data costs; batch by symbol.
6. Hallucination control: the output is a schema (enum plus citations to the
   supplied text); the explanation may only reference numbers present in the
   input JSON; a validator rejects anything else; the event enum is a feature
   whose value is tested like any other (H9: post-event behaviour differs by
   class).
7. Validation: agreement with a hand-labelled sample; the feature's marginal
   contribution in the OOS model.

---

## Part 11. Architecture audit, recommended architecture, roadmap

### 11.1 Audit findings (ranked)

1. Fake VWAP anchors in `_anchored_vwap_payload`; no session reset; wrong
   five flip anchors in `systematic_execution.py`. Correctness.
2. Time-of-day bias in every VPA volume detector on intraday timeframes
   (`vpa_score.bar_metrics`). Feature construction.
3. Order-flow language on bar-only proxies in dashboard cards. Honesty.
4. Walk-forward SEs, purge and single origin (Part 8.1). Validation.
5. `auto_adjust=True` history and a live spot row appended to cached frames in
   `_load_symbol_bars` (the last bar's close is overwritten by a quote with a
   different timestamp basis; any feature computed on that frame is
   inconsistent between the research path and the API path). Data integrity.
6. Probability/confidence redundancy and uncalibrated probability presented as
   a percentage (already disclaimed in text; the number is still on the card).
7. Non-deterministic vision term in the fused ledger.
8. Performance: whole-window recomputation per read; Python loops over bars
   in every feature; fine for one symbol, hostile to research sweeps.
9. Fragile dependency: yfinance is the only price source, unofficial,
   rate-limited, retroactively adjusts, and caps 1h history at ~730 days. The
   deletion or change of that endpoint stops the whole platform.

### 11.2 Recommended architecture

```
Market data (bars now; trades+quotes later)      ──► raw store (unadjusted, tz-aware, session-tagged)
        │
        ▼
Validation / normalisation  (gaps, duplicates, zero volume, session calendar, adjustment factors kept separately)
        │
        ▼
Feature engine  (incremental, per symbol, per session; every function takes bars[:t]; slot baselines shift(1))
   ├─ price / volatility          ├─ session + event VWAP, bands, z, crosses, time-on-side
   ├─ slot-relative volume        ├─ structure: pivot levels, VAP, distance in ATR
   └─ flow proxy (labelled proxy) └─ regime: vol tercile, trend, variance ratio, liquidity
        │
        ▼
Probability engine  (magnitude model first; direction model second; both calibrated on date-purged OOS folds)
        │
        ▼
Decision  (no-trade default; directional only if p > cost threshold AND E|move| > 2x cost AND calibration OK in regime)
        │
        ▼
Risk filter  (regime veto, event veto, max exposure)  ──►  BUY / SELL / HOLD / NO TRADE
        │
        ▼
Ledger  (every feature value, model version, p, decision, realised outcome) ──► research DB used by the harness
```

The harness reads the same ledger the live path writes, so research and
production cannot diverge on feature definitions.

### 11.3 Roadmap

**Phase 1 — VWAP + volume features, on the data that exists (1–2 weeks).**
Fix the anchor endpoint (session reset on 1h, real anchors, drop the fake
ones, correct the flip-anchor slice). Add slot-relative volume to VPA and
re-run its walk-forward. Fix the harness (date-cluster bootstrap, time purge,
rolling origins, cost column). Promote `vwap_pilot_study.py` to the harness.
Exit criterion: the dashboard shows no reference line that is not defined by
a session or an event; every VPA detector uses slot-normalised volume.

**Phase 2 — Regime layer (1 week).** Wire `classify_regimes` and the
variance-ratio / liquidity features into the ledger as slices and features.
Exit criterion: every harness table is reported per regime with CIs.

**Phase 3 — Data acquisition and order flow (blocked on data).** Minute bars
plus trades and quotes for a 20–50 symbol universe (SPY/QQQ plus liquid
names). Implement tick-rule / bulk-volume classification, CVD, quote
imbalance, slot volume at 1m. Run H1–H8 as pre-registered tests. Exit
criterion: at least one hypothesis clears cost with CIs excluding zero in 2 of
3 rolling origins, or the order-flow layer is formally shelved.

**Phase 4 — Probability engine (2 weeks, after Phase 3 or on bars-only
features if Phase 3 is shelved).** Magnitude model, then direction model,
both calibrated; decision rule with no-trade default; ledger writing.

**Phase 5 — Validation (1–2 weeks).** Rolling-origin walk-forward, date-purged
CV, regime slices, cost stress (the repo's `robustness.monte_carlo_robustness`
already does cost stresses and concentration checks), deflated Sharpe with the
trial count recorded, reliability curves. Use the pre-registered GO/NO-GO
format in `docs/GATE.md`.

**Phase 6 — Paper trading (≥ 3 months).** Live feature ledger vs research
ledger reconciliation daily; calibration drift monitoring; no discretionary
overrides.

**Phase 7 — Production.** Only on a passed gate, with the same code path.

### 11.4 What to stop presenting

Until the corresponding hypothesis passes: "delta", "aggressor", "absorption
side", "imbalance" on bar data; the anchored VWAP curves as currently
anchored; the VPA percentage as a probability; "energy building" reads.

---

## Appendix: files touched by this audit

- New: `research/vwap_pilot_study.py` (reproducible pilot; run as a module).
- New: this document.
- No production code was changed in the audit pass. Fixes were applied in the
  remediation pass below.

---

# Remediation pass (same day)

Four parallel workers plus a coordinator applied the fixes. Test state after:
**1984 passed, 2 failed** across the suite before remediation of the two
failures; both were then resolved or attributed (see "Test state" below).
`tests/test_vpa_engine.py` was deliberately left untouched by every worker and
used as the shared regression tripwire; it was verified unmodified since
2026-08-31 and stayed green throughout.

## What was fixed

### VWAP anchoring (`state_estimation.py`, `systematic_execution.py`, `api_server.py`)
- Fabricated anchors removed. `_anchored_vwap_payload` no longer anchors at
  bar 0 / n/2 / 0.75n under session and event labels. Intraday now returns a
  true session VWAP that resets at each session boundary, plus a prior-session
  curve truncated at today's open so it cannot absorb today's volume. Daily
  returns rule-based swing-pivot anchors and 52-week high/low, each with
  `anchor_kind`, `anchor_timestamp` and an honest label, and omits any anchor
  it cannot establish with a stated reason rather than inventing one.
- A `window_start` base anchor was added by the coordinator after the worker's
  first pass returned zero anchors on short or monotonic series, which left the
  chart with no reference line. It is the cumulative VWAP of the displayed
  window, anchored at bar 0, explicitly labelled as *not* a session VWAP and as
  making no support/resistance claim. The original defect was the mislabelling,
  not the act of anchoring at the first bar.
- Anchors resolving to the same bar are collapsed into one curve carrying an
  `also_marks` list, so a swing high that is also the 52-week high draws once
  and does not imply two independent confirmations.
- Flip anchors in `systematic_execution.py` now keep the four **most recent**
  gamma-flip crossings plus bar 0. The old `[:5]` kept the five oldest and
  discarded every recent one.
- Band width now uses West's incremental weighted variance instead of
  `E[x²]−E[x]²`, which loses precision to cancellation on high-priced series.
- Zero, negative and non-finite volume bars no longer drag the VWAP; a bar with
  no positive volume since its anchor is NaN, not a fabricated value.
- Price basis is typical price (H+L+C)/3 where available, and the payload now
  states which basis was used.

### An unplanned data-integrity defect found during the VWAP work
`_load_symbol_bars` selected whichever file had the latest timestamp string
across the hourly and daily tiers, ignoring `prefer_intraday`. Because
`"...15:30:00" > "...00:00:00"`, **any request for daily bars was silently
served hourly data whenever the market had traded that day.** This also
affected the changepoint endpoint, whose own docstring states it requires daily
bars. Fixed by selecting the cadence family first and only falling back to the
other family when the preferred one has no file for the symbol.

### VPA volume time-of-day bias (`vpa_score.py`, `vpa_thresholds.py`)
Intraday `vol_ratio` and `spread_ratio` baselines are now the trailing median
of the **same session slot** over prior sessions, exclusive of the bar being
judged, with a graceful fallback to the legacy trailing baseline when slot
history is short. Daily and weekly paths are byte-identical to before.
Measured effect on real 1h data, count of bars tripping the 2.0x
"ultra-high volume" gate at the opening slot:

| Symbol | Before | After |
|---|---|---|
| SPY | 5 | 0 |
| AAPL | 23 | 4 |
| QQQ | 33 | 5 |
| TSLA | 34 | 6 |

Mean `vol_ratio` per slot for SPY flattened from 1.57 at the open against
0.65–0.91 midday, to 0.90–0.99 across every slot.

### Walk-forward harness statistics (`vpa_backtest.py`)
- Binomial `sqrt(0.25/n)` replaced by a bootstrap resampling whole `as_of`
  dates, applied to every headline statistic. The naive figure is retained but
  relabelled as understated.
- The purge is now date-based with a real embargo. The old row-based purge
  dropped a fraction of one trading day when 60 symbols shared each date.
- Rolling origins (default 4) replaced the single split, and a "signal" verdict
  now requires agreement across all origins.
- Added `--cost-bp` with net columns, and made a continuous
  direction-signed excess return the primary statistic instead of a hit rate
  that left-skewed returns make hard to read.
- Added `--jobs` for per-symbol parallelism.

Two findings from the corrected harness. On the documented 60-symbol
configuration all four origins report no edge, so **the original null is robust
to the corrected statistics** — it got stronger, not weaker. On a 12-symbol
large-cap universe three of four origins report signal and one does not, which
the harness now correctly refuses to call an edge; the old single-split view
would have called it signal outright.

### Reproducibility and honesty (`vpa_engine.py`, dashboard)
- The Gemini vision read no longer enters the scored evidence ledger by
  default, so two runs over identical bars now produce identical probability
  and confidence. It is surfaced as its own block with an
  `agrees_with_quantitative` flag. The old fused behaviour is opt-in and stamps
  the response `deterministic: false` / `reproducible: false`. Image-only
  requests are always stamped non-deterministic. The API server does not pass
  the opt-in, so production already gets the reproducible path.
- Proxy disclosure added to the absorption and flow-state views, where
  close-location-value proxies were displayed under order-flow labels. Tracing
  confirmed the options flow tape and dealer-gamma surfaces are genuinely
  measured and were correctly labelled already.

## New capability: causal feature engine and magnitude model

- `research/session_features.py` — pure, causal, session-aware features
  (session VWAP and its z-distance, crosses, acceptance, slot-relative volume,
  range ratio, realised vol, and a clearly-named bar-geometry flow proxy).
  Targets live in a separate function so a target cannot reach a model as a
  feature. `assert_causal` is an executable leakage guard that perturbs the
  future and asserts the past does not move; it is anchored to a timestamp
  rather than a row position, and it runs against real SPY bars in the tests.
- `research/magnitude_model.py` — conditional quantile model of the remaining
  session move, with session-grouped folds, a session embargo, rolling origins
  and session-clustered bootstrap intervals. Includes `no_trade_filter`.

Results on 40 symbols, 746 sessions, 202k rows, four rolling origins:

| Measure | Result |
|---|---|
| Median-quantile skill vs trailing unconditional quantile | +0.099, +0.103, +0.114, +0.117 |
| Spearman, predicted vs realised magnitude | 0.43 to 0.46 |
| Absolute-error improvement | 4.64 bp, CI [4.24, 5.09] |
| Quantile calibration (0.25 / 0.5 / 0.75 / 0.9) | 0.251 / 0.497 / 0.740 / 0.892 |

Calibration is close to exact and skill is positive at every origin. The
no-trade filter, at a 16 bp hurdle, vetoes 2.6% of bars; those bars went on to
move 18.0 bp [16.0, 20.3] against 63.9 bp [55.6, 77.5] for the bars it allowed,
and the intervals do not overlap.

### A correction to Part 8 of this audit

An ablation was run to test whether relative volume is really the driver, and
it is **not**. On 15 symbols and two origins, absolute-error improvement by
feature set:

| Feature set | Skill by origin | Abs-error improvement |
|---|---|---|
| Relative volume only | +0.015, +0.017 | 0.95 bp [0.75, 1.14] |
| Realised volatility only | +0.068, +0.098 | 4.85 bp [4.34, 5.36] |
| Volatility + session geometry | +0.118, +0.147 | 7.70 bp [7.10, 8.40] |
| Volatility + geometry + relative volume | +0.129, +0.157 | 8.33 bp [7.71, 8.99] |

The headline claim in Part 8 — "slot-relative volume forecasts the size of the
remaining move" — is **largely confounded by volatility regime**. High-volatility
names carry both elevated volume and larger moves, and the marginal table in
Part 8 table I could not separate the two. Volatility level and how much
session remains do most of the work. Relative volume adds a small but
consistent increment on top (about +0.6 bp of absolute-error improvement,
positive at both origins), and `range_ratio` adds about the same.

This does not change any directional conclusion, and it does not make the
magnitude model less useful — a well-calibrated volatility-and-geometry
forecast is exactly what a barrier width and a no-trade hurdle need. It does
mean the relative-volume finding should be described as a modest contributor,
not as the effect.

## Test state

- Full suite: 1984 passed at the point of the remediation review, with
  `tests/research/test_optimizer.py` and `tests/research/test_xs5_runner.py`
  uncollectable because `cvxpy` is not installed (pre-existing, unrelated).
- `tests/test_api_server_symbol_bars.py::test_microstructure_endpoints_succeed_for_fallback_symbol`
  failed after the first VWAP pass and was fixed by the `window_start` anchor.
- `tests/research/test_options_experimental.py::test_unbiased_gex_profile`
  fails **only inside the full-suite run** and passes alone and as a whole
  file. `research/gex_model.py` has no intra-repo imports, holds no module
  state and copies its input, and was not touched by this work, so this is
  pre-existing order-dependent test pollution that the newly added test files
  may have re-ordered into view. It is not caused by any change here and is
  logged as a separate defect to chase.
- New tests added: `tests/test_anchored_vwap_sessions.py`,
  `tests/test_vpa_volume_normalisation.py`,
  `tests/test_vpa_backtest_statistics.py`,
  `tests/test_vpa_vision_determinism.py`,
  `tests/research/test_session_features.py`.

## Still open

1. `docs/VPA_VALIDATION.md` describes the old naive standard error, the old
   row-based purge and a single split. Its headline conclusion is unchanged and
   now better supported, but the method section is stale.
2. The live-spot row appended inside `_load_symbol_bars` still overwrites the
   last bar's close with a quote on a different timestamp basis, so the research
   and API paths can disagree on the final bar.
3. ~~`dashboard/src/views/RegimeView.vue` substitutes a hardcoded GEX-by-expiry
   table when the API returns none.~~ **Fixed — see "Regime workstation
   fabricated data" below.** One residual item remains: `VolatilitySurface3D`
   (item 6 there).
4. `research/session_features.py` and the array-level session VWAP in
   `research/state_estimation.py` are two implementations of the same idea. They
   should be reconciled, or a cross-check test added asserting they agree
   numerically, before either is trusted in production.
5. Order-flow work (Part 3, Part 4, hypotheses H5–H8) remains blocked on
   acquiring minute bars plus trades and quotes.

---

# Regime workstation fabricated data (same day, follow-up)

Flagged during the vision/proxy work as one defect in one computed property.
Tracing it found **seven**, spanning the view and three of the charts it feeds.
They compounded: two of them would have silently defeated a fix applied only to
the view, because a chart handed an honest empty array manufactured its own
replacement data.

| # | Location | What it fabricated |
|---|---|---|
| 1 | `RegimeView.expiryFlowRows` | Five hardcoded expiries (`'May 17'`, `$412.5M`, …) whenever the API had no `gex_by_expiry` |
| 2 | `RegimeView.strikeOiRows` | Open interest derived from gamma as `abs(call_gex_m \|\| 10) * 850`, rendered as contract counts |
| 3 | `RegimeView.timeSeriesPoints` | `?? 525` spot for any symbol missing price history |
| 4 | `RegimeView.timeSeriesPoints` | `total_gex_m * 25` published as order-flow "volume delta" — a series this repo has no data for at all |
| 5 | `NetGammaSpotTimeSeries` | An entire synthetic intraday session: 15 hardcoded clock times, a hand-drawn gamma arc, a `sin()` price walk off a 525 spot, and `sin()` volume bars |
| 6 | `StrikeOpenInterestChart` | An 11-strike OI ladder built with `Math.random()`, so the fake numbers changed on every render |
| 7 | `StrikeGammaExposureChart` | An 11-strike dealer-gamma ladder shaped by `140 * exp(-dist * 18)`, plus OI derived from it |

Also fixed: a `'May 17 Exp'` default expiry label, and a chart subtitle (also
its aria-label) asserting "Highest OI concentration at 525C and 520P" whenever
the walls were unknown — a fabricated fact read aloud to screen readers.

All now return empty and render an em dash with a plain-language reason,
matching the repo convention that a missing number is never drawn as a
plausible one.

**Not fixed, and it is the largest remaining one.** `VolatilitySurface3D` on
the same view takes no data input whatsoever. It synthesises its entire surface
from a closed-form `ivAt()` skew formula around spot, so the "3D Vol Surface"
panel has never shown measured implied volatility for any symbol. Making it
honest means wiring a real IV surface source, which is a feature rather than a
bug fix, so it is logged rather than patched. Until then it should not be read
as data.

`GexFlowVisual.vue` was examined and deliberately left alone: it is a
marketing/paper surface used only by the landing page, and its own conformance
test documents its illustrative numbers as intentional.

**Regression guard.** `dashboard/src/__tests__/regime-no-fabricated-data.test.ts`
(23 assertions) pins every one of the above. This matters more than usual here
because the failure mode is silent — the charts render perfectly either way,
and a test asserting on rendered output cannot tell fabricated data from real
data. The guard was negative-controlled: reintroducing the original hardcoded
array verbatim makes it fail, and removing it makes it pass again.

Dashboard suite after: **2200 tests across 103 files, all passing**, and
`vue-tsc --noEmit` clean.
