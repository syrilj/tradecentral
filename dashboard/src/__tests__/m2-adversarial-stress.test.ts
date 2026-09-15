import { describe, expect, it } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import type { OptionsBoardRow, OptionsSqueeze, SqueezeSetup } from '@/api'
import {
  calculateFeaturedSetup,
  buildLevelLadder,
  gammaRegimeSide,
  freshnessTier,
  formatSignedScore,
  distanceFromSpot,
} from '@/squeezeCalc'
import { buildOptionsDirection, type OptionsDirectionSummary } from '@/optionsDirection'
import SqueezeScreener from '@/components/SqueezeScreener.vue'
import OptionsDirectionBrief from '@/components/OptionsDirectionBrief.vue'
import { computePressureScore } from '@/components/OptionsConvictionBoard.vue'

function mockSetup(
  side: 'bullish' | 'bearish',
  score: number,
  overrides: Partial<SqueezeSetup> = {},
): SqueezeSetup {
  return {
    side,
    score,
    score_01: score / 100,
    likelihood:
      score >= 75 ? 'imminent' : score >= 55 ? 'likely' : score >= 35 ? 'possible' : 'unlikely',
    factors: [
      {
        id: 'prox',
        label: 'Wall Proximity',
        score: Math.round(score * 0.4),
        max: 40,
        detail: 'prox',
      },
      {
        id: 'gamma',
        label: 'Gamma Concentration',
        score: Math.round(score * 0.3),
        max: 30,
        detail: 'gamma',
      },
      {
        id: 'flow',
        label: 'Flow Momentum',
        score: Math.round(score * 0.3),
        max: 30,
        detail: 'flow',
      },
    ],
    setup_analysis: [`${side === 'bullish' ? 'Call' : 'Put'} wall structure`],
    for_stronger: ['Requires delta flow'],
    trading_implication: `${side === 'bullish' ? 'Upside' : 'Downside'} pressure`,
    spot: 100,
    wall: side === 'bullish' ? 110 : 90,
    wall_pct: side === 'bullish' ? 0.1 : -0.1,
    ...overrides,
  }
}

