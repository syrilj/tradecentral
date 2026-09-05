import { describe, expect, it } from 'vitest'
import {
  computeFlowConcentration,
  dteLabel,
  expiryLabel,
  trueMoneyness,
  type ConcentrationPrint,
} from '../flowConcentration'
import { DTE_MISSING } from '../flowDisplay'

function print(over: Partial<ConcentrationPrint> = {}): ConcentrationPrint {
  return {
    premium: 100_000,
    contracts: 10,
    dte: 3,
    expiry: '2026-09-11',
    right: 'call',
    strike: 700,
    underlying_price: 719,
    ...over,
  }
}

describe('expiryLabel', () => {
  it('renders an ISO expiry as a short calendar date', () => {
    expect(expiryLabel('2026-09-11')).toBe('Sep 11')
    expect(expiryLabel('2026-01-02')).toBe('Jan 2')
    expect(expiryLabel('2026-12-18')).toBe('Dec 18')
  })

  it('does not slide a day regardless of the host timezone', () => {
    // A `new Date('2026-09-11')` parse renders as Sep 10 west of UTC.
    expect(expiryLabel('2026-09-11')).toBe('Sep 11')
  })

  it('passes through anything that is not an ISO date', () => {
    expect(expiryLabel('not-a-date')).toBe('not-a-date')
    expect(expiryLabel('2026-13-01')).toBe('2026-13-01')
  })
})

describe('dteLabel', () => {
  it('names a missing DTE rather than printing a zero', () => {
    expect(dteLabel(null)).toBe(DTE_MISSING)
  })

  it('renders same-day as 0D and clamps negatives to it', () => {
    expect(dteLabel(0)).toBe('0D')
    expect(dteLabel(-2)).toBe('0D')
  })

  it('rounds fractional DTE', () => {
    expect(dteLabel(6.4)).toBe('6D')
    expect(dteLabel(6.6)).toBe('7D')
  })
})

describe('trueMoneyness', () => {
  it('recomputes ITM depth the provider clamps to zero', () => {
    // Live case from the provider window: SPY 685 call against spot 770.18
    // reports otm_pct = 0, which reads as "ATM".
    const m = trueMoneyness(print({ right: 'call', strike: 685, underlying_price: 770.18 }))
    expect(m).not.toBeNull()
    expect(m as number).toBeLessThan(-0.1)
  })

  it('is positive out-of-the-money for both rights', () => {
    expect(trueMoneyness(print({ right: 'call', strike: 750, underlying_price: 700 }))).toBeCloseTo(
      0.0714,
      3,
    )
    expect(trueMoneyness(print({ right: 'put', strike: 650, underlying_price: 700 }))).toBeCloseTo(
      0.0714,
      3,
    )
  })

  it('returns null rather than guessing when a leg is missing', () => {
    expect(trueMoneyness(print({ strike: null }))).toBeNull()
    expect(trueMoneyness(print({ underlying_price: null }))).toBeNull()
    expect(trueMoneyness(print({ underlying_price: 0 }))).toBeNull()
    expect(trueMoneyness(print({ right: null }))).toBeNull()
  })
})

