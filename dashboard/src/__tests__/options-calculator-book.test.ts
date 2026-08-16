import { describe, expect, it } from 'vitest'
import {
  asStrategy,
  bookAllocation,
  buildPayoffChart,
  findBreakevens,
  netDebit,
  nextLegId,
  samplePnlRows,
  seedBook,
  usableLegs,
} from '@/optionsCalculator'

describe('options book helpers', () => {
  it('seeds a long call, long put, or two-leg straddle', () => {
    expect(seedBook({ strategy: 'long_call', strike: 105, premium: 4 })).toEqual([
      { id: 'leg-1', right: 'call', strike: 105, quantity: 1, premium: 4 },
    ])
    expect(seedBook({ strategy: 'long_put', strike: 95, premium: 3, quantity: 2 })).toEqual([
      { id: 'leg-1', right: 'put', strike: 95, quantity: 2, premium: 3 },
    ])
    expect(seedBook({ strategy: 'long_straddle', strike: 100, premium: 5 })).toHaveLength(2)
  })

  it('maps query aliases and drops unusable legs before the API call', () => {
    expect(asStrategy('put')).toBe('long_put')
    expect(asStrategy('straddle')).toBe('long_straddle')
    expect(usableLegs([
      { id: 'leg-1', right: 'call', strike: 100, quantity: 1, premium: 2 },
      { id: 'leg-2', right: 'put', strike: 0, quantity: 1, premium: 2 },
      { id: 'leg-3', right: 'put', strike: 90, quantity: 0, premium: 2 },
    ])).toEqual([{ right: 'call', strike: 100, quantity: 1, premium: 2 }])
  })

  it('nets debit as premium × 100 × signed quantity', () => {
    expect(netDebit([
      { id: 'a', right: 'call', strike: 100, quantity: 1, premium: 5 },
      { id: 'b', right: 'call', strike: 110, quantity: -1, premium: 2 },
    ])).toBe(300)
  })

  it('finds expiry breakevens where P/L crosses zero and samples the table', () => {
    const series = [
      { spot: 90, pnl: -400 },
      { spot: 100, pnl: -400 },
      { spot: 104, pnl: 0 },
      { spot: 110, pnl: 600 },
    ]
    expect(findBreakevens(series)).toEqual([104])
    const rows = samplePnlRows(series, [100])
    expect(rows.some((row) => row.spot === 100)).toBe(true)
    expect(rows[0].spot).toBeLessThan(rows[rows.length - 1].spot)
  })

  it('allocates the next leg id without colliding', () => {
    expect(nextLegId([{ id: 'leg-1' }, { id: 'leg-4' }])).toBe('leg-5')
  })

  it('splits book cash into call/put mix and long/short notional', () => {
    const mix = bookAllocation([
      { id: 'a', right: 'call', strike: 100, quantity: 1, premium: 5 },
      { id: 'b', right: 'put', strike: 100, quantity: 1, premium: 3 },
      { id: 'c', right: 'call', strike: 110, quantity: -1, premium: 2 },
    ])
    expect(mix.callDebit).toBe(300)
    expect(mix.putDebit).toBe(300)
    expect(mix.longNotional).toBe(800)
    expect(mix.shortCredit).toBe(200)
    expect(mix.net).toBe(600)
    expect(mix.callShare).toBeCloseTo(0.5)
    expect(mix.putShare).toBeCloseTo(0.5)
  })

  it('builds a signed payoff chart with zero, spot, strikes, and breakevens', () => {
    const series = [
      { spot: 90, pnl: -400 },
      { spot: 100, pnl: -400 },
      { spot: 104, pnl: 0 },
      { spot: 110, pnl: 600 },
    ]
    const chart = buildPayoffChart({
      series,
      spot: 100,
      strikes: [{ strike: 104, right: 'call' }],
      width: 640,
      height: 220,
    })
    expect(chart).not.toBeNull()
    expect(chart?.line.startsWith('M')).toBe(true)
    expect(chart?.profitArea).toContain('Z')
    expect(chart?.lossArea).toContain('Z')
    expect(chart?.xTicks.length).toBeGreaterThan(1)
    expect(chart?.yTicks.some((tick) => tick.label === 0)).toBe(true)
    expect(chart?.strikes[0]?.strike).toBe(104)
    expect(chart?.breakevens[0]?.spot).toBe(104)
    expect(chart?.maxProfit).toBe(600)
    expect(chart?.maxLoss).toBe(-400)
    expect(chart?.spotX).toBeGreaterThan(chart!.pad.l)
    expect(chart?.spotX).toBeLessThan(chart!.width - chart!.pad.r)
  })
})