describe('Adversarial Stress Suite - calculateFeaturedSetup Boundary & Tie-Breaking', () => {
  describe('1. SignedScore Boundary Values & Floating Point Subnormals', () => {
    it('handles +0.0 and -0.0 as neutral/zero signedScore falling back to structure', () => {
      const bullHigher = mockSetup('bullish', 50)
      const bearLower = mockSetup('bearish', 20)
      const bullLower = mockSetup('bullish', 20)
      const bearHigher = mockSetup('bearish', 50)

      // +0.0
      expect(calculateFeaturedSetup('quiet', bullHigher, bearLower, +0.0).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bullLower, bearHigher, +0.0).side).toBe('bearish')

      // -0.0
      expect(calculateFeaturedSetup('quiet', bullHigher, bearLower, -0.0).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bullLower, bearHigher, -0.0).side).toBe('bearish')
    })

    it('handles Number.MIN_VALUE and tiny positive/negative floats', () => {
      const bull = mockSetup('bullish', 10)
      const bear = mockSetup('bearish', 90)

      // Tiny positive float > 0 -> should pick bullish despite bear having 90 vs bull 10
      expect(calculateFeaturedSetup('quiet', bull, bear, Number.MIN_VALUE).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bull, bear, Number.EPSILON).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bull, bear, 1e-15).side).toBe('bullish')

      // Tiny negative float < 0 -> should pick bearish despite bull having 90 vs bear 10
      const bullHigh = mockSetup('bullish', 90)
      const bearLow = mockSetup('bearish', 10)
      expect(calculateFeaturedSetup('quiet', bullHigh, bearLow, -Number.MIN_VALUE).side).toBe(
        'bearish',
      )
      expect(calculateFeaturedSetup('quiet', bullHigh, bearLow, -Number.EPSILON).side).toBe(
        'bearish',
      )
      expect(calculateFeaturedSetup('quiet', bullHigh, bearLow, -1e-15).side).toBe('bearish')
    })

    it('handles extreme float bounds: MAX_VALUE, Infinity, -Infinity, NaN', () => {
      const bull = mockSetup('bullish', 20)
      const bear = mockSetup('bearish', 80)

      // Number.MAX_VALUE
      expect(calculateFeaturedSetup('quiet', bull, bear, Number.MAX_VALUE).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bull, bear, -Number.MAX_VALUE).side).toBe('bearish')

      // Infinity & -Infinity (isFinite -> false -> sc = 0 -> falls back to structure rs > bs -> bearish)
      expect(calculateFeaturedSetup('quiet', bull, bear, Infinity).side).toBe('bearish')
      expect(calculateFeaturedSetup('quiet', bull, bear, -Infinity).side).toBe('bearish')

      // NaN (sc = 0 -> falls back to structure rs > bs -> bearish)
      expect(calculateFeaturedSetup('quiet', bull, bear, NaN).side).toBe('bearish')
      expect(calculateFeaturedSetup('quiet', bull, bear, Number('invalid')).side).toBe('bearish')
    })

    it('handles null, undefined, and non-number types in signedScore safely', () => {
      const bull = mockSetup('bullish', 30)
      const bear = mockSetup('bearish', 70)

      expect(calculateFeaturedSetup('quiet', bull, bear, null).side).toBe('bearish')
      expect(calculateFeaturedSetup('quiet', bull, bear, undefined).side).toBe('bearish')
      // @ts-expect-error test runtime robustness against bad typing
      expect(calculateFeaturedSetup('quiet', bull, bear, 'positive').side).toBe('bearish')
    })
  })

  describe('2. Primary String Variants and Robust Parsing', () => {
    it('correctly matches case-insensitive and substring primary variations', () => {
      const bull = mockSetup('bullish', 10)
      const bear = mockSetup('bearish', 90)

      expect(calculateFeaturedSetup('BULLISH', bull, bear, -50).side).toBe('bullish')
      expect(calculateFeaturedSetup('BEARISH', bull, bear, 50).side).toBe('bearish')
      expect(calculateFeaturedSetup('  bullish  ', bull, bear, -50).side).toBe('bullish')
      expect(calculateFeaturedSetup('  BEARISH  ', bull, bear, 50).side).toBe('bearish')
      expect(calculateFeaturedSetup('bull_squeeze', bull, bear, -50).side).toBe('bullish')
      expect(calculateFeaturedSetup('bear_squeeze', bull, bear, 50).side).toBe('bearish')
    })

    it('treats non-bull/bear primary strings as non-directional falling back to signedScore', () => {
      const bull = mockSetup('bullish', 10)
      const bear = mockSetup('bearish', 90)

      expect(calculateFeaturedSetup('neutral', bull, bear, 10).side).toBe('bullish')
      expect(calculateFeaturedSetup('neutral', bull, bear, -10).side).toBe('bearish')
      expect(calculateFeaturedSetup('two_way', bull, bear, 10).side).toBe('bullish')
      expect(calculateFeaturedSetup('two_way', bull, bear, -10).side).toBe('bearish')
      expect(calculateFeaturedSetup('', bull, bear, 10).side).toBe('bullish')
      expect(calculateFeaturedSetup('', bull, bear, -10).side).toBe('bearish')
    })
  })

  describe('3. Missing, Partial, and Degenerate Setup Objects', () => {
    it('returns available setup when only one setup is defined', () => {
      const bull = mockSetup('bullish', 50)

      // Only bull defined
      const resOnlyBull = calculateFeaturedSetup('quiet', bull, undefined, -20)
      expect(resOnlyBull.side).toBe('bearish')
      expect(resOnlyBull.setup).toBe(bull) // Fallback to available setup

      // Only bear defined
      const bear = mockSetup('bearish', 50)
      const resOnlyBear = calculateFeaturedSetup('quiet', undefined, bear, 20)
      expect(resOnlyBear.side).toBe('bullish')
      expect(resOnlyBear.setup).toBe(bear) // Fallback to available setup
    })

    it('returns undefined setup safely when both setups are undefined', () => {
      const resBothUndef = calculateFeaturedSetup('quiet', undefined, undefined, 10)
      expect(resBothUndef.side).toBe('bullish')
      expect(resBothUndef.setup).toBeUndefined()

      const resBothUndefNeg = calculateFeaturedSetup('quiet', undefined, undefined, -10)
      expect(resBothUndefNeg.side).toBe('bearish')
      expect(resBothUndefNeg.setup).toBeUndefined()
    })

    it('handles setups with missing or NaN scores gracefully', () => {
      // @ts-expect-error test missing score
      const bullNoScore: SqueezeSetup = { side: 'bullish' }
      // @ts-expect-error test NaN score
      const bearNanScore: SqueezeSetup = { side: 'bearish', score: NaN }

      // Both scores resolve to 0 via bs = bull?.score ?? 0 -> tie defaults to bullish
      const res = calculateFeaturedSetup('quiet', bullNoScore, bearNanScore, 0)
      expect(res.side).toBe('bullish')
      expect(res.setup).toBe(bullNoScore)
    })

    it('handles NaN in bull.score or bear.score when signedScore is 0', () => {
      // bull.score is NaN, bear.score is 50
      // @ts-expect-error test NaN
      const bullNan: SqueezeSetup = { side: 'bullish', score: NaN }
      const bear50 = mockSetup('bearish', 50)

      // In JS: (50 > NaN) is false, (NaN > 50) is false, defaults to bullish
      const res1 = calculateFeaturedSetup('quiet', bullNan, bear50, 0)
      expect(res1.side).toBe('bullish')

      // bear.score is NaN, bull.score is 50
      const bull50 = mockSetup('bullish', 50)
      // @ts-expect-error test NaN
      const bearNan: SqueezeSetup = { side: 'bearish', score: NaN }
      const res2 = calculateFeaturedSetup('quiet', bull50, bearNan, 0)
      expect(res2.side).toBe('bullish')
    })
  })
})

