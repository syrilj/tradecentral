# Quant Research Tabs — Methodology & Implementation Contract

Four new research tabs inside the existing TradeCentral app: **Statistical Arbitrage**,
**Realised Volatility**, **Mean Reversion**, **Momentum Trading**. This document is the
authoritative methodology and the build contract every agent implements against.

## 0. Governing principles (hard rules)

1. **No fabricated data.** Every number rendered is computed from `data/1d`, `data/1d_wide`
   parquets (via `research/vpa_bars.load_bars`) or another real existing source. Missing
   data → explicit `null` + reason string, never a placeholder.
2. **No lookahead.** Any rolling/estimated quantity used by the signal or backtest at
   time t is computed from bars ≤ t only. Positions established from the signal computed
   on close T earn returns starting T+1 (signal-to-execution lag of one full bar).
3. **One annualization.** Daily log returns → annualize variance by ×252, vol by √252.
   Sharpe = mean(daily net return)/std(daily net return) × √252. Every metric states
   its frequency. Never mix.
4. **Costs on turnover.** cost_t = cost_bps/10_000 × Σ|Δw_t| (gross one-way bps, applied
   on every position change including leg rebalances). Default 5 bps per leg turnover.
5. **Reuse, don't duplicate.** Shared math goes in one module (`research/quant_core.py`);
   tabs import it and the existing `research/vol_targeting.py`, `research/statistics.py`,
   `research/portfolio.py`, `research/costs.py` where those already cover a need.
6. **Honest stats.** Significance ≠ profitability. Non-stationary inputs are never fed to
   stationary models without a caveat field. Every payload carries caveats where a
   metric is conditional or unreliable.
7. Adjusted prices are used for return/spread math (the parquets are already
   split/dividend-adjusted Yahoo EOD). Forward-fill is only allowed to bridge
   non-simultaneous holidays in PAIR alignment, and only when the gap is ≤ 5 sessions;
   a filled bar earns 0 return and is flagged in `pair_meta.filled_bars`.

## 1. Shared layer — `research/quant_core.py`

New module. Pure functions, numpy/pandas, no FastAPI imports, no side effects.
Existing code is reused, not copied: `realized_volatility`/`ewma_volatility` from
`research/vol_targeting.py` are re-exported; Sharpe significance reuses
`research/statistics.py` where applicable.

API (exact signatures — all tabs code against these):

```python
ANNUAL = 252

def simple_returns(close: pd.Series) -> pd.Series          # P_t/P_{t-1} - 1
def log_returns(close: pd.Series) -> pd.Series             # ln(P_t/P_{t-1})
def rolling_mean(s: pd.Series, window: int) -> pd.Series   # trailing, min_periods=window
def rolling_std(s: pd.Series, window: int) -> pd.Series    # trailing, ddof=1
def rolling_zscore(s: pd.Series, window: int) -> pd.Series # (s - rolling_mean)/rolling_std, NaN until window obs
def ema(s: pd.Series, window: int) -> pd.Series           # span=window
def drawdown(equity: pd.Series) -> pd.Series              # equity/cummax - 1
def max_drawdown(equity: pd.Series) -> float
def sharpe(daily_returns: pd.Series) -> float | None      # None if std==0 or n<2
def cagr(equity: pd.Series) -> float | None               # (last/first)^(252/n) - 1, trading-day index
def beta(y: pd.Series, x: pd.Series) -> float | None      # cov(x,y)/var(x) over aligned overlap
def correlation(y: pd.Series, x: pd.Series, window: int | None = None) -> pd.Series | float
def autocorrelation(s: pd.Series, lag: int = 1) -> float | None  # pearson on s[t] vs s[t-lag], demeaned
def rolling_ols_beta(y: pd.Series, x: pd.Series, window: int) -> pd.Series  # beta_t uses only data <= t
def engle_granger(y: pd.Series, x: pd.Series) -> dict
    # {'statistic', 'p_value' (or None), 'critical_values': {'1%':-3.90,'5%':-3.34,'10%':-3.04},
    #  'n_obs', 'window_note'} — OLS of y on x (with intercept), ADF on residuals.
    # p_value via statsmodels adfuller if importable, else None + critical values only.
def ou_half_life(spread: pd.Series) -> dict
    # ΔS_t = α + λ·S_{t-1} + ε_t → {'lambda','half_life' (None if λ>=0 or p>=0.05),
    # 'mean_reverting': bool, 'n_obs'} — OLS slope t-stat decides mean_reverting.
def hurst_exponent(s: pd.Series, max_lag: int = 100) -> float | None  # R/S style; None if n<60
def transaction_costs(weights: pd.DataFrame, cost_bps: float) -> pd.Series  # Σ|Δw|×bps/1e4
def equity_curve(daily_strategy_returns: pd.Series) -> pd.Series         # (1+r).cumprod(), starts 1.0
def to_records(df: pd.DataFrame, cols: list[str]) -> list[dict]         # date→iso, NaN→None, JSON-safe
```

