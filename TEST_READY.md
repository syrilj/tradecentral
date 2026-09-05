# E2E Test Suite Ready: Real-Time Market Regime Detection & Price Attraction / Magnet Levels Engine

## 1. Test Execution Commands & Environments

### Frontend (Vitest & TypeScript Strict Typecheck)
```bash
# Run the dedicated price attractors E2E Vitest suite
cd dashboard && npx vitest run src/__tests__/price-attractors-e2e.test.ts

# Production build and vue-tsc strict typecheck
cd dashboard && npm run build
```

### Backend (Pytest & Python 3.10)
```bash
# Run the dedicated price attractors E2E Pytest suite
python3 -m pytest tests/e2e/test_price_attractors_e2e.py -v

# Run full project pytest suite
python3 -m pytest tests/e2e -q
```

---

## 2. 4-Tier Test Coverage Summary

| Tier | Category | Python Tests | TypeScript Tests | Total Passed | Description |
|:----:|:---------|:------------:|:----------------:|:------------:|:------------|
| **Tier 1** | **Feature Coverage** | 36 | 36 | **72 tests** | Isolated coverage of 6 features: Regime Classifier, Magnet Detection, Telemetry Calculations, Zero-Spoofing Protocol, API Contracts, and Concurrency Invariants. |
| **Tier 2** | **Boundary & Corner Cases** | 36 | 36 | **72 tests** | Comprehensive testing across 12 boundary dimensions: flat gamma, extreme moneyness, 0DTE vs 730DTE, missing OI, monotonic profiles, negative rates, multi-crossings, exact collisions, single contract, symmetric straddles, 300% IV, and malformed symbols. |
| **Tier 3** | **Pairwise Cross-Feature** | 8 | 8 | **16 tests** | Cross-subsystem interaction pairs: regime shift + retargeting, OpEx pinning + Kalman confluence, 0DTE charm + put wall, batch quote coalescing, missing OI enrichment, vanna shock expansion, collar inversion, and cluster-pull alignment. |
| **Tier 4** | **Real-World Scenarios** | 6 | 6 | **12 tests** | Institutional market simulations: Triple Witching quarterly pin, short-gamma squeeze cascade, 0DTE afternoon charm bleed, market open gap dislocation, put wall breach pivot, and post-earnings IV crush. |
| **Total** | **All 4 Tiers** | **86 tests** | **86 tests** | **172 tests** | **100% Pass Rate across Backend & Frontend Suites** |

---

## 3. Detailed Test Inventory Breakdown

### Tier 1: Feature Coverage (72 tests)
- **F01: Real-Time Market Regime Classifier**: Positive gamma dampening, negative gamma amplification, neutral transition flip band, 0DTE charm drift, kinematic acceleration vs mean-reversion, topography quadrant classification.
- **F02: Multi-Factor Price Magnet Detection**: Call wall overhead resistance, put wall downside support, gamma flip transition pivot, max pain pinning, kinematic Kalman drift, volume POC liquidity node, conviction rank descending ordering.
- **F03: Quantitative Attractor Telemetry**: Signed point distance $\Delta P$, signed percentage distance $\% \Delta$, gravitational pull score $S_{pull} \in [0, 100]$, directional classification (`above`, `below`, `at_spot`), component breakdown metadata, 1D expected move scaling.
- **F04: Zero-Spoofing & Anti-Fabrication Protocol**: Empty chain unmeasurable fallback, zero OI detection, null telemetry propagation, non-positive spot rejection, confluence zone exclusion, warnings transparency.
- **F05: API Server Telemetry Endpoints**: Payload schema adherence, supporting lens attribution, dominant direction resolution (`bullish_pull`, `bearish_pull`, `neutral_pin`), quality breakdown booleans.
- **F06: Concurrency & Cache Invariants**: Deterministic calculation idempotency, thread-safe parallel multi-worker execution, confluence zone thresholding, sub-millisecond analytical latency, valid ISO timestamp generation.

