import type { AuthConfig } from 'convex/server'

// Clerk's Convex integration issues an audience-scoped token named "convex".
// Set this separately on the production Convex deployment.
export default {
  providers: [
    {
      domain: process.env.CLERK_JWT_ISSUER_DOMAIN!,
      applicationID: 'convex',
    },
  ],
} satisfies AuthConfig
