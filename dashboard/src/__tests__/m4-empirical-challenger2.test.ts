/**
 * Challenger 2: Milestone 4 Empirical Adversarial Verification Suite
 *
 * Rigorously stress-tests:
 * 1. All 7 market regime types across components and view contracts.
 * 2. All 4 directional pull vector badges and edge pill formatting.
 * 3. Primary magnet levels with extreme distances (+500%, -90%, +10000%), identical prices,
 *    and degenerate coordinate domains (zero-span, spot == price, NaN/Infinity).
 * 4. Layout robustness and zero-spoofing resilience across LiveStackView & DeskView.
 */
import { describe, it, expect } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import RegimeStateBadge from '../components/RegimeStateBadge.vue'
import PriceDrawLadder from '../components/PriceDrawLadder.vue'
import {
  type MarketRegimeType,
  type DominantDirectionType,
  type PriceDrawLevel,
  isRegimeMeasurable,
  getRegimeBadgeClass,
  computeDistanceTelemetry,
  computeConfluenceClusters,
  determineDominantDirection,
  createUnmeasuredPayload,
  formatDistancePercent,
  formatDistancePoints,
  formatPullScore,
  getRegimeLabel,
} from '../priceDrawContracts'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

async function renderBadge(props: Record<string, unknown> = {}): Promise<string> {
  const app = createSSRApp({
    render: () => h(RegimeStateBadge, props),
  })
  return renderToString(app)
}

async function renderLadder(props: Record<string, unknown> = {}): Promise<string> {
  const app = createSSRApp({
    render: () => h(PriceDrawLadder, props),
  })
  return renderToString(app)
}

