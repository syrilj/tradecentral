# VPA Rebuild Contract

Shared interface spec so backend / frontend / research workers can build in parallel
without stepping on each other. **This file is the source of truth. If you need to
deviate, write the deviation into this file (append to "Deviations") rather than
diverging silently.**

Route under repair: `http://127.0.0.1:8787/vpa` → `dashboard/src/views/VpaView.vue`
Engine: `research/vpa_engine.py`, codex: `research/vpa_codex.py`, handler:
`tools/api_server.py` (`/api/vpa/analyze`, `/api/vpa/codex`, `/api/vpa/samples`).

---

## 0. Confirmed defects (verified live against the running server, not assumed)

| # | Defect | Evidence |
|---|--------|----------|
| D1 | Timeframe control is a no-op. `Daily`, `15m`, `Weekly` return byte-identical analyses. The selector only relabels; bars are always daily from `/api/trajectory`. | POST `/api/vpa/analyze` with 3 timeframes → identical `probability_pct`, `support_resistance`, `confidence_score`. |
| D2 | Snapshot-to-vision never runs. `analyze_chart_vpa` checks `ohlcv_series` **before** `image_base64`; the UI always sends bars alongside the snapshot, so the image is silently discarded. | POST image+bars → `engine_mode: quantitative_ohlcv_vpa`. Image dropped, no warning. |
| D3 | No vision credentials configured. `GEMINI_API_KEY` / `GOOGLE_API_KEY` absent from `.env`, so even image-only requests fall to canned heuristic text. | POST image-only → `engine_mode: offline_heuristic`. |
| D4 | Probabilities, confidence and R:R are literal constants, not derived. | `confidence_score` always `0.86`; `probability_pct` always `74`/`26`; `risk_reward_ratio` always `"1 : 3.1"` — invariant across symbol, timeframe and data. |
| D5 | Support/resistance is `min()`/`max()` over 30 bars, mislabelled "30-bar fractal". No pivot detection, no clustering, no role reversal, no touch counting. | `vpa_engine.py` `evaluate_ohlcv_series` S/R block. |
| D6 | Volume-at-price bins each bar's **entire** volume into the bin of its close. A bar spanning six bins contributes to one. POC is therefore wrong. | `vpa_engine.py` VAP block, `bin_idx` from `b["close"]` only. |
| D7 | `test_candles.detected` is hardcoded `True` in every code path, including the fallback. Same for several `stopping_or_topping` fields. | grep `"detected": True`. |
| D8 | Canned sample dicts must not be presented as a live engine read. Third-party published chart commentaries are not included. | `SAMPLE_CHARTS` is empty. |

## 1. Non-negotiable principles

1. **No invented precision.** Every number the UI shows must be traceable to a computation
   over real bars, or be absent. A missing number renders as `—`, never as a plausible constant.
2. **Honest capability reporting.** If a timeframe has no data, or vision has no API key, the
   API says so in a structured field and the UI disables the control with the reason. We never
   serve daily bars while the label says 15m.
3. **Every claim carries evidence.** Probability, confidence and direction each ship with the
   signal ledger that produced them, including the bar indices involved and the
   internal rule id. If a worker cannot name the rule, the rule does not ship.
4. **Original thresholds.** Numeric proxies live in `research/vpa_thresholds.py`.
   They are this workstation's ratios. No third-party book text is stored in the repo.

## 2. Data reality (verified)

- `data/1h/` — **588 symbols** (backfilled 2026-08-31 from 59 via `tools/fetch_universe.py --interval 1h`), hourly bars 2023-10 → 2026-08. **Real intraday across effectively the whole universe.**
- `data/1d/`, `data/1d_wide/` — daily per-symbol parquet. Per project convention these are
  *order + fallback*, never one replacing the other. `1d_wide` = 558 symbols.
- **No data below 1h.** `1m`, `5m`, `15m`, `30m` in the current timeframe dropdown are unbacked.

Timeframe support matrix the API must implement and report:

| Timeframe | Source | Status |
|-----------|--------|--------|
| `1h` | `data/1h/{SYM}.parquet` native | available (588 symbols) |
| `2h`, `4h` | resample from 1h | available (588 symbols) |
| `1D` | `data/1d/` then `data/1d_wide/` fallback | available |
| `1W` | resample from daily | available |
| `1m`, `5m`, `15m`, `30m` | — | **unavailable — must be reported, not faked** |

## 3. New modules (worker B owns all Python)

