import { describe, expect, it } from 'vitest'
import { buildDecisionPriceContext } from '../decisionPriceContext'

describe('decision price context', () => {
  it('prefers the live quote and locates price inside the measured value area', () => {
    const context = buildDecisionPriceContext({
      symbol: 'SPCX',
      quote: {
        symbol: 'SPCX',
        last: 54.25,
        prev_close: 53.8,
        chg_1d_pct: 0.84,
        asof: '2026-09-21T15:32:50Z',
        source: 'polygon',
        quality: 'live',
      },
      options: null,
      vpa: {
        market_phase: 'Accumulation',
        dominant_sentiment: 'Bullish',
        confidence_score: 0.7,
        effort_vs_result_verdict: 'VALIDATION',
        forensic_breakdown: {} as never,
        primary_scenario: {} as never,
        alternative_scenarios: [],
        trade_execution_guide: {} as never,
        levels: [
          { price: 52.8, kind: 'support', strength: 0.8, source: 'pivot cluster' },
          { price: 55.1, kind: 'resistance', strength: 0.7, source: 'pivot cluster' },
        ],
        vap: { value_area_low: 53.5, value_area_high: 55, poc: 54.1 },
      },
    })

    expect(context.spot).toBe(54.25)
    expect(context.spotSource).toBe('polygon quote')
    expect(context.status).toBe('ready')
    expect(context.valueArea?.location).toBe('inside')
    expect(context.nearestBelow?.label).toBe('POINT OF CONTROL')
    expect(context.nearestAbove?.label).toBe('VALUE AREA HIGH')
    expect(context.summary).toContain('inside the measured value area')
  })

  it('falls back to the VPA close without fabricating absent levels', () => {
    const context = buildDecisionPriceContext({
      symbol: 'SPCX',
      quote: null,
      options: null,
      vpa: {
        timeframe: '1h',
        market_phase: 'Markdown',
        dominant_sentiment: 'Bearish',
        confidence_score: 0.6,
        effort_vs_result_verdict: 'MIXED',
        forensic_breakdown: {} as never,
        primary_scenario: {} as never,
        alternative_scenarios: [],
        trade_execution_guide: {} as never,
        bars: [{ d: '2026-09-21T15:00:00Z', o: 53, h: 54, l: 52.9, c: 53.4, v: 100 }],
      },
    })

    expect(context.spot).toBe(53.4)
    expect(context.spotSource).toBe('1h close')
    expect(context.status).toBe('partial')
    expect(context.nearestAbove).toBeNull()
    expect(context.nearestBelow).toBeNull()
    expect(context.summary).toContain('no measured structural levels')
  })

  it('renders a missing state when every measured price source is absent', () => {
    const context = buildDecisionPriceContext({ symbol: 'SPCX' })

    expect(context.spot).toBeNull()
    expect(context.status).toBe('missing')
    expect(context.nearbyLevels).toEqual([])
  })
})
