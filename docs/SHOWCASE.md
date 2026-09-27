# TradeCentral — selected technical highlights

## The workstation

These are captures from the running local app, using its actual SPY research state. The options source is marked stale and the decision engine abstains when too few independent lenses are ready; those states are part of the product's provenance and risk model.

![TradeCentral options positioning workspace](../dashboard/src/assets/showcase/options-positioning.png)

![TradeCentral decision workspace showing standby](../dashboard/src/assets/showcase/decision-live.png)

## Resume bullets

Resume-ready project bullets for technical portfolios and recruiter conversations:

- Built TradeCentral from scratch: a Vue 3/TypeScript and Python research workstation that joins options flow, dealer gamma exposure, market regimes, and model evidence into symbol-level decision support with source age visible on every critical readout.
- Engineered a point-in-time research and decision pipeline with typed provider adapters, walk-forward evaluation, preregistered gates, and shadow evidence; it abstains when quotes are stale, contracts are incomplete, or independent lenses disagree.
- Shipped a Cloudflare Workers preview with a Clerk-managed waitlist and owner-scoped Convex watchlists; added independent owner checks in the Python API and verified the frontend and edge behavior with 2,688 passing frontend tests and six Worker routing tests.

The system is for research and decision support; it does not route broker orders. The current Cloudflare preview uses Clerk development authentication, has no custom domain, and does not expose the research API. The source repository remains private pending an open-source release review and license. See the [README](../README.md) and [preview deployment notes](CLOUDFLARE_DEPLOYMENT.md) for current scope.
