# Intraday Options Model — GEX × VWAP × Microstructure

Parameter-level distillation of the supplied research doc (prose exposition dropped,
every threshold / formula / gate retained), plus a gap analysis against this repo.

## 1. Dealer gamma

```
GEX_$      = Σ Γ_i · OI_i · M · S² · 0.01 · Φ_i      (per 1% move)
GEX_share  = Σ Γ_i · OI_i · M · Φ_i                  (per $1 move)
Δ_dealer   = Σ Δ_i · OI_i · M · Φ_i ;  ∂Δ_dealer/∂S = GEX_share
```
Sign convention Φ: dealers net **long** gamma on OTM calls, net **short** gamma on
OTM puts (public buys puts, sells calls). Refine intraday by reclassifying prints
against NBBO instead of trusting static OI.

- `GEX > 0` → counter-cyclical hedging → vol dampening, mean reversion to high-gamma strikes.
- `GEX < 0` → pro-cyclical hedging → vol amplification, trend acceleration.
- Empirical anchor: +1σ in dealer net 0DTE gamma ⇒ ≈ −7.3% intraday variance.

Derived levels: **Gamma Flip / HVL** (Σ GEX = 0, the regime classifier),
**Call Wall** (max positive call gamma strike), **Put Wall** (max net put gamma
strike), **Net DEX** (aggregate dealer delta imbalance).

## 2. VWAP + volume profile

```
VWAP_t = Σ P_k V_k / Σ V_k              P_k = (H+L+C)/3
σ_t    = sqrt( Σ V_k (P_k − VWAP_t)² / Σ V_k )
Band   = VWAP_t ± n·σ_t                 n ∈ {1,2,3}
```
Profile: **POC** (max-volume tick), **VAH/VAL** (70% volume envelope),
**HVN** (friction / acceptance), **LVN** (liquidity void — price travels through).

## 3. Order-flow verification

Lee-Ready classification (quote rule, then tick rule at midpoint, then carry prior):
```
D_k = +1  if P_k > mid ; −1 if P_k < mid
      +1  if P_k = mid and ΔP_k > 0 ; −1 if ΔP_k < 0 ; else D_{k−1}
Δ_bar = Σ V_ask − Σ V_bid          CVD_t = Σ_j Δ_bar,j
```
- **Absorption divergence** — price makes new extreme, CVD does not → fade.
- **Initiative confirmation** — CVD accelerates with the break, no divergence → continuation.
- **Diagonal imbalance** — `V_ask,P / V_bid,P−1 ≥ 3.0` (or the mirror) ; ≥3 consecutive ticks = **stacked imbalance** = shelf.
- **Absorption footprint** — heavy volume at the wick, neutral-to-opposing bar delta.
- **Exhaustion footprint** — volume collapses to single digits, delta ≈ 0.

## 4. Regime table

| Regime | GEX | Price location | Profile | Setups | Vol |
|---|---|---|---|---|---|
| I Compressive mean reversion | > 0 high | inside walls, around VWAP | inside VAL–VAH, dense HVN | fade ±2σ, fade walls, revert to POC | subdued |
| II Directional expansion | < 0 (below flip) | outside ±1σ | breaking VA into LVN | momentum breakout, retest continuation | elevated |
| III Boundary pin / trap | > 0 clustered | within 0.20% of wall or POC | VA extremes near expiry | pin, fade false breaks | compressed |
| IV Asymmetric convexity | 0 → negative | decisive wall breach | clearing VA into open space | breakout scalp, buy delta accel | parabolic |

## 5. Cross-asset calibration

| | SPY | TSLA | MSTR |
|---|---|---|---|
| Driver | 0DTE / index hedging | retail call momentum | BTC velocity + convert arb |
| Dominant regime | net long gamma ~70%+ of days | episodic short-gamma bursts | convex negative-GEX tails |
| Hedge instrument | /ES + cash baskets | common | common (borrow constrained) |
| 0DTE share | 50–60% of volume | moderate, weekly-concentrated | low; weeklies dominate |
| IV | 12–22% | 40–65% | 70–130%+ |
| Spread friction cap | ≤ 1.0% | ≤ 2.5% | ≤ 5.0% (mid-peg mandatory) |
| Protocol | revert inside walls; break only below flip | momentum on wall breach + call CVD | BTC-confluence momentum, strict limits |

