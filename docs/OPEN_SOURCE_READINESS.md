# Open source release checklist

TradeCentral is still a private project. Keep the existing repository private
until the current working tree is reviewed and an open source license is chosen.

## Current audit

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
3. Choose and add a `LICENSE`. Without one, a public repository is visible but
   does not grant normal open source reuse rights.
4. Check provider data redistribution terms before adding dashboard screenshots
   or example snapshots to the public repository. Prefer screenshots with no
   account identifiers or licensed raw data.
5. Re-run the dashboard build, security tests, and an anonymous/owner/non-owner
   authentication smoke test against the exact deployment to be published.
6. Update the README's launch state and screenshot links so they describe what
   a visitor can actually open. Keep the private API hostname and local profile
   outside committed configuration.

Cloudflare `workers.dev` currently serves a public preview with a Clerk
development instance. Clerk documents development instances as unsuitable for
production workloads; a production instance needs a domain you control. Do
not describe this preview as a production authentication boundary.
