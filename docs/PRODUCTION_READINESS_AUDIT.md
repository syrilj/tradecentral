# Production readiness audit — 2026-08-14

## Verdict

The dashboard is ready for an authenticated, single-replica internal deployment after the environment in `PRODUCTION_DEPLOYMENT.md` is configured. It is not ready for horizontal scaling or public multi-tenant use: scan jobs, caches, provider deduplication, and artifacts remain process-local.

## Findings and disposition

| Severity | Finding | Disposition |
| --- | --- | --- |
| Critical | Clerk protected only the Vue route; the Python API did not verify the bearer token. | Fixed. Protected API routes verify Clerk session JWTs and authorized parties when `EDGE_REQUIRE_AUTH=1`. |
| High | A wider server bind would have exposed wildcard-CORS API routes without a backend security boundary. | Fixed. Non-loopback startup fails unless auth and an exact CORS allowlist are configured. |
| High | The locked frontend tree contained the high-severity `nanoid` advisory GHSA-2v37-7h3g-55p8. | Fixed by updating `nanoid` from 3.3.16 to 3.3.18; `npm audit --omit=dev --audit-level=high` reports zero vulnerabilities. |
| High | Jobs and caches are in memory, so multiple replicas would disagree and duplicate provider work. | Open by design. Run one API replica; externalize jobs, locks, caches, and artifacts before horizontal scaling. |
| Medium | `ThreadingMixIn` could create an unbounded number of request threads. | Fixed with bounded concurrency (default 32), listen backlog, and socket deadlines. |
| Medium | Browser fetches had no deadline and could wait indefinitely on a degraded provider/API. | Fixed with a configurable 30-second client deadline; background polls already avoid overlap and pause in hidden tabs. |
| Medium | Text/JSON/static JavaScript responses were uncompressed. | Fixed with negotiated gzip. Live smoke test reduced the 186 KB main JavaScript asset to about 66 KB on the wire. |
| Medium | Direct `npm test`/`npm run build` under old Node failed inside Vite with an opaque Web Crypto error. | Fixed with explicit Node 18 engine and preflight checks. |
| Medium | The operator dependency file omitted the Clerk backend SDK already used by the validated environment. | Fixed with a pinned `clerk-backend-api==6.0.1`. |
| Medium | Google client libraries will stop supporting Python 3.10 after 2026-10-04. | Open migration item. Revalidate the scientific environment on Python 3.11+ before the deadline. |

## Performance evidence

- Frontend route-level code splitting is active.
- Main application JavaScript: 186.28 KB raw / 65.56 KB gzip.
- Three.js risk-neutral model: 518.67 KB raw / 131.09 KB gzip, lazy-loaded outside the initial route.
- Frontend: 211 tests passed; production TypeScript/Vite build passed.
- Python: 1,093 tests passed in 202.77 seconds.
- Focused API/production contracts: 103 tests passed.
- Python environment: `pip check` reports no broken requirements.
- Frontend production dependency audit: zero known vulnerabilities reported.

## Scaling boundary

The Vue/static layer can be cached and replicated independently. The API should stay at one warm replica for the current operator/team workload. The next scale step is not more HTTP threads; it is separating interactive reads from provider acquisition and scientific jobs:

1. Move scans to a durable queue with persisted job state.
2. Put provider single-flight locks, rate budgets, and hot payloads in a shared cache.
3. Store immutable artifacts in versioned object storage with a manifest.
4. Split artifact reads, cached provider reads, live compute, and mutations into explicit endpoint classes with latency budgets.
5. Load-test representative cached and cold paths, then choose worker/process counts from measured p95 latency and memory use.

Until those steps are complete, keep one API replica and treat process restart as cancellation of any in-flight scan.
