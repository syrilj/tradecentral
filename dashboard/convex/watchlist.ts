import { mutationGeneric, queryGeneric } from 'convex/server'
import { v } from 'convex/values'

const MAX_SYMBOLS = 40
const SYMBOL = /^[A-Z0-9.-]{1,10}$/

async function ownerId(ctx: { auth: { getUserIdentity: () => Promise<{ subject: string } | null> } }) {
  const identity = await ctx.auth.getUserIdentity()
  const configured = process.env.OWNER_CLERK_USER_ID?.trim()
  if (!configured || !identity || identity.subject !== configured) {
    throw new Error('Not authorized')
  }
  return configured
}

export const get = queryGeneric({
  args: {},
  handler: async (ctx) => {
    const owner = await ownerId(ctx)
    const record = await ctx.db
      .query('watchlists')
      .withIndex('by_owner', (q) => q.eq('ownerId', owner))
      .unique()
    return record?.symbols ?? null
  },
})

export const replace = mutationGeneric({
  args: { symbols: v.array(v.string()) },
  handler: async (ctx, { symbols }) => {
    const owner = await ownerId(ctx)
    if (symbols.length > MAX_SYMBOLS || new Set(symbols).size !== symbols.length ||
        symbols.some((symbol) => !SYMBOL.test(symbol))) {
      throw new Error('Invalid watchlist')
    }
    const existing = await ctx.db
      .query('watchlists')
      .withIndex('by_owner', (q) => q.eq('ownerId', owner))
      .unique()
    if (existing) {
      await ctx.db.patch(existing._id, { symbols, updatedAt: Date.now() })
    } else {
      await ctx.db.insert('watchlists', { ownerId: owner, symbols, updatedAt: Date.now() })
    }
    return symbols
  },
})
