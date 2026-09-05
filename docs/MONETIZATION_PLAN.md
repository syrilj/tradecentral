# Monetizing TradeCentral — Freemium Hybrid Plan

> Decision context (2026-08-29): model = **freemium hybrid** (hosted app, delayed/EOD data, monetize analytics). Buyer = **serious retail options/day traders**.

## What's here

TradeCentral is a local-first quant workstation: 35+ Vue views (regime engine, dealer gamma maps, options chains + Greeks, flow tape, microstructure, scanners, calculators), a 337KB stdlib Python API (`tools/api_server.py`), and nightly research artifacts. It binds to 127.0.0.1 by design, but already carries network-deployment scaffolding: Clerk auth (`dashboard/src/auth.ts`, `AuthView.vue`), `EDGE_REQUIRE_AUTH`, CORS allowlist, request concurrency guards — the server refuses non-loopback binds until auth is safe.

## The load-bearing fact (fee schedules as of Aug 2026)

Real-time options is what makes hosted trading products expensive:

- **OPRA redistribution license: ~$1,500/mo flat** (or ~$650/mo query-only), **plus** $1.25/user/mo non-professional, $31.50/user/mo professional, plus $2,000/mo per non-display category if real-time data feeds server-side calcs.
- **Delayed (15+ min) data: no per-user OPRA fees** — but the redistribution license still applies if you display raw chains.
- Equity delayed/EOD redistribution is far cheaper (vendor plans ~$99–299/mo, e.g. Twelve Data/Tiingo tier, include redistribution rights).

Therefore freemium hybrid is viable **only if v1 ships on delayed/data-derived analytics** and real-time options is reserved for a later tier (or dropped). A real-time tier at $1,500+/mo needs ~40 paying users just to cover OPRA.