## 6. Instrument selection

- Strike corridor **0.35–0.50 Δ** (ATM→slight OTM); gamma peaks ATM, OI/liquidity clusters here.
- Reject `< 0.20 Δ` (decay, no gamma) and `> 0.70 Δ` (no convexity, capital heavy).
- Theta: `Θ = −S·φ(d1)·σ / (2√t) − rKe^{−rt}N(d2)` → vertical as `t → 0`.
- SPY 0DTE permitted **09:45–13:30 ET only**; after 13:30 switch to 1DTE.
- TSLA / MSTR: **never 0DTE**. Nearest Friday weekly, 2–5 DTE (7–14 DTE if entering Thu/Fri).
- `Spread Friction Ratio = (Ask − Bid) / Mid × 100`, capped per asset (§5). Limit orders pegged to NBBO mid.

## 7. Setups

| | S1 Mean reversion | S2 Expansion | S3 Reflexive squeeze |
|---|---|---|---|
| Assets | SPY, TSLA (range days) | SPY, TSLA, MSTR | TSLA, MSTR |
| GEX | > 0, inside walls | below flip / HVL | spot ≥ call wall, Net DEX < 0 |
| VWAP | testing ±2σ/±3σ | decisive break outside ±1σ | sustained run above +2σ |
| Profile | VA extreme (VAH/VAL) | VA → LVN | clearing VAH into open space |
| CVD | absorption divergence | trend-aligned, no divergence | parabolic, consecutive new highs |
| Footprint | wick absorption + opposing imbalance | stacked imbalances through the break | stacked buying imbalances |
| Contract | 0.40–0.45 Δ | 0.35–0.45 Δ | 0.40–0.50 Δ weekly |
| Expiry | 0DTE SPY <13:30 / weekly TSLA | 0DTE SPY / 2–5 DTE else | 2–5 DTE, never 0DTE |
| Stop | 0.20% beyond wall, or 5-min close outside | reclaim breakout midpoint / 0.15% back inside flip | 5-min close below call wall |
| T1 | session VWAP (50%) | ±2σ extension (50%) | +50% premium (33%) |
| T2 | opposing VA boundary / POC | opposing wall, trail 9 EMA | +100% (33%), trail anchored VWAP from breakout bar |

## 8. Risk & sizing

```
f* = ((p·b − q) / b) · C_f          C_f = 0.20  (one-fifth Kelly)
Contracts = floor( Equity · Risk% / MaxOptionRisk_per_contract )
```
- Risk 1.0–1.5% equity per setup. `MaxOptionRisk` priced theoretically **at the underlying stop tick**, not as a premium %.
- Stops are **underlying-structural** — a 1-min close beyond the wall / band. Premium-% stops are forbidden as primary invalidation.
- Order-flow override: entry on absorption met by an opposing stacked imbalance > 4 ticks ⇒ exit immediately.
- `−30%` premium = emergency circuit breaker only (halt / feed latency). Never average down.

## 9. Session windows (ET)

| Window | Phase | Permitted |
|---|---|---|
| 09:30–09:45 | opening auction | no execution; record Initial Balance H/L |
| 09:45–11:30 | morning initiative | S1 + S2 prime window |
| 11:30–13:30 | lunch consolidation | mean reversion only, at ±2σ with heavy absorption |
| 13:30–15:30 | afternoon acceleration | S2 active; SPY shifts to 1DTE |
| 15:30–16:00 | liquidation | no entries; **flat by 15:45**, unconditional |

## 10. Daily lifecycle

1. **08:30–09:25 pre-market map** — net GEX, flip, walls, Net DEX; prior-day POC/VAH/VAL; BTC context for MSTR.
2. **09:30–09:45 auction** — mark IB high/low; classify regime by spot vs flip.
3. **09:45–13:30 verification** — require GEX-level × ±2σ confluence, then CVD + footprint confirmation.
4. **routing** — filter chain to 0.35–0.50 Δ, apply expiry rules, audit spread friction, peg to mid, size at ⅕ Kelly.
5. **management** — scale 50% at T1, stop to break-even, structural invalidation only, flat 15:45.

