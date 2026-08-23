# E2E Test Infra: TradeCentral Dashboard Visual Redesign

## Test Philosophy
- Opaque-box, requirement-driven. Derives from ORIGINAL_REQUEST.md.
- Methodology: Category-Partition + Boundary Value Analysis + Pairwise Combinatorial + Real-World Workload Testing.

## Feature Inventory & Test Mapping
| # | Feature | Source (Requirement) | Tier 1 (Feature) | Tier 2 (Boundary) | Tier 3 (Cross-Feature) | Tier 4 (Workload) |
|---|---------|----------------------|:----------------:|:-----------------:|:----------------------:|:-----------------:|
| 1 | Glassmorphism & Token Conformance | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| 2 | Aceternity UI Primitives | ORIGINAL_REQUEST §R4 | 5 | 5 | ✓ | ✓ |
| 3 | Frosted Top Bar & Tape Tickers | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 4 | Collapsible Side Nav & Tool Groups | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 5 | Operator Profile Drawer & Clerk Flow | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 6 | Density & Preferences Persistence | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 7 | Options Chain Strike Grid & Call/Put Hierarchy | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 8 | Charm & Greeks Positioning Analytics | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |

## Test Architecture
- Vitest unit & component test runner (`npm test` in `dashboard/`).
- TypeScript compiler & Vite build runner (`npm run build` in `dashboard/`).
- Design conformance suite (`src/__tests__/design-conformance.test.ts`).
- New test suites for navigation shell, profile flow, options chain, and preferences composables.

## Coverage Goals
- 100% test pass on all existing 52 test suites (991+ tests).
- 0 type errors on `vue-tsc --noEmit`.
- 0 design conformance violations (all CSS variables valid, no raw colors, no illegal halos).