```
research/vpa_bars.py     load_bars(symbol, timeframe, lookback) -> (bars, meta)
research/vpa_levels.py   detect_levels(bars) -> LevelSet
research/vpa_score.py    score_evidence(bars, levels) -> EvidenceLedger -> probabilities
```

`research/vpa_engine.py` becomes the orchestrator that composes these. Do not leave the
scoring inline.

## 4. Response contract (additive — existing fields stay so nothing breaks)

```jsonc
{
  // ...all existing fields retained, but now computed...
  "confidence_score": 0.71,          // derived, never constant
  "primary_scenario":     { "probability_pct": 63, ... },
  "alternative_scenarios": [ { "probability_pct": 37, ... } ],  // must sum to 100 with primary

  "bars_meta": {                      // NEW — proves the timeframe actually took effect
    "timeframe_requested": "15m",
    "timeframe_served":    "1h",
    "downgraded":          true,
    "downgrade_reason":    "no data below 1h for NVDA",
    "bar_count":           420,
    "first_bar":           "2026-05-01T13:30:00",
    "last_bar":            "2026-07-29T19:30:00",
    "source":              "data/1h/NVDA.parquet"
  },

  "levels": [                         // NEW — numeric, drawable
    { "price": 190.01, "low": 189.4, "high": 190.6, "kind": "support",
      "strength": 0.81, "touches": 4, "source": "pivot_cluster",
      "role_reversed": false, "last_touch_bar": 388 }
  ],
  "vap": {                            // NEW — range-distributed, not close-binned
    "poc": 196.2, "value_area_low": 188.0, "value_area_high": 203.5,
    "bins": [ { "low": 185.0, "high": 187.5, "volume": 1.2e8 } ]
  },

  "evidence": [                       // NEW — the ledger behind every number
    { "signal": "stopping_volume", "direction": "bullish", "weight": 0.22,
      "bars": [412, 413], "book_ref": "Ch.6 — Stopping Volume",
      "detail": "Volume 2.4x 20-bar average with narrowing spread and deep lower wicks." }
  ],
  "probability_basis": {              // NEW — how the % was formed
    "bull_score": 1.42, "bear_score": 0.58, "method": "logistic",
    "band": [35, 80], "note": "Capped: VPA is directional evidence, not a calibrated forecast."
  },

  "vision_status": {                  // NEW — D2/D3 honesty
    "available": false,
    "reason": "GEMINI_API_KEY not configured",
    "image_received": true,
    "image_used": false
  },
  "engine_mode": "quantitative_ohlcv_vpa" // | "vision_multimodal" | "vision+quant" | "canonical_codex_reference"
}
```

### New endpoint

`GET /api/vpa/health` →
```jsonc
{
  "vision": { "available": false, "reason": "GEMINI_API_KEY not configured" },
  "timeframes": [ { "value": "1h", "label": "1 Hour", "available": true, "symbols": 59 },
                  { "value": "15m", "label": "15 Minutes", "available": false,
                    "reason": "no data below 1h" } ],
  "data_sources": { "1h": 59, "1d": 558 }
}
```
The frontend builds its timeframe dropdown from this, not from a hardcoded array.

## 5. Scoring rules (worker B, grounded by worker A)

- Build a signed evidence ledger. Each detector emits `(direction, weight, bars, book_ref, detail)`.
- Aggregate to `bull_score` / `bear_score`; map to `probability_pct` with a bounded logistic.
- **Clamp to [35, 80].** VPA reads direction, it does not produce calibrated forecasts;
  a 92% claim from candle geometry is not defensible.
- `confidence_score` = f(bar count, signal agreement, data recency, downgrade penalty).
  A downgraded timeframe must lower confidence.
- `risk_reward_ratio` computed from the actual entry / stop / target numbers. If any is
  unavailable, emit `null`, not a string.
- Alternative-scenario probabilities must complete to 100 with the primary.
- **Regression guard:** no code path may emit `0.86`, `74`, `26`, or `"1 : 3.1"` as a literal.

## 6. Levels rules (worker B, grounded by worker A)

- Fractal pivots: `n`-bar left/right confirmation (default 3, configurable).
- Cluster pivots into zones with ATR-scaled tolerance; count touches; decay by recency.
- VAP: distribute each bar's volume **across its high–low range**, not into the close bin (fixes D6).
  Derive POC and 70% value area.
- Role reversal: a ceiling closed through on rising volume becomes a floor — set
  `role_reversed: true`.
- Breakout validation: a close outside the zone **plus** rising volume.
  Low-volume breakout ⇒ emit a `fakeout_risk` evidence item, not a bullish one.

