import { describe, it, expect } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'

import PrimaryRegimeCard from '../components/PrimaryRegimeCard.vue'
import FourPillarContextGrid from '../components/FourPillarContextGrid.vue'
import TransitionRiskGauge from '../components/TransitionRiskGauge.vue'
import ModelAgreementMatrix from '../components/ModelAgreementMatrix.vue'
import DynamicExplanationPanel from '../components/DynamicExplanationPanel.vue'
import MarketContextCard from '../components/MarketContextCard.vue'
import ForwardTrajectoryCard from '../components/ForwardTrajectoryCard.vue'
import PositioningSummaryCard from '../components/PositioningSummaryCard.vue'
import InstantaneousHedgingCard from '../components/InstantaneousHedgingCard.vue'
import KeyLevelsCard from '../components/KeyLevelsCard.vue'
import FlowSummaryDonutCard from '../components/FlowSummaryDonutCard.vue'
import type { MarketRegimePayload } from '../regimeContracts'
import type { MicrostructureRegimeSnapshot } from '../microstructureContracts'

function visible(html: string): string {
  return html.replace(/<!--[\s\S]*?-->/g, '')
}

async function renderComponent(component: any, props: Record<string, any> = {}): Promise<string> {
  const app = createSSRApp({
    render: () => h(component, props),
  })
  return visible(await renderToString(app))
}

