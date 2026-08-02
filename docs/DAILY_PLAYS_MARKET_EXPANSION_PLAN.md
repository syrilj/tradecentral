# Daily plays — market-expansion plan

Date: 2026-07-30  
Status: implementation in progress  
Operator goal: use market rotation and live options activity to decide where to
scan, then return only executable same-day option tickets as plays.

## Product contract

The normal command remains:

```bash
python3 -m edge.daily_plays today --account 1000
```

Its terminal output has three compact sections:

1. `Market map`: where relative strength and money flow are moving.
2. `Validated actionable plays`: exact contract, limit reference, risk, and
   calibrated confidence. This section contains `ENTER` records only.
3. A short causal explanation when no ticket passed. Rejected and research rows
   remain in JSON/audit artifacts and are never printed as plays.

`NO_PLAY` must mean that the entire configured discovery and validation funnel
was run and no candidate passed. It must not mean that a seven-symbol promoted
model was treated as the entire market.

## Funnel

```text
fresh sector/theme heatmap
            |
            v
leading and lagging sleeves + liquid focus names
            |
            v
bounded broad-market target set
            |
            +--> promoted directional models
            +--> promoted option-strategy models
            +--> historically validated live-flow features
            +--> research challengers (sealed from decisions)
            |
            v
directional candidate shortlist
            |
            v
live listed contract identity + NBBO + OI/volume + Greeks
            |
            v
spread, freshness, DTE, delta, concentration, and account-risk gates
            |
            v
ENTER tickets only
```

Heatmap and flow evidence route compute. They never manufacture a probability
or bypass an execution gate.

## Current evidence and gaps

| Component | Current finding | Decision use |
|---|---|---|
| Sector/theme heatmap | Fresh LSE daily bars, 14 books, balanced leaders and laggards, 25 routed targets | Active routing input |
| Promoted v72 equity sleeve | Verified deployment artifact, seven-symbol domain, ordinal confidence | Directional setup only; cannot claim fixed-horizon probability |
| v35 options sleeve | Eight-name OOS option-strategy champion; current-day scan produced no opening event | Candidate lane after artifact-integrity and live-paper controls are completed |
| 60-name daily challenger | Correct 5/10/20-session target and walk-forward calibration, but latest development gate failed | Research only; cannot authorize chains or tickets |
| LSE options flow | Current trade prints, premium, contract identity, IV and Greeks | Discovery/evidence only because aggressor side is not reported |
| LSE options chain | Expired-page starvation repaired; current expirations are now returned | Still execution-incomplete: no live bid, ask, or open interest fields |
| Kronos | Interval/regime research only; directional edge is not validated | Advisory only |

There are therefore two independent promotion blockers:

1. no broad directional model currently passes the frozen development gate; and
2. the connected live options source does not expose the NBBO/OI fields required
   to prove an executable entry.

Neither blocker may be hidden by displaying ordinal scores as confidence.

The latest corrected 60-name challenger confirms why a replacement experiment
is required. Its 5-day XGBoost candidate had positive standalone expectancy but
a negative paired lower confidence bound versus momentum; the 10-day winner
was momentum itself; and the 20-day winner also failed incremental edge. Active
rates were roughly 98–100%, so the system was mostly harvesting market drift
rather than selecting a small daily opportunity set. No earlier artifact passes
the current paired gate.

## Delivery tracks

### Track A — market and flow discovery

- Keep the sector heatmap visually separate and compact.
- Route both strong and weak sleeves so the scan can find calls and puts.
- Reproduce only historically defined flow features from their original raw
  inputs and thresholds.
- Batch live-flow reads with a bounded total timeout.
- Record coverage counts: books, routed names, live-flow names, directional
  candidates, requested chains, valid chains.
- Treat unknown aggressor-side prints as unsigned activity, not bullish or
  bearish evidence.

Acceptance:

- a wrong-symbol or stale provider page cannot enter the target set;
- rerunning with frozen inputs produces identical routing;
- flow expands discovery without changing model confidence; and
- the operator can see exactly how much of the broad route was scanned.

### Track B — model lanes

- Keep v72 behind its verified manifest.
- Add v35 only through a verified options-strategy manifest that hashes its
  engine/config/election evidence and preserves its eight-symbol domain.
- Rebuild the broad daily challenger from a point-in-time liquidity universe.
- Freeze an objective 150–300-name optionable/liquid universe with delistings
  and immutable raw/corporate-action snapshots.
- Compare learned models against simple momentum and sector-relative-strength
  baselines before opening the terminal holdout.
- Target a selective 2–15% daily activity rate or a fixed top/bottom candidate
  budget, with every candidate compared to baselines at matched coverage.
- Use purged walk-forward out-of-fold predictions, date-block bootstrap,
  search-adjusted performance, fixed 5/10/20-session event semantics, and
  calibration measured on untouched data.
- Nest family, feature, hyperparameter, calibrator, and operating-threshold
  selection entirely inside each outer fold; count the full adaptive research
  lineage in multiplicity control.
- Start a prospective terminal holdout only on the first full session after
  code, environment, universe, data, feature, and decision-policy hashes are
  frozen. Do not reuse the backdated July 13 interval.
- Promote a model lane only when its pre-registered lower confidence bound is
  positive after costs and its calibration/reliability limits pass.

Acceptance:

- no archived or failed artifact can be selected by `latest`;
- every emitted probability identifies its event, horizon, calibrator, and
  artifact hash;
- model-domain coverage and broad research coverage are reported separately;
- a strategy-specific options model is never mislabeled as an underlying
  directional probability.

### Track C — execution validation

- Retain the active-expiration filtering added to the LSE chain loader.
- Introduce an explicit provider-capability preflight for contract identity,
  same-session timestamp, bid, ask, OI, volume, and Greeks.
- Connect a live NBBO-capable source before any broad candidate can become
  `ENTER`.
- Join quotes by exact OCC/provider contract identity; never synthesize an
  option symbol from strike and expiry.
- Enforce 30–60 DTE, delta, spread, OI, volume, quote-age, per-position,
  per-underlying, and aggregate-risk limits.

Acceptance:

- an expired, delayed, incomplete, crossed, wide, or identity-less quote fails
  closed with the exact field-level reason;
- a valid fixture and a real provider snapshot share the same canonical
  contract;
- the terminal ticket includes the exact contract and a limit reference derived
  from current executable quotes.

### Track D — output and learning loop

- Keep `plays.json` and the terminal play table `ENTER`-only.
- Persist watches, rejections, flow discoveries, research candidates, and
  provider capabilities in separately named artifacts.
- Realize underlying and option outcomes at their declared horizons.
- Monitor hit rate, Brier/ECE where probabilities apply, net expectancy,
  drawdown, coverage, provider failures, and abstention causes.
- Require frozen shadow evidence before widening a model or changing a gate.

Acceptance:

- no `ABSTAIN` row appears beneath a play heading;
- `NO_PLAY` names the actual exhausted funnel and the first causal blocker;
- the audit can distinguish “no setup” from “setup found but no executable
  quote”; and
- every promotion is reproducible from immutable artifacts.

## Dependency order

1. Finish provider/model/flow audits and freeze the schemas.
2. Land the LSE active-contract repair and capability preflight.
3. Add the broad live-flow discovery artifact without granting decision rights.
4. Verify and integrate the v35 strategy lane as shadow-only.
5. Train/evaluate the new point-in-time broad directional challenger.
6. Connect and validate a live NBBO/OI provider.
7. Run replay, unit, live smoke, and shadow-readiness gates.

The command can become broader before all tracks finish, but it cannot truthfully
produce a live-validated option ticket until both a directional lane and the
execution-data lane pass for the same candidate.
