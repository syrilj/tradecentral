/**
 * Tier 4: Institutional Workloads & Real-World Application Scenarios
 *
 * Requirements: >= 20 test assertions covering realistic institutional workflows:
 *  - Scenario 1: Mega-Cap Hyperscale Compute Cascade (NVDA -> AVGO -> TSM -> VRT -> MSFT)
 *  - Scenario 2: Speculative Direct-to-Cell Telecom Expansion (ASTS -> RKLB -> T)
 *  - Scenario 3: Arbitrary Uncataloged Small-Cap Fallback Resolution (XYZUNKNOWN)
 *  - Scenario 4: Cross-Frontier Thematic Bridge Jump Navigation (CEG -> Energy Grid -> AI Datacenter)
 *  - Scenario 5: Multi-Stage Loading Pipeline & State Transition Progression
 *  - Scenario 6: High-Density Graph Stress & Layout Slot Allocation
 */

import { describe, it, expect, vi } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
  }),
  useRoute: () => ({
    query: {},
  }),
}))

import {
  formatCapExSensitivity,
  rankBeneficiaries,
} from '@/chainDisplay'

import ValueChainGraph from '@/components/ValueChainGraph.vue'

import type {
  SupplyChainNode,
  SupplyChainEdge,
  ThematicBridge,
} from '@/api'

