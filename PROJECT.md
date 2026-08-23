# Project: TradeCentral Dashboard Visual Redesign & Layout Overhaul

## Architecture
TradeCentral is a high-performance Vue 3 + TypeScript quantitative market research and decision-support workstation for US equities and options.
- **Frontend Stack**: Vue 3 (Composition API), Vite 6, TypeScript (`vue-tsc`), Vitest v3, `@clerk/vue`, Geist & Geist Mono fonts, GSAP, Three.js.
- **Styling Paradigm**: Custom CSS Custom Properties (`src/styles/tokens.css`, `src/styles/base.css`), Scoped CSS, Strict Design Conformance (`design-conformance.test.ts`).
- **Core Layout Architecture**: `src/App.vue` (top instrument strip `.strip`, collapsible sidebar rail `.rail`, stage `.stage`, footer `.foot`).
- **Component Ecosystem**: Reusable UI components in `src/components/`, views in `src/views/`, composables in `src/composables/`, routes in `src/router.ts`.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Glassmorphism Design Tokens | Add `--glass-*` tokens (surfaces, multi-layer frosted borders, subtle specular highlights, blurs, shadows) compliant with `design-conformance.test.ts`. | M1 | ORIGINAL_REQUEST §R4 |
| 2 | Aceternity UI Utility Classes | Add `.glass-panel`, `.glass-card`, `.glass-chip`, `.btn-glass`, `.input-glass` to `base.css` with responsive hover states and micro-interactions. | M1 | ORIGINAL_REQUEST §R4 |
| 3 | Core UI Primitives Upgrade | Upgrade `Panel.vue`, `SearchPalette.vue`, `HelpTip.vue`, and `VerdictChip.vue` to leverage modern glassmorphic tokens. | M1 | ORIGINAL_REQUEST §R4 |
| 4 | Frosted Top Navigation Bar | Sleek top bar (`.strip`) with frosted glass backdrop (`backdrop-filter: blur`), active market tape tickers (SPY/QQQ/DIA/XLE with sparklines), VIX context, Sector Rotation board, Fear/Greed gauge, session clock, and search trigger. | M2 | ORIGINAL_REQUEST §R1 |
| 5 | Collapsible Side Navigation | Intuitive collapsible side rail (`.rail`) with smooth expanding/collapsing transitions, categorized tool groups (Core Desk, Market Analytics, Research Lab), glowing active route indicators, and tooltips. | M2 | ORIGINAL_REQUEST §R1 |
| 6 | Preferences Composable | Create `src/composables/usePreferences.ts` managing density (`compact`/`comfortable`), accent theme, audio cues, and `localStorage` persistence. | M3 | ORIGINAL_REQUEST §R2 |
| 7 | Operator Profile Drawer / Modal | Create `src/components/ProfileDrawer.vue` displaying authenticated operator info (Clerk), session telemetry, layout density toggles, theme preferences, and sign-out actions. | M3 | ORIGINAL_REQUEST §R2 |
| 8 | Dual Profile Triggers | Connect Profile Drawer to both top-right header trigger in `.strip` and side navigation in `.rail`. | M3 | ORIGINAL_REQUEST §R2 |
| 9 | Options Chain Multi-tiered Strike Grid | Redesign `views/OptionsView.vue` and `views/DriftView.vue` with dense, readable multi-tiered strike tables, call/put side-by-side grids, and clear visual hierarchy for bid/ask, volume, and open interest. | M4 | ORIGINAL_REQUEST §R3 |
| 10 | Charm & Greeks Positioning Analytics | Revamp Black-Scholes charm $\partial\Delta/\partial t$ and Greeks positioning into interactive glassmorphic cards, smooth hover effects, clear heatmaps/sparklines, and streamlined strike/expiration controls. | M4 | ORIGINAL_REQUEST §R3 |
| 11 | Supply Chain & Options Calculator Polish | Enhance `views/ChainView.vue`, `views/CalculatorView.vue`, and `components/OptionsCalculator.vue` with frosted glass aesthetics, risk-reward bounds, and payoff diagrams. | M4 | ORIGINAL_REQUEST §R3 |
| 12 | End-to-End Build & Test Verification | Run full Vitest suite (all test files, 0 regressions) and verify `npm run build` (`vue-tsc --noEmit && vite build`) completes with 0 errors. | M5 | ORIGINAL_REQUEST §Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Glassmorphism & Aceternity Design System | `tokens.css`, `base.css`, `Panel.vue`, `SearchPalette.vue`, `VerdictChip.vue`, `HelpTip.vue` | None | DONE |
| 2 | Unified Navigation Shell & Top Bar | `App.vue`, Top Bar (`.strip`), Collapsible Side Nav (`.rail`), tool groupings, session clock, market tickers | M1 | DONE |
| 3 | Seamless Profile & Account Flow | `usePreferences.ts`, `ProfileDrawer.vue`, Header & Side Nav Profile triggers, density & preference controls | M1, M2 | DONE |
| 4 | Options Chain & Charm / Greeks Positioning | `views/OptionsView.vue`, `views/DriftView.vue`, `views/ChainView.vue`, `components/OptionsCalculator.vue`, analytics cards | M1 | IN_PROGRESS |
| 5 | Comprehensive Verification & Test Hardening | Vitest regression test suite, E2E test validation, design conformance check, production build check | M1, M2, M3, M4 | PLANNED |

