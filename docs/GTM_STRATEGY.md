# Edge — Go-To-Market Strategy (v1, Sept 2026)

> Builds directly on `docs/MONETIZATION_PLAN.md` (freemium hybrid, $29/mo Pro / $199/yr, derived-values-only launch, no real-time anything in v1). All pricing claims below are verified Sept 2026 unless marked estimate. Hard constraint baked in throughout: **v1 ships on delayed/derived data only** — LSE vault caps at ~15k requests/day and the alternate route has a monthly byte quota, so no real-time OPRA-grade promises anywhere in this plan.

---

## 1. Positioning

**Positioning statement (current):**

Edge is a pre-market options planning desk for serious retail traders: every morning it computes the day's dealer-gamma levels, regime state, IV surface, and 0DTE magnets for the tickers you trade — the same analytics institutions pay six figures for — delivered as a daily brief and a live-delayed dashboard at $29/month, a third of what flow scanners charge. It doesn't dump a raw flow firehose on you; it tells you where the dealer positioning pins price, so you can plan entries before the open instead of chasing prints after they happen.

**Three positioning options to test** (run as landing-page headline A/B/C in week 1, 2 weeks of traffic, judge on waitlist conversion rate per visitor):

| # | Option | Headline | Hypothesis |
|---|---|---|---|
| A | **The gamma desk** | "Know where the dealers are pinned — before the open." | Gamma levels are the product's most screenshot-able, most differentiated artifact (monetization doc calls the gamma map "the viral artifact"). |
| B | **Institutional analytics, retail price** | "The options analytics desk, at 1/3 the price of flow scanners." | Price-led; tests whether the $29 vs $50–149 gap (UW/FlowAlgo/Cheddar) is itself the hook. Risk: attracts price-shoppers who churn. |
| C | **The daily brief** | "Your options market, explained in 5 minutes every morning." | Digest-led; tests whether time-poor traders want *synthesis* rather than more data. Lowest legal risk, weakest wow-factor. |

Decision rule: whichever headline produces ≥2x the waitlist conversion of the runner-up becomes the primary; the runner-up becomes the paid-launch ad angle.

## 2. Target segments (ranked)

| Rank | Segment | Profile | Why first |
|---|---|---|---|
| **1** | **Theta sellers / pre-market planners** (1–45 DTE credit spreads, iron condors, wheels) — the r/thetagang + r/options core | Plans trades before the open or on weekends; needs gamma levels, expected move, IV rank, regime context; does **not** need tick-level speed | **Delayed/15-min data is a non-issue for their workflow** — this is the decisive constraint. They plan around daily levels, which is exactly what the nightly artifact pipeline (routes 09/10, precomputed gamma levels, regime summary) produces at near-zero marginal cost. High tool-spending tolerance (already pay for TradingView/Barchart). Largest reachable free community. |
| 2 | 0DTE / intraday SPX-SPY gamma traders | Biggest, loudest community (FinTwit, Discord); the 0DTE tape engine and intraday gamma map are built for them — **but** they feel every second of the 15-min delay, so v1 under-delivers for them | Hold until either the delayed-chain tier launches (month 2–3) or BYO-key real-time mode ships; they are the month-4–6 expansion segment and the reason real-time is on the roadmap at all. |
| 3 | Flow-curious beginners ("who bought all those calls?") | Attracted by flow scanners; low willingness to pay, high support load, and Unusual Whales' free delayed tier already captures them | Don't target. Let the free SEO pages catch them incidentally; they convert poorly and stress support. |

**Primary segment = #1.** All copy, channels, and onboarding below are tuned to a trader who plans credit spreads on SPY/QQQ/IWM before 9:30 ET.

## 3. Competitive landscape (verified Sept 2026)

| Competitor | Pricing (retail tiers) | Strength | Weakness edge exploits |
|---|---|---|---|
| **Unusual Whales** | $50/$75/$120 mo list; ~$34–82/mo on annual promo; free tier = 15-min delayed flow | Broadest data (flow, GEX heatmaps, politician trades, AI analyst, Discord) | Flow-firehose without conviction ranking — you filter it yourself; no per-ticker daily gamma-level content, no pre-market brief; entry price $50 > edge $29 |
| **FlowAlgo** | $149 mo, $99/mo annual (no free tier; $37 2-wk trial) | Fastest raw sweeps + dark pool | Most expensive in category; zero free onboarding; raw speed is useless on delayed data — different game entirely |
| **Cheddar Flow** | $85/$99 mo, $75/mo annual; 7-day trial | Cleanest UI | Same firehose problem; gamma exposure is a Pro add-on, not a daily-planning surface |
| **BlackBoxStocks** | $59–99 mo (full ~$99.97) | Community/chat rooms, algos | Chat-centric; noisy; nothing pre-market-planning shaped |
| **Market Chameleon** | Free (15-min delayed) / $39 / $69 / $79 / $99 mo | Earnings + IV-rank backtesting depth | Cluttered, screen-and-table UI; earnings-centric, not daily gamma/regime planning |
| **OptionCharts** | Free + Premium (15-min delayed OPRA); Ultimate = real-time w/ OPRA agreement | Clean free chain charts | A charting utility, not a daily workflow; no regime, no brief, no levels |
| **TradingView** (indirect) | ~$14–30 mo | The default chart everyone owns | No options-positioning analytics at all — anchor, not enemy |

