# Trading stack audit — 2026-07-29

Scope: `Kronos/`, `TradingAlgoWork/`, `TradingWork/`. Goal: find which models
actually carry edge, verify the headline claims, and decide whether a paid GPU
VM is justified.

---

## 1. Repo map

| Repo | Size | What it is | Rigour |
|---|---:|---|---|
| **`TradingAlgoWork/`** | 5.2 GB | Full research platform: 152 versioned `SignalEngine` bundles, walk-forward + locked-holdout backtester, genetic evolve pipeline, SHA256-pinned deployment manifest, FastAPI runtime, Next.js trade desk | **Highest.** Deflated Sharpe, Wilson CIs, purged CV, fail-closed promotion gates |
| **`Kronos/`** | 156 MB | Upstream AAAI-2026 foundation model (`NeoQuasar/Kronos-base`, 102M params, OHLCV→discrete tokens→autoregressive transformer) + ~40 custom overlay scripts (conformal intervals, GEX, confidence scoring, selective serving) | **Mixed.** Excellent interval calibration; the directional overlays are unvalidated |
| **`TradingWork/`** | 1.4 GB | Earliest repo. Scanners (gap / institutional flow / technical / growth), per-ticker XGB WFO models, Supabase + Next.js app, **live options-flow signal journal** | **Lowest** for models, but holds the only real forward-recorded data |

---

## 2. Critical finding — the headline Kronos number is a lookahead leak

`Kronos/forecasts/TREND_V5_REPORT.md` reports the selective model at
**71.35% all-days** and **82.33% actionable (283 trades)**, holdout 82.73%.
Those are the numbers that make the stack look tradeable. **They are contaminated.**

### The mechanism

```
eval_walkforward.py:440   date         = df.iloc[t].timestamps      <- the TARGET day
eval_walkforward.py:374   actual_close = df.iloc[t].close
eval_walkforward.py:375   last_close   = df.iloc[t-1].close

bakeoff_trend_v5.py:43-45 closes   = hist[timestamps <= date]       <- INCLUDES bar t
bakeoff_trend_v5.py:65    last_ret = closes[-1]/closes[-2] - 1
                                   = actual_close/last_close - 1
                                   == actual_ret        (identically, every row)
```

`last_ret` is passed straight into `point_bias.correct_point_return()`. Its
anti-fade branches (`point_bias.py:58,74`) emit a corrected return whose **sign
follows `last_ret`** whenever `|last_ret| >= 4%`. Feeding them the realized
return makes them correct by construction. `ret_3d` and the `closes` array
handed to `trend_regime.compute_trend_regime()` are contaminated the same way.

### Measured impact

`edge/tools/verify_no_lookahead.py` (runnable, 799 walk-forward days):

| Signal | Directional accuracy | p vs coin |
|---|---:|---:|
| Kronos raw median | 50.7% | — |
| Persistence baseline | 46.8% | — |
| **Selective — leak-free** (as computed inside `eval_walkforward.py`) | **49.3%** | 0.66 |
| Selective — actionable subset, leak-free (n=249) | **51.8%** | 0.31 |
| Selective — with the leak reinstated | 70.3% | — |
| Selective — actionable, with the leak (n=231) | 79.2% | — |
| *Published claim* | *71.35% / 82.33%* | — |

Reinstating the leak reproduces the published number to within 1pp. Leak-free,
the selective model is **indistinguishable from a coin flip.**

The leak-free path inside `eval_walkforward.py::_day_gate` (line 189,
`ret_1d = last_close / hist_closes[-2] - 1`) is correct. **Only the offline
bakeoff reconstruction is broken** — so the fix is contained, but every report
derived from it must be regenerated.

### Also contaminated by inheritance

- `forecasts/TREND_V5_REPORT.md` — all "selective / v5 / actionable" rows
- `forecasts/ULTRA_BEAT_REPORT.md` — Champion Ensemble 53.14%/54.52% (same bakeoff family)
- `edge_filter.py` `WINRATE{}` table (0.72 / 0.62 / 0.54) — the tier win-rates the
  live screen prints to the operator
- The on-disk `TREND_V5_REPORT.md` also **does not match its generator**
  (`bakeoff_trend_v5.py` writes different section headings), so it was
  hand-edited or produced by an unversioned script. Treat as untrusted.

### What survives in Kronos

`forecasts/VERIFIED_REPORT.md` is honest and holds up: 120 sessions/ticker,
leak-free expanding window, and it states plainly that **no ticker shows a
statistically defensible directional edge** (all p > 0.05). Its real product is
**calibrated uncertainty**: split-conformal lifts PI80 coverage from 53% → 79%
(target 80%). That is a genuine, reusable asset.

`EXP1_KRONOS_REMEASURE.md` is also a good sign — the team already caught one
overfit (HIGH-confidence dir-acc 0.722 on n=18 collapsed to 0.486 on n=70) and
correctly rejected it. Same failure mode, caught by more samples.

---

## 3. Model ranking (honest)