describe('Challenger 2 Empirical Verification: Milestone 4 Views & Components', () => {
  // =========================================================================
  // Mission 1: Verify all 7 Market Regime Types
  // =========================================================================
  describe('1. Market Regime Matrix Verification (All 7 Types)', () => {
    const regimes: Array<{
      type: MarketRegimeType
      expectedLabel: string
      badgeClass: string
      pillClass: string
    }> = [
      {
        type: 'volatility_dampening',
        expectedLabel: 'VOL DAMPENING · LONG Γ',
        badgeClass: 'regime-badge--dampening',
        pillClass: 'regime-dampening',
      },
      {
        type: 'volatility_amplification',
        expectedLabel: 'VOL AMPLIFICATION · SHORT Γ',
        badgeClass: 'regime-badge--amplification',
        pillClass: 'regime-amplification',
      },
      {
        type: 'charm_decay_selling',
        expectedLabel: 'CHARM DECAY · SELLING DRIFT',
        badgeClass: 'regime-badge--charm',
        pillClass: 'regime-charm',
      },
      {
        type: 'charm_decay_buying',
        expectedLabel: 'CHARM DECAY · BUYING DRIFT',
        badgeClass: 'regime-badge--charm',
        pillClass: 'regime-charm',
      },
      {
        type: 'vanna_vol_expansion',
        expectedLabel: 'VANNA EXPANSION · VOL SHOCK',
        badgeClass: 'regime-badge--vanna',
        pillClass: 'regime-vanna',
      },
      {
        type: 'neutral_transition',
        expectedLabel: 'TRANSITION STRADDLE · Γ-FLIP',
        badgeClass: 'regime-badge--neutral',
        pillClass: 'regime-transition',
      },
      {
        type: 'unmeasurable',
        expectedLabel: 'REGIME UNMEASURED',
        badgeClass: 'regime-badge--unmeasured',
        pillClass: 'regime-unmeasured',
      },
    ]

    for (const r of regimes) {
      it(`correctly handles and renders regime '${r.type}'`, async () => {
        expect(getRegimeBadgeClass(r.type)).toBe(r.badgeClass)

        const isMeasurableFlag = r.type !== 'unmeasurable'
        expect(isRegimeMeasurable(r.type)).toBe(isMeasurableFlag)

        const html = await renderBadge({
          regimeState: r.type,
          dominantDirection: isMeasurableFlag ? 'neutral_pin' : 'unmeasured',
          regimeStrength: isMeasurableFlag ? 0.75 : null,
          measurable: isMeasurableFlag,
        })

        expect(html).toContain(r.expectedLabel)
        expect(html).toContain(r.pillClass)
        if (isMeasurableFlag) {
          expect(html).toContain('75%')
        } else {
          expect(html).not.toContain('75%')
          expect(html).toContain('regime-unmeasured')
        }
      })
    }
  })

  // =========================================================================
  // Mission 2: Verify Directional Pull Vectors (4 Types)
  // =========================================================================
  describe('2. Directional Pull Vectors Verification (All 4 Types)', () => {
    const vectors: Array<{
      type: DominantDirectionType
      expectedGlyph: string
      expectedClass: string
      measurable: boolean
    }> = [
      {
        type: 'bullish_pull',
        expectedGlyph: '▲ BULLISH PULL',
        expectedClass: 'vector-bullish',
        measurable: true,
      },
      {
        type: 'bearish_pull',
        expectedGlyph: '▼ BEARISH PULL',
        expectedClass: 'vector-bearish',
        measurable: true,
      },
      {
        type: 'neutral_pin',
        expectedGlyph: '● NEUTRAL PIN',
        expectedClass: 'vector-neutral',
        measurable: true,
      },
      {
        type: 'unmeasured',
        expectedGlyph: '—',
        expectedClass: 'vector-unmeasured',
        measurable: false,
      },
    ]

    for (const v of vectors) {
      it(`renders directional vector badge pill '${v.type}' with correct style`, async () => {
        const html = await renderBadge({
          regimeState: v.measurable ? 'volatility_dampening' : 'unmeasurable',
          dominantDirection: v.type,
          measurable: v.measurable,
        })

        expect(html).toContain(v.expectedGlyph)
        expect(html).toContain(v.expectedClass)
      })
    }

    it('determines dominant direction empirically from level arrays', () => {
      const spot = 500
      const bullishLevels: PriceDrawLevel[] = [
        {
          id: 'cw',
          type: 'call_wall',
          label: 'Call Wall',
          price: 520,
          distance_pts: 20,
          distance_pct: 4,
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
          price: 480,
          distance_pts: -20,
          distance_pct: -4,
          pull_score: 20,
          direction: 'below',
          regime_role: 'Support',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
      ]
      expect(determineDominantDirection(bullishLevels, spot)).toBe('bullish_pull')

      const bearishLevels: PriceDrawLevel[] = [
        {
          id: 'cw',
          type: 'call_wall',
          label: 'Call Wall',
          price: 520,
          distance_pts: 20,
          distance_pct: 4,
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
          price: 480,
          distance_pts: -20,
          distance_pct: -4,
          pull_score: 85,
          direction: 'below',
          regime_role: 'Support',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: true,
        },
      ]
      expect(determineDominantDirection(bearishLevels, spot)).toBe('bearish_pull')

      const balancedLevels: PriceDrawLevel[] = [
        {
          id: 'cw',
          type: 'call_wall',
          label: 'Call Wall',
          price: 520,
          distance_pts: 20,
          distance_pct: 4,
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
          price: 480,
          distance_pts: -20,
          distance_pct: -4,
          pull_score: 50,
          direction: 'below',
          regime_role: 'Support',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
      ]
      expect(determineDominantDirection(balancedLevels, spot)).toBe('neutral_pin')

      expect(determineDominantDirection([], spot)).toBe('unmeasured')
      expect(determineDominantDirection(balancedLevels, null)).toBe('unmeasured')
      expect(determineDominantDirection(balancedLevels, -10)).toBe('unmeasured')
    })
  })

  // =========================================================================
  // Mission 3: Primary Magnet Levels with Extreme Distances & Identical Prices
  // =========================================================================
  describe('3. Extreme Distances, Identical Prices & Degenerate Rails', () => {
    it('survives extreme +500% distance primary magnet without crashing gauge rail', async () => {
      const spot = 100.0
      const extremeLevel: PriceDrawLevel = {
        id: 'extreme_high',
        type: 'call_wall',
        label: 'Mega Call Wall',
        price: 600.0, // +500%
        distance_pts: 500.0,
        distance_pct: 500.0,
        pull_score: 95,
        direction: 'above',
        regime_role: 'Distant Resistance',
        supporting_lenses: ['GAMMA'],
        lens_count: 1,
        is_primary_magnet: true,
      }

      const html = await renderLadder({
        spot,
        levels: [extremeLevel],
        quality: {
          measurable: true,
          open_interest_available: true,
          iv_available: true,
          volume_available: true,
          reason: null,
        },
      })

      expect(html).toContain('Mega Call Wall')
      expect(html).toContain('$600.00')
      expect(html).toContain('+500.00%')
      expect(html).toContain('gauge-marker')
      expect(html).not.toContain('NaN')
      expect(html).not.toContain('Infinity')
    })

    it('survives extreme -90% distance primary magnet without crashing gauge rail', async () => {
      const spot = 1000.0
      const extremeLowLevel: PriceDrawLevel = {
        id: 'extreme_low',
        type: 'put_wall',
        label: 'Deep Crash Put Wall',
        price: 100.0, // -90%
        distance_pts: -900.0,
        distance_pct: -90.0,
        pull_score: 99,
        direction: 'below',
        regime_role: 'Tail Risk Floor',
        supporting_lenses: ['GAMMA', 'GEX'],
        lens_count: 2,
        is_primary_magnet: true,
      }

      const html = await renderLadder({
        spot,
        levels: [extremeLowLevel],
        quality: {
          measurable: true,
          open_interest_available: true,
          iv_available: true,
          volume_available: true,
          reason: null,
        },
      })

      expect(html).toContain('Deep Crash Put Wall')
      expect(html).toContain('$100.00')
      expect(html).toContain('-90.00%')
      expect(html).not.toContain('NaN')
    })

    it('survives extreme +10,000% distance attractor without numeric overflow', async () => {
      const spot = 10.0
      const moonLevel: PriceDrawLevel = {
        id: 'moon_level',
        type: 'call_wall',
        label: 'Moon Strike',
        price: 1010.0, // +10,000%
        distance_pts: 1000.0,
        distance_pct: 10000.0,
        pull_score: 100,
        direction: 'above',
        regime_role: 'Extreme OTM',
        supporting_lenses: ['GAMMA'],
        lens_count: 1,
        is_primary_magnet: true,
      }

      const html = await renderLadder({
        spot,
        levels: [moonLevel],
        quality: {
          measurable: true,
          open_interest_available: true,
          iv_available: true,
          volume_available: true,
          reason: null,
        },
      })

      expect(html).toContain('Moon Strike')
      expect(html).toContain('+10,000.00%')
      expect(html).not.toContain('NaN')
    })

    it('handles identical prices across all levels and spot (zero domain span) gracefully', async () => {
      const identicalPrice = 500.0
      const identicalLevels: PriceDrawLevel[] = [
        {
          id: 'cw_500',
          type: 'call_wall',
          label: 'Call Wall',
          price: identicalPrice,
          distance_pts: 0.0,
          distance_pct: 0.0,
          pull_score: 80,
          direction: 'at_spot',
          regime_role: 'Pinned Wall',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: true,
        },
        {
          id: 'pw_500',
          type: 'put_wall',
          label: 'Put Wall',
          price: identicalPrice,
          distance_pts: 0.0,
          distance_pct: 0.0,
          pull_score: 80,
          direction: 'at_spot',
          regime_role: 'Pinned Wall',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
        {
          id: 'flip_500',
          type: 'gamma_flip',
          label: 'Gamma Flip',
          price: identicalPrice,
          distance_pts: 0.0,
          distance_pct: 0.0,
          pull_score: 80,
          direction: 'at_spot',
          regime_role: 'Zero Gamma Pivot',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
      ]

      const html = await renderLadder({
        spot: identicalPrice,
        levels: identicalLevels,
        quality: {
          measurable: true,
          open_interest_available: true,
          iv_available: true,
          volume_available: true,
          reason: null,
        },
      })

      expect(html).toContain('Call Wall')
      expect(html).toContain('Put Wall')
      expect(html).toContain('Gamma Flip')
      expect(html).toContain('$500.00')
      // Ensure no NaN% in CSS styles
      expect(html).not.toContain('top: NaN%')
      expect(html).not.toContain('top: undefined%')
    })

    it('filters out invalid/non-positive/NaN/Infinity level prices cleanly', async () => {
      const corruptLevels: PriceDrawLevel[] = [
        {
          id: 'valid_lvl',
          type: 'call_wall',
          label: 'Valid Call Wall',
          price: 550.0,
          distance_pts: 50.0,
          distance_pct: 10.0,
          pull_score: 75,
          direction: 'above',
          regime_role: 'Valid Resistance',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: true,
        },
        {
          id: 'neg_lvl',
          type: 'put_wall',
          label: 'Corrupt Neg Wall',
          price: -50.0,
          distance_pts: -550.0,
          distance_pct: -110.0,
          pull_score: 10,
          direction: 'below',
          regime_role: 'Corrupt',
          supporting_lenses: [],
          lens_count: 0,
          is_primary_magnet: false,
        },
        {
          id: 'nan_lvl',
          type: 'gamma_flip',
          label: 'Corrupt NaN Flip',
          price: NaN,
          distance_pts: null,
          distance_pct: null,
          pull_score: null,
          direction: 'at_spot',
          regime_role: 'Corrupt',
          supporting_lenses: [],
          lens_count: 0,
          is_primary_magnet: false,
        },
        {
          id: 'inf_lvl',
          type: 'max_pain_pin',
          label: 'Corrupt Inf Pin',
          price: Infinity,
          distance_pts: null,
          distance_pct: null,
          pull_score: null,
          direction: 'at_spot',
          regime_role: 'Corrupt',
          supporting_lenses: [],
          lens_count: 0,
          is_primary_magnet: false,
        },
      ]

      const html = await renderLadder({
        spot: 500.0,
        levels: corruptLevels,
        quality: {
          measurable: true,
          open_interest_available: true,
          iv_available: true,
          volume_available: true,
          reason: null,
        },
      })

      expect(html).toContain('Valid Call Wall')
      expect(html).not.toContain('Corrupt Neg Wall')
      expect(html).not.toContain('Corrupt NaN Flip')
      expect(html).not.toContain('Corrupt Inf Pin')
      expect(html).not.toContain('NaN')
      expect(html).not.toContain('Infinity')
    })
  })

  // =========================================================================
  // Mission 4: Confluence Clustering & Pure Helper Stress
  // =========================================================================
  describe('4. Confluence Clustering & Distance Telemetry Edge Tests', () => {
    it('computes distance telemetry accurately across edge spot prices', () => {
      expect(computeDistanceTelemetry(105, 100)).toEqual({
        distance_pts: 5,
        distance_pct: 5,
        direction: 'above',
      })

      expect(computeDistanceTelemetry(95, 100)).toEqual({
        distance_pts: -5,
        distance_pct: -5,
        direction: 'below',
      })

      expect(computeDistanceTelemetry(100.00001, 100)).toEqual({
        distance_pts: 0,
        distance_pct: 0,
        direction: 'at_spot',
      })

      expect(computeDistanceTelemetry(100, null)).toEqual({
        distance_pts: null,
        distance_pct: null,
        direction: 'at_spot',
      })

      expect(computeDistanceTelemetry(100, 0)).toEqual({
        distance_pts: null,
        distance_pct: null,
        direction: 'at_spot',
      })

      expect(computeDistanceTelemetry(100, -50)).toEqual({
        distance_pts: null,
        distance_pct: null,
        direction: 'at_spot',
      })
    })

    it('clusters multiple adjacent levels within threshold into unified confluence zones', () => {
      const spot = 500
      const clusterableLevels: PriceDrawLevel[] = [
        {
          id: 'cw_502',
          type: 'call_wall',
          label: 'Call Wall',
          price: 502.0,
          distance_pts: 2.0,
          distance_pct: 0.4,
          pull_score: 80,
          direction: 'above',
          regime_role: 'Resistance',
          supporting_lenses: ['GAMMA', 'GEX'],
          lens_count: 2,
          is_primary_magnet: true,
        },
        {
          id: 'vp_503',
          type: 'volume_poc',
          label: 'Volume POC',
          price: 503.0,
          distance_pts: 3.0,
          distance_pct: 0.6,
          pull_score: 70,
          direction: 'above',
          regime_role: 'High Volume Node',
          supporting_lenses: ['VOLUME'],
          lens_count: 1,
          is_primary_magnet: false,
        },
        {
          id: 'pw_470',
          type: 'put_wall',
          label: 'Put Wall',
          price: 470.0,
          distance_pts: -30.0,
          distance_pct: -6.0,
          pull_score: 85,
          direction: 'below',
          regime_role: 'Support',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
      ]

      const clusters = computeConfluenceClusters(clusterableLevels, spot, 0.75)
      expect(clusters.length).toBe(1)
      expect(clusters[0].level).toBe(502.5)
      expect(clusters[0].distance_pct).toBe(0.5)
      expect(clusters[0].lens_count).toBe(3) // GAMMA, GEX, VOLUME
      expect(clusters[0].supporting_lenses).toEqual(
        expect.arrayContaining(['GAMMA', 'GEX', 'VOLUME']),
      )
      expect(clusters[0].labels).toEqual(['Call Wall', 'Volume POC'])
      expect(clusters[0].above_spot).toBe(true)
    })

    it('validates pure formatting and unmeasured payload helpers under adversarial values', () => {
      const payload = createUnmeasuredPayload('TEST_SYM', 'Custom missing reason')
      expect(payload.symbol).toBe('TEST_SYM')
      expect(payload.spot).toBeNull()
      expect(payload.regime_state).toBe('unmeasurable')
      expect(payload.quality.measurable).toBe(false)
      expect(payload.quality.reason).toBe('Custom missing reason')

      expect(getRegimeLabel('unmeasurable')).toBe('Unmeasured Regime')
      expect(getRegimeLabel('volatility_dampening')).toContain('Vol Dampening')

      expect(formatDistancePoints(null)).toBe('—')
      expect(formatDistancePoints(NaN)).toBe('—')
      expect(formatDistancePoints(Infinity)).toBe('—')
      expect(formatDistancePoints(12.345)).toBe('+12.35')
      expect(formatDistancePoints(-9.876)).toBe('-9.88')

      expect(formatDistancePercent(null)).toBe('—')
      expect(formatDistancePercent(NaN)).toBe('—')
      expect(formatDistancePercent(Infinity)).toBe('—')
      expect(formatDistancePercent(5.678)).toBe('+5.68%')
      expect(formatDistancePercent(-1.234)).toBe('-1.23%')

      expect(formatPullScore(null)).toBe('—')
      expect(formatPullScore(NaN)).toBe('—')
      expect(formatPullScore(-20)).toBe('0')
      expect(formatPullScore(150)).toBe('100')
      expect(formatPullScore(87.6)).toBe('88')
    })
  })

  // =========================================================================
  // Mission 5: Source Contract Invariants in LiveStackView and DeskView
  // =========================================================================
  describe('5. Source View Invariants and Template Integrity', () => {
    it('LiveStackView satisfies all regime, magnet, and zero-spoofing architectural tokens', () => {
      const liveStackSrc = source('views/LiveStackView.vue')

      // Component wiring
      expect(liveStackSrc).toContain(
        "import RegimeStateBadge from '@/components/RegimeStateBadge.vue'",
      )
      expect(liveStackSrc).toContain(
        "import PriceDrawLadder from '@/components/PriceDrawLadder.vue'",
      )
      expect(liveStackSrc).toContain(
        "import type { PriceDrawTelemetryPayload, PriceDrawLevel } from '@/priceDrawContracts'",
      )

      // Reactive stream subscription
      expect(liveStackSrc).toContain('const priceDrawRes = useResource<PriceDrawTelemetryPayload>(')
      expect(liveStackSrc).toContain('api.priceAttractors(symbol.value)')

      // Template integration
      expect(liveStackSrc).toContain('<RegimeStateBadge')
      expect(liveStackSrc).toContain('<PriceDrawLadder')
      expect(liveStackSrc).toContain(':payload="priceDrawPayload"')
    })

    it('DeskView satisfies all multi-panel regime/magnet columns and breadth KPI card tokens', () => {
      const deskSrc = source('views/DeskView.vue')

      // Component & contract imports
      expect(deskSrc).toContain("import RegimeStateBadge from '@/components/RegimeStateBadge.vue'")
      expect(deskSrc).toContain('isRegimeMeasurable')
      expect(deskSrc).toContain('formatDistancePercent')

      // Reactive telemetry map
      expect(deskSrc).toContain(
        'const regimeTelemetryMap = ref<Record<string, PriceDrawTelemetryPayload>>({})',
      )

      // Breadth KPI computation
      expect(deskSrc).toContain('const marketRegimeBreadth = computed(() => {')
      expect(deskSrc).toContain('dampening++')
      expect(deskSrc).toContain('amplification++')

      // Template table columns (Panel 01, Panel 03, Panel 04)
      expect(deskSrc).toContain('<th class="label col-regime">Regime / Magnet</th>')
      expect(deskSrc).toContain('Regime & Magnet Breadth')
      expect(deskSrc).toContain('kpi-regime-card')
    })
  })
})
