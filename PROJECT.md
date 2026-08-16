# Project: Institutional Market Section & Free Intelligence Pipeline

## Architecture
- **Frontend Cockpit (`dashboard/src/views/MarketView.vue`, `dashboard/src/components/`)**: High-density QuiverQuant/Bloomberg-inspired market intelligence cockpit in Vue 3 + TypeScript, featuring 10 integrated analytical tabs, interactive statement toggles, zero-emoji institutional typography, standardized "Coming Soon / Data Source Unavailable" containers, and strict `—` missing value formatting.
- **Backend Stock Intelligence Engine (`tools/financial_data.py`, `tools/api_server.py`)**: High-throughput multi-period financial statement extractor, ratio engine, executive compensation compiler, analyst consensus target aggregator, SEC Form 4 insider trading tape, STOCK Act congressional trading tracker, LDA corporate lobbying ledger, USASpending federal contracts parser, USPTO patents registry, and 13F institutional ownership calculator.
- **SEC EDGAR Direct Feed & Alternative Data Ingestion (`tools/sentiment_anomalies.py`)**: Direct CIK-mapped querying of SEC EDGAR public JSON submissions with rate-limit compliance and multi-tier caching (15m in-memory TTL, 7-day disk persistence).
- **Dual-Track Testing & Integrity Verification (`tests/`, `dashboard/`)**: Comprehensive Pytest API contract suites, Vitest frontend component & zero-emoji verification suites (318+ passing tests), Vite production builds, and forensic integrity audits.

## Feature Inventory
| # | Feature | Description | Milestone | Source | Status |
|---|---------|-------------|-----------|--------|--------|
| F1.1 | Multi-Period Financial Statements & Margin Engine | Multi-period Income Statement, Balance Sheet, Cash Flow with gross/operating/net margins and segment/geo breakdowns | M1 | Survey Backend | DONE |
| F1.2 | Valuation & Solvency Ratio Extractor | 20+ financial ratios (P/E trailing/fwd, P/S, P/B, EV/EBITDA, D/E, Quick/Current, ROE, ROA, FCF) | M1 | Survey Backend | DONE |
| F1.3 | Executive Compensation & Officer Registry | Named executive officers, salaries, bonuses, stock awards, total pay, and CEO-to-median ratio | M1 | Survey Backend | DONE |
| F1.4 | Analyst Consensus, Price Targets & Earnings Surprise | Price targets (high, median, low, current, upside %), rating upgrades/downgrades, and EPS surprise history | M1 | Survey Backend | DONE |
| F1.5 | SEC Form 4 Insider Tape & Backtest Matrix | Form 4 transactions, 90-day net metrics, quarterly net volume matrix, and Form 4 strategy backtest tearsheet | M1 | Survey Backend | DONE |
| F1.6 | Government Disclosures & Federal Awards | Congressional trades (STOCK Act), lobbying disclosures (LDA), federal agency contracts, and USPTO patent grants | M1 | Survey Backend | DONE |
| F1.7 | 13F Ownership & Short Interest Analytics | Top institutional & mutual fund holders, float breakdown (institutional/insider/retail), short interest & days to cover | M1 | Survey Backend | DONE |
| F1.8 | SEC EDGAR Filings & News Feeds | Live CIK filings (10-K, 10-Q, 8-K) via SEC EDGAR public feeds and curated financial news items | M1 | Survey Backend | DONE |
| F1.9 | Multi-Ticker Compare & Normalized Trajectory | Multi-symbol comparison table (valuation, margins, momentum) and normalized % price trajectory | M1 | Survey Backend | DONE |
| F2.1 | Strict Zero-Emoji Institutional Design System | Eliminate 100% of unicode emojis in MarketView, replace with institutional typography and subtle badges | M2 | Survey Frontend | DONE |
| F2.2 | In-Tab Insiders Navigation (Loop Fix) | Fix circular redirect loop on Insiders tab so all 10 tabs render seamlessly in-cockpit | M2 | Survey Frontend | DONE |
| F2.3 | Standardized "Coming Soon / Unavailable" Fallbacks | Clean institutional container with informative subtext for unavailable datasets; eliminate fake numbers | M2 | Survey Frontend | DONE |
| F2.4 | High-Density QuiverQuant UX & Period/View Toggles | Dense data grids, statement view mode (Table/Charts), sticky headers, aligned tabular figures | M2 | Survey Frontend | DONE |
| F2.5 | Strict Dash (`—`) Formatting Invariant | Guarantee all missing/null values render as `—` (dash) across all tabs, never raw zeros or NaN | M2 | Survey Frontend | DONE |
| F3.1 | Dedicated MarketView Vitest Suite | Unit and contract tests for MarketView tab switching, zero-emoji invariant, and fallback states | M3 | Survey Specs | DONE |
| F3.2 | Backend Financial Intelligence Pytest Suite | Comprehensive endpoint tests for `/api/financials`, `/api/company-profile`, `/api/insiders`, `/api/government`, `/api/ownership` | M3 | Survey Specs | DONE |
| F3.3 | Full Suite Builds & Automated Verification | Passing `npm test` (318 tests), passing `pytest`, passing `npm run build`, and zero-emoji regex audit | M3 | Survey Specs | DONE |
| F3.4 | Forensic Integrity Audit | Static, runtime, and execution verification confirming genuine implementation and zero facade cheating (Verdict: CLEAN) | M3 | Survey Specs | DONE |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Backend Free Data Pipelines & API Ingestion | F1.1–F1.9 in `tools/financial_data.py`, `tools/api_server.py`, `tools/sentiment_anomalies.py` | None | DONE |
| M2 | Frontend MarketView Institutional UX & Zero-Emoji | F2.1–F2.5 in `dashboard/src/views/MarketView.vue`, `dashboard/src/components/`, `tokens.css` | M1 | DONE |
| M3 | Dual-Track Testing, Automated Verification & Forensic Audit | F3.1–F3.4 across `tests/`, `dashboard/`, Vitest, Pytest, Vite build | M2 | DONE |

