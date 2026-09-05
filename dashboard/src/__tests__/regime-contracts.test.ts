import { describe, it, expect } from 'vitest'
import type {
  MarketRegimePayload,
  PrimaryRegimeType,
  TrendContext,
  VolatilityContext,
  StructureContext,
  FlowContext,
  RegimeState,
  RegimeBreadthPayload,
} from '../regimeContracts'
import {
  extractWatchedLevelsFromPayload,
  computePayloadLevelDistances,
  parsePrimaryRegimeBadge,
  parseConfidenceVisuals,
  parseTransitionRiskVisuals,
  parseAgreementVisuals,
  parsePillars,
  isRegimeMeasurable,
  levelCrossings,
} from '../regimeSignals'

describe('Multi-Dimensional Market Regime Contracts & Signal Parsers', () => {
  const primaryRegimes: PrimaryRegimeType[] = [
    'bull_trend',
    'bear_trend',
    'compression_range',
    'mean_reverting',
    'vol_expansion_breakout',
    'uncertain_transitional',
    'unmeasurable',
  ]

  function makeMockPayload(overrides: Partial<MarketRegimePayload> = {}): MarketRegimePayload {
    return {
      symbol: 'SPY',
      asof_utc: '2026-09-02T12:00:00Z',
      spot: 520.5,
      primary: 'bull_trend',
      primaryLabel: 'Bullish Trend',
      confidence: {
        score: 0.88,
        band: 'high',
        penaltyFactors: [],
      },
      probabilities: {
        bullish: 0.7,
        bearish: 0.15,
        neutral: 0.15,
      },
      trend: {
        state: 'strong_up',
        slope: 0.0034,
        kalmanVelocity: 0.42,
        kalmanZScore: 1.85,
        trendPersistence: 0.82,
        measured: true,
      },
      volatility: {
        state: 'normal',
        realizedVolPct: 14.2,
        impliedVolPct: 15.1,
        volPercentile: 0.45,
        parkinsonVolPct: 13.8,
        ivHvRatio: 1.06,
        measured: true,
      },
      structure: {
        state: 'trending',
        ouHalfLifeBars: 48.0,
        hurstExponent: 0.62,
        breakoutZScore: 1.45,
        exhaustionZScore: 0.22,
        measured: true,
      },
      flow: {
        state: 'accumulation',
        dealerGammaRegime: 'long',
        netGexM: 450.0,
        netVexM: 18.5,
        netCharmDriftM: 5.2,
        orderFlowDeltaM: 120.0,
        hedgingPressureDirection: 'supportive',
        measured: true,
      },
      transition: {
        level: 'low',
        changepointProb5d: 0.12,
        changepointProb20d: 0.28,
        mapRunLength: 18,
        expectedRunLength: 35,
        stabilityScore: 0.88,
        measured: true,
      },
      agreement: {
        band: 'high',
        agreementScore: 0.85,
        agreeingModels: ['Trend (Kalman)', 'Gamma Topography', 'Order Flow (MAD)'],
        conflictingModels: [],
        divergenceSummary: 'Strong multi-model alignment',
        pairwiseMatrix: {
          'Trend (Kalman)': { 'Trend (Kalman)': 1.0, 'Gamma Topography': 0.8 },
          'Gamma Topography': { 'Trend (Kalman)': 0.8, 'Gamma Topography': 1.0 },
        },
      },
      explanation: {
        headline: 'Bullish Kinematic Trend with Long Gamma Damping',
        summary:
          'Kalman filter estimates positive velocity (+1.85σ) reinforced by positive institutional gamma and order flow.',
        leadingDrivers: ['Kalman velocity z-score +1.85σ', 'Positive dealer gamma ($450M)'],
        riskFactors: ['Potential resistance at Call Wall $530'],
        uncertaintySources: [],
      },
      levels: {
        callWall: 530.0,
        putWall: 505.0,
        gammaFlip: 512.0,
        sessionVwap: 518.5,
      },
      quality: {
        measurable: true,
        missingLenses: [],
        reason: null,
      },
      ...overrides,
    }
  }

  describe('Schema & Type Conformance', () => {
    it.each(primaryRegimes)('validates primary regime type %s', (regime) => {
      const payload = makeMockPayload({ primary: regime })
      expect(payload.primary).toBe(regime)
      const visual = parsePrimaryRegimeBadge(regime)
      expect(visual.label).toBeTruthy()
      expect(visual.tone).toBeTruthy()
    })

    it('enforces confidence scores and probabilities bounded in [0.0, 1.0]', () => {
      const payload = makeMockPayload()
      expect(payload.confidence.score).toBeGreaterThanOrEqual(0.0)
      expect(payload.confidence.score).toBeLessThanOrEqual(1.0)
      if (payload.probabilities) {
        const sum =
          payload.probabilities.bullish +
          payload.probabilities.bearish +
          payload.probabilities.neutral
        expect(Math.abs(sum - 1.0)).toBeLessThan(1e-4)
      }
      expect(payload.transition.stabilityScore).toBeGreaterThanOrEqual(0.0)
      expect(payload.transition.stabilityScore).toBeLessThanOrEqual(1.0)
      expect(payload.agreement.agreementScore).toBeGreaterThanOrEqual(0.0)
      expect(payload.agreement.agreementScore).toBeLessThanOrEqual(1.0)
    })
  })

  describe('4-Pillar Multi-Dimensional Contexts', () => {
    it('verifies TrendContext fields and nullability', () => {
      const trend: TrendContext = {
        state: 'strong_up',
        slope: 0.0034,
        kalmanVelocity: 0.42,
        kalmanZScore: 1.85,
        trendPersistence: 0.82,
        measured: true,
      }
      expect(trend.measured).toBe(true)
      expect(trend.kalmanZScore).toBe(1.85)

      const unmeasuredTrend: TrendContext = {
        state: 'unmeasured',
        slope: null,
        kalmanVelocity: null,
        kalmanZScore: null,
        trendPersistence: null,
        measured: false,
      }
      expect(unmeasuredTrend.measured).toBe(false)
      expect(unmeasuredTrend.kalmanZScore).toBeNull()
    })

    it('verifies VolatilityContext fields and nullability', () => {
      const vol: VolatilityContext = {
        state: 'compression',
        realizedVolPct: 10.5,
        impliedVolPct: 12.0,
        volPercentile: 0.15,
        parkinsonVolPct: 9.8,
        ivHvRatio: 1.14,
        measured: true,
      }
      expect(vol.state).toBe('compression')
      expect(vol.volPercentile).toBe(0.15)
    })

    it('verifies StructureContext fields and nullability', () => {
      const struct: StructureContext = {
        state: 'mean_reverting',
        ouHalfLifeBars: 12.5,
        hurstExponent: 0.38,
        breakoutZScore: 0.4,
        exhaustionZScore: 1.8,
        measured: true,
      }
      expect(struct.hurstExponent).toBe(0.38)
      expect(struct.ouHalfLifeBars).toBe(12.5)
    })

    it('verifies FlowContext fields and GammaRegime enum compatibility', () => {
      const flow: FlowContext = {
        state: 'accumulation',
        dealerGammaRegime: 'long',
        netGexM: 350.0,
        netVexM: 12.0,
        netCharmDriftM: 4.5,
        orderFlowDeltaM: 80.0,
        hedgingPressureDirection: 'supportive',
        measured: true,
      }
      expect(flow.dealerGammaRegime).toBe('long')
    })
  })

  describe('Zero-Spoofing & Unmeasurable Invariants', () => {
    it('flags isRegimeMeasurable as false when primary is unmeasurable or quality.measurable is false', () => {
      const unmeasurablePayload = makeMockPayload({
        primary: 'unmeasurable',
        primaryLabel: 'Regime Unmeasured',
        quality: {
          measurable: false,
          missingLenses: ['flow', 'gamma'],
          reason: 'No listed options chain available',
        },
        levels: {
          callWall: null,
          putWall: null,
          gammaFlip: null,
          sessionVwap: null,
        },
      })

      expect(isRegimeMeasurable(unmeasurablePayload)).toBe(false)
      expect(isRegimeMeasurable(null)).toBe(false)
      expect(isRegimeMeasurable(undefined)).toBe(false)

      const visual = parsePrimaryRegimeBadge(unmeasurablePayload.primary)
      expect(visual.label).toBe('UNMEASURABLE')
      expect(visual.tone).toBe('stale')
      expect(visual.isUncertain).toBe(true)
    })

    it('extractWatchedLevelsFromPayload returns empty array for null levels or null payload', () => {
      expect(extractWatchedLevelsFromPayload(null)).toEqual([])
      expect(extractWatchedLevelsFromPayload(undefined)).toEqual([])

      const emptyLevelsPayload = makeMockPayload({
        levels: {
          callWall: null,
          putWall: null,
          gammaFlip: null,
          sessionVwap: null,
        },
      })
      expect(extractWatchedLevelsFromPayload(emptyLevelsPayload)).toEqual([])
    })

    it('extractWatchedLevelsFromPayload extracts valid positive levels including vwap', () => {
      const payload = makeMockPayload()
      const levels = extractWatchedLevelsFromPayload(payload)
      expect(levels.length).toBe(4)
      expect(levels.map((l) => l.key)).toEqual(['call', 'put', 'flip', 'vwap'])
    })

    it('computePayloadLevelDistances returns null distance for missing levels or null spot', () => {
      expect(computePayloadLevelDistances(null, null, null)).toEqual({
        call: null,
        put: null,
        flip: null,
        vwap: null,
      })

      const distances = computePayloadLevelDistances(
        520.0,
        {
          callWall: 530.0,
          putWall: 505.0,
          gammaFlip: null,
          sessionVwap: 518.5,
        },
        5.0,
      )

      expect(distances.call).not.toBeNull()
      expect(distances.call?.pct).toBeCloseTo(((530 - 520) / 520) * 100, 2)
      expect(distances.call?.emMultiple).toBeCloseTo(10 / 5, 2)
      expect(distances.flip).toBeNull()
      expect(distances.vwap?.pct).toBeCloseTo(((518.5 - 520) / 520) * 100, 2)
    })
  })

  describe('Signal Helpers & Visual Transformers', () => {
    it('parseConfidenceVisuals handles null and valid confidence scores', () => {
      const nullVisual = parseConfidenceVisuals(null)
      expect(nullVisual.displayScore).toBe('—')
      expect(nullVisual.tone).toBe('stale')

      const highVisual = parseConfidenceVisuals({
        score: 0.92,
        band: 'high',
        penaltyFactors: [],
      })
      expect(highVisual.displayScore).toBe('92%')
      expect(highVisual.tone).toBe('bullish')
      expect(highVisual.penaltyCount).toBe(0)

      const penalizedVisual = parseConfidenceVisuals({
        score: 0.42,
        band: 'low',
        penaltyFactors: ['High changepoint hazard', 'Model divergence'],
      })
      expect(penalizedVisual.tone).toBe('danger')
      expect(penalizedVisual.penaltyCount).toBe(2)
      expect(penalizedVisual.penaltySummary).toContain('High changepoint hazard')
    })

    it('parseTransitionRiskVisuals handles low vs critical hazard', () => {
      const lowRisk = parseTransitionRiskVisuals({
        level: 'low',
        changepointProb5d: 0.1,
        changepointProb20d: 0.2,
        mapRunLength: 20,
        expectedRunLength: 40,
        stabilityScore: 0.9,
        measured: true,
      })
      expect(lowRisk.isHighHazard).toBe(false)
      expect(lowRisk.tone).toBe('normal')

      const criticalRisk = parseTransitionRiskVisuals({
        level: 'critical',
        changepointProb5d: 0.78,
        changepointProb20d: 0.9,
        mapRunLength: 3,
        expectedRunLength: 15,
        stabilityScore: 0.22,
        measured: true,
      })
      expect(criticalRisk.isHighHazard).toBe(true)
      expect(criticalRisk.tone).toBe('critical')
      expect(criticalRisk.displayPct).toBe('78%')
    })

    it('parseAgreementVisuals handles consensus vs conflict', () => {
      const consensusVisual = parseAgreementVisuals({
        band: 'high',
        agreementScore: 0.9,
        agreeingModels: ['Model A', 'Model B', 'Model C'],
        conflictingModels: [],
        divergenceSummary: null,
      })
      expect(consensusVisual.hasConflict).toBe(false)
      expect(consensusVisual.tone).toBe('high')
      expect(consensusVisual.consensusRatio).toBe('3/3')

      const conflictVisual = parseAgreementVisuals({
        band: 'conflict',
        agreementScore: 0.35,
        agreeingModels: ['Model A'],
        conflictingModels: ['Model B', 'Model C'],
        divergenceSummary: 'Trend model conflicts with Gamma topography',
      })
      expect(conflictVisual.hasConflict).toBe(true)
      expect(conflictVisual.tone).toBe('conflict')
      expect(conflictVisual.summary).toContain('conflicts')
    })

    it('parsePillars handles measured and unmeasured pillars', () => {
      const payload = makeMockPayload({
        flow: {
          state: 'unmeasured',
          dealerGammaRegime: 'unmeasurable',
          netGexM: null,
          netVexM: null,
          netCharmDriftM: null,
          orderFlowDeltaM: null,
          hedgingPressureDirection: 'neutral',
          measured: false,
        },
      })
      const pillars = parsePillars(payload)

      expect(pillars.trend.measured).toBe(true)
      expect(pillars.trend.tone).toBe('bullish')
      expect(pillars.volatility.measured).toBe(true)
      expect(pillars.structure.measured).toBe(true)
      expect(pillars.flow.measured).toBe(false)
      expect(pillars.flow.tone).toBe('stale')
      expect(pillars.flow.stateLabel).toBe('UNMEASURED')
    })

    it('levelCrossings detects spot crosses in correct origin-proximity order', () => {
      const levels = [
        { key: 'flip' as const, label: 'FLIP', price: 510 },
        { key: 'call' as const, label: 'CALL', price: 520 },
        { key: 'vwap' as const, label: 'VWAP', price: 515 },
      ]

      // Rising from 508 to 525: crossed in order 510, 515, 520
      const risingCrossings = levelCrossings(508, 525, levels)
      expect(risingCrossings.length).toBe(3)
      expect(risingCrossings.map((c) => c.price)).toEqual([510, 515, 520])
      expect(risingCrossings.every((c) => c.dir === 'up')).toBe(true)

      // Falling from 522 to 505: crossed in order 520, 515, 510
      const fallingCrossings = levelCrossings(522, 505, levels)
      expect(fallingCrossings.length).toBe(3)
      expect(fallingCrossings.map((c) => c.price)).toEqual([520, 515, 510])
      expect(fallingCrossings.every((c) => c.dir === 'down')).toBe(true)

      // No movement
      expect(levelCrossings(515, 515, levels)).toEqual([])
    })
  })

  describe('Backward Compatibility with Legacy Single-Symbol Gamma Contracts', () => {
    it('preserves legacy contract types and structure', () => {
      const legacyState: RegimeState = {
        netGammaM: 150.0,
        gammaSlope: 1.2,
        distanceToFlip: 0.02,
        regime: 'long',
        flipBandPct: 0.0025,
        spot: 520.0,
        zeroGamma: 510.0,
        pinStrike: 522.0,
        callWall: 530.0,
        putWall: 505.0,
        measurable: true,
        gammaScaleM: 500.0,
        slopeScaleM: 5.0,
      }
      expect(legacyState.regime).toBe('long')
      expect(legacyState.measurable).toBe(true)

      const legacyBreadth: RegimeBreadthPayload = {
        asof: '2026-09-02T12:00:00Z',
        universe: 'core',
        rows: [],
        divergence: null,
        warnings: [],
        cache: null,
      }
      expect(legacyBreadth.universe).toBe('core')
    })
  })
})
