# E2E Test Infra: TradeCentral Flow, Options, Squeeze & Recommendations Reconciliation

## Test Philosophy
- Opaque-box, requirement-driven. Derives from `ORIGINAL_REQUEST.md`.
- Anti-fabrication verification: zero instances of fake zeroes or unmeasured states disguised as zero.
- Cross-view parity verification: matching numbers and directional consensus across Flow, Options, Squeeze, and Suggestion views.

## Feature Inventory & Test Coverage Mapping
| # | Feature | Requirement | Tier 1 (Coverage) | Tier 2 (Boundaries) | Tier 3 (Cross-Feature) | Tier 4 (Real-World) |
|---|---------|-------------|:-----------------:|:-------------------:|:----------------------:|:--------------------:|
| 1 | Flow & Options Calculation Parity | R1 | 5 tests | 5 tests | ✓ | ✓ |
| 2 | Dominance & Imbalance Sentiment | R1 | 5 tests | 5 tests | ✓ | ✓ |
| 3 | Squeeze Screener Direction Alignment | R2 | 5 tests | 5 tests | ✓ | ✓ |
| 4 | Conviction Board & Net GEX Decoupling | R2 | 5 tests | 5 tests | ✓ | ✓ |
| 5 | Pressure Drift & Conflict Indicators | R2 | 5 tests | 5 tests | ✓ | ✓ |
| 6 | Recommendation Freshness & Level Sync | R3 | 5 tests | 5 tests | ✓ | ✓ |
| 7 | Stability Window & Setup Drawer Cache | R3 | 5 tests | 5 tests | ✓ | ✓ |
| 8 | Zero-Fallback & Anti-Fabrication in UI | R4 | 5 tests | 5 tests | ✓ | ✓ |

## Test Architecture
- **Frontend Test Runner**: Vitest v3.2.7 (`cd dashboard && npm test`)
- **Frontend Build & Type Checker**: Vue-tsc + Vite (`cd dashboard && npm run build`)
- **Backend Test Runner**: Pytest with Python 3.10 (`.venv-qlib/bin/pytest eval -q`, `.venv-qlib/bin/pytest tests/daily_plays -q`)
- **Dedicated Conformance Test Files**:
  - `dashboard/src/__tests__/ui-zero-fallback-conformance.test.ts` (Component zero-fallback assertions)
  - `dashboard/src/__tests__/flow-options-reconciliation.test.ts` (Cross-view calculation & threshold tests)
  - `dashboard/src/__tests__/squeeze-direction-alignment.test.ts` (Squeeze vs Direction Brief alignment tests)
  - `dashboard/src/__tests__/recommendations-freshness.test.ts` (Recommendation drawer cache and level attribution tests)

## Coverage Thresholds
- **Tier 1**: ≥5 per feature (≥40 tests)
- **Tier 2**: ≥5 boundary/null cases per feature (≥40 tests)
- **Tier 3**: Pairwise interaction tests across Flow, Options, Squeeze, Suggest (≥10 tests)
- **Tier 4**: Real-world institutional workflow scenarios (≥5 scenarios)
- **Tier 5**: Adversarial stress testing and forensic integrity verification