**Backtest convention used by all tabs** (each tab implements its own position engine but
shares these rules): signal frame `sig_t` computed from data ≤ t; position frame
`pos_t = sig_t.shift(1)` (T+1 execution, no same-bar round trip); gross return
`r_t = Σ pos_{t-1}·ret_t`; net `= gross − transaction_costs`; equity from net.
A state machine (entry/exit/stop/max-hold) produces `sig` with **hysteresis** — position
persists until an exit/stop/max-hold condition fires, so thresholds cannot flap.

## 2. Tab: Statistical Arbitrage  (`/stat-arb`)

**Question:** *Is this pair's relative value statistically meaningful right now, how far
is the spread from equilibrium, and would trading it historically have worked?*
Default pair Y=V, X=MA (user-entered, any supported symbols).

Data: `load_bars(y)`, `load_bars(x)`; inner-join on date; require ≥ 252 aligned bars
else `insufficient_overlap` error. `price_mode` param: `adjusted` (default — levels in
dollars, spread readable as $ of mispricing) or `log` (log-price spread = log ratio
hedge, appropriate when the two price scales differ wildly or the relationship is
proportional; note: log-mode beta approximates the ratio hedge and spread is in log
units, harder to read but scale-free). Raw close is offered but discouraged in a caveat
(split/dividend jumps would masquerade as spread moves).

Hedge ratio: `static` = full-sample OLS β (shown as *diagnostic only* — in a backtest it
leaks future info, so the backtest NEVER uses static beta) or `rolling` (default, window
126; options 60/126/252) via `rolling_ols_beta` (uses only data ≤ t).

Spread `S_t = Y_t − β_t·X_t` (or log variant). Z-score `z_t = rolling_zscore(S, z_window
=60)` — window params separate from beta window. Engle–Granger over the last `eg_window`
(=504, or full overlap if shorter) bars + over a recent 252-bar window; payload carries
both with interpretation text and the explicit caveat: cointegration is sample-dependent
and unstable; significance ≠ profitability; non-cointegrated pairs get a warning banner,
NOT a block.

Signal state machine (all configurable): flat → short spread when z > `z_entry`(2.0);
long when z < −entry; exit to flat when |z| < `z_exit`(0.5); stop when |z| > `z_stop`
(3.5, optional, null disables); force exit after `max_hold`(60) bars in trade. State
persists; no per-bar flapping.

Position construction: **beta-hedged** (default): $N notional in Y, $−β·N in X, where β
is the rolling beta at entry (beta refreshed only at rebalance points to limit churn);
alternative `dollar` mode: ±$N/2 each leg. Payload field `hedge_mode` states which is
used, and the UI renders it. Position weights renormalized daily to the current leg
prices (constant-notional, not buy-and-hold drift), with leg-rebalance turnover costed.

