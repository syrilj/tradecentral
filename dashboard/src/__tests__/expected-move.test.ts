import { describe, expect, it } from 'vitest'
import {
  computeRuleOf16ExpectedMove,
  assessMoveExcursion,
  assessWallAlignment,
} from '@/expectedMove'
import { tickerSector, tickerSectorEtf, tickerSectorCode } from '@/tickerIdentity'

describe('Rule of 16 Expected Move Engine', () => {
  it('computes 1D Expected Move using the Rule of 16 formula: Spot * (IV / 16)', () => {
    const spot = 500
    const iv = 0.16 // 16% annualized IV -> 1% daily move
    const res = computeRuleOf16ExpectedMove(spot, iv)

    expect(res).not.toBeNull()
    expect(res!.spot).toBe(500)
    expect(res!.ivAnnualPct).toBeCloseTo(16.0, 1)
    expect(res!.em1dDollars).toBeCloseTo(5.0, 2) // 500 * (0.16 / 16) = $5.00
    expect(res!.em1dPct).toBeCloseTo(1.0, 2) // 1.0%
    expect(res!.em1dLow).toBeCloseTo(495.0, 2)
    expect(res!.em1dHigh).toBeCloseTo(505.0, 2)
  })

  it('computes 1W Expected Move using sqrt(5/252) scaling', () => {
    const spot = 100
    const iv = 0.32 // 32% annualized IV
    const res = computeRuleOf16ExpectedMove(spot, iv)

    expect(res).not.toBeNull()
    expect(res!.em1dDollars).toBeCloseTo(2.0, 2) // 100 * (0.32 / 16) = $2.00
    // 1-Week: Spot * IV * sqrt(5/252) ≈ 100 * 0.32 * 0.14086 ≈ 4.51
    expect(res!.em1wDollars).toBeGreaterThan(res!.em1dDollars)
    expect(res!.em1wLow).toBeLessThan(res!.em1dLow)
    expect(res!.em1wHigh).toBeGreaterThan(res!.em1dHigh)
  })

  it('computes 1M Expected Move using 1/sqrt(12) scaling', () => {
    const spot = 200
    const iv = 0.2
    const res = computeRuleOf16ExpectedMove(spot, iv)

    expect(res).not.toBeNull()
    expect(res!.em1mDollars).toBeGreaterThan(res!.em1wDollars)
    expect(res!.em1mLow).toBeCloseTo(200 - 200 * (0.2 / Math.sqrt(12)), 1)
  })

  it('falls back to VIX reference when ticker IV is missing', () => {
    const spot = 580
    const vix = 20.0 // VIX = 20 -> 20/16 = 1.25% daily move
    const res = computeRuleOf16ExpectedMove(spot, null, vix)

    expect(res).not.toBeNull()
    expect(res!.em1dPct).toBeCloseTo(1.25, 2)
    expect(res!.em1dDollars).toBeCloseTo(580 * 0.0125, 2)
  })

  it('returns null for zero or negative spots', () => {
    expect(computeRuleOf16ExpectedMove(0, 0.2)).toBeNull()
    expect(computeRuleOf16ExpectedMove(-100, 0.2)).toBeNull()
    expect(computeRuleOf16ExpectedMove(null, 0.2)).toBeNull()
  })
})

describe('Move Excursion Assessment', () => {
  it('identifies moves within 1σ as normal consolidation', () => {
    const assessment = assessMoveExcursion(2.0, 5.0) // 0.4x EM
    expect(assessment.status).toBe('within_normal')
    expect(assessment.ratio).toBeCloseTo(0.4, 2)
    expect(assessment.label).toContain('40% of 1D EM')
  })

  it('identifies moves between 0.8x and 1.2x as testing the 1σ boundary', () => {
    const assessment = assessMoveExcursion(5.0, 5.0) // 1.0x EM
    expect(assessment.status).toBe('expansion')
    expect(assessment.label).toContain('Testing 1σ Boundary')
  })

  it('identifies moves exceeding 1.2x as abnormal volatility breakout', () => {
    const assessment = assessMoveExcursion(8.5, 5.0) // 1.7x EM
    expect(assessment.status).toBe('abnormal_breakout')
    expect(assessment.label).toContain('Abnormal Volatility Breakout')
  })
})

describe('Gamma Wall Spatial Alignment with Expected Move', () => {
  it('correctly detects when Call Wall and Put Wall sit inside the 1D Expected Move corridor', () => {
    const spot = 500
    const em1d = 10 // Corridor: [490, 510]
    const callWall = 508 // inside
    const putWall = 492 // inside

    const spatial = assessWallAlignment(callWall, putWall, spot, em1d)
    expect(spatial.callWallInside1d).toBe(true)
    expect(spatial.putWallInside1d).toBe(true)
    expect(spatial.callWallDistEmRatio).toBeCloseTo(0.8, 2)
    expect(spatial.putWallDistEmRatio).toBeCloseTo(0.8, 2)
  })

  it('correctly detects when Call Wall sits outside the 1D Expected Move corridor', () => {
    const spot = 500
    const em1d = 10 // Corridor: [490, 510]
    const callWall = 525 // outside (2.5x EM)
    const putWall = 480 // outside (2.0x EM)

    const spatial = assessWallAlignment(callWall, putWall, spot, em1d)
    expect(spatial.callWallInside1d).toBe(false)
    expect(spatial.putWallInside1d).toBe(false)
    expect(spatial.callWallDistEmRatio).toBeCloseTo(2.5, 2)
  })
})

describe('Sector Mapping & ETF Pair Identity', () => {
  it('maps equities to their appropriate sector ETF', () => {
    expect(tickerSector('AAPL')).toBe('Technology')
    expect(tickerSectorEtf('AAPL')).toBe('XLK')
    expect(tickerSectorCode('AAPL')).toBe('Tech')

    expect(tickerSector('JPM')).toBe('Financials')
    expect(tickerSectorEtf('JPM')).toBe('XLF')
    expect(tickerSectorCode('JPM')).toBe('Fin')

    expect(tickerSector('XOM')).toBe('Energy')
    expect(tickerSectorEtf('XOM')).toBe('XLE')
    expect(tickerSectorCode('XOM')).toBe('Energy')

    expect(tickerSector('AMZN')).toBe('Consumer Discretionary')
    expect(tickerSectorEtf('AMZN')).toBe('XLY')

    expect(tickerSector('GOOGL')).toBe('Communication')
    expect(tickerSectorEtf('GOOGL')).toBe('XLC')
  })

  it('handles index ETFs idempotently', () => {
    expect(tickerSectorEtf('SPY')).toBe('SPY')
    expect(tickerSectorEtf('QQQ')).toBe('QQQ')
    expect(tickerSectorEtf('IWM')).toBe('IWM')
    expect(tickerSectorEtf('XLK')).toBe('XLK')
  })
})
