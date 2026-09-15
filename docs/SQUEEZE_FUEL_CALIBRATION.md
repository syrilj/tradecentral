# Squeeze FUEL calibration — measured fix for the mega-cap "NO FUEL" bug

Date: 2026-09-14 (panel data through chain snapshot 2026-09-15)
Scope: the unsigned fuel leg only (`squeeze_risk` → `fuel_ui`). Direction legs
(signed flow × momentum) are untouched.

## Hypothesis and diagnosis

Shipped theory (pre-fix), `daily_plays/gex_core.py`:

```
SR      = |GEX⁻_1pct| / ADV · exp(-0.05 · weighted_dte) · atm_share
fuel_ui = tanh(40 · SR)
```

`weighted_dte` was the |GEX|-weighted mean DTE of the **whole book**. Reproduced
offline from the NVDA 2026-09-15 chain snapshot (production enrichment, ADV from
`data/1d_wide` 20-session dollar volume):

- spot 210.96, ADV = $28.13B, |GEX⁻| = $3.27B per 1% move
- liquidity ratio = 3.27 / 28.13 = **0.1162**, atm_share = **0.231**
- full-book weighted DTE = **64.5 d** → urgency exp(-0.05·64.5) = **0.0398**
- SR = 0.1162 · 0.0398 · 0.231 = **0.00107** → fuel = tanh(40·0.00107) = **4.3%** → "NO FUEL"

The decomposition confirms the worked example exactly. The failure is the
urgency *basis*, not the constant: dealers rehedge the near-expiry book
intraday; NVDA's front 40% of |GEX| sits at DTE **5.9 d** while its long-dated
OI tail drags the weighted mean to 64.5 d and multiplies fuel by 0.04.

## Harness and dataset

- Script: `research/squeeze_fuel_calibration.py` (extends the methodology of
  `research/squeeze_validation.py`; artifacts in `runs/squeeze_fuel_calibration/`
  `panel.parquet` + `metrics.json`).
- Panel: 589 chain snapshots over 35 dates (2026-07-31 → 2026-09-15),
  206 symbols, 540 scored with ADV; 461 with 1d forward returns (late snapshots
  are forward-censored from local prices — never fabricated).
- Two row universes per snapshot: `prod` (production enrichment — BS gamma when
  missing, **no** dte/OI filter) and `harness` (prior validation filter
  dte ≤ 45, OI ≥ 50) for consistency with `runs/squeeze_validation`.
- Prior validation's outcome metric (directional hit rates, theory score IC)
  plus its amplification block — rank IC of SR vs |forward return| — informed
  this study. Prior result worth restating: on the old harness-population the
  *raw* SR↔|r| IC was already **negative (-0.24 @1d)**; we reproduce that on the
  larger panel and show below it is a cross-sectional book-depth/vol confound,
  not a direction error.

### Data-quality fix required first

~11 of 2,576 NVDA rows (and 178/540 panel records before the fix) carry
**NaN openInterest** (vendor blanks); NaN is truthy in Python, so it silently
poisoned whole-chain aggregates (GEX → NaN, atm_share → 0, weighted_dte →
sentinel 30). The calibration script and this work's conclusions are contingent
on coercing NaN OI/IV/gamma to skip in enrichment.

## Why raw |move| is the wrong target metric here

Every candidate — shipped base included — shows pooled/per-date Spearman IC ≈
**-0.25…-0.33 vs next-day |return|**, with perfectly anti-monotone quintiles.
Deep option books relative to ADV live on liquid, low-|move| names, so raw
|move| ranking inverts. The theory-consistent outcome is **moving beyond what
options priced**: |fwd_1d| / EM_1d (EM = spot · median ATM IV / √365). All
judgments below use vol-normalized metrics plus tail-move enrichment
(P(|fwd_1d| > 2×EM_1d) in top vs bottom SR quintile).

## Candidate metrics (production universe, n=540)

| candidate | vn IC 1d | per-date vn IC | per-symbol vn IC (19 syms) | tail top/bot | NVDA fuel @40 |
|---|---|---|---|---|---|
| base (shipped: full book, c=0.05) | +0.027 | **-0.005** | **-0.147** | 4.4% / 5.6% (**inverted**) | 4.3% |
| c01_full | +0.030 | +0.023 | +0.073 | 7.8 / 5.6 | — |
| c02_full | +0.030 | +0.016 | -0.033 | 5.6 / 5.6 | — |
| c05_near5 (±5% book) | **+0.040** | +0.019 | -0.030 | 6.7 / 5.6 | 20.7% |
| c02_near5 | +0.032 | +0.028 | +0.050 | 8.9 / 5.6 | 50.8% |
| c01_near5 | +0.028 | +0.031 | +0.052 | 7.8 / 5.6 | — |
| **c05_front40 (winner)** | +0.036 | +0.028 | **+0.071** | **10.0 / 4.4 (2.3×)** | 66.5% |
| c02_front40 | +0.030 | +0.034 | +0.085 | 8.9 / 5.6 | 50.8% |
| c05_clip10 | +0.026 | +0.028 | +0.050 | 8.9 / 5.6 | — |
| no_urgency (liq·atm) | +0.026 | +0.028 | +0.050 | 8.9 / 5.6 | 79.1% |
| liq_only (ablation) | +0.033 | **+0.039** | **+0.144** | 7.8 / 4.4 | — |