describe('computeFlowConcentration', () => {
  it('reports an empty, non-null-share result for no prints', () => {
    for (const input of [null, undefined, []]) {
      const c = computeFlowConcentration(input)
      expect(c.totalPremium).toBe(0)
      expect(c.measuredPrints).toBe(0)
      expect(c.expiries).toEqual([])
      expect(c.peakShare).toBeNull()
      expect(c.horizons).toHaveLength(4)
      // Never 0% — nothing was measured, so there is no share to report.
      expect(c.horizons.every((h) => h.share === null)).toBe(true)
    }
  })

  it('buckets premium onto disjoint horizons that sum to one', () => {
    const c = computeFlowConcentration([
      print({ dte: 0, premium: 100 }),
      print({ dte: 5, premium: 200 }),
      print({ dte: 20, premium: 300 }),
      print({ dte: 90, premium: 400 }),
    ])
    expect(c.totalPremium).toBe(1000)
    const byKey = Object.fromEntries(c.horizons.map((h) => [h.key, h.share]))
    expect(byKey.zero).toBeCloseTo(0.1, 6)
    expect(byKey.week).toBeCloseTo(0.2, 6)
    expect(byKey.month).toBeCloseTo(0.3, 6)
    expect(byKey.beyond).toBeCloseTo(0.4, 6)
    const sum = c.horizons.reduce((acc, h) => acc + (h.share ?? 0), 0)
    expect(sum).toBeCloseTo(1, 9)
  })

  it('puts the horizon boundaries on 0, 7 and 31 days', () => {
    const at = (dte: number): string => {
      const c = computeFlowConcentration([print({ dte, premium: 10 })])
      return c.horizons.find((h) => (h.share ?? 0) > 0)?.key ?? 'none'
    }
    expect(at(0)).toBe('zero')
    expect(at(1)).toBe('week')
    expect(at(7)).toBe('week')
    expect(at(8)).toBe('month')
    expect(at(31)).toBe('month')
    expect(at(32)).toBe('beyond')
  })

  it('aggregates repeated expiries and sorts richest premium first', () => {
    const c = computeFlowConcentration([
      print({ expiry: '2026-09-04', dte: 0, premium: 100 }),
      print({ expiry: '2026-09-11', dte: 7, premium: 500 }),
      print({ expiry: '2026-09-04', dte: 0, premium: 300 }),
    ])
    expect(c.expiries).toHaveLength(2)
    expect(c.expiries[0].key).toBe('2026-09-11')
    expect(c.expiries[0].premium).toBe(500)
    expect(c.expiries[1].key).toBe('2026-09-04')
    expect(c.expiries[1].premium).toBe(400)
    expect(c.expiries[1].prints).toBe(2)
    expect(c.peakShare).toBeCloseTo(500 / 900, 6)
  })

  it('splits call and put premium within an expiry', () => {
    const c = computeFlowConcentration([
      print({ right: 'call', premium: 700 }),
      print({ right: 'put', premium: 300 }),
    ])
    expect(c.expiries[0].callPremium).toBe(700)
    expect(c.expiries[0].putPremium).toBe(300)
    expect(c.expiries[0].premium).toBe(1000)
  })

  it('skips prints with no usable premium instead of counting them as zero', () => {
    const c = computeFlowConcentration([
      print({ premium: 400 }),
      print({ premium: null }),
      print({ premium: 0 }),
      print({ premium: -50 }),
      print({ premium: Number.NaN }),
    ])
    expect(c.measuredPrints).toBe(1)
    expect(c.unmeasuredPrints).toBe(4)
    expect(c.totalPremium).toBe(400)
    // The single measured print is the whole window, not a fifth of it.
    expect(c.expiries[0].share).toBe(1)
  })

  it('counts a missing expiry rather than bucketing it under a guess', () => {
    const c = computeFlowConcentration([
      print({ expiry: '2026-09-11', premium: 100 }),
      print({ expiry: null, premium: 100 }),
      print({ expiry: '   ', premium: 100 }),
    ])
    expect(c.missingExpiry).toBe(2)
    expect(c.expiries).toHaveLength(1)
    // Premium still counts toward the window total even without an expiry.
    expect(c.totalPremium).toBe(300)
    expect(c.expiries[0].share).toBeCloseTo(1 / 3, 6)
  })

  it('counts a missing DTE and still buckets the print by expiry', () => {
    const c = computeFlowConcentration([print({ dte: null, expiry: '2026-09-11', premium: 250 })])
    expect(c.missingDte).toBe(1)
    expect(c.expiries).toHaveLength(1)
    expect(c.expiries[0].dteLabel).toBe(DTE_MISSING)
    expect(c.horizons.every((h) => h.premium === 0)).toBe(true)
  })

  it('backfills an expiry DTE from a later print that carries one', () => {
    const c = computeFlowConcentration([
      print({ expiry: '2026-09-11', dte: null, premium: 100 }),
      print({ expiry: '2026-09-11', dte: 7, premium: 100 }),
    ])
    expect(c.expiries[0].dte).toBe(7)
    expect(c.expiries[0].dteLabel).toBe('7D')
  })

  it('falls back to volume when contracts are absent', () => {
    const c = computeFlowConcentration([
      print({ contracts: null, volume: 12 }),
      print({ contracts: 8, volume: 99 }),
    ])
    expect(c.expiries[0].contracts).toBe(20)
  })

  it('never emits a share above one or below zero', () => {
    const c = computeFlowConcentration([
      print({ expiry: '2026-09-04', premium: 1 }),
      print({ expiry: '2026-09-11', premium: 1_000_000_000 }),
    ])
    for (const e of c.expiries) {
      expect(e.share).not.toBeNull()
      expect(e.share as number).toBeGreaterThanOrEqual(0)
      expect(e.share as number).toBeLessThanOrEqual(1)
    }
  })
})
