import { describe, expect, it } from 'vitest'
import {
  DEFAULT_WATCHLIST,
  WATCHLIST_MAX,
  loadWatchlist,
  normalizeWatchSymbol,
  saveWatchlist,
  toggleWatchlistSymbol,
  uniqueWatchlist,
  watchlistHas,
} from '@/watchlist'

function memoryStorage(seed: string | null = null) {
  const bag = new Map<string, string>()
  if (seed != null) bag.set('edge_custom_watchlist', seed)
  return {
    getItem(key: string) {
      return bag.has(key) ? bag.get(key)! : null
    },
    setItem(key: string, value: string) {
      bag.set(key, value)
    },
  }
}

describe('shared personal watchlist', () => {
  it('normalizes and dedupes symbols without inventing names', () => {
    expect(normalizeWatchSymbol(' nvda ')).toBe('NVDA')
    expect(uniqueWatchlist(['aapl', 'AAPL', ' msft ', '', 'GOOG1'])).toEqual(['AAPL', 'MSFT', 'GOOG1'])
    expect(uniqueWatchlist([])).toEqual([...DEFAULT_WATCHLIST])
  })

  it('caps the book and persists through the same storage key Desk already uses', () => {
    const storage = memoryStorage()
    const many = Array.from({ length: 50 }, (_, i) => `S${i}`)
    const saved = saveWatchlist(many, storage)
    expect(saved).toHaveLength(WATCHLIST_MAX)
    expect(loadWatchlist(storage)).toEqual(saved)
  })

  it('toggles membership and reports whether the name is on the book', () => {
    const storage = memoryStorage()
    const start = loadWatchlist(storage)
    const added = toggleWatchlistSymbol(start, 'HOOD', storage)
    expect(added.added).toBe(true)
    expect(watchlistHas(added.symbols, 'hood')).toBe(true)
    const removed = toggleWatchlistSymbol(added.symbols, 'HOOD', storage)
    expect(removed.added).toBe(false)
    expect(watchlistHas(removed.symbols, 'HOOD')).toBe(false)
  })
})