The shipped base is the *only* candidate whose top-SR quintile has **fewer**
beyond-2×EM days than its bottom quintile, and it is strongly negative
per-symbol (-0.147). Every near-book/front-book variant beats it. `liq_only`'s
strength means the signal lives in |GEX|/ADV; the multiplicative corrections
must at minimum not destroy it — urgency on the front book passes, urgency on
the full book (base) fails.

Harness universe (dte ≤ 45, OI ≥ 50) corroborates direction: c05_front40
per-symbol +0.065 vs base +0.035; tail top 10.0% in both, bottom 6.7% vs 4.4%.

## Winner and chosen constants

**`urgency_dte_basis = "front40"`** (urgency priced off the |GEX|-weighted DTE
of the front 40% of the book by expiry, falling back to full-book DTE when no
DTE data survives), **`urgency_c = 0.05` unchanged**, **`fuel_scale 40 → 25`**.

fuel_scale is a pure display transform (rank metrics are scale-invariant), so it
was tuned for a usable 0–100% band on the production SR distribution:

| fuel_scale | median | p75 | p80 | p90 | % pinned <5% | NVDA | AAPL | SPY/QQQ |
|---|---|---|---|---|---|---|---|---|
| 40 (shipped) | 30.6% | 71.0% | 83.3% | 99.6% | 11.5% | 66.5% | 95% | 100% |
| 16 (= p90→85%) | 12.5% | 33.9% | 44.3% | 85.0% | 28.1% | 30.8% | 62% | 100% |
| **25 (chosen)** | **19.5%** | **50.4%** | **63.4%** | **96.2%** | **18.5%** | **46.3%** | **81%** | 100% |

Scale 40 pins the top ~19% of names at ≥85% (no resolution where squeeze
ranking matters); scale 16 recreates the "everything reads low" complaint
(median 12.5%). Scale 25 keeps a hot tail (p90 ≥ 96%) with a live mid-band.
SPY/QQQ saturating at 100% is honest: their |GEX⁻|/ADV are 1.24 / 0.85 with
atm_share ≥ 0.64 and 2d front books — index books are that large.
Names with genuinely thin near books still read NO FUEL (SPCX 3%, SNDK 4%).

## What changed in code

`daily_plays/gex_core.py` only (no call-site change required; all four callers —
options_intelligence, research/flow_shift, research/squeeze_validation,
research/squeeze_flow_eval — inherit the new calibration through defaults):

1. `short_premium_gex_1pct_m` now also returns `front40_weighted_dte`
   (|GEX|-weighted mean DTE over the cheapest 40% of the book by expiry;
   `None` when no DTE data).
2. `compute_theory_squeeze` gains `urgency_dte_basis: str = "front40"`
   (`"full"` = legacy). New `components` keys: `front40_weighted_dte`,
   `urgency_dte`, `urgency_dte_basis`; `urgency` is computed on `urgency_dte`;
   `weighted_dte` still reports the full-book value for display continuity.
3. Default `fuel_scale` 40 → 25 in `compute_theory_squeeze` and
   `directional_squeeze_scores`.

Exact legacy replay: `urgency_dte_basis="full", urgency_c=0.05, fuel_scale=40.0`.

Frontend identity (`dashboard/src/squeezeCalc.ts`) defaults `fuel_scale` to 25
and prints `tanh(fuel_scale·SR)` from the shipped payload. Legacy replay still
ships `fuel_scale: 40` and the board follows that number.

## Tests

- `tests/daily_plays/test_gex_theory_squeeze.py`: +4 tests (front40 worked
  example; NVDA-style long-tail regression — new SR > 100× legacy; no-DTE
  fallback; invalid basis raises). No existing test pinned the old constants.
- `python3 -m pytest -q tests/daily_plays/test_gex_theory_squeeze.py
  tests/daily_plays/test_gex_core_squeeze.py tests/daily_plays/test_options_board.py
  tests/research/test_squeeze_validation.py tests/research/test_squeeze_flow_eval.py
  tests/research/test_squeeze_flow_shift.py tests/daily_plays/test_options_intelligence.py`
  → **134 passed**.
- `cd dashboard && npx vitest run src/__tests__/squeeze-screener-calc.test.ts
  src/__tests__/squeeze-live-correlates.test.ts
  src/__tests__/squeeze-direction-alignment.test.ts` → **94 passed** (mocks only;
  no frontend change).

## Caveats

- Dealer inventory is *inferred* (customer-long / dealer-short premium, q = −OI),
  never observed. A long-dealer-gamma pocket inside a short-premium book is
  invisible to this model regardless of calibration.
- Single OI snapshot per day; no intraday OI evolution, no flow direction in
  this study (out of scope).
- Statistical power is modest: 13 dates have ≥8 names for cross-sectional IC;
  per-symbol IC averages 19 symbols with ≥5 observations; vol-normalized ICs of
  +0.03–0.04 at n≈460 are weak-but-positive, and the headline evidence is the
  tail enrichment (10.0% vs 4.4%) plus the per-symbol swing from -0.147 to
  +0.071. Treat fuel as a conditioner, not a standalone alpha signal.
- The raw-|move| cross-sectional inversion (-0.3 IC, monotone -1.0) remains for
  ALL variants — book depth ∝ liquidity ∝ low raw vol. Do not regress fuel
  against raw |move| in future studies; use EM-normalized moves or per-symbol
  panels.
- Chain NaN-OI rows are dropped by this study's enrichment; if production
  `_enrich_chain_for_theory` is ever fed NaN OI the same poisoning applies
  (currently it passes NaN through to `short_premium_gex_1pct_m`).
- Late snapshot dates (2026-09-13 → 15) have censored forward returns and only
  enter coverage/display statistics, not ICs.
