# Integrating `awesome-systematic-trading` into `edge/`

Source: https://github.com/wangzhe3224/awesome-systematic-trading (Readme.md, master)

---

## STATUS — implemented 2026-08-03

Steps A, D and E are **built and tested**; B is built as a weights-only
optimizer awaiting a real evaluation run. 467 tests pass across `edge/tests`.

| Step | Deliverable | State |
|---|---|---|
| A · diagnose | `research/factor_diagnostics.py` (IC decay w/ hand-rolled Newey-West, quantile returns, quantile turnover, monotonicity) + `tools/factor_tearsheet.py` | done · 22 tests |
| B · turnover | `research/optimizer.py` — cvxpy/CLARABEL, cost inside the objective | done · 11 tests · not yet evaluated against `GATE_XS_RESULT.md` |
| D · options fills | `daily_plays/options_fills.py` — patient-then-cross, per-leg spread rejection | done · 28 tests · **not yet wired into `realize.py`** |
| E · vol targeting | `research/vol_targeting.py` — causal realized/EWMA, scale series only | done · 18 tests |
| — · knowledge graph | `tools/graphify_index.py` + `tools/graphify_payload.py` | done · 9 tests |
| — · dashboard | routes **09 Research** and **10 Graph**, `/api/factors`, `/api/graph` | done |
| C · universe | `FinanceDatabase` into `build_pit_universe.py` | **not started** |
| F · expression alphas | operator grammar into the GA genome | **not started** |
| G · 8-K catalysts | `FilingFirehose` into `pead_adapter.py` | **not started** |

**Nothing from the awesome list was actually installed.** Every Tier-1 item was
implemented natively against the repo's own primitives instead: `alphalens` is
unmaintained and would have pinned pandas, and cvxpy was already present, so
`cvxportfolio`/`skfolio` added nothing but a dependency. The list's value here
turned out to be as a *checklist of questions*, not a source of code.

### What Step A actually found

The diagnostic exists to answer whether the edge survives turnover. Run on real
data, it says **no**, on both signals tested:

- `momentum_20d`, 2499 dates × 557 symbols: mean IC(1d) **−0.0063** (NW t −1.59),
  monotonicity **−0.900**. The signal is inverted — Q1 (lowest momentum) earns
  the most. It reaches |t| ≥ 2 only at 3d, and negative.
- `qlib_xs4/lgb158` (the frozen GATE_XS3 baseline, "the number to beat"),
  491 dates × 366 symbols: mean IC(1d) **+0.0040** (NW t +0.53, not
  significant), monotonicity +0.700, and **0 of 5 quantiles clear their own
  turnover cost**. Every bucket's gross return is positive and smaller than
  what it costs to hold.

That last line is the finding. It is consistent with `README.md`'s own
"10bp halves the edge", and it means Step B's optimizer is now the load-bearing
experiment: if cost-aware weights cannot lift a bucket above its cost line,
turnover was never the fixable part.

Caveat on comparability: these windows are not the ones `GATE_XS_RESULT.md`
reports (which found Rank IC 0.033, NW t 2.68). Different date range, different
universe. Do not read the numbers above as contradicting that gate until the
same window is run.

### Open follow-ups

1. **Wire `options_fills.py` into `realize.py`.** The module is tested but not
   yet on the path, so live shadow option plays are *still* scored at mid. This
   is the highest-value remaining item and it is a small change.
2. **Run Step B's optimizer through `simulate_long_short`** on the same folds as
   `GATE_XS_RESULT.md` and compare. Built but unevaluated.
3. **Re-run the tearsheet on the gate's own window** so the numbers above are
   comparable to the recorded gate.
4. `tools/factor_tearsheet.py` raises (does not clamp) if asked for data at or
   after the sealed holdout start, 2026-07-13.

## Framing

The list has ~250 entries. Almost none of them address this repo's actual
bottleneck. `README.md` already states the diagnosis:

> Two things now look like the real constraints: **turnover** (10bp halves the
> edge) and **universe construction** ... Neither is fixed by a bigger model.

So the filter applied below is: *does this library attack turnover, universe
construction, or an accounting hole we know exists?* Everything that only adds
another model class or another backtester is rejected, with reasons.

