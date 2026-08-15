import { describe, expect, it } from 'vitest'
import {
  classifyFilingKind,
  classifyInsiderSide,
  insiderLean,
  presentFintelInsiders,
  presentSecFilings,
} from '@/insiderDisplay'

describe('insider display', () => {
  it('classifies buy and sell without inventing a side', () => {
    expect(classifyInsiderSide('Purchase')).toBe('buy')
    expect(classifyInsiderSide('S-Sale')).toBe('sell')
    expect(classifyInsiderSide('')).toBe('other')
    expect(classifyFilingKind('4')).toBe('insider')
    expect(classifyFilingKind('8-K')).toBe('event')
    expect(classifyFilingKind('SC 13D')).toBe('holder')
  })

  it('normalizes Fintel insider rows and SEC filings', () => {
    const insiders = presentFintelInsiders([
      { insider_name: 'Jane Doe', transaction_type: 'Buy', shares: 1200, price: 41.2, date: '2026-08-01' },
      { name: 'John Roe', type: 'Sell', share_count: 400 },
    ])
    expect(insiders).toHaveLength(2)
    expect(insiders[0].side).toBe('buy')
    expect(insiders[0].source).toBe('fintel')
    expect(insiders[0].detail).toContain('1200 sh')
    expect(insiderLean(insiders)).toEqual({ buys: 1, sells: 1, label: 'MIXED' })

    const filings = presentSecFilings({
      filings: [
        { form: '4', filed: '2026-08-02', description: 'Statement of changes', url: 'https://sec.gov/x' },
        { form: '8-K', filed: '2026-08-03', description: 'Item 2.02' },
      ],
    })
    expect(filings[0].kind).toBe('insider')
    expect(filings[1].kind).toBe('event')
  })
})
