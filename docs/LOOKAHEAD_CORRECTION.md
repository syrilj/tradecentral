# Execution-Lag Lookahead — Correction Record

**Date**: 2026-08-01
**Scope**: `edge/tools/build_pead_catalyst_model.py`, `edge/tools/build_pead_factor_hybrid.py`
**Trigger**: live results not matching backtest.

---

## What was wrong

Both PEAD simulators stamped portfolio weights on the bar the signal was formed
from, then multiplied by that same bar's close-to-close return:

```python
long_w.iloc[i : i + holding_days] = <formed from df_signal.iloc[i]>
port_ret = (long_w * close.pct_change(1)).sum(axis=1)   # .iloc[i] is bar i's own return
```

`close.pct_change(1).iloc[i]` is the move from close `i-1` to close `i` — already
realised before the bar-`i` signal exists. The signal is an overnight-gap
feature, and the overnight gap is a *component* of that very return, so the
simulator was collecting the gap it had just observed. It is close to circular.

Two things made the signal unknowable before bar `i`'s close in any case:
`gap_std` reads bar `i`'s open, and `vol_surge` reads bar `i`'s **full-day**
volume. One bar is the earliest honest execution.

The hybrid additionally applied `port_ret.clip(-0.10, 0.10)` to the portfolio
return series. Truncating the series collapses the Sharpe denominator while the
lookahead holds the numerator up — that combination, not the risk controls the
docstring advertises, is what produced its Sharpe of 13.33.

## Effect

Same signal, same universe (557 symbols, `edge/data/1d_wide`, 2016-08 → 2026-07),
same costs. Only the execution alignment changed.

| Model | | Net annual | Sharpe | Rank IC |
|---|---|---:|---:|---:|
| PEAD catalyst | as shipped (lag 0) | **+502.98%** | 5.38 | +0.0396 |
| PEAD catalyst | corrected (lag 1) | **−10.38%** | −0.26 | −0.0027 |
| PEAD catalyst | corrected (lag 2) | −13.31% | −0.37 | — |
| PEAD hybrid | as shipped (lag 0, clipped) | **+290.62%** | 13.33 | +0.0270 |
| PEAD hybrid | corrected (lag 1, unclipped) | **+1.53%** | 0.08 | +0.0270 |

**100% of the reported edge was the lookahead.** Corrected, the catalyst model's
gross return is +1.26% against 39.63% annualised volatility — indistinguishable
from zero, and 11.64% of annual cost drag buries it.

`build_finra_factor_model.py` was checked and is **correct** — it uses
`daily_ret.shift(-1)` at line 149. Its honest −13.39% net return is why it never
looked remarkable.

## Two further defects found in the same files

1. **Headline IC was conditional.** Mean Rank IC was computed only over names
   with `|signal| > 1.5`, a self-selected subset of extreme gappers. That
   subset gives +0.0396; the full cross-section gives **−0.0027**. `GATE_PEAD.md`'s
   0.040 threshold was written for a cross-section. Both figures are now
   reported so neither can be quoted alone.

2. **`short_pressure` was silently dead.** `load_finra_short_vol()` looked for
   `edge/data/finra_short_vol.csv`, which has never existed — the fetcher writes
   `edge/data/finra_shortvol/`. The miss was swallowed by `except: pass`, the
   feature collapsed to the constant 0.5, and `GATE_PEAD_RESULT.md` went on
   listing it as included. The loader now searches the real directory and says
   so loudly when it finds nothing.

## The durable fix

`edge/research/portfolio.py` — one audited accounting primitive. `execution_lag`
defaults to 1 and **raises below 1**, so the defect is unrepresentable rather
than merely fixed. It also:

- charges costs per bar against realised turnover, so net Sharpe and net
  drawdown reflect them (the old code subtracted a scalar from an annualised
  number and left the risk metrics on a gross series);
- never clips the portfolio return series, and masks `|1-day return| > 50%` at
  the *asset* level instead, per the known unadjusted corporate actions in
  `1d_wide` (24 such bars in this panel);
- guarantees `gross_annual_return / annual_volatility == gross_sharpe` exactly,
  so a figure set that violates it did not come from here;
- refuses to reindex a weight frame whose index does not match the price frame.

`edge/tests/research/test_portfolio.py` is the regression test. Its central case
feeds the simulator a signal that *is* the current bar's realised return —
perfect same-bar correlation, zero forward information. An honest simulator
prints noise (measured: −8.7%, Sharpe −0.44); the leaking alignment prints
**+1326%, Sharpe 101**. A companion test feeds a genuinely predictive signal, so
the suite cannot be passed by always returning zero.

## What this does not do

It does not make anything tradeable. It removes a false positive. The corrected
PEAD models are NO-GO on their pre-registered gates, and now for the honest
reason. Per [`xs_v3/DECISION_RECORD.md`](../runs/xs_v3/DECISION_RECORD.md) the
2024-08-01+ holdout is spent, so improvements measured on it are not evidence.

---

## Follow-up corrections (2026-08-16)

Three further instances of the same defect class were closed:

1. **`edge/tools/gcp_experiment_pead_v2.py`** carried the identical lag-0
   pattern (`port_ret = (long_w * daily_ret).sum(axis=1) - ...` with
   `daily_ret = close_prices.pct_change(1)` and no shift). It was tracked as a
   KNOWN GAP in `edge/tests/research/test_portfolio_primitive_guard.py`'s
   ALLOWLIST. All portfolio accounting now routes through
   `edge.research.portfolio.simulate_long_short` with `execution_lag=1`, and the
   file was removed from the ALLOWLIST and added to the guard's migrated-tools
   positive control. Verified with a synthetic smoke test: a pure-noise signal
   prints ~zero edge at lag 1, while an oracle signal is still detected.

2. **`edge/tools/backtest_vol_timing.py`** entered options on the same bar
   whose end-of-day vol-complex data (VIX, term_slope, SKEW) formed the signal,
   pricing the entry with that same bar's spot and VIX. Entries are now queued
   on bar `i` and filled at bar `i+1`'s open — one full bar of execution lag.

3. **`edge/research/daily_data.py`** now supports point-in-time universe
   filtering: `load_daily_universe(..., pit_instruments=<dated-interval
   instruments file>)` drops rows outside each symbol's membership spans and
   drops symbols the file never admits. The default remains unfiltered so
   existing preregistered universes are unchanged; opting a runner into PIT
   filtering is a protocol change that belongs in a new preregistration.

`edge/research/robustness.py` additionally gained `monte_carlo_robustness`, a
bootstrap-of-returns diagnostic (max-drawdown distribution, probability of
loss by holding period, annual compounded-return CI) wired into the daily
directional runner's artifact as a supplemental, non-promotion diagnostic.

---

*Simulated / historical only. Not financial advice.*
