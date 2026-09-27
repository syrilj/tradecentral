import { ConvexHttpClient } from 'convex/browser'
import { makeFunctionReference } from 'convex/server'
import { uniqueWatchlist } from './watchlist'

type TokenGetter = () => Promise<string | null>

const getWatchlist = makeFunctionReference<'query', Record<string, never>, string[] | null>(
  'watchlist:get',
)
const replaceWatchlist = makeFunctionReference<'mutation', { symbols: string[] }, string[]>(
  'watchlist:replace',
)

export function cloudWatchlistConfigured(): boolean {
  return Boolean(String(import.meta.env.VITE_CONVEX_URL ?? '').trim())
}

async function authenticatedClient(getToken: TokenGetter): Promise<ConvexHttpClient> {
  const url = String(import.meta.env.VITE_CONVEX_URL ?? '').trim()
  if (!/^https:\/\/[^/]+\.convex\.cloud$/.test(url)) {
    throw new Error('Convex deployment URL is not configured')
  }
  const token = await getToken()
  if (!token) throw new Error('Convex authentication is unavailable')
  const client = new ConvexHttpClient(url)
  client.setAuth(token)
  return client
}

/** Read one small, owner-only record on page entry. No subscription or polling. */
export async function loadCloudWatchlist(getToken: TokenGetter): Promise<string[] | null> {
  const client = await authenticatedClient(getToken)
  return client.query(getWatchlist, {})
}

export async function saveCloudWatchlist(symbols: string[], getToken: TokenGetter): Promise<void> {
  const client = await authenticatedClient(getToken)
  await client.mutation(replaceWatchlist, { symbols: uniqueWatchlist(symbols, []) })
}