## Interface Contracts
### Design System ↔ UI Components
- Semantic CSS variables in `src/styles/tokens.css` (Implemented & Verified):
  - `--glass-base`: `rgba(18, 20, 26, 0.65)`
  - `--glass-surface`: `rgba(18, 20, 26, 0.82)`
  - `--glass-surface-hi`: `rgba(24, 27, 34, 0.88)`
  - `--glass-overlay`: `rgba(8, 9, 12, 0.85)`
  - `--glass-border`: `rgba(255, 255, 255, 0.08)`
  - `--glass-border-hi`: `rgba(255, 255, 255, 0.16)`
  - `--glass-specular`: `inset 0 1px 0 rgba(255, 255, 255, 0.10)`
  - `--glass-shadow-sm`: `0 2px 8px rgba(0, 0, 0, 0.28)`
  - `--glass-shadow-lg`: `0 16px 48px rgba(0, 0, 0, 0.85)`
  - `--glass-blur-sm`: `blur(8px)`
  - `--glass-blur-md`: `blur(16px)`
  - `--glass-blur-lg`: `blur(24px)`
- Global utility classes in `src/styles/base.css` (Implemented & Verified):
  - `.glass-panel`, `.glass-card`, `.glass-chip`, `.btn-glass`, `.input-glass`

### Preferences Composable ↔ Shell & Profile Drawer
- `src/composables/usePreferences.ts`:
  ```ts
  export type DensityMode = 'compact' | 'comfortable';
  export interface UserPreferences {
    density: DensityMode;
    accent: string;
    soundEnabled: boolean;
    streamUpdates: boolean;
  }
  export function usePreferences(): {
    preferences: Ref<UserPreferences>;
    setDensity: (mode: DensityMode) => void;
    toggleSound: () => void;
    toggleStream: () => void;
  };
  ```

### Profile Drawer Component Interface
- `src/components/ProfileDrawer.vue`:
  - Props: `modelValue: boolean`, `userEmail?: string`, `telemetry?: WorkstationTelemetry`
  - Emits: `update:modelValue`, `signOut`, `updatePreferences`

## Code Layout
- `dashboard/src/styles/tokens.css`: Design system tokens and semantic color definitions.
- `dashboard/src/styles/base.css`: Global base styles and reusable glassmorphism utility classes.
- `dashboard/src/composables/usePreferences.ts`: Workstation preference management.
- `dashboard/src/components/ProfileDrawer.vue`: Operator profile, density toggle, and preferences drawer.
- `dashboard/src/App.vue`: Top navigation strip, collapsible side rail, route groupings, command palette.
- `dashboard/src/views/OptionsView.vue`: Options drift workspace, qualified flow tape, GEX strike map.
- `dashboard/src/views/DriftView.vue`: Charm $\partial\Delta/\partial t$ analytics, 3-factor breakdown cards, side-by-side Greeks strike table.
- `dashboard/src/views/ChainView.vue`: Thematic supply chain & value cascade graph.
- `dashboard/src/components/OptionsCalculator.vue`: Options pricing and Greeks sensitivity matrix.