**Edge's structural advantages:** (1) price — $29/mo undercuts every paid tier above; (2) *synthesis over firehose* — daily brief + levels vs raw prints; (3) the nightly artifact pipeline makes the **free tier nearly free to serve** (monetization doc: routes 09/10 read offline artifacts), so edge can sustain a genuinely useful free tier the $50–149 players don't bother with; (4) programmatic per-ticker SEO ("SPY gamma levels today") the engine generates at zero marginal cost — no competitor does this; (5) BYO-key mode as a legit real-time escape hatch without redistribution liability.

## 4. Channel plan (ranked by expected ROI)

| Rank | Channel | Expected ROI rationale | First concrete action |
|---|---|---|---|
| 1 | **Programmatic SEO: per-ticker gamma-level pages** | Zero marginal cost (nightly engine already computes levels); compounds; targets rank-1 segment's exact query ("SPY gamma levels today") — monetization doc explicitly lists this | Week 1: generate pages for top 30 tickers (SPY, QQQ, IWM, TSLA, NVDA, AAPL, SPX, AMD, META, AMZN…) with today's levels, expected move, regime state; sitemap + Search Console |
| 2 | **X / FinTwit daily gamma-map post** | The gamma map is the designated viral artifact; daily cadence builds a following that becomes the launch amplifier; $0 | Week 1 start: one post every trading day, 8:45 ET, SPY map + one-line regime read + link |
| 3 | **Weekly gamma-levels email** | Top-of-funnel named in monetization doc; owned audience immune to platform bans; direct waitlist→beta pipe | Week 2: set up (Lemon Squeezy/Paddle list or Buttondown), send Fridays with the week's levels for 10 tickers |
| 4 | **Reddit value posts (r/options, r/thetagang, r/Daytrading)** | Segment #1 lives here; a genuinely useful free gamma-level writeup historically does well; $0 but labor-heavy | Week 2: one high-effort text post (e.g., "how dealer gamma pins SPY into expiry, with today's levels as the example") — teach, don't pitch; link in profile |
| 5 | **Trading YouTube micro-creators (10–100k subs)** | One theta/income-strategy creator review converts its audience at far higher trust than ads; cost ~$0–500/video in free Pro access | Week 4: DM 20 creators offering lifetime Pro + early access; target 3 yeses |
| 6 | **Options Discords** | Where segment #1 and #2 overlap; slow-burn reputation | Week 3: join 5 large servers, be useful in public channels for 2 weeks before any mention |
| 7 | **Product Hunt + Show HN** | One-day traffic spike, weak retention historically — but cheap and gives launch-day social proof | Week 5 launch day only; prep hunter + assets week 4 |
| 8 | TikTok/IG Reels | Youngest audience, worst segment fit (beginners), highest production cost | Deprioritize entirely for v1 |

Paid ads: none until ≥30 paying users; with a $150–300/mo infra budget the unit economics don't support paid acquisition yet.

## 5. Launch plan — 8 weeks, v0 closed beta → v1 paid launch

**Gates carried over from the monetization doc: ≥100 waitlist emails before any options data spend; ≥20 active beta users and ≥5 who'd pay $29/mo before spending on OPRA; lawyer review (~$500–1,500) before charging.**

