# E2E Test Infra: Market Regime System Rebuild

## Test Philosophy
- Opaque-box, requirement-driven, mathematically rigorous.
- Verifies point-in-time causality, numerical stability, probability normalization, confidence calibration, zero-spoofing honesty, and historical stability.
- Methodology: Category-Partition + Boundary Value Analysis + Combinatorial Pairwise + Real-World Market Replay.

## Feature Inventory & Test Coverage Goals
| # | Feature | Source | Tier 1 (Unit) | Tier 2 (Boundary) | Tier 3 (Pairwise) | Tier 4 (Workload) |
|---|---------|--------|:-------------:|:-----------------:|:-----------------:|:-----------------:|
| 1 | Point-in-Time Returns, Realized Vol & ATR | R1, R2 | 5 | 5 | ✓ | ✓ |
| 2 | West's Incremental Session VWAP & Dispersion | R1, R2 | 5 | 5 | ✓ | ✓ |
| 3 | Black-Scholes Greeks (1st-3rd order) & GEX Profiles | R1, R2 | 5 | 5 | ✓ | ✓ |
| 4 | Gamma Flip Disambiguation & Wall Extraction | R1, R2 | 5 | 5 | ✓ | ✓ |
| 5 | Kinematic Kalman Trend Model | R2 | 5 | 5 | ✓ | ✓ |
| 6 | Rolling Volatility Percentile Environment | R2 | 5 | 5 | ✓ | ✓ |
| 7 | Market Structure Model (VR & OU Half-Life) | R2 | 5 | 5 | ✓ | ✓ |
| 8 | Transition & Change-Point Hazard Model | R2, R3 | 5 | 5 | ✓ | ✓ |
| 9 | Flow Context & Microstructure Topography | R2 | 5 | 5 | ✓ | ✓ |
| 10 | Unified Layer 3 Deterministic Reconciliation | R2, R3 | 5 | 5 | ✓ | ✓ |
| 11 | Strictly Normalized Probability Distribution ($\sum p = 1$) | R3 | 5 | 5 | ✓ | ✓ |
| 12 | Calibrated Multi-Factor Confidence Score | R3 | 5 | 5 | ✓ | ✓ |
| 13 | Multi-Model Agreement Matrix & Fail-Closed State | R3 | 5 | 5 | ✓ | ✓ |
| 14 | Dynamic Explainability Engine | R4 | 5 | 5 | ✓ | ✓ |
| 15 | Backend API Server Endpoints | R2, R5 | 5 | 5 | ✓ | ✓ |
| 16 | TypeScript Data Contracts (`regimeContracts.ts`) | R5 | 5 | 5 | ✓ | ✓ |
| 17 | Client-Side Signals & Primitives (`regimeSignals.ts`) | R5 | 5 | 5 | ✓ | ✓ |
| 18 | Multi-Dimensional UI Workstation Components | R5 | 5 | 5 | ✓ | ✓ |
| 19 | Zero-Spoofing & Anti-Fabrication Remediation | R5 | 5 | 5 | ✓ | ✓ |
| 20 | Historical Benchmark Simulation Suite | R6 | 5 | 5 | ✓ | ✓ |

## Test Architecture
- Backend Test Runner: `pytest`
  - `tests/research/test_regime_features.py`: Point-in-time features, Greeks, VWAP.
  - `tests/research/test_statistics_regimes.py`: Rolling percentile vol, Kalman trend, market structure.
  - `tests/research/test_microstructure_regime.py`: Greeks, topography, flip extraction.
  - `tests/research/test_regime_reconciliation.py`: Layer 3 aggregation, calibrated confidence, probability sums.
  - `tests/research/test_regime_explainability.py`: Dynamic attribution vector, top drivers, divergence notes.
  - `tests/daily_plays/test_regime_attractor_engine.py`: Multi-factor price magnets & pull scores.
  - `eval/validate_historical_regimes.py`: Walk-forward simulation on historical market slices.
- Frontend Test Runner: `npm test` (Vitest)
  - `dashboard/src/__tests__/regime-contracts.test.ts`: TypeScript contract validators.
  - `dashboard/src/__tests__/regime-ui-components.test.ts`: SSR rendering of Primary Regime Card, 4 pillars, Agreement Matrix, Explanation Panel.
  - `dashboard/src/__tests__/tier5-zero-spoofing-adversarial.test.ts`: Verifies zero fake zeros across all cards.
- Frontend Build Runner: `npm run build` (`vue-tsc --noEmit && vite build`).

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Market Context | Acceptance Criteria |
|---|----------|--------------------|----------------|---------------------|
| 1 | 2020 March COVID Shock | Volatility Shock, BOCPD Changepoint, Bear Trend, Short Gamma | Extreme volatility spike | Detects shock in $<2$ bars, confidence drops, transition risk $>0.8$. |
| 2 | 2021 Bull Run Momentum | Bull Trend, Long Gamma Dampening, Trending Structure | Low vol persistent trend | High confidence ($>0.75$), stable regime, zero false whipsaws. |
| 3 | 2022 Rate Hike Bear Market | Bear Trend, Elevated Vol, Institutional Distribution | Persistent downtrend | Detects distribution, high agreement, accurate resistance walls. |
| 4 | 2024 Range-Bound Magnet Pin | Compression Range, Pinning Gamma, OU Half-Life $<10$ bars | Sideways oscillation | Mean-reverting structure, call/put wall bounds respected. |
| 5 | Sharp Intraday Flip Boundary Crossing | Flip proximity $\le 0.25\%$, Conflict Trigger | Trend vs Short Gamma mismatch | Enters `"Uncertain / Transitional"` fail-closed state gracefully. |

## Coverage Thresholds
- Tier 1: $\ge 5$ test cases per feature.
- Tier 2: $\ge 5$ boundary/corner cases per feature.
- Tier 3: Pairwise coverage across all 5 specialized model interactions.
- Tier 4: $\ge 5$ historical walk-forward simulation benchmarks.
