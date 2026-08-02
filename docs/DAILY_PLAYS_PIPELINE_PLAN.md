# Daily plays pipeline — frozen implementation plan

Date: 2026-07-30  
Status: core implemented; retained as the original design record  
Scope: `Kronos/`, `TradingAlgoWork/`, `TradingWork/`, and the consolidating `edge/` workspace

The current operating contract is in `DAILY_PLAYS_RUNBOOK.md`. Broad-market
and live-flow expansion is tracked in
`DAILY_PLAYS_MARKET_EXPANSION_PLAN.md`; those documents supersede any initial
policy defaults or delivery status recorded below.

## 1. Outcome

Build one operator command that produces today's ranked equity/options plays:

```bash
python3 -m edge.daily_plays today --account 1000
python3 -m edge.daily_plays today --account 1000 --json
```

The command must:

1. obtain a point-in-time candidate universe;
2. combine Kronos research with the repository's promoted internal models;
3. validate only shortlisted candidates against the live options feed;
4. return exact contract identities, entry/risk/invalidation details, evidence,
   freshness, and honest confidence;
5. explicitly return `ABSTAIN` when no candidate is execution-valid; and
6. persist an auditable run manifest and decision ledger.

This is decision support and shadow trading first. It must not place orders.

## 2. Existing components to reuse

| Need | Existing source | Planned role |
|---|---|---|
| Forecast/scenario prior | `Kronos/forecast_calibrated.py`, `Kronos/live_fusion_scan.py` | Research adapter; direction, interval, regime, GEX context |
| Promoted internal models | `TradingAlgoWork/tools/model_registry.py`, `trade_desk.py`, `live_plan.py` | Candidate direction and model evidence |
| Confidence policy | `TradingAlgoWork/tools/confidence_runtime.py` | Calibration/freshness gates and `ENTER/WATCH/ABSTAIN` semantics |
| Risk/vehicle selection | `TradingAlgoWork/tools/risk_manager.py`, `live_plan.py` | Account-aware maximum loss and equity/options routing |
| Contract selection | `TradingAlgoWork/tools/options_picker.py` | Candidate structure logic, refactored behind a live provider |
| Live market/options access | `TradingAlgoWork/services/market_runtime/LSEAdapter`, `tools/gamma_exposure.py` | Primary production market and chain source |
| Options/flow evidence | `TradingWork/src/lse_provider.py`, `uoa_scanner.py`, `signal_journal.py` | Forward options-flow context and eventual outcomes |
| Audit/evaluation | `edge/eval/`, `edge/runs/` | Point-in-time tests, shadow ledger, reliability reports |

The new package lives in `edge/daily_plays/`. Source repositories remain
independent and are consumed through adapters; the first implementation wave
must not rewrite them.

## 3. Non-negotiable truth rules

1. **Kronos is a prior, not decision confidence.** The historical selective
   71%/82% result is contaminated by lookahead. Kronos can contribute direction,
   forecast interval, regime, and agreement, but cannot directly raise the
   reported calibrated probability.
2. **Calibration is not edge.** `v90_wide` passed calibration but failed the
   pre-registered expectancy gate. It cannot be silently promoted across the
   widened universe.
3. **Live means fresh and identified.** A play is not `ENTER` unless every
   actionable option leg has an exact identifier and a sufficiently fresh,
   executable quote from the primary live source.
4. **Delayed fallback is research-only.** `yfinance` may keep development and
   replay paths usable, but any option proposal built from it is marked
   `DEGRADED` and capped at `WATCH`.
5. **No-play is a valid result.** The pipeline succeeds with an empty `plays`
   array plus abstention reasons when the data or evidence is weak.
6. **No arbitrary confidence blending.** Model probability, evidence quality,
   and execution validity remain separate fields. Execution data gates a play;
   it does not manufacture a higher model probability.
7. **No order placement.** Phase 1 writes operator tickets and a shadow ledger
   only.

## 4. Target architecture

```text
Session clock + run context
          |
          v
Candidate universe --------> Kronos adapter (research prior)
          |                   Internal-model adapter (calibrated/ordinal signal)
          |                   Forward-flow adapter (optional evidence)
          +-------------------------------+
                                          v
                                Candidate fusion/ranking
                                          |
                                shortlist (small, bounded)
                                          |
                                          v
                           Live options chain + quote validation
                                          |
                                          v
                              Risk and structure construction
                                          |
                                          v
                    Confidence policy + ENTER/WATCH/ABSTAIN gate
                                          |
                         +----------------+----------------+
                         v                                 v
                 Console/JSON report               Run + shadow ledger
```

The expensive live chain work happens only after candidate ranking. The same
run clock and `asof_utc` are passed to every adapter to prevent accidental
future-data mixing.

## 5. Canonical contracts

### 5.1 Run manifest

Every invocation persists:

