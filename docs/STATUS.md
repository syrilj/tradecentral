# edge/ status — 2026-07-29 / continued 2026-07-30

Source of truth for the plan: [`PLAN.md`](PLAN.md). Pre-registered GPU trigger:
[`GATE.md`](GATE.md). Honest audit: [`AUDIT.md`](AUDIT.md).

## Wave completion

| Step | Goal | Status | Evidence |
|---|---|---|---|
| **1** | Leak-free eval harness + property test | **DONE** | `edge/eval/{harness,conformal,test_no_lookahead}.py`; `pytest edge/eval` → 3 passed |
| **2** | Fix Kronos bakeoff + supersede contaminated reports | **DONE** | `Kronos/bakeoff_trend_v5.py` `hist_closes_asof` uses `timestamps < asof`; regenerated `TREND_V5_REPORT.md` + archive; `edge_filter.WINRATE` flagged UNVERIFIED (source artifact unrecoverable); `verify_no_lookahead.py` exit 0 shows fixed bakeoff ≈ coin flip |
| **3** | One comparable evidence base / leaderboard | **DONE** | `TradingAlgoWork/LEADERBOARD.json` — 10 priority models under cash=$1k, same universe/window/costs |
| **4** | Port v90 champion into `edge/models/v90/` | **DONE** | Bundle + MODEL.md; Sharpe n&lt;50 nulled; default OP pre-registered as `balanced_top5`; runtime gate fixed to `_enter_hi` |
| **5** | Widen universe (≥40 symbols, multi-regime, refit) | **DONE** | 59/60 1h symbols in `edge/data/1h/`; 10y daily in `edge/data/1d/`; re-fit → `edge/models/v90_wide/` |
| **6** | Pre-register GO/NO-GO gate + evaluate once | **DONE — NO-GO** | Spec in `GATE.md`; result in [`GATE_RESULT.md`](GATE_RESULT.md). Expectancy ≤0 at n≥200 |
| **7** | Forward shadow / reliability log | **RUNNING** | `edge/tools/shadow_v90.py` live; log at `edge/runs/shadow_decisions.jsonl` (accumulate ≥60 sessions) |
| **8** | Kronos fine-tune (GPU) | **BLOCKED** | Gate failed; do not buy VM |
| **9** | Cross-sectional hypothesis (Qlib, daily, 10y) | **DONE — NO-GO** | Gate in [`GATE_XS.md`](GATE_XS.md), result in [`GATE_XS_RESULT.md`](GATE_XS_RESULT.md); artifacts `edge/runs/qlib_xs/` |
| **10** | 5/10/20d directional daily research | **DONE — DEVELOPMENT NO-GO** | Nested purged/embargoed evaluation, 17 recorded trials, sealed terminal holdout; [`DIRECTIONAL_DAILY_RESULT.md`](DIRECTIONAL_DAILY_RESULT.md) |
| **11** | Turnover / regime-window sweep (`GATE_XS2.md`) | **DONE — NO-GO** | 36-config sweep + 200-draw null + 2 confirmation arms; [`GATE_XS2_RESULT.md`](GATE_XS2_RESULT.md) |
| **12** | Wide universe breadth hypothesis (`GATE_XS3.md`) | **DONE — NO-GO** | 557 symbols, pitwide N=250; actual Rank IC **+0.0052**, NW t **+0.47**, post-cost IR **+0.373**, turnover **545%** — fails 5 of 6. `GATE_XS3_RESULT.md`'s GO and its figures (+0.0631 / 4.69 / 0.768) match no artifact and are **retracted**: [`GATE_XS3_CORRECTION.md`](GATE_XS3_CORRECTION.md) |

## Step 10 — fixed-horizon directional research

The hardened daily pipeline evaluated momentum, volatility-scaled momentum,
regularized logistic regression, conservative CPU XGBoost, and two fixed simple
hypotheses across 5-, 10-, and 20-session targets. Standalone development
expectancy was positive for the selected broad-universe trials, but **no
challenger established a positive paired lower bound versus frozen momentum**.
The liquid-ETF sensitivity was also a NO-GO: 5d/10d expectancy lower bounds were
negative, while 20d failed both incremental evidence and calibration.

