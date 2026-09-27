# Predation Tab — Design Spec

Implements **Carlin, Lobo & Viswanathan (2007), "Episodic Liquidity Crises:
Cooperative and Predatory Trading"** (Journal of Finance LXII:5) as a live
screening + price-target surface on the `edge/` stack.

**Goal (user's words):** *find stocks that are getting hit like this, figure out
where the price is trying to go to, and where a potential bottom will be* — with
a mean/reversion cloud and volume-price analysis as the supporting read.

---

## 1. The model we are implementing

### 1.1 Price equation (paper eq. 1)

```
P_t = U_t + γ·X_t + λ·Y_t
dX_t = Y_t dt,     dU_t = σ dB_t   (martingale — no drift)
```

| term | meaning |
|---|---|
| `U_t` | fundamental value (expected future dividends). **This is "where price is trying to go".** |
| `γ·X_t` | **permanent** impact of strategic-trader inventory `X_t`. Does not revert. |
| `λ·Y_t` | **temporary** impact of the *rate* of trading `Y_t`. Reverts to zero the moment forced trading stops. **This is the snapback.** |

The whole tab is one idea: **decompose the current price into these three
pieces, and show the user the piece that must revert.**

### 1.2 Equilibrium trading path (paper Result 1, eq. 5–7)

```
Y_i(t) = a·e^(−((n−1)/(n+1))·(γ/λ)·t)  +  b_i·e^((γ/λ)·t)
```

- First term = **racing**: everyone dumping early, decaying exponentially.
- Second term = **fading**: predators reversing to buy back. `Σ b_i = 0`.
- Aggregate over one distressed + one predator: `Y_total = 2a·e^(−(1/3)(γ/λ)t)`
  — the `b` terms cancel, so aggregate flow decays cleanly at rate `k`.

**Decay rate** `k = ((n−1)/(n+1))·(γ/λ)`.

### 1.3 Where the bottom is

Along `[0, T]` price falls **monotonically** (dP/dt = `2a·e^(−kt)·(2γ/3)` < 0 for
a sell). At `t = T` the forced trading completes, `Y → 0`, and the temporary term
`λ·Y_T` **snaps back**. Therefore:

- **The bottom is at `t = T`** — the moment the forced liquidation finishes.
- **Snapback magnitude = `λ·|Y_T|`.**
- **Post-event settle = `U_0 + γ·Δx`** — the pre-event level plus the permanent
  impact of the block. Price does *not* return all the way up.

This gives the three numbers the tab exists to produce:
**settle (target), bottom (level), T (timing).**

### 1.4 γ/λ is the master variable (paper Result 4, §II.B)

- **High γ/λ** → cooperation is sustainable → liquidity looks smooth *most of the
  time*, but episodes are **rare, violent, and short-lived**. Best snapback
  candidates. Label `regime: "episodic"`.
- **Low γ/λ** → cooperation cannot be supported → **chronic** predation, grinding
  decline, no clean reversal. Label `regime: "chronic"`. These are traps.

Surface `ρ = γ/λ` and its universe percentile prominently. It is the paper's
single headline empirical claim.

### 1.5 Contagion (paper §II.B)

Cooperation sustained *across* markets means that when it breaks, it breaks
everywhere at once. Operationalise as: ≥ N symbols in the same sector
simultaneously in `racing` phase → emit a `contagion` flag.

---

## 2. Estimation

### 2.1 Signed flow proxy `y_t`

We have no tick data. Build an ADV-normalised signed flow proxy from two
independent sources and **expose both components** so the UI can show which one
drove the reading. Label it a proxy in the UI — it is not true signed order flow.

1. **CLV (close location value)** from OHLC — Wyckoff/VPA-standard:
   ```
   clv_t = ((C−L) − (H−C)) / (H−L)          ∈ [−1, 1]   (0 if H==L)
   ```
2. **FINRA off-exchange short ratio** `s_t ∈ [0,1]` from
   `data/finra_shortvol/short_vol.csv` (`date,symbol,short_ratio`, 2018-08-01→):
   ```
   finra_t = 1 − 2·s_t                      (s=0.5 neutral, s>0.5 net selling)
   ```

Fuse, then normalise by 20-session ADV:
```
raw_t = V_t · ( w·clv_t + (1−w)·finra_t )
w = 0.5 when short_ratio present for that (symbol, date), else w = 1.0
y_t = raw_t / ADV20_t
```

### 2.2 Identifying γ and λ (exactly identified — this is the key trick)

Differencing the price equation at daily frequency (`Δt = 1`, so `ΔX_t = Y_t`):

```
ΔP_t = ΔU_t + γ·Y_t + λ·(Y_t − Y_{t−1})
```

so regressing the **return** on contemporaneous and lagged flow:

```
r_t = β₀·y_t + β₁·y_{t−1} + ε_t
```

gives, directly:

```
λ̂ = −β₁
γ̂ =  β₀ + β₁
σ̂_U = std(ε)        ← the fundamental diffusion, used for the cloud width
```

Details:
- Rolling window: **252 sessions**, min 120 obs.
- OLS, no intercept (returns are ~zero-mean at this horizon); report `r2`,
  `n_obs`, and heteroskedasticity-robust (HC1) standard errors `se_gamma`,
  `se_lambda`.
- **Validity gate:** require `λ̂ > 0` **and** `γ̂ > 0` (both impacts must be
  positive for the model to hold). If violated → `impact_fit.stable = false`;
  the symbol is **excluded from ranking but still returned with the flag set**.
  Never silently drop it.

### 2.3 Recovering `n` (how many are racing)

Fit `log|y_t| = α − k·t` over the event window (OLS; require fit `r2 ≥ 0.3`).
With `ρ = γ̂/λ̂`:

```
(n−1)/(n+1) = k/ρ    ⇒    n̂ = (1 + k/ρ) / (1 − k/ρ)
```

- Valid only for `0 < k/ρ < 1`.
- If `k/ρ ≥ 1` → `n_hat = null`, `racing = "extreme"` (decay faster than the
  n→∞ bound; the model's upper bound is violated, say so rather than fabricating).
- `n̂ ≥ 2` ⇒ predators are present, not just a lone liquidator.

### 2.4 Block size `Δx̂` and completion time `T̂`

Aggregate flow decays as `Y_t = Y_0·e^{−kt}`:

```
remaining  = |Y_now| / k
Δx̂        = Q_done + Y_now/k          (Q_done = observed cumulative y over event)
T̂_remain  = ln( |Y_now| / (ε·|Y_peak|) ) / k,   ε = 0.10, floored at 0
```

### 2.5 The three levels

Let `P_pre` = close at event start (also report the pre-event volume-profile POC
as a cross-check, §2.7).

```
P_settle = P_pre · (1 + γ̂·Δx̂)                     # where price is trying to go
Y_T      = Y_now · e^{−k·T̂_remain}
P_bottom = P_settle · (1 + λ̂·Y_T)                  # the trough, at t = T̂
snapback_pct = (P_settle / P_bottom − 1) · 100
days_to_bottom = T̂_remain
```

Also compute `P_bottom_alt = P_now·(1 + λ̂·(Y_T − Y_now))` (projecting only the
*additional* pressure still to come) and report both; if they disagree by more
than 25% of the gap, flag `targets.reconciled = false`.

Confidence intervals propagate the regression SEs:
```
settle_lo/hi = P_pre · (1 + (γ̂ ∓ 1.96·se_gamma)·Δx̂)
bottom_lo/hi likewise through se_lambda
```

### 2.6 Phase classification (racing → fading → recovering)

The paper's own dynamic *is* the trade timeline. **The fade is the entry.**

| phase | condition | meaning |
|---|---|---|
| `racing` | `|y_t|` at/near event peak, `T̂_remain > 1.5` | still being dumped, bottom ahead |
| `fading` | `|y_t| < 0.4·|y_peak|` and `T̂_remain ≤ 1.5` | liquidation finishing, **bottom imminent/now** |
| `recovering` | `y_t` sign flipped positive while price still < settle | predators buying back |
| `settled` | `|y_t|` back inside its 1σ baseline band | over |

### 2.7 Volume-price analysis (independent read on `U`)

Volume profile over the 60 sessions **before** event start:
- 50 price bins across the range; distribute each session's volume across the
  bins its `[low, high]` spans, weighted triangularly toward the close.
- **POC** = highest-volume bin (where the business actually got done).
- **Value area** = smallest contiguous band around POC holding 70% of volume →
  `VAH` / `VAL`.
- **LVN below** = lowest-volume bin below current price — the air pocket price
  travels through fast; a second, independent estimate of where the bottom prints.

**Agreement test:** if `P_settle ∈ [VAL, VAH]` → `agreement: "confirms"`. If
`P_settle` is outside and on the opposite side from `P_now` → `"conflicts"`.
Else `"neutral"`. Two independent methods agreeing is the confidence signal.

### 2.8 Event detection / score

A symbol is in a predatory liquidity event when, over a trailing 10-session window:

| id | test | why |
|---|---|---|
| D1 | cumulative `Σy` ≤ 5th percentile of its own 2-year distribution | persistent one-sided selling |
| D2 | `temp_share = |λ̂·y_now| / |return over event| ≥ 0.35` | rate-driven, not news-driven |
| D3 | exponential decay fit `k > 0`, `r2 ≥ 0.3` | the racing signature |
| D4 | Parkinson vol ratio vs 60-session baseline ≥ 1.5 | illiquidity spike |
| D5 | `|γ̂·Σy| < |total drawdown|` | price overshoots what permanent impact justifies |

`predation_score` ∈ [0,100] = weighted blend of the five normalised sub-scores
(weights: D1 0.25, D2 0.25, D3 0.20, D4 0.15, D5 0.15). Rank by it.

---

## 3. Non-negotiable correctness rules

1. **No lookahead.** Every value at date `t` uses only data with index ≤ `t`.
   Mirror `tests/research/test_flow_state_no_lookahead.py`: shuffle/truncate
   future rows and assert historical outputs are bit-identical.
2. **Sealed holdout.** Validation must not touch data on/after **2026-07-13**.
3. **Every estimate carries uncertainty.** SEs/CIs in the payload; unstable fits
   are labelled `stable: false`, never hidden or silently dropped.
4. **Signed flow is a proxy** — say so in the UI, and show the CLV and FINRA
   components separately.
5. **Research surface, not advice.** Respect the repo's existing
   `decision_authorized` / `live_capital_authorized` flags. No order tickets.
6. **Fail loud.** A missing FINRA panel degrades `w` to 1.0 and sets
   `flow_source: "clv"` in the payload — it does not silently change the numbers
   without saying so.

---

## 4. Payload contract (fixed — frontend and backend build against this)

### `GET /api/predation-scan?limit=40`

```jsonc
{
  "asof": "2026-08-09 12:00:00 UTC",
  "universe_size": 557,
  "evaluated": 540,
  "flow_source": "clv+finra",           // or "clv"
  "finra_coverage_pct": 82.1,
  "holdout_start": "2026-07-13",
  "contagion": [
    { "sector": "Regional Banks", "count": 7, "symbols": ["..."] }
  ],
  "candidates": [ /* PredationRow */ ],
  "all_candidates": [ /* incl. unstable fits, for transparency */ ],
  "notes": ["..."]
}
```

### `PredationRow`

```jsonc
{
  "symbol": "XYZ",
  "sector": "Regional Banks",
  "price": 38.40,
  "pre_event_price": 46.10,
  "event_start": "2026-07-28",
  "event_days": 9,

  "predation_score": 82.4,
  "phase": "fading",                     // racing | fading | recovering | settled
  "regime": "episodic",                  // episodic | chronic | unknown

  "gamma": 0.031, "gamma_se": 0.008,
  "lambda_": 0.094, "lambda_se": 0.019,  // note trailing underscore — `lambda` is reserved in py
  "rho": 0.33, "rho_pct": 78.0,

  "impact_fit": { "r2": 0.21, "n_obs": 252, "stable": true },
  "k_decay": 0.19, "n_hat": 3.1, "racing": "normal",   // racing: normal | extreme

  "flow": {
    "cum_signed_adv": -3.21,
    "y_now": -0.41, "y_peak": -0.93,
    "clv_component": -0.28, "finra_component": -0.13
  },

  "drawdown_pct": -16.7,
  "temp_share": 0.52, "perm_share": 0.48,

  "targets": {
    "settle": 43.90, "settle_lo": 42.10, "settle_hi": 45.70,
    "bottom": 37.10, "bottom_lo": 35.80, "bottom_hi": 38.40,
    "bottom_alt": 37.55, "reconciled": true,
    "days_to_bottom": 1.2,
    "snapback_pct": 18.3
  },

  "vpa": {
    "poc": 44.20, "vah": 46.80, "val": 42.30,
    "lvn_below": 37.60, "agreement": "confirms"
  },

  "flags": ["earnings_in_window"]
}
```

### `GET /api/predation/{SYMBOL}`

`PredationRow` plus:

```jsonc
{
  "history": [ { "date": "2026-05-01", "close": 46.1, "volume": 1.2e6,
                 "y": -0.11, "cum_y": -0.11 } ],          // ~120 sessions
  "cloud":   [ { "h": 0, "date": "2026-08-09", "center": 38.9,
                 "lo1": 37.6, "hi1": 40.2, "lo2": 36.3, "hi2": 41.5 } ],
  "vpa_bins":[ { "price_lo": 42.0, "price_hi": 42.5, "volume": 3.1e6,
                 "is_poc": false, "in_value_area": true } ],
  "trading_rate_fit": { "dates": ["..."], "observed": [-0.9], "fitted": [-0.88] },
  "diagnostics": { "residual_vol": 0.021, "window": 252, "warnings": [] }
}
```

### The mean cloud

For `h = 0 … H` where `H = ceil(T̂_remain) + 10`:

```
Y_h      = y_now · e^{−k·h}
center_h = P_settle · (1 + λ̂·Y_h)
width_h  = P_pre · sqrt( σ̂_U²·h + (se_gamma·Δx̂)² + (se_λ·Y_h)² )
lo1/hi1  = center_h ∓ 1·width_h
lo2/hi2  = center_h ∓ 2·width_h
```

The centre dips to `P_bottom` at `h = T̂_remain`, then rises asymptotically to
`P_settle`. The band widens with `√h` from the fundamental diffusion plus fixed
parameter uncertainty. **That cone is the "mean cloud".**

---

## 5. Files to create

| path | contents |
|---|---|
| `research/predatory_liquidity.py` | §2.1–2.6 core math. Pure, no I/O. |
| `research/volume_profile.py` | §2.7 VPA. Pure, no I/O. |
| `tools/predation_scan.py` | universe orchestration → payload. Pure, in-memory in/out (mirror `tools/momentum_scan.py`). |
| `tools/api_server.py` | +`/api/predation-scan`, +`/api/predation/{SYM}`, cached like `_momentum_scan_payload`. |
| `dashboard/src/views/PredationView.vue` | the tab. |
| `dashboard/src/components/PredationCloudChart.vue` | price history + forward cloud + settle/bottom lines + VPA histogram on the right axis. |
| `dashboard/src/components/RacingFadeChart.vue` | observed vs fitted `Y_t` — the paper's Figure 3. |
| `dashboard/src/api.ts` | types + `predationScan()` / `predation(sym)`. |
| `dashboard/src/router.ts`, `App.vue` | route `/predation`, title `Predation`, index `16`. |
| `tests/research/test_predatory_liquidity.py` | incl. **recovery test**: synthesise a path from known γ, λ, n and assert the estimator recovers them. |
| `tests/research/test_volume_profile.py` | POC/value-area correctness on hand-built profiles. |
| `tests/research/test_predation_no_lookahead.py` | §3.1. |
| `tests/test_predation_scan.py`, `tests/test_predation_endpoint.py` | scan + endpoint. |
| `tools/validate_predation.py` | §6. |

## 6. Validation (this is what makes it real)

`tools/validate_predation.py`, pre-holdout data only (< 2026-07-13):

- Find all historical events; from each `fading`-phase entry, measure realized
  forward returns at +1/+3/+5/+10 sessions.
- Report: hit rate vs. a matched-control sample (`research/matched_controls.py`
  already exists — reuse it), mean fraction of predicted snapback actually
  captured, and calibration of `days_to_bottom` (predicted vs. realised).
- **Break out by `ρ` decile.** The paper predicts high-`ρ` names give the
  cleanest reversals. If that gradient is absent, say so plainly in the output —
  a null result is the honest deliverable, not a reason to tune until it passes.
