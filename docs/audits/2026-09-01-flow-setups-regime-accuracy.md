# Flow / Setups / Regime — accuracy and usability pass

**Date:** 2026-09-01 · **Branch:** `vpa/production-hardening`
**Verification:** 1944 Python tests + 2110 dashboard tests pass; typecheck clean.

Goal: make the Flow, Setups and Regime surfaces trustworthy for live use — fix
inaccurate data, visual defects, and anything else blocking real trading use.

---

## 1. Fabricated data presented as measured (P0)

The highest-severity class found. Each of these rendered indistinguishably from
a real reading.

| Site | Fabrication | Fix |
|---|---|---|
| `render_dashboard.fetch_sector_flow_signals` | On any scan exception returned a **literal rotation** — money-in `XLC/XLE/QQQ/XLF/SMH`, money-out `IGV/XLV/SOXX/XLY`, watch `AAPL/MSFT/AMD`. The live panel that day was `XLE/XLV/XLP/XLU/XLC` — materially different. | Fails closed: empty lists, `available: false`, reason attached. |
| `render_dashboard` vol complex | `{"VIX": 20.66, "term_slope": 1.0058, "tail_risk": 139.55, "date": "Live"}` — an invented vol regime stamped **"Live"**. | Absent reads absent; carries the observed bar date. |
| `RegimeView.vue` ribbon | `:iv-rank="48.2"` hardcoded for every symbol/day; `:next-expiry-dte="2"` (contradicted its own "0D (09-01)" date); fallbacks `0.78` put/call and `'May 17'` expiry. | Derived or `null`. DTE computed from the observed expiry. |
| `RegimeView.vue` net flow | `signed_net_premium ?? 312.6` — an unmeasured session read as a heavy bullish tape. | `null`. |
| `/api/government` | Served **invented securities trades attributed to real, named members of Congress** (Ro Khanna, Tommy Tuberville) with filing dates, dollar brackets and `disclosures-clerk.house.gov` URLs, stamped `available: true`, `source: regulatory_disclosures_…`, asof today. The generator had been deleted; its **output cache survived** and the read path re-labelled it as authentic. | Cache quarantined; provenance (`fetched_utc` + `source_feed`) now mandatory before any entry is served. |

Three test files *required* the congressional fabrication to pass, which is what
kept it alive. Rewritten to pin the honest contract in both directions.

## 2. Stale and ragged market data (P0) — root cause of "setups don't work"

`fetch_universe.py` refreshed only `config/universe_wide.json` (175 names), but
the API serves every parquet on disk. **42 symbols never refreshed** — including
`QQQ, IWM, DIA, XLE, XLF, XLU, XLP, SMH, SOXX, XBI, TLT, HYG, LQD, GLD, SLV`.

Result: `data/1d` held 142 names at `2026-08-05` and 69 at `2026-08-21` — sector
rotation ranked ETF closes up to **16 days apart** and called it "rotation now".
The directional adapter rejected everything as `stale_candle`, so Setups showed
rows with no side and no probability.

- `fetch_universe.py` now unions every on-disk symbol (`--config-only` opts out).
- `fetch_vol_complex.py` had `end_date` **hardcoded to `2026-07-30`** — every run
  re-truncated the vol complex to July. Now defaults to today.
- New `/api/health.market_data`: per-store newest bar, stale symbols, session
  lag, and a `ragged` flag. Footer-metadata only — 775 files in 0.34s.

**Effect:** directional signals **0 → 25**; Setups renders **41 setups (30 call /
11 put)** with real calibrated probabilities.

## 3. Visual / correctness defects

- **Flow ticker card** printed the *market-wide* `PUT FLOW 70%` headline above
  *per-ticker* premiums and a per-ticker bar reading **97%** — two populations
  under one ticker heading. Now uses the ticker's own split (verified: 61% with
  a 39/61 bar). The orphaned market-wide computed was removed.
- **Regime HV 20D / HV 30D** were never wired and read `—` forever. `price_series`
  only carries the ~6 sessions the sparkline draws, so realised vol is now derived
  server-side from the full daily history. SPY HV20 **7.48%** cross-checks against
  the independent vol-complex figure of 7.33%.
- **VIX** was fetched from Yahoo as the literal `VIX`, which is not a ticker
  (`^VIX` is) — the macro strip never had a VIX print and burned a failed network
  round trip per load. Added an index-alias table. Header went `04 AUG 16.50
  STALE` → `01 SEP 16.67`.

## 4. Test-suite repairs

- `test_m3_adversarial_challenge` pinned a literal `ASOF` against the live
  `data/1d` store, so every routine refresh turned it red. Now derives the asof
  from the data.
- `test_api_server_security` pinned 3 mutating endpoints; `/api/vpa/analyze` had
  joined the set, leaving the guard red and guarding nothing.

---

## Known-remaining (reported honestly, not fixed)

- **6 dead tickers** keep stale bars: `EA, EQR` (both stores), `AVB, LBRDK`.
  Delisted/acquired; `/api/health` now flags them rather than hiding them.
- **qlib panel unpublished** → `qlib_symbols: 0`; Setups shows "QLIB UNMEASURED".
- **IV Rank / IV Percentile** need a trailing IV history the payload does not
  carry. They report absent rather than a constant.
- **Cold-start latency:** the first uncached `/api/options/suggest` build can
  exceed the 30s socket timeout under vendor slowness, so the first load of the
  day can return nothing. Warm, it answers in ~0.6s. A request deadline with a
  partial fail-closed payload is the right fix; not attempted here.
