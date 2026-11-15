import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { DASH } from '@/format'
import {
  benchmarkTrendLabel,
  benchmarkTrendTone,
  flowBarStyle,
  flowLeanLabel,
  formatReturnPct,
  topFlowRow,
  watchMatchesFlow,
} from '@/sectorDisplay'

describe('sector display missing data', () => {
  it('does not paint a missing return as +0.00%', () => {
    expect(formatReturnPct(null)).toBe(DASH)
    expect(formatReturnPct(undefined)).toBe(DASH)
    expect(formatReturnPct(Number.NaN)).toBe(DASH)
    expect(formatReturnPct(0)).toBe('+0.00%')
    expect(formatReturnPct(0.0125)).toBe('+1.25%')
    expect(formatReturnPct(-0.02, 1)).toBe('-2.0%')
  })

  it('does not report a missing moving-average state as below the average', () => {
    expect(benchmarkTrendLabel(undefined)).toBe('MA20 UNAVAILABLE')
    expect(benchmarkTrendLabel(null)).toBe('MA20 UNAVAILABLE')
    expect(benchmarkTrendLabel('false')).toBe('MA20 UNAVAILABLE')
    expect(benchmarkTrendLabel(false)).toBe('BELOW MA20')
    expect(benchmarkTrendLabel(true)).toBe('ABOVE MA20')
    expect(benchmarkTrendTone(null)).toBe('flat')
    expect(benchmarkTrendTone(false)).toBe('neg')
    expect(benchmarkTrendTone(true)).toBe('pos')
  })

  it('keeps an unmeasured flow score out of the money-in filter', () => {
    expect(flowLeanLabel(null)).toBe('UNMEASURED')
    expect(flowLeanLabel(0)).toBe('flat')
    expect(flowLeanLabel(0.02)).toBe('money in')
    expect(flowLeanLabel(-0.01)).toBe('money out')
    expect(watchMatchesFlow(null, 'in')).toBe(false)
    expect(watchMatchesFlow(null, 'out')).toBe(false)
    expect(watchMatchesFlow(null, 'all')).toBe(true)
    expect(watchMatchesFlow(0, 'in')).toBe(false)
    expect(watchMatchesFlow(0.01, 'in')).toBe(true)
    expect(watchMatchesFlow(-0.01, 'out')).toBe(true)
    expect(flowBarStyle(null, 0.05)).toEqual({ side: 'none', width: '0%' })
  })

  it('does not crown a missing flow score as the top sector', () => {
    const rows = [
      { etf: 'XLK', flow_score: null },
      { etf: 'XLE', flow_score: -0.02 },
      { etf: 'XLF', flow_score: 0.01 },
    ]
    expect(topFlowRow(rows, 'in')?.etf).toBe('XLF')
    expect(topFlowRow(rows, 'out')?.etf).toBe('XLE')
  })

  it('wires the sector screen to the missing-data formatters', () => {
    const src = readFileSync(new URL('../views/SectorsView.vue', import.meta.url), 'utf8')
    expect(src).toContain('formatReturnPct')
    expect(src).toContain('benchmarkTrendLabel')
    expect(src).toContain('watchMatchesFlow')
    expect(src).not.toContain('spy_ret_1d ?? 0')
    expect(src).not.toContain('spy_ret_5d ?? 0')
    expect(src).not.toContain("(w.score ?? 0) >= 0 ? 'money in'")
  })
})