Backtest: both legs' P&L net of costs; metrics = CAGR, vol, Sharpe, max DD, n trades,
win rate, avg/median trade days, turnover, plus **buy-both-legs-and-hold benchmark over
the same window**. Diagnostics: rolling beta series + beta stability (std of Δβ),
rolling 126d correlation, spread/z chart, current z, days-in-trade distribution,
half-life (only shown when `ou_half_life` reports `mean_reverting=True`, else rendered
as "process not measurably mean-reverting (λ ≥ 0)"), residual ACF lags 1–10.

## 3. Tab: Realised Volatility  (`/realized-vol`)

**Question:** *How volatile has this been, vs implied where available, and what would
vol targeting have done?* Default SPY.

Returns: **log returns** (default, time-additive, correct for variance aggregation);
simple returns available as a param choice with caveat they are not additive. RV over
rolling `window`(21): `RV_var = Σ_{t-w+1..t} r²`, `RV_ann = sqrt(RV_var × 252)` —
exactly ONE annualization (rolling variance ×252, then sqrt). Payload exposes
`rolling_variance`, `rolling_std` (same window, non-annualized), and `annualized_rv` as
distinct fields so the UI never double-annualizes. Re-export the existing
`realized_volatility`/`ewma_volatility` from `vol_targeting.py` for the EWMA comparison
series.

Intraday: `data/1h/{SYM}.parquet` is real (588 symbols). When present, hourly RV
`RV_day = Σ r_hourly² × (annualization factor = 252 × bars_per_day(=6.5→7))` is offered
as a comparison series vs close-to-close; gaps/half-days flagged. NO 1m/5m claims unless
the parquet exists for that symbol — check, don't assume (LSE candles exist for some
symbols; treat as unavailable → `intraday_available: false`). No microstructure
noise-adjustments (no Yang-Zhang) — state plainly this is close-to-close RV.