Sources: [ThetaData OPRA Fee Guide](https://www.thetadata.net/articles/2026-05-29-opra-fee-guide-for-options-market-data), [marketdata.app OPRA fees explainer](https://www.marketdata.app/education/options/opra-fees/), [OPRA fee schedule (SEC)](https://www.sec.gov/files/rules/sro/nms/2025/34-104267-ex1.pdf), [Massive (ex-Polygon) pricing](https://massive.com/pricing) (verify; reference: [qveris.ai pricing guide](https://qveris.ai/guides/polygon-pricing-optimized/)).

## Data stack changes required

1. **Drop yfinance entirely** from anything user-facing — Yahoo TOS does not permit commercial redistribution. Replace with a vendor whose plan includes redistribution rights (verify "redistribution" clause, not just "commercial use").
2. **Options chains:** cheapest compliant launch = delayed chains via a vendor + OPRA delayed-redistribution license (~$650–1,500/mo). Cheaper still: show only **derived values** server-computed (gamma exposure by strike, expected move, IV surface stats) — derived data that can't be reverse-engineered into quotes sidesteps per-user fees. Gate raw chain grids behind the paid tier and verify OPRA delayed terms before launch.
3. **Fintel** (insiders/ownership/short interest): API redistribution terms are restrictive — verify an enterprise/redistribution plan or cut those views from the hosted product (keep in local mode).
4. FINRA short-volume files are publicly downloadable; display is generally fine but confirm FINRA's retransmission terms.
5. Keep **BYO-key mode** as an escape hatch: power users paste their own Massive/ThetaData key for a real-time view — you never redistribute. The adapter pattern already exists (`LSEOptionsAdapter` in `tools/api_server.py`).

## Product cut (v1) — views in/out

**Free tier** (delayed/EOD, hero features for screenshots): Regime summary (state + transition probs), daily gamma levels (precomputed nightly), watchlist (max 5), options calculators, squeeze calc, EOD scanner highlights.

**Pro tier ~$29/mo or $199/yr** (15-min refresh): full gamma map + levels updating intraday, full options chain w/ Greeks + expected move, flow tape + alerts, microstructure regime view, anomalies, sectors/macro, unlimited watchlists, CSV export.

**Exclude from v1:** real-time data of any kind; order routing/execution (none exists — keep it that way, avoids broker-dealer territory); personalized recommendations — reframe "Daily Plays"/"Suggest" views as *scanner output* with impersonal criteria, not "we recommend you buy X"; social/copy-trading; portfolio-specific advice; any performance claims in marketing ("our signals returned X%" invites FTC/SEC trouble unless audited).

## Legal obligations (minimum viable compliance)

1. **Investment Advisers Act — publisher's exclusion:** keep all content impersonal, general, and regularly published. No tailored advice, no individual-targeted signals. This keeps you out of RIA registration. The single most important legal design constraint; it shapes feature naming/copy.
2. **ToS + disclaimers** ("not investment advice; informational only"), **privacy policy** (Clerk + analytics ⇒ GDPR/CCPA basics: consent, deletion endpoint).
3. **Entity:** LLC before charging.
4. **Payments/sales tax:** Merchant of Record (Lemon Squeezy/Paddle) to avoid 40-state sales-tax registration, OR Stripe + Stripe Tax.
5. **Marketing:** no guaranteed-return or backtest-as-live-performance claims (FTC substantiation).
6. **No execution/funds handling.**

## Architecture work (what gets built)

1. **Production server**: serve `api_server.py` behind gunicorn; per-route auth + plan-gating middleware, per-user rate limits.
2. **Central data pipeline**: nightly/15-min batch (existing `tools/build_*.py`, `daily_plays_schedule.py`) → shared artifact store (GCS/S3 + Postgres). Views that already read offline artifacts (routes 09/10) are free-tier content at near-zero marginal cost.
3. **Billing**: Stripe Checkout + Customer Portal + webhook → entitlement table (plan → view gates in `dashboard/src/router.ts` + API route guards).
4. **Provider swap layer**: config-driven provider registry so the hosted product uses licensed vendors while local mode keeps current sources (incl. BYO keys).
5. **Compliance UI**: disclaimer banner, data-delay badges on every view (also an OPRA/license requirement), ToS/privacy pages.
6. **Ops**: Fly.io or Hetzner VM ($20–60/mo) + Cloudflare for the SPA + managed Postgres (Neon/Supabase free tier), uptime monitor, Sentry.

## Realistic costs at launch

| Item | Monthly |
|---|---|
| Equities vendor w/ redistribution rights (delayed) | $99–200 |
| Options: derived-values-only launch (no chain display) | $0–650 |
| Options: delayed chain display (OPRA delayed + vendor) | ~$650–1,500 |
| Hosting + DB + storage + email | $40–80 |
| Clerk (≤10k MAU), Sentry, domain | ~$0–30 |
| **v1 total (derived-only options)** | **~$150–300** |
| **v1 total (with delayed chains)** | **~$850–1,800** |

Stripe/MoR takes 2.9%+30¢ (or ~5% MoR). Break-even on delayed chains at $29/mo ≈ 30–55 paying users. **Recommendation: launch derived-only, add delayed chains in month 2–3 once ~20 paying users exist.**

## Launch sequence

1. **Landing page + waitlist** (gamma map + regime screenshots are the hook) — before any build.
2. **Closed beta**: 20–50 users from r/options, r/thetagang, options Discords; free in exchange for feedback + testimonials. Validate willingness to pay with a "founding member $99/yr lifetime" Stripe door.
3. **Paid launch:** X/FinTwit daily gamma-map posts (the map is the viral artifact), 3-min YouTube walkthrough, Product Hunt, Show HN, SEO pages per ticker ("SPY gamma levels today" — the engine generates these for free).
4. Price anchor: TradingView Essential ~$14–30/mo, Bookmap ~$50–100/mo → **$29/mo, $199/yr**, weekly free gamma-levels email as top-of-funnel.

## Verification / success gates

- Waitlist converts ≥100 emails before paying for any options license.
- Beta: ≥20 active users, ≥5 who'd pay $29/mo, before spending on OPRA.
- Lawyer review of ToS + publisher's-exclusion posture (~$500–1,500 one-time) before charging.

## Explicitly out of scope (later expansions)

Selling computed signals as an API, real-time anything in v1, mobile app, broker integrations — each changes the legal/cost math.