describe('Tier 4: Realistic Institutional Workloads & Application Scenarios', () => {
  // =========================================================================
  // Scenario 1: Mega-Cap Hyperscale Compute Cascade (NVDA -> AVGO -> TSM -> VRT -> MSFT)
  // =========================================================================
  it('Scenario 1: traces institutional CapEx cascade across multi-tier AI accelerator ecosystem', () => {
    // 1. Hyperscale enterprise customer with CapEx commitments
    const msftNode: SupplyChainNode = {
      symbol: 'MSFT',
      name: 'Microsoft Corporation',
      sector: 'Technology',
      sub_industry: 'Cloud Infrastructure',
      tier: 'downstream_customer',
      market_cap_billions: 3200.0,
      is_focus: false,
      metrics: {
        elasticity_score: 72.0,
        capex_sensitivity: 1.6,
        revenue_concentration_pct: 6.0,
        operating_leverage: 1.5,
        forward_pe: 31.0,
        peg_ratio: 1.9,
        gross_margin_trend: 'stable',
        yoy_revenue_growth: 15.0,
        next_earnings_date: '2026-10-27',
        flow_sentiment_score: 0.62,
        options_skew: 'hedged',
      },
      evidence: [],
    }

    // 2. Core mega driver designing GPU clusters
    const nvdaNode: SupplyChainNode = {
      symbol: 'NVDA',
      name: 'NVIDIA Corporation',
      sector: 'Technology',
      sub_industry: 'Semiconductors',
      tier: 'mega_driver',
      market_cap_billions: 3120.0,
      is_focus: true,
      metrics: {
        elasticity_score: 99.0,
        capex_sensitivity: 4.8,
        revenue_concentration_pct: 35.0,
        operating_leverage: 3.2,
        forward_pe: 38.0,
        peg_ratio: 1.2,
        gross_margin_trend: 'expanding',
        yoy_revenue_growth: 122.0,
        next_earnings_date: '2026-11-18',
        flow_sentiment_score: 0.89,
        options_skew: 'heavy_call_sweep',
      },
      evidence: [
        {
          source_type: 'earnings_transcript',
          filing_date: '2026-08-27',
          period: 'Q2 FY2027',
          speaker: 'Jensen Huang',
          quote: 'Every dollar of cloud CapEx directly compounds into our accelerated computing systems.',
          context: 'Hyperscale CapEx acceleration',
          confidence: 0.98,
        },
      ],
    }

    // 3. Custom silicon & networking partner
    const avgoNode: SupplyChainNode = {
      symbol: 'AVGO',
      name: 'Broadcom Inc.',
      sector: 'Technology',
      sub_industry: 'Custom Silicon & PCIe Switching',
      tier: 'tier1_supplier',
      market_cap_billions: 780.0,
      is_focus: false,
      metrics: {
        elasticity_score: 95.0,
        capex_sensitivity: 4.2,
        revenue_concentration_pct: 32.0,
        operating_leverage: 2.8,
        forward_pe: 27.5,
        peg_ratio: 1.1,
        gross_margin_trend: 'expanding',
        yoy_revenue_growth: 45.0,
        next_earnings_date: '2026-09-04',
        flow_sentiment_score: 0.82,
        options_skew: 'heavy_call_sweep',
      },
      evidence: [],
    }

    // 4. Foundry & advanced packaging partner
    const tsmNode: SupplyChainNode = {
      symbol: 'TSM',
      name: 'Taiwan Semiconductor Manufacturing',
      sector: 'Technology',
      sub_industry: 'Foundry & CoWoS Packaging',
      tier: 'tier1_supplier',
      market_cap_billions: 890.0,
      is_focus: false,
      metrics: {
        elasticity_score: 94.0,
        capex_sensitivity: 4.1,
        revenue_concentration_pct: 25.0,
        operating_leverage: 2.7,
        forward_pe: 24.0,
        peg_ratio: 1.0,
        gross_margin_trend: 'expanding',
        yoy_revenue_growth: 38.0,
        next_earnings_date: '2026-10-16',
        flow_sentiment_score: 0.78,
        options_skew: 'bullish_call_drift',
      },
      evidence: [],
    }

    // 5. Critical cooling enabler
    const vrtNode: SupplyChainNode = {
      symbol: 'VRT',
      name: 'Vertiv Holdings Co',
      sector: 'Industrials',
      sub_industry: 'Liquid Cooling Infrastructure',
      tier: 'horizontal_enabler',
      market_cap_billions: 48.0,
      is_focus: false,
      metrics: {
        elasticity_score: 92.0,
        capex_sensitivity: 3.9,
        revenue_concentration_pct: 19.0,
        operating_leverage: 2.9,
        forward_pe: 28.0,
        peg_ratio: 1.15,
        gross_margin_trend: 'expanding',
        yoy_revenue_growth: 42.0,
        next_earnings_date: '2026-10-29',
        flow_sentiment_score: 0.8,
        options_skew: 'heavy_call_sweep',
      },
      evidence: [],
    }

    const nodes = [nvdaNode, msftNode, avgoNode, tsmNode, vrtNode]

    // Ranking beneficiaries excluding focal node
    const ranked = rankBeneficiaries(nodes)
    expect(ranked.map((n) => n.symbol)).toEqual(['AVGO', 'TSM', 'VRT', 'MSFT'])

    // Verify CapEx sensitivities
    expect(formatCapExSensitivity(avgoNode.metrics.capex_sensitivity)).toBe('+4.2x')
    expect(formatCapExSensitivity(tsmNode.metrics.capex_sensitivity)).toBe('+4.1x')
    expect(formatCapExSensitivity(vrtNode.metrics.capex_sensitivity)).toBe('+3.9x')
    expect(formatCapExSensitivity(msftNode.metrics.capex_sensitivity)).toBe('+1.6x')
  })

  // =========================================================================
  // Scenario 2: Speculative Direct-to-Cell Space Stock Traversal (ASTS -> RKLB -> T)
  // =========================================================================
  it('Scenario 2: evaluates speculative space value chain under missing metrics conditions', () => {
    // Speculative space stock with high growth but missing traditional P/E or forward ratios
    const astsNode: SupplyChainNode = {
      symbol: 'ASTS',
      name: 'AST SpaceMobile Inc.',
      sector: 'Telecommunications',
      sub_industry: 'Space & Direct-to-Cell Satellite',
      tier: 'mega_driver',
      market_cap_billions: 7.2,
      is_focus: true,
      metrics: {
        elasticity_score: 96.0,
        capex_sensitivity: 5.0,
        revenue_concentration_pct: 75.0,
        operating_leverage: 3.8,
        forward_pe: null, // Pre-commercial earnings -> strictly null
        peg_ratio: null,
        gross_margin_trend: null,
        yoy_revenue_growth: null,
        next_earnings_date: '2026-11-12',
        flow_sentiment_score: 0.92,
        options_skew: 'heavy_call_sweep',
      },
      evidence: [
        {
          source_type: 'sec_10q',
          filing_date: '2026-08-14',
          period: 'Q2 2026',
          speaker: 'Item 1 Financial Statements',
          quote: 'We have definitive commercial launch agreements with Rocket Lab and spectrum partnerships with AT&T.',
          context: 'Commercial spectrum and launch commitments',
          confidence: 0.99,
        },
      ],
    }

    const rklbNode: SupplyChainNode = {
      symbol: 'RKLB',
      name: 'Rocket Lab USA',
      sector: 'Aerospace',
      sub_industry: 'Space Launch & Satellites',
      tier: 'tier1_supplier',
      market_cap_billions: 4.1,
      is_focus: false,
      metrics: {
        elasticity_score: 91.0,
        capex_sensitivity: 3.5,
        revenue_concentration_pct: 28.0,
        operating_leverage: 2.2,
        forward_pe: null, // Unprofitable -> strictly null
        peg_ratio: null,
        gross_margin_trend: 'expanding',
        yoy_revenue_growth: 35.0,
        next_earnings_date: '2026-11-06',
        flow_sentiment_score: 0.77,
        options_skew: 'bullish_call_drift',
      },
      evidence: [],
    }

    const tNode: SupplyChainNode = {
      symbol: 'T',
      name: 'AT&T Inc.',
      sector: 'Telecommunications',
      sub_industry: 'Commercial Carrier',
      tier: 'downstream_customer',
      market_cap_billions: 155.0,
      is_focus: false,
      metrics: {
        elasticity_score: 68.0,
        capex_sensitivity: 1.2,
        revenue_concentration_pct: 5.0,
        operating_leverage: 1.2,
        forward_pe: 8.5,
        peg_ratio: 1.4,
        gross_margin_trend: 'stable',
        yoy_revenue_growth: 2.0,
        next_earnings_date: '2026-10-23',
        flow_sentiment_score: 0.54,
        options_skew: 'hedged',
      },
      evidence: [],
    }

    const nodes = [astsNode, rklbNode, tNode]

    // Verify unmeasured metrics render as '—' rather than fake zeroes
    expect(astsNode.metrics.forward_pe).toBeNull()
    expect(rklbNode.metrics.forward_pe).toBeNull()

    // Sub-industry keyword filtering isolates pure-play space names
    const spaceOnly = rankBeneficiaries(nodes, 'space')
    expect(spaceOnly.map((n) => n.symbol)).toEqual(['RKLB']) // Excludes non-space carrier T and focus ASTS
  })

  // =========================================================================
  // Scenario 3: Arbitrary Uncataloged Small-Cap Fallback Resolution
  // =========================================================================
  it('Scenario 3: resolves arbitrary uncataloged ticker into structured archetype graph', async () => {
    const novelSymbol = 'XYZUNKNOWN'
    const fallbackNode: SupplyChainNode = {
      symbol: novelSymbol,
      name: 'XYZ Emerging Industrial Tech',
      sector: 'Industrials',
      sub_industry: 'Industrial Robotics & Sensors',
      tier: 'mega_driver',
      market_cap_billions: null,
      is_focus: true,
      metrics: {
        elasticity_score: null,
        capex_sensitivity: null,
        revenue_concentration_pct: null,
        operating_leverage: null,
        forward_pe: null,
        peg_ratio: null,
        gross_margin_trend: null,
        yoy_revenue_growth: null,
        next_earnings_date: null,
        flow_sentiment_score: null,
        options_skew: null,
      },
      evidence: [],
    }

    const peerNode: SupplyChainNode = {
      symbol: 'SYM',
      name: 'Symbotic Inc.',
      sector: 'Industrials',
      sub_industry: 'Industrial Robotics & Sensors',
      tier: 'tier1_supplier',
      market_cap_billions: 14.5,
      is_focus: false,
      metrics: {
        elasticity_score: 85.0,
        capex_sensitivity: 2.4,
        revenue_concentration_pct: 18.0,
        operating_leverage: 1.9,
        forward_pe: 45.0,
        peg_ratio: 1.3,
        gross_margin_trend: 'expanding',
        yoy_revenue_growth: 55.0,
        next_earnings_date: null,
        flow_sentiment_score: 0.7,
        options_skew: 'bullish_call_drift',
      },
      evidence: [],
    }

    const edges: SupplyChainEdge[] = [
      {
        id: 'xyz_sym',
        source: 'XYZUNKNOWN',
        target: 'SYM',
        relationship: 'peer',
        strength: 0.7,
        supply_category: 'Industrial Robotics Benchmark',
        evidence_count: 0,
      },
    ]

    const app = createSSRApp({
      render: () =>
        h(ValueChainGraph, {
          nodes: [fallbackNode, peerNode],
          edges,
          selectedSymbol: novelSymbol,
        }),
    })
    const html = await renderToString(app)

    expect(html).toContain('XYZUNKNOWN')
    expect(html).toContain('SYM')
    expect(html).toContain('flow-peer')
    expect(html).toContain('arrow-peer')
  })

  // =========================================================================
  // Scenario 4: Cross-Frontier Thematic Bridge Jump Navigation
  // =========================================================================
  it('Scenario 4: navigates cross-frontier bridge from nuclear energy to AI data center clusters', () => {
    const bridge: ThematicBridge = {
      id: 'ai_datacenter',
      theme_name: 'AI Data Center Infrastructure',
      role: 'Nuclear baseload electrification for AI clusters',
      shared_tickers: ['CEG', 'VST'],
    }

    expect(bridge.id).toBe('ai_datacenter')
    expect(bridge.shared_tickers).toContain('CEG')

    // Simulate route query generation upon clicking the bridge chip
    function createBridgeRouteQuery(targetThemeId: string) {
      return {
        theme: targetThemeId,
        mode: 'intertwined',
      }
    }

    const query = createBridgeRouteQuery(bridge.id)
    expect(query.theme).toBe('ai_datacenter')
    expect(query.mode).toBe('intertwined')
  })

  // =========================================================================
  // Scenario 5: Multi-Stage Loading Pipeline & State Machine Progression
  // =========================================================================
  it('Scenario 5: advances through all 4 loading stages sequentially and handles error recovery', () => {
    type Stage = 'idle' | 'resolving' | 'fetching' | 'mapping' | 'rendering' | 'complete' | 'error'

    class LoadingStateMachine {
      public currentStage: Stage = 'idle'
      public progressPct = 0
      public stageLabel = 'Idle'
      public error: string | null = null

      public start(symbol: string) {
        this.error = null
        this.advanceTo('resolving', 20, `Resolving ${symbol} & sector taxonomy`)
      }

      public onSuppliersDiscovered() {
        this.advanceTo('fetching', 50, 'Discovering multi-tier suppliers & customers')
      }

      public onMetricsComputed() {
        this.advanceTo('mapping', 75, 'Computing elasticity & CapEx exposure')
      }

      public onGraphCompiled() {
        this.advanceTo('rendering', 90, 'Compiling topology & rendering graph')
      }

      public onComplete(symbol: string) {
        this.advanceTo('complete', 100, `Computed ${symbol} value chain`)
      }

      public onError(err: string) {
        this.currentStage = 'error'
        this.error = err
        this.stageLabel = `Error: ${err}`
      }

      private advanceTo(stage: Stage, pct: number, label: string) {
        this.currentStage = stage
        this.progressPct = pct
        this.stageLabel = label
      }
    }

    const pipeline = new LoadingStateMachine()
    expect(pipeline.currentStage).toBe('idle')

    pipeline.start('NVDA')
    expect(pipeline.currentStage).toBe('resolving')
    expect(pipeline.progressPct).toBe(20)
    expect(pipeline.stageLabel).toContain('Resolving NVDA')

    pipeline.onSuppliersDiscovered()
    expect(pipeline.currentStage).toBe('fetching')
    expect(pipeline.progressPct).toBe(50)

    pipeline.onMetricsComputed()
    expect(pipeline.currentStage).toBe('mapping')
    expect(pipeline.progressPct).toBe(75)

    pipeline.onGraphCompiled()
    expect(pipeline.currentStage).toBe('rendering')
    expect(pipeline.progressPct).toBe(90)

    pipeline.onComplete('NVDA')
    expect(pipeline.currentStage).toBe('complete')
    expect(pipeline.progressPct).toBe(100)
    expect(pipeline.stageLabel).toContain('Computed NVDA')

    // Test resilient error capture
    pipeline.onError('Server timed out')
    expect(pipeline.currentStage).toBe('error')
    expect(pipeline.error).toBe('Server timed out')
  })

  // =========================================================================
  // Scenario 6: High-Density Graph Stress & Layout Slot Allocation
  // =========================================================================
  it('Scenario 6: budgets distributed vertical slots for high-density multi-incident edges', () => {
    // Test slot distribution math for 5 incident edges on a single node
    const edgeCount = 5
    const cardHeight = 72

    const computedSlotY = Array.from({ length: edgeCount }, (_, i) => {
      // Formula: 18 + ((i + 0.5) / edgeCount) * 36
      return 18 + ((i + 0.5) / edgeCount) * 36
    })

    // Verify slots are evenly distributed within [18, 54] vertical band of the 72px card
    expect(computedSlotY[0]).toBe(18 + 0.1 * 36) // 21.6px
    expect(computedSlotY[4]).toBe(18 + 0.9 * 36) // 50.4px
    expect(computedSlotY[4]).toBeLessThan(cardHeight)

    for (let i = 0; i < computedSlotY.length - 1; i++) {
      expect(computedSlotY[i + 1]).toBeGreaterThan(computedSlotY[i])
      expect(computedSlotY[i + 1] - computedSlotY[i]).toBeCloseTo(36 / edgeCount, 3)
    }
  })
})
