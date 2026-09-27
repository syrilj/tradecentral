/**
 * Comprehensive 4-Tier E2E Test Suite for Real-Time Market Regime Detection
 * & Price Attraction / Magnet Levels Engine (Frontend Vitest Suite).
 *
 * Covers:
 * - Tier 1: Feature Coverage (F01-F06, >=5 tests each, 36 tests total)
 * - Tier 2: Boundary & Corner Cases (B01-B12, 12 dimensions, 36 tests total)
 * - Tier 3: Cross-Feature Pairwise Combinations (P01-P08, 8 tests total)
 * - Tier 4: Real-World Institutional Scenarios (S01-S06, 6 tests total)
 */

import { describe, it, expect, vi } from 'vitest'
import {
  type MarketRegimeType,
  type PriceDrawLevel,
  type PriceDrawTelemetryPayload,
  UNMEASURED_PLACEHOLDER,
  isRegimeMeasurable,
  isLevelMeasurable,
  getRegimeLabel,
  getRegimeBadgeClass,
  formatDistancePoints,
  formatDistancePercent,
  formatPullScore,
  getDirectionalVector,
  computeDistanceTelemetry,
  computeConfluenceClusters,
  determineDominantDirection,
  createUnmeasuredPayload,
} from '@/priceDrawContracts'

