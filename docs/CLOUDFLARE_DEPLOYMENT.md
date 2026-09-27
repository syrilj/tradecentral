# Preview and production launch: owner access and waitlist

## workers.dev preview

The connected accounts currently have a `tradecentral` Cloudflare Worker and
only a **development** TradeCentral Clerk instance. Clerk requires a domain
you control for a production instance; `workers.dev` is suitable here only
as a preview. The Clerk development instance is configured for native
Waitlist mode and has an existing owner account.
Its live development settings have smart CAPTCHA and a sign-in lockout enabled.

The preview hostname is a `workers.dev` URL kept in the untracked deploy
environment, not in this repository. Cloudflare Access makes `/`, `/waitlist`,
`/auth`, `/auth/*`, and `/assets/*` public. Private dashboard paths and
`/api/*` remain behind Access. The Worker also disables its API proxy, so even
an Access-approved request cannot reach the local research service. The preview
uses an owner-scoped Convex development deployment for small watchlist state.
That deployment URL stays in the untracked environment. This Access
configuration is account state; a Wrangler deployment alone does not recreate
it.

The Access application sends users denied by its identity or other access
rules to the public `/waitlist` page. A direct private URL still first shows
Cloudflare Access sign-in; the deny redirect applies after that decision.

The development Clerk instance has a `convex` JWT template with the
`aud: convex` claim. The Convex deployment sets its issuer to that Clerk
instance and `OWNER_CLERK_USER_ID` to the owner's exact development user ID.
An owner token was accepted by the read function; anonymous reads and writes
were denied. Use the production Clerk user ID and issuer on the separate
production deployment when a custom domain is available.

An untracked repo-root `.env.preview.local` should contain
`VITE_EDGE_AUTH_MODE=clerk`, a `https://<deployment>.convex.cloud` URL, and the
operator email in `VITE_EDGE_ALLOWED_EMAILS`. The untracked `.env` supplies the
Clerk publishable key. Run
`npm run build:preview` from `dashboard/`, then deploy with Wrangler. The
Worker API proxy remains disabled. The landing page and waitlist can be public,
but live research panels will show an unavailable API state. Do not use this
development Clerk instance as the final production authentication boundary.

## Current architecture

The Cloudflare Worker serves the Vue app and Clerk's waitlist. Its API proxy is
**disabled by default**; `/api/*` returns 503 without contacting the Python
research process or a data provider. Clerk authenticates the owner. The Python
API and Convex independently check the owner's Clerk user ID before serving
private data. A copied dashboard URL does not grant access to research data.

The Python process cannot run on Workers or Convex: it uses pandas, local
Parquet/artifacts, provider adapters, and threaded jobs. Convex stores only a
small owner watchlist. Do not put market data or provider keys in the browser,
Worker variables, or Convex client code.

## One-time account setup

1. In the **Clerk production instance**, choose **Waitlist** sign-up mode and
   invite the owner address from your private environment. Do not enable Clerk's paid identifier
   Allowlist feature. Complete the owner's sign-in and copy that account's
   Clerk user ID (`user_...`) from the Clerk Dashboard.
2. Configure a Convex audience (`aud: convex`) in the Clerk production
   instance, either with Clerk's Convex integration or a `convex` JWT template
   matching the preview client. Record the production Frontend API/issuer URL
   and publishable key.
3. Use the existing **Convex Free** `tradecentral` project. Set
   `CLERK_JWT_ISSUER_DOMAIN` to the production Clerk issuer and
   `OWNER_CLERK_USER_ID` to the new production owner ID on the **production
   Convex deployment**. From `dashboard/`, run `npx convex deploy`. Record its
   `https://...convex.cloud` URL. The development deployment already has the
   development issuer and owner ID and was verified with an owner token.
4. Add a domain you control to Cloudflare and use it for the Clerk production
   instance and the final app hostname. Configure Clerk's production allowed
   origins and redirect URLs for that hostname. Review the existing Cloudflare
   Access path exceptions when moving to the final hostname so public pages
   and their assets load while research routes stay protected.

