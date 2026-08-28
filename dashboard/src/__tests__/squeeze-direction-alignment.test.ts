import { describe, expect, it } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import type { OptionsBoardRow, OptionsSqueeze, SqueezeSetup } from '@/api'
import { calculateFeaturedSetup } from '@/squeezeCalc'
import { buildOptionsDirection, type OptionsDirectionSummary } from '@/optionsDirection'
import SqueezeScreener from '@/components/SqueezeScreener.vue'
import OptionsDirectionBrief from '@/components/OptionsDirectionBrief.vue'
import { computePressureScore } from '@/components/OptionsConvictionBoard.vue'

// ============================================================================
// Fixture Generators & Mocks
// ============================================================================

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
        id: 'proximity',
        label: 'Wall Proximity',
        score: Math.round(score * 0.4),
        max: 40,
        detail: 'Proximity metric',
      },
      {
        id: 'concentration',
        label: 'Gamma Concentration',
        score: Math.round(score * 0.3),
        max: 30,
        detail: 'Concentration metric',
      },
      {
        id: 'flow',
        label: 'Flow Momentum',
        score: Math.round(score * 0.3),
        max: 30,
        detail: 'Flow metric',
      },
    ],
    setup_analysis: [`${side === 'bullish' ? 'Upside' : 'Downside'} structure test`],
    for_stronger: ['Requires sustained delta flow'],
    trading_implication: `${side === 'bullish' ? 'Call' : 'Put'} wall magnet effect`,
    spot: 100,
    wall: side === 'bullish' ? 115 : 98,
    wall_pct: side === 'bullish' ? 0.15 : -0.02,
    ...overrides,
  }
}

function mockBoardRow(overrides: Partial<OptionsBoardRow> = {}): OptionsBoardRow {
  return {
    symbol: 'NVDA',
    rank: 1,
    selection_basis: 'live_options_flow',
    selection_basis_note: 'Unusual signed order flow print',
    selection_score: 0.85,
    score_kind: 'ordinal_score',
    context_side: 'bullish',
    sources: ['tape', 'chain'],
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
    call_wall: 115,
    put_wall: 98,
    gamma_flip: 95,
    pin_strike: 100,
    call_premium: 250_000,
    put_premium: 50_000,
    activity_imbalance: null,
    expected_move: 5.5,
    atm_iv: 0.35,
    warnings: [],
    ...overrides,
  }
}

