# Options Route Note

Status: living operator/research memo  
Scope: how names and prints move through TradeCentral options surfaces  
Audience: operators, reviewers, and anyone about to add another options page  
Does not: implement Dark Pool / equity prints, invent missing LSE fields, or authorize broker orders

This note is the routing contract for options. The broader market-intelligence platform spec is already implemented on these surfaces. Do not rebuild Desk, Flow, Options, Setups, or the daily-plays pipeline from that spec. Extend this path.

The operator question this system answers:

> Where should expensive options work be spent, what does the tape actually show, and what is still unauthorized?

It does **not** answer “is this print bullish?” unless the provider supplied a signed aggressor. LSE currently does not.

---

## 1. Product routes (Vue)

`dashboard/src/router.ts` is the source of truth. Options work lives on four operator routes plus two legacy redirects.

| Path | Route name | Workspace | Operator question |
|---|---|---|---|
| `/options` | `options` | Options Drift | What is the live chain, GEX, and tape for **one** underlier? |
| `/flow` | `flow` | Market Flow | Where is **market-wide** options tape concentrating? |
| `/suggest` | `suggest` | Setups | What call/put + GEX sell does Flow suggest, and where is the exit? |
| `/calculator` | `calculator` | Calculator | Spot / strike / DTE / vol P/L. Setups prefill the exact contract. |
| `/insiders` | `insiders` | Insiders | What did officers file (Form 4) and what does Fintel show? |
| `/flow-state` | `flowstate` | redirect | Legacy → `/flow?tab=states` |
| `/anomalies` | `anomalies` | redirect | Legacy → `/sentiment?tab=outliers` (not an options surface) |

Primary rail (`dashboard/src/App.vue`): Desk → Market → **Options** → **Flow** → **Setups**. Calculator is a specialist tool off Options, not a competing workspace.

Query contracts already in use:

- `/options?symbol=SPY` — underlier intelligence
- `/flow?symbol=SPY` or `/flow?setup=SPY` — tape filtered to a name
- `/suggest?symbol=SPY` — setups board focused on a name
- `/flow?tab=states` — flow-state artifact tab

Cross-links that must stay consistent (do not invent a fifth options home):

- Desk live-LSE coverage → `/flow`
- Market / Momentum / Changepoints / Search → `/options?symbol=`
- Options header → `/flow`, `/calculator`
- Flow suggestion drawer → `/options?symbol=`, `/suggest?symbol=`
- Setups → `/options`, `/flow`

Search fallback after auth is `/flow` (`safeRedirect`). That is intentional: market-wide tape is the default options landing after login, not a marketing page.

---

## 2. API routes (Python)

`tools/api_server.py` is the implementation source of truth. Options/flow handlers:

| Method | Path | Role | Must not |
|---|---|---|---|
| `GET` | `/api/options?symbol=&mode=live\|history&range=` | Single-name chain + intelligence | Invent NBBO/OI when LSE omitted them |
| `GET` | `/api/options/board[?force=1]` | Cross-name options board | Treat board rank as promotion |
| `GET\|POST` | `/api/options/backfill_oi?symbol=` | Persist OI snapshot; invalidate that symbol's `/api/options` cache | Relabel last-trade time as quote time |
| `GET` | `/api/options/opportunities` | Same payload as suggest | Authorize `ENTER` |
| `GET` | `/api/options/suggest[?symbol=][&force=1]` | Flow + GEX setup suggestions (`suggestion_contract: flow-rule-v1`) | Transfer unsigned tape into direction |
| `GET` | `/api/options-calculator?strategy=&spot=&strike=&dte=&vol=&premium=` | Deterministic P/L surface | Fetch live quotes as a side effect |
| `GET` | `/api/unusual-flow[?limit=&min_premium=]` | Market-wide unusual tape | Claim vendor-certified sweeps unless `trade_class_source=vendor` |
| `GET` | `/api/health` | Advertises `flow_feed_contract: market-wide-v1` | Change that string without a contract bump |

Related, **not** options routing: `/api/flow-state` (daily-bar proxy artifact), `/api/fintel/*` (Fintel unusual flow; key stays server-side). Fintel is attention-only and never an LSE order path.

Health contract strings that other tests lock:

- `flow_feed_contract = "market-wide-v1"`
- `suggestion_contract = "flow-rule-v1"`

---

## 3. Data router (daily plays)

This is the actual **flow router**. Sector money-flow chooses *where to look*. Live LSE prints can *reprioritize* that list. Neither step creates a direction, a calibrated probability, or an option-chain request.