```json
{
  "schema_version": "daily-plays-run-v1",
  "run_id": "20260730T140500Z-<hash>",
  "requested_for": "2026-07-30",
  "asof_utc": "2026-07-30T14:05:00Z",
  "market_session": "regular",
  "account": 1000.0,
  "mode": "live|degraded|replay",
  "providers": {},
  "model_versions": {},
  "config_hash": "...",
  "code_provenance": {},
  "warnings": []
}
```

### 5.2 Play

Each play has:

```json
{
  "schema_version": "daily-play-v1",
  "play_id": "<run_id>:<symbol>:<strategy>",
  "symbol": "NVDA",
  "side": "long|short",
  "strategy": "call_debit_spread|put_debit_spread|long_call|long_put|equity",
  "state": "ENTER|WATCH|ABSTAIN",
  "rank": 1,
  "thesis": [],
  "invalidation": [],
  "entry": {
    "limit_reference": 0.0,
    "underlying_reference": 0.0,
    "quote_asof_utc": "...",
    "max_quote_age_seconds": 0
  },
  "legs": [],
  "risk": {
    "account": 1000.0,
    "max_loss_dollars": 0.0,
    "max_loss_pct": 0.0,
    "contracts": 0,
    "reward_risk_reference": null
  },
  "confidence": {
    "state": "ENTER|WATCH|ABSTAIN",
    "model_probability": null,
    "calibrated_probability": null,
    "confidence_kind": "calibrated_probability|ordinal_score|unavailable",
    "calibration_version": null,
    "evidence_grade": "A|B|C|F",
    "reasons": [],
    "failed_checks": []
  },
  "evidence": {
    "internal_model": {},
    "kronos": {},
    "options": {},
    "flow": {},
    "macro": {}
  },
  "freshness": {},
  "provenance": {}
}
```

### 5.3 Option leg identity

Every option leg must include:

```json
{
  "side": "buy|sell",
  "right": "call|put",
  "occ_symbol": "NVDA260821C00180000",
  "underlying": "NVDA",
  "expiry": "2026-08-21",
  "dte": 22,
  "strike": 180.0,
  "multiplier": 100,
  "bid": 0.0,
  "ask": 0.0,
  "mid": 0.0,
  "spread_pct": 0.0,
  "volume": 0,
  "open_interest": 0,
  "iv": null,
  "delta": null,
  "quote_asof_utc": "...",
  "provider": "lse",
  "provider_contract_id": null
}
```

No generated or inferred expiry/strike/contract symbol is allowed. Missing
identity or quote fields force `ABSTAIN`.

## 6. Pipeline stages

### Stage A — session and safety preflight

- Resolve the requested trading date in `America/New_York`.
- Record whether the run is premarket, regular, after-hours, closed, or replay.
- Create one immutable run context containing `asof_utc`.
- Validate account/risk configuration and required provider credentials.
- In production, fail closed if LSE live data is unavailable.
- In development, allow delayed fallback but mark the full run `DEGRADED`.

### Stage B — candidate generation

- Start from a configured liquid universe with sector and event metadata.
- Request internal-model reads through the existing registry and live-plan
  primitives.
- Load or generate Kronos scenarios through a dedicated adapter.
- Attach macro/regime and forward options-flow evidence when available.
- Apply cheap liquidity, price, event, and model-support filters.
- Rank to a bounded shortlist (default 10) before requesting chains.

Kronos agreement can break ties or change evidence grade, but cannot change a
calibrated probability.

### Stage C — live options validation

For every shortlisted symbol:

- fetch one synchronized underlying quote and listed expirations;
- choose only contracts inside configurable DTE, delta, risk, and liquidity
  windows;
- reject stale, crossed, zero-bid, missing-identity, or excessive-spread quotes;
- capture volume, open interest, IV, Greeks when supplied, GEX/walls, and flow;
- construct at most a small number of debit-defined-risk structures;
- recompute debit and maximum loss from the live leg quotes; and
- retain the exact rejected checks for operator inspection.

Initial conservative defaults, configuration-backed and testable:

- quote age: <= 30 seconds in regular session;
- DTE: 14–45 for swing, 0–7 only in a separately enabled intraday policy;
- spread: <= 15% of midpoint, with an absolute floor for low-premium contracts;
- open interest: >= 100 per long leg;
- volume: >= 10 per long leg;
- defined maximum loss: <= configured account risk budget;
- no market order language.

Defaults are policy, not claims of optimality. They require later empirical
validation.

### Stage D — confidence and final state

The gate is hierarchical:

1. model support and point-in-time integrity;
2. applicable calibrator and probability threshold;
3. setup/direction validity;
4. Kronos/macro contradiction check;
5. live quote freshness and contract identity;
6. liquidity/spread/risk checks;
7. portfolio exposure checks.

State rules:

- `ENTER`: applicable calibrated probability clears its pre-registered
  threshold, all execution gates pass, and there is no hard contradiction;
- `WATCH`: plausible setup but probability is ordinal/unavailable, a soft
  contradiction exists, or feed quality is degraded;
- `ABSTAIN`: stale/missing live data, missing contract identity, unsupported
  model domain, failed risk gate, or no setup.

Display both `confidence_kind` and calibration version beside any number. Never
format an ordinal score as a probability.