describe('Adversarial Stress Suite - computePressureScore Microstructure Rigor', () => {
  function makeRow(overrides: Partial<OptionsBoardRow> = {}): OptionsBoardRow {
    return {
      symbol: 'TEST',
      rank: 1,
      selection_basis: 'live_options_flow',
      selection_basis_note: '',
      selection_score: 1.0,
      score_kind: 'ordinal_score',
      context_side: 'bullish',
      sources: ['tape'],
      decision_authorized: false,
      available: true,
      spot: 100,
      squeeze_score: null,
      squeeze_label: null,
      squeeze_primary: 'quiet',
      structure_score: null,
      long_gamma_dampened: false,
      net_gex_m: null,
      gex_regime: 'pos_gamma',
      call_wall: 110,
      put_wall: 90,
      gamma_flip: 95,
      pin_strike: 100,
      call_premium: 0,
      put_premium: 0,
      activity_imbalance: null,
      expected_move: 5,
      atm_iv: 0.3,
      warnings: [],
      ...overrides,
    }
  }

  it('clamps extreme squeeze_score to [-100, 100]', () => {
    const rowHigh = makeRow({ squeeze_score: 99999, call_premium: 200_000 })
    const resHigh = computePressureScore(rowHigh)
    expect(resHigh.signed).toBe(100)
    expect(resHigh.score).toBe(100)
    expect(resHigh.label).toBe('+100.0')
    expect(resHigh.tone).toBe('pos')

    const rowLow = makeRow({ squeeze_score: -99999, put_premium: 200_000 })
    const resLow = computePressureScore(rowLow)
    expect(resLow.signed).toBe(-100)
    expect(resLow.score).toBe(100)
    expect(resLow.label).toBe('-100.0')
    expect(resLow.tone).toBe('neg')
  })

  it('applies minimum dampener of 0.15 for very small live prints ($100)', () => {
    const rowTiny = makeRow({
      selection_basis: 'live_options_flow',
      squeeze_score: 40,
      call_premium: 100,
      put_premium: 0,
    })
    const res = computePressureScore(rowTiny)
    // dampener is Math.max(0.15, 100 / 100_000 = 0.001) = 0.15
    expect(res.signed).toBeCloseTo(40 * 0.15, 2)
    expect(res.tone).toBe('pos')
  })

  it('does not dampen when total premium is zero or selection_basis is not live_options_flow', () => {
    const rowPEAD = makeRow({
      selection_basis: 'pead_ordinal',
      squeeze_score: 40,
      call_premium: 100,
      put_premium: 0,
    })
    const res = computePressureScore(rowPEAD)
    expect(res.signed).toBe(40)
  })

  it('correctly formats Net GEX without pos/neg tone conflation across zero, positive, negative, and extreme values', () => {
    expect(computePressureScore(makeRow({ net_gex_m: 0 })).label).toBe('0.0M')
    expect(computePressureScore(makeRow({ net_gex_m: 0 })).tone).toBe('neutral')

    expect(computePressureScore(makeRow({ net_gex_m: 150.25 })).label).toBe('+150.3M')
    expect(computePressureScore(makeRow({ net_gex_m: 150.25 })).tone).toBe('neutral')

    expect(computePressureScore(makeRow({ net_gex_m: -275.84 })).label).toBe('-275.8M')
    expect(computePressureScore(makeRow({ net_gex_m: -275.84 })).tone).toBe('neutral')
  })
})