Current state, for reference:

| Capability | Where it lives | Status |
|---|---|---|
| Purged/embargoed CV | `research/splits.py`, `panel_splits.py` | strong, better than most libs |
| Deflated Sharpe, block bootstrap, effective trial count | `research/statistics.py` | strong |
| Pre-registered gates + ledger | `research/gates.py`, `experiment_ledger.py` | strong |
| Long/short accounting w/ execution lag | `research/portfolio.py` | strong — caught a +502%/yr lookahead |
| Model menu | `research/directional_bakeoff.py` | logistic, elastic net, HGB, ExtraTrees, XGBoost, soft-vote |
| Cross-sectional | qlib Alpha158 / CSRankNorm (`tools/qlib_run.py`) | Rank IC 0.033, NW t 2.68 |
| Rule evolution | `research/ga/` | fixed signal families, multi-objective fitness |
| Options | `daily_plays/options_intelligence.py`, `gex_core.py` | no fill model |
| Installed already | cvxpy, xgboost, lightgbm, qlib, pyarrow, yfinance | — |

---

## Tier 1 — attacks a stated constraint. Do these.

### 1.1 `cvxportfolio` — put transaction cost *inside* the objective

**Problem it solves.** `simulate_long_short` charges
`turnover_per_bar * cost_per_side` *after* weights are formed. The optimizer
that produced those weights never saw the cost, so it has no reason to prefer
a cheaper neighbouring portfolio with 95% of the alpha. When 10bp halves the
edge, that is the whole game.

**What changes.** A new `research/optimizer.py` that takes the same signal
frame the current top-N ranking consumes and returns weights from

```
max  wᵀ α  −  γ_risk · wᵀΣw  −  γ_trade · ‖w − w_prev‖₁ · cost
s.t. Σw = 0 (dollar-neutral), ‖w‖₁ ≤ leverage, |wᵢ| ≤ cap
```

cvxpy is already installed; `cvxportfolio` adds the multi-period version and
the cost models. `skfolio` (sklearn-API) is the lighter alternative if a
full cvxportfolio dependency is unwanted.

**Non-negotiable.** The optimizer produces `long_weights`/`short_weights` and
nothing else. `simulate_long_short` stays the sole accounting path — the
optimizer's own reported P&L is never quoted as a result. Otherwise we grow a
second, unaudited accounting path, which is exactly how the PEAD lookahead
survived.

**Test.** `tests/research/test_optimizer.py`: at `γ_trade = 0` the optimizer
must reproduce the current top-N weights to within tolerance; as `γ_trade`
rises, `PortfolioResult.annual_turnover` must fall monotonically.

**Success criterion.** Net Sharpe on the qlib xs signal at 10bp beats the
current top-N construction on the same folds. If it does not, turnover was
not the binding constraint and that is itself a publishable result.

### 1.2 `alphalens` — find out *where* the Rank IC 0.033 lives

**Problem it solves.** `tools/rank_ic.py` reports one number. It cannot say
whether the edge is concentrated in the extreme quantiles (holdable cheaply)
or spread evenly across the book (turnover-doomed), nor how fast IC decays
with horizon — which sets the minimum viable rebalance period, which sets
turnover.

**What changes.** `tools/factor_tearsheet.py` wrapping
`alphalens.tears.create_full_tear_sheet` over the qlib xs signal. Outputs to
`runs/qlib_xs4/tearsheet/`. Read: IC decay by horizon (1/5/10/20d), mean
return by quantile, turnover by quantile, IC by sector.

**Ordering.** Run this *before* 1.1. If IC decay says the signal survives to
10 days, the turnover fix is a rebalance-frequency change and the optimizer is
optional. Cheap diagnostic, gates an expensive build.

**Caveat.** alphalens is unmaintained upstream; the list points at
`wangzhe3224/alphalens` (fork). Pin it, and treat its return numbers as
diagnostics only — they do not go through `simulate_long_short`, so they are
not evidence for a gate.

### 1.3 `FinanceDatabase` + `FilingFirehose` — universe construction