| Rank | Model | Where | Real measured performance | Verdict |
|---|---|---|---|---|
| **1** | **`v90_meta_confidence`** | `TradingAlgoWork/models/poc_va_macdha/` | Locked holdout, two-sided, after 10bp costs. Holdout **ECE 0.0048** (when it says 55% it wins ~55%). top-5%: n=111, WR 55.0% [45.7, 63.9], PF 1.17, +0.17%/trade. top-2%: n=34, WR 58.8%, PF 2.26 | **Best in the stack.** Purged+embargoed 5-fold, isotonic calibration, triple-barrier labels, genuine SELL head. Honest about its own limits |
| 2 | `v72_dual_sleeve` (promoted) | `TradingAlgoWork/` | Full WR 72.1% n=179 → **OOS 65.5% n=84**. +513% / Sharpe 3.08 simulated | Real but long/flat only; confidence is **ordinal, not probability** — manifest blocks probability-sized execution by design |
| 3 | Kronos split-conformal intervals | `Kronos/conformal.py` | PI80 53% → 79% coverage, leak-free, 796 sessions | Genuine. Not a directional signal — an uncertainty band |
| 4 | `v23_devin_overlay` | `TradingAlgoWork/runs/evolve_equity_1h` | +130%, Sharpe 2.21, n=92, DD −9.1%, multi-lock PASS | Plausible but selected from 152 candidates on one basket/one regime |
| 5 | Options-flow signal journal | `TradingWork/data/signal_journal.db` | 2,926 UNUSUAL_VOLUME outcomes + 12 other signals | **Only forward-recorded data you own.** Currently 9 days — too short to conclude anything, but it compounds daily |
| — | Kronos selective / trend-v5 / ultra-beat | `Kronos/` | **49.3% leak-free** | Do not trade |
| — | `v70_high_confidence_wr` (90.9% WR) | `TradingAlgoWork/` | n=33, Wilson low ~76%, no OOS | Sample too thin; repo already flags `below_claim_n` |

### Known bugs to fix in v90

- `results.json` Sharpe values of **13.8 and 29.3** are artifacts of annualizing
  1764 bars/yr across 34 and 11 trades. Meaningless; remove or recompute per-trade.
- Operating point `enter_hi` was chosen by reading holdout profit factor across
  4 candidate quantiles. Threshold *values* come from train OOF (correct), but
  the *choice of which one to ship* peeked. Minor, but must be pre-registered.
- At the only tradeable frequency (top-10%, n=320) expectancy is **negative**
  (−0.05%/trade, PF 0.94). The edge exists only where n ≤ 111.

---

## 4. What is actually blocking you

Not compute. The binding constraints are:

1. **152 model versions searched on one 7-symbol basket in one regime**
   (2024-08 → 2026-07, an AI melt-up). Deflated Sharpe discounts best-of-N but
   cannot manufacture out-of-regime evidence.
2. **No forward track record.** Every number in all three repos is simulated.
3. **No lookahead test in CI.** The leak above sat in a published report and
   propagated into the live `edge_filter` win-rate table shown to the operator.
4. **Evidence base is not comparable** — `results.json` files were generated at
   mixed starting capital ($1k vs $1M) and mixed windows, so cross-model tables
   mix runs (already documented in `docs/MODEL_REVIEW_AND_HIGH_WINRATE_PLAN.md` §2.5).

---

## 5. VM verdict

**Do not buy the GPU VM yet.** Reasoning:

- The result that would justify it (71–84% selective) does not exist.
- The real ceiling on this universe/timeframe, measured honestly, is **~52–59%
  win rate with positive expectancy only at low frequency**. That is a
  real but thin edge — and thin edges are killed by execution cost, not by
  insufficient model capacity.
- Fine-tuning Kronos-base (102M params) on 7 tickers × 2 years of 1H bars is
  ~3,500 bars/ticker. That is far too little data to fine-tune 102M parameters;
  the likely outcome is a better in-sample fit and no OOS gain. The fix for
  that is **more symbols and more history**, which is a cheap CPU/bandwidth
  problem, not a GPU problem.
- Steps 1–6 of the plan are all CPU-only and cost nothing but time.

**Buy the VM when — and only when — this pre-registered trigger fires:**

> A frozen v90-class spec, evaluated once on a ≥40-symbol universe spanning
> ≥2 distinct regimes (incl. one drawdown ≥15%), delivers on the locked holdout:
> **n ≥ 200 trades, expectancy ≥ +0.15R after 10bp costs, Wilson 95% lower bound
> on WR > 50%, ECE ≤ 0.05, and deflated Sharpe > 0.**

If that fires, GPU spend is justified for (a) Kronos fine-tuning on the widened
universe and (b) a proper hyperparameter search under purged CV. If it does not
fire, a VM would have bought you a faster way to overfit.

Rough cost if it does fire: a single A10G/L4 spot instance (~$0.5–1.0/hr) for
~40–60 hours covers tokenizer + predictor fine-tune and one search pass. Budget
~$50–100, not a monthly reservation.

---

*Every number in this document is simulated or historical backtest. Nothing here
is financial advice.*
