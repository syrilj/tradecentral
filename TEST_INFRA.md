# E2E Test Infra: Options Flow & Squeeze Screener Overhaul

## Test Philosophy
- Requirement-driven opaque-box and component test verification.
- Enforce 100% test pass rate on `npm test` (`vitest run`).
- Validate zero TypeScript errors on `vue-tsc --noEmit && vite build`.
- Enforce token compliance and high-contrast design system constraints.

## Feature Inventory & Test Coverage Mapping
| # | Feature | Source (Requirement) | Test Suite |
|---|---------|----------------------|------------|
| 1 | High-Contrast Token System & Token Alignment | ORIGINAL_REQUEST §4 | `src/components/__tests__/options-ui-tokens.test.ts`, `src/components/__tests__/gex-map-enhanced.test.ts` |
| 2 | Squeeze Screener Calculation & Setup Fixes | ORIGINAL_REQUEST §1 | `src/__tests__/squeeze-screener-calc.test.ts` (NEW), `src/__tests__/options-direction.test.ts` |
| 3 | Options Flow & Conviction Board Data Pipeline Fixes | ORIGINAL_REQUEST §1, §4 | `src/__tests__/flow-display.test.ts`, `src/components/__tests__/flow-workspace.test.ts`, `src/__tests__/e2e-tier1-feature-coverage.test.ts` |
| 4 | Em-Dash Elimination & Clean Numeric Fallbacks | ORIGINAL_REQUEST §3 | `src/__tests__/options-display-fallbacks.test.ts` (NEW), `src/__tests__/chain-display.test.ts`, `src/__tests__/flow-display.test.ts` |
| 5 | High-Impact Graphics & Charts Polish | ORIGINAL_REQUEST §2 | `src/charts/__tests__/charts.test.ts`, `src/components/__tests__/gex-map-enhanced.test.ts`, `src/__tests__/options-drift-chart.test.ts` (NEW) |
| 6 | Full Test Suite Pass & Type Check | ORIGINAL_REQUEST §5 | `npm run test` (all 40+ files), `npm run build` (`vue-tsc --noEmit`) |

## Test Architecture
- Test runner: `vitest run` in `/Users/syriljacob/Desktop/alltrading/edge/dashboard`
- Type checker: `vue-tsc --noEmit` in `/Users/syriljacob/Desktop/alltrading/edge/dashboard`
- Pass/Fail semantics: Exit code 0, 0 test failures, 0 TypeScript errors.
