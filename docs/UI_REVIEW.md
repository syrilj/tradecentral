# Public UI review — September 2026

TradeCentral's public preview now introduces the actual research workstation before asking for access. The private application routes and research logic remain intact.

## Five changes with the most impact

1. **Show the product.** The landing hero defaults to an actual SPY options-positioning capture, with a full-size link and the interactive Monte Carlo model as a second tab. The capture retains the app's stale-source warning and measured risk state.
2. **Make the waitlist real.** The access panel uses Clerk's managed Waitlist component. It shows an explicit unavailable state when Clerk is not configured and never fabricates a queued request or local ticket.
3. **Give the request a clear path.** Editorial heading, three-step explanation, focused benefits, a real decision-workspace capture on desktop, and one primary action explain what the preview is and what happens after a request.
4. **Preserve the public/private boundary.** Public routes reuse shell resources and do not start market-data polling. Private screens, the Python API, and Convex each enforce their own owner boundary.
5. **Make waiting states legible.** Decision and regime skeletons announce progress to assistive technology, retain stable geometry, and disable nonessential motion when reduced motion is requested.

## Before and after

| Before | After |
| --- | --- |
| Structural product illustration led the hero. | A captured workstation view leads, with the model simulation available on demand. |
| A simulated local waitlist could appear to accept a request. | Clerk submits the request; unavailable sessions say explicitly that nothing was submitted. |
| Public landing could start a market-clock API poll. | Public landing consumes shell state without initiating a request. |
| Loading placeholders had weaker status announcements. | Skeletons expose progress and support reduced motion. |

## Visual system and verification

The public surfaces use scoped CSS variables in `dashboard/src/views/AuthView.vue` and `dashboard/src/views/LandingView.vue`: warm paper and near-black ink, one orange accent, Inter Tight headings, Inter body text, hairline rules, and compact focus rings. This retains the darker instrument interface inside the private workspaces. The live 1440px preview and waitlist were visually checked; the build, 2,702 frontend tests, 54 API security tests, and six Worker routing tests passed.

The current workers.dev preview uses Clerk development mode. Its research API is disabled until an approved owner-only connection is available.

## Private workstation polish

The five biggest wins from the private-workspace audit were:

1. Give Flow, Setups, Regime, Options, and Charm a readable first heading and explanatory copy, while keeping dense tables compact.
2. Keep the mobile workspace rail horizontally scrollable so all primary tabs remain reachable and labels do not collide.
3. Let the Vanna strike chart and expiry table scroll within their own regions on phones, with keyboard focus visible.
4. Make Setups summary filters keyboard-operable and expose the selected state in Setups and Regime controls.
5. Fix Market's stale search and comparison responses, keyboard result selection, and invalid tab URLs; contain its ticker and chart controls at narrow widths.

| Before | After |
| --- | --- |
| Dense chrome gave every line similar weight. | Symbol, page identity, and current task lead; supporting data retains compact instrument styling. |
| Narrow viewports could extend beyond the workspace. | The seven research views were checked at 375, 768, 1024, and 1440px; the Market and Options overflow found in that pass was corrected. |
| Late Market requests could replace the latest selection. | Search and comparison responses are sequenced to the active input and basket. |

The desk continues to use `dashboard/src/styles/tokens.css`: near-black surfaces, legible neutral ink, one phosphor accent, semantic call/put color only for signed market data, `--t-view-title` for workspace headings, and `--t-reading` for explanatory text. Motion remains restrained and follows the existing reduced-motion rules. Vue components and the existing router remain in place; introducing React-only primitives into this Vue application would change the product stack and risk its behavior.