## Interface Contracts
### Backend HTTP API Endpoints
- `GET /api/financials?symbol=SYM&period={quarterly|annual}`: Returns `FinancialsPayload` with `income_statement`, `balance_sheet`, `cash_flow`, `ratios`, `revenue_breakdown`, `period`, `source`, `asof`.
- `GET /api/company-profile?symbol=SYM`: Returns `CompanyProfilePayload` with `profile`, `compensation`, `analyst_targets`, `consensus`, `smart_score`, `thesis`, `upgrades_downgrades`.
- `GET /api/insiders?symbol=SYM`: Returns `InsidersIntelligencePayload` with `recent_transactions`, `quarterly_net`, `metrics_90d`, `strategy_backtest`, `source`.
- `GET /api/government?symbol=SYM`: Returns `GovernmentPayload` with `congressional_trades`, `lobbying`, `contracts`, `patents`, `source`.
- `GET /api/ownership?symbol=SYM`: Returns `OwnershipPayload` with `institutional_holders`, `mutual_fund_holders`, `breakdown`, `short_interest`, `source`.
- `GET /api/compare?symbols=SYM1,SYM2,...&window={1m|3m|6m|1y|all}`: Returns multi-ticker comparison metrics and normalized trajectory.
- `GET /api/sentiment?symbol=SYM`: Returns sentiment payload with embedded `sec_filings_for_symbol`.

### Data Formatting Invariants
- All missing or null metrics must be rendered as `—` (dash), never `0`, `0.0%`, or `NaN`.
- All financial numbers must follow institutional shorthand formatting (`$1.24B`, `$450.2M`, `$12.50/sh`, `14.2%`).
- Zero Unicode emojis permitted in any component or view.

## Code Layout
- `tools/financial_data.py`: Multi-period statements, ratios, compensation, targets, insiders, government, ownership data pipelines.
- `tools/api_server.py`: HTTP API routing and endpoint handlers for stock intelligence feeds.
- `tools/sentiment_anomalies.py`: SEC EDGAR direct JSON submissions scraper and filing link generator.
- `dashboard/src/views/MarketView.vue`: Main institutional market cockpit view with 10 analytical tabs.
- `dashboard/src/financialsDisplay.ts`: Data formatting and presentation utilities.
- `dashboard/src/insiderDisplay.ts`: Insider trading formatting utilities.
- `dashboard/src/api.ts`: Frontend TypeScript interfaces and API client functions.
- `tests/e2e/test_financial_intelligence_endpoints.py`: Pytest backend endpoint verification suite.
- `dashboard/src/__tests__/market_view_institutional.spec.ts`: Dedicated Vitest institutional market verification suite.
- `dashboard/src/views/__tests__/MarketView.spec.ts`: Component-level Vitest suite.
