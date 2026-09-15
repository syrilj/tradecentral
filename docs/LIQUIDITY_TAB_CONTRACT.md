# Liquidity tab — stop pools, sweeps, bias, proper stops

Goal: a primary dashboard tab that, for one stock, estimates **where stop-losses
are likely resting** around the live price (from a fixed-range volume profile
plus swing structure), flags **when a liquidity sweep looks likely**, reads
**long / short bias** off completed sweeps, and suggests **stops placed beyond
the pools** so an ordinary sweep does not take the position out.

Owners (disjoint files — do not edit another owner's files):

| Unit | Owner | Files |
|---|---|---|
| Engine + route | backend agent | `research/liquidity_map.py`, `tests/test_liquidity_map.py`, the `/api/liquidity/*` branch in `tools/api_server.py` |
| Tab | frontend agent | `dashboard/src/views/LiquidityView.vue`, `dashboard/src/liquidityContracts.ts`, `dashboard/src/__tests__/liquidity-view.test.ts`, the liquidity entries in `api.ts`, `router.ts`, `App.vue`, `components/AppIcon.vue` |
| Calibration study | study agent (after engine lands) | `research/liquidity_study.py`, `tests/test_liquidity_study.py`, `runs/liquidity_study/**` |

## 0. Honesty rules (non-negotiable)

1. **No order-book, NBBO or tick data exists** in this repo — underlying is OHLCV
   candles only. Stop pools are *inferred from price structure*. Every pool
   carries `basis: "inferred_from_structure"`; UI copy never says "orders" or
   "resting liquidity observed".
2. The volume profile spreads each bar's volume across its high–low range
   (`profile.method: "bar_range_distribution"`). Say so in the UI footnote.
3. **No literal probabilities.** Any rate shown comes from counted history with
   its sample size `n`. If `n < thresholds.min_samples`, the value is `null`
   with a `reason`. Prior finding (`research/reversal_study.py`): single-stock
   chart triggers were ≈ coin flip out of sample. Expect the same here and
   report whatever the counts say.
4. Missing data → `null` + `reason`. Never substitute a plausible default.
5. No lookahead: a pivot only becomes a pool once its right-side confirmation
   bars have closed; sweeps are evaluated only against pools known at that bar.

## 1. Endpoint

`GET /api/liquidity/analyze`

| Param | Values | Default |
|---|---|---|
| `symbol` | ticker | required |
| `timeframe` | `1m` `5m` `15m` (LSE candles via `_lse_intraday_bars`), `1h` (disk via `research.vpa_bars.load_bars`) | `5m` |
| `range` | `session` (most recent RTH session 09:30–16:00 America/New_York), `2d` `5d` `10d` (last N RTH sessions) | `session` |
| `anchor_start`, `anchor_end` | ISO timestamps; when both present they override `range` (true fixed-range profile) | — |

- History for pools/sweeps/base rates = all bars fetched (1m: 3 days, 5m/15m: 10 days, 1h: 400 bars). Profile uses only the range.
- 30 s in-process cache keyed by all params. Provider failure / empty bars → `{available:false, reason}` (HTTP 200).
- Engine entry point is pure: `analyze_liquidity(bars, *, symbol, timeframe, range_start, range_end, now=None) -> dict`. The route does I/O and slicing only.

`GET /api/liquidity/thresholds` → `{ thresholds }` (the tunables below).

## 2. Response shape

```jsonc
{
  "available": true,
  "reason": null,
  "symbol": "SPY",
  "timeframe": "5m",
  "generated_at": "2026-09-13T20:30:00Z",
  "basis": "inferred_from_structure",
  "price": { "last": 561.2, "ts": "…", "source": "lse_candles|yahoo|disk_1h", "stale_seconds": 42 },
  "atr": { "value": 0.84, "period": 14 },
  "profile": {
    "range_start": "…", "range_end": "…", "bars_used": 78,
    "method": "bar_range_distribution", "bin_size": 0.1,
    "poc": 560.9, "vah": 561.6, "val": 559.8,
    "bins": [{ "price_lo": 0, "price_hi": 0, "price_mid": 0, "volume": 0, "share": 0, "node": "hvn|lvn|normal" }],
    "hvns": [560.9], "lvns": [562.3]
  },
  "pools": [{
    "id": "bs-1",
    "side": "buy_stops",            // above price: short stops + breakout buy-stops
                                    // "sell_stops" below price: long stops + breakdown sells
    "level": 562.4, "zone_lo": 562.4, "zone_hi": 562.7,
    "sources": ["equal_highs", "prior_session_high"],
    "touches": 3, "first_seen": "…", "last_tested": "…", "untested_bars": 21,
    "distance": { "abs": 1.2, "atr": 1.43, "pct": 0.0021 },
    "thin_liquidity_between": true,
    "score": 0.71,
    "score_components": { "confluence": 0, "touches": 0, "freshness": 0, "proximity": 0, "thin_path": 0 },
    "status": "resting|swept_reclaimed|swept_accepted"
  }],
  "sweeps": [{
    "ts": "…", "pool_id": "ss-2", "side": "sell_stops", "level": 559.1, "extreme": 558.8,
    "pierce_atr": 0.36, "bars_to_reclaim": 2, "volume_ratio": 1.8,
    "outcome": "reclaimed|accepted|pending",
    "forward": { "bars": 12, "ret_atr": 1.1 }       // null when not enough bars after
  }],
  "sweep_watch": [{
    "pool_id": "bs-1", "side": "buy_stops", "distance_atr": 1.43,
    "drivers": ["thin path (LVN at 562.3)", "3 equal highs", "momentum toward pool"],
    "base_rate": { "p_touch": 0.44, "within_bars": 12, "n": 131 }   // null + reason if n < min_samples
  }],
  "bias": {
    "direction": "long|short|neutral",
    "confidence_basis": "counted_history|structure_only",
    "evidence": [{ "signal": "…", "direction": "long|short|neutral", "weight": 0.3, "detail": "…" }],
    "summary": "Sell-stops under 559.1 swept and reclaimed in 2 bars; price back inside value."
  },
  "stops": {
    "long":  { "naive": 559.05, "suggested": 558.55, "beyond_pool_id": "ss-2", "risk_atr": 3.0, "rationale": "…", "method": "beyond_pool|atr_fallback" },
    "short": { "…": "same shape" }
  },
  "calibration": {
    "source": "symbol_history|study_file|null",
    "sweep_reclaim_follow_through": { "rate": 0.52, "n": 64, "horizon_bars": 12 },   // null + reason if n < min_samples
    "notes": "…"
  },
  "bars": [{ "ts": "…", "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0 }],
  "thresholds": { }
}
```

## 3. Algorithm

All tunables live in one `LIQUIDITY_THRESHOLDS` dict and are echoed in the response.

1. **ATR(14)** on the served timeframe (`vpa_levels.average_true_range`).
2. **Fixed-range profile** over the range slice: reuse `amt_engine.build_profile`
   (POC, VAH/VAL). HVN/LVN = bins whose volume is a local max/min over ±2 bins and
   above/below 1.3× / 0.5× the median bin.
3. **Pool candidates** (from history, confirmed only):
   - `swing_high` / `swing_low` — `vpa_levels.find_pivots`.
   - `equal_highs` / `equal_lows` — ≥2 pivots within `eq_tol_atr` (0.15). Level = cluster extreme (stops sit beyond the highest high / lowest low).
   - `prior_session_high/low`, `opening_range_high/low` (first 30 min of the latest RTH session; skipped for 1h).
   - `value_area_high/low` from step 2.
   - `round_number` — whole dollars (price ≥ $20) or half dollars (< $20) within 3 ATR.
   - Merge candidates within `merge_atr` (0.25); union sources; keep the extreme level on the stop side.
4. **Side** by level vs last price. **Zone**: buy_stops `[level, level + buffer_atr·ATR]`, sell_stops mirror (`buffer_atr` 0.35).
5. **Score** = weighted sum, each component in [0,1]: confluence (sources, cap 4), touches (cap 4), freshness (untested), proximity `exp(-distance_atr/2)`, thin_path (an LVN lies between price and level). Weights in thresholds; score in [0,1]. Drop pools beyond `max_pool_atr` (6).
6. **Sweep detection** per bar vs pools known at that bar: wick beyond level by ≥ `min_pierce_atr` (0.05) then a close back on the original side within `reclaim_bars` (3) → `reclaimed`; two consecutive closes beyond → `accepted`; otherwise `pending`. Record `volume_ratio` vs the 20-bar median and `forward` return in ATR over `forward_bars` (12), signed in the reclaim direction.
7. **Base rates (symbol history)**: for every historical bar within `watch_atr` (1.5) of a pool, did price touch the pool within `forward_bars`? Rate + n. For reclaimed sweeps, share with `forward.ret_atr > 0`. `min_samples` 20 → else null + reason.
8. **Sweep watch** = resting pools within `watch_atr`, sorted by score, with plain-language drivers.
9. **Bias**: most recent reclaimed sweep within `bias_recency_bars` (12) → direction of the reclaim (sell-stop sweep reclaimed → long; buy-stop sweep reclaimed → short). Accepted sweep → continuation direction. Price vs POC and nearest high-score pool on each side add weighted evidence. `neutral` when evidence nets below `bias_min_edge`. `confidence_basis = counted_history` only when calibration n ≥ min_samples.
10. **Stops**: long `suggested` = nearest sell_stops pool below price → `zone_lo − stop_buffer_atr·ATR` (0.10); `naive` = pool level − $0.01 (the obvious one-tick-under placement the sweep targets). No pool within `max_stop_atr` (3) → `last − 1.5·ATR`, `method: "atr_fallback"`. Short mirrors. `risk_atr = |last − suggested| / ATR`.

## 4. Tab

- Route `/liquidity`, `LiquidityView.vue`; primaryNav entry right after VPA:
  `{ name: 'liquidity', title: 'Liquidity', hint: 'Stop pools · sweeps · stops', icon: 'liquidity', tab: true }`; add a `liquidity` glyph to `AppIcon.vue`.
- Controls: symbol, timeframe segmented (1m/5m/15m/1h), range segmented (Session/2D/5D/10D), GO LIVE toggle (poll every 30 s while visible; follow existing GO LIVE pattern).
- Top: **Bias** card — direction, summary, evidence rows, `confidence_basis` badge.
- Main chart: candles + fixed-range profile histogram on the right edge; POC/VAH/VAL lines; pool zones as bands (buy_stops above, sell_stops below, opacity ∝ score); sweep markers at the wick extreme (reclaimed vs accepted distinguishable); dashed suggested-stop lines for long and short.
- Side column: **Sweep watch** list (distance ATR, drivers, base rate with n or "not enough history"), **Stops** card (naive vs suggested, risk in ATR, rationale), **Pools** table (level, side, source chips, distance ATR, score, status).
- Footnote: "Stop pools are inferred from price structure and bar volume — no order-book data." plus calibration n.
- Reuse `charts.ts`, `useChartSize` (keep the chart host mounted — no `v-if` swap on the host element; see useChartSize stale-host bug), `Panel`, `Readout`, `format.ts`, `useResource`. Follow `AmtView.vue` patterns.
- Must pass `design-conformance.test.ts`: tokens only, no glows/ring shadows/radial gradients, wash tokens never inside gradients, font-size ≥ 10px.