describe('Adversarial Stress Suite - Supporting Squeeze Helpers Rigor', () => {
  it('validates formatSignedScore with zero, signed zero, and non-finite numbers', () => {
    expect(formatSignedScore(null)).toBe('—')
    expect(formatSignedScore(undefined)).toBe('—')
    expect(formatSignedScore(NaN)).toBe('—')
    expect(formatSignedScore(Infinity)).toBe('—')
    expect(formatSignedScore(0)).toBe('0')
    expect(formatSignedScore(-0)).toBe('0')
    expect(formatSignedScore(0.00001)).toBe('0')
    expect(formatSignedScore(-0.00001)).toBe('0')
    expect(formatSignedScore(15.4)).toBe('+15.4')
    expect(formatSignedScore(-15.4)).toBe('-15.4')
  })

  it('validates gammaRegimeSide under normal and boundary spot/flip values', () => {
    expect(gammaRegimeSide(null, 100)).toBe('unmeasured')
    expect(gammaRegimeSide(100, null)).toBe('unmeasured')
    expect(gammaRegimeSide(105, 100)).toBe('above_flip')
    expect(gammaRegimeSide(95, 100)).toBe('below_flip')
    expect(gammaRegimeSide(100, 100)).toBe('at_flip')
  })

  it('validates distanceFromSpot with non-positive or non-finite inputs', () => {
    expect(distanceFromSpot(null, 100)).toBeNull()
    expect(distanceFromSpot(100, null)).toBeNull()
    expect(distanceFromSpot(100, 0)).toBeNull()
    expect(distanceFromSpot(100, -10)).toBeNull()
    expect(distanceFromSpot(110, 100)).toEqual({ delta: 10, pct: 0.1 })
    expect(distanceFromSpot(90, 100)).toEqual({ delta: -10, pct: -0.1 })
  })

  it('validates freshnessTier across boundary seconds and modes', () => {
    expect(freshnessTier(10, 'live')).toBe('live')
    expect(freshnessTier(100, 'live')).toBe('delayed')
    expect(freshnessTier(1000, 'live')).toBe('stale')
    expect(freshnessTier(10, 'history_mode')).toBe('history')
    expect(freshnessTier(10, 'unavailable')).toBe('unknown')
    expect(freshnessTier(null, 'live')).toBe('unknown')
    expect(freshnessTier(-5, 'live')).toBe('unknown')
  })

  it('validates buildLevelLadder ordering and unmeasured sinking', () => {
    const ladder = buildLevelLadder({
      side: 'bullish',
      spot: 100,
      callWall: 120,
      putWall: 80,
      gammaFlip: null,
      pinStrike: 105,
    })

    // Measured levels sorted high to low: 120 (call_wall), 105 (pin), 100 (spot), 80 (put_wall)
    expect(ladder[0].level).toBe(120)
    expect(ladder[1].level).toBe(105)
    expect(ladder[2].level).toBe(100)
    expect(ladder[3].level).toBe(80)
    // Unmeasured sinks to bottom
    expect(ladder[4].id).toBe('gamma_flip')
    expect(ladder[4].level).toBeNull()
  })
})

