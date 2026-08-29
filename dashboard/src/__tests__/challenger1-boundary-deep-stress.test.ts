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
  DASH,
} from '@/format'
import {
  calculateFeaturedSetup,
  calculateRingOffset,
  formatNearSpotGex,
  calculateTrackWidthPct,
  RING_CIRCUMFERENCE,
} from '@/squeezeCalc'
import {
  classifyFlowOrder,
  classifyPremiumTier,
  computeVolOiRatio,
  flowWhaleTier,
  formatDteBadge,
  formatMoneyness,
  namedEmpty,
  mixShareLabel,
  concentrationLabel,
  pulseWindowCopy,
  type FlowOrderInput,
} from '@/flowDisplay'
import { linearScale, niceTicks, linePath } from '@/charts'
import { buildOptionsDirection } from '@/optionsDirection'
import type { GexStrikeRow, SqueezeSetup } from '@/api'

describe('Challenger 1: Empirical Adversarial & Boundary Stress Test Suite', () => {
  /* ==========================================================================
     1. SQUEEZE CALCULATIONS & TIE-BREAKING MATHEMATICS
     ========================================================================== */
  describe('1. Squeeze Calculations & Adversarial Structure Inputs', () => {
    function makeSetup(score: number, overrides: Partial<SqueezeSetup> = {}): SqueezeSetup {
      return {
        side: 'bullish',
        score,
        score_01: score / 100,
        likelihood:
          score >= 75 ? 'imminent' : score >= 55 ? 'likely' : score >= 35 ? 'possible' : 'unlikely',
        factors: [],
        setup_analysis: [],
        for_stronger: [],
        trading_implication: 'Testing implication',
        spot: 500,
        wall: null,
        wall_pct: null,
        ...overrides,
      }
    }

    it('handles negative, zero, NaN, infinite scores in calculateFeaturedSetup', () => {
      // 1. Negative scores comparison
      const bullNeg = makeSetup(-20)
      const bearNeg = makeSetup(-10) // bearNeg > bullNeg (-10 > -20)
      expect(calculateFeaturedSetup('quiet', bullNeg, bearNeg, 0).side).toBe('bearish')

      // 2. Zero scores
      const bullZero = makeSetup(0)
      const bearZero = makeSetup(0)
      expect(calculateFeaturedSetup('quiet', bullZero, bearZero, 0).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bullZero, bearZero, -15).side).toBe('bearish')
      expect(calculateFeaturedSetup('quiet', bullZero, bearZero, 15).side).toBe('bullish')

      // 3. -0 vs +0
      expect(calculateFeaturedSetup('quiet', makeSetup(-0), makeSetup(0), -0).side).toBe('bullish')

      // 4. NaN scores in setups
      const bullNaN = makeSetup(NaN)
      const bearNaN = makeSetup(NaN)
      expect(calculateFeaturedSetup('quiet', bullNaN, bearNaN, -5).side).toBe('bearish')
      expect(calculateFeaturedSetup('quiet', bullNaN, bearNaN, 5).side).toBe('bullish')

      // 5. Infinite scores
      const bullInf = makeSetup(Infinity)
      const bearFinite = makeSetup(99)
      expect(calculateFeaturedSetup('quiet', bullInf, bearFinite, 0).side).toBe('bullish')

      const bullNegInf = makeSetup(-Infinity)
      const bearZero2 = makeSetup(0)
      expect(calculateFeaturedSetup('quiet', bullNegInf, bearZero2, 0).side).toBe('bearish')
    })

    it('empirically verifies tie-breaking with negative, positive, and null signedScore', () => {
      const bull50 = makeSetup(50)
      const bear50 = makeSetup(50)

      // Signed score negative -> bearish
      expect(calculateFeaturedSetup('quiet', bull50, bear50, -0.0001).side).toBe('bearish')
      expect(calculateFeaturedSetup('quiet', bull50, bear50, -100).side).toBe('bearish')
      expect(calculateFeaturedSetup('two_way', bull50, bear50, -42).side).toBe('bearish')

      // Signed score positive -> bullish
      expect(calculateFeaturedSetup('quiet', bull50, bear50, 0.0001).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bull50, bear50, 100).side).toBe('bullish')
      expect(calculateFeaturedSetup('two_way', bull50, bear50, 42).side).toBe('bullish')

      // Signed score zero or null -> defaults to bullish
      expect(calculateFeaturedSetup('quiet', bull50, bear50, 0).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bull50, bear50, null).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bull50, bear50, undefined).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bull50, bear50, NaN).side).toBe('bullish')
    })

    it('stress-tests calculateRingOffset with extreme inputs', () => {
      const C = RING_CIRCUMFERENCE // ≈ 263.89

      // Positive bounds
      expect(calculateRingOffset(0)).toBeCloseTo(C, 4)
      expect(calculateRingOffset(100)).toBeCloseTo(0, 4)
      expect(calculateRingOffset(50)).toBeCloseTo(C * 0.5, 4)
      expect(calculateRingOffset(1000)).toBeCloseTo(0, 4) // Clamped to 100%
      expect(calculateRingOffset(Infinity)).toBeCloseTo(0, 4)

      // Negative bounds (Math.abs ensures progress renders)
      expect(calculateRingOffset(-0)).toBeCloseTo(C, 4)
      expect(calculateRingOffset(-50)).toBeCloseTo(C * 0.5, 4)
      expect(calculateRingOffset(-100)).toBeCloseTo(0, 4)
      expect(calculateRingOffset(-500)).toBeCloseTo(0, 4)
      expect(calculateRingOffset(-Infinity)).toBeCloseTo(0, 4)

      // Corrupted / missing
      expect(calculateRingOffset(null)).toBeCloseTo(C, 4)
      expect(calculateRingOffset(undefined)).toBeCloseTo(C, 4)
      expect(calculateRingOffset(NaN)).toBeCloseTo(C, 4)
      expect(Number.isFinite(calculateRingOffset(NaN))).toBe(true)
    })

    it('stress-tests formatNearSpotGex with extreme currency values', () => {
      // Standard positive & negative
      expect(formatNearSpotGex(10.55)).toBe('+$10.6M')
      expect(formatNearSpotGex(-10.55)).toBe('-$10.6M')
      expect(formatNearSpotGex(0)).toBe('+$0.0M')
      expect(formatNearSpotGex(-0)).toBe('+$0.0M')

      // Billions scale in millions
      expect(formatNearSpotGex(1500.4)).toBe('+$1500.4M')
      expect(formatNearSpotGex(-2450.8)).toBe('-$2450.8M')

      // Missing & Non-finite
      expect(formatNearSpotGex(null)).toBe('—')
      expect(formatNearSpotGex(undefined)).toBe('—')
      expect(formatNearSpotGex(NaN)).toBe('—')
      expect(formatNearSpotGex(Infinity)).toBe('+$InfinityM')
      expect(formatNearSpotGex(-Infinity)).toBe('-$InfinityM')
    })

    it('stress-tests calculateTrackWidthPct clamping and zero-division', () => {
      // Normal
      expect(calculateTrackWidthPct(50, 100)).toBe(50)
      expect(calculateTrackWidthPct(25, 50)).toBe(50)

      // Zero & negative denominator
      expect(calculateTrackWidthPct(50, 0)).toBe(0)
      expect(calculateTrackWidthPct(50, -100)).toBe(0)
      expect(calculateTrackWidthPct(50, null)).toBe(0)
      expect(calculateTrackWidthPct(50, NaN)).toBe(0)

      // Negative numerator clamped to 0
      expect(calculateTrackWidthPct(-50, 100)).toBe(0)
      expect(calculateTrackWidthPct(-0.001, 100)).toBe(0)

      // Overflow numerator clamped to 100
      expect(calculateTrackWidthPct(150, 100)).toBe(100)
      expect(calculateTrackWidthPct(1000, 100)).toBe(100)

      // Missing values
      expect(calculateTrackWidthPct(null, 100)).toBe(0)
      expect(calculateTrackWidthPct(undefined, 100)).toBe(0)
      expect(calculateTrackWidthPct(NaN, 100)).toBe(0)
    })
  })

  /* ==========================================================================
     2. OPTIONS FLOW CALCULATIONS & EXTREME BOUNDARY CONDITIONS
     ========================================================================== */
  describe('2. Options Flow Calculations & Boundary Conditions', () => {
    it('handles empty tape (0 prints, $0 premium) without division by zero', () => {
      const volOi = computeVolOiRatio(0, 0)
      expect(volOi.ratio).toBeNull()
      expect(volOi.formatted).toBe('0.00x')

      const volOiNull = computeVolOiRatio(null, null)
      expect(volOiNull.ratio).toBeNull()
      expect(volOiNull.formatted).toBe('0.00x')

      const dir = buildOptionsDirection(null, 'live')
      expect(dir).toBeDefined()
      expect(dir.headline).toBe('AWAITING DATA')
      expect(dir.score).toBeNull()
    })

    it('handles massive single print vs low volume ($50M print on 10 volume)', () => {
      const massivePrint: FlowOrderInput = {
        trade_class: 'sweep',
        is_sweep: true,
        aggressor: 'ask',
        premium: 50_000_000,
        volume: 10,
        open_interest: 5,
      }
      const classified = classifyFlowOrder(massivePrint)
      expect(classified.type).toBe('golden_sweep')
      expect(classified.label).toBe('GOLDEN SWEEP')

      const tier = classifyPremiumTier(50_000_000)
      expect(tier.tier).toBe('mega_whale')
      expect(tier.isWhale).toBe(true)

      const whale = flowWhaleTier(50_000_000)
      expect(whale.tier).toBe('1m')
      expect(whale.label).toBe('$1M+')
    })

    it('handles zero spot price ($0) and negative strikes safely', () => {
      // Moneyness formatting with 0 or negative otmPct
      expect(formatMoneyness(0)).toEqual({ label: 'ATM', className: 'moneyness-atm' })
      expect(formatMoneyness(0.005)).toEqual({ label: 'ATM', className: 'moneyness-atm' })
      expect(formatMoneyness(-0.005)).toEqual({ label: 'ATM', className: 'moneyness-atm' })
      expect(formatMoneyness(0.05)).toEqual({ label: 'OTM +5.0%', className: 'moneyness-otm' })
      expect(formatMoneyness(-0.05)).toEqual({ label: 'ITM -5.0%', className: 'moneyness-itm' })
      expect(formatMoneyness(null)).toEqual({ label: 'N/A', className: 'moneyness-none' })
      expect(formatMoneyness(undefined)).toEqual({ label: 'N/A', className: 'moneyness-none' })
      expect(formatMoneyness(NaN)).toEqual({ label: 'N/A', className: 'moneyness-none' })
      expect(formatMoneyness(Infinity)).toEqual({ label: 'N/A', className: 'moneyness-none' })
      expect(formatMoneyness(-Infinity)).toEqual({ label: 'N/A', className: 'moneyness-none' })
    })

    it('handles DTE badge formatting across boundary days (0D, 7D, 30D, 90D, 365D, negative, null)', () => {
      expect(formatDteBadge(0)).toEqual({ label: '0D', className: 'dte-0d' })
      expect(formatDteBadge(0.4)).toEqual({ label: '0D', className: 'dte-0d' })
      expect(formatDteBadge(1)).toEqual({ label: '1D', className: 'dte-weekly' })
      expect(formatDteBadge(7)).toEqual({ label: '7D', className: 'dte-weekly' })
      expect(formatDteBadge(8)).toEqual({ label: '8D', className: 'dte-monthly' })
      expect(formatDteBadge(30)).toEqual({ label: '30D', className: 'dte-monthly' })
      expect(formatDteBadge(31)).toEqual({ label: '31D', className: 'dte-quarterly' })
      expect(formatDteBadge(90)).toEqual({ label: '90D', className: 'dte-quarterly' })
      expect(formatDteBadge(91)).toEqual({ label: '91D', className: 'dte-leap' })
      expect(formatDteBadge(365)).toEqual({ label: '365D', className: 'dte-leap' })
      expect(formatDteBadge(null)).toEqual({ label: 'N/A', className: 'dte-unknown' })
      expect(formatDteBadge(undefined)).toEqual({ label: 'N/A', className: 'dte-unknown' })
      expect(formatDteBadge(NaN)).toEqual({ label: 'N/A', className: 'dte-unknown' })
    })

    it('verifies namedEmpty, mixShareLabel, concentrationLabel, and pulseWindowCopy robustness', () => {
      expect(namedEmpty(null, 'UNAVAILABLE')).toBe('UNAVAILABLE')
      expect(namedEmpty(undefined, 'EMPTY')).toBe('EMPTY')
      expect(namedEmpty('', 'EMPTY')).toBe('EMPTY')
      expect(namedEmpty(NaN, 'EMPTY')).toBe('EMPTY')
      expect(namedEmpty(Infinity, 'EMPTY')).toBe('EMPTY')
      expect(namedEmpty(42, 'EMPTY')).toBe('42')
      expect(namedEmpty('NVDA', 'EMPTY')).toBe('NVDA')

      expect(mixShareLabel(null, '50%')).toBe('NO MIX IN SAMPLE')
      expect(mixShareLabel(NaN, '50%')).toBe('NO MIX IN SAMPLE')
      expect(mixShareLabel(0.5, '50%')).toBe('50%')

      expect(concentrationLabel(null, 'NO STRIKE')).toBe('NO STRIKE')
      expect(concentrationLabel('Unavailable', 'NO STRIKE')).toBe('NO STRIKE')
      expect(concentrationLabel('$500 Call', 'NO STRIKE')).toBe('$500 Call')

      expect(
        pulseWindowCopy({
          baseline: true,
          newPrints: 5,
          newPremiumLabel: '$1M',
          windowDeltaLabel: '+$500k',
        }),
      ).toBe('first window baseline')
      expect(
        pulseWindowCopy({
          baseline: false,
          newPrints: 12,
          newPremiumLabel: '$2.5M',
          windowDeltaLabel: '+$1M',
        }),
      ).toBe('$2.5M · 12 new vs previous provider window')
      expect(
        pulseWindowCopy({
          baseline: false,
          newPrints: 0,
          newPremiumLabel: '$0',
          windowDeltaLabel: '+$0',
        }),
      ).toBe('+$0 vs previous provider window')
    })
  })

  /* ==========================================================================
     3. EXHAUSTIVE FORMATTING & CLEAN NUMERIC FALLBACK STRESS TABLE
     ========================================================================== */
  describe('3. Exhaustive Formatter Missing-Data Matrix', () => {
    // Anything here is "no measurement", not "a measurement of zero". JS would
    // coerce most of them to 0 (Number('') === 0, Number([]) === 0), which is
    // exactly why they are enumerated: a zero that means "missing" misreads as
    // flat gamma / zero spot on a trading surface.
    const missingInputs: unknown[] = [
      null,
      undefined,
      NaN,
      Infinity,
      -Infinity,
      '',
      '   ',
      'invalid_string',
      {},
      [],
    ]

    it('optNum returns DASH for every missing input and formats real numbers', () => {
      for (const val of missingInputs) {
        expect(optNum(val, 2)).toBe(DASH)
      }
      expect(optNum(0)).toBe('0.00')
      expect(optNum(-0)).toBe('-0.00')
      expect(optNum(1234.5678)).toBe('1,234.57')
      expect(optNum(-42.1, 1)).toBe('-42.1')
    })

    it('optPct returns DASH for every missing input and formats real percentages', () => {
      for (const val of missingInputs) {
        expect(optPct(val, 2)).toBe(DASH)
      }
      expect(optPct(12.5)).toBe('12.50%')
      expect(optPct(0)).toBe('0.00%')
    })

    it('optPctFrac returns DASH for every missing input and converts real fractions', () => {
      for (const val of missingInputs) {
        expect(optPctFrac(val, 2)).toBe(DASH)
      }
      expect(optPctFrac(0.125)).toBe('12.50%')
      expect(optPctFrac(0)).toBe('0.00%')
    })

    it('optSignedPct returns DASH for every missing input and keeps an explicit sign', () => {
      for (const val of missingInputs) {
        expect(optSignedPct(val, 2)).toBe(DASH)
      }
      expect(optSignedPct(5.5)).toBe('+5.50%')
      expect(optSignedPct(-3.2)).toBe('-3.20%')
    })

    it('optSigned returns DASH for every missing input and keeps an explicit sign', () => {
      for (const val of missingInputs) {
        expect(optSigned(val, 2)).toBe(DASH)
      }
      expect(optSigned(10)).toBe('+10.00')
      expect(optSigned(-10)).toBe('-10.00')
    })

    it('optCompact returns DASH for every missing input and abbreviates real magnitudes', () => {
      for (const val of missingInputs) {
        expect(optCompact(val, 1)).toBe(DASH)
      }
      expect(optCompact(1_500_000)).toBe('1.5M')
      expect(optCompact(25_000)).toBe('25.0K')
    })

    it('optUsd returns DASH for every missing input and formats real currency', () => {
      for (const val of missingInputs) {
        expect(optUsd(val, 2)).toBe(DASH)
      }
      expect(optUsd(100)).toBe('$100.00')
      expect(optUsd(0)).toBe('$0.00')
    })

    it('optGex returns DASH for every missing input and scales real M/B values', () => {
      for (const val of missingInputs) {
        expect(optGex(val, 1)).toBe(DASH)
      }
      expect(optGex(0)).toBe('$0.0M')
      expect(optGex(12.4)).toBe('$12.4M')
      expect(optGex(-5.2)).toBe('-$5.2M')
      expect(optGex(2500)).toBe('$2.5B')
      expect(optGex(-1800)).toBe('-$1.8B')
    })

    it('never emits a NaN string for any input', () => {
      const all = [...missingInputs, 0, -0, 1234.5678, -42.1]
      for (const val of all) {
        for (const out of [
          optNum(val, 2),
          optPct(val, 2),
          optPctFrac(val, 2),
          optSignedPct(val, 2),
          optSigned(val, 2),
          optCompact(val, 1),
          optUsd(val, 2),
          optGex(val, 1),
        ]) {
          expect(typeof out).toBe('string')
          expect(out).not.toContain('NaN')
          expect(out.length).toBeGreaterThanOrEqual(1)
        }
      }
    })
  })

  /* ==========================================================================
     4. CHART GEOMETRY MATH & RESILIENCE
     ========================================================================== */
  describe('4. Chart Geometry Math, Inverted Strikes & Extreme Layouts', () => {
    it('handles 0-width and 0-height linear scales without dividing by zero or throwing', () => {
      // 1. Zero-width domain [100, 100]
      const scaleZeroDomain = linearScale([100, 100], [0, 500])
      expect(Number.isFinite(scaleZeroDomain(100))).toBe(true)
      expect(Number.isFinite(scaleZeroDomain(150))).toBe(true)

      // 2. Zero-width range [200, 200]
      const scaleZeroRange = linearScale([0, 100], [200, 200])
      expect(scaleZeroRange(50)).toBe(200)

      // 3. Invert of linear scale with zero domain
      expect(Number.isFinite(scaleZeroDomain.invert(250))).toBe(true)
    })

    it('handles inverted strikes (descending strikes input) properly', () => {
      const rawRows: GexStrikeRow[] = [
        { strike: 550, call_gex_m: 10, put_gex_m: -5, net_gex_m: 5, call_oi: 1000, put_oi: 500 },
        { strike: 525, call_gex_m: 20, put_gex_m: -10, net_gex_m: 10, call_oi: 2000, put_oi: 1000 },
        { strike: 500, call_gex_m: 50, put_gex_m: -20, net_gex_m: 30, call_oi: 5000, put_oi: 2000 },
        { strike: 475, call_gex_m: 5, put_gex_m: -30, net_gex_m: -25, call_oi: 500, put_oi: 3000 },
      ]

      // When sorted ascending
      const sorted = [...rawRows].sort((a, b) => a.strike - b.strike)
      expect(sorted[0].strike).toBe(475)
      expect(sorted[sorted.length - 1].strike).toBe(550)

      // niceTicks on strike range
      const ticks = niceTicks(sorted[0].strike, sorted[sorted.length - 1].strike, 5)
      expect(ticks.length).toBeGreaterThanOrEqual(2)
      expect(ticks[0]).toBeGreaterThanOrEqual(475)
      expect(ticks[ticks.length - 1]).toBeLessThanOrEqual(550)
    })

    it('handles purely negative GEX profiles without division by zero or NaN coordinate offsets', () => {
      const negRows: GexStrikeRow[] = [
        { strike: 100, call_gex_m: 0, put_gex_m: -50, net_gex_m: -50, call_oi: 0, put_oi: 5000 },
        { strike: 105, call_gex_m: 0, put_gex_m: -80, net_gex_m: -80, call_oi: 0, put_oi: 8000 },
        { strike: 110, call_gex_m: 0, put_gex_m: -30, net_gex_m: -30, call_oi: 0, put_oi: 3000 },
      ]

      // maxAbs calculation
      const maxAbs = Math.max(
        1e-9,
        ...negRows.map((r) =>
          Math.max(Math.abs(r.call_gex_m), Math.abs(r.put_gex_m), Math.abs(r.net_gex_m)),
        ),
      )
      expect(maxAbs).toBe(80)

      const halfPlotH = 100
      const zeroY = 150

      const barCalculations = negRows.map((r) => {
        const putH = Math.max(
          r.put_gex_m !== 0 ? 2 : 0,
          (Math.abs(r.put_gex_m) / maxAbs) * halfPlotH,
        )
        const netY = zeroY - (r.net_gex_m / maxAbs) * halfPlotH
        return { putH, netY }
      })

      expect(barCalculations[1].putH).toBe(100) // 80/80 * 100
      expect(barCalculations[1].netY).toBe(250) // 150 - (-80/80)*100 = 250 (placed below zero line)
      expect(barCalculations.every((b) => Number.isFinite(b.putH) && Number.isFinite(b.netY))).toBe(
        true,
      )
    })

    it('generates valid SVG linePath for empty, single point, and multi-point series', () => {
      expect(linePath([])).toBe('')
      expect(linePath([{ x: 10, y: 20 }])).toBe('M10,20')
      expect(
        linePath([
          { x: 10, y: 20 },
          { x: 30, y: 40 },
        ]),
      ).toBe('M10,20L30,40')
    })
  })
})
