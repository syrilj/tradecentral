/**
 * Personal book shared by Desk, Flow, Options, and Market.
 * Persists in this browser only — not an account roster and not a signal.
 */
export const WATCHLIST_STORAGE_KEY = 'edge_custom_watchlist'
export const DEFAULT_WATCHLIST = ['NVDA', 'TSLA', 'AMD'] as const
export const WATCHLIST_MAX = 40

export function normalizeWatchSymbol(value: unknown): string {
  return String(value || '')
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9.-]/g, '')
    .slice(0, 10)
}

export function uniqueWatchlist(
  values: unknown,
  fallback: readonly string[] = DEFAULT_WATCHLIST,
): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const value of Array.isArray(values) ? values : []) {
    const symbol = normalizeWatchSymbol(value)
    if (!symbol || seen.has(symbol)) continue
    seen.add(symbol)
    out.push(symbol)
    if (out.length >= WATCHLIST_MAX) break
  }
  if (out.length) return out
  return [...fallback].map(normalizeWatchSymbol).filter(Boolean).slice(0, WATCHLIST_MAX)
}

export function loadWatchlist(
  storage: Pick<Storage, 'getItem'> | null | undefined = defaultStorage(),
): string[] {
  if (!storage) return [...DEFAULT_WATCHLIST]
  try {
    const raw = storage.getItem(WATCHLIST_STORAGE_KEY)
    if (!raw) return [...DEFAULT_WATCHLIST]
    return uniqueWatchlist(JSON.parse(raw))
  } catch {
    return [...DEFAULT_WATCHLIST]
  }
}

export function saveWatchlist(
  symbols: unknown,
  storage: Pick<Storage, 'setItem'> | null | undefined = defaultStorage(),
): string[] {
  const next = uniqueWatchlist(symbols, [])
  if (storage) {
    try {
      storage.setItem(WATCHLIST_STORAGE_KEY, JSON.stringify(next))
    } catch {
      // Private mode / quota must not break the desk.
    }
  }
  return next
}

export function toggleWatchlistSymbol(
  symbols: unknown,
  rawSymbol: unknown,
  storage: Pick<Storage, 'setItem'> | null | undefined = defaultStorage(),
): { symbols: string[]; added: boolean } {
  const current = uniqueWatchlist(symbols, [])
  const symbol = normalizeWatchSymbol(rawSymbol)
  if (!symbol) return { symbols: current, added: false }
  const exists = current.includes(symbol)
  const next = exists
    ? current.filter((item) => item !== symbol)
    : uniqueWatchlist([...current, symbol], [])
  return { symbols: saveWatchlist(next, storage), added: !exists }
}

export function watchlistHas(symbols: unknown, rawSymbol: unknown): boolean {
  const symbol = normalizeWatchSymbol(rawSymbol)
  return Boolean(symbol) && uniqueWatchlist(symbols, []).includes(symbol)
}

function defaultStorage(): Storage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}
