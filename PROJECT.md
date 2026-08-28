# Project: TradeCentral Flow, Options, Squeeze & Recommendations Reconciliation

## Architecture
TradeCentral is a high-density financial workstation with a Python analytics/API backend (`daily_plays/`, `research/`, `tools/api_server.py`) and a Vue 3 + TypeScript frontend (`dashboard/`).
This project reconciles metric calculations, squeeze screener logic, directional bias indicators, recommendation freshness, and zero-fallback UI rendering across Flow and Options interfaces.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        TradeCentral Workstation                        │
├──────────────────────────────────┬─────────────────────────────────────┤
│      Frontend (Vue 3 / TS)       │      Backend (Python 3.10)          │
├──────────────────────────────────┼─────────────────────────────────────┤
│ - FlowDashboard.vue              │ - daily_plays/options_intelligence  │
│ - OptionsView.vue                │ - daily_plays/opportunity_scanner   │
│ - OptionsFlowContext.vue         │ - daily_plays/flow_adapter          │
│ - OptionsDirectionBrief.vue      │ - tools/api_server.py               │
│ - OptionsConvictionBoard.vue     │ - research/                         │
│ - SqueezeScreener.vue / calc     │                                     │
│ - FlowSuggestionDrawer.vue       │                                     │
│ - optionsDirection.ts / format.ts│                                     │
└──────────────────────────────────┴─────────────────────────────────────┘
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Backend Flow Aggregation & API Parity | Reconcile summary totals, filter defaults (`min_premium`, `min_volume`), and endpoint parameters across `/api/options` and `/api/unusual-flow`. | M1 | R1, Survey 1 |
| 2 | Level Source & Recommendation Engine Fixes | Correct `gamma_flip` attribution to `LEVEL_SOURCE_GEX`, propagate plan target/invalidation sources, expand stability observation window. | M1 | R3, Survey 2 |
| 3 | Suggestion Cache Invalidation | Auto-invalidate `_FLOW_SUGGESTION_CACHE` upon fresh market flow arrival. | M1 | R3, Survey 2 |
| 4 | Squeeze Direction Tie-Breaking Alignment | Reconcile `calculateFeaturedSetup` in `squeezeCalc.ts` to prioritize signed score / flow lean over geometric wall proximity. | M2 | R2, Survey 2 |
| 5 | Conviction Board Pressure & GEX Decoupling | Decouple Net GEX from directional `pos`/`neg` green/red styling; remove unsigned activity imbalance fallback in pressure scoring. | M2 | R1, R2, Survey 1 & 2 |
| 6 | Directional Drift & Conflict Indicators | Synchronize `OptionsDirectionBrief`, `SqueezeScreener`, and `PressureDriftChart` on mixed/conflicting flow state. | M2 | R2, Survey 2 |
| 7 | Frontend Flow & Options Summary Parity | Use full backend session summaries in `OptionsFlowContext` rather than truncated tape slice; remove 24-row slice in `FlowDashboard`. | M3 | R1, Survey 1 |
| 8 | Call/Put Dominance Threshold Transparency | Align and clarify dominance thresholds between Flow Tape Share (>=55%) and Institutional Activity Imbalance (>=58%). | M3 | R1, R2, Survey 3 |
| 9 | Recommendation Drawer Live Refresh | Force live cache bypass on symbol change in `FlowSuggestionDrawer.vue` and `SuggestView.vue`. | M3 | R3, Survey 2 & 3 |
| 10 | Zero-Fallback & Anti-Fabrication UI Remediation | Eliminate all 22 hardcoded fake zeros (`$0.00`, `0.00%`, `0.0%`, `+$0.0M`, `1.00x`, `+0.0`, `0D`) across `OptionsView.vue`, `OptionsFlowContext.vue`, `OptionsDirectionBrief.vue`, `OptionsConvictionBoard.vue`, `FintelView.vue`. | M4 | R4, Survey 3 |
| 11 | Comprehensive E2E Test Suite (Tiers 1-4) | Requirement-driven test suites for Flow/Options parity, Squeeze alignment, Recommendation freshness, and Zero-Fallback conformance. | M5 | Acceptance Criteria, Survey 3 |
| 12 | Adversarial Hardening (Tier 5) | Adversarial stress testing, edge-case coverage, and forensic integrity verification. | M5 | Acceptance Criteria, Survey 3 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Backend Calculations & Recommendation Engine Reconciliation | `daily_plays/options_intelligence.py`, `daily_plays/opportunity_scanner.py`, `tools/api_server.py` | none | DONE |
| M2 | Squeeze Screener & Directional Bias Reconciliation | `dashboard/src/squeezeCalc.ts`, `dashboard/src/optionsDirection.ts`, `dashboard/src/components/OptionsConvictionBoard.vue`, `dashboard/src/components/OptionsDirectionBrief.vue`, `dashboard/src/components/SqueezeScreener.vue` | M1 | DONE |
| M3 | Flow & Options Calculation Parity & Drawer Sync | `dashboard/src/components/FlowDashboard.vue`, `dashboard/src/components/OptionsFlowContext.vue`, `dashboard/src/components/FlowSuggestionDrawer.vue`, `dashboard/src/views/SuggestView.vue`, `dashboard/src/api.ts` | M1, M2 | IN_PROGRESS |
| M4 | UI Zero-Fallback & Anti-Fabrication Remediation | `dashboard/src/views/OptionsView.vue`, `dashboard/src/components/OptionsFlowContext.vue`, `dashboard/src/components/OptionsDirectionBrief.vue`, `dashboard/src/components/OptionsConvictionBoard.vue`, `dashboard/src/views/FintelView.vue` | M2, M3 | PLANNED |
| M5 | E2E Integration, Full Test Verification & Adversarial Hardening | Full frontend test suite (`npm test`), build (`npm run build`), Python test suite (`pytest eval`, `pytest tests/daily_plays`), and Tier 1-5 tests | M1, M2, M3, M4 | PLANNED |

## Interface Contracts
### `daily_plays/opportunity_scanner.py` ↔ `tools/api_server.py` ↔ `dashboard/src/api.ts`
- `setup_level_model` attributes `gamma_flip` to `LEVEL_SOURCE_GEX` ("options GEX").
- `build_live_opportunities` preserves `plan_target_source` and `plan_invalidation_source` when levels exist.
- `_FLOW_SUGGESTION_CACHE` actively purges updated symbols upon fresh unusual flow arrival and respects `force=True`.
- `_CONTRACT_STABILITY_MAX_GAP_S = 2700.0s` (45 min) maintains stability counts across standard 5-10 min operator pauses.

### `dashboard/src/squeezeCalc.ts` ↔ `dashboard/src/components/SqueezeScreener.vue`
- `calculateFeaturedSetup(props)` returns `{ side: 'bullish' | 'bearish' | 'neutral' | 'two_way', setup: Setup | null }`.
- When signed score or flow direction is available, featured setup side aligns with market directional bias.

### `dashboard/src/format.ts` ↔ All UI Components
- Missing/null data returns `DASH` (`—`), never fake zero numbers (`0.00`, `$0.00`, `0.00%`, `+$0.0M`, `1.00x`).

## Code Layout
- Backend analytics: `daily_plays/`, `research/`, `tools/api_server.py`
- Frontend components: `dashboard/src/components/`
- Frontend views: `dashboard/src/views/`
- Frontend logic & state: `dashboard/src/`
- Frontend tests: `dashboard/src/__tests__/` and `dashboard/tests/`
- Python tests: `tests/daily_plays/`, `eval/`
