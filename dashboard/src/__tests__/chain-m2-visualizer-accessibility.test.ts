import { describe, it, expect } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { routerKey, type Router } from 'vue-router'
import ValueChainGraph from '@/components/ValueChainGraph.vue'
import EvidenceDrawer from '@/components/EvidenceDrawer.vue'
import type { SupplyChainEdge, SupplyChainNode } from '@/api'

interface DrawerProps {
  node?: SupplyChainNode | null
  open: boolean
  edges?: SupplyChainEdge[]
  focalNode?: SupplyChainNode | null
  incidentEdges?: SupplyChainEdge[]
}

function renderDrawer(props: DrawerProps) {
  const app = createSSRApp({
    render: () => h(EvidenceDrawer, props),
  })
  app.provide(routerKey, {
    push: () => Promise.resolve(),
    replace: () => Promise.resolve(),
    currentRoute: { value: { query: {} } },
  } as unknown as Router)
  return renderToString(app)
}

const MOCK_NODES: SupplyChainNode[] = [
  {
    symbol: 'NVDA',
    name: 'NVIDIA Corporation',
    sector: 'Semiconductors',
    sub_industry: 'Accelerated Compute & AI GPUs',
    tier: 'mega_driver',
    market_cap_billions: 3120.0,
    is_focus: true,
    metrics: {
      elasticity_score: 98.5,
      capex_sensitivity: 4.8,
      revenue_concentration_pct: 35.0,
      operating_leverage: 3.2,
      forward_pe: 28.5,
      peg_ratio: 1.15,
      gross_margin_trend: 'expanding',
      yoy_revenue_growth: 122.0,
      next_earnings_date: '2026-11-18',
      flow_sentiment_score: 0.92,
      options_skew: 'heavy_call_sweep',
    },
    evidence: [
      {
        source_type: 'sec_10k',
        filing_date: '2026-02-20',
        period: 'FY2026',
        speaker: 'Jensen Huang',
        quote: 'Demand for Blackwell architecture systems significantly outstrips current packaging capacity.',
        context: 'Supply chain constraints and packaging partner relationships.',
        confidence: 0.95,
      },
    ],
  },
  {
    symbol: 'TSM',
    name: 'Taiwan Semiconductor',
    sector: 'Semiconductors',
    sub_industry: 'Advanced Node Foundry & CoWoS',
    tier: 'tier1_supplier',
    market_cap_billions: 890.0,
    is_focus: false,
    metrics: {
      elasticity_score: 94.0,
      capex_sensitivity: 3.9,
      revenue_concentration_pct: 22.0,
      operating_leverage: 2.8,
      forward_pe: 22.4,
      peg_ratio: 1.05,
      gross_margin_trend: 'expanding',
      yoy_revenue_growth: 38.5,
      next_earnings_date: '2026-10-16',
      flow_sentiment_score: 0.85,
      options_skew: 'bullish_call_drift',
    },
    evidence: [],
  },
  {
    symbol: 'AAOI',
    name: 'Applied Optoelectronics',
    sector: 'Technology',
    sub_industry: '800G Optical Transceivers',
    tier: 'tier1_supplier',
    market_cap_billions: 1.85,
    is_focus: false,
    metrics: {
      elasticity_score: 96.0,
      capex_sensitivity: 5.2,
      revenue_concentration_pct: 42.0,
      operating_leverage: 3.5,
      forward_pe: 31.0,
      peg_ratio: 1.3,
      gross_margin_trend: 'expanding',
      yoy_revenue_growth: 65.0,
      next_earnings_date: '2026-11-05',
      flow_sentiment_score: 0.88,
      options_skew: 'heavy_call_sweep',
    },
    evidence: [],
  },
  {
    symbol: 'MSFT',
    name: 'Microsoft Corporation',
    sector: 'Software & Cloud',
    sub_industry: 'Hyperscale Cloud Infrastructure',
    tier: 'downstream_customer',
    market_cap_billions: 3200.0,
    is_focus: false,
    metrics: {
      elasticity_score: 74.0,
      capex_sensitivity: 2.1,
      revenue_concentration_pct: 12.0,
      operating_leverage: 2.1,
      forward_pe: 30.2,
      peg_ratio: 1.8,
      gross_margin_trend: 'stable',
      yoy_revenue_growth: 16.0,
      next_earnings_date: '2026-10-24',
      flow_sentiment_score: 0.76,
      options_skew: 'balanced_bullish',
    },
    evidence: [],
  },
  {
    symbol: 'AMZN',
    name: 'Amazon.com Inc.',
    sector: 'Consumer & Cloud',
    sub_industry: 'Hyperscale Cloud & AWS',
    tier: 'downstream_customer',
    market_cap_billions: 2100.0,
    is_focus: false,
    metrics: {
      elasticity_score: 72.0,
      capex_sensitivity: 2.3,
      revenue_concentration_pct: 14.0,
      operating_leverage: 2.2,
      forward_pe: 33.0,
      peg_ratio: 1.9,
      gross_margin_trend: 'expanding',
      yoy_revenue_growth: 13.5,
      next_earnings_date: '2026-10-30',
      flow_sentiment_score: 0.72,
      options_skew: 'hedged',
    },
    evidence: [],
  },
]