**Problem it solves.** The second stated constraint: "dropping the
hindsight-picked 2020-23 listing cohort *improves* the signal and *worsens*
the returns." That is survivorship structure, not a model problem.
`tools/build_pit_universe.py` exists; it needs a wider, dated listing source.

- `FinanceDatabase` — 300k+ symbols with listing metadata, for constructing a
  genuinely point-in-time membership series rather than a hand-picked list.
- `FilingFirehose` — SEC EDGAR JSON with body-text-classified 8-Ks and 13D/G.
  This feeds `daily_plays/adapters/pead_adapter.py` directly: PEAD needs
  event timestamps, and 8-K Item 8.01 items are exactly the buried catalysts
  the adapter is trying to trade. Free 72h tier is enough to evaluate.

**Guardrail.** Every new loader must raise on miss, per the
`short_pressure` incident (`research/features.py::assert_no_degenerate_feature_columns`).
No `except Exception: pass`.

---

## Tier 2 — real model improvement, but must pass the existing gates.

### 2.1 Expression-based alpha search — widen the GA search space

`research/ga/genome.py` searches a fixed `SIGNAL_FAMILIES` set (momentum,
vol-scaled momentum, mean-reversion, ...). The list's expression-alpha
section generalises this to a formula grammar:

- `alphagen` (RL-driven formulaic alpha generation)
- `alpha_examples` (Polars-based expression alphas — closest to the current
  numpy panel in `research/ga/panel.py`, lowest port cost)
- `torchquantum` (WorldQuant operator set on PyTorch)

**The catch, and it is the whole story.** Widening the search space multiplies
the trial count. `research/statistics.py` already has
`bonferroni_deflated_sharpe_approximation` and
`effective_trial_count_from_returns` — the expression searcher **must** report
its true trial count into those, not the count of survivors. A formula search
that reports "I found one with Sharpe 2" without its denominator is worse than
no search at all.

**Recommendation.** Port the operator grammar into the existing GA genome
rather than adopting a whole framework. `research/ga/fitness.py` already has
the multi-objective fitness, the protocol guard, and the holdout seal. Keep
those; swap only the signal-expression representation.

### 2.2 `arch` (GARCH) + Hurst — turnover-cheap volatility levers

`research/regimes.py` classifies regimes; `features.py` has one realized-vol
column. Two additions that lower turnover rather than raise it:

- **Vol targeting** — scale gross exposure by forecast vol so position changes
  come from vol, not from signal churn. Historically the cheapest Sharpe
  improvement available on a mediocre signal.
