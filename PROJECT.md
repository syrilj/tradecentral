# Project: Market Regime System — Full Functional Rebuild & Mathematical Validation

## Architecture
The TradeCentral Market Regime System provides real-time and historical multi-dimensional market state detection for US equities and options. It is structured into a rigorous 3-layer point-in-time architecture with deterministic aggregation, calibrated confidence, dynamic explainability, and workstation UI integration:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               Layer 1: Raw Point-in-Time Features                      │
│ - Causal Log Returns (r_t) & Realized Volatility (Close-Close, Garman-Klass, Parkinson)│
│ - True Range & Average True Range (ATR_t)                                              │
│ - Session-Anchored VWAP & M2 Dispersion Bands (West's Incremental Algorithm)           │
│ - Slot-Relative Volume (rvol_slot) & Median Baseline                                   │
│ - Black-Scholes Greeks (Delta, Gamma, Vega, Theta, Vanna, Charm, Speed, Zomma)        │
│ - Strike-Level GEX, VEX, CHEX Dollar Profiles & Multi-root Flip Disambiguation        │
│ - Signed Flow Proxy (CLV * Volume) & Robust Median/MAD Z-Scores                        │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
┌───────────────────────────────────────────▼────────────────────────────────────────────┐
│                             Layer 2: Specialized Models                                │
│ 1. Trend Model: Kinematic Kalman Filter (log-price, velocity z-score, hysteresis)     │
│ 2. Volatility Model: Rolling 252d Realized Volatility Percentiles & Bounds             │
│ 3. Market Structure Model: Lo-MacKinlay Variance Ratio & OU Half-Life Mean Reversion   │
│ 4. Transition Model: CUSUM / BOCPD Changepoint Hazard & Flip Proximity Instability     │
│ 5. Flow Context Model: Microstructure Topography (FPR/BPR/FNS/BNS) & Flow State Machine│
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
┌───────────────────────────────────────────▼────────────────────────────────────────────┐
│                    Layer 3: Reconciliation & Calibrated Aggregation                    │
│ - Deterministic Mapping to Primary Regime:                                             │
│   (BULLISH_TREND | BEARISH_TREND | COMPRESSION_RANGE | MEAN_REVERTING |                │
│    VOL_EXPANSION_BREAKOUT | UNCERTAIN_TRANSITIONAL | UNMEASURABLE)                     │
│ - Probability Distribution: Normalized p_bull + p_bear + p_neutral = 1.0               │
│ - Calibrated Multi-Model Confidence: C = Q_data * A_models * D_boundary * S * (1-0.5T) │
│ - Multi-Model Agreement Matrix (5x5 Pairwise Alignment & Consensus Ratio)              │
│ - Fail-Closed Trigger: Forces UNCERTAIN_TRANSITIONAL on Conflict / High Hazard / Noise │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
┌───────────────────────────────────────────▼────────────────────────────────────────────┐
│                     Dynamic Explainability & Workstation Presentation                  │
│ - Feature Attribution Vector (alpha), Top Drivers, Agreeing vs. Diverging Models       │
│ - Backend API Endpoints: /api/market-regime, /api/gamma/regime, /api/microstructure    │
│ - Frontend Workstation: Unified Contracts, Primary Regime Card, 4-Pillar Context Grid, │
│   Transition Risk Gauge, Model Agreement Matrix, Zero-Spoofing Honest Missing States    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

## Feature Inventory
Every requirement from R1 through R6 is mapped to an assigned milestone:

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Point-in-Time Returns, Realized Vol & ATR | Strictly causal $t \le T$ log returns, rolling 20d/140h realized volatility, Wilder's ATR without lookahead. | M1 | R1, R2, Survey |
| 2 | West's Incremental Session VWAP & Dispersion | Numerically stable weighted VWAP $\mu_t$ and $M_{2,t}$ variance with session reset. | M1 | R1, R2, Survey |
| 3 | Black-Scholes Greeks & GEX Profiles | Complete 1st-3rd order Greeks (Delta, Gamma, Vega, Theta, Vanna, Charm, Speed, Zomma) and dollar GEX/VEX/CHEX. | M1 | R1, R2, Survey |
| 4 | Gamma Flip Disambiguation & Wall Extraction | Linear root crossing nearest to spot; directional call/put walls strictly on proper side of spot. | M1 | R1, R2, Survey |
| 5 | Kinematic Kalman Trend Model | Log-price 2-state constant-velocity Kalman filter with normalized velocity z-score and hysteresis. | M1 | R1, R2, Survey |
| 6 | Rolling Volatility Percentile Environment | Trailing 252d rolling percentile ranking of realized vol (low/normal/elevated/shock) avoiding expanding drift. | M1 | R1, R2, Survey |
| 7 | Market Structure Model (VR & OU Half-Life) | Lo-MacKinlay Variance Ratio ($q=5$) and Ornstein-Uhlenbeck mean-reversion half-life. | M1 | R1, R2, Survey |
| 8 | Transition & Change-Point Hazard Model | Continuous flip distance penalty + CUSUM/BOCPD run-length hazard score $T_{\text{risk}} \in [0, 1]$. | M1 | R1, R2, Survey |
| 9 | Flow Context & Microstructure Topography | Robust median/MAD signed flow z-score + 4-quadrant dealer topography (FPR, BPR, FNS, BNS). | M1 | R1, R2, Survey |
| 10 | Unified Layer 3 Deterministic Reconciliation | Multi-model state aggregation into Primary Regime, Volatility State, Market Structure, Flow Context. | M2 | R2, R3, Survey |
| 11 | Strictly Normalized Probability Distribution | Bounded probabilities summing strictly to 1.0 ($p_{\text{bull}} + p_{\text{bear}} + p_{\text{neutral}} = 1.0$). | M2 | R2, R3, Survey |
| 12 | Calibrated Multi-Factor Confidence Score | $C = Q_{\text{data}} \cdot A_{\text{models}} \cdot D_{\text{boundary}} \cdot S_{\text{persistence}} \cdot (1 - 0.5 T_{\text{risk}}) \in [0.0, 1.0]$. | M2 | R3, Survey |
| 13 | Multi-Model Agreement Matrix & Fail-Closed State | 5x5 model posture comparison; fail-closed trigger to `"Uncertain / Transitional"` on conflict or boundary proximity. | M2 | R3, Survey |
| 14 | Dynamic Explainability Engine | Signed feature attribution vector $\mathbf{\alpha}$, top leading drivers, agreeing/diverging models breakdown, dynamic alerts. | M2 | R4, Survey |
| 15 | Backend API Server Endpoints | `/api/market-regime`, `/api/gamma/regime`, `/api/microstructure-regime`, `/api/price-attractors` unified payloads. | M2 | R2, R4, Survey |
| 16 | TypeScript Data Contracts (`regimeContracts.ts`) | `UnifiedMarketState`, `MarketRegimePayload`, `PrimaryRegimeType`, `CalibratedConfidence`, 4 pillars, `TransitionRisk`. | M3 | R5, Survey |
| 17 | Client-Side Signals & Primitives (`regimeSignals.ts`) | Sub-session level crossings, trigger distance, normal CDF, missing-data safe fallback logic. | M3 | R5, Survey |
| 18 | Multi-Dimensional UI Workstation Components | `PrimaryRegimeCard.vue`, 4-Pillar context grid, `TransitionRiskGauge.vue`, `ModelAgreementMatrix.vue`, `DynamicExplanationPanel.vue`. | M3 | R5, Survey |
| 19 | Zero-Spoofing & Anti-Fabrication Remediation | Remove fake default prices (`$525`, `$522`), static numbers (`-234.7M`, `+87.4M`), and fabricated `Price > VWAP` in secondary cards. | M3 | R5, Survey |
| 20 | Historical Benchmark Simulation Suite | Replay historical slices (2020 crash, 2021 bull, 2022 bear, 2024 range) confirming stability, low whipsaws ($<10\%$), fast transition latency. | M4 | R6, Survey |
| 21 | Comprehensive Automated Backend & Frontend Tests | Causality property tests, mathematical boundary tests, extreme input numerical stability, Vitest UI rendering tests. | M4 | R6, Survey |
| 22 | Adversarial Hardening (Tier 5) | White-box stress testing under zero-variance, unipolar GEX, 0DTE expiry, single-stock small-cap vs index scaling. | M4 | R6, Survey |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Layer 1 & 2 Core Backend Models & Mathematical Rebuild | `research/regimes.py`, `research/regime_features.py`, `research/kalman_trend.py`, `research/microstructure_regime.py`, `research/bocpd.py`, `research/flow_state.py`, `daily_plays/regime_attractor_engine.py`, `research/gex_model.py`, backend tests | none | DONE |
| M2 | Layer 3 Aggregation, Calibrated Confidence & Dynamic Explainability | `research/regime_engine.py`, `research/regimes.py`, `daily_plays/regime_attractor_engine.py`, `daily_plays/desk_regime_fusion.py`, `daily_plays/adaptive_signal.py`, `tools/api_server.py`, backend reconciliation tests | M1 | DONE |
| M3 | UI Contracts, Signals & Frontend Workstation Components | `dashboard/src/regimeContracts.ts`, `dashboard/src/regimeSignals.ts`, `dashboard/src/api.ts`, `dashboard/src/components/`, `dashboard/src/views/`, secondary card sanitization, Vitest tests | M2 | IN_PROGRESS |
| M4 | Historical Simulation, E2E Test Verification & Adversarial Hardening | `eval/validate_historical_regimes.py`, `tests/`, `dashboard/src/__tests__/`, Tier 1-5 test execution, build validation | M1, M2, M3 | PLANNED |

## Interface Contracts
### `research/regimes.py` / `research/regime_engine.py` ↔ `tools/api_server.py`
- `compute_unified_market_regime(symbol: str, prices: pd.DataFrame, options_chain: Optional[pd.DataFrame] = None) -> UnifiedMarketState`
- Returns a structured dictionary / dataclass conforming to:
  * `symbol`: str
  * `spot`: Optional[float]
  * `asof`: str (ISO 8601 UTC)
  * `primary_regime`: PrimaryRegime enum string (`BULLISH_TREND`, `BEARISH_TREND`, `COMPRESSION_RANGE`, `MEAN_REVERTING`, `VOL_EXPANSION_BREAKOUT`, `UNCERTAIN_TRANSITIONAL`, `UNMEASURABLE`)
  * `confidence`: float in `[0.0, 1.0]`
  * `volatility_state`: str (`COMPRESSION_LOW`, `NORMAL_MEDIUM`, `ELEVATED_HIGH`, `VOLATILITY_SHOCK`)
  * `market_structure`: str (`TRENDING`, `MEAN_REVERTING`, `RANGE_BOUND`)
  * `flow_context`: str (`INSTITUTIONAL_ACCUMULATION`, `INSTITUTIONAL_DISTRIBUTION`, `ABSORPTION_CHURN`, `BALANCED_FLOW`)
  * `transition_risk`: float in `[0.0, 1.0]`
  * `probabilities`: `{"bullish": float, "bearish": float, "neutral": float}` where sum is strictly 1.0
  * `model_agreement`: `{"overall_agreement": float, "agreeing_models": List[str], "conflicting_models": List[str], "divergence_summary": Optional[str]}`
  * `explainability`: `{"summary_text": str, "leading_drivers": List[dict], "transition_alert": Optional[str]}`
  * `levels`: `{"call_wall": Optional[float], "put_wall": Optional[float], "gamma_flip": Optional[float], "session_vwap": Optional[float]}`
  * `quality`: `{"measurable": bool, "reason": Optional[str], "data_completeness": float}`

### `tools/api_server.py` ↔ `dashboard/src/api.ts` ↔ `dashboard/src/regimeContracts.ts`
- GET `/api/market-regime?symbol=X` returns `MarketRegimePayload` JSON matching TypeScript interface.
- Strict nulls: Missing or unmeasurable metrics serialize as `null` or `measurable: false`, never `0.00` or fake placeholders.

## Code Layout
- Backend analytics & models: `research/`, `daily_plays/`
- API server: `tools/api_server.py`
- Frontend logic & contracts: `dashboard/src/regimeContracts.ts`, `dashboard/src/regimeSignals.ts`, `dashboard/src/api.ts`
- Frontend components: `dashboard/src/components/`
- Frontend views: `dashboard/src/views/`
- Backend test suites: `tests/research/`, `tests/daily_plays/`, `tests/`, `eval/`
- Frontend test suites: `dashboard/src/__tests__/`