---

# Gap analysis vs. this repo

Checked `research/*` (75 modules) and `tools/api_server.py`.

> An earlier pass of this analysis reported items 1 and 2 below as missing.
> That was wrong: the greps behind it were run against `edge/`, which is a
> self-symlink, and traversal skipped the package. Both were already built.

## Already built

| Spec | Where |
|---|---|
| Dealer GEX profile, gamma flip, call/put walls, regime strength, VEX/CHEX/speed/zomma | `research/microstructure_regime.py` |
| Unbiased dollar-gamma profile | `research/gex_model.py` |
| Session + anchored VWAP with **volume-weighted 1sd/2sd bands** (West's incremental M2) | `research/state_estimation.py` |
| **Volume profile: POC, VAH/VAL, LVN** | `research/volume_profile.py`; also `research/amt_engine.py` and `vpa_levels.compute_vap` |
| Auction context: balance windows, rotation factor, choppiness, efficiency ratio | `research/amt_engine.py` |
| 0DTE same-day expiry magnets on intraday bars | `research/zero_dte.py` |
| Absorption logic (VPA lineage) | `research/vpa_engine.py`, `vpa_score.py`, `absorption_backtest.py` |
| Regime-gated signal generation + backtest | `research/systematic_execution.py` |

## Built in this pass

| Spec | Where |
|---|---|
| §1 Net DEX (aggregate + per strike, both dealer conventions) | `research/microstructure_regime.py` — `calculate_contract_dex`, `net_dex_m`/`call_dex_m`/`put_dex_m` |
| §2 ±3σ (and arbitrary n) VWAP bands | `research/state_estimation.py` — `AnchoredVWAPResult.sigma` / `.band(n)` |
| §9 Session phases, permitted setups, 15:45 flatten flag | `research/execution_gates.py` — `session_gate` |
| §9 Initial Balance (09:30–09:45) | `research/execution_gates.py` — `initial_balance` |
| §6 Expiry policy (0DTE index <13:30, 1DTE after, never-0DTE single names, Thu/Fri floor) | `research/execution_gates.py` — `expiry_policy` |
| §5/§6 Spread Friction Ratio + per-symbol caps | `research/execution_gates.py` — `spread_friction` |
| §6 0.35–0.50Δ contract router | `research/execution_gates.py` — `select_contract` |
| §8 Fractional Kelly + contract count at the underlying stop | `research/execution_gates.py` — `fractional_kelly`, `position_size` |

Tests: `tests/test_execution_gates.py` (40), `tests/test_dealer_delta_exposure.py` (12).

## Not built — no data supports it

| Spec | Missing | Why it stays out |
|---|---|---|
| §3 | Lee-Ready classification, bar delta, CVD | needs NBBO at trade time on the **underlying**; the app has OHLCV candles only |
| §3 | Footprint rungs, 3:1 diagonal / stacked imbalance | needs per-print trade data at each price rung |

`TradingWork/src/lse_provider.py:620` states it directly: the options feed
reports no aggressor side and no bid/ask — last price, volume and greeks only.
The one side hint that exists is a cross-reference against a ~15-minute delayed
yfinance chain, carried as `STALE_QUOTE` and explicitly not decisive. That is
options flow, not the underlying tape, so it cannot stand in either.

Deriving bar delta from where a candle closes in its range would produce a
number for every bar and a caption reading "absorption divergence confirmed"
under all of them. Both setups that depend on §3 therefore run on GEX × VWAP
band × volume-profile confluence alone until a tick+quote feed exists.

## Known gap in what was built

`spread_friction` returns `measurable=False` on every contract from the live
chain, because neither the LSE path nor `_yahoo_front_expiry_chain` in
`tools/api_server.py` carries bid/ask through to the chain row. Yahoo's frame
*has* those columns; the row builder drops them. Restoring them there would
make the friction gate live for index symbols on a delayed quote — worth doing,
and worth labelling as delayed when it is.
