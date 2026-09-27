import { describe, expect, it } from 'vitest'
import type { MarketFlowPrint } from '@/api'
import { collectWatchlistAlerts, printAlertKind } from '@/flowAlerts'

function print(over: Partial<MarketFlowPrint> = {}): MarketFlowPrint {
  return {
    timestamp: '2026-08-14T15:00:00Z',
    symbol: 'NVDA',
    right: 'call',
    premium: 80_000,
    volume: 20,
    contracts: 20,
    strike: 150,
    expiry: '2026-09-18',
    aggressor: null,
    signed_premium: null,
    premium_estimated: false,
    anomaly_flags: [],
    anomaly_score: 0,
    premium_percentile: 0.5,
    is_unusual: false,
    is_sweep: false,
    ...over,
  }
}

describe('watchlist Unusual/Sweep alerts', () => {
  it('fires only for pinned names with Unusual or Sweep tags', () => {
    const alerts = collectWatchlistAlerts({
      watchlist: ['NVDA', 'AMD'],
      prints: [
        print({ symbol: 'NVDA', is_unusual: true, timestamp: '2026-08-14T15:01:00Z' }),
        print({
          symbol: 'AMD',
          is_sweep: true,
          trade_class: 'sweep',
          timestamp: '2026-08-14T15:02:00Z',
        }),
        print({ symbol: 'TSLA', is_unusual: true, timestamp: '2026-08-14T15:03:00Z' }),
        print({ symbol: 'NVDA', timestamp: '2026-08-14T15:04:00Z' }),
      ],
    })
    expect(alerts.map((row) => `${row.symbol}:${row.kind}`)).toEqual(['NVDA:unusual', 'AMD:sweep'])
  })

  it('skips already-seen keys and can restrict to the new-print set', () => {
    const hit = print({ symbol: 'NVDA', is_unusual: true, is_sweep: true })
    const first = collectWatchlistAlerts({ watchlist: ['NVDA'], prints: [hit] })
    expect(first[0]?.kind).toBe('both')
    const skipped = collectWatchlistAlerts({
      watchlist: ['NVDA'],
      prints: [hit],
      seenKeys: first.map((row) => row.key),
    })
    expect(skipped).toEqual([])
    const notNew = collectWatchlistAlerts({
      watchlist: ['NVDA'],
      prints: [hit],
      newPrintKeys: ['other-key'],
    })
    expect(notNew).toEqual([])
  })

  it('classifies combined unusual+sweep as both', () => {
    expect(printAlertKind(print({ is_unusual: true, is_sweep: true }))).toBe('both')
    expect(printAlertKind(print({ presets: ['unusual'] }))).toBe('unusual')
    expect(printAlertKind(print({ trade_class: 'sweep' }))).toBe('sweep')
    expect(printAlertKind(print())).toBeNull()
  })
})
