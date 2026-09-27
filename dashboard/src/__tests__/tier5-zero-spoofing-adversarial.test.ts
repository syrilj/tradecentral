import { describe, it, expect } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import PriceDrawLadder from '../components/PriceDrawLadder.vue'
import RegimeStateBadge from '../components/RegimeStateBadge.vue'
import GammaExposureMap from '../components/GammaExposureMap.vue'
import OptionsDriftChart from '../components/OptionsDriftChart.vue'
import ProbabilityDensityChart from '../components/ProbabilityDensityChart.vue'
import GammaHistoryStrip from '../components/GammaHistoryStrip.vue'
import MarketContextCard from '../components/MarketContextCard.vue'
import ForwardTrajectoryCard from '../components/ForwardTrajectoryCard.vue'
import PositioningSummaryCard from '../components/PositioningSummaryCard.vue'
import InstantaneousHedgingCard from '../components/InstantaneousHedgingCard.vue'
import KeyLevelsCard from '../components/KeyLevelsCard.vue'
import FlowSummaryDonutCard from '../components/FlowSummaryDonutCard.vue'
import PrimaryRegimeCard from '../components/PrimaryRegimeCard.vue'
import FourPillarContextGrid from '../components/FourPillarContextGrid.vue'
import TransitionRiskGauge from '../components/TransitionRiskGauge.vue'
import ModelAgreementMatrix from '../components/ModelAgreementMatrix.vue'
import DynamicExplanationPanel from '../components/DynamicExplanationPanel.vue'
import type { PriceDrawTelemetryPayload } from '../priceDrawContracts'
import type { MarketRegimePayload } from '../regimeContracts'

async function renderComponent(component: any, props: Record<string, any> = {}): Promise<string> {
  const app = createSSRApp({
    render: () => h(component, props),
  })
  return renderToString(app)
}