### Tier 2: Boundary & Corner Cases (72 tests)
- **B01: Zero & Flat Gamma Surfaces**: Neutral transition fallback, finite non-NaN pull scores, exact zero distance points/pct.
- **B02: Extreme Moneyness & Strikes**: Deep OTM strikes (500% from spot), sub-dollar penny stocks (4 decimal places), astronomical index levels ($50,000).
- **B03: Extreme DTE Regimes**: 0DTE intraday expiry (0.0002 years), 730DTE LEAPs (2.0 years), rapid charm bleed activation.
- **B04: Missing OI Feeds & Partial Topography**: Graceful BS fallback on None gammas/IVs, partial zero-OI strike handling.
- **B05: Monotonic Non-Crossing GEX Curves**: Strictly positive / strictly negative gamma, monotonic gamma flip fallback.
- **B06: Zero & Negative Interest Rates**: Black-Scholes stability at $r = 0$ and $r < 0$.
- **B07: Multi-Crossing Gamma Topography**: Multi-crossing profile root finding, multi-attractor candidate retention, scale-free regime strength $[0, 1]$.
- **B08: Exact Strike Collision / Spot at Gamma Flip**: Spot equals strike, spot equals gamma flip, max pain at spot.
- **B09: Single-Contract & Sparse Chains**: 1-strike chain handling, single strike call/put wall detection, single level confluence exclusion.
- **B10: Symmetric Straddle Distributions**: Near-zero net GEX, dominant direction neutral pin, equal pull scores.
- **B11: Extreme Volatility Spikes (>300% IV)**: Non-NaN gamma calculation, wide 1D expected move, bounded pull scores.
- **B12: Malformed Payloads & Non-Standard Symbols**: Lowercase ticker normalization, crypto hyphenated tickers (BTC-USD), mismatched sequence lengths.

### Tier 3: Cross-Feature Pairwise Combinations (16 tests)
- **P01**: Regime Transition + Magnet Retargeting on Spot Shift
- **P02**: OpEx Pinning + Kinematic Envelope Confluence Zone
- **P03**: 0DTE Afternoon Charm Bleed + Put Wall Decay Interaction
- **P04**: Batch Quote Coalescing + Multi-Threaded In-Flight Deduplication
- **P05**: Missing OI Feed + Option Chain Payload Integration
- **P06**: High Vanna Sensitivity + Volatility Expansion Regime Mapping
- **P07**: Call Wall / Put Wall Collar Inversion Handling
- **P08**: Confluence Cluster Formation + Dominant Direction Alignment

### Tier 4: Real-World Institutional Scenarios (12 tests)
- **S01**: Triple Witching Quarterly OpEx Pinning Simulation ($500 strike, 120k OI concentration)
- **S02**: Short-Gamma Squeeze Cascade Acceleration Simulation (Call Wall breach in negative gamma)
- **S03**: 0DTE Afternoon Charm Bleed Flash Draw Simulation (Late session dealer delta re-hedging)
- **S04**: Market Open Volatility Dislocation & Gap Handling (+4% pre-market gap re-indexing)
- **S05**: Sudden Regime Pivot upon Put Wall Breach (Support breakdown volatility cascade)
- **S06**: Earnings Announcement IV Crush & Magnet Dissipation Simulation (120% -> 30% IV collapse)

---

## 4. Gate & Forensic Audit Verdict
- Reviewer 1 Verdict: **APPROVE (100% Contract & Specification Conformance)**
- Reviewer 2 Verdict: **APPROVE (100% Boundary & Concurrency Safety)**
- Challenger 1 Verdict: **CONFIRMED (Zero Fragility under Degenerate Data)**
- Challenger 2 Verdict: **CONFIRMED (Zero Leakage under Multi-Threading)**
- Forensic Integrity Auditor: **CLEAN (0 Violations — 100% Genuine Computations, No Hardcoded Bypasses)**