| Week | Milestones |
|---|---|
| **1** | Landing page + waitlist live (headline A/B/C test running). Lawyer engaged for ToS + publisher's-exclusion review. LLC filed. Start daily X gamma-map posts. SEO pages for top 10 tickers shipped. |
| **2** | Weekly email live. Reddit value post #1. Beta build: Clerk auth, plan-gating middleware, delay badges, disclaimer banner (already scaffolded per monetization doc). Recruit from waitlist + r/thetagang: target **50 beta invites** for 25 accepts. |
| **3** | **v0 closed beta live** (derived-only free tier + full Pro preview). Onboarding: 15-min setup call with each beta user (recorded — these are the testimonial + churn-reason mines). Join/activate 5 Discords. |
| **4** | Beta iteration: ship top 3 requested fixes. Instrument funnel (signup → first brief viewed → day-7 return). **Open the founding-member door: $99/yr lifetime** to beta users + waitlist (monetization doc's WTP probe). Pricing-page A/B starts ($29 vs $49 anchor). Creator outreach begins. |
| **5** | **Go/no-go Wednesday**: gate = ≥20 weekly-active beta users AND ≥5 "yes I'd pay $29/mo" AND lawyer sign-off. If green: **v1 paid launch Tuesday of week 6** — Lemon Squeezy checkout, Product Hunt + Show HN same day, launch email to waitlist, YouTube 3-min walkthrough published. If red: one more beta week, re-gate week 6. |
| **6** | **v1 paid launch + amplification.** Launch-day support rota (single founder: block the full day). Post-launch: publish 2 beta testimonials, SEO pages expanded to top 30 tickers, Reddit post #2 ("how I use gamma levels" style). Target: **10 paying users by end of week 6.** |
| **7** | Retention sprint: onboarding email sequence (day 0/2/5), first weekly free email to full list, fix top churn reason from exit surveys. Decision point per monetization doc: if ≥20 payers, begin delayed-chain vendor procurement for month 2. |
| **8** | Post-mortem + month-2 plan: funnel numbers vs targets (below), pricing experiment readout, decide delayed-chain timing, write 0DTE-segment entry plan (needs real-time via BYO-key or delayed chains). |

**Targets by end of week 8:** 300+ waitlist emails, 25+ active free users, 15–25 paying (~$450–730 MRR) — comfortably above the 30-payer break-even trajectory for delayed chains, on the derived-only ~$150–300/mo cost base.

## 6. Pricing / validation experiments

**E1 — Founding-member door (Wk 4–5).** Offer $99/yr lifetime Pro to the waitlist and beta cohort, capped at 25 seats, one week.
*Success:* ≥15 purchases from ≥100 waitlist emails (≥15% conversion) → validates that the beta cohort's stated WTP is real and pre-funds the delayed-chain tier. <8 purchases → pricing/messaging problem before product problem; re-test at $59/yr before proceeding.

**E2 — Anchor A/B on pricing page (Wk 4–8).** Split new traffic 50/50 between $29/mo and $49/mo Pro anchors (annual fixed at $199 both arms; annual is the expected winner per the monetization doc's TradingView/Bookmap anchor logic).
*Success:* if $49 converts at ≥50% of the $29 rate, monthly revenue per visitor is higher — schedule a $39–49 price test for month 2. If $49 converts <25% of $29's rate, hold $29 (the under- UW/Cheddar price gap is doing work) and never revisit until delayed chains ship.

**E3 — Trial-gate conversion (Wk 6–8).** Free users hitting the paywall on intraday gamma updates get a one-click 14-day Pro trial (no card). 
*Success:* ≥20% trial→paid AND ≥5% of all free users entering trial per month. <10% trial→paid means the free/pro divide is wrong — likely the intraday-updating artifacts aren't valuable enough vs the free daily levels; fix the gate, not the price.

## 7. Top 5 risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| 1 | **Data redistribution/compliance misstep** — displaying raw delayed chains or yfinance-derived data without redistribution rights; OPRA delayed license misunderstood | Launch derived-values-only (monetization doc's recommendation, $0–650/mo); drop yfinance from all user-facing paths; verify each vendor's *redistribution* clause in writing; delay badges on every view (also an OPRA display requirement); BYO-key as the real-time escape hatch |
| 2 | **Publisher's-exclusion slip** — any "Suggest"/"Daily Plays" copy that reads as personalized advice triggers RIA registration exposure | Reframe as impersonal scanner output (already mandated in monetization doc); lawyer review of all marketing copy + ToS before charging; no performance claims anywhere ("our signals returned X%" is banned) |
| 3 | **Delayed data under-delivers for the loudest users (0DTE crowd)** → churn and negative word-of-mouth from the highest-visibility segment | Deliberately market to segment #1 (planners, not scalpers); show data-delay badges prominently; route power users to BYO-key; do not promise intraday precision in any copy until a licensed feed exists |
| 4 | **Free-tier cannibalization** — Market Chameleon and Unusual Whales free tiers set an anchor; users camp on edge's free tier | Gate everything that *updates intraday* (the monetization doc's Pro line: full gamma map + levels updating intraday, flow tape, unlimited watchlists); free tier is the nightly snapshot — genuinely useful, deliberately static; weekly email converts free→awareness→paid |
| 5 | **Solo-founder bandwidth + infra quota burn** (LSE 15k/day vault cap, monthly byte quota; a tripped breaker has previously rendered as "CREDENTIAL MISSING") | Free tier serves precomputed artifacts (near-zero marginal cost); request ledger (`/api/lse-budget`) reviewed before each campaign spike; memoized flow/chain routes; cap launch-day features to what's already shipped — no new views during launch weeks |

## 8. Open questions

1. **LSE commercial terms:** the current provider arrangement lives in the sibling TradingWork repo with consumer-grade keys — commercial redistribution rights for hosted service are unverified. This is a blocking dependency for week 3, not a nice-to-have.
2. **Landing-page waitlist conversion benchmark:** is 100 emails a floor or a stretch? No baseline traffic data exists yet; week 1–2 numbers will calibrate every downstream target.
3. **Founder bandwidth vs 6-day sprint cadence:** the launch plan assumes roughly half of each sprint on GTM; conflicts with the delivery roadmap need an explicit trade-off call.
4. **Delayed-chain timing** is expressed as a payer count (≥20) in the monetization doc but as calendar time (month 2–3) in its cost table — reconcile once E1/E2 data exists.