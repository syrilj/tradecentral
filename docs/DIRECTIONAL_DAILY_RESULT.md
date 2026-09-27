# Directional daily research result — 2026-07-30

## Decision

**DEVELOPMENT NO-GO. The terminal holdout remains sealed and unevaluated.**

This result does not authorize live trading, option-chain collection, or option
shadow trades. It also does not justify GPU training or a larger model. The
daily-plays command must reject this artifact as a production candidate.

The authoritative broad-universe experiment is
`e5caa497b9347854950aac660ee1f7b97bb27c4dbd2785e5d9ef9b7f5f0b936e`.
Its report and frozen artifact are under:

`edge/runs/research/directional_daily_v1/e5caa497b9347854950aac660ee1f7b97bb27c4dbd2785e5d9ef9b7f5f0b936e/`

The implementation fingerprint is
`d6aa8db4544fe22b67f272c754d6e51159fb43de6e96b9c4919c1798d4669cfd`;
the data fingerprint is
`15ccc6ab52103ef827c06cf7185c891c0e87630f4853b06767aefc536aa00e92`.
Interrupted ledger entries without a final report are preliminary and are not
candidates.

## Protocol

- 60-symbol daily universe and 2,499 development dates.
- Frozen 5-, 10-, and 20-session targets: features known at the prior close,
  entry at the next session open, exit at the configured horizon close.
- Nine nested, purged, embargoed outer folds, including a pre-specified partial
  final validation fold. All fitting, calibration, threshold selection, and
  model selection occur on training data only.
- Seventeen recorded configurations across momentum, volatility-scaled
  momentum, regularized logistic regression, a conservative CPU XGBoost
  challenger, and two fixed theory-driven simple hypotheses.
- Inference is aggregated by decision date with horizon-sized block bootstrap.
  The search-aware Sharpe statistic uses all recorded trials.
- Promotion requires positive net expectancy, a positive bootstrap lower bound,
  positive search-adjusted Sharpe, acceptable calibration, and a positive
  paired lower bound versus the frozen momentum baseline.

The terminal holdout is 2026-07-13 through 2027-01-29, with at least 120
sessions required before evaluation. Its status is `SEALED_UNEVALUATED`; it was
not loaded to produce this result.

## Broad-universe result

| Horizon | Selected development trial | Net expectancy | Net 95% lower bound | Search-adjusted Sharpe lower | ECE | Candidate minus momentum 95% lower |
|---|---|---:|---:|---:|---:|---:|
| 5d | `xgboost_conservative_v1_5d` | +0.3352% | +0.0614% | +0.289 | 1.19% | **−0.0177%** |
| 10d | `momentum_10d` | +0.8391% | +0.2170% | +0.621 | 1.42% | **0.0000%** |
| 20d | `volatility_scaled_momentum_20d` | +1.9219% | +0.6036% | +0.823 | 4.60% | **−0.0271%** |

All three horizons fail the incremental-evidence gate. The ten-day winner is
the frozen baseline itself. The five- and twenty-day challengers have positive
standalone estimates but cannot establish that their incremental performance is
greater than zero. Calibration is not evidence of tradable edge.

The two fixed follow-up hypotheses also failed:

- Five-day large-shock reversal: negative net expectancy and negative lower
  bound.
- Twenty-day leave-one-out sector-residual momentum: negative net expectancy
  and negative lower bound.

Those thresholds are not retuned after seeing the result.

## Liquid-ETF concentration stress

The independently recorded 13-ETF sensitivity experiment is
`35390f0256b1714b5ca4ffbc1fc5345147c64f8270440fc218c1eabf28faf8bc`.
It is also a development NO-GO.

| Horizon | Selected trial | Net expectancy | Net 95% lower bound | Search-adjusted Sharpe lower | ECE | Candidate minus momentum 95% lower |
|---|---|---:|---:|---:|---:|---:|
| 5d | `xgboost_conservative_v1_5d` | +0.0727% | **−0.0912%** | **−0.260** | 0.76% | **−0.0267%** |
| 10d | `xgboost_conservative_v1_10d` | +0.2701% | **−0.0651%** | +0.188 | 3.97% | **−0.0009%** |
| 20d | `regularized_logistic_c0.1_20d` | +0.6832% | +0.0119% | +0.462 | **7.82%** | **−0.0011%** |

The five- and ten-day expectancy bounds become negative. The twenty-day result
does not beat momentum and breaches the 5% calibration limit. This supports the
diagnosis that the broad-universe headline return is not robust evidence of a
deployable model.

## Operational consequence

- `underlying_gate = FAIL_DEVELOPMENT`
- `holdout.status = SEALED_UNEVALUATED`
- `option_shadow_collection_authorized = false`
- No broker connectivity or order placement exists.
- No real-capital or option play may be produced from this experiment.

The next research attempt must begin with a new, economically motivated
hypothesis and a new pre-registered gate. Adding capacity or repeatedly searching
the same development data would increase selection bias, not confidence.

---

*Historical simulation and research only. Not financial advice.*
