import { describe, expect, it } from 'vitest'
import type { MarketFlowPrint } from '@/api'
import {
  alertPathPoints,
  buildPowerAlerts,
  fiveDayTracker,
  isCheapContract,
  isPowerAlertCandidate,
  parseFlowSymbolQuery,
  powerAlertLean,
  scorePowerAlert,
  signedStreak,
  symbolPassesQuery,
} from '@/flowPowerAlerts'

function print(over: Partial<MarketFlowPrint> = {}): MarketFlowPrint {
  return {
    timestamp: '2026-08-21T15:00:00Z',
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

describe('Cheddar-style power alerts (no dark pool, no invented side)', () => {
  it('does not treat unsigned call/put identity as bullish or bearish', () => {
    expect(powerAlertLean(print({ right: 'call' }))).toBe('call')
    expect(powerAlertLean(print({ right: 'put' }))).toBe('put')
    expect(powerAlertLean(print({ right: 'call', bias: 'bullish', aggressor: 'buy' }))).toBe(
      'signed-bullish',
    )
    expect(powerAlertLean(print({ right: 'put', aggressor: 'sell' }))).toBe('signed-bearish')
  })

  it('flags cheap contracts only when the fill is between $0.20 and $0.70', () => {
    expect(isCheapContract(0.2)).toBe(true)
    expect(isCheapContract(0.45)).toBe(true)
    expect(isCheapContract(0.7)).toBe(true)
    expect(isCheapContract(0.19)).toBe(false)
    expect(isCheapContract(0.71)).toBe(false)
    expect(isCheapContract(null)).toBe(false)
    expect(isCheapContract(undefined)).toBe(false)
  })

  it('requires a notable print — ordinary tape is not an alert', () => {
    expect(isPowerAlertCandidate(print())).toBe(false)
    expect(isPowerAlertCandidate(print({ is_unusual: true }))).toBe(true)
    expect(isPowerAlertCandidate(print({ is_sweep: true, trade_class: 'sweep' }))).toBe(true)
    expect(isPowerAlertCandidate(print({ premium: 250_000 }))).toBe(true)
    expect(isPowerAlertCandidate(print({ contracts: 5000, open_interest: 400 }))).toBe(true)
  })

  it('ranks size, unusual, and sweep above a quiet print', () => {
    const quiet = scorePowerAlert(print({ premium: 25_000 }))
    const unusual = scorePowerAlert(print({ premium: 25_000, is_unusual: true }))
    const whaleSweep = scorePowerAlert(
      print({
        premium: 1_200_000,
        is_unusual: true,
        is_sweep: true,
        trade_class: 'sweep',
        aggressor: 'buy',
      }),
    )
    expect(unusual).toBeGreaterThan(quiet)
    expect(whaleSweep).toBeGreaterThan(unusual)
    expect(whaleSweep).toBeLessThanOrEqual(100)
  })

  it('tracks first-print spot versus current spot and leaves missing option P/L missing', () => {
    const first = print({
      timestamp: '2026-08-21T14:00:00Z',
      is_unusual: true,
      underlying_price: 100,
      price: null,
      premium: 120_000,
    })
    const laterTape = print({
      timestamp: '2026-08-21T15:30:00Z',
      is_unusual: true,
      strike: 160,
      underlying_price: 104,
      price: 0.55,
      premium: 90_000,
    })
    const built = buildPowerAlerts({
      prints: [first],
      now: new Date('2026-08-21T16:00:00Z'),
    })
    const replay = buildPowerAlerts({
      prints: [{ ...first, underlying_price: 104 }, laterTape],
      history: built.history,
      now: new Date('2026-08-21T16:00:00Z'),
    })
    const alert = replay.alerts.find((row) => row.key === built.alerts[0]?.key)
    expect(alert?.firstSpot).toBe(100)
    expect(alert?.currentSpot).toBe(104)
    expect(alert?.spotMovePct).toBeCloseTo(0.04, 6)
    expect(alert?.premiumMovePct).toBeNull()
  })

  it('builds a 5-day count tracker without inventing quiet-day spots', () => {
    const history = [
      {
        key: 'a',
        symbol: 'NVDA',
        sessionDate: '2026-08-19',
        timestamp: '2026-08-19T14:00:00Z',
        firstSpot: 100,
        firstPrice: 0.5,
        right: 'call',
        strike: 150,
        expiry: '2026-09-18',
        premium: 80_000,
        strength: 60,
        lean: 'call' as const,
      },
      {
        key: 'b',
        symbol: 'NVDA',
        sessionDate: '2026-08-21',
        timestamp: '2026-08-21T14:00:00Z',
        firstSpot: 103,
        firstPrice: 0.55,
        right: 'call',
        strike: 150,
        expiry: '2026-09-18',
        premium: 90_000,
        strength: 62,
        lean: 'signed-bullish' as const,
      },
    ]
    const tracker = fiveDayTracker({
      symbol: 'NVDA',
      history,
      currentSpot: 108,
      now: new Date('2026-08-21T20:00:00Z'),
    })
    expect(tracker.days).toHaveLength(5)
    expect(tracker.days.map((day) => day.date)).toEqual([
      '2026-08-17',
      '2026-08-18',
      '2026-08-19',
      '2026-08-20',
      '2026-08-21',
    ])
    expect(tracker.days.find((day) => day.date === '2026-08-17')?.count).toBe(0)
    expect(tracker.days.find((day) => day.date === '2026-08-17')?.firstSpot).toBeNull()
    expect(tracker.days.find((day) => day.date === '2026-08-19')?.count).toBe(1)
    expect(tracker.totalAlerts).toBe(2)
    expect(tracker.spotMovePct).toBeCloseTo(0.08, 6)
  })

  it('reports consecutive signed leans and ignores call/put identity streaks', () => {
    const signed = [
      { lean: 'signed-bullish' as const, key: '1' },
      { lean: 'signed-bullish' as const, key: '2' },
      { lean: 'signed-bullish' as const, key: '3' },
    ].map((row, index) => ({
      key: row.key,
      symbol: 'AMD',
      sessionDate: '2026-08-21',
      timestamp: `2026-08-21T14:0${index}:00Z`,
      firstSpot: 120,
      firstPrice: 1.2,
      right: 'call',
      strike: 130,
      expiry: '2026-09-18',
      premium: 200_000,
      strength: 70,
      lean: row.lean,
    }))
    expect(signedStreak(signed, 'AMD')).toEqual({ lean: 'signed-bullish', count: 3 })
    const identity = signed.map((row) => ({ ...row, lean: 'call' as const }))
    expect(signedStreak(identity, 'AMD')).toBeNull()
  })

  it('parses Cheddar-style -TICKER exclusions without dropping the rest of the tape', () => {
    const query = parseFlowSymbolQuery('NVDA -SPY -QQQ')
    expect(query.includes).toEqual(['NVDA'])
    expect(query.excludes).toEqual(['SPY', 'QQQ'])
    expect(symbolPassesQuery('NVDA', query, [])).toBe(true)
    expect(symbolPassesQuery('SPY', query, [])).toBe(false)
    expect(symbolPassesQuery('AMD', query, ['AMD'])).toBe(false)
    expect(symbolPassesQuery('AMD', parseFlowSymbolQuery(''), ['SPY'])).toBe(true)
  })

  it('draws an underlying path only from measured spots', () => {
    const path = alertPathPoints(
      [
        print({ timestamp: '2026-08-21T14:00:00Z', underlying_price: 100 }),
        print({ timestamp: '2026-08-21T14:05:00Z', underlying_price: null }),
        print({ timestamp: '2026-08-21T14:10:00Z', underlying_price: 101.5 }),
      ],
      'NVDA',
    )
    expect(path.map((point) => point.y)).toEqual([100, 101.5])
  })
})