Keep the production keys and user ID in private environment files or dashboard
secrets. The publishable key and Convex URL are public identifiers; the Clerk
secret key and Python JWT public key must be handled according to their roles.
No Clerk secret key is needed in the browser or Convex source.

## Build and publish static front door

Create an untracked repo-root `.env.production.local` containing:

```dotenv
VITE_EDGE_AUTH_MODE=clerk
VITE_CLERK_PUBLISHABLE_KEY=pk_live_...
VITE_CONVEX_URL=https://your-production-deployment.convex.cloud
VITE_EDGE_ALLOWED_EMAILS=owner@example.com
```

Then:

```bash
cd dashboard
npm ci
npm run build:public
cd ..
npx wrangler deploy -c cloudflare/wrangler.toml
```

`build:public` rejects local mode, a development Clerk key, or a missing Convex
URL. `cloudflare/wrangler.toml` keeps `API_PROXY_ENABLED=false`, so publication
does not expose expensive API endpoints. Confirm the public landing page and
waitlist, and a non-owner sign-in denied and sent to the waitlist. An
unauthenticated `/api/status` request is redirected by Cloudflare Access;
after Access, the disabled Worker API returns 503. Do not interpret a
successful static launch as a working research API.

## Optional live research API

Enable this only after the Python service passes the authenticated smoke tests.
Start it with the private values in `cloudflare/.env.cloudflare`:

```dotenv
EDGE_HOST=127.0.0.1
EDGE_AUTH_MODE=clerk
EDGE_PUBLIC_DEPLOYMENT=1
EDGE_REQUIRE_AUTH=1
EDGE_BACKGROUND_JOBS=0
EDGE_OWNER_USER_ID=user_...
CLERK_JWT_KEY=-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----
CLERK_AUTHORIZED_PARTIES=https://tradecentral.your-domain.example
EDGE_CORS_ORIGINS=https://tradecentral.your-domain.example
```

The server refuses to start in public mode without the Clerk public key,
authorized party, exact owner ID, or with local auth. Use a dedicated
Cloudflare Tunnel hostname for the loopback API; protect the tunnel hostname
itself as well, because it is a separate public route. Configure the Worker
with `API_PROXY_ENABLED=true`, `PUBLIC_ORIGIN` set to the exact Worker HTTPS
origin, and `API_UPSTREAM` set to the exact tunnel HTTPS origin. Never put an
API hostname in the committed `wrangler.toml` defaults.

Public mode disables the API's three unattended warm/sync jobs unless
`EDGE_BACKGROUND_JOBS=1` is explicitly set. The owner can still request live
research data; those requests can consume provider quota. This setting avoids
provider work merely because the server is running.

Before enabling the Worker proxy, verify all of these directly against the
tunnel and again through the Worker:

- Missing bearer token and another valid Clerk user both receive 401 before
  provider work begins.
- The owner receives data with a valid session token; malformed/expired tokens
  receive 401.
- POST from a foreign Origin receives 403; GET cannot start a scan.
- The browser renders missing/stale states when the API is offline.

## Cost boundaries

- Cloudflare Workers Free has a hard daily Worker request limit; static asset
  requests are free and unlimited. Keep static assets asset-first and `/api/*`
  Worker-first. See [Workers limits](https://developers.cloudflare.com/workers/platform/limits/)
  and [static asset billing](https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/).
- Clerk Hobby is free for this single owner. Native Waitlist mode is used;
  Clerk's identifier Allowlist is a paid feature. See [Clerk restrictions](https://clerk.com/docs/authentication/allowlist)
  and [pricing](https://clerk.com/pricing).
- Convex Free has hard resource caps. The only deployed functions read or write
  one owner watchlist, with at most 40 symbols and no polling. See [Convex Free
  limits](https://docs.convex.dev/production/state/limits) and
  [pricing FAQ](https://www.convex.dev/pricing/faq).
- Provider subscriptions and local compute are separate costs. Enabling a
  public Python API can consume provider quota even when Cloudflare, Clerk,
  and Convex remain within their free plans.