describe('Tier 5 Adversarial Zero-Spoofing & Null-Safety Stress Suite', () => {
  describe('PriceDrawLadder.vue Zero-Spoofing Invariants', () => {
    it('handles completely null / undefined props without crashing', async () => {
      const html = await renderComponent(PriceDrawLadder, {
        payload: null,
        levels: undefined,
        spot: null,
        quality: null,
        symbol: 'CORRUPT',
      })
      expect(html).toBeTruthy()
      expect(html).toContain('CORRUPT')
      expect(html).toContain('REGIME UNMEASURED')
    })

    it('renders placeholder DASH and unmeasured banner when measurable is false', async () => {
      const unmeasurablePayload: PriceDrawTelemetryPayload = {
        symbol: 'UNMEASURED_SYM',
        spot: null,
        asof_utc: '2026-08-29T12:00:00Z',
        regime_state: 'unmeasurable',
        regime_label: 'Unmeasured Regime',
        regime_strength: null,
        dominant_direction: 'unmeasured',
        primary_magnet: null,
        levels: [],
        confluence_clusters: [],
        quality: {
          measurable: false,
          open_interest_available: false,
          iv_available: false,
          volume_available: false,
          reason: 'No listed options chain available',
        },
        warnings: ['No listed options chain available'],
      }

      const html = await renderComponent(PriceDrawLadder, {
        payload: unmeasurablePayload,
      })

      expect(html).toBeTruthy()
      expect(html).toContain('unmeasured-state')
      expect(html).toContain('REGIME UNMEASURED · NO ACTIVE PRICE MAGNETS')
      expect(html).toContain('No listed options chain available')
    })

    it('filters out non-finite or negative prices without throwing exceptions', async () => {
      const corruptLevels: any[] = [
        {
          id: 'corrupt_1',
          type: 'call_wall',
          label: 'Corrupt NaN',
          price: NaN,
          distance_pts: NaN,
          distance_pct: NaN,
          pull_score: 50,
          direction: 'above',
          regime_role: 'Resistance',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: true,
        },
        {
          id: 'corrupt_2',
          type: 'put_wall',
          label: 'Corrupt Negative',
          price: -100,
          distance_pts: -200,
          distance_pct: -200,
          pull_score: 40,
          direction: 'below',
          regime_role: 'Support',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
        {
          id: 'valid_1',
          type: 'gamma_flip',
          label: 'Valid Flip',
          price: 150.0,
          distance_pts: 0.0,
          distance_pct: 0.0,
          pull_score: 90,
          direction: 'at_spot',
          regime_role: 'Pivot',
          supporting_lenses: ['GAMMA'],
          lens_count: 1,
          is_primary_magnet: false,
        },
      ]

      const html = await renderComponent(PriceDrawLadder, {
        levels: corruptLevels,
        spot: 150.0,
        symbol: 'CORRUPT_LEVELS',
      })

      expect(html).toBeTruthy()
      expect(html).toContain('Valid Flip')
      expect(html).not.toContain('Corrupt NaN')
      expect(html).not.toContain('Corrupt Negative')
    })
  })

  describe('RegimeStateBadge.vue Zero-Spoofing Invariants', () => {
    it('renders REGIME UNMEASURED and DASH for null strength when unmeasurable', async () => {
      const html = await renderComponent(RegimeStateBadge, {
        regimeState: 'unmeasurable',
        regimeStrength: null,
        measurable: false,
      })
      expect(html).toBeTruthy()
      expect(html).toContain('REGIME UNMEASURED')
      expect(html).toContain('—')
      expect(html).toContain('regime-unmeasured')
    })

    it('clamps strength display without throwing errors on out-of-bound inputs', async () => {
      const html = await renderComponent(RegimeStateBadge, {
        regimeState: 'volatility_dampening',
        regimeStrength: 0.854,
        measurable: true,
      })
      expect(html).toBeTruthy()
      expect(html).toContain('VOL DAMPENING · LONG Γ')
      expect(html).toContain('85%')
    })
  })

  describe('Secondary Cards Adversarial Zero-Spoofing Under Null Inputs', () => {
    it('MarketContextCard: produces zero fake technical tags or prices when inputs are null', async () => {
      const html = await renderComponent(MarketContextCard, {
        symbol: 'NULL_TEST',
        spot: null,
        vwap: null,
        gammaFlip: null,
        callWall: null,
        putWall: null,
        netFlowM: null,
        ivRank: null,
        kalmanVelocity: null,
      })

      expect(html).toContain('Context Unmeasured')
      expect(html).not.toContain('Price &gt; VWAP')
      expect(html).not.toContain('Price &lt; VWAP')
      expect(html).not.toContain('Bullish Flow')
      expect(html).not.toContain('Bearish Flow')
      expect(html).not.toContain('IV Normal')
      expect(html).not.toContain('525')
    })

    it('ForwardTrajectoryCard: produces empty steps instead of fabricated $525 / s*0.995 levels', async () => {
      const html = await renderComponent(ForwardTrajectoryCard, {
        symbol: 'NULL_TRAJ',
        spot: null,
        regime: null,
        gammaFlip: null,
        callWall: null,
        putWall: null,
        pinStrike: null,
      })

      expect(html).toContain('Trajectory levels unmeasured')
      expect(html).not.toContain('$525')
      expect(html).not.toContain('$522')
      expect(html).not.toContain('$519')
    })

    it('PositioningSummaryCard: renders DASH and Unmeasured without default +87.4M or Bullish', async () => {
      const html = await renderComponent(PositioningSummaryCard, {})

      expect(html).toContain('Unmeasured')
      expect(html).toContain('—')
      expect(html).not.toContain('+87.4M')
      expect(html).not.toContain('Bullish')
    })

    it('InstantaneousHedgingCard: renders DASH without static -234.7M or +161.5M fake numbers', async () => {
      const html = await renderComponent(InstantaneousHedgingCard, {
        snapshot: null,
        spot: null,
        netGammaM: null,
      })

      expect(html).toContain('—')
      expect(html).not.toContain('-234.7M')
      expect(html).not.toContain('+161.5M')
      expect(html).not.toContain('+179.2M')
      expect(html).not.toContain('vs prev. 1h -18.2%')
    })

    it('KeyLevelsCard: renders DASH without hardcoded 525.16 or synthetic multipliers', async () => {
      const html = await renderComponent(KeyLevelsCard, {
        spot: null,
        maxPain: null,
        vwap: null,
        resistance: null,
        support: null,
      })

      expect(html).toContain('—')
      expect(html).not.toContain('525.16')
      expect(html).not.toContain('$525')
    })

    it('FlowSummaryDonutCard: renders DASH and unmeasured when flows are null', async () => {
      const html = await renderComponent(FlowSummaryDonutCard, {
        totalPremiumM: null,
        bullishPremiumM: null,
        bearishPremiumM: null,
        netFlowM: null,
      })

      expect(html).toContain('—')
    })
  })

  describe('Multi-Dimensional Workstation Components Zero-Spoofing', () => {
    it('PrimaryRegimeCard: renders UNMEASURED and DASH when payload is null', async () => {
      const html = await renderComponent(PrimaryRegimeCard, {
        payload: null,
        symbol: 'NULL_REGIME',
        spot: null,
      })

      expect(html).toContain('REGIME UNMEASURED')
      expect(html).toContain('—')
    })

    it('FourPillarContextGrid: renders unmeasured notices when lenses are not measured', async () => {
      const nullPayload: MarketRegimePayload = {
        symbol: 'UNMEASURED',
        asof_utc: '2026-09-02T12:00:00Z',
        spot: null,
        primary: 'unmeasurable',
        primaryLabel: 'Regime Unmeasured',
        confidence: { score: 0, band: 'low', penaltyFactors: [] },
        trend: {
          state: 'unmeasured',
          slope: null,
          kalmanVelocity: null,
          kalmanZScore: null,
          trendPersistence: null,
          measured: false,
        },
        volatility: {
          state: 'unmeasured',
          realizedVolPct: null,
          impliedVolPct: null,
          volPercentile: null,
          parkinsonVolPct: null,
          ivHvRatio: null,
          measured: false,
        },
        structure: {
          state: 'unmeasured',
          ouHalfLifeBars: null,
          hurstExponent: null,
          breakoutZScore: null,
          exhaustionZScore: null,
          measured: false,
        },
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
        transition: {
          level: 'low',
          changepointProb5d: 0,
          changepointProb20d: 0,
          mapRunLength: 0,
          expectedRunLength: 0,
          stabilityScore: 0,
          measured: false,
        },
        agreement: {
          band: 'low',
          agreementScore: 0,
          agreeingModels: [],
          conflictingModels: [],
          divergenceSummary: null,
        },
        explanation: {
          headline: '',
          summary: '',
          leadingDrivers: [],
          riskFactors: [],
          uncertaintySources: [],
        },
        levels: { callWall: null, putWall: null, gammaFlip: null, sessionVwap: null },
        quality: { measurable: false, missingLenses: ['all'], reason: 'No data' },
      }

      const html = await renderComponent(FourPillarContextGrid, { payload: nullPayload })
      expect(html).toContain('Price bar history insufficient')
      expect(html).toContain('Historical volatility distribution unavailable')
      expect(html).toContain('Variance ratio and mean-reversion telemetry unmeasured')
      expect(html).toContain('No active option chain')
    })

    it('TransitionRiskGauge: renders unmeasured without fake hazard percentages', async () => {
      const html = await renderComponent(TransitionRiskGauge, {
        transition: null,
        measurable: false,
      })
      expect(html).toContain('UNMEASURED')
      expect(html).toContain('—')
    })

    it('ModelAgreementMatrix: handles null agreement cleanly', async () => {
      const html = await renderComponent(ModelAgreementMatrix, { agreement: null })
      // Null agreement must NOT spoof a "0% consensus" or an identity matrix.
      expect(html).toContain('—')
      expect(html).not.toContain('>0%<')
      expect(html).not.toContain('>1.0<')
    })

    it('DynamicExplanationPanel: handles empty explanations gracefully', async () => {
      const html = await renderComponent(DynamicExplanationPanel, {
        explanation: null,
        measurable: false,
      })
      expect(html).toContain('Deterministic Regime Synthesis Active')
    })
  })

  describe('Visual Polish Charts Null-Safety & Zero-Spoofing', () => {
    it('GammaExposureMap renders empty state gracefully without points', async () => {
      const html = await renderComponent(GammaExposureMap, {
        rows: [],
        spot: 0,
        callWall: 0,
        putWall: 0,
        gammaFlip: 0,
      })
      expect(html).toBeTruthy()
    })

    it('OptionsDriftChart renders empty state gracefully with null/empty series', async () => {
      const html = await renderComponent(OptionsDriftChart, {
        symbol: 'EMPTY_TEST',
        price: [],
        flow: [],
        spot: null,
      })
      expect(html).toBeTruthy()
    })

    it('ProbabilityDensityChart handles zero spot or missing IV without NaN SVG paths', async () => {
      const html = await renderComponent(ProbabilityDensityChart, {
        spot: 0,
        iv: 0,
        dte: 0,
      })
      expect(html).toBeTruthy()
    })

    it('GammaHistoryStrip renders gracefully with empty history array', async () => {
      const html = await renderComponent(GammaHistoryStrip, {
        history: [],
      })
      expect(html).toBeTruthy()
    })
  })
})