- **Hurst exponent** (the list's `hurst-calculator`, or `arch`) as a regime
  gate: trade the momentum book only in trending regimes, the reversion book
  only in mean-reverting ones. Cuts trades rather than adding them.

`statsmodels` and `arch` are both missing from `.venv-qlib` — installing
statsmodels also gives proper Newey-West machinery instead of the hand-rolled
path.

### 2.3 `flashalpha-fill-simulator` — options fills

`research/costs.py` says explicitly:

> This module accounts only for hypothetical underlying long/short exposure.
> It does not consume option chains and must never be used to infer option P&L.

But `daily_plays/` ships options plays (`options_intelligence.py`, 1338 lines;
`adapters/options.py` computes mid and spread_pct). So the options side has a
correctly-flagged accounting hole. The fill simulator models post-and-wait
limits, stale-quote guards and patient-then-cross exits for credit/debit
spreads — engine-agnostic, zero runtime deps.

**What changes.** `daily_plays/options_fills.py` mirroring `costs.py`'s
structure: an explicit, conservative fill model that shadow P&L in
`realize.py` runs through, so option plays stop being scored on mid.

---

## Tier 3 — infrastructure. No alpha, real time savings.

| Library | Use here | Priority |
|---|---|---|
| `DuckDB` | query `data/1d_wide/` parquet directly instead of loading full panels into pandas; makes universe/coverage checks seconds not minutes | high, trivial |
| `Polars` | `research/ga/panel.py` panel builds; the GA is the hot loop | medium |
| `ArcticDB` | proper store for `data/option_chains/` and tick data — currently loose files | medium |
| `quantstats` / `ffn` | tearsheet HTML for the Vue dashboard's `EvolutionView`/`DeskView`; feeds `tools/render_dashboard.py` | low, 1 day |
| `numba` | `research/ga/fitness.py` rolling ops | low, only if GA is slow |
| `joblib` | already used in `directional_bakeoff.py` | done |

---

## Explicitly rejected, with reasons

| Entry | Why not |
|---|---|
| `vectorbt`, `backtrader`, `zipline`, `bt`, `nautilus_trader`, `Manifold-BT` | Each is a *second* accounting path. `research/portfolio.py` exists because a hand-rolled loop hid a +502%/yr lookahead; adding an engine whose lag semantics you have not audited reintroduces exactly that class of bug. If a fast sweeper is wanted for coarse parameter search, any result must be re-run through `simulate_long_short` before it is quoted anywhere. |
| `FinRL`, RL trading gyms | RL needs far more data than a 59-symbol daily panel, and its reward is a backtest — so every leak in the sim becomes a learned policy. The repo's own evidence says the model class is not the constraint. |
| `FinGPT`, LLM stock pickers, "AI Hedge Fund" | No leak-free evaluation protocol; unfalsifiable claims. Nothing here would survive `research/gates.py`. |
| `TA-Lib` / `pandas-ta` (130+ indicators) | Adding 130 correlated indicators to a 9-feature causal set is a multiple-testing generator, not a signal source. If more features are wanted, qlib Alpha158 is already wired and already counted. |
| `hftbacktest` | Wrong frequency. Daily bars. |
| `deepdow`, `spectre`, GPU libs | `docs/AUDIT.md` verdict stands: do not buy a GPU VM. |

---

## Sequencing

Each step is independently abandonable; nothing later depends on an earlier
step *succeeding*, only on it having been run.

**Step A — diagnose (½ day, ~zero risk).**
Install `alphalens` (pinned fork), `statsmodels`, `duckdb`. Build
`tools/factor_tearsheet.py`. Run on the qlib xs4 signal. **Decision point:**
does IC survive past 1 day, and is return monotone in quantile?

**Step B — turnover (2–3 days), gated on A.**
Only if A shows the edge is real but turnover-eaten. Add `cvxportfolio` or
`skfolio`, build `research/optimizer.py` + tests. Re-run the existing
walk-forward with optimizer weights through the *unchanged*
`simulate_long_short`. Compare against `docs/GATE_XS_RESULT.md` on the same
folds.

**Step C — universe (2 days), parallel with B.**
`FinanceDatabase` into `tools/build_pit_universe.py`. Re-run the xs
evaluation on a PIT universe. This directly tests the README's own
observation about the 2020-23 listing cohort.

**Step D — options fills (2 days), independent.**
`daily_plays/options_fills.py`. Highest value per line in the whole plan
because it closes an accounting hole that is currently *known and open* on the
live shadow book.

**Step E — vol targeting (1 day), independent.**
`arch` + exposure scaling in `research/portfolio.py`. Cheap, and it lowers
turnover rather than raising it, so it composes with B.

**Step F — expression alphas (1 week), gated on B or C producing a GO.**
Last, not first. Only worth the multiple-testing burden once the accounting
and universe questions are settled.

**Step G — 8-K catalyst feed (open-ended).**
`FilingFirehose` into `pead_adapter.py`. Evaluate on the free tier before
paying.

---

## Invariants any of this work must not break

1. `execution_lag >= 1`. `research/portfolio.py` is the only long/short
   accounting path. New libraries produce weights or diagnostics, never
   quoted P&L.
2. Every data loader raises on miss. No silent degradation to a constant
   (`research/features.py`, `docs/LOOKAHEAD_CORRECTION.md`).
3. The terminal holdout from 2026-07-13 stays sealed. Nothing added here gets
   a path argument that could reach it.
4. Trial counts are reported honestly into
   `research/statistics.py::effective_trial_count_from_returns`. Any search
   that widens the hypothesis space widens the deflation with it.
5. Gates in `docs/GATE*.md` are pre-registered before results are looked at.

---

*Simulated-backtest tooling. Nothing here is financial advice.*
