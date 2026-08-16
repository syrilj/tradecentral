# Project: Options Flow & Squeeze Screener Overhaul

## Architecture
- Frontend: Vue 3 + TypeScript + Vite + Pinia (`dashboard/src/`)
- Styling: High-contrast dark theme token architecture (`src/styles/tokens.css`, `src/styles/theme.css`)
- Test Framework: Vitest (`npm test` / `vitest run`) + Vue TSC (`vue-tsc --noEmit`)
- Backend API Integration: Python FastAPI/Flask endpoints (`tools/api_server.py`, `daily_plays/`) consumed via `src/api.ts` and `src/composables/useResource.ts`

## Feature Inventory
| # | Feature | Description | Milestone | Status |
|---|---------|-------------|-----------|--------|
| 1 | High-Contrast Token System & Token Alignment | Upgrade `--call` (Emerald `#10b981`/`#34d399`) and `--put` (Crimson `#f43f5e`/`#fb7185`) in `tokens.css`; align `options-ui-tokens.test.ts` and `gex-map-enhanced.test.ts` | M1 | DONE |
| 2 | Squeeze Screener Calculation & Setup Fixes | Fix featured tie-breaking (`signedScore`), negative score SVG ring offset (`Math.abs`), near-spot GEX formatting (`-$X.XM`), factor track clamping, takeaway polarity | M2 | DONE |
| 3 | Options Flow & Conviction Board Data Pipeline Fixes | Fix C/P ratio zero-division on empty tape, pressure score normalization, moneyness null guard, and flow order taxonomy in `OptionsView.vue`, `OptionsConvictionBoard.vue`, `OptionsFlowContext.vue` | M3 | DONE |
| 4 | Em-Dash Elimination & Clean Numeric Fallbacks | Eradicate all placeholder em-dashes ("—" / "--") across Options and Squeeze views, replacing with clean numeric fallbacks ($0.00, 0.00%, 0, styled N/A badges) | M4 | DONE |
| 5 | High-Impact Graphics, Gauges & Tooltip Enhancements | Crisp SVG borders, smooth hover tooltips/crosshairs, cubic-bezier transition curves, 3D gradient sync across `GammaExposureMap.vue`, `OptionsDriftChart.vue`, `ProbabilityDensityChart.vue`, `RiskNeutral3DModel.vue`, `SqueezeScreener.vue` | M5 | DONE |
| 6 | E2E Testing, Adversarial Verification & Full Test Pass | Comprehensive test suite pass (100% pass across all 45 test files / 661 tests), zero TypeScript compilation errors, forensic audit | M6 | DONE |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Design System & Token Upgrades | `src/styles/tokens.css`, `src/components/__tests__/options-ui-tokens.test.ts`, `src/components/__tests__/gex-map-enhanced.test.ts` | none | DONE |
| M2 | Squeeze Screener Calculation Fixes | `src/components/SqueezeScreener.vue`, `src/__tests__/squeeze-screener-calc.test.ts` | M1 | DONE |
| M3 | Options Flow & Conviction Board Overhaul | `src/views/OptionsView.vue`, `src/components/OptionsConvictionBoard.vue`, `src/components/OptionsDirectionBrief.vue`, `src/components/OptionsFlowContext.vue`, `src/flowDisplay.ts` | M1 | DONE |
| M4 | Em-Dash Elimination & Numeric Fallbacks | `src/format.ts`, `src/flowDisplay.ts`, `src/views/OptionsView.vue`, `src/components/SqueezeScreener.vue`, `src/components/OptionsConvictionBoard.vue`, `src/components/OptionsDirectionBrief.vue`, `src/components/OptionsFlowContext.vue`, `src/views/FintelView.vue` | M2, M3 | DONE |
| M5 | High-Impact Graphics & Charts Polish | `src/components/GammaExposureMap.vue`, `src/components/OptionsDriftChart.vue`, `src/components/ProbabilityDensityChart.vue`, `src/components/RiskNeutral3DModel.vue`, `src/components/GammaHistoryStrip.vue` | M1 | DONE |
| M6 | E2E & Full Test Pass Verification | Full dashboard test suites + TypeScript build + Forensic Audit | M1, M2, M3, M4, M5 | DONE |

## Interface Contracts
### `src/styles/tokens.css` ↔ Vue Components
- `--call`: `#10b981` (High-contrast emerald green for Call contracts & Bullish structures)
- `--call-hi`: `#34d399` (High-contrast bright emerald for highlights)
- `--call-wash`: `rgba(16, 185, 129, 0.12)` (Translucent emerald wash for fills/tails)
- `--put`: `#f43f5e` (High-contrast crimson red for Put contracts & Bearish structures)
- `--put-hi`: `#fb7185` (High-contrast bright crimson for highlights)
- `--put-wash`: `rgba(244, 63, 94, 0.12)` (Translucent crimson wash for fills/tails)

### `src/format.ts` / Options Display Formatting
- Currency: `optUsd(val, fallback = '$0.00')` -> outputs `$X.XX` or `$0.00`
- Percentage: `optPct(val, fallback = '0.00%')` -> outputs `X.XX%` or `0.00%`
- Signed GEX: `signedGex(val, fallback = '$0.0M')` -> outputs `+$X.XM`, `-$X.XM`, or `$0.0M`
- Counts / Integers: `optNum(val, fallback = '0')` -> outputs `X` or `0`
- Missing status: `<span class="badge-na">N/A</span>`

## Code Layout
- `dashboard/src/styles/tokens.css`: Core design system variables
- `dashboard/src/squeezeCalc.ts`: Pure algorithmic calculations for squeeze setups, rings, and takeaways
- `dashboard/src/components/SqueezeScreener.vue`: Squeeze gauge, setup, factors, levels, takeaways
- `dashboard/src/views/OptionsView.vue`: Master options flow, strike chain, KPI rail, stalker cards
- `dashboard/src/components/OptionsConvictionBoard.vue`: Conviction pressure meter & rankings table
- `dashboard/src/components/OptionsDirectionBrief.vue`: Directional read headline, score track, evidence
- `dashboard/src/components/OptionsFlowContext.vue`: Tape contract mix, desk action triage
- `dashboard/src/components/GammaExposureMap.vue`: Interactive dual-bar GEX chart & level markers
- `dashboard/src/components/OptionsDriftChart.vue`: Underlying close + premium activity dual-pane chart
- `dashboard/src/components/ProbabilityDensityChart.vue`: 2D lognormal probability density curve
- `dashboard/src/components/RiskNeutral3DModel.vue`: Three.js 3D volatility surface
- `dashboard/src/format.ts` & `dashboard/src/flowDisplay.ts`: Formatting and flow calculation helpers
- `dashboard/src/__tests__/`: Automated test suites (45 suites, 661 tests)