describe('Adversarial Stress Suite - SSR Rendering & Component Resilience', () => {
  it('renders SqueezeScreener with completely empty/null payload without throwing or crashing', async () => {
    const app = createSSRApp({
      render: () =>
        h(SqueezeScreener, {
          squeeze: null,
          spot: null,
        }),
    })
    const html = await renderToString(app)
    expect(html).toContain('Squeeze unavailable')
    expect(html).not.toContain('NaN')
  })

  it('renders SqueezeScreener with degenerate numeric values (Infinity, NaN, negative prices) cleanly', async () => {
    const degenerateSqueeze: OptionsSqueeze = {
      bullish: NaN,
      bearish: NaN,
      score: NaN,
      label: 'quiet',
      primary: 'quiet',
      drivers: [],
      negative_fuel: undefined,
      long_gamma_dampened: false,
      key_levels: {
        spot: -50,
        call_wall: NaN,
        call_wall_pct: null,
        put_wall: null,
        put_wall_pct: null,
        gamma_flip: null,
        gamma_flip_pct: null,
        pin_strike: Infinity,
        near_spot_net_gex_m: NaN,
      },
      bullish_setup: mockSetup('bullish', 0, { spot: -50, wall: NaN, wall_pct: null, score: 0 }),
      bearish_setup: mockSetup('bearish', 0, {
        spot: -50,
        wall: null,
        wall_pct: undefined,
        score: 0,
      }),
    }

    const app = createSSRApp({
      render: () =>
        h(SqueezeScreener, {
          squeeze: degenerateSqueeze,
          spot: -50,
        }),
    })
    const html = await renderToString(app)
    expect(html).not.toContain('NaN')
    expect(html).not.toContain('Infinity')
    // A NaN score is unmeasured — no side is invented for it.
    expect(html).toContain('class="sq neutral"')
    expect(html).toContain('UNMEASURED')
  })

  it('renders OptionsDirectionBrief with unmeasured/degenerate summary cleanly without crashing', async () => {
    const emptyDir = buildOptionsDirection(null, 'missing')
    const app = createSSRApp({
      render: () =>
        h(OptionsDirectionBrief, {
          symbol: 'EMPTY',
          read: emptyDir,
          spot: null,
          callWall: null,
          putWall: null,
          gammaFlip: null,
        }),
    })
    const html = await renderToString(app)
    expect(html).toContain('AWAITING DATA')
    expect(html).toContain('direction-brief rise unavailable')
    expect(html).not.toContain('NaN')
  })

  it('maintains strict visual alignment across Bullish, Bearish, and Mixed market states in SSR', async () => {
    // 1. Bullish scenario
    const bullSummary: OptionsDirectionSummary = {
      signed_flow_imbalance: 0.75,
      signed_flow_confidence: 0.9,
      gamma_flip: 90,
      call_wall: 120,
      put_wall: 85,
      squeeze: {
        bullish: 0.7,
        bearish: 0.1,
        score: 35.0,
        label: 'bullish',
        primary: 'bullish',
        drivers: ['signed_bullish_flow'],
        key_levels: {
          spot: 100,
          call_wall: 120,
          call_wall_pct: null,
          put_wall: 85,
          put_wall_pct: null,
          gamma_flip: 90,
          gamma_flip_pct: null,
          pin_strike: null,
        },
        bullish_setup: mockSetup('bullish', 35, { wall: 120 }),
        bearish_setup: mockSetup('bearish', 10, { wall: 85 }),
        theory: { momentum: 0.02, momentum_fresh: true },
      },
    }
    const bullRead = buildOptionsDirection(bullSummary, 'live')
    const bullBriefApp = createSSRApp({
      render: () =>
        h(OptionsDirectionBrief, {
          symbol: 'NVDA',
          read: bullRead,
          spot: 100,
          callWall: 120,
          putWall: 85,
          gammaFlip: 90,
        }),
    })
    const bullBriefHtml = await renderToString(bullBriefApp)
    expect(bullBriefHtml).toContain('direction-brief rise bullish')
    expect(bullBriefHtml).toContain('BULLISH')

    const bullScreenerApp = createSSRApp({
      render: () => h(SqueezeScreener, { squeeze: bullSummary.squeeze, spot: 100 }),
    })
    const bullScreenerHtml = await renderToString(bullScreenerApp)
    expect(bullScreenerHtml).toContain('class="sq bullish"')

    // 2. Bearish scenario
    const bearSummary: OptionsDirectionSummary = {
      signed_flow_imbalance: -0.75,
      signed_flow_confidence: 0.9,
      gamma_flip: 110,
      call_wall: 115,
      put_wall: 80,
      squeeze: {
        bullish: 0.1,
        bearish: 0.7,
        score: -35.0,
        label: 'bearish',
        primary: 'bearish',
        drivers: ['signed_bearish_flow'],
        key_levels: {
          spot: 100,
          call_wall: 115,
          call_wall_pct: null,
          put_wall: 80,
          put_wall_pct: null,
          gamma_flip: 110,
          gamma_flip_pct: null,
          pin_strike: null,
        },
        bullish_setup: mockSetup('bullish', 10, { wall: 115 }),
        bearish_setup: mockSetup('bearish', 35, { wall: 80 }),
        theory: { momentum: -0.02, momentum_fresh: true },
      },
    }
    const bearRead = buildOptionsDirection(bearSummary, 'live')
    const bearBriefApp = createSSRApp({
      render: () =>
        h(OptionsDirectionBrief, {
          symbol: 'TSLA',
          read: bearRead,
          spot: 100,
          callWall: 115,
          putWall: 80,
          gammaFlip: 110,
        }),
    })
    const bearBriefHtml = await renderToString(bearBriefApp)
    expect(bearBriefHtml).toContain('direction-brief rise bearish')
    expect(bearBriefHtml).toContain('BEARISH')

    const bearScreenerApp = createSSRApp({
      render: () => h(SqueezeScreener, { squeeze: bearSummary.squeeze, spot: 100 }),
    })
    const bearScreenerHtml = await renderToString(bearScreenerApp)
    expect(bearScreenerHtml).toContain('class="sq bearish"')
  })
})