The terminal holdout (2026-07-13 through 2027-01-29) remains
`SEALED_UNEVALUATED`. The artifact reports `FAIL_DEVELOPMENT` and explicitly
forbids option-shadow authorization. See
[`DIRECTIONAL_DAILY_RESULT.md`](DIRECTIONAL_DAILY_RESULT.md) for the exact
metrics and experiment hashes.

## Step 9 — the cross-sectional attempt

Every model in the stack through Step 8 asks an **absolute** question ("will this
symbol rise?"). Step 9 tested the **cross-sectional** one ("which names outperform
the rest?") — LightGBM on Alpha158 with `CSRankNorm`, daily bars 2016-2026 from
`edge/data/1d/`, long-only top-10. Run alongside the existing stack; `eval/`,
`models/v90*/` and shadow logging are untouched.

**Result: NO-GO**, but a more informative one than Step 6.

| | xs47 (all singles) | xs40 (listed by 2016-08) |
|---|---:|---:|
| Rank IC (gate ≥0.02) | 0.0126 | **0.0334** |
| NW t-stat (gate >2.0) | 1.35 | **2.68** |
| Rank ICIR (gate ≥0.20) | 0.085 | 0.180 |
| Excess ann. vs SPY after cost | +9.13% | +4.44% |
| Information ratio (gate >0.5) | **0.627** | 0.299 |

Two findings worth carrying forward:

1. **Removing the hindsight-picked 2020-23 listing cohort *improves* the signal
   and *worsens* the returns.** xs47's portfolio advantage is substantially the
   payoff from holding names chosen in 2026 because they worked — not ranking
   skill. Universe construction now moves the result more than the model does.
2. **Cost is the binding constraint, not capacity.** On xs40, 10bp round-trip
   halves the edge (IR 0.606 → 0.299). Pre-cost it would have cleared.

Also new: `edge/tools/rank_ic.py` measures Rank IC / ICIR directly. Run against
v90_wide as a negative control it gives **Rank IC −0.0008, NW t −0.09, flat
quintiles** (`edge/runs/v90_wide_ic.json`) — every quintile earned the same
+0.12%, i.e. the melt-up drift, with no ordering information at all. That is a
sharper diagnosis of the Step 6 failure than the win-rate tables were, and it is
now the null that future signals are measured against.

## Why live did not match backtest

The two models showing tradeable-looking returns (PEAD catalyst +502.98%, PEAD
hybrid +290.62%) were booking each bar's own return against a weight formed from
that bar's own features. At one bar of execution lag they are −10.38% and +1.53%.
Nothing was wrong with the live path — `daily_plays` is consistently
`asof_utc`-driven. The backtest was the thing that was wrong, so live could never
have matched it. Full record: [`LOOKAHEAD_CORRECTION.md`](LOOKAHEAD_CORRECTION.md).

## One-line state

Baseline v90 on 7 names still looks like a thin calibrated pocket (ECE 0.0048,
n=111, +0.17%/trade). **The same recipe on 59 names is a NO-GO:** n=2049 at
balanced, WR ~53%, expectancy **negative**, Sharpe −0.73, ECE still excellent
(0.009). The new 5/10/20d daily candidates also fail their development gate
because they do not beat frozen momentum with a positive paired confidence
bound. Calibration ≠ edge. Kronos selective 71%/82% remains a lookahead
artifact. **Do not buy a GPU VM or trade these models.**

## Leaderboard headline (contract-normalized, $1k cash)

From `TradingAlgoWork/LEADERBOARD.json` (generated 2026-07-30):

| Model | Total return | Sharpe | WR | n | Note |
|---|---:|---:|---:|---:|---|
| v72_dual_sleeve | +467% | 3.00 | 71.8% | 177 | Top absolute return; long/flat only; ordinal confidence |
| v39b_live_adapt | +310% | 2.70 | 68.8% | 141 | |
| v39d_confluence | +299% | 2.60 | 66.9% | 139 | |
| v85_anti_overfit | +154% | 1.75 | 57.7% | 123 | Low WR, solid payoff |
| v23_devin_overlay | +130% | 2.21 | 65.2% | 92 | |
| v90_meta_confidence | +16% (native OP) | 2.76 | 55.0% | 111 | **Only calibrated probabilities**; shipped OP |
| v70_high_confidence_wr | +43% | 1.25 | 90.9% | 33 | Highest WR, worst vs buy-and-hold basket |

Surprise under one contract: **highest win rate ≠ best strategy**. v70 beats
nobody on return; v90's high-frequency OP loses money.

| **13** | Decouple options capture in `daily_plays` | **DONE** | `edge/daily_plays/pipeline.py` captures `option_snapshots.json` whenever options adapter exists regardless of model entry state; `test_pipeline_integration.py` → 111 passed |
| **14** | Track 1: Volatility Timing (`GATE_VOL_TIMING.md`) | **DONE — NO-GO** | Pre-registered gate [`GATE_VOL_TIMING.md`](GATE_VOL_TIMING.md); 15-year vol complex fetched (`edge/data/vol_complex.csv`); 36-cell sweep in `edge/runs/vol_timing/grid_sweep.json` → all 36 cells NO-GO |
| **15** | Track 2: FINRA Short Volume Factor Engine | **DONE — NO-GO** | `edge/tools/fetch_finra_short_vol.py`, `edge/tools/build_finra_factor_model.py`; Mean IC **+0.0290**, but 10bp trading costs drop net return to **-13.39%** |
| **16** | GCP Vertex AI Distributed Sweeps & Proof | **DONE** | `edge/tools/submit_vol_finra_gcp.py` verified with `--dry-run` on Spot VM allocation |
| **17** | Track 3: PEAD Catalyst & Gap Acceleration (`GATE_PEAD.md`) | **DONE — NO-GO** | Pre-registered gate [`GATE_PEAD.md`](GATE_PEAD.md); Mean Rank IC **−0.0027**, ICIR **−0.12**, Net Annual **−10.38%**, Sharpe **−0.26**. This row previously read **GO** at IC +0.1518 / ICIR 2.14 / +120.76% / Sharpe 3.04 — figures that match no artifact, the same failure as [`GATE_XS3_CORRECTION.md`](GATE_XS3_CORRECTION.md). **Retracted.** |
| **18** | Execution-lag lookahead in the portfolio simulators | **DONE — FIXED** | `build_pead_catalyst_model.py` and `build_pead_factor_hybrid.py` booked each bar's own return against a weight formed from that bar's features. Fix: [`edge/research/portfolio.py`](../research/portfolio.py) (`execution_lag` ≥ 1 enforced); regression test `edge/tests/research/test_portfolio.py`. See [`LOOKAHEAD_CORRECTION.md`](LOOKAHEAD_CORRECTION.md) |

## Known data constraint for Step 5

Free Yahoo `1h` history is roughly **~730 calendar days**. The plan's "≥8 years"
cannot be satisfied on free 1H bars alone. Step 5 tooling therefore:

1. Expands **cross-section** (≥40 liquid names, ≥4 sectors) on 1H for the
   available window (primary for v90 re-fit).
2. Pulls **daily** bars for ≥8 years to document regimes / drawdowns (secondary
   evidence; not a silent swap of the model bar size).

Any claim of "8-year 1H walk-forward" without a paid data source is rejected.

## Next actions (in order)

0. **Step 9/10 follow-up, if continuing research.** The binding constraint on the
   cross-sectional path is *turnover and universe construction*, not model
   capacity. The single most promising next test is a lower-turnover rebalance
   (weekly, or wider topk) on a **fresh** window under a **new** gate file. Do
   not re-tune topk/n_drop on the 2024-26 test segment — forbidden by
   `GATE_XS.md` rule 1. For the daily directional path, start from a new
   economically motivated hypothesis and pre-register it before another run;
   do not retune the failed shock/sector-residual hypotheses. Do not add model
   capacity.
1. ~~Fetch + re-fit + gate~~ **done → NO-GO** (see `GATE_RESULT.md`).
2. Keep `python3 edge/tools/shadow_v90.py` on a schedule; ` --realize` after
   horizon; `shadow_reliability.py` weekly. Need ≥60 sessions before any
   live-capital discussion.
3. Decouple `daily_plays` option capture to bank ground-truth chains daily.
4. Run GCP Vertex AI custom jobs via `submit_vol_finra_gcp.py` for cloud-based parallel experiments.

---

*Simulated / historical only. Not financial advice.*
