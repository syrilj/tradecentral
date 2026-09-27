import { defineSchema, defineTable } from 'convex/server'
import { v } from 'convex/values'

// Only small operator state belongs here. Market data and model artifacts stay
// with the Python research stack, so anonymous traffic cannot create provider
// calls or large database writes.
export default defineSchema({
  watchlists: defineTable({
    ownerId: v.string(),
    symbols: v.array(v.string()),
    updatedAt: v.number(),
  }).index('by_owner', ['ownerId']),
})
