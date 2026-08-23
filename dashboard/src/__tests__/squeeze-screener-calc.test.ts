import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { SqueezeSetup } from '@/api'
import {
  calculateFeaturedSetup,
  calculateRingOffset,
  formatNearSpotGex,
  calculateTrackWidthPct,
  buildTakeaways,
  RING_CIRCUMFERENCE,
} from '@/squeezeCalc'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function mockSetup(score: number, overrides: Partial<SqueezeSetup> = {}): SqueezeSetup {
  return {
    side: 'bullish',
    score,
    score_01: score / 100,
    likelihood: score >= 75 ? 'imminent' : score >= 55 ? 'likely' : score >= 35 ? 'possible' : 'unlikely',
    factors: [],
    setup_analysis: [],
    for_stronger: [],
    trading_implication: 'Structure test implication',
    spot: 500,
    wall: null,
    wall_pct: null,
    ...overrides,
  }
}

describe('Squeeze Screener Calculation Suite', () => {
  describe('1. Setup Selection & Tie-Breaking with signedScore', () => {
    it('honors explicit primary="bearish" regardless of setup score comparison', () => {
      const bull = mockSetup(80)
      const bear = mockSetup(40)
      const res = calculateFeaturedSetup('bearish', bull, bear, 40)
      expect(res.side).toBe('bearish')
      expect(res.setup).toBe(bear)
    })

    it('honors explicit primary="bullish" regardless of setup score comparison', () => {
      const bull = mockSetup(30)
      const bear = mockSetup(75)
      const res = calculateFeaturedSetup('bullish', bull, bear, -45)
      expect(res.side).toBe('bullish')
      expect(res.setup).toBe(bull)
    })

    it('selects higher score setup when primary is "quiet"', () => {
      const bullHigh = mockSetup(70)
      const bearLow = mockSetup(25)
      expect(calculateFeaturedSetup('quiet', bullHigh, bearLow, 0).side).toBe('bullish')

      const bullLow = mockSetup(20)
      const bearHigh = mockSetup(65)
      expect(calculateFeaturedSetup('quiet', bullLow, bearHigh, 0).side).toBe('bearish')
    })

    it('tie-breaks equal structure scores (bs === rs) using negative signedScore -> bearish', () => {
      const bull = mockSetup(45)
      const bear = mockSetup(45)
      // Negative signed score (-30) indicates put-skew / bearish bias
      const resQuiet = calculateFeaturedSetup('quiet', bull, bear, -30)
      expect(resQuiet.side).toBe('bearish')
      expect(resQuiet.setup).toBe(bear)

      const resTwoWay = calculateFeaturedSetup('two_way', bull, bear, -15)
      expect(resTwoWay.side).toBe('bearish')
      expect(resTwoWay.setup).toBe(bear)
    })

    it('tie-breaks equal structure scores (bs === rs) using positive signedScore -> bullish', () => {
      const bull = mockSetup(50)
      const bear = mockSetup(50)
      const resQuiet = calculateFeaturedSetup('quiet', bull, bear, 25)
      expect(resQuiet.side).toBe('bullish')
      expect(resQuiet.setup).toBe(bull)

      const resTwoWay = calculateFeaturedSetup('two_way', bull, bear, 10)
      expect(resTwoWay.side).toBe('bullish')
      expect(resTwoWay.setup).toBe(bull)
    })

    it('defaults to bullish when structure scores are equal and signedScore is 0 or null', () => {
      const bull = mockSetup(40)
      const bear = mockSetup(40)
      expect(calculateFeaturedSetup('quiet', bull, bear, 0).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bull, bear, null).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bull, bear, undefined).side).toBe('bullish')
    })

    it('handles undefined setups gracefully', () => {
      const resNullBull = calculateFeaturedSetup('quiet', undefined, mockSetup(30), -10)
      expect(resNullBull.side).toBe('bearish')

      const resNullBoth = calculateFeaturedSetup('quiet', undefined, undefined, -5)
      expect(resNullBoth.side).toBe('bearish')

      const resNullBothPos = calculateFeaturedSetup('quiet', undefined, undefined, 5)
      expect(resNullBothPos.side).toBe('bullish')
    })

    it('handles compound primary labels and case-insensitivity cleanly', () => {
      const bull = mockSetup(60)
      const bear = mockSetup(40)
      expect(calculateFeaturedSetup('bearish_squeeze', bull, bear).side).toBe('bearish')
      expect(calculateFeaturedSetup('BEARISH_LEAN', bull, bear).side).toBe('bearish')
      expect(calculateFeaturedSetup('bullish_squeeze', bull, bear).side).toBe('bullish')
      expect(calculateFeaturedSetup('BULLISH', bull, bear).side).toBe('bullish')
    })

    it('falls back to available setup when preferred side setup is missing', () => {
      const bull = mockSetup(65)
      const res = calculateFeaturedSetup('bearish', bull, undefined)
      expect(res.side).toBe('bearish')
      expect(res.setup).toBe(bull)
    })
  })

  describe('2. Radial Ring Offset Math & Geometry Bounds', () => {
    it('calculates exact stroke-dashoffset for standard score ranges', () => {
      const fullOffset = RING_CIRCUMFERENCE
      expect(calculateRingOffset(0)).toBeCloseTo(fullOffset, 2)
      expect(calculateRingOffset(100)).toBeCloseTo(0, 2)
      expect(calculateRingOffset(50)).toBeCloseTo(fullOffset * 0.5, 2)
      expect(calculateRingOffset(25)).toBeCloseTo(fullOffset * 0.75, 2)
      expect(calculateRingOffset(75)).toBeCloseTo(fullOffset * 0.25, 2)
    })

    it('renders ring progress accurately for negative scores using Math.abs', () => {
      const fullOffset = RING_CIRCUMFERENCE
      // Negative scores (e.g. -50 bearish squeeze) should render 50% stroke fill
      expect(calculateRingOffset(-50)).toBeCloseTo(fullOffset * 0.5, 2)
      expect(calculateRingOffset(-75)).toBeCloseTo(fullOffset * 0.25, 2)
      expect(calculateRingOffset(-100)).toBeCloseTo(0, 2)
    })

    it('clamps extreme positive and negative scores strictly to [0, 100]%', () => {
      expect(calculateRingOffset(150)).toBeCloseTo(0, 2)
      expect(calculateRingOffset(999)).toBeCloseTo(0, 2)
      expect(calculateRingOffset(-150)).toBeCloseTo(0, 2)
      expect(calculateRingOffset(-500)).toBeCloseTo(0, 2)
    })

    it('handles null, undefined, and NaN without runtime errors or invalid offsets', () => {
      const fullOffset = RING_CIRCUMFERENCE
      expect(calculateRingOffset(null)).toBeCloseTo(fullOffset, 2)
      expect(calculateRingOffset(undefined)).toBeCloseTo(fullOffset, 2)
      expect(calculateRingOffset(Number.NaN)).toBeCloseTo(fullOffset, 2)
    })

    it('supports custom circumference values', () => {
      const customC = 100
      expect(calculateRingOffset(40, customC)).toBeCloseTo(60, 2)
      expect(calculateRingOffset(-40, customC)).toBeCloseTo(60, 2)
    })
  })

  describe('3. Currency Formatting for Near-Spot Net GEX', () => {
    it('formats positive values with leading plus sign and standard dollar unit', () => {
      expect(formatNearSpotGex(12.34)).toBe('+$12.3M')
      expect(formatNearSpotGex(0.48)).toBe('+$0.5M')
      expect(formatNearSpotGex(100)).toBe('+$100.0M')
      expect(formatNearSpotGex(0)).toBe('+$0.0M')
    })

    it('formats negative values as -$X.XM rather than $-X.XM', () => {
      expect(formatNearSpotGex(-5.2)).toBe('-$5.2M')
      expect(formatNearSpotGex(-0.4)).toBe('-$0.4M')
      expect(formatNearSpotGex(-12.34)).toBe('-$12.3M')
      expect(formatNearSpotGex(-99.9)).toBe('-$99.9M')
    })

    it('handles missing or invalid GEX values with fallback em-dash', () => {
      expect(formatNearSpotGex(null)).toBe('—')
      expect(formatNearSpotGex(undefined)).toBe('—')
      expect(formatNearSpotGex(Number.NaN)).toBe('—')
    })
  })

  describe('4. Factor Track Width Percentage Calculations & Clamping', () => {
    it('calculates proper width percentage for positive factor scores', () => {
      expect(calculateTrackWidthPct(50, 100)).toBe(50)
      expect(calculateTrackWidthPct(15, 20)).toBe(75)
      expect(calculateTrackWidthPct(10, 10)).toBe(100)
      expect(calculateTrackWidthPct(0, 50)).toBe(0)
    })

    it('clamps negative scores to 0% to prevent negative CSS widths', () => {
      expect(calculateTrackWidthPct(-10, 100)).toBe(0)
      expect(calculateTrackWidthPct(-50, 50)).toBe(0)
      expect(calculateTrackWidthPct(-0.01, 100)).toBe(0)
    })

    it('clamps overflow scores to 100%', () => {
      expect(calculateTrackWidthPct(120, 100)).toBe(100)
      expect(calculateTrackWidthPct(25, 20)).toBe(100)
    })

    it('handles zero or negative maximums safely', () => {
      expect(calculateTrackWidthPct(10, 0)).toBe(0)
      expect(calculateTrackWidthPct(10, -5)).toBe(0)
      expect(calculateTrackWidthPct(null, 100)).toBe(0)
      expect(calculateTrackWidthPct(10, null)).toBe(0)
      expect(calculateTrackWidthPct(Number.NaN, 100)).toBe(0)
    })
  })

  describe('5. Takeaway Bullet Dot Polarity & Tone', () => {
    it('assigns "pos" dot tone and upward arrow to bullish call wall level', () => {
      const takeaways = buildTakeaways({
        side: 'bullish',
        wallLevel: 580,
        wallPct: 0.025,
        wallLabel: 'Call Wall',
      })
      expect(takeaways.length).toBeGreaterThanOrEqual(1)
      expect(takeaways[0].type).toBe('pos')
      expect(takeaways[0].icon).toBe('↑')
      expect(takeaways[0].line).toContain('Call Wall at $580.00 (+2.5%)')
    })

    it('assigns "neg" dot tone and downward arrow to bearish put wall level', () => {
      const takeaways = buildTakeaways({
        side: 'bearish',
        wallLevel: 550,
        wallPct: -0.03,
        wallLabel: 'Put Wall',
      })
      expect(takeaways.length).toBeGreaterThanOrEqual(1)
      expect(takeaways[0].type).toBe('neg')
      expect(takeaways[0].icon).toBe('↓')
      expect(takeaways[0].line).toContain('Put Wall at $550.00 (-3.0%)')
    })

    it('assigns "warn" dot tone to dampened long-gamma regime notices', () => {
      const takeaways = buildTakeaways({
        side: 'bullish',
        dampened: true,
      })
      const damp = takeaways.find((t) => t.line.includes('Long-gamma regime'))
      expect(damp).toBeDefined()
      expect(damp?.type).toBe('warn')
      expect(damp?.icon).toBe('●')
    })

    it('assigns "info" dot tone to general trading implications', () => {
      const takeaways = buildTakeaways({
        side: 'bullish',
        implication: 'High positive gamma cushions abrupt drawdown.',
      })
      const impl = takeaways.find((t) => t.line.includes('cushions'))
      expect(impl).toBeDefined()
      expect(impl?.type).toBe('info')
      expect(impl?.icon).toBe('●')
    })

    it('correctly maps setup_analysis strings with keyword classification', () => {
      const takeaways = buildTakeaways({
        side: 'bearish',
        analysis: [
          'Downside acceleration below put wall magnet',
          'Zero-gamma volatility amplification zone',
          'Partial structure lean on low volume',
        ],
      })
      expect(takeaways[0].type).toBe('neg')
      expect(takeaways[0].icon).toBe('↓')
      expect(takeaways[1].type).toBe('warn')
      expect(takeaways[1].icon).toBe('●')
      expect(takeaways[2].type).toBe('info')
      expect(takeaways[2].icon).toBe('●')
    })
  })

  describe('6. Component Template & CSS Token Compliance', () => {
    const vueSrc = readFileSync(join(root, 'components/SqueezeScreener.vue'), 'utf8')

    it('includes smooth cubic-bezier transition for radial ring fill', () => {
      expect(vueSrc).toContain('transition: stroke-dashoffset 0.6s cubic-bezier(0.22, 1, 0.36, 1);')
    })

    it('defines crimson takeaway dot class for bearish setups', () => {
      expect(vueSrc).toContain('.takeaway-dot.neg { background: var(--put); }')
    })

    it('preserves emerald and crimson score highlights for hot scores without amber override', () => {
      expect(vueSrc).toContain('.sq.bullish .score-num.hot { color: var(--call-hi); }')
      expect(vueSrc).toContain('.sq.bearish .score-num.hot { color: var(--put-hi); }')
      expect(vueSrc).not.toContain('.score-num.hot { color: var(--warn); }')
    })

    it('binds calculated track width helper across factors and alt tracks', () => {
      expect(vueSrc).toContain('calculateTrackWidthPct(f.score, f.max)')
      expect(vueSrc).toContain('calculateTrackWidthPct(otherSide.setup.score, 100)')
    })
  })
})