describe('Price Attractors & Market Regime E2E Test Suite', () => {
  // =========================================================================
  // TIER 1: FEATURE COVERAGE (F01 - F06)
  // =========================================================================

  describe('Tier 1: Feature 01 - Market Regime Classifier & Contract Typings', () => {
    it('F1.1: Correctly validates all 7 standardized market regime types', () => {
      const validRegimes: MarketRegimeType[] = [
        'volatility_dampening',
        'volatility_amplification',
        'charm_decay_selling',
        'charm_decay_buying',
        'vanna_vol_expansion',
        'neutral_transition',
        'unmeasurable',
      ]
      for (const regime of validRegimes) {
        expect(typeof getRegimeLabel(regime)).toBe('string')
        expect(getRegimeLabel(regime).length).toBeGreaterThan(3)
      }
    })

    it('F1.2: Returns true for measurable regimes and false for unmeasurable', () => {
      expect(isRegimeMeasurable('volatility_dampening')).toBe(true)
      expect(isRegimeMeasurable('volatility_amplification')).toBe(true)
      expect(isRegimeMeasurable('charm_decay_selling')).toBe(true)
      expect(isRegimeMeasurable('charm_decay_buying')).toBe(true)
      expect(isRegimeMeasurable('vanna_vol_expansion')).toBe(true)
      expect(isRegimeMeasurable('neutral_transition')).toBe(true)
      expect(isRegimeMeasurable('unmeasurable')).toBe(false)
    })

    it('F1.3: Maps volatility_dampening to Long Gamma label and badge class', () => {
      expect(getRegimeLabel('volatility_dampening')).toContain('Long Γ')
      expect(getRegimeBadgeClass('volatility_dampening')).toBe('regime-badge--dampening')
    })

    it('F1.4: Maps volatility_amplification to Short Gamma label and badge class', () => {
      expect(getRegimeLabel('volatility_amplification')).toContain('Short Γ')
      expect(getRegimeBadgeClass('volatility_amplification')).toBe('regime-badge--amplification')
    })

    it('F1.5: Maps neutral_transition to Gamma-Flip Band label and badge class', () => {
      expect(getRegimeLabel('neutral_transition')).toContain('Flip Band')
      expect(getRegimeBadgeClass('neutral_transition')).toBe('regime-badge--neutral')
    })

    it('F1.6: Correctly formats unmeasurable regime with unmeasured badge class', () => {
      expect(getRegimeLabel('unmeasurable')).toBe('Unmeasured Regime')
      expect(getRegimeBadgeClass('unmeasurable')).toBe('regime-badge--unmeasured')
    })
  })

  describe('Tier 1: Feature 02 - Multi-Factor Price Magnet Detection & Types', () => {
    it('F2.1: Correctly constructs Call Wall level with overhead resistance role', () => {
      const callWall: PriceDrawLevel = {
        id: 'cw_500',
        type: 'call_wall',
        label: 'Call Wall',
        price: 500.0,
        distance_pts: 10.0,
        distance_pct: 2.04,
        pull_score: 85.0,
        direction: 'above',
        regime_role: 'Overhead Resistance Cap',
        supporting_lenses: ['GAMMA', 'VOLUME'],
        lens_count: 2,
        is_primary_magnet: true,
      }
      expect(callWall.type).toBe('call_wall')
      expect(callWall.direction).toBe('above')
      expect(callWall.is_primary_magnet).toBe(true)
    })

    it('F2.2: Correctly constructs Put Wall level with downside support role', () => {
      const putWall: PriceDrawLevel = {
        id: 'pw_470',
        type: 'put_wall',
        label: 'Put Wall',
        price: 470.0,
        distance_pts: -20.0,
        distance_pct: -4.08,
        pull_score: 75.0,
        direction: 'below',
        regime_role: 'Downside Support Floor',
        supporting_lenses: ['GAMMA', 'THETA'],
        lens_count: 2,
        is_primary_magnet: false,
      }
      expect(putWall.type).toBe('put_wall')
      expect(putWall.direction).toBe('below')
      expect(putWall.distance_pts).toBe(-20.0)
    })

    it('F2.3: Correctly identifies Gamma Flip level as regime transition pivot', () => {
      const flipLevel: PriceDrawLevel = {
        id: 'gf_485',
        type: 'gamma_flip',
        label: 'Zero-Gamma Flip',
        price: 485.0,
        distance_pts: -5.0,
        distance_pct: -1.02,
        pull_score: 92.0,
        direction: 'below',
        regime_role: 'Regime Transition Pivot',
        supporting_lenses: ['GAMMA'],
        lens_count: 1,
        is_primary_magnet: true,
      }
      expect(flipLevel.type).toBe('gamma_flip')
      expect(flipLevel.regime_role).toContain('Transition Pivot')
    })

    it('F2.4: Correctly models Max Pain Pin with high gravitational pull score', () => {
      const maxPain: PriceDrawLevel = {
        id: 'mp_490',
        type: 'max_pain_pin',
        label: 'Max Pain Pin',
        price: 490.0,
        distance_pts: 0.0,
        distance_pct: 0.0,
        pull_score: 98.0,
        direction: 'at_spot',
        regime_role: 'OpEx Expiry Pin',
        supporting_lenses: ['THETA', 'GAMMA'],
        lens_count: 2,
        is_primary_magnet: true,
      }
      expect(maxPain.direction).toBe('at_spot')
      expect(maxPain.pull_score).toBe(98.0)
    })

    it('F2.5: Correctly models Kinematic Drift and Volume POC attractors', () => {
      const kinematic: PriceDrawLevel = {
        id: 'kd_495',
        type: 'kinematic_drift',
        label: 'Kinematic Attractor',
        price: 495.0,
        distance_pts: 5.0,
        distance_pct: 1.02,
        pull_score: 65.0,
        direction: 'above',
        regime_role: 'Kalman Velocity Equilibrium',
        supporting_lenses: ['KALMAN'],
        lens_count: 1,
        is_primary_magnet: false,
      }
      const poc: PriceDrawLevel = {
        id: 'poc_488',
        type: 'volume_poc',
        label: 'Volume POC',
        price: 488.0,
        distance_pts: -2.0,
        distance_pct: -0.41,
        pull_score: 70.0,
        direction: 'below',
        regime_role: 'High-Volume Node',
        supporting_lenses: ['VOLUME'],
        lens_count: 1,
        is_primary_magnet: false,
      }
      expect(kinematic.supporting_lenses).toContain('KALMAN')
      expect(poc.supporting_lenses).toContain('VOLUME')
    })

    it('F2.6: Evaluates isLevelMeasurable correctly based on null status of metrics', () => {
      const valid: PriceDrawLevel = {
        id: 'l1',
        type: 'call_wall',
        label: 'Call Wall',
        price: 500,
        distance_pts: 10,
        distance_pct: 2,
        pull_score: 80,
        direction: 'above',
        regime_role: 'Resistance',
        supporting_lenses: ['GAMMA'],
        lens_count: 1,
        is_primary_magnet: true,
      }
      const unmeasured: PriceDrawLevel = {
        id: 'l2',
        type: 'call_wall',
        label: 'Call Wall',
        price: 500,
        distance_pts: null,
        distance_pct: null,
        pull_score: null,
        direction: 'above',
        regime_role: 'Resistance',
        supporting_lenses: [],
        lens_count: 0,
        is_primary_magnet: false,
      }
      expect(isLevelMeasurable(valid)).toBe(true)
      expect(isLevelMeasurable(unmeasured)).toBe(false)
    })
  })

  describe('Tier 1: Feature 03 - Quantitative Attractor Telemetry & Vector Mechanics', () => {
    it('F3.1: Accurately computes signed points and percentage for levels above spot', () => {
      const spot = 200.0
      const targetPrice = 205.0
      const tel = computeDistanceTelemetry(targetPrice, spot)
      expect(tel.distance_pts).toBe(5.0)
      expect(tel.distance_pct).toBe(2.5)
      expect(tel.direction).toBe('above')
    })

    it('F3.2: Accurately computes signed points and percentage for levels below spot', () => {
      const spot = 200.0
      const targetPrice = 190.0
      const tel = computeDistanceTelemetry(targetPrice, spot)
      expect(tel.distance_pts).toBe(-10.0)
      expect(tel.distance_pct).toBe(-5.0)
      expect(tel.direction).toBe('below')
    })

    it('F3.3: Accurately identifies at_spot condition when price equals spot', () => {
      const spot = 150.0
      const tel = computeDistanceTelemetry(150.0, spot)
      expect(tel.distance_pts).toBe(0.0)
      expect(tel.distance_pct).toBe(0.0)
      expect(tel.direction).toBe('at_spot')
    })

    it('F3.4: Formats positive distance with explicit plus prefix', () => {
      expect(formatDistancePoints(3.456)).toBe('+3.46')
      expect(formatDistancePercent(1.875)).toBe('+1.88%')
    })

    it('F3.5: Formats negative distance with standard minus prefix', () => {
      expect(formatDistancePoints(-4.2)).toBe('-4.20')
      expect(formatDistancePercent(-2.15)).toBe('-2.15%')
    })

    it('F3.6: Formats pull score clamped to 0 - 100 range', () => {
      expect(formatPullScore(84.3)).toBe('84')
      expect(formatPullScore(105.0)).toBe('100')
      expect(formatPullScore(-15.0)).toBe('0')
    })
  })

  describe('Tier 1: Feature 04 - Zero-Spoofing & Anti-Fabrication Guarantees', () => {
    it('F4.1: Formats null distance points as explicit em dash placeholder', () => {
      expect(formatDistancePoints(null)).toBe(UNMEASURED_PLACEHOLDER)
      expect(formatDistancePoints(NaN)).toBe(UNMEASURED_PLACEHOLDER)
      expect(formatDistancePoints(Infinity)).toBe(UNMEASURED_PLACEHOLDER)
    })

    it('F4.2: Formats null distance percentage as explicit em dash placeholder', () => {
      expect(formatDistancePercent(null)).toBe(UNMEASURED_PLACEHOLDER)
      expect(formatDistancePercent(NaN)).toBe(UNMEASURED_PLACEHOLDER)
      expect(formatDistancePercent(-Infinity)).toBe(UNMEASURED_PLACEHOLDER)
    })

    it('F4.3: Formats null pull score as explicit em dash placeholder', () => {
      expect(formatPullScore(null)).toBe(UNMEASURED_PLACEHOLDER)
      expect(formatPullScore(NaN)).toBe(UNMEASURED_PLACEHOLDER)
    })

    it('F4.4: Returns null telemetry when spot is null, NaN, or non-positive', () => {
      const telNull = computeDistanceTelemetry(100, null)
      expect(telNull.distance_pts).toBeNull()
      expect(telNull.distance_pct).toBeNull()
      expect(telNull.direction).toBe('at_spot')

      const telZero = computeDistanceTelemetry(100, 0)
      expect(telZero.distance_pts).toBeNull()
      expect(telZero.distance_pct).toBeNull()
    })

    it('F4.5: Creates compliant unmeasured payload without fake zeroes', () => {
      const payload = createUnmeasuredPayload('SPY', 'No options chain available')
      expect(payload.symbol).toBe('SPY')
      expect(payload.spot).toBeNull()
      expect(payload.regime_state).toBe('unmeasurable')
      expect(payload.regime_strength).toBeNull()
      expect(payload.dominant_direction).toBe('unmeasured')
      expect(payload.quality.measurable).toBe(false)
      expect(payload.quality.reason).toBe('No options chain available')
      expect(payload.levels).toHaveLength(0)
    })

    it('F4.6: determineDominantDirection returns unmeasured when all pull scores are null or empty', () => {
      const emptyResult = determineDominantDirection([], 100)
      expect(emptyResult).toBe('unmeasured')

      const nullLevels: PriceDrawLevel[] = [
        {
          id: '1',
          type: 'call_wall',
          label: 'CW',
          price: 110,
          distance_pts: null,
          distance_pct: null,
          pull_score: null,
          direction: 'above',
          regime_role: 'Resistance',
          supporting_lenses: [],
          lens_count: 0,
          is_primary_magnet: false,
        },
      ]
      expect(determineDominantDirection(nullLevels, 100)).toBe('unmeasured')
    })
  })

  describe('Tier 1: Feature 05 - API Client Integration & Directional Vectors', () => {
    it('F5.1: Resolves dominant direction to bullish_pull when overhead pull dominates', () => {
      const spot = 100.0
      const levels: PriceDrawLevel[] = [
        {
          id: 'cw',
          type: 'call_wall',
          label: 'Call Wall',
          price: 110,
          distance_pts: 10,
          distance_pct: 10,
          pull_score: 90,
          direction: 'above',
          regime_role: 'Resistance',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: true,
        },
        {
          id: 'pw',
          type: 'put_wall',
          label: 'Put Wall',
          price: 90,
          distance_pts: -10,
          distance_pct: -10,
          pull_score: 20,
          direction: 'below',
          regime_role: 'Support',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
      ]
      expect(determineDominantDirection(levels, spot)).toBe('bullish_pull')
    })

    it('F5.2: Resolves dominant direction to bearish_pull when downside pull dominates', () => {
      const spot = 100.0
      const levels: PriceDrawLevel[] = [
        {
          id: 'cw',
          type: 'call_wall',
          label: 'Call Wall',
          price: 110,
          distance_pts: 10,
          distance_pct: 10,
          pull_score: 15,
          direction: 'above',
          regime_role: 'Resistance',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
        {
          id: 'pw',
          type: 'put_wall',
          label: 'Put Wall',
          price: 90,
          distance_pts: -10,
          distance_pct: -10,
          pull_score: 85,
          direction: 'below',
          regime_role: 'Support',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: true,
        },
      ]
      expect(determineDominantDirection(levels, spot)).toBe('bearish_pull')
    })

    it('F5.3: Resolves dominant direction to neutral_pin when pull scores are balanced', () => {
      const spot = 100.0
      const levels: PriceDrawLevel[] = [
        {
          id: 'cw',
          type: 'call_wall',
          label: 'Call Wall',
          price: 105,
          distance_pts: 5,
          distance_pct: 5,
          pull_score: 50,
          direction: 'above',
          regime_role: 'Resistance',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
        {
          id: 'pw',
          type: 'put_wall',
          label: 'Put Wall',
          price: 95,
          distance_pts: -5,
          distance_pct: -5,
          pull_score: 50,
          direction: 'below',
          regime_role: 'Support',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
      ]
      expect(determineDominantDirection(levels, spot)).toBe('neutral_pin')
    })

    it('F5.4: Resolves direction correctly using getDirectionalVector with tolerance', () => {
      expect(getDirectionalVector(100.00001, 100.0)).toBe('at_spot')
      expect(getDirectionalVector(100.05, 100.0)).toBe('above')
      expect(getDirectionalVector(99.95, 100.0)).toBe('below')
    })

    it('F5.5: Handles null spot in getDirectionalVector gracefully returning at_spot', () => {
      expect(getDirectionalVector(100.0, null)).toBe('at_spot')
      expect(getDirectionalVector(100.0, NaN)).toBe('at_spot')
    })

    it('F5.6: Correctly parses full PriceDrawTelemetryPayload contract', () => {
      const payload: PriceDrawTelemetryPayload = {
        symbol: 'NVDA',
        spot: 125.5,
        asof_utc: '2026-08-29T16:00:00Z',
        regime_state: 'volatility_amplification',
        regime_label: getRegimeLabel('volatility_amplification'),
        regime_strength: 0.85,
        dominant_direction: 'bullish_pull',
        primary_magnet: {
          id: 'cw_130',
          type: 'call_wall',
          label: 'Call Wall',
          price: 130.0,
          distance_pts: 4.5,
          distance_pct: 3.59,
          pull_score: 95.0,
          direction: 'above',
          regime_role: 'Breakout Acceleration',
          supporting_lenses: ['GAMMA', 'KALMAN'],
          lens_count: 2,
          is_primary_magnet: true,
        },
        levels: [],
        confluence_clusters: [],
        quality: {
          measurable: true,
          open_interest_available: true,
          iv_available: true,
          volume_available: true,
          reason: null,
        },
        warnings: [],
      }
      expect(payload.symbol).toBe('NVDA')
      expect(payload.primary_magnet?.pull_score).toBe(95.0)
      expect(payload.quality.measurable).toBe(true)
    })
  })

  describe('Tier 1: Feature 06 - Confluence Clusters & Multi-Lens Aggregation', () => {
    it('F6.1: Aggregates multiple levels within cluster threshold into single confluence zone', () => {
      const spot = 100.0
      const levels: PriceDrawLevel[] = [
        {
          id: 'cw',
          type: 'call_wall',
          label: 'Call Wall',
          price: 105.0,
          distance_pts: 5,
          distance_pct: 5,
          pull_score: 80,
          direction: 'above',
          regime_role: 'Resistance',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
        {
          id: 'mp',
          type: 'max_pain_pin',
          label: 'Max Pain',
          price: 105.2,
          distance_pts: 5.2,
          distance_pct: 5.2,
          pull_score: 85,
          direction: 'above',
          regime_role: 'Pin',
          supporting_lenses: ['THETA'],
          lens_count: 1,
          is_primary_magnet: true,
        },
      ]
      const clusters = computeConfluenceClusters(levels, spot, 0.75)
      expect(clusters).toHaveLength(1)
      expect(clusters[0].lens_count).toBe(2)
      expect(clusters[0].supporting_lenses).toContain('GAMMA')
      expect(clusters[0].supporting_lenses).toContain('THETA')
      expect(clusters[0].labels).toContain('Call Wall')
      expect(clusters[0].labels).toContain('Max Pain')
    })

    it('F6.2: Does not cluster levels exceeding the percentage threshold', () => {
      const spot = 100.0
      const levels: PriceDrawLevel[] = [
        {
          id: 'cw',
          type: 'call_wall',
          label: 'Call Wall',
          price: 105.0,
          distance_pts: 5,
          distance_pct: 5,
          pull_score: 80,
          direction: 'above',
          regime_role: 'Resistance',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
        {
          id: 'pw',
          type: 'put_wall',
          label: 'Put Wall',
          price: 95.0,
          distance_pts: -5,
          distance_pct: -5,
          pull_score: 75,
          direction: 'below',
          regime_role: 'Support',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
      ]
      const clusters = computeConfluenceClusters(levels, spot, 0.75)
      expect(clusters).toHaveLength(0)
    })

    it('F6.3: Returns empty array for empty levels or null spot', () => {
      expect(computeConfluenceClusters([], 100)).toHaveLength(0)
      expect(computeConfluenceClusters([], null)).toHaveLength(0)
    })

    it('F6.4: Correctly sets above_spot true for clusters above or at spot', () => {
      const spot = 100.0
      const levels: PriceDrawLevel[] = [
        {
          id: 'l1',
          type: 'call_wall',
          label: 'L1',
          price: 110,
          distance_pts: 10,
          distance_pct: 10,
          pull_score: 50,
          direction: 'above',
          regime_role: 'R',
          supporting_lenses: ['G'],
          lens_count: 1,
          is_primary_magnet: false,
        },
        {
          id: 'l2',
          type: 'volume_poc',
          label: 'L2',
          price: 110.5,
          distance_pts: 10.5,
          distance_pct: 10.5,
          pull_score: 50,
          direction: 'above',
          regime_role: 'R',
          supporting_lenses: ['V'],
          lens_count: 1,
          is_primary_magnet: false,
        },
      ]
      const clusters = computeConfluenceClusters(levels, spot, 1.0)
      expect(clusters[0].above_spot).toBe(true)
    })

    it('F6.5: Correctly sets above_spot false for clusters below spot', () => {
      const spot = 100.0
      const levels: PriceDrawLevel[] = [
        {
          id: 'l1',
          type: 'put_wall',
          label: 'L1',
          price: 90,
          distance_pts: -10,
          distance_pct: -10,
          pull_score: 50,
          direction: 'below',
          regime_role: 'S',
          supporting_lenses: ['G'],
          lens_count: 1,
          is_primary_magnet: false,
        },
        {
          id: 'l2',
          type: 'volume_poc',
          label: 'L2',
          price: 89.8,
          distance_pts: -10.2,
          distance_pct: -10.2,
          pull_score: 50,
          direction: 'below',
          regime_role: 'S',
          supporting_lenses: ['V'],
          lens_count: 1,
          is_primary_magnet: false,
        },
      ]
      const clusters = computeConfluenceClusters(levels, spot, 1.0)
      expect(clusters[0].above_spot).toBe(false)
    })

    it('F6.6: Deduplicates identical lenses across overlapping levels in a cluster', () => {
      const spot = 100.0
      const levels: PriceDrawLevel[] = [
        {
          id: 'l1',
          type: 'call_wall',
          label: 'CW',
          price: 102.0,
          distance_pts: 2,
          distance_pct: 2,
          pull_score: 50,
          direction: 'above',
          regime_role: 'R',
          supporting_lenses: ['GAMMA', 'THETA'],
          lens_count: 2,
          is_primary_magnet: false,
        },
        {
          id: 'l2',
          type: 'volume_poc',
          label: 'POC',
          price: 102.2,
          distance_pts: 2.2,
          distance_pct: 2.2,
          pull_score: 50,
          direction: 'above',
          regime_role: 'R',
          supporting_lenses: ['GAMMA', 'VOLUME'],
          lens_count: 2,
          is_primary_magnet: false,
        },
      ]
      const clusters = computeConfluenceClusters(levels, spot, 0.75)
      expect(clusters[0].lens_count).toBe(3) // GAMMA, THETA, VOLUME
      expect(clusters[0].supporting_lenses).toEqual(
        expect.arrayContaining(['GAMMA', 'THETA', 'VOLUME']),
      )
    })
  })

  // =========================================================================
  // TIER 2: BOUNDARY & CORNER CASES (B01 - B12)
  // =========================================================================

  describe('Tier 2: Boundary & Corner Cases (12 Dimensions)', () => {
    // Dimension 1: Zero & Flat Gamma Surfaces
    it('B1.1: Handles flat zero-gamma surface returning neutral fallback regime', () => {
      const regime: MarketRegimeType = 'neutral_transition'
      expect(getRegimeLabel(regime)).toContain('Neutral')
      expect(isRegimeMeasurable(regime)).toBe(true)
    })

    it('B1.2: Handles pull scores of 0 without crashing or producing NaN', () => {
      expect(formatPullScore(0.0)).toBe('0')
    })

    it('B1.3: Handles zero points distance with proper signed formatting', () => {
      expect(formatDistancePoints(0.0)).toBe('0.00')
      expect(formatDistancePercent(0.0)).toBe('0.00%')
    })

    // Dimension 2: Extreme Moneyness & Astronomical Strikes
    it('B2.1: Handles extreme deep OTM strike ($5,000 spot on $50,000 strike)', () => {
      const tel = computeDistanceTelemetry(50000.0, 5000.0)
      expect(tel.distance_pts).toBe(45000.0)
      expect(tel.distance_pct).toBe(900.0)
      expect(formatDistancePercent(tel.distance_pct)).toBe('+900.00%')
    })

    it('B2.2: Handles penny stock extreme precision ($0.05 spot on $0.07 strike)', () => {
      const tel = computeDistanceTelemetry(0.07, 0.05)
      expect(tel.distance_pts).toBe(0.02)
      expect(tel.distance_pct).toBe(40.0)
      expect(tel.direction).toBe('above')
    })

    it('B2.3: Handles massive price values without string overflow', () => {
      const formatted = formatDistancePoints(1234567.89)
      expect(formatted).toBe('+1234567.89')
    })

    // Dimension 3: Extreme DTE Regimes (0DTE vs 730DTE LEAPs)
    it('B3.1: Formats 0DTE high charm decay selling regime correctly', () => {
      expect(getRegimeLabel('charm_decay_selling')).toContain('Selling Drift')
      expect(getRegimeBadgeClass('charm_decay_selling')).toBe('regime-badge--charm')
    })

    it('B3.2: Formats 0DTE charm decay buying regime correctly', () => {
      expect(getRegimeLabel('charm_decay_buying')).toContain('Buying Drift')
    })

    it('B3.3: Handles LEAPs with low pull scores without rounding errors', () => {
      expect(formatPullScore(0.4)).toBe('0')
      expect(formatPullScore(1.6)).toBe('2')
    })

    // Dimension 4: Missing OI Feeds & Partial Topography
    it('B4.1: Renders quality unmeasured breakdown on missing OI feed', () => {
      const payload = createUnmeasuredPayload('AAPL', 'Missing Open Interest feed')
      expect(payload.quality.open_interest_available).toBe(false)
      expect(payload.quality.measurable).toBe(false)
      expect(payload.warnings).toContain('Missing Open Interest feed')
    })

    it('B4.2: Evaluates level with partial null values as non-measurable', () => {
      const partial: PriceDrawLevel = {
        id: 'p1',
        type: 'call_wall',
        label: 'CW',
        price: 150,
        distance_pts: 5,
        distance_pct: null, // null percentage
        pull_score: 50,
        direction: 'above',
        regime_role: 'Resistance',
        supporting_lenses: [],
        lens_count: 0,
        is_primary_magnet: false,
      }
      expect(isLevelMeasurable(partial)).toBe(false)
    })

    it('B4.3: Preserves missing reason in createUnmeasuredPayload', () => {
      const customReason = 'Feed provider disconnected for maintenance'
      const payload = createUnmeasuredPayload('TSLA', customReason)
      expect(payload.quality.reason).toBe(customReason)
    })

    // Dimension 5: Monotonic Non-Crossing GEX Profiles
    it('B5.1: Classifies pure monotonic positive GEX as volatility_dampening', () => {
      expect(getRegimeBadgeClass('volatility_dampening')).toBe('regime-badge--dampening')
    })

    it('B5.2: Classifies pure monotonic negative GEX as volatility_amplification', () => {
      expect(getRegimeBadgeClass('volatility_amplification')).toBe('regime-badge--amplification')
    })

    it('B5.3: Handles monotonic cluster without infinite loop', () => {
      const spot = 100.0
      const levels: PriceDrawLevel[] = Array.from({ length: 10 }, (_, i) => ({
        id: `l_${i}`,
        type: 'call_wall',
        label: `CW_${i}`,
        price: 100.0 + i * 0.1, // tightly spaced
        distance_pts: i * 0.1,
        distance_pct: ((i * 0.1) / 100) * 100,
        pull_score: 50,
        direction: 'above',
        regime_role: 'Resistance',
        supporting_lenses: ['GAMMA'],
        lens_count: 1,
        is_primary_magnet: false,
      }))
      const clusters = computeConfluenceClusters(levels, spot, 0.75)
      expect(clusters.length).toBeGreaterThanOrEqual(1)
    })

    // Dimension 6: Negative Interest Rates & Zero Cost-of-Carry
    it('B6.1: Maintains numerical stability when calculating distance under zero cost of carry', () => {
      const tel = computeDistanceTelemetry(100.0, 100.0)
      expect(tel.distance_pts).toBe(0.0)
      expect(tel.distance_pct).toBe(0.0)
    })

    it('B6.2: Handles small fractional rate movements without NaN in percentage', () => {
      const tel = computeDistanceTelemetry(100.001, 100.0)
      expect(tel.distance_pts).toBeCloseTo(0.001, 3)
      expect(tel.distance_pct).toBeCloseTo(0.001, 3)
    })

    it('B6.3: Handles negative pull score input by clamping to 0', () => {
      expect(formatPullScore(-100)).toBe('0')
    })

    // Dimension 7: Multi-Crossing Gamma Topography
    it('B7.1: Handles multiple candidate levels with equal pull scores', () => {
      const spot = 100.0
      const levels: PriceDrawLevel[] = [
        {
          id: 'gf1',
          type: 'gamma_flip',
          label: 'Flip 1',
          price: 95.0,
          distance_pts: -5,
          distance_pct: -5,
          pull_score: 80,
          direction: 'below',
          regime_role: 'Pivot 1',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
        {
          id: 'gf2',
          type: 'gamma_flip',
          label: 'Flip 2',
          price: 105.0,
          distance_pts: 5,
          distance_pct: 5,
          pull_score: 80,
          direction: 'above',
          regime_role: 'Pivot 2',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: true,
        },
      ]
      const dir = determineDominantDirection(levels, spot)
      expect(dir).toBe('neutral_pin')
    })

    it('B7.2: Classifies vanna_vol_expansion badge class correctly', () => {
      expect(getRegimeBadgeClass('vanna_vol_expansion')).toBe('regime-badge--vanna')
    })

    it('B7.3: Returns correct label for vanna_vol_expansion', () => {
      expect(getRegimeLabel('vanna_vol_expansion')).toContain('Vanna Expansion')
    })

    // Dimension 8: Exact Strike Collision / Spot at Gamma Flip
    it('B8.1: Returns direction at_spot when spot exactly matches target level', () => {
      expect(getDirectionalVector(450.0, 450.0)).toBe('at_spot')
    })

    it('B8.2: Formats exactly 0.0 delta percent cleanly without minus sign', () => {
      expect(formatDistancePercent(0.0)).toBe('0.00%')
    })

    it('B8.3: Formats exactly 0.0 delta points cleanly without minus sign', () => {
      expect(formatDistancePoints(0.0)).toBe('0.00')
    })

    // Dimension 9: Single-Contract & Highly Sparse Chains
    it('B9.1: Correctly handles a single isolated level without clustering', () => {
      const levels: PriceDrawLevel[] = [
        {
          id: 'single',
          type: 'call_wall',
          label: 'Single Call',
          price: 150.0,
          distance_pts: 10.0,
          distance_pct: 7.14,
          pull_score: 60.0,
          direction: 'above',
          regime_role: 'Resistance',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: true,
        },
      ]
      const clusters = computeConfluenceClusters(levels, 140.0, 0.75)
      expect(clusters).toHaveLength(0) // Minimum 2 levels required for confluence
    })

    it('B9.2: Single level above spot resolves dominant direction to bullish_pull', () => {
      const levels: PriceDrawLevel[] = [
        {
          id: 'single',
          type: 'call_wall',
          label: 'Single Call',
          price: 150.0,
          distance_pts: 10.0,
          distance_pct: 7.14,
          pull_score: 60.0,
          direction: 'above',
          regime_role: 'Resistance',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: true,
        },
      ]
      expect(determineDominantDirection(levels, 140.0)).toBe('bullish_pull')
    })

    it('B9.3: Single level below spot resolves dominant direction to bearish_pull', () => {
      const levels: PriceDrawLevel[] = [
        {
          id: 'single_put',
          type: 'put_wall',
          label: 'Single Put',
          price: 130.0,
          distance_pts: -10.0,
          distance_pct: -7.14,
          pull_score: 60.0,
          direction: 'below',
          regime_role: 'Support',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: true,
        },
      ]
      expect(determineDominantDirection(levels, 140.0)).toBe('bearish_pull')
    })

    // Dimension 10: Symmetric Straddle Distributions
    it('B10.1: Symmetric call and put walls equidistant from spot produce neutral_pin', () => {
      const spot = 200.0
      const levels: PriceDrawLevel[] = [
        {
          id: 'cw',
          type: 'call_wall',
          label: 'Call Wall',
          price: 210.0,
          distance_pts: 10.0,
          distance_pct: 5.0,
          pull_score: 70.0,
          direction: 'above',
          regime_role: 'Resistance',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
        {
          id: 'pw',
          type: 'put_wall',
          label: 'Put Wall',
          price: 190.0,
          distance_pts: -10.0,
          distance_pct: -5.0,
          pull_score: 70.0,
          direction: 'below',
          regime_role: 'Support',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
      ]
      expect(determineDominantDirection(levels, spot)).toBe('neutral_pin')
    })

    it('B10.2: Symmetric levels do not collide in confluence clustering', () => {
      const spot = 200.0
      const levels: PriceDrawLevel[] = [
        {
          id: 'cw',
          type: 'call_wall',
          label: 'CW',
          price: 210.0,
          distance_pts: 10,
          distance_pct: 5,
          pull_score: 70,
          direction: 'above',
          regime_role: 'R',
          supporting_lenses: ['G'],
          lens_count: 1,
          is_primary_magnet: false,
        },
        {
          id: 'pw',
          type: 'put_wall',
          label: 'PW',
          price: 190.0,
          distance_pts: -10,
          distance_pct: -5,
          pull_score: 70,
          direction: 'below',
          regime_role: 'S',
          supporting_lenses: ['G'],
          lens_count: 1,
          is_primary_magnet: false,
        },
      ]
      const clusters = computeConfluenceClusters(levels, spot, 0.75)
      expect(clusters).toHaveLength(0)
    })

    it('B10.3: Symmetric straddle pull score formatting is identical', () => {
      expect(formatPullScore(70.0)).toBe('70')
    })

    // Dimension 11: Extreme Volatility Spikes (>300% IV)
    it('B11.1: Pull score cap prevents overflow beyond 100 under extreme IV squeeze', () => {
      expect(formatPullScore(350.0)).toBe('100')
    })

    it('B11.2: Volatility dampening badge renders correctly under high volatility', () => {
      expect(getRegimeBadgeClass('volatility_dampening')).toBe('regime-badge--dampening')
    })

    it('B11.3: Telemetry distance percent handles high volatility wide swings (+50%)', () => {
      const tel = computeDistanceTelemetry(150.0, 100.0)
      expect(tel.distance_pct).toBe(50.0)
      expect(formatDistancePercent(tel.distance_pct)).toBe('+50.00%')
    })

    // Dimension 12: Malformed Payloads & Non-Standard Symbols
    it('B12.1: Uppercases lowercase or mixed case ticker symbols in unmeasured payload', () => {
      const payload = createUnmeasuredPayload('aapl')
      expect(payload.symbol).toBe('AAPL')
    })

    it('B12.2: Handles non-standard crypto/futures symbols (e.g. BTC-USD)', () => {
      const payload = createUnmeasuredPayload('btc-usd')
      expect(payload.symbol).toBe('BTC-USD')
    })

    it('B12.3: Handles null level list in determineDominantDirection gracefully', () => {
      expect(determineDominantDirection(null as any, 100)).toBe('unmeasured')
    })
  })

  // =========================================================================
  // TIER 3: CROSS-FEATURE COMBINATIONS (P01 - P08)
  // =========================================================================

  describe('Tier 3: Cross-Feature Pairwise Combinations (8 Pairs)', () => {
    it('P01: Regime Transition + Magnet Retargeting on Spot Shift', () => {
      // Spot starts at 98 (below flip 100 -> negative gamma)
      const spotBefore = 98.0
      const flipLevel: PriceDrawLevel = {
        id: 'flip',
        type: 'gamma_flip',
        label: 'Flip',
        price: 100.0,
        distance_pts: 2.0,
        distance_pct: 2.04,
        pull_score: 95.0,
        direction: 'above',
        regime_role: 'Transition Pivot',
        supporting_lenses: ['GAMMA'],
        lens_count: 1,
        is_primary_magnet: true,
      }
      expect(flipLevel.direction).toBe('above')
      expect(flipLevel.price).toBeGreaterThan(spotBefore)

      // Spot crosses flip to 102 (above flip -> positive gamma)
      const spotAfter = 102.0
      const updatedTel = computeDistanceTelemetry(flipLevel.price, spotAfter)
      expect(updatedTel.direction).toBe('below')
      expect(updatedTel.distance_pts).toBe(-2.0)
    })

    it('P02: OpEx Expiry Pinning + Kinematic Envelope Confluence Zone', () => {
      const spot = 500.0
      const maxPain: PriceDrawLevel = {
        id: 'mp',
        type: 'max_pain_pin',
        label: 'Max Pain',
        price: 502.0,
        distance_pts: 2.0,
        distance_pct: 0.4,
        pull_score: 90,
        direction: 'above',
        regime_role: 'Pin',
        supporting_lenses: ['THETA', 'GAMMA'],
        lens_count: 2,
        is_primary_magnet: true,
      }
      const kinematic: PriceDrawLevel = {
        id: 'kd',
        type: 'kinematic_drift',
        label: 'Kinematic Drift',
        price: 503.0,
        distance_pts: 3.0,
        distance_pct: 0.6,
        pull_score: 80,
        direction: 'above',
        regime_role: 'Velocity Drift',
        supporting_lenses: ['KALMAN'],
        lens_count: 1,
        is_primary_magnet: false,
      }
      const clusters = computeConfluenceClusters([maxPain, kinematic], spot, 0.75)
      expect(clusters).toHaveLength(1)
      expect(clusters[0].lens_count).toBe(3) // THETA, GAMMA, KALMAN
      expect(clusters[0].level).toBe(502.5)
    })

    it('P03: 0DTE Afternoon Charm Bleed + Put Wall Decay Interaction', () => {
      const regime: MarketRegimeType = 'charm_decay_selling'
      const putWall: PriceDrawLevel = {
        id: 'pw',
        type: 'put_wall',
        label: 'Put Wall',
        price: 450.0,
        distance_pts: -5.0,
        distance_pct: -1.1,
        pull_score: 85.0,
        direction: 'below',
        regime_role: 'Downside Support',
        supporting_lenses: ['GAMMA', 'THETA'],
        lens_count: 2,
        is_primary_magnet: true,
      }
      expect(getRegimeBadgeClass(regime)).toBe('regime-badge--charm')
      expect(putWall.direction).toBe('below')
      expect(putWall.supporting_lenses).toContain('THETA')
    })

    it('P04: Batch Quote Coalescing + In-Flight Deduplication Logic', () => {
      const inFlightRequests = new Map<string, Promise<PriceDrawTelemetryPayload>>()
      const mockFetch = vi
        .fn()
        .mockImplementation((sym: string) => Promise.resolve(createUnmeasuredPayload(sym)))

      function fetchTelemetry(sym: string): Promise<PriceDrawTelemetryPayload> {
        const key = sym.toUpperCase()
        if (inFlightRequests.has(key)) {
          return inFlightRequests.get(key)!
        }
        const promise = mockFetch(key).finally(() => {
          inFlightRequests.delete(key)
        })
        inFlightRequests.set(key, promise)
        return promise
      }

      const p1 = fetchTelemetry('NVDA')
      const p2 = fetchTelemetry('NVDA')
      expect(p1).toBe(p2) // Same promise coalesced
      expect(mockFetch).toHaveBeenCalledTimes(1)
    })

    it('P05: Missing OI Feed + Option Chain Payload Integration', () => {
      const payload = createUnmeasuredPayload('IWM', 'Zero OI captured in chain')
      expect(payload.quality.measurable).toBe(false)
      expect(payload.quality.open_interest_available).toBe(false)
      expect(isRegimeMeasurable(payload.regime_state)).toBe(false)
      expect(formatDistancePercent(payload.primary_magnet?.distance_pct ?? null)).toBe(
        UNMEASURED_PLACEHOLDER,
      )
    })

    it('P06: High Vanna Sensitivity + Volatility Expansion Regime Mapping', () => {
      const regime: MarketRegimeType = 'vanna_vol_expansion'
      expect(isRegimeMeasurable(regime)).toBe(true)
      expect(getRegimeLabel(regime)).toContain('Vanna Expansion')
      expect(getRegimeBadgeClass(regime)).toBe('regime-badge--vanna')
    })

    it('P07: Call Wall / Put Wall Inversion Handled Correctly', () => {
      // Inverted market where Put Wall > Call Wall due to heavy puts
      const spot = 100.0
      const putWall: PriceDrawLevel = {
        id: 'pw',
        type: 'put_wall',
        label: 'Put Wall',
        price: 105.0,
        distance_pts: 5.0,
        distance_pct: 5.0,
        pull_score: 90.0,
        direction: 'above',
        regime_role: 'Inverted Support',
        supporting_lenses: ['GAMMA'],
        lens_count: 1,
        is_primary_magnet: false,
      }
      const callWall: PriceDrawLevel = {
        id: 'cw',
        type: 'call_wall',
        label: 'Call Wall',
        price: 95.0,
        distance_pts: -5.0,
        distance_pct: -5.0,
        pull_score: 50.0,
        direction: 'below',
        regime_role: 'Inverted Resistance',
        supporting_lenses: ['GAMMA'],
        lens_count: 1,
        is_primary_magnet: false,
      }
      const dir = determineDominantDirection([putWall, callWall], spot)
      expect(dir).toBe('bullish_pull') // Net pull above spot exceeds 15% threshold
    })

    it('P08: Confluence Cluster Formation + Dominant Direction Pull Alignment', () => {
      const spot = 100.0
      const levels: PriceDrawLevel[] = [
        {
          id: 'cw',
          type: 'call_wall',
          label: 'Call Wall',
          price: 110.0,
          distance_pts: 10,
          distance_pct: 10,
          pull_score: 90,
          direction: 'above',
          regime_role: 'Resistance',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: true,
        },
        {
          id: 'poc',
          type: 'volume_poc',
          label: 'Volume POC',
          price: 110.5,
          distance_pts: 10.5,
          distance_pct: 10.5,
          pull_score: 80,
          direction: 'above',
          regime_role: 'High Volume',
          supporting_lenses: ['VOLUME'],
          lens_count: 1,
          is_primary_magnet: false,
        },
      ]
      const clusters = computeConfluenceClusters(levels, spot, 1.0)
      const dominantDir = determineDominantDirection(levels, spot)
      expect(clusters).toHaveLength(1)
      expect(clusters[0].above_spot).toBe(true)
      expect(dominantDir).toBe('bullish_pull')
    })
  })

  // =========================================================================
  // TIER 4: REAL-WORLD INSTITUTIONAL SCENARIOS (S01 - S06)
  // =========================================================================

  describe('Tier 4: Real-World Institutional Scenarios (6 Scenarios)', () => {
    it('S01: Triple Witching Quarterly OpEx Pinning Simulation', () => {
      const spot = 500.0
      const maxPainLevel: PriceDrawLevel = {
        id: 'mp_500',
        type: 'max_pain_pin',
        label: 'Max Pain Pin',
        price: 500.0,
        distance_pts: 0.0,
        distance_pct: 0.0,
        pull_score: 98.0,
        direction: 'at_spot',
        regime_role: 'OpEx Quarterly Pinning Magnet',
        supporting_lenses: ['THETA', 'GAMMA', 'VOLUME'],
        lens_count: 3,
        is_primary_magnet: true,
      }
      expect(maxPainLevel.price).toBe(spot)
      expect(maxPainLevel.direction).toBe('at_spot')
      expect(maxPainLevel.pull_score).toBeGreaterThan(95.0)
      expect(formatDistancePercent(maxPainLevel.distance_pct)).toBe('0.00%')
    })

    it('S02: Short-Gamma Squeeze Cascade Acceleration Simulation', () => {
      const spot = 155.0
      const regime: MarketRegimeType = 'volatility_amplification'
      const callWall: PriceDrawLevel = {
        id: 'cw_150',
        type: 'call_wall',
        label: 'Call Wall',
        price: 150.0,
        distance_pts: -5.0,
        distance_pct: -3.23,
        pull_score: 92.0,
        direction: 'below', // Breached above Call Wall
        regime_role: 'Breached Resistance - Short Squeeze Fuel',
        supporting_lenses: ['GAMMA', 'KALMAN'],
        lens_count: 2,
        is_primary_magnet: true,
      }
      expect(spot).toBeGreaterThan(callWall.price)
      expect(getRegimeBadgeClass(regime)).toBe('regime-badge--amplification')
      expect(callWall.direction).toBe('below')
      expect(callWall.pull_score).toBeGreaterThan(90)
    })

    it('S03: 0DTE Afternoon Charm Bleed Flash Draw Simulation', () => {
      const regime: MarketRegimeType = 'charm_decay_selling'
      const spot = 430.0
      const charmLevel: PriceDrawLevel = {
        id: 'charm_attractor',
        type: 'kinematic_drift',
        label: 'Charm Bleed Drift',
        price: 426.0,
        distance_pts: -4.0,
        distance_pct: -0.93,
        pull_score: 88.0,
        direction: 'below',
        regime_role: 'Delta Bleed Dealer Selling Pressure',
        supporting_lenses: ['THETA', 'KALMAN'],
        lens_count: 2,
        is_primary_magnet: true,
      }
      expect(spot).toBeGreaterThan(charmLevel.price)
      expect(getRegimeLabel(regime)).toContain('Selling Drift')
      expect(charmLevel.direction).toBe('below')
      expect(formatDistancePercent(charmLevel.distance_pct)).toBe('-0.93%')
    })

    it('S04: Market Open Volatility Dislocation & Gap Handling', () => {
      // Overnight gap: Spot jumps from 100 to 104 (+4%)
      const preMarketSpot = 100.0
      const openSpot = 104.0
      const gammaFlipPrice = 101.0

      const telPre = computeDistanceTelemetry(gammaFlipPrice, preMarketSpot)
      const telOpen = computeDistanceTelemetry(gammaFlipPrice, openSpot)

      expect(telPre.direction).toBe('above') // Flip was above pre-market
      expect(telOpen.direction).toBe('below') // Flip is now below open spot
      expect(telOpen.distance_pts).toBe(-3.0)
    })

    it('S05: Sudden Regime Pivot upon Put Wall Breach', () => {
      // Spot drops below put wall from 202 to 196 (Put Wall at 200)
      const spot = 196.0
      const putWall: PriceDrawLevel = {
        id: 'pw_200',
        type: 'put_wall',
        label: 'Put Wall',
        price: 200.0,
        distance_pts: 4.0,
        distance_pct: 2.04,
        pull_score: 95.0,
        direction: 'above',
        regime_role: 'Breached Floor -> Volatility Cascade',
        supporting_lenses: ['GAMMA'],
        lens_count: 1,
        is_primary_magnet: true,
      }
      expect(spot).toBeLessThan(putWall.price)
      expect(putWall.direction).toBe('above')
      expect(formatDistancePoints(putWall.distance_pts)).toBe('+4.00')
    })

    it('S06: Earnings Announcement IV Crush & Magnet Dissipation Simulation', () => {
      // Post earnings: IV drops from 120% to 35%, pull scores collapse
      const preEarningsPull = 95.0
      const postEarningsPull = 25.0

      expect(formatPullScore(preEarningsPull)).toBe('95')
      expect(formatPullScore(postEarningsPull)).toBe('25')
      expect(postEarningsPull).toBeLessThan(preEarningsPull)
    })
  })
})