const MOCK_EDGES: SupplyChainEdge[] = [
  {
    id: 'edge_tsm_nvda',
    source: 'TSM',
    target: 'NVDA',
    relationship: 'supplies_to',
    strength: 0.98,
    supply_category: 'CoWoS-L Advanced Packaging & 4NP Wafers',
    annual_contract_value_est_m: 8500,
    evidence_count: 5,
  },
  {
    id: 'edge_aaoi_nvda',
    source: 'AAOI',
    target: 'NVDA',
    relationship: 'supplies_to',
    strength: 0.88,
    supply_category: '800G OSFP Transceiver Modules',
    annual_contract_value_est_m: 320,
    evidence_count: 2,
  },
  {
    id: 'edge_nvda_msft',
    source: 'NVDA',
    target: 'MSFT',
    relationship: 'purchases_from',
    strength: 0.94,
    supply_category: 'Blackwell GPU Superclusters & NVLink Switches',
    annual_contract_value_est_m: 14200,
    evidence_count: 4,
  },
  // Column 3 same-column peer edge (downstream customer to downstream customer)
  {
    id: 'edge_msft_amzn_peer',
    source: 'MSFT',
    target: 'AMZN',
    relationship: 'peer',
    strength: 0.82,
    supply_category: 'Hyperscale Cloud AI Infrastructure Competitor',
    annual_contract_value_est_m: undefined,
    evidence_count: 1,
  },
]

