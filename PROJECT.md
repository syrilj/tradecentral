# Project: TradeCentral Full-Stack Performance Optimization

## Architecture
- **Frontend Cockpit (`dashboard/`)**: Vue 3 + TypeScript + Vite + Pinia + Three.js 3D Volatility Surfaces.
- **Backend API Server (`tools/api_server.py`)**: Multi-threaded HTTP JSON API server with in-memory caching and DirectApiClient for testing.
- **Market Scan & Signal Engines (`daily_plays/`, `tools/render_dashboard.py`)**: Multi-horizon XGBoost directional momentum models, PEAD earnings scanner, Qlib 16-factor alpha scorer, and LSE live options flow router.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1.1 | DeskView O(1) Pre-indexing | Replace O(N) array scans in `signalFor` and `peadFor` with reactive `computed` Maps; memoize sparkline generations | M1 | Survey Frontend |
| F1.2 | OptionsView Drawer Polling Gating | Gate background polling for `unusual` and `opportunities` resources when drawers are collapsed | M1 | Survey Frontend |
| F1.3 | WebGL Three.js Resource Management | Add explicit geometry/material disposal and render-on-demand loops to `RiskNeutral3DModel.vue` | M1 | Survey Frontend |
| F2.1 | Fast JSON Serialization & Headers | Replace recursive cloning `_sanitize` with direct fast JSON encoder handler and configure static asset caching | M2 | Survey Backend |
| F2.2 | Vectorized Time-Series Formatting | Vectorize `_build_series` with NumPy array calculations and single zip comprehension | M2 | Survey Backend |
| F2.3 | PyArrow Search Metadata Extraction | Extract row count/schema via PyArrow ParquetFile metadata in `_get_symbol_meta` and cache metadata | M2 | Survey Backend |
| F2.4 | Quote Provider Concurrency & Circuit Breaking | Avoid full Parquet decompression for latest quotes; circuit-break sequential timeframe timeouts | M2 | Survey Backend |
| F2.5 | API Contract Invariant Alignment | Harmonize response tags (`session`, `quality`, `source`, `flow_feed_contract`) across all 33 endpoints | M2 | Survey Backend |
| F3.1 | Directional Model Horizon Deduplication | Extract features and run XGBoost boosters once per symbol; vectorize horizon multipliers (5, 10, 20) | M3 | Survey Scan |
| F3.2 | Concurrent Scan Stage Execution | Parallelize independent stages (PEAD, Directional, Sector Flow, Qlib) via `ThreadPoolExecutor` in `get_dashboard_data` | M3 | Survey Scan |
| F3.3 | Multi-Threaded Parquet & Vectorized Qlib | Add column projection and parallel loading in `pead_adapter.py` and `qlib_scan_score.py` | M3 | Survey Scan |
| F3.4 | Quantitative Gate & Invariant Integrity | Preserve strict fail-closed criteria ($p \ge 0.65$), SHA-256 manifests, and ordinal isolation | M3 | Survey Scan |
| F4.1 | Automated Full-Suite Verification | Execute and achieve 0 failures across `npm test` (dashboard), `pytest` (backend 1029+ tests), and `npm run build` | M4 | Survey Global |
| F4.2 | Empirical Profiling Benchmark Report | Generate comprehensive before/after latency and throughput benchmarks demonstrating full-stack acceleration | M4 | Survey Global |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Frontend UI & Telemetry Optimization | F1.1, F1.2, F1.3 in `dashboard/` | None | DONE |
| M2 | Backend API Throughput & Latency | F2.1, F2.2, F2.3, F2.4, F2.5 in `tools/api_server.py` | None | DONE |
| M3 | Market Scan & Computation Acceleration | F3.1, F3.2, F3.3, F3.4 in `daily_plays/` & `tools/render_dashboard.py` | None | DONE |
| M4 | Full Suite Invariants & Profiling Benchmarks | F4.1, F4.2 across all test suites, builds, and benchmark harnesses | M1, M2, M3 | DONE |



## Interface Contracts
### Frontend ↔ Backend API Contracts
- `GET /api/quotes?symbols=...`: Must return `{ [symbol]: { last, change_pct, volume, quality, source, asof } }` where `quality` in `{"realtime", "delayed", "eod_parquet", "synthetic", "unavailable", "local", "live"}` and `source` in `{"lse_candles", "local_daily_parquet", "daily_parquet", "wide", "core", "synthetic"}`.
- `GET /api/market-clock`: Must return object containing both `market_session` and `session`.
- `GET /api/health`: Must return `flow_feed_contract: "market-wide-v1"` and `suggestion_contract: "flow-rule-v1"`.
- `GET /api/trajectory?symbol=...`: Must return `series: list[dict]` with keys `{"d", "o", "h", "l", "c", "v", "ret", "cum", "dd"}` with numeric rounding.

### Scan & Model Gate Invariants
- Entry gate requires calibrated probability $p \ge 0.65$ with `confidence_kind: "calibrated_probability"`.
- Ordinal scores remain `confidence_kind: "ordinal_score"` or `"ordinal_activity"`.
- SHA-256 model manifests (64 hex chars) must match frozen model artifacts.

## Code Layout
- `dashboard/src/views/DeskView.vue`: Desk cockpit view, watchlist, PEAD, Directional tables.
- `dashboard/src/views/OptionsView.vue`: Options analysis view, GEX charts, unusual flow, opportunities drawers.
- `dashboard/src/components/RiskNeutral3DModel.vue`: Three.js WebGL 3D implied volatility surface component.
- `dashboard/src/composables/useResource.ts`: Resource polling and lifecycle composable.
- `tools/api_server.py`: FastAPI / HTTP API server endpoints, serialization, time-series formatting, search metadata, quote provider.
- `daily_plays/adapters/internal_models.py`: XGBoost v90 directional model and multi-horizon serving adapter.
- `daily_plays/adapters/pead_adapter.py`: Post-earnings announcement drift candidate generator and parquet reader.
- `daily_plays/qlib_scan_score.py`: 16-factor cross-sectional alpha scoring engine and LightGBM evaluator.
- `tools/render_dashboard.py`: Multi-stage dashboard scan coordinator (`get_dashboard_data`).