```text
LSE daily bars (sector ETFs + SPY)
        │  missing books may be Yahoo-filled
        ▼
TradingAlgoWork sector-money-flow heatmap
        │  labeled lse_live_daily | yfinance | lse_live_daily+yfinance_missing
        ▼
select_sector_targets()                     # discovery.json
        │  promote bag first, then research names, cap 1–50 (default 25)
        ▼
load_live_flow_activity(target_symbols)     # flow_activity.json
        │  per-symbol LSE prints, unsigned, premium-ranked
        │  routing_order = active names first, then remainder
        ▼
Promoted model scan on routing_order        # candidates.json
        │  flow/Kronos are evidence only
        ▼
fuse_candidate()                            # rank_score; probability unchanged
        ▼
Live chain fetch ONLY if calibrated + promoted + regular session
        ▼
Options policy + risk gates                 # plays.json ENTER | else NO_PLAY
```

### 3.1 Discovery (`daily_plays/adapters/sector_flow.py`)

`select_sector_targets()`:

1. Alternate heatmap `money_in` / `money_out` so one hot sleeve cannot consume the budget.
2. Round-robin focus names across those books.
3. Always inspect the frozen promotion bag (`EQUITY_WINNER_BAG`) first.
4. Keep only names in the configured research universe. Sector ETFs drive the heatmap; they do not steal model slots.
5. Cap at `DAILY_PLAYS_DISCOVERY_LIMIT` (default 25, hard max 50).

Stale rule: if `asof_bar` is more than 4 calendar days behind the run date, discovery returns `_evidence_warning: sector_flow_report_stale` and does not invent targets.

Yahoo fill is **discovery-only**. Label is `lse_live_daily+yfinance_missing`. That proxy can route a scan. It cannot validate execution.

### 3.2 Tape activity (`daily_plays/adapters/flow.py`)

Two loaders, two jobs. Do not merge them.

| Loader | Endpoint / caller | Job |
|---|---|---|
| `load_live_flow_activity(symbols=...)` | daily-plays pipeline | Fan-out LSE prints on **routed** names. Writes `routing_order`. |
| `load_market_flow_activity(...)` | `/api/unusual-flow`, Flow view | One market-wide `/x_options_flow` page. Does **not** inherit Deep-scan coverage. |

`routing_order` = symbols with observed premium/alerts, premium-desc, then the original requested list. Pipeline overwrites `discovery["target_symbols"]` with that order. This only changes model-scan priority.

Every activity row is stamped:

- `decision_authorized = false`
- `directional_calibration_transferred = false`

Unsigned LSE prints stay `direction = "neutral"` and `sentiment = "neutral"`. Call/put identity is **not** a directional trade. Signed premium is used only when the provider actually supplied an aggressor; coverage is reported separately (`signed_print_count`, `signed_premium_coverage`).

**Bullish / bearish activity signs** are a separate field: `activity_lean` from `describe_activity_lean()`. Call-heavy premium can read `BULLISH` with source `call_put_premium`. That is a desk sign, not an aggressor and not `ENTER`. `decision_authorized` remains `false` on every tape/activity row. The Options header shows both: `ACTIVITY SIGN` and `AUTHORIZED = NO`.

Circuit breaker: three consecutive LSE timeouts open a process-lifetime circuit (`flow_lse_circuit_open`). Remaining fan-out is cancelled. `EDGE_SKIP_LSE_FLOW` forces the same fail-closed path.

Symbol hygiene: provider pages that return an unfiltered 500-row dump are discarded (`flow_symbol_mismatch`). An OCC/contract id is never guessed into an underlying.

### 3.3 Fusion (`daily_plays/fusion.py`)

Kronos and flow **cannot** modify a calibrated probability.

`rank_score = model_component + 0.01 * research_support - 0.02 * n_contradictions`

That ±1–2 bp tie-break is the entire influence of flow on ranking. Contradictions downgrade evidence grade and keep state at `WATCH`. They never flip side.

`ENTER` still requires, after fusion:

- `confidence_kind = calibrated_probability`
- `probability_target = underlying_directional_return`
- horizon in `{5, 10, 20}`
- `calibrated_probability >= entry_threshold` (frozen operating point, typically ≥ 0.65)
- SHA-256 promotion artifact + `promotion_authorized = true`
- regular session in live mode
- live NBBO/OI + listed OCC identity
- liquidity / spread / DTE / risk policy