describe('Regime UI Components SSR & Behavioral Test Suite', () => {
  const mockPayload: MarketRegimePayload = {
    symbol: 'SPY',
    asof_utc: '2026-09-02T14:30:00Z',
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
      conflicts: [],
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
  }

  describe('PrimaryRegimeCard.vue', () => {
    it('renders hero badge, confidence meter, and probability simplex when measured', async () => {
      const html = await renderComponent(PrimaryRegimeCard, {
        payload: mockPayload,
        symbol: 'SPY',
        spot: 520.5,
      })

      expect(html).toContain('BULLISH TREND')
      expect(html).toContain('88%')
      expect(html).toContain('HIGH')
      expect(html).toContain('BULL 70%')
      expect(html).toContain('NEUT 15%')
      expect(html).toContain('BEAR 15%')
      expect(html).toContain('$520.50')
      expect(html).toContain('$530.00')
      expect(html).toContain('$505.00')
      expect(html).not.toContain('hazard-alert-glow')
    })

    it('renders hazard glow and banner when transition hazard is high', async () => {
      const highHazardPayload: MarketRegimePayload = {
        ...mockPayload,
        transition: {
          level: 'critical',
          changepointProb5d: 0.72,
          changepointProb20d: 0.88,
          mapRunLength: 2,
          expectedRunLength: 20,
          stabilityScore: 0.28,
          measured: true,
        },
      }

      const html = await renderComponent(PrimaryRegimeCard, {
        payload: highHazardPayload,
        symbol: 'SPY',
        spot: 520.5,
      })

      expect(html).toContain('hazard-alert-glow')
      expect(html).toContain('ELEVATED TRANSITION HAZARD (72%)')
    })

    it('renders honest unmeasured state when payload is null', async () => {
      const html = await renderComponent(PrimaryRegimeCard, {
        payload: null,
        symbol: 'SPY',
        spot: null,
      })

      expect(html).toContain('REGIME UNMEASURED')
      expect(html).toContain('—')
    })
  })

  describe('FourPillarContextGrid.vue', () => {
    it('renders all 4 pillars with measured metrics', async () => {
      const html = await renderComponent(FourPillarContextGrid, {
        payload: mockPayload,
      })

      expect(html).toContain('TREND &amp; PERSISTENCE')
      expect(html).toContain('+1.85σ')
      expect(html).toContain('VOLATILITY ENVIRONMENT')
      expect(html).toContain('45.0%')
      expect(html).toContain('MARKET STRUCTURE')
      expect(html).toContain('48.0 bars')
      expect(html).toContain('0.62')
      expect(html).toContain('ORDER FLOW &amp; GAMMA')
      expect(html).toContain('LONG Γ')
      expect(html).toContain('+$450.0M')
    })

    it('renders explicit unmeasured notices when lenses are unmeasured', async () => {
      const unmeasuredPayload: MarketRegimePayload = {
        ...mockPayload,
        trend: {
          state: 'unmeasured',
          slope: null,
          kalmanVelocity: null,
          kalmanZScore: null,
          trendPersistence: null,
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
      }

      const html = await renderComponent(FourPillarContextGrid, {
        payload: unmeasuredPayload,
      })

      expect(html).toContain('Price bar history insufficient to compute Kinematic Kalman filter.')
      expect(html).toContain('No active option chain. Flow &amp; dealer Greeks withheld.')
    })
  })

  describe('TransitionRiskGauge.vue', () => {
    it('renders arc gauge and stability metrics', async () => {
      const html = await renderComponent(TransitionRiskGauge, {
        transition: mockPayload.transition,
        measurable: true,
      })

      expect(html).toContain('12.0%')
      expect(html).toContain('LOW HAZARD')
      expect(html).toContain('88%')
      expect(html).toContain('18 bars')
      expect(html).toContain('35 bars')
    })

    it('renders unmeasured state when transition is null', async () => {
      const html = await renderComponent(TransitionRiskGauge, {
        transition: null,
        measurable: false,
      })

      expect(html).toContain('UNMEASURED')
      expect(html).toContain('—')
    })
  })

  describe('ModelAgreementMatrix.vue', () => {
    it('renders 5x5 matrix and consensus header', async () => {
      const html = await renderComponent(ModelAgreementMatrix, {
        agreement: mockPayload.agreement,
      })

      expect(html).toContain('MODEL CONSENSUS')
      expect(html).toContain('85%')
      expect(html).toContain('AGREE:')
      expect(html).toContain('Trend (Kalman)')
    })
  })

  describe('DynamicExplanationPanel.vue', () => {
    it('renders dynamic headline, summary, and drivers', async () => {
      const html = await renderComponent(DynamicExplanationPanel, {
        explanation: mockPayload.explanation,
        measurable: true,
      })

      expect(html).toContain('Bullish Kinematic Trend with Long Gamma Damping')
      expect(html).toContain('Kalman filter estimates positive velocity')
      expect(html).toContain('TOP ATTRIBUTED FEATURE DRIVERS')
      expect(html).toContain('Kalman velocity z-score +1.85σ')
      expect(html).toContain('ACTIVE RISK FACTORS')
      expect(html).toContain('Potential resistance at Call Wall $530')
    })
  })

  describe('MarketContextCard.vue Zero-Spoofing', () => {
    it('renders measured context when all inputs are supplied', async () => {
      const html = await renderComponent(MarketContextCard, {
        symbol: 'NVDA',
        spot: 120.5,
        vwap: 119.0,
        gammaFlip: 118.0,
        callWall: 125.0,
        putWall: 115.0,
        netFlowM: 45.2,
        ivRank: 72,
        kalmanVelocity: 0.15,
      })

      expect(html).toContain('MARKET CONTEXT')
      expect(html).toContain('NVDA is trading slightly above VWAP')
      expect(html).toContain('bullish intraday momentum')
      expect(html).toContain('Price &gt; VWAP')
      expect(html).toContain('Bullish Flow')
      expect(html).toContain('IV Elevated')
      expect(html).toContain('GEX + Above 118')
      expect(html).toContain('Negative Below 115')
    })

    it('renders unmeasured fallback without fake Price > VWAP or Bullish Flow', async () => {
      const html = await renderComponent(MarketContextCard, {
        symbol: 'SPY',
        spot: null,
        vwap: null,
        gammaFlip: null,
        callWall: null,
        putWall: null,
        netFlowM: null,
        ivRank: null,
        kalmanVelocity: null,
      })

      expect(html).toContain('SPY')
      expect(html).not.toContain('Price &gt; VWAP')
      expect(html).not.toContain('Price &lt; VWAP')
      expect(html).not.toContain('Bullish Flow')
      expect(html).not.toContain('Bearish Flow')
      expect(html).toContain('Context Unmeasured')
    })
  })

  describe('ForwardTrajectoryCard.vue Zero-Spoofing', () => {
    it('renders steps for long gamma regime', async () => {
      const html = await renderComponent(ForwardTrajectoryCard, {
        symbol: 'SPY',
        spot: 520.0,
        regime: 'long',
        gammaFlip: 510.0,
        callWall: 530.0,
        putWall: 500.0,
        pinStrike: 522.0,
      })

      expect(html).toContain('FORWARD POSITIVE RAMP')
      expect(html).toContain('$522')
      expect(html).toContain('(Pin Magnet)')
      expect(html).toContain('$530')
      expect(html).toContain('(Resistance Wall)')
      expect(html).toContain('$510')
      expect(html).toContain('(Lower Boundary)')
    })

    it('renders empty trajectory state when levels are completely null', async () => {
      const html = await renderComponent(ForwardTrajectoryCard, {
        symbol: 'UNMEASURED',
        spot: null,
        regime: null,
        gammaFlip: null,
        callWall: null,
        putWall: null,
        pinStrike: null,
      })

      expect(html).toContain('FORWARD REGIME TRAJECTORY')
      expect(html).toContain('Trajectory levels unmeasured')
      expect(html).not.toContain('$525')
      expect(html).not.toContain('$522')
    })
  })

  describe('PositioningSummaryCard.vue Zero-Spoofing', () => {
    it('renders measured positioning metrics with valid classes', async () => {
      const html = await renderComponent(PositioningSummaryCard, {
        regime: 'long',
        dealerBias: 'Aggressive Hedging',
        crowdPositioning: 'Bullish Demand',
        smartMoneyFlow: 'Bearish Distribution',
        netDeltaM: -45.2,
      })

      expect(html).toContain('Long Gamma')
      expect(html).toContain('Aggressive Hedging')
      expect(html).toContain('Bullish Demand')
      expect(html).toContain('Bearish Distribution')
      expect(html).toContain('-45.2M')
    })

    it('renders unmeasured DASH state for completely null inputs', async () => {
      const html = await renderComponent(PositioningSummaryCard, {})

      expect(html).toContain('Unmeasured')
      expect(html).toContain('—')
      expect(html).not.toContain('+87.4M')
      expect(html).not.toContain('Bullish')
    })
  })

  describe('InstantaneousHedgingCard.vue Zero-Spoofing', () => {
    it('renders measured hedging pressure and Greeks from snapshot', async () => {
      const snap: MicrostructureRegimeSnapshot = {
        symbol: 'SPY',
        spot: 510,
        asof: '2026-09-02T12:00:00Z',
        regime: 'positive_gamma',
        regime_strength: 0.8,
        net_gex_m: 200,
        call_gex_m: 300,
        put_gex_m: -100,
        net_gex_profile_m: 200,
        net_vex_m: 25.0,
        net_chex_m: 10,
        hedging_flow_m: 15.4,
        zero_dte_charm_drift_m: 5,
        gamma_flip: 505,
        call_wall: 520,
        put_wall: 495,
        volatility_trigger: 508,
        absolute_gamma_peak: 515,
        quality: {
          measurable: true,
          contracts: 500,
          strikes: 80,
          total_open_interest: 1_200_000,
          iv_fallback_contracts: 0,
          flip_located: true,
          dealer_convention: 'index',
          reason: null,
        },
        topography: {
          quadrant: 'forward_positive_ramp',
          title: 'Positive Ramp',
          description: 'Long gamma environment above flip.',
          dealer_hedging_action: 'Buy dips, sell rips',
          expected_market_behavior: 'Damped moves, mean-reversion tendency',
          gex_above_spot_m: 300,
          gex_below_spot_m: -100,
          gex_ratio: 3.0,
          call_wall: 520,
          put_wall: 495,
          gamma_flip: 505,
          volatility_trigger: 508,
          absolute_gamma_peak: 515,
        },
        strikes: [],
        gex_profile: [],
        notes: [],
      }

      const html = await renderComponent(InstantaneousHedgingCard, {
        snapshot: snap,
        spot: 510,
        netGammaM: 200,
      })

      expect(html).toContain('INSTANTANEOUS HEDGING')
      expect(html).toContain('+15.4M')
      expect(html).toContain('+75.0M')
      expect(html).toContain('+28.0M')
    })

    it('renders DASH when snapshot and inputs are null without fake numbers', async () => {
      const html = await renderComponent(InstantaneousHedgingCard, {
        snapshot: null,
        spot: null,
        netGammaM: null,
      })

      expect(html).toContain('INSTANTANEOUS HEDGING')
      expect(html).toContain('—')
      expect(html).not.toContain('-234.7M')
      expect(html).not.toContain('+161.5M')
      expect(html).not.toContain('+179.2M')
      expect(html).not.toContain('vs prev. 1h -18.2%')
    })
  })

  describe('KeyLevelsCard.vue Zero-Spoofing', () => {
    it('renders DASH for null levels without fabricating 525.16', async () => {
      const html = await renderComponent(KeyLevelsCard, {
        spot: null,
        maxPain: null,
        vwap: null,
        resistance: null,
        support: null,
      })

      expect(html).toContain('KEY LEVELS')
      expect(html).toContain('—')
      expect(html).not.toContain('525.16')
      expect(html).not.toContain('$525')
    })
  })

  describe('FlowSummaryDonutCard.vue Zero-Spoofing', () => {
    it('renders unmeasured state when flow premiums are null', async () => {
      const html = await renderComponent(FlowSummaryDonutCard, {
        totalPremiumM: null,
        bullishPremiumM: null,
        bearishPremiumM: null,
        netFlowM: null,
      })

      expect(html).toContain('FLOW SUMMARY (TODAY)')
      expect(html).toContain('—')
    })
  })
})