### Stage E — output and persistence

Human output is a compact ranked table followed by exact operator tickets.
Machine output is the canonical JSON contract. Persist:

```text
edge/runs/daily_plays/<run_id>/manifest.json
edge/runs/daily_plays/<run_id>/candidates.json
edge/runs/daily_plays/<run_id>/option_snapshots.json
edge/runs/daily_plays/<run_id>/plays.json
edge/runs/daily_plays/shadow_decisions.jsonl
```

Raw secrets and authorization headers must never be written.

## 7. Package layout

```text
edge/daily_plays/
  __init__.py
  __main__.py
  cli.py
  clock.py
  contracts.py
  config.py
  pipeline.py
  fusion.py
  options_validation.py
  render.py
  ledger.py
  adapters/
    kronos.py
    internal_models.py
    options.py
    flow.py
edge/config/daily_plays.json
edge/tests/daily_plays/
```

Adapters normalize source-specific payloads immediately. Core pipeline code
must not depend on raw `yfinance`, LSE SDK, Kronos, or trade-desk payload shapes.

## 8. Validation gates

### Unit/property tests

- schema round-trip and rejection of incomplete option identities;
- deterministic run IDs/config hashes for frozen inputs;
- New York session/calendar boundary tests;
- future bars cannot change an earlier run;
- quote age, crossed market, zero bid, spread, OI, volume, and risk gates;
- ordinal confidence cannot emit `ENTER`;
- Kronos inputs cannot increase calibrated probability;
- stale/degraded provider cannot emit `ENTER`;
- empty valid run returns `plays=[]`, not a crash.

### Replay integration tests

- frozen Kronos, internal-model, and live-chain fixtures produce a stable report;
- provider timeout/retry/circuit-breaker paths;
- one bullish, one bearish, one no-play, and one stale-feed scenario;
- JSON contains no NaN/Infinity and matches `daily-play-v1`.

### Shadow acceptance

Before any live-capital discussion:

- at least 60 market sessions;
- every decision realized after its configured horizon;
- reliability by confidence bucket and state;
- expectancy after realistic spread/slippage;
- false-positive and abstention rates;
- data/provider failure rate;
- no unresolved lookahead or timestamp violations.

Promotion requires a new pre-registered gate. Passing technical tests alone
does not promote the pipeline to live trading.

## 9. Delivery waves and worker ownership

### Wave 1 — parallel foundations

**Worker A: core contract and CLI**

- Own only `edge/daily_plays/{__init__,__main__,cli,clock,contracts,config}.py`,
  `edge/config/daily_plays.json`, and matching core tests.
- Implement typed canonical contracts, run context, configuration, and a CLI
  shell with dependency injection.
- No live provider calls and no edits to source repositories.

**Worker B: research/model adapters and fusion**

- Own only `edge/daily_plays/adapters/{kronos,internal_models,flow}.py`,
  `edge/daily_plays/fusion.py`, and matching tests/fixtures.
- Normalize existing source outputs and enforce the Kronos confidence
  restriction.
- No CLI, options-provider, or persistence edits.

**Worker C: live options adapter and validation**

- Own only `edge/daily_plays/adapters/options.py`,
  `edge/daily_plays/options_validation.py`, and matching tests/fixtures.
- Use LSE as primary, explicit delayed fallback for development, exact contract
  identity, quote freshness, liquidity, spread, and risk checks.
- No CLI, fusion, or source-repository edits.

### Wave 2 — integration

**Worker D: pipeline, renderer, and replay**

- Starts only after Workers A–C complete.
- Own `edge/daily_plays/{pipeline,render,ledger}.py`, end-to-end fixtures/tests,
  and the operator runbook.
- Wire adapters through the contracts; do not weaken any fail-closed gate.
- Demonstrate the command with frozen replay data before attempting a live call.

### Wave 3 — shadow operations

**Worker E: scheduler/realization/monitoring**

- Add idempotent scheduled invocation, outcome realization, reliability
  reporting, and provider/model health metrics.
- Extend the ledger without changing the `daily-play-v1` contract.
- Produce a 60-session readiness checklist; do not enable order submission.

## 10. Definition of done

The delegated implementation is complete when:

1. both documented commands run from the workspace root;
2. frozen replay tests pass without network access;
3. a live run either returns fully identified validated plays or an honest
   no-play/degraded result;
4. every play includes exact option leg identity, quote timestamp/source,
   maximum loss, invalidation, evidence, confidence kind, and reasons;
5. no ordinal or Kronos-derived score is presented as calibrated probability;
6. all raw inputs and outputs are auditable by `run_id`;
7. the pipeline cannot place an order; and
8. the shadow/reliability path is ready for 60 sessions.

## 11. Explicitly deferred

- automatic broker order entry;
- GPU fine-tuning of Kronos while the current pre-registered gate remains
  `NO-GO`;
- a new blended meta-model trained on the same already-used holdout;
- claiming profitability from backtests or from confidence calibration alone;
- sweeping the full options universe before candidate ranking.
