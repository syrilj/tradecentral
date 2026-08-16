import { describe, expect, it } from 'vitest'
import {
  asStrategy,
  bookAllocation,
  buildPayoffChart,
  calculateStrategyPoP,
  computeRiskNeutralModel,
  computeTargetRiskMetrics,
  findBreakevens,
  netDebit,
  nextLegId,
  probTerminalAbove,
  probTerminalBelow,
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

  it('evaluates risk-neutral lognormal model and 1σ/2σ expected move boundaries', () => {
    const model = computeRiskNeutralModel({
      spot: 100,
      dteDays: 30,
      volPct: 30,
    })
    expect(model).not.toBeNull()
    expect(model!.expectedMove).toBeCloseTo(100 * 0.3 * Math.sqrt(30 / 365), 3)
    expect(model!.expectedLow).toBeCloseTo(100 - model!.expectedMove, 3)
    expect(model!.expectedHigh).toBeCloseTo(100 + model!.expectedMove, 3)
    expect(model!.twoSigmaLow).toBeCloseTo(100 - 2 * model!.expectedMove, 3)
    expect(model!.twoSigmaHigh).toBeCloseTo(100 + 2 * model!.expectedMove, 3)
    expect(model!.low).toBeLessThan(model!.expectedLow)
    expect(model!.high).toBeGreaterThan(model!.expectedHigh)
  })

  it('computes terminal price risk-neutral probabilities above, below, and target risk metrics', () => {
    // Spot = 100, Strike = 100 -> ATM is roughly 50%
    const pAtmAbove = probTerminalAbove(100, 100, 30, 30)
    expect(pAtmAbove).toBeGreaterThan(0.40)
    expect(pAtmAbove).toBeLessThan(0.60)

    const pAtmBelow = probTerminalBelow(100, 100, 30, 30)
    expect(pAtmAbove + pAtmBelow).toBeCloseTo(1.0, 5)

    // OTM Strike = 120 -> Prob above is significantly lower
    const pOtmAbove = probTerminalAbove(120, 100, 30, 30)
    expect(pOtmAbove).toBeLessThan(0.20)

    // Target metrics
    const target = computeTargetRiskMetrics({
      targetPrice: 110,
      spot: 100,
      dteDays: 30,
      volPct: 30,
      callWall: 115,
      putWall: 95,
    })
    expect(target).not.toBeNull()
    expect(target!.chgPct).toBeCloseTo(10.0, 2)
    expect(target!.zScore).toBeGreaterThan(0)
    expect(target!.probAbove).toBeGreaterThan(0)
    expect(target!.probAbove).toBeLessThan(0.5)
    expect(target!.probBetweenWalls).toBeGreaterThan(0)
  })

  it('calculates exact Strategy Probability of Profit (PoP) for directional and multi-leg books', () => {
    // 1. Long Call at 100 for $5 debit -> Breakeven 105 -> PoP is P(S > 105)
    const longCallPoP = calculateStrategyPoP({
      legs: [{ id: '1', right: 'call', strike: 100, quantity: 1, premium: 5 }],
      spot: 100,
      dteDays: 30,
      volPct: 30,
    })
    expect(longCallPoP.pop).toBeGreaterThan(0.20)
    expect(longCallPoP.pop).toBeLessThan(0.50)
    expect(longCallPoP.breakevens.length).toBeGreaterThanOrEqual(1)
    expect(longCallPoP.profitZoneDesc).toContain('Profitable above')

    // 2. Bull Put Spread (Credit spread collecting premium -> high PoP)
    const bullPutPoP = calculateStrategyPoP({
      legs: [
        { id: '1', right: 'put', strike: 100, quantity: -1, premium: 4 },
        { id: '2', right: 'put', strike: 95, quantity: 1, premium: 1.5 },
      ],
      spot: 100,
      dteDays: 30,
      volPct: 30,
    })
    expect(bullPutPoP.pop).toBeGreaterThan(0.55)
    expect(bullPutPoP.profitZoneDesc).toContain('Profitable')

    // 3. Iron Condor (Profitable between wings)
    const condorPoP = calculateStrategyPoP({
      legs: [
        { id: '1', right: 'put', strike: 90, quantity: 1, premium: 1 },
        { id: '2', right: 'put', strike: 95, quantity: -1, premium: 2.5 },
        { id: '3', right: 'call', strike: 105, quantity: -1, premium: 2.5 },
        { id: '4', right: 'call', strike: 110, quantity: 1, premium: 1 },
      ],
      spot: 100,
      dteDays: 30,
      volPct: 30,
    })
    expect(condorPoP.pop).toBeGreaterThan(0.40)
    expect(condorPoP.profitZoneDesc).toContain('Profitable')
  })
})
