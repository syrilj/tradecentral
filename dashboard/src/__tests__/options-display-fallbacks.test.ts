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
  num,
  pct,
  pctFrac,
  usd,
  signed,
  signedPct,
  compact,
  DASH,
} from '@/format'
import {
  computeVolOiRatio,
  formatDteBadge,
  formatMoneyness,
} from '@/flowDisplay'
import { calculateFeaturedSetup, calculateRingOffset, RING_CIRCUMFERENCE } from '@/squeezeCalc'

describe('Milestone 4: Options & Squeeze Clean Numeric Fallbacks & Em-Dash Elimination', () => {
  describe('1. optNum Formatter', () => {
    it('returns clean "0.00" on null, undefined, NaN, and non-finite values by default', () => {
      expect(optNum(null)).toBe('0.00')
      expect(optNum(undefined)).toBe('0.00')
      expect(optNum(NaN)).toBe('0.00')
      expect(optNum(Infinity)).toBe('0.00')
      expect(optNum(-Infinity)).toBe('0.00')
      expect(optNum('')).toBe('0.00')
      expect(optNum('not-a-number')).toBe('0.00')
    })

    it('respects decimal precision for fallbacks', () => {
      expect(optNum(null, 0)).toBe('0')
      expect(optNum(null, 1)).toBe('0.0')
      expect(optNum(null, 3)).toBe('0.000')
    })

    it('formats valid numbers with commas and fixed precision', () => {
      expect(optNum(1234.5678, 2)).toBe('1,234.57')
      expect(optNum(0, 2)).toBe('0.00')
      expect(optNum(-42.1, 1)).toBe('-42.1')
    })
  })

  describe('2. optPct Formatter', () => {
    it('returns "0.00%" on missing inputs', () => {
      expect(optPct(null)).toBe('0.00%')
      expect(optPct(undefined)).toBe('0.00%')
      expect(optPct(NaN)).toBe('0.00%')
      expect(optPct(null, 1)).toBe('0.0%')
    })

    it('formats valid percentages', () => {
      expect(optPct(12.5, 2)).toBe('12.50%')
      expect(optPct(0, 2)).toBe('0.00%')
      expect(optPct(-3.25, 1)).toBe('-3.3%')
    })
  })

  describe('3. optPctFrac Formatter', () => {
    it('returns "0.00%" or "0.0%" on missing inputs', () => {
      expect(optPctFrac(null, 2)).toBe('0.00%')
      expect(optPctFrac(undefined, 1)).toBe('0.0%')
      expect(optPctFrac(NaN)).toBe('0.00%')
    })

    it('multiplies fractional input by 100 and formats as percent', () => {
      expect(optPctFrac(0.125, 2)).toBe('12.50%')
      expect(optPctFrac(0.05, 1)).toBe('5.0%')
      expect(optPctFrac(-0.025, 2)).toBe('-2.50%')
    })
  })

  describe('4. optSignedPct Formatter', () => {
    it('returns "+0.00%" or "+0.0%" with explicit plus on missing inputs', () => {
      expect(optSignedPct(null, 2)).toBe('+0.00%')
      expect(optSignedPct(undefined, 1)).toBe('+0.0%')
      expect(optSignedPct(NaN)).toBe('+0.00%')
    })

    it('formats signed percentages with explicit direction', () => {
      expect(optSignedPct(5.25, 2)).toBe('+5.25%')
      expect(optSignedPct(0, 1)).toBe('+0.0%')
      expect(optSignedPct(-3.5, 1)).toBe('-3.5%')
    })
  })

  describe('5. optSigned Formatter', () => {
    it('returns "+0.00" or "+0.0" with explicit plus on missing inputs', () => {
      expect(optSigned(null, 2)).toBe('+0.00')
      expect(optSigned(undefined, 1)).toBe('+0.0')
      expect(optSigned(NaN)).toBe('+0.00')
      expect(optSigned(null, 0)).toBe('+0')
    })

    it('formats signed numbers with explicit plus', () => {
      expect(optSigned(45.6, 1)).toBe('+45.6')
      expect(optSigned(0, 1)).toBe('+0.0')
      expect(optSigned(-12.34, 2)).toBe('-12.34')
    })
  })

  describe('6. optCompact Formatter', () => {
    it('returns "0" on missing inputs without em-dash', () => {
      expect(optCompact(null)).toBe('0')
      expect(optCompact(undefined)).toBe('0')
      expect(optCompact(NaN)).toBe('0')
    })

    it('formats large values into compact representations', () => {
      expect(optCompact(1_500_000)).toBe('1.5M')
      expect(optCompact(25_000)).toBe('25.0K')
      expect(optCompact(3_200_000_000)).toBe('3.2B')
      expect(optCompact(0)).toBe('0')
    })
  })

  describe('7. optUsd Formatter', () => {
    it('returns "$0.00" on missing inputs without em-dash', () => {
      expect(optUsd(null)).toBe('$0.00')
      expect(optUsd(undefined)).toBe('$0.00')
      expect(optUsd(NaN)).toBe('$0.00')
      expect(optUsd(null, 0)).toBe('$0')
    })

    it('formats valid currency values', () => {
      expect(optUsd(1234.5)).toBe('$1,234.50')
      expect(optUsd(0)).toBe('$0.00')
      expect(optUsd(500, 0)).toBe('$500')
    })
  })

  describe('8. optGex Formatter', () => {
    it('returns "$0.0M" on missing inputs without em-dash', () => {
      expect(optGex(null)).toBe('$0.0M')
      expect(optGex(undefined)).toBe('$0.0M')
      expect(optGex(NaN)).toBe('$0.0M')
      expect(optGex(null, 2)).toBe('$0.00M')
    })

    it('formats GEX magnitude in millions and billions with dollar sign', () => {
      expect(optGex(12.4)).toBe('$12.4M')
      expect(optGex(-5.2)).toBe('-$5.2M')
      expect(optGex(2500)).toBe('$2.5B')
      expect(optGex(-1800)).toBe('-$1.8B')
      expect(optGex(0)).toBe('$0.0M')
    })
  })

  describe('9. Flow Display Badge and Moneyness Fallbacks', () => {
    it('computeVolOiRatio falls back to "0.00x" on missing inputs', () => {
      expect(computeVolOiRatio(null, null)).toEqual({
        ratio: null,
        formatted: '0.00x',
        isHigh: false,
        isExtreme: false,
      })
      expect(computeVolOiRatio(undefined, undefined).formatted).toBe('0.00x')
      expect(computeVolOiRatio(100, null).formatted).toBe('0.00x')
      expect(computeVolOiRatio(null, 100).formatted).toBe('0.00x')
      expect(computeVolOiRatio(-50, 100).formatted).toBe('0.00x')
    })

    it('computeVolOiRatio identifies 0 OI as "NEW (0 OI)"', () => {
      expect(computeVolOiRatio(500, 0)).toEqual({
        ratio: null,
        formatted: 'NEW (0 OI)',
        isHigh: true,
        isExtreme: true,
      })
    })

    it('formatDteBadge falls back to "N/A" on missing inputs', () => {
      expect(formatDteBadge(null)).toEqual({ label: 'N/A', className: 'dte-unknown' })
      expect(formatDteBadge(undefined)).toEqual({ label: 'N/A', className: 'dte-unknown' })
      expect(formatDteBadge(NaN)).toEqual({ label: 'N/A', className: 'dte-unknown' })
    })

    it('formatMoneyness falls back to "N/A" on missing inputs', () => {
      expect(formatMoneyness(null)).toEqual({ label: 'N/A', className: 'moneyness-none' })
      expect(formatMoneyness(undefined)).toEqual({ label: 'N/A', className: 'moneyness-none' })
      expect(formatMoneyness(NaN)).toEqual({ label: 'N/A', className: 'moneyness-none' })
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
})
