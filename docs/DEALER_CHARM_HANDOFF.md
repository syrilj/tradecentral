# Dealer / Charm read handoff

## Task

The Drift view was producing conflicting interpretations of the same options snapshot. The representative case is NVDA with spot `225.30`, put wall `220`, call wall `230`, net GEX `+778M`, net charm `-952,833 sh/day`, pressure imbalance around `+0.28`, and a source flag of `actionable: true`. The old UI described this as a confirmed bullish breakout and emitted an execution directive even though spot was still inside the supplied walls and the tape was nearly balanced. The feed was also about `86,000` seconds old while the backend confidence freshness could still read as 100%.

## Intended behavior

There must be one primary read. It should:

- classify spot by the supplied walls using strict outside comparisons; equality remains in range;
- show stale or unknown age before interpreting current wall location;
- describe charm as a structural Black-Scholes/OI positioning proxy (`negative net charm` means modeled dealer buying), never as observed tape flow;
- keep GEX as volatility/context information, not a directional vote;
- show pressure/actionability as source evidence rather than letting it override price location;
- avoid inferred gamma flips, guaranteed follow-through, entry/exit instructions, targets, stops, or claims of confirmation;
- preserve explicit missing, invalid, zero, and unmeasurable states.

For the representative case, the clear read is: stale snapshot; last reported spot is inside `220–230`; charm shows a modeled buying tilt; current direction is unverified until a fresh snapshot arrives.

## Current implementation

`dashboard/src/dealerRead.ts` contains `resolveDealerRead(payload, now?)`, the single structural resolver. It returns `unavailable`, `stale`, `in_range`, `above_call_wall`, or `below_put_wall`, plus concise narrative, watch text, and evidence fields. Freshness is based on the greatest available feed/tape age and elapsed age from `asof_utc`, with a five-minute policy threshold. Non-live modes, unknown age, and an explicitly stale underlying mark the read stale.

`dashboard/src/views/DriftView.vue` imports the resolver and renders the primary read card (`data-testid="dealer-primary-read"`). The duplicated microstructure assessment, consensus directive, pressure-channel voting display, and strategy activation logic were removed from the script/template while the controls, charts, GEX map, and strike table remain available as evidence/detail views.

`dashboard/src/__tests__/dealer-read.test.ts` covers the representative stale case, the fresh in-range case, opposing pressure, wall equality/boundaries, invalid wall data, zero versus unmeasurable GEX, unknown freshness, and unavailable charm.

## Remaining work for the next agent

1. Run the dashboard typecheck and targeted tests with the supported Node runtime:

   ```bash
   cd dashboard
   PATH=/opt/homebrew/bin:$PATH npm test -- --run src/__tests__/dealer-read.test.ts
   PATH=/opt/homebrew/bin:$PATH npm run build
   ```

2. Inspect the rendered `/drift` page against the real API response. The local API is normally at `http://127.0.0.1:8787`; the Vite dev server may require the host's approved runtime/port permissions. Confirm the card visibly says stale/in-range and that no old “EXECUTE LONG”, “confirmed breakout”, “bullish breakout”, or strategy grid remains.

3. Fix any TypeScript/template errors caused by removing the old computed values. Keep changes scoped to the dealer/charm work; this checkout already contains unrelated pre-existing modifications.

4. The backend audit identified a separate semantic defect in `daily_plays/options_intelligence.py`: pressure confidence freshness is currently promoted by `mode_resolved == live` without necessarily incorporating feed/tape age. If changing the backend, add a focused age input to the pressure-gauge call, make stale/unknown source age unable to produce `actionable: true`, and add Python tests. Do not alter the charm sign convention or blend math: positive net charm is dealer selling, negative net charm is dealer buying; GEX remains context.

## Files owned by this handoff

- `dashboard/src/dealerRead.ts`
- `dashboard/src/__tests__/dealer-read.test.ts`
- `dashboard/src/views/DriftView.vue`
- optionally `daily_plays/options_intelligence.py` and a focused Python test for the freshness defect

Do not reset or clean the repository. The worktree is intentionally dirty with unrelated user changes.