Implied vol: the app's options chain data (`data/option_chains` + options intelligence)
provides IV per contract; where an ATM IV series is derivable, show `implied_series` and
`VRP = IV_ann − RV_ann` (21d lookback), with percentile rank of current VRP within the
available window, sign interpretation ("positive = options priced richer than realized;
historically a premium to variance sellers, NOT an automatic trade"), and the caveat
that IV sample may be short. **VIX**: only if ^VIX daily bars can be loaded from the
existing data sources (check `data/1d` for `^VIX`); VIX is described as "SPX-derived
annualized 30-day implied volatility index — not SPY's IV". If absent: `vix_available:
false`, no fabrication, no yfinance-fetch at request time (API must stay offline-fast);
a `vix_missing` reason string.

Vol-target overlay: `w_t = clip(target_vol / RV_ann_{t−1}, floor, cap)` — RV from data ≤
t−1, applied to t's return (T+1). target_vol default 0.15 (15% ann), cap 1.5, floor 0.25.
Compare vs buy-and-hold on the same range: return, vol, Sharpe, max DD, avg exposure,
turnover, costed at `cost_bps`. Reuse `vol_target_scale`/`apply_vol_target` logic where
signatures fit; otherwise implement the scalar overlay per §1 rules.

Diagnostics (curated only): current RV + percentile (within 3y window), vol-of-vol (std
of 21d RV over 252d), ACF of squared returns lags 1–10 (volatility clustering
evidence), current target exposure. No regime labels, no forecasts.

## 4. Tab: Mean Reversion  (`/mean-reversion`)

**Question:** *Is this asset stretched vs its own recent behavior, is the regime
suitable for fading, and did that work historically?* Default AAPL, 20-day window.

MA: `sma` (default, equal weight — the classic Bollinger-style baseline) or `ema`
(span=window; faster, reacts sooner, signals fire earlier and more often — stated in the
UI copy). `z_t = (P_t − μ_t)/σ_t` on the **selected MA and rolling std of price**
(trailing window only). Signal machine: long when z < −`z_entry`(2), short when z >
+entry (shorting configurable: `both`/`long_only`/`short_only`); exit when |z| <
`z_exit`(0.5) **or price crosses the MA** (`exit_on: 'z' | 'mean_cross'`, configurable —
mean-cross exits earlier in persistent trends, z-exit holds longer); optional stop
`z_stop`(3.5) for adverse continuation; max_hold(40). T+1, costs, equity curve,
drawdown, trade distribution, vs buy-and-hold same range.

Regime diagnostics — only the ones reliable at daily frequency:
- 1-day return autocorrelation with t-stat-ish caveat (n≈250 obs → SE≈1/√n; |ACF| < 2·SE
  is noise; state this instead of a star-rating).
- Trend strength: 252d total return vs its own vol (|ret|/vol as a rough signal-to-noise;
  labelled as such).
- OU half-life **fitted on the rolling z-series or log-price deviations, never raw
  price** (raw price is non-stationary; fitting OU to it produces garbage — the payload
  includes a `fit_target: 'z_series'` field stating what was fit). `ou_half_life` gates
  on λ<0 and slope significance as in §1.
- Hurst exponent is **omitted** — R/S estimates on ~500 daily bars have huge variance
  and no decision value here; a `diagnostics.hurst_omitted` note explains why. (No fake
  sophistication.)

## 5. Tab: Momentum  (`/momentum`)

**Question:** *Is this asset exhibiting persistent time-series momentum, and how does it
rank cross-sectionally right now?* Two SEPARATE panels — never blended.

**A. Time-series momentum** (single symbol, default SPY): `M_t = P_t/P_{t−L} − 1`
(price-ratio return over lookback L; identical to cumulative log-return for the same
window — both shown, formula stated). Lookbacks 63/126/252 + **12-1**: return from t−252
to t−21 (skip the most recent month — the standard academic construction; skipping
avoids the short-term reversal that contaminates 12-0). Signal: long when M_t > 0 (+
vol-target optional off by default), flat otherwise (`ts_mode: 'sign'`); backtest each
lookback separately with T+1, costs, vs buy-and-hold. Excess vs SPY when symbol ≠ SPY.

**B. Cross-sectional momentum** (universe = the `data/1d_wide` intersection that has ≥
`formation+1` bars, default formation 126, top/bottom `bucket`=5 (quintiles), rebalance
every `rebalance`(21) bars): at each rebalance date t_k, rank symbols by formation
return computed on data ≤ t_k (formation window strictly ends at t_k; holding starts
t_k+1). Equal-weight top bucket long; bottom bucket short when `shorting: true` (else
long-only top bucket vs universe-average benchmark — stated explicitly). Costs on each
rebalance turnover. NO CRSP-style claims: payload declares the universe (symbol count,
date range, survivorship caveat — the parquet universe is today's constituents, which
biases backtests upward; this caveat is rendered in the UI, not buried). Reuse
`simulate_long_short` from `research/portfolio.py` for the L/S engine where it fits.

Diagnostics: current momentum per lookback + percentile within 3y, cross-sectional rank
of the selected symbol, universe breadth (% symbols with positive formation return),
cross-sectional return dispersion (std of formation returns), turnover, drawdown, and
"why it's working/failing" attribution: rolling 63d strategy return vs benchmark.

## 6. API contracts (all under `/api/quant/…`, dispatch added by integrator)

All: `GET`, params from query string, JSON payload
`{'ok': True, 'asof': iso, 'symbol(s)': …, 'params': {echo}, …tab fields…,
'caveats': [str]}`. Errors: `{'ok': False, 'error': code, 'detail': str}` with 200 +
ok:false (matches existing api_server style where payload carries status). NaN → null.
Series as `{'date': iso, …}` record arrays, capped to last 1500 points.

| endpoint | params | key response fields |
|---|---|---|
| `/api/quant/stat-arb` | y,x,price_mode,beta_mode,beta_window,z_window,z_entry,z_exit,z_stop(optional),max_hold,cost_bps,hedge_mode,eg_window | pair_meta, eg_static, eg_recent, beta_series, spread_series, z_series, signal, trades, backtest, benchmark, diagnostics |
| `/api/quant/realized-vol` | symbol,return_type,window,target_vol,cap,floor,cost_bps | rv_series (var/std/ann), intraday(intr_avail flag), implied(vix/iv availability), vrp, vol_target{overlay_series, stats vs bnh}, diagnostics |
| `/api/quant/quant-mr` | symbol,window,ma,exit_on,z_entry,z_exit,z_stop(optional),max_hold,direction,cost_bps | z_series, signal, trades, backtest, benchmark, regime_diagnostics |
| `/api/quant/momentum` | symbol,lookbacks,formation,bucket,rebalance,shorting,cost_bps | ts{per-lookback series+backtest}, xs{ranks, current_buckets, backtest, universe_meta}, diagnostics |

## 7. UI contract

Views: `StatArbView.vue`, `RealizedVolView.vue`, `MeanReversionView.vue`,
`MomentumView.vue` in `dashboard/src/views/`. Each follows the VannaView pattern:
`useResource` + typed api function from `@/api`, `Panel` + `LoadingState` components,
`linearScale`/`niceTicks` from `@/charts`, `@/format` helpers, route-query symbol
convention (`router.replace({name, query})`), explicit `unavailableReason` (no fabricated
placeholder numbers, `DASH` for null), responsive chart geometry with `useChartSize` where
the existing views use it. Config controls (symbol/pair inputs, window selects, threshold
inputs) re-run the fetch on change. Caveats render as a muted footnote strip. All four
land in `primaryNav` (App.vue) with `tab: true` and `router.ts` routes
(`meta: {title, index}` continuing the existing sequence) — integrator owns those two
files. Colors/typography/spacing come from existing CSS tokens; no new design language.

## 8. File ownership (merge gate)

| owner | files |
|---|---|
| core agent | `research/quant_core.py`, `tests/test_quant_core.py` |
| stat-arb agent | `research/quant_stat_arb.py`, `tests/test_quant_stat_arb.py`, `dashboard/src/views/StatArbView.vue`, `dashboard/src/statArbContracts.ts` |
| rvol agent | `research/quant_realized_vol.py`, `tests/test_quant_realized_vol.py`, `dashboard/src/views/RealizedVolView.vue`, `dashboard/src/realizedVolContracts.ts` |
| mr agent | `research/quant_mean_reversion.py`, `tests/test_quant_mean_reversion.py`, `dashboard/src/views/MeanReversionView.vue`, `dashboard/src/meanReversionContracts.ts` |
| momo agent | `research/quant_momentum.py`, `tests/test_quant_momentum.py`, `dashboard/src/views/MomentumView.vue`, `dashboard/src/momentumContracts.ts` |
| integrator | `tools/api_server.py` dispatch, `dashboard/src/api.ts`, `dashboard/src/router.ts`, `dashboard/src/App.vue` |

Merge gate per tab: python tests pass (`pytest tests/test_quant_*.py`), no edits outside
owned files, every payload field either computed or null-with-reason, T+1 shift present
in backtest code, caveats present.

## 9. Backtest integrity checklist (applies to every tab)

- [ ] position = signal.shift(1); first valid position after full warm-up windows
- [ ] rolling stats: `min_periods=window`, trailing windows only
- [ ] beta/z/half-life/OU params at t use bars ≤ t
- [ ] XS ranking strictly before holding period
- [ ] costs on |Δweight| including leg rebalances
- [ ] benchmark same date range, same cost convention (or explicit zero-cost note)
- [ ] pair alignment flags forward-filled bars (≤5 sessions) as 0-return
- [ ] metrics annualized once, via ANNUAL=252, √252 for vol
- [ ] insufficient-data → error payload, not a partial chart