v72 dual-sleeve ordinal confidence is diagnostic only. The sealed directional challenger is research-board only. Neither can authorize a chain request.

---

## 4. Tape classification (documented, not arbitrary)

Implemented in `daily_plays/options_intelligence.py`. These are **descriptive labels on the observed tape**, not alpha forecasts. They have not passed a walk-forward IC gate. Do not present them as a proprietary signal with a live edge.

### 4.1 Unusual

A print is `is_unusual` when **both** are known and:

- DTE ≤ 35
- OTM ≥ 10%

If DTE or OTM is missing, the flag is false. Missing is not zero.

### 4.2 Sweep

Two independent sources. Never collapse them.

| Source | `trade_class_source` | Rule |
|---|---|---|
| Vendor | `vendor` | Provider set `trade_class = sweep`. Preserved. |
| Burst heuristic | `burst_heuristic` | Same contract, ≥2 prints, consecutive gap ≤ 3s, combined premium ≥ $100k |

A looser **repeat cluster** (same contract, ≥3 prints, span ≤ 15 minutes, cluster premium ≥ max($250k, 3× tape-median premium)) sets `anomaly_flags += repeat_cluster` but does not by itself rewrite `trade_class` unless the burst rule also fires.

UI must distinguish vendor sweeps from burst heuristics. The heuristic is app-side, not exchange-certified.

### 4.3 Other IF labels

| Flag | Rule |
|---|---|
| `is_block` | `trade_class == block` |
| `is_top_position` | contracts > open interest (OI must be present) |
| `is_momentum` | contracts / OI ≥ 0.50 if OI present; else volume ≥ 75th percentile when tape length ≥ 4 |
| `is_moonshot` | price ≤ $2.50 **and** OTM ≥ 20% |

### 4.4 Anomaly score

Robust z versus the **current tape batch** (not a historical baseline):

- `premium_score`, `volume_score` via median / MAD
- flag if score ≥ 3.5
- `anomaly_score = max(0, premium_score, volume_score, 3.5 if clustered/sweep else 0)`

This is a batch-relative outlier, not “8.4× normal volume” versus a 20-day ADV. If the UI needs “why unusual,” show the **inputs** (DTE, OTM, premium, vol/OI, burst count), not a synthetic 0–100 “unusual activity score” that pretends to be a model.

### 4.5 Heat

`print_heat_score` is a published monotone transform in `[0, 100]`:

```text
raw = 0.30·log1p(size)
    + 0.30·log1p(premium)
    + 0.15·log1p(volume)
    + 0.15·log1p(size / max(OI, 1))   # 0 if OI missing
    + 0.10 · (1 / (1 + DTE/35)) · log1p(100)

heat = 100 · (1 − exp(−raw / 6))
```

Missing OI drops the OI term; it does not impute OI. Missing DTE uses 30, documented as a display default, not a forecast input.

### 4.6 Symbol aggregates

`build_options_top_tickers()` ranks underliers on unusual OTM / volume / premium, sweep premium, momentum premium, call premium, put premium. Direction share uses signed premium when present; otherwise it reports call/put premium with `share_basis = call_put_premium`. That basis string must stay visible. Call premium ≠ bullish.

---

## 5. LSE field coverage (do not fake)

The live LSE chain is **reference/activity**, not an executable quote source.

Usually present: contract identity, last trade, volume, IV, Greeks.

Usually **absent**: bid/ask NBBO, open interest, quote timestamp, multiplier/adjustment unless explicitly supplied.

Rules:

1. Leave missing fields unavailable.
2. Label last-trade time as last-trade time. Never as quote time.
3. A live `ENTER` requires a connected provider that actually supplies current NBBO/OI.
4. Dark Pool and equity prints are out of scope. Do not add a tab, badge, or empty state that implies they exist.

---

## 6. Quantitative constraints (why this router is conservative)

Grounded in the research bar this repo already uses for gates (`docs/GATE_*.md`, walk-forward / purged CV / cost haircuts).