describe('Milestone 2: Graph Visualizer Geometry & WCAG AA Accessibility', () => {
  describe('ValueChainGraph Accessibility (GAP-04)', () => {
    it('renders node cards with full keyboard operability attributes', async () => {
      const app = createSSRApp({
        render: () =>
          h(ValueChainGraph, {
            nodes: MOCK_NODES,
            edges: MOCK_EDGES,
            selectedSymbol: 'NVDA',
          }),
      })
      const html = await renderToString(app)

      // Node cards must have tabindex="0"
      expect(html).toContain('tabindex="0"')

      // Node cards must have role="button"
      expect(html).toContain('role="button"')

      // Node cards must have descriptive aria-label
      expect(html).toContain('aria-label="Select NVDA - NVIDIA Corporation"')
      expect(html).toContain('aria-label="Select TSM - Taiwan Semiconductor"')
      expect(html).toContain('aria-label="Select AAOI - Applied Optoelectronics"')
      expect(html).toContain('aria-label="Select MSFT - Microsoft Corporation"')

      // Selected node card must reflect aria-pressed state
      expect(html).toContain('aria-pressed="true"')
      expect(html).toContain('aria-pressed="false"')
      expect(html).toContain('selected')

      // Focus tag button must have accessible name
      expect(html).toContain('aria-label="Focus value chain on TSM"')
      expect(html).toContain('aria-label="Focus value chain on AAOI"')
    })

    it('contains high-contrast :focus-visible rules conforming to WCAG 2.4.7 in component style', async () => {
      const fs = await import('node:fs')
      const path = await import('node:path')
      const graphCode = fs.readFileSync(
        path.join(process.cwd(), 'src/components/ValueChainGraph.vue'),
        'utf-8',
      )

      expect(graphCode).toContain('.node-card:focus-visible')
      expect(graphCode).toContain('.tier-filter-btn:focus-visible')
      expect(graphCode).toContain('.node-focus-tag:focus-visible')
      expect(graphCode).toContain('outline-offset')
    })
  })

  describe('ValueChainGraph Column 3 Lateral Arc Geometry (GAP-05)', () => {
    it('uses a 1080px viewport and prevents Column 3 lateral arcs from clipping', async () => {
      const app = createSSRApp({
        render: () =>
          h(ValueChainGraph, {
            nodes: MOCK_NODES,
            edges: MOCK_EDGES,
            selectedSymbol: 'MSFT',
          }),
      })
      const html = await renderToString(app)

      // Verify viewBox width is 1080
      expect(html).toContain('viewBox="0 0 1080')
      expect(html).toMatch(/width:\s*1080px/)

      // Verify SVG paths exist and same-column peer arc in Col 3 (MSFT to AMZN) does not exceed 1080
      // MSFT and AMZN are both in Column 3 (x = 780, card right edge = 960)
      // The lateral arc path should start at x=960 and have control points well below 1080
      const pathTags = [...html.matchAll(/<path[^>]*\bd="([^"]+)"[^>]*>/g)]
      expect(pathTags.length).toBeGreaterThan(0)

      for (const match of pathTags) {
        const d = match[1]
        // Extract all numeric tokens from path
        const numbers = d.match(/-?\d+(\.\d+)?/g)?.map(Number) ?? []
        // None of the coordinates should exceed 1080 (the SVG viewBox width)
        const xCoords = numbers.filter((_, idx) => idx % 2 === 0)
        for (const x of xCoords) {
          expect(x).toBeLessThanOrEqual(1060)
        }
      }
    })
  })

  describe('EvidenceDrawer Dialog Semantics & Dismissal', () => {
    it('renders accessible dialog semantics, backdrop scrim, and close button label', async () => {
      const html = await renderDrawer({
        node: MOCK_NODES[0],
        open: true,
        edges: MOCK_EDGES,
      })

      // Dialog semantics
      expect(html).toContain('role="dialog"')
      expect(html).toContain('aria-modal="true"')
      expect(html).toContain('aria-label="Entity Evidence and Supply Chain Details: NVDA - NVIDIA Corporation"')

      // Backdrop scrim for dismissal
      expect(html).toContain('data-test="drawer-backdrop"')
      expect(html).toContain('class="drawer-backdrop"')

      // Accessible close button
      expect(html).toContain('aria-label="Close drawer"')
      expect(html).toContain('title="Close drawer"')
    })

    it('has focus-visible and escape key listeners in EvidenceDrawer code', async () => {
      const fs = await import('node:fs')
      const path = await import('node:path')
      const drawerCode = fs.readFileSync(
        path.join(process.cwd(), 'src/components/EvidenceDrawer.vue'),
        'utf-8',
      )

      expect(drawerCode).toContain('@keydown.esc')
      expect(drawerCode).toContain('.close-btn:focus-visible')
      expect(drawerCode).toContain('.desk-btn:focus-visible')
      expect(drawerCode).toContain('onGlobalKeydown')
    })
  })

  describe('EvidenceDrawer Relationship Rationale & Contract Context Section', () => {
    it('renders prominent relationship rationale with direct connection, contract value, and strength meter', async () => {
      // Testing with AAOI which has incident edge edge_aaoi_nvda
      const aaoiNode = MOCK_NODES.find((n) => n.symbol === 'AAOI')!
      const html = await renderDrawer({
        node: aaoiNode,
        open: true,
        edges: MOCK_EDGES,
      })

      // Section header
      expect(html).toContain('RELATIONSHIP RATIONALE &amp; CONTRACT CONTEXT')

      // Direct connection pair
      expect(html).toContain('AAOI ➔ NVDA')

      // Relationship label
      expect(html).toContain('Supplies to')

      // Supply category
      expect(html).toContain('800G OSFP Transceiver Modules')

      // Estimated annual contract value
      expect(html).toContain('$320M / yr')

      // Link strength
      expect(html).toContain('88%')
      expect(html).toContain('strength-high')

      // Narrative callout
      expect(html).toContain('critical partner that supplies to NVDA')
      expect(html).toContain('88% dependency link')
      expect(html).toContain('Estimated annual procurement / contract value is ~$320M')
    })

    it('renders focal entity ecosystem anchor fallback narrative when selected node is the core driver', async () => {
      const nvdaNode = MOCK_NODES.find((n) => n.symbol === 'NVDA')!
      const html = await renderDrawer({
        node: nvdaNode,
        open: true,
        // Pass empty edges to test anchor fallback
        edges: [],
      })

      expect(html).toContain('RELATIONSHIP RATIONALE &amp; CONTRACT CONTEXT')
      expect(html).toContain('CORE ECOSYSTEM ANCHOR')
      expect(html).toContain('central anchor entity for this value chain')
      expect(html).toContain('Capital expenditures, architectural roadmap decisions')
    })

    it('renders explicit dashes for missing contract values without fake zeros', async () => {
      const msftNode = MOCK_NODES.find((n) => n.symbol === 'MSFT')!
      const html = await renderDrawer({
        node: msftNode,
        open: true,
        // Peer edge has no annual contract value
        edges: [MOCK_EDGES[3]],
      })

      expect(html).toContain('MSFT ➔ AMZN')
      expect(html).toContain('Sector Peer')
      // Missing contract value must be an explicit dash
      expect(html).toContain('—')
    })
  })
})
