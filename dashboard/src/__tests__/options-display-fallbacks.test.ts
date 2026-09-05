import { describe, expect, it } from 'vitest'
import {
  optNum,
  optPct,
  optPctFrac,
  optSignedPct,
  optSigned,
  optCompact,
  optUsd,
  optGex,
  optSignedGex,
  num,
  pct,
  pctFrac,
  usd,
  signed,
  signedPct,
  compact,
  DASH,
} from '@/format'
import { computeVolOiRatio, formatDteBadge, formatMoneyness } from '@/flowDisplay'
import { calculateFeaturedSetup, calculateRingOffset, RING_CIRCUMFERENCE } from '@/squeezeCalc'

describe('Milestone 4: Options & Squeeze Formatters Honour the No-Fake-Zero Rule', () => {
  describe('1. optNum Formatter', () => {
    it('returns DASH on null, undefined, NaN, and non-finite values', () => {
      expect(optNum(null)).toBe(DASH)
      expect(optNum(undefined)).toBe(DASH)
      expect(optNum(NaN)).toBe(DASH)
      expect(optNum(Infinity)).toBe(DASH)
      expect(optNum(-Infinity)).toBe(DASH)
      expect(optNum('')).toBe(DASH)
      expect(optNum('not-a-number')).toBe(DASH)
    })

    it('formats valid numbers with commas and fixed precision', () => {
      expect(optNum(1234.5678, 2)).toBe('1,234.57')
      expect(optNum(0, 2)).toBe('0.00')
      expect(optNum(-42.1, 1)).toBe('-42.1')
    })
  })

  describe('2. optPct Formatter', () => {
    it('returns DASH on missing inputs', () => {
      expect(optPct(null)).toBe(DASH)
      expect(optPct(undefined)).toBe(DASH)
      expect(optPct(NaN)).toBe(DASH)
      expect(optPct(null, 1)).toBe(DASH)
    })

    it('formats valid percentages', () => {
      expect(optPct(12.5, 2)).toBe('12.50%')
      expect(optPct(0, 2)).toBe('0.00%')
      expect(optPct(-3.25, 1)).toBe('-3.3%')
    })
  })

  describe('3. optPctFrac Formatter', () => {
    it('returns DASH on missing inputs', () => {
      expect(optPctFrac(null, 2)).toBe(DASH)
      expect(optPctFrac(undefined, 1)).toBe(DASH)
      expect(optPctFrac(NaN)).toBe(DASH)
    })

    it('multiplies fractional input by 100 and formats as percent', () => {
      expect(optPctFrac(0.125, 2)).toBe('12.50%')
      expect(optPctFrac(0.05, 1)).toBe('5.0%')
      expect(optPctFrac(-0.025, 2)).toBe('-2.50%')
    })
  })

  describe('4. optSignedPct Formatter', () => {
    it('returns DASH on missing inputs', () => {
      expect(optSignedPct(null, 2)).toBe(DASH)
      expect(optSignedPct(undefined, 1)).toBe(DASH)
      expect(optSignedPct(NaN)).toBe(DASH)
    })

    it('formats signed percentages with explicit direction, + on zero', () => {
      expect(optSignedPct(5.25, 2)).toBe('+5.25%')
      expect(optSignedPct(0, 1)).toBe('+0.0%')
      expect(optSignedPct(-3.5, 1)).toBe('-3.5%')
    })
  })

  describe('5. optSigned Formatter', () => {
    it('returns DASH on missing inputs', () => {
      expect(optSigned(null, 2)).toBe(DASH)
      expect(optSigned(undefined, 1)).toBe(DASH)
      expect(optSigned(NaN)).toBe(DASH)
      expect(optSigned(null, 0)).toBe(DASH)
    })

    it('formats signed numbers with explicit plus, + on zero', () => {
      expect(optSigned(45.6, 1)).toBe('+45.6')
      expect(optSigned(0, 1)).toBe('+0.0')
      expect(optSigned(-12.34, 2)).toBe('-12.34')
    })
  })

  describe('6. optCompact Formatter', () => {
    it('returns DASH on missing inputs', () => {
      expect(optCompact(null)).toBe(DASH)
      expect(optCompact(undefined)).toBe(DASH)
      expect(optCompact(NaN)).toBe(DASH)
    })

    it('formats large values into compact representations', () => {
      expect(optCompact(1_500_000)).toBe('1.5M')
      expect(optCompact(25_000)).toBe('25.0K')
      expect(optCompact(3_200_000_000)).toBe('3.2B')
      expect(optCompact(0)).toBe('0')
    })
  })

  describe('7. optUsd Formatter', () => {
    it('returns DASH on missing inputs', () => {
      expect(optUsd(null)).toBe(DASH)
      expect(optUsd(undefined)).toBe(DASH)
      expect(optUsd(NaN)).toBe(DASH)
      expect(optUsd(null, 0)).toBe(DASH)
    })

    it('formats valid currency values', () => {
      expect(optUsd(1234.5)).toBe('$1,234.50')
      expect(optUsd(0)).toBe('$0.00')
      expect(optUsd(500, 0)).toBe('$500')
    })
  })

  describe('8. optGex / optSignedGex Formatters', () => {
    it('returns DASH on missing inputs', () => {
      expect(optGex(null)).toBe(DASH)
      expect(optGex(undefined)).toBe(DASH)
      expect(optGex(NaN)).toBe(DASH)
      expect(optGex(null, 2)).toBe(DASH)
      expect(optSignedGex(null)).toBe(DASH)
      expect(optSignedGex(undefined)).toBe(DASH)
      expect(optSignedGex(NaN)).toBe(DASH)
    })

    it('formats GEX magnitude in millions and billions with dollar sign', () => {
      expect(optGex(12.4)).toBe('$12.4M')
      expect(optGex(-5.2)).toBe('-$5.2M')
      expect(optGex(2500)).toBe('$2.5B')
      expect(optGex(-1800)).toBe('-$1.8B')
      expect(optGex(0)).toBe('$0.0M')
    })

    it('formats signed GEX with sign preceding the dollar symbol, + on zero', () => {
      expect(optSignedGex(12.4)).toBe('+$12.4M')
      expect(optSignedGex(-5.2)).toBe('-$5.2M')
      expect(optSignedGex(2500)).toBe('+$2.5B')
      expect(optSignedGex(0)).toBe('+$0.0M')
    })
  })

  describe('9. Flow Display Badge and Moneyness Fallbacks', () => {
    it('computeVolOiRatio names missing volume and OI instead of 0.00x', () => {
      expect(computeVolOiRatio(null, null)).toEqual({
        ratio: null,
        formatted: 'VOL/OI MISSING',
        isHigh: false,
        isExtreme: false,
      })
      expect(computeVolOiRatio(undefined, undefined).formatted).toBe('VOL/OI MISSING')
      expect(computeVolOiRatio(100, null).formatted).toBe('OI MISSING')
      expect(computeVolOiRatio(null, 100).formatted).toBe('VOL MISSING')
      expect(computeVolOiRatio(-50, 100).formatted).toBe('VOL MISSING')
    })

    it('computeVolOiRatio identifies 0 OI as "NEW (0 OI)"', () => {
      expect(computeVolOiRatio(500, 0)).toEqual({
        ratio: null,
        formatted: 'NEW (0 OI)',
        isHigh: true,
        isExtreme: true,
      })
    })

    it('formatDteBadge names missing DTE', () => {
      expect(formatDteBadge(null)).toEqual({ label: 'DTE MISSING', className: 'dte-unknown' })
      expect(formatDteBadge(undefined)).toEqual({ label: 'DTE MISSING', className: 'dte-unknown' })
      expect(formatDteBadge(NaN)).toEqual({ label: 'DTE MISSING', className: 'dte-unknown' })
    })

    it('formatMoneyness names missing OTM', () => {
      expect(formatMoneyness(null)).toEqual({ label: 'OTM MISSING', className: 'moneyness-none' })
      expect(formatMoneyness(undefined)).toEqual({
        label: 'OTM MISSING',
        className: 'moneyness-none',
      })
      expect(formatMoneyness(NaN)).toEqual({ label: 'OTM MISSING', className: 'moneyness-none' })
    })
  })

  describe('10. Squeeze Calculation Fallbacks', () => {
    it('calculateFeaturedSetup falls back cleanly on empty setups', () => {
      const feat = calculateFeaturedSetup('quiet', undefined, undefined, undefined)
      expect(feat.side).toBe('bullish')
      expect(feat.setup).toBeUndefined()
    })

    it('calculateRingOffset handles 0 score cleanly without NaN', () => {
      const offset = calculateRingOffset(0, RING_CIRCUMFERENCE)
      expect(Number.isFinite(offset)).toBe(true)
      expect(offset).toBe(RING_CIRCUMFERENCE)
    })
  })

  describe('11. Equities Backward Compatibility Invariant', () => {
    it('preserves global DASH (—) behavior for general equities readouts', () => {
      expect(num(null)).toBe(DASH)
      expect(num(undefined)).toBe(DASH)
      expect(num(NaN)).toBe(DASH)
      expect(pct(null)).toBe(DASH)
      expect(pctFrac(null)).toBe(DASH)
      expect(usd(null)).toBe(DASH)
      expect(signed(null)).toBe(DASH)
      expect(signedPct(null)).toBe(DASH)
      expect(compact(null)).toBe(DASH)
    })
  })

  describe('12. Options/Squeeze Formatters Are Honest About Missing Data (regression)', () => {
    const badInputs = [null, undefined, NaN, Infinity, -Infinity, '', 'not-a-number']

    it('every opt* formatter returns DASH for every non-finite/missing input shape', () => {
      for (const bad of badInputs) {
        expect(optNum(bad)).toBe(DASH)
        expect(optPct(bad)).toBe(DASH)
        expect(optPctFrac(bad)).toBe(DASH)
        expect(optSignedPct(bad)).toBe(DASH)
        expect(optSigned(bad)).toBe(DASH)
        expect(optCompact(bad)).toBe(DASH)
        expect(optUsd(bad)).toBe(DASH)
        expect(optGex(bad)).toBe(DASH)
        expect(optSignedGex(bad)).toBe(DASH)
      }
    })
  })
})
