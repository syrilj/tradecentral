# E2E Test Infra: TradeCentral Performance & Contract Invariant Verification

## Test Philosophy
- **Opaque-box & Requirement-driven**: Tests derive strictly from user requirements in `ORIGINAL_REQUEST.md` and system architecture in `PROJECT.md`, verifying observable behaviors, API contracts, quantitative guarantees, and performance boundaries.
- **Methodology**: Systematic 4-Tier verification combining Category-Partition, Boundary Value Analysis (BVA), Pairwise Combinatorial Interaction Testing, and Realistic Market Workload Simulation.
- **Progressive Verification**: Independent test modules for Backend REST API, Scan & Model Pipelines, and Frontend UI Telemetry, unified under a high-performance test harness in `tests/e2e/`.

## Feature Inventory
| # | Feature | Source (Requirement) | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|---|---------|----------------------|:------:|:------:|:------:|:------:|
| 1 | F1.1 Watchlist Polling Batching | ORIGINAL_REQUEST R1 / PROJECT §F1.1 | 5 | 5 | ✓ | ✓ |
| 2 | F1.2 Quote Marks Reactivity Optimization | ORIGINAL_REQUEST R1 / PROJECT §F1.2 | 5 | 5 | ✓ | ✓ |
| 3 | F1.3 Visibility-Guarded Telemetry | ORIGINAL_REQUEST R1 / PROJECT §F1.3 | 5 | 5 | ✓ | ✓ |
| 4 | F1.4 WebGL Resource Disposal | ORIGINAL_REQUEST R1 / PROJECT §F1.4 | 5 | 5 | ✓ | ✓ |
| 5 | F1.5 Design Token & Contract Preservation | ORIGINAL_REQUEST R4 / PROJECT §F1.5 | 5 | 5 | ✓ | ✓ |
| 6 | F2.1 Backend Serialization Optimization | ORIGINAL_REQUEST R2 / PROJECT §F2.1 | 5 | 5 | ✓ | ✓ |
| 7 | F2.2 Time-Series Formatting Acceleration | ORIGINAL_REQUEST R2 / PROJECT §F2.2 | 5 | 5 | ✓ | ✓ |
| 8 | F2.3 Search Metadata & Parquet Caching | ORIGINAL_REQUEST R2 / PROJECT §F2.3 | 5 | 5 | ✓ | ✓ |
| 9 | F2.4 Quote Provider Concurrency & Waterfall | ORIGINAL_REQUEST R2 / PROJECT §F2.4 | 5 | 5 | ✓ | ✓ |
| 10 | F2.5 Backend API Contract Invariants | ORIGINAL_REQUEST R4 / PROJECT §F2.5 | 5 | 5 | ✓ | ✓ |
| 11 | F3.1 Directional Model Compute Deduplication | ORIGINAL_REQUEST R3 / PROJECT §F3.1 | 5 | 5 | ✓ | ✓ |
| 12 | F3.2 Concurrent Scan Stage Execution | ORIGINAL_REQUEST R3 / PROJECT §F3.2 | 5 | 5 | ✓ | ✓ |
| 13 | F3.3 Parallel Parquet I/O with Column Projection | ORIGINAL_REQUEST R3 / PROJECT §F3.3 | 5 | 5 | ✓ | ✓ |
| 14 | F3.4 Quantitative Calibration & Gate Invariants | ORIGINAL_REQUEST R4 / PROJECT §F3.4 | 5 | 5 | ✓ | ✓ |

## Test Architecture
- **Runner**: Pytest runner with unified runner script `tests/e2e/run_all_e2e.py` and Vitest runner in `dashboard/`.
- **Backend/Scan Invocations**:
  - `python3 -m pytest tests/e2e/ -v`
  - `python3 tests/e2e/run_all_e2e.py`
- **Frontend Invocations**:
  - `npm test` inside `dashboard/`
- **Pass/Fail Semantics**: All test suites must complete with exit code 0 and 0 failures. No test assertion may rely on mocked no-op placeholders or hardcoded expected strings.
- **Directory Layout**:
  ```
  tests/e2e/
  ├── __init__.py
  ├── conftest.py                   # Shared fixtures, FastAPI TestClient, synthetic Parquet generators
  ├── run_all_e2e.py                # Standalone unified test runner with structured TAP/summary output
  ├── test_tier1_features.py        # Tier 1: 70+ feature coverage tests across F1.1-F3.4
  ├── test_tier2_boundaries.py      # Tier 2: 70+ boundary, extreme value, and corner case tests
  ├── test_tier3_pairwise.py        # Tier 3: 15+ cross-feature combination & interaction tests
  └── test_tier4_scenarios.py       # Tier 4: 8+ end-to-end real-world market workload scenarios
  dashboard/src/__tests__/
  ├── desk-empirical-stress.test.ts # Frontend batching, reactivity, and visibility lifecycle
  ├── desk-market-contract.test.ts  # Token compliance, contract strings, and liveMarks
  └── ... (19 Vitest test suites)
  ```

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Full Market Open Scan & Broadcast | F2.1, F2.4, F2.5, F3.2, F3.3 | High |
| 2 | High-Volatility Multi-Symbol Stream | F1.1, F1.2, F2.1, F2.4 | High |
| 3 | Deep Quantitative Signal Generation | F3.1, F3.2, F3.3, F3.4 | High |
| 4 | Search Navigation & Trajectory Rendering | F2.1, F2.2, F2.3, F2.5 | Medium |
| 5 | Background Inactivity & Wakeup Cycle | F1.3, F1.4, F2.4 | Medium |
| 6 | Fail-Closed Model Rejection & Gate Enforcement | F2.5, F3.4 | High |
| 7 | High-Concurrency API Burst & Caching | F2.1, F2.3, F2.4 | High |
| 8 | End-to-End Market Day Simulation | F1.1, F1.5, F2.5, F3.1, F3.2, F3.4 | High |

## Coverage Thresholds
- **Tier 1 (Feature Coverage)**: >=5 tests per feature $\times 14$ features = **70 test cases minimum**.
- **Tier 2 (Boundary & Corner Cases)**: >=5 tests per feature $\times 14$ features = **70 test cases minimum**.
- **Tier 3 (Cross-Feature Pairwise)**: >=1 test per major feature pair = **15 test cases minimum**.
- **Tier 4 (Real-World Scenarios)**: Realistic end-to-end trading workflows = **8 test cases minimum**.
- **Total Minimum E2E Test Suite**: **163 test cases** across backend, scan, and frontend contract suites.