| Constraint | How the options router obeys it |
|---|---|
| **Look-ahead** | Discovery uses bars dated `asof_bar`. Stale >4d fails closed. Fusion cannot use future chain snapshots. Last-trade ts is not a quote ts. |
| **Unsigned tape** | No aggressor → no signed premium → no bull/bear from C/P. This is the most common way options “alpha” is fake. |
| **Yahoo / delayed** | `delayed_or_proxy = true`. Can route research attention. Cannot pass execution validation. |
| **Survivorship** | Promotion bag is a frozen winner set. Discovery is not allowed to treat that bag as a live tradable universe. Research board is sealed and excluded from the decision ledger. |
| **Multiple testing** | Heatmap + tape + GEX + v72 + directional challenger are **separate** hypotheses. Only the promoted, hash-locked calibration can authorize work. Informal “this tape looks hot” is not a test that passed. |
| **Costs** | Shadow report requires explicit `spread_bps` / `slippage_bps`. Readiness: ≥120 sessions, ≥200 completed shadow option trades, ≥2 regimes, zero timestamp violations. Promotion still does not enable a broker. |
| **Capacity** | Flow fan-out is bounded (25 names, 8 workers, 6s/name, circuit after 3 timeouts). This is an attention budget, not a capacity model. |
| **Regime** | Sector rotation fields are descriptive (`rotation.kind`, `is_definitive`). They do not switch models. GEX regime is a separate gated hypothesis (`docs/GATE_GEX.md`), not a live overlay on unsigned prints. |
| **Overfit** | Do not add free parameters to unusual/sweep heuristics without a pre-registered gate. Current constants (35 DTE, 10% OTM, $100k burst, 3s gap) are **labels**, not optimized alphas. |

Minimum bar if anyone later claims these labels predict returns:

- walk-forward train/test (not one backtest window)
- IC vs next-horizon underlying or option mark, **after** spread + slippage
- t-stat / information ratio, trade count ≥ 30 per slice
- regime split (bull / bear / chop)
- no look-ahead in print→return alignment (print time must precede the return window)
- haircut: in-sample Sharpe 2 → expect ~1 live; Sharpe >3 is treated as overfit until proven otherwise

That study does not exist in-repo for the burst/unusual labels. Until it does, the UI language is “flagged,” not “edge.”

---

## 7. Persistence and provenance

Each `python3 -m edge.daily_plays today` run writes, under `runs/daily_plays/<run_id>/`:

| Artifact | Contents |
|---|---|
| `discovery.json` | Sector report, `target_symbols`, market map |
| `flow_activity.json` | Unsigned tape coverage + `routing_order` |
| `candidates.json` | Fused shortlist |
| `option_snapshots.json` | Chains fetched **after** authorization |
| `plays.json` | `ENTER` tickets only |
| `decisions.json` | Full audit |
| `research_board.json` | Sealed holdout; **excluded** from the decision ledger |
| `manifest.json` | Run identity |

Provenance strings already in payloads:

- flow adapter: `source = trading_work_flow`, `provenance.raw_source = TradingWork/src/uoa_scanner.py`
- market tape: `data_source = lse_market_flow`
- per-print: `trade_class_source ∈ {vendor, burst_heuristic}`
- sector: `market_map.source ∈ {lse_live_daily, yfinance, lse_live_daily+yfinance_missing}`

Credentials (`LSE_API_KEY`, `FINTEL_API_KEY`) stay in the server environment. They are never sent to Vue.

---

## 8. Operator path (behavior, not screenshots)

1. Open Desk. Read live-LSE coverage (`LSE PASS COMPLETE` / partial / unavailable). Coverage is not a signal.
2. Open Flow. Market-wide tape updates from `/api/unusual-flow`. Filter; do not refresh-spam Deep scan.
3. Click a name → Options (`/options?symbol=`). Chain + GEX + that name’s prints.
4. Open a print. Read flags and **why** (DTE, OTM, premium, burst, vendor vs heuristic). `NO SIDE` means LSE did not report an aggressor.
5. If Flow + GEX produced a setup, open Setups. Suggestion contract is `flow-rule-v1`, not a calibrated 5/10/20-day probability.
6. Calculator is a what-if. It does not pull a live ticket.
7. Watchlists and Desk symbols deep-link back to Options. They do not create a second routing model.

---

## 9. What is still incomplete (honest)

Reuse what exists. Do not paper over these with mock data.

- LSE still does not provide aggressor, NBBO, or reliable OI on the live chain. Those cells stay unavailable.
- Unusual / sweep / heat are tape labels without a walk-forward IC study.
- Market-wide Flow is one provider page (`limit` ≤ 2000), not a full OPRA firehose and not a websocket.
- `/api/flow-state` is a daily-bar **proxy** artifact, not live options flow. Keep that name honest.
- Dark Pool is intentionally absent.
- No broker order routing. `daily_plays` is decision-support and shadow only.

If a future change needs a new options URL, a new filter model, or a new “unusual score,” it must attach here first: which existing loader it extends, which contract string it bumps, and which gate it is **not** allowed to skip.
