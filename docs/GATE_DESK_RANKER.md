# GATE — desk ranker v1 — pre-registered 2026-08-16

Written **before** the bakeoff is run. This does not amend `GATE.md`,
`GATE_XS.md`, `GATE_XS2.md`, `GATE_XS3.md`, `GATE_XS4.md`, or
`FACTOR_PROBE_RESULT.md`. Those verdicts stand.

## Hypothesis

The shipped scan scorer is the wrong implementation of research that already
exists:

1. `FACTOR_WEIGHTS` still mixes `lowvol` and `liq`, which the factor probe
   found absent or sign-flipped.
2. The LightGBM ensemble was fit on a same-bar 5d label
   (`close[t+5]/close[t]-1`) while live scoring must enter after the decision
   bar. That is the same class of leak that flattened Kronos and PEAD.
3. High-capacity trees on this catalog produced IC ≈ 0.005. Two hand-specified
   factors (`rev5`, `mom12_1`) produced IC ≈ 0.02.

**Claim:** a *zero-fit* regime-conditioned blend of only those two
literature-signed factors, scored against a **skip-day** 5-session label and
traded as a **weekly hysteresis** long book, has higher skip-day Rank IC and
higher net return after 10 bp than the shipped factor blend and the shipped
LightGBM ensemble.

This is an implementation of known effects, not a search for new ones.

## Frozen recipe (no search)

| Item | Frozen value |
|---|---|
| Factors | `rev5 = -1 * 5d return`, `mom12_1 = close[t-21]/close[t-252]-1` |
| Cross-section | daily rank → z-score, then weighted sum |
| HIGH vol weights | `rev5=0.65`, `mom12_1=0.35` |
| MEDIUM vol weights | `rev5=0.50`, `mom12_1=0.50` |
| LOW vol weights | `rev5=0.35`, `mom12_1=0.65` |
| Vol regime | `research.regimes.classify_regimes` on SPY (fallback: equal-weight catalog close), expanding terciles of 20d realized vol |
| Label | `close[t+1+5]/close[t+1]-1` (skip-day, h=5) |
| Rebalance | Fridays only |
| Book | long names with score percentile ≥ 0.80; stay if already held and percentile ≥ 0.65 |
| Cost | 10 bp round-trip (5 bp each side) |
| Execution | weights at Friday close earn the next session's close-to-close path (lag ≥ 1) |

Regime weights come from the economic story (reversal in stress, continuation
in calm). They are **not** fit on any window of this dataset.

## Windows

| Role | Dates | Status |
|---|---|---|
| Development bakeoff | 2022-01-18 → 2023-12-29 | Spent by `GATE_XS3` for *other* learners. First look at *this* recipe. |
| Confirmation report | 2025-01-02 → 2026-06-30 | Overlaps the factor-probe recent window for these two factors. **Not a clean confirmation.** Reported for honesty, not as a GO. |

A future clean confirmation requires data after 2026-07-29 or a different
feature set.

## Success vs the shipped scorer (development window)

All of the following must hold on 2022-01-18 → 2023-12-29:

1. Skip-day mean Rank IC of desk ranker **>** shipped `FACTOR_WEIGHTS` blend.
2. Skip-day mean Rank IC of desk ranker **>** shipped `qlib_scan_lgb` ensemble
   when that artifact loads; if it does not load, this arm is skipped.
3. Hysteresis book net return @ 10 bp **>** the same book built from the
   shipped factor blend.
4. Annualized turnover of the hysteresis book **< 20×**.

No live-capital or ENTER authorization is possible from this gate. A pass only
authorizes replacing the *ordinal scan score* with this recipe.

## Trial count

**1.** One pre-registered recipe. Do not retune weights on either window.

## What this will not do

- Train LightGBM, XGBoost, or a neural net.
- Use same-bar labels.
- Treat the score as a calibrated probability.
- Authorize ENTER, paper sizing, or broker connectivity.
