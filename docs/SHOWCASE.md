# TradeCentral — Technical Showcase & Product Highlights

## The Workstation Gallery

These captures are from the running local workstation operating under real market conditions. In accordance with TradeCentral's core design philosophy, all data ages, provider source labels, missing states, and model confidence bounds are explicitly rendered rather than fabricated.

---

### 1. Options Positioning & Dealer Gamma Exposure (GEX)

![TradeCentral options positioning workspace](../dashboard/src/assets/showcase/options-positioning.png)

*Single-underlier options intelligence displaying net gamma exposure (GEX), open interest strike distribution, call resistance & put support walls, and risk-neutral implied range diagnostics.*

- **Gamma Topology:** Aggregates strike-level open interest and delta-adjusted gamma to compute the net dealer gamma profile. Highlights dealer pinning zones and volatility suppression bands.
- **Support & Resistance Walls:** Pinpoints the Call Wall (primary dealer hedge resistance / upside ceiling) and Put Wall (primary dealer hedge support / downside floor).
- **Provenance Transparency:** The data header displays exact source age, stale badges, and provider health.

---

### 2. Dealer-Gamma Regime & Microstructure Dynamics

![TradeCentral dealer-gamma regime workspace](../dashboard/src/assets/showcase/regime-dynamics.png)

*Executive regime briefing showing SPY Long Gamma stance, 2-state kinematic state-space filtering, causal Nadaraya-Watson envelopes, pivot ladder, and 1D / 1W expected move excursions.*

- **Dealer Stance Modeling:** Classifies whether market makers are in **Long Gamma** (damping volatility by fading extensions and buying weakness) or **Short Gamma** (amplifying trends via directional delta-hedging).
- **Kinematic State-Space Filtering:** 2-state Kalman filter and causal Nadaraya-Watson kernel envelopes isolate true price drift without introducing lookahead bias.
- **Microstructure Pivot Ladder:** Real-time calculated Call Wall, Put Wall, Gamma Flip Point, Kernel Mean ($m(t)$), and $\pm 1\sigma$ Expected Move bounds ($ATM \cdot IV / \sqrt{252}$).

---

### 3. Market-Wide Options Flow Tape & Real-Time Analytics

![TradeCentral market-wide options flow workspace](../dashboard/src/assets/showcase/flow-tape.png)

*Real-time provider options tape with 15s polling, sweep/block detection, whale orders ($500k+), vendor golden sweeps, cumulative net flow trend, and multi-tier expiry concentration.*

- **Institutional Tape Reading:** Tracks institutional options transactions with granular filters for aggressive Sweeps, Whale orders ($500k+), Volume > OI, and Unusual Moneyness.
- **Provider Analytics:** Displays cumulative net flow curve, call vs. put volume & premium distribution (e.g. Call Dominant flow), and premium concentration across DTE brackets (0 DTE, 1–7D, 8–30D, 30D+).
- **Fill Classification:** Heuristic trade categorization distinguishes between institutional size, burst sweeps, and multi-exchange fills with transparent missing-OI flags.

---

### 4. Directional Setups & Strike Execution Planning

![TradeCentral directional setups workspace](../dashboard/src/assets/showcase/setups-directional.png)

*Bullish & Bearish directional plans with planning mode safety gating, QLIR scores, exact contract strike candidates, dealer-hedge support levels, and take-profit targets.*

- **Gated Execution Workflow:** Operates in Planning Mode outside regular trading hours and strictly enforces multi-condition freshness gates before authorizing live directional entries.
- **Exact Contract Candidates:** Pinpoints recommended strike candidates based on open interest clusters, gamma pin levels, and delta-liquidity profiles.
- **Asymmetric Risk Profiles:** Automatically computes invalidation levels anchored to dealer-hedge support prints and tiered take-profit targets aligned with dealer call walls.

---

### 5. Volume Price Analysis (VPA) & Wyckoff Campaign Phase

![TradeCentral volume price analysis workspace](../dashboard/src/assets/showcase/vpa-analysis.png)

*Volume-price analysis on exact OHLCV bars: effort versus result, campaign phase, volume-profile POC, and value areas.*

- **Effort vs. Result Verification:** Evaluates candle spread versus traded volume to detect institutional absorption, stopping volume, tests of supply, and distribution spikes.
- **Volume Profile & Value Area:** High-resolution volume distribution highlighting Point of Control (POC), Value Area High (VAH), and Value Area Low (VAL).
- **Role-Reversed Price Levels:** Algorithmic identification of dynamic support and resistance zones with bar-level evidence tracing.

---

### 6. Thematic Value Chain Elasticity & Revenue Propagation

![TradeCentral value chain workspace](../dashboard/src/assets/showcase/value-chain.png)

*Thematic supply-chain node topology (GLP-1 & CDMO, Advanced Semiconductor, AI Infrastructure), CapEx sensitivity, revenue concentration, and options skew.*

- **Supply Chain Node Topology:** Maps interdependencies across Core Drivers, Tier 1 Suppliers, and Infrastructure Enablers across emerging industry megatrends.
- **CapEx Flow-Through Sensitivity:** Quantifies operating leverage and downstream revenue propagation resulting from upstream capital expenditure announcements.
- **Derivative Alignment:** Correlates fundamental supply chain positioning with options order-flow momentum and implied volatility skew.

---

### 7. Decision Brain Consensus Engine & Live Read

![TradeCentral decision workspace showing standby](../dashboard/src/assets/showcase/decision-live.png)

*Decision Brain consensus engine combining regime, structure, flow, and valuation lenses with explicit standby and out-of-sample capital validation.*

- **Multi-Lens Evidence Fusion:** Requires independent quantitative models (VPA, Dealer Gamma, Flow Tape, Trend Kinematics) to reach strict consensus before signaling conviction.
- **Fail-Closed Governance:** Reverts to explicit **Standby** whenever source quotes are stale, spread thresholds are violated, or model agreement is insufficient.

---

## Technical Portfolio & Architecture Highlights

Resume-ready project bullets for technical portfolios, interviews, and recruiter discussions:

- **Full-Stack Quantitative Workstation:** Designed and engineered TradeCentral from scratch using **Vue 3, TypeScript, and Python 3.10**. Integrated 15 specialized research surfaces covering options flow, dealer gamma exposure (GEX), microstructure regimes, and Wyckoff volume price analysis behind a high-density, accessible dark instrument interface.
- **Robust Mathematical & Microstructure Models:** Implemented 2-state kinematic Kalman state-space filtering, causal Nadaraya-Watson kernel envelopes, Black-Scholes greeks extraction, GEX topology modeling, and original volume-price analysis with bar-level evidence attribution.
- **Leak-Resistant Research & Evaluation Harness:** Built a point-in-time walk-forward evaluation framework with split-conformal prediction intervals, preregistered GO/NO-GO gate artifacts, and shadow-trading ledger auditing to prevent lookahead bias and data leakage.
- **Fail-Closed Decision Support Architecture:** Constructed typed provider adapters and evidence fusion logic that strictly fail closed; the engine abstains and reports explicit degraded/standby states whenever quotes are stale, spreads widen, or independent analytical lenses disagree.
- **High-Performance Edge & Cloud Deployment:** Shipped a production-grade Cloudflare Workers preview with owner-scoped Convex watchlists, Clerk authentication, and loopback Python API security verified by over 2,700 passing Vitest tests and security integration suites.

> **Disclaimer:** TradeCentral is designed strictly for quantitative research, market diagnostics, and decision support. The checked-in pipeline does not submit, place, or route broker orders. Backtests, model diagnostics, options analytics, and simulated outcomes are for research purposes only and do not constitute financial advice.
