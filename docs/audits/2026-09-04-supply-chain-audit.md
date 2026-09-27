# Supply Chain (`/chain`) Audit — Math, Code, UI

Date: 2026-09-04. Branch: vpa/production-hardening.
Scope: `tools/supply_chain.py`, `/api/supply-chain[/themes]` handler, `ChainView.vue` + `ValueChainGraph` / `BeneficiaryTable` / `EvidenceDrawer` / `ThematicBanner`, `chainDisplay.ts`, API contracts.

## What was wrong

### Fabricated data rendered as measurements (recurring repo bug class)

1. **Seeded-RNG peer metrics** — `_peer_node` filled `capex_sensitivity`, `revenue_concentration_pct`,
   `operating_leverage`, `forward_pe`, `peg_ratio`, `yoy_revenue_growth`, `flow_sentiment_score` from
   `_seeded_float(symbol, salt, lo, hi)` (MD5 of "SYMBOL:salt"). Every auto-discovered peer on earth got a
   plausible number in a fixed bullish range (`flow` 0.6–0.9, `options_skew` hardcoded `"bullish_call_drift"`,
   `gross_margin_trend` hardcoded `"expanding"`).
2. **Fabricated SEC citations** — `_peer_node` attached a `sec_10q` "evidence" card to every peer with a canned
   quote ("operating disclosures confirm ongoing commercial supply alignment…"), `confidence: 0.88`, dated
   **today**. `_discover_company_graph` attributed an invented "disclosures confirm capacity buildouts, customer
   purchase commitments…" sentence to *real* filings (real form/date, invented quote), and when EDGAR returned
   nothing it emitted a fully invented citation.
3. **Template relationships for arbitrary tickers** — for any symbol not in the 15-name curated registry, sector
   keywords triggered one of 7 archetype branches asserting named companies as the queried firm's suppliers /
   customers with invented strengths (0.89–0.98) and invented quote text (e.g. every healthcare symbol "buys
   sterile fill-finish from CTLT").
4. **Invented future events** — dedicated/fallback payloads shipped a `catalyst_timeline` with fixed dates:
   a "Periodic SEC 10-Q Filing" dated 2026-08-28 (already in the past) and a "Strategic Supplier & Partner
   Summit" on 2026-09-18, generated for *any* symbol.
5. **Dead-key fallback literals** — focal valuation read `ratios["forward_pe"]` / `ratios["peg_ratio"]`, keys
   `financial_data._extract_ratios` never emits (real keys: `pe_forward`, `revenue_growth_yoy`), so *every*
   arbitrary-ticker focal silently served P/E 22.0 and PEG 1.1, plus hardcoded elasticity 88.5, capex sens 3.0,
   rev conc 32.0, op lev 3.2, flow 0.78.

### Math
6. Elasticity formula (0.35·capexSens + 0.25·revConc + 0.20·opLev + 0.20·flow, each min-max normalised) is
   coherent **but** defaulted missing inputs to mid-range literals, so unknown peers scored ~70 instead of
   being unscored, and entered the `top_beneficiaries` ranking on fabricated inputs. `min(99.9, max(10.0, …))`
   plus `or 75.0` masked bad composites.

### UI
7. Graph column headers were hardcoded to the AI-datacenter theme ("Materials & Metrology", "Optics, Memory,
   Cooling") for every theme (GLP-1, space, financials…).
8. Tier filter had render cases for `tier2`/`customer` but no buttons — unreachable filters.
9. `optionsSkewLabel(undefined)` rendered a "Neutral" chip when no skew data existed — indistinguishable from
   a measured neutral skew.
10. TS contracts typed every metric non-nullable, so a dropped metric typechecked while rendering "—" or a
    wrong literal.

## Fixes applied

- `_peer_node`: identity + market cap + forward P/E + YoY revenue growth from the live profile (new additive
  `about.forward_pe` / `about.revenue_growth_yoy` keys in `financial_data` — no extra network cost); every
  underivable metric `None`; `evidence: []`.
- `_discover_company_graph`: correct ratio keys (`pe_forward`, `revenue_growth_yoy` + income-row YoY fallback);
  no literal fallbacks; filing citations carry real form/date/description with `quote: None`; no fallback
  citation; when the symbol is in a curated ecosystem, curated metrics+citations overlay the focal (that is the
  product's analyst dataset).
- Non-registry dedicated mode: honest graph = focal + real same-sector peers from the tracked universe with
  `peer` edges; archetype supplier templates removed; narrative states the limitation.
- `calculate_beneficiary_elasticity`: weighted average over **present** components only; returns `None` when no
  inputs exist; callers skip `None` from `top_beneficiaries` and emit `elasticity_score: null`.
- Dedicated/fallback `catalyst_timeline`: inherited from the curated ecosystem when the focal belongs to one,
  else empty (the banner simply hides an empty timeline).
- UI: theme-neutral column labels; all four tier filters reachable; skew chip shows "—" when absent; drawer
  skips `null` quotes; contracts widened to `| null`.
- Tests that pinned fabrications updated to pin honesty instead.

## Verification (2026-09-04, live)

- `.venv-qlib/bin/python -m pytest tests/test_supply_chain.py tests/e2e/test_supply_chain_endpoint.py` — **17/17 pass**.
- `vitest run chain-display chain-view` — **12/12 pass**; `vue-tsc --noEmit` — clean (BriefView null-ranking fixed).
- Live endpoint, three paths after server restart:
  - **Unknown symbol** (XYZQ): focal + 8 real same-sector peers, all metrics null, `catalyst_timeline: []`,
    zero evidence quotes, honest narrative.
  - **Registry symbol** (AAPL): curated-registry multi-tier graph (16 nodes / 19 edges), real fwd P/E 33.65
    and YoY growth 16.4 via new `about.forward_pe` / `about.revenue_growth_yoy`; no scoring inputs invented.
  - **Curated node** (MU): curated metrics overlay the focal (elasticity 92.5, timeline of 4 curated events),
    beneficiaries ranked: ALAB, AAOI, SMCI, VRT, MRVL, LITE.
- Browser verification on rebuilt `runs/dashboard_dist` (:8787): theme-neutral column headers render;
  All/Tier 1/**Tier 2**/Drivers/**Customers** filters all present and filter live; skew cells render "—" for
  null; drawer shows "—" metrics, no blockquote without a real quote, and the honest no-citations line;
  zero console errors.
- Known residual: cold-cache dedicated mode for a registry symbol can exceed the frontend fetch timeout
  (client `ERR_ABORTED`) while the backend still computes and caches; a subsequent refresh renders
  instantly. Server-side latency for registry peer profile fetches is the remaining polish item.
