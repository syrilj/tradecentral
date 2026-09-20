# TypeSafe integration verification — 2026-09-20

The configured `TYPESAFE_API_KEY` authenticated successfully against the official
`https://api.typesafe.ai/v1/systemone` endpoint, using `jev-latest` (resolved to
`jev-1.13.0`). Credentials stayed server-side and were not logged.

## Findings and changes

- Python's default certificate store failed TLS verification. The adapter now adds
  certifi's trusted roots while retaining system roots and hostname verification.
- Browser observation timestamps defeated the evidence cache. Observation time is
  now response metadata; actual source timestamps, freshness, evidence, questions,
  model, and credential identity remain in the cache key.
- Concurrent identical snapshots are coalesced. Eight test callers made one
  provider call. Cached responses are isolated from caller mutation.
- Authentication failures now report HTTP status without exposing response bodies
  or credentials.
- Historical options fallback is labeled stale in the decision screen. Symbol
  changes during source collection cannot relabel the old evidence as a new ticker.
- Loading text distinguishes market collection from TypeSafe evaluation.
- Rebuilt the dashboard and restarted the old local backend on 127.0.0.1:8787.

## Measurements

These are individual development measurements, not percentile benchmarks.

| Measurement | Result |
| --- | --- |
| Direct live five-question evaluation | 218 ms |
| Tokens in that request | 925 input, 142 output |
| Application adapter, first evaluation | 217.53 ms |
| Application adapter, same evidence with new observation time | 0.41 ms, cache hit |
| Restarted production-local route, provider latency | 313 ms |
| Old backend options / regime / VPA / session gate | 17.068 / 18.917 / 0.500 / 11.114 seconds |
| Current temporary backend options / regime / VPA / session gate | 4.471 / 14.846 / 0.240 / 0.020 seconds |

The two market-data runs are not equivalent benchmarks: the current options run
returned historical fallback. The current regime cold computation remains slow.
TypeSafe is called after source collection, so its subsecond latency does not make
the entire cold-load flow subsecond. No dollar savings estimate is claimed; the
cache removes duplicate billable calls inside its 15-second window.

## Validation and scope

- 14 Python regression tests passed; targeted Ruff checks passed.
- 4 decision-screen tests passed; full frontend type-check and production build passed.
- Live adapter and HTTP-route smoke tests returned `typesafe`, not fallback.
- Smoke evidence was synthetic and closed-gate; posture was `wait`, with
  `decision_authorized=false`. This verifies connectivity and integration, not
  live-session trading performance or calibration.

Repeat the small paid smoke test from the repository root:

```sh
.venv-qlib/bin/python tools/test_typesafe_live.py
```

Official contract checked: https://docs.typesafe.ai/api.md

## Bounded collection and separate lean

The Decision page now gives each parallel source a 2.5-second collection window,
then submits available evidence to TypeSafe. Slow requests are retained and consumed
on a later five-second refresh, avoiding duplicate requests for the same symbol and
source. Pending data is explicitly marked; source timestamps remain in the input.
The collection window does not bound inference or total network latency.

A separate parallel Choice judgment reports bullish, bearish, neutral, or unknown
lean independently of entry timing and policy. WAIT can therefore retain a bullish
or bearish lean. The local fallback ignores sources not marked ready and labels
its direction as fallback, with no model confidence for that lean.

Validation: 16 Python tests and 5 frontend tests passed, including slow-request
reuse and closed-gate direction preservation. Frontend type-check and production
build passed. No new live latency or trading-accuracy benchmark was performed.
Live documentation retrieval was unavailable (DNS/access failure); the existing
verified Choice request contract was retained.