## 7. Frontend (worker C owns all of `dashboard/src/`)

- Timeframe dropdown built from `/api/vpa/health`; unavailable options disabled with the reason
  shown, never silently substituted.
- `watch` on timeframe and asset class → re-fetch. Currently only `trajWindow` is watched.
- Draw `levels[]` and `vap` on the canvas chart: support/resistance bands, POC line, value area
  shading, role-reversal marker.
- Evidence panel rendering `evidence[]` with book citations — this is the antidote to
  "the numbers look made up".
- `probability_basis` shown alongside the percentage, including the "not a calibrated
  forecast" caveat.
- Snapshot button reflects `vision_status`: disabled with the reason when unavailable.
  It must never appear to work and silently do nothing (D2).
- Do not present a third-party published chart commentary as engine output (D8).
- Typography and layout pass; keep the existing design tokens and chart conventions.

## 8. Verification (worker D)

Every defect D1–D8 needs a test that fails on the current code:

- D1: two timeframes → different `bars_meta.bar_count` and different analysis.
- D2: image + bars → `vision_status.image_used` reflects reality; precedence respected.
- D4: synthetic bull / bear / neutral series → three different probabilities; assert none
  equal the old constants.
- D5/D6: synthetic series with planted pivots and a known volume node → detected within tolerance.
- D7: a series with no test candle → `test_candles.detected == false`.
- Contract test: every field in §4 present with the right type.
- Full-suite regression: `pytest tests/` and the dashboard vitest suite must stay green.

## Deviations

_Append here with worker name and rationale._

### Status — 2026-08-30

All three workers were killed mid-flight by a spend limit. Completion state, verified
directly rather than taken on trust:

- **Backend (§3–§6):** landed. `vpa_bars.py`, `vpa_levels.py`, `vpa_score.py`,
  `vpa_thresholds.py` created; `vpa_engine.py` refactored to orchestrate them;
  `/api/vpa/health` live. 32 engine tests pass.
- **Frontend (§7):** landed. `vue-tsc` clean, 41 vitest cases pass, page verified in-browser.
  Worker C died at its own lint step; typecheck and tests were run afterwards by the
  orchestrator instead.
- **Thresholds:** numeric proxies live in `research/vpa_thresholds.py`. No third-party book is vendored.
- **Verification (§8):** D1–D8 all confirmed fixed against the live server.
  Full suite: 1892 passed, 5 failed — all five pre-existing and unrelated to VPA
  (congressional-trade data drift, chain adapter). Two further collection errors are
  pre-existing (`cvxpy` not installed).

Outstanding: probability ceiling saturation (9 of 30 real runs land exactly on the 80 clamp,
none on the floor) suggests `logistic_k` wants recalibration against a bear sample.

### Status — 2026-08-31 (production hardening)

Follow-up pass closing the gaps left by the first round:

- **Per-symbol capability.** `/api/vpa/health` now takes `?symbol=`, so a ticker
  without hourly bars no longer has 1h offered in the dropdown. Previously
  availability was global and the downgrade only surfaced after the request.
- **Vision reframed as optional.** For any symbol we hold bars for, the
  exact-OHLCV read is strictly more precise than inferring candles from pixels,
  so a missing model is reduced reach, not a broken feature. `vision_status`
  now carries `required: false` and `primary_path`. Vertex ADC is accepted
  alongside an API key.
- **Probability saturation fixed.** The hard clamp collapsed every strong read
  onto exactly 80 (9 of 30 runs), and the 35 floor was unreachable because
  `max(p, 1-p) >= 50`. Replaced with a squash onto `[50, ceiling]`.
- **Trend and congestion detectors added** — dynamic trend lines from joined pivots,
  plus triple tops and bottoms, triangles, and pennants.
- **Intraday coverage closed** — `data/1h` backfilled 59 -> 588 of 589 symbols.
  IBIT alone returns empty from the provider and correctly downgrades to daily
  with a stated reason, which keeps that path genuinely exercised.
- **Walk-forward validation added** (`research/vpa_backtest.py`,
  `docs/VPA_VALIDATION.md`). Result: no measurable edge over a skill-free
  caller once drift is accounted for; surfaced in the UI beside the percentage.

Suites: 43 VPA engine cases, 42 VPA view cases, 2105 frontend cases all green;
backend 1903 passed / 5 failed, those five pre-existing and unrelated to VPA
(congressional-trade data drift, chain adapter), unchanged from the baseline.
