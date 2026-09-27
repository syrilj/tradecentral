# Open source release checklist

TradeCentral is still a private project. Keep the existing repository private
until the current working tree is reviewed and an open source license is chosen.

## Current audit

### Verified in the current working tree (2026-09-26)

- Dashboard production build and the complete frontend suite pass (135 files,
  2,702 tests). The Market view's focused suite passes all 44 tests.
- Local API security tests pass (54 tests), and the Cloudflare Worker security
  tests pass (6 tests).
- Core leak-resistance checks pass (3 tests). The full Python suite is not yet
  verified in this checkout: the default Python lacks `cvxpy`, and the frozen
  research environment's SciPy binary fails to import on this host. A run from
  the workspace parent with the two optimizer modules excluded passed 2,016
  tests before a test requiring the repo-relative `data/1d` directory failed;
  that focused test passes when run from the repository root. A repository-root
  run of the available suite is in progress. A stale adversarial assertion for
  0.1% IV was corrected to require an unmeasured expected move; its focused
  file passes.
- The seven primary research workspaces (Flow, Options, Setups, Regime, Charm,
  Vanna, Market) were checked in the local browser at 375, 768, 1024, and
  1440 px for workspace-width overflow. Market and Options overflow found at
  the two smallest widths was fixed.
- Gitleaks found no secrets in the current Git diff. A full history scan still
  reports the documented `generic-api-key` field-name match in
  `docs/SQUEEZE_FUEL_CALIBRATION.md`; it is not a credential.

These checks cover the local source and preview configuration. The exact public
deployment still needs an anonymous, owner, and non-owner access smoke test
before its access claims can be treated as verified.

- The local `.env`, `.env.preview.local`, and `cloudflare/.env.cloudflare` must
  stay out of Git. The Cloudflare profile was tracked previously; it is now
  ignored and removed from the index while its local copy remains on disk.
- The 13 tracked `.claude-flow/` runtime files were removed from the index and
  ignored. They are generated state, not project source.
- A Git-history Gitleaks scan on 2026-09-26 reported one generic-key match in
  `docs/SQUEEZE_FUEL_CALIBRATION.md`; manual inspection identified it as a
  source-code field name, not a credential. The historical Cloudflare profile
  contains empty values for its Clerk verifier, owner ID, publishable key, and
  Convex URL. Repeat the scan immediately before publication, including any
  new commits and pull requests.
- The dashboard operator email is now supplied through ignored local build
  configuration instead of a source constant. A Vite `VITE_` variable is
  embedded in the browser bundle, so it is an access hint, not a secret. The
  Python API and Convex must enforce the exact Clerk user ID independently.

## Before changing repository visibility

1. Review `git diff --cached`, `git diff`, and untracked files. Commit only
   intentional source, documentation, and tests; never commit local datasets,
   generated market data, model binaries, provider tokens, or environment files.
2. Run Gitleaks over all Git history and inspect every result without posting
   credential values in an issue or log. Rotate any real credential discovered.
3. Choose and add a `LICENSE`. A formal Commercial Proprietary Software License and Evaluation Agreement has been added to `LICENSE` with explicit trade secret protections, UCC warranty disclaimers, liability caps, and in-app `/license` and `/terms` disclosures.
4. Check provider data redistribution terms before adding dashboard screenshots
   or example snapshots to the public repository. Prefer screenshots with no
   account identifiers or licensed raw data.
5. Re-run the dashboard build, security tests, and an anonymous/owner/non-owner
   authentication smoke test against the exact deployment to be published.
   Restore a working research environment and run the complete Python suite.
6. Update the README's launch state and screenshot links so they describe what
   a visitor can actually open. Keep the private API hostname and local profile
   outside committed configuration.

Cloudflare `workers.dev` currently serves a public preview with a Clerk
development instance. Clerk documents development instances as unsuitable for
production workloads; a production instance needs a domain you control. Do
not describe this preview as a production authentication boundary.