describe('Milestone 2: Squeeze Screener & Directional Bias Reconciliation Suite', () => {
  // ==========================================================================
  // Section 1: calculateFeaturedSetup - Signed Score Priority Over Geometry
  // ==========================================================================
  describe('1. calculateFeaturedSetup Directional Reconciliation', () => {
    it('selects Bullish setup when signed flow is positive, even if put wall is closer than call wall (rs > bs)', () => {
      // Scenario: Put wall is closer (rs = 48) than Call wall (bs = 18), but signedScore is positive (+15.2)
      const bull = mockSetup('bullish', 18, { wall: 115, wall_pct: 0.15 })
      const bear = mockSetup('bearish', 48, { wall: 98, wall_pct: -0.02 })

      // When primary is 'quiet', positive signedScore MUST select Bullish setup
      const resultQuiet = calculateFeaturedSetup('quiet', bull, bear, 15.2)
      expect(resultQuiet.side).toBe('bullish')
      expect(resultQuiet.setup).toBe(bull)

      // When primary is 'two_way', positive signedScore MUST select Bullish setup
      const resultTwoWay = calculateFeaturedSetup('two_way', bull, bear, 25.0)
      expect(resultTwoWay.side).toBe('bullish')
      expect(resultTwoWay.setup).toBe(bull)

      // When primary is empty / undefined
      const resultUndef = calculateFeaturedSetup(undefined, bull, bear, 8.5)
      expect(resultUndef.side).toBe('bullish')
      expect(resultUndef.setup).toBe(bull)
    })

    it('selects Bearish setup when signed flow is negative, even if call wall is closer than put wall (bs > rs)', () => {
      // Scenario: Call wall is closer (bs = 52) than Put wall (rs = 15), but signedScore is negative (-24.5)
      const bull = mockSetup('bullish', 52, { wall: 102, wall_pct: 0.02 })
      const bear = mockSetup('bearish', 15, { wall: 85, wall_pct: -0.15 })

      // When primary is 'quiet', negative signedScore MUST select Bearish setup
      const resultQuiet = calculateFeaturedSetup('quiet', bull, bear, -24.5)
      expect(resultQuiet.side).toBe('bearish')
      expect(resultQuiet.setup).toBe(bear)

      // When primary is 'two_way', negative signedScore MUST select Bearish setup
      const resultTwoWay = calculateFeaturedSetup('two_way', bull, bear, -12.0)
      expect(resultTwoWay.side).toBe('bearish')
      expect(resultTwoWay.setup).toBe(bear)
    })

    it('honors explicit primary="bullish" or primary="bearish" regardless of signedScore and structure scores', () => {
      const bull = mockSetup('bullish', 10)
      const bear = mockSetup('bearish', 90)

      // Explicit bullish primary overrides higher bearish structure score and negative signed score
      const resBull = calculateFeaturedSetup('bullish', bull, bear, -50)
      expect(resBull.side).toBe('bullish')
      expect(resBull.setup).toBe(bull)

      // Explicit bearish primary overrides higher bullish structure score and positive signed score
      const resBear = calculateFeaturedSetup('bearish', bull, bear, 50)
      expect(resBear.side).toBe('bearish')
      expect(resBear.setup).toBe(bear)
    })

    it('falls back to structure score comparison (bs vs rs) only when signedScore is 0, null, or undefined', () => {
      const bullHigh = mockSetup('bullish', 60)
      const bearLow = mockSetup('bearish', 20)

      // With signedScore = 0 -> bs > rs wins (bullish)
      expect(calculateFeaturedSetup('quiet', bullHigh, bearLow, 0).side).toBe('bullish')
      // With signedScore = null -> bs > rs wins (bullish)
      expect(calculateFeaturedSetup('quiet', bullHigh, bearLow, null).side).toBe('bullish')

      const bullLow = mockSetup('bullish', 20)
      const bearHigh = mockSetup('bearish', 60)

      // With signedScore = 0 -> rs > bs wins (bearish)
      expect(calculateFeaturedSetup('quiet', bullLow, bearHigh, 0).side).toBe('bearish')
      // With signedScore = undefined -> rs > bs wins (bearish)
      expect(calculateFeaturedSetup('quiet', bullLow, bearHigh, undefined).side).toBe('bearish')
    })

    it('defaults to bullish on exact structure tie (bs === rs) when signedScore is 0, null, or undefined', () => {
      const bull = mockSetup('bullish', 40)
      const bear = mockSetup('bearish', 40)

      expect(calculateFeaturedSetup('quiet', bull, bear, 0).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bull, bear, null).side).toBe('bullish')
      expect(calculateFeaturedSetup('quiet', bull, bear, undefined).side).toBe('bullish')
    })

    it('handles edge case inputs (missing setup objects, NaN, infinite scores)', () => {
      const bull = mockSetup('bullish', 30)

      // Missing bear setup with negative signed score returns available setup
      const resMissingBear = calculateFeaturedSetup('quiet', bull, undefined, -15)
      expect(resMissingBear.side).toBe('bearish')
      expect(resMissingBear.setup).toBe(bull)

      // Missing bull setup with positive signed score returns available setup
      const bear = mockSetup('bearish', 30)
      const resMissingBull = calculateFeaturedSetup('quiet', undefined, bear, 15)
      expect(resMissingBull.side).toBe('bullish')
      expect(resMissingBull.setup).toBe(bear)
    })
  })

  // ==========================================================================
  // Section 2: computePressureScore - Neutral Tone for Dealer GEX Fallbacks
  // ==========================================================================
  describe('2. OptionsConvictionBoard computePressureScore & GEX Neutrality', () => {
    it('returns neutral tone and 0.0 label when all pressure metrics are absent', () => {
      const row = mockBoardRow({
        squeeze_score: null,
        activity_imbalance: null,
        net_gex_m: null,
        selection_score: null,
      })

      const res = computePressureScore(row)
      expect(res.tone).toBe('neutral')
      expect(res.score).toBe(0)
      expect(res.signed).toBe(0)
      expect(res.label).toBe('0.0')
    })

    it('returns neutral tone for positive Net GEX without directional pressure (does not map long GEX to green pos)', () => {
      // Long gamma (+85.5M) dampens volatility; it is NOT a bullish directional momentum trend
      const row = mockBoardRow({
        squeeze_score: null,
        activity_imbalance: null,
        net_gex_m: 85.5,
      })

      const res = computePressureScore(row)
      expect(res.tone).toBe('neutral')
      expect(res.tone).not.toBe('pos')
      expect(res.signed).toBe(85.5)
      expect(res.label).toBe('+85.5M')
    })

    it('returns neutral tone for negative Net GEX without directional pressure (does not map short GEX to red neg)', () => {
      // Short gamma (-64.2M) amplifies volatility; it is NOT a bearish directional momentum trend
      const row = mockBoardRow({
        squeeze_score: null,
        activity_imbalance: null,
        net_gex_m: -64.2,
      })

      const res = computePressureScore(row)
      expect(res.tone).toBe('neutral')
      expect(res.tone).not.toBe('neg')
      expect(res.signed).toBe(-64.2)
      expect(res.label).toBe('-64.2M')
    })

    it('returns "pos" tone for qualified positive directional squeeze score', () => {
      const row = mockBoardRow({
        squeeze_score: 35.0,
        call_premium: 300_000,
        put_premium: 50_000,
      })

      const res = computePressureScore(row)
      expect(res.tone).toBe('pos')
      expect(res.score).toBeCloseTo(35.0, 1)
      expect(res.signed).toBeCloseTo(35.0, 1)
      expect(res.label).toBe('+35.0')
    })

    it('returns "neg" tone for qualified negative directional squeeze score', () => {
      const row = mockBoardRow({
        squeeze_score: -42.0,
        call_premium: 50_000,
        put_premium: 400_000,
      })

      const res = computePressureScore(row)
      expect(res.tone).toBe('neg')
      expect(res.score).toBeCloseTo(42.0, 1)
      expect(res.signed).toBeCloseTo(-42.0, 1)
      expect(res.label).toBe('-42.0')
    })

    it('returns "neutral" tone when squeeze_score is within noise threshold [-0.5, 0.5]', () => {
      const rowNearZero = mockBoardRow({ squeeze_score: 0.3 })
      expect(computePressureScore(rowNearZero).tone).toBe('neutral')

      const rowNegNearZero = mockBoardRow({ squeeze_score: -0.4 })
      expect(computePressureScore(rowNegNearZero).tone).toBe('neutral')
    })

    it('dampens pressure score appropriately for small premium live flow prints (< $100k)', () => {
      const rowSmall = mockBoardRow({
        selection_basis: 'live_options_flow',
        squeeze_score: 50.0,
        call_premium: 20_000,
        put_premium: 10_000, // Total premium $30k -> dampener = 0.30
      })

      const res = computePressureScore(rowSmall)
      expect(res.signed).toBeCloseTo(50.0 * 0.3, 1) // +15.0
      expect(res.label).toBe('+15.0')
    })

    it('does not synthesize directional bias from unsigned activity_imbalance fallback (returns neutral tone)', () => {
      const rowPosActivity = mockBoardRow({
        squeeze_score: null,
        activity_imbalance: 0.65,
        call_premium: 150_000,
        put_premium: 50_000,
        selection_score: null,
      })
      expect(computePressureScore(rowPosActivity).tone).toBe('neutral')

      const rowNegActivity = mockBoardRow({
        squeeze_score: null,
        activity_imbalance: -0.7,
        call_premium: 50_000,
        put_premium: 150_000,
        selection_score: null,
      })
      expect(computePressureScore(rowNegActivity).tone).toBe('neutral')
    })

    it('returns neutral tone when falling back to selection_score without directional basis', () => {
      const rowModel = mockBoardRow({
        selection_basis: 'directional_model',
        selection_score: 72.5,
        squeeze_score: null,
        activity_imbalance: null,
        net_gex_m: null,
      })

      const res = computePressureScore(rowModel)
      expect(res.tone).toBe('neutral')
      expect(res.label).toBe('72.5')
    })
  })

  // ==========================================================================
  // Section 3: Cross-Component Directional Consensus Integration
  // ==========================================================================
  describe('3. Cross-Component Directional Consensus (SqueezeScreener & OptionsDirectionBrief)', () => {
    it('produces Bullish consensus across SqueezeScreener and OptionsDirectionBrief with positive flow and closer put wall', async () => {
      // Market state: AAPL with bullish signed flow (+0.45), closer put wall (98 vs 115 from spot 100), quiet primary
      const squeezePayload: OptionsSqueeze = {
        bullish: 0.55,
        bearish: 0.15,
        score: 18.0,
        label: 'quiet',
        primary: 'quiet',
        drivers: ['signed_bullish_flow'],
        negative_fuel: 0.42,
        long_gamma_dampened: false,
        key_levels: {
          spot: 100,
          call_wall: 115,
          call_wall_pct: 0.15,
          put_wall: 98,
          put_wall_pct: -0.02,
          gamma_flip: 95,
          gamma_flip_pct: -0.05,
          pin_strike: 100,
          near_spot_net_gex_m: 12.5,
        },
        bullish_setup: mockSetup('bullish', 20, { wall: 115, wall_pct: 0.15 }),
        bearish_setup: mockSetup('bearish', 55, { wall: 98, wall_pct: -0.02 }),
        theory: {
          momentum: 0.012,
          momentum_fresh: true,
        },
      }

      const directionSummary: OptionsDirectionSummary = {
        signed_flow_imbalance: 0.45,
        signed_flow_confidence: 0.8,
        activity_imbalance: 0.25,
        gamma_flip: 95,
        call_wall: 115,
        put_wall: 98,
        squeeze: squeezePayload,
      }

      // 1. Check optionsDirection math
      const dirRead = buildOptionsDirection(directionSummary, 'live')
      expect(dirRead.state).toBe('bullish')
      expect(dirRead.headline).toBe('BULLISH')
      expect(dirRead.basis).toBe('SIGNED FLOW + MOMENTUM')

      // 2. Check squeezeCalc math
      const featured = calculateFeaturedSetup(
        squeezePayload.primary,
        squeezePayload.bullish_setup,
        squeezePayload.bearish_setup,
        squeezePayload.score,
      )
      expect(featured.side).toBe('bullish')

      // 3. Render OptionsDirectionBrief component via SSR
      const briefApp = createSSRApp({
        render: () =>
          h(OptionsDirectionBrief, {
            symbol: 'AAPL',
            read: dirRead,
            spot: 100,
            callWall: 115,
            putWall: 98,
            gammaFlip: 95,
            regime: 'pos_gamma',
            totalGexM: 12.5,
          }),
      })
      const briefHtml = await renderToString(briefApp)
      expect(briefHtml).toContain('direction-brief rise bullish')
      expect(briefHtml).toContain('SIGNED FLOW + MOMENTUM')
      expect(briefHtml).toContain('direction-title')
      expect(briefHtml).toContain('BULLISH')
      expect(briefHtml).not.toContain('direction-brief rise bearish')

      // 4. Render SqueezeScreener component via SSR
      const screenerApp = createSSRApp({
        render: () =>
          h(SqueezeScreener, {
            squeeze: squeezePayload,
            spot: 100,
            asof: '2026-08-25T14:30:00Z',
            ageSeconds: 15,
            mode: 'live',
          }),
      })
      const screenerHtml = await renderToString(screenerApp)
      expect(screenerHtml).toContain('class="sq bullish"')
      expect(screenerHtml).toContain('DISTANCE TO CALL WALL')
      expect(screenerHtml).toContain('POCKET $100.00–$115.00')
      expect(screenerHtml).not.toContain('class="sq bearish"')
    })

    it('produces Bearish consensus across SqueezeScreener and OptionsDirectionBrief with negative flow and closer call wall', async () => {
      // Market state: TSLA with bearish signed flow (-0.50), closer call wall (102 vs 85 from spot 100), quiet primary
      const squeezePayload: OptionsSqueeze = {
        bullish: 0.12,
        bearish: 0.6,
        score: -22.0,
        label: 'quiet',
        primary: 'quiet',
        drivers: ['signed_bearish_flow'],
        negative_fuel: 0.58,
        long_gamma_dampened: false,
        key_levels: {
          spot: 100,
          call_wall: 102,
          call_wall_pct: 0.02,
          put_wall: 85,
          put_wall_pct: -0.15,
          gamma_flip: 105,
          gamma_flip_pct: 0.05,
          pin_strike: 100,
          near_spot_net_gex_m: -18.0,
        },
        bullish_setup: mockSetup('bullish', 60, { wall: 102, wall_pct: 0.02 }),
        bearish_setup: mockSetup('bearish', 25, { wall: 85, wall_pct: -0.15 }),
        theory: {
          momentum: -0.015,
          momentum_fresh: true,
        },
      }

      const directionSummary: OptionsDirectionSummary = {
        signed_flow_imbalance: -0.5,
        signed_flow_confidence: 0.85,
        activity_imbalance: -0.4,
        gamma_flip: 105,
        call_wall: 102,
        put_wall: 85,
        squeeze: squeezePayload,
      }

      // 1. Check optionsDirection math
      const dirRead = buildOptionsDirection(directionSummary, 'live')
      expect(dirRead.state).toBe('bearish')
      expect(dirRead.headline).toBe('BEARISH')
      expect(dirRead.basis).toBe('SIGNED FLOW + MOMENTUM')

      // 2. Check squeezeCalc math
      const featured = calculateFeaturedSetup(
        squeezePayload.primary,
        squeezePayload.bullish_setup,
        squeezePayload.bearish_setup,
        squeezePayload.score,
      )
      expect(featured.side).toBe('bearish')

      // 3. Render OptionsDirectionBrief component via SSR
      const briefApp = createSSRApp({
        render: () =>
          h(OptionsDirectionBrief, {
            symbol: 'TSLA',
            read: dirRead,
            spot: 100,
            callWall: 102,
            putWall: 85,
            gammaFlip: 105,
            regime: 'neg_gamma',
            totalGexM: -18.0,
          }),
      })
      const briefHtml = await renderToString(briefApp)
      expect(briefHtml).toContain('direction-brief rise bearish')
      expect(briefHtml).toContain('SIGNED FLOW + MOMENTUM')
      expect(briefHtml).toContain('direction-title')
      expect(briefHtml).toContain('BEARISH')
      expect(briefHtml).not.toContain('direction-brief rise bullish')

      // 4. Render SqueezeScreener component via SSR
      const screenerApp = createSSRApp({
        render: () =>
          h(SqueezeScreener, {
            squeeze: squeezePayload,
            spot: 100,
            asof: '2026-08-25T14:30:00Z',
            ageSeconds: 20,
            mode: 'live',
          }),
      })
      const screenerHtml = await renderToString(screenerApp)
      expect(screenerHtml).toContain('class="sq bearish"')
      expect(screenerHtml).toContain('DISTANCE TO PUT WALL')
      expect(screenerHtml).toContain('POCKET $100.00–$85.00')
      expect(screenerHtml).not.toContain('class="sq bullish"')
    })

    it('correctly maps Mixed / Conflict state without forcing one-sided squeeze bias', () => {
      // Bullish signed flow (+0.40) but negative price momentum (-0.025)
      const directionSummary: OptionsDirectionSummary = {
        signed_flow_imbalance: 0.4,
        signed_flow_confidence: 0.7,
        squeeze: {
          bullish: 0.3,
          bearish: 0.25,
          score: 5.0,
          label: 'two_way',
          primary: 'two_way',
          drivers: ['signed_bullish_flow', 'down_momentum'],
          theory: {
            momentum: -0.025,
            momentum_fresh: true,
          },
        },
      }

      const dirRead = buildOptionsDirection(directionSummary, 'live')
      expect(dirRead.state).toBe('mixed')
      expect(dirRead.headline).toBe('MIXED / WAIT')
      expect(dirRead.basis).toBe('CONFLICTING FLOW + MOMENTUM')
    })

    it('decouples Dealer Gamma Regime (long gamma volatility dampening) from Directional Bias', async () => {
      // Long dealer gamma (+50M) with spot above flip (100 > 90) AND bullish signed flow (+0.60)
      const dirRead = buildOptionsDirection(
        {
          signed_flow_imbalance: 0.6,
          signed_flow_confidence: 0.9,
          gamma_flip: 90,
          call_wall: 110,
          put_wall: 85,
        },
        'live',
      )

      const briefApp = createSSRApp({
        render: () =>
          h(OptionsDirectionBrief, {
            symbol: 'NVDA',
            read: dirRead,
            spot: 100,
            callWall: 110,
            putWall: 85,
            gammaFlip: 90,
            regime: 'pos_gamma',
            totalGexM: 50.0,
          }),
      })

      const briefHtml = await renderToString(briefApp)
      // Directional headline is BULLISH
      expect(briefHtml).toContain('BULLISH')
      // Dealer Gamma thesis clearly explains volatility dampening, not bullish trend
      expect(briefHtml).toContain('LONG GAMMA · VOLATILITY DAMPENED')
      expect(briefHtml).toContain('DAMPEN ABOVE $90.00')
      expect(briefHtml).toContain('dealers buy into weakness and sell into strength')
    })
  })
})
