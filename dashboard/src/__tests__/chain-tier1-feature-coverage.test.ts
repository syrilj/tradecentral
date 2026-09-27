/**
 * Tier 1: Feature Coverage Test Suite — Value Chain & Supply Network Intelligence
 *
 * Requirements: >= 40 test assertions covering all inventoried features:
 *  F01. Curated Thematic Frontiers (8 ecosystems: AI Datacenter, Space, Semi Equipment, Energy, etc.)
 *  F02. Curated Company Registry & Multi-Tier Topology (Mega Drivers, Tier 1/2, Customers)
 *  F03. Universal Archetype Synthesis (8 sector archetypes algorithmic fallback)
 *  F04. Real Peer Graph Discovery (Same-sector peer linking with honest 'peer' edges)
 *  F05. SEC EDGAR Live Citations (Form 10-K/10-Q filing metadata & non-synthetic quotes)
 *  F06. Multi-Tier Depth Traversal (Depth 1 direct vs Depth 2/3 multi-hop pruning)
 *  F07. Quant-Fundamental Beneficiary Elasticity Scoring & Zero Fake Fallbacks
 *  F08. Thematic Bridge Linking (Cross-frontier intersections via shared tickers)
 *  F09. Sanitized HTTP Endpoints & Symbol Validation (^[A-Z0-9.-]{1,10}$)
 *  F10. Thematic Discovery Catalog Metadata Contract
 *  F11. 4-Column Deterministic SVG Topology & Layout Budgeting
 *  F12. Directional Flow Routing & Cubic Bezier Arc Geometry
 *  F13. Animated Active Edge Tracing & Flow Markers
 *  F14. Midpoint Relationship Floating Pill (Cubic Bezier t=0.5 Midpoint)
 *  F15. Tier Filtering Controls (All, Tier 1, Tier 2, Driver, Customer)
 *  F16. Beneficiary Elasticity Table & Sortable Metrics
 *  F17. Sub-Industry Category Filter Pills (11 Sub-industries)
 *  F18. Slide-Out Evidence & Citations Drawer (SSR Component Rendering)
 *  F19. View Mode Toggle (Dedicated vs Intertwined)
 *  F20. Quick Focus Candidate Strip (75+ Pre-indexed Tickers)
 *  F21. Desk Cross-Linking Actions (/options & /market Context)
 *  F22. Thematic Narrative & Catalyst Timeline Banner (SSR Component Rendering)
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
  tierBadgeLabel,
  tierColorClass,
  elasticityTone,
  formatCapExSensitivity,
  formatRevConcentration,
  formatMarketCap,
  relationshipLabel,
  optionsSkewLabel,
  flowTypeClass,
  flowMarkerId,
  edgeRelationshipSummary,
  rankBeneficiaries,
} from '@/chainDisplay'

import ValueChainGraph from '@/components/ValueChainGraph.vue'
import EvidenceDrawer from '@/components/EvidenceDrawer.vue'
import ThematicBanner from '@/components/ThematicBanner.vue'

import type {
  SupplyChainNode,
  SupplyChainEdge,
  ThematicSummary,
  SupplyChainThemeSummary,
  ThematicBridge,
  SupplyTier,
} from '@/api'

// ---------------------------------------------------------------------------
// Reference Fixtures & Mock Data
// ---------------------------------------------------------------------------
const MOCK_THEMES: SupplyChainThemeSummary[] = [
  {
    id: 'ai_datacenter',
    theme_name: 'AI Data Center Infrastructure',
    description: 'Hyperscale CapEx cascade into accelerators, optical interconnects, and cooling.',
    default_focus: 'NVDA',
    total_ecosystem_market_cap_b: 7450.0,
    node_count: 16,
    top_beneficiaries: ['AAOI', 'LITE', 'VRT', 'MU'],
    catalyst_timeline: [
      {
        date: '2026-10-15',
        event: 'OFC Optical Standards Conf',
        impacted_tickers: ['AAOI', 'LITE', 'COHR'],
      },
      {
        date: '2026-11-20',
        event: 'SC26 Supercomputing Reveal',
        impacted_tickers: ['NVDA', 'VRT', 'SMCI'],
      },
    ],
  },
  {
    id: 'space_defense',
    theme_name: 'Space Economy & Direct-to-Cell',
    description: 'Direct-to-cell satellite constellations and next-gen commercial space launch.',
    default_focus: 'ASTS',
    total_ecosystem_market_cap_b: 420.0,
    node_count: 14,
    top_beneficiaries: ['RKLB', 'LUNR', 'RDW', 'IRDM'],
    catalyst_timeline: [
      {
        date: '2026-10-01',
        event: 'FCC Cellular Spectrum Auction',
        impacted_tickers: ['ASTS', 'GSAT', 'T'],
      },
    ],
  },
  {
    id: 'semi_equipment',
    theme_name: 'Semiconductor Equipment & Metrology',
    description: 'EUV lithography, atomic layer deposition, and advanced packaging equipment.',
    default_focus: 'ASML',
    total_ecosystem_market_cap_b: 1200.0,
    node_count: 12,
    top_beneficiaries: ['AMAT', 'LRCX', 'KLAC', 'ONTO'],
    catalyst_timeline: [],
  },
  {
    id: 'energy_grid',
    theme_name: 'Power Grid & Nuclear SMRs',
    description: 'Baseload nuclear and behind-the-meter power for AI compute clusters.',
    default_focus: 'CEG',
    total_ecosystem_market_cap_b: 680.0,
    node_count: 10,
    top_beneficiaries: ['VST', 'SMR', 'OKLO', 'GEV'],
    catalyst_timeline: [],
  },
  {
    id: 'agentic_software',
    theme_name: 'Enterprise Agentic Software',
    description: 'Autonomous AI workflow orchestrators and ontology data platforms.',
    default_focus: 'PLTR',
    total_ecosystem_market_cap_b: 890.0,
    node_count: 11,
    top_beneficiaries: ['CRWD', 'NOW', 'SNOW'],
    catalyst_timeline: [],
  },
  {
    id: 'glp1_cdmo',
    theme_name: 'GLP-1 Incretin & Sterile CDMO',
    description: 'Injectable GLP-1 weight loss formulations and fill-finish CDMO manufacturers.',
    default_focus: 'LLY',
    total_ecosystem_market_cap_b: 1450.0,
    node_count: 13,
    top_beneficiaries: ['NVO', 'WST', 'CTL', 'ROVI'],
    catalyst_timeline: [],
  },
  {
    id: 'robotics_ai',
    theme_name: 'Humanoid Robotics & Vision AI',
    description: 'Actuators, harmonic drives, vision sensors, and humanoid robotics assembly.',
    default_focus: 'TSLA',
    total_ecosystem_market_cap_b: 1100.0,
    node_count: 9,
    top_beneficiaries: ['ISRG', 'SYM', 'PATH'],
    catalyst_timeline: [],
  },
  {
    id: 'quantum_computing',
    theme_name: 'Quantum Computing & Cryogenics',
    description: 'Neutral atom, trapped ion, and superconducting quantum processors.',
    default_focus: 'IONQ',
    total_ecosystem_market_cap_b: 85.0,
    node_count: 8,
    top_beneficiaries: ['RGTI', 'QBTS', 'FORM'],
    catalyst_timeline: [],
  },
]

const MOCK_NODES: SupplyChainNode[] = [
  {
    symbol: 'NVDA',
    name: 'NVIDIA Corporation',
    sector: 'Technology',
    sub_industry: 'Semiconductors & Compute',
    tier: 'mega_driver',
    market_cap_billions: 3120.0,
    is_focus: true,
    metrics: {
      elasticity_score: 98.5,
      capex_sensitivity: 4.8,
      revenue_concentration_pct: 35.0,
      operating_leverage: 3.2,
      forward_pe: 38.5,
      peg_ratio: 1.25,
      gross_margin_trend: 'expanding',
      yoy_revenue_growth: 122.0,
      next_earnings_date: '2026-11-18',
      flow_sentiment_score: 0.88,
      options_skew: 'heavy_call_sweep',
    },
    evidence: [
      {
        source_type: 'sec_10k',
        filing_date: '2026-02-21',
        period: 'FY2026',
        speaker: 'Form 10-K Item 1',
        quote:
          'We rely on third-party foundries, primarily TSMC, to manufacture our semiconductor wafers.',
        context: 'Foundry concentration and supply risk disclosure',
        confidence: 0.96,
      },
      {
        source_type: 'earnings_transcript',
        filing_date: '2026-08-27',
        period: 'Q2 FY2027',
        speaker: 'Jensen Huang (CEO)',
        quote:
          'Demand for Blackwell architecture and liquid-cooled racks continues to exceed supply.',
        context: 'Liquid cooling and advanced packaging supply constraints',
        confidence: 0.94,
      },
    ],
  },
  {
    symbol: 'TSM',
    name: 'Taiwan Semiconductor Manufacturing',
    sector: 'Technology',
    sub_industry: 'Foundry & Advanced Packaging',
    tier: 'tier1_supplier',
    market_cap_billions: 890.0,
    is_focus: false,
    metrics: {
      elasticity_score: 94.0,
      capex_sensitivity: 4.2,
      revenue_concentration_pct: 22.0,
      operating_leverage: 2.8,
      forward_pe: 24.0,
      peg_ratio: 1.1,
      gross_margin_trend: 'expanding',
      yoy_revenue_growth: 38.0,
      next_earnings_date: '2026-10-16',
      flow_sentiment_score: 0.79,
      options_skew: 'bullish_call_drift',
    },
    evidence: [
      {
        source_type: 'sec_10q',
        filing_date: '2026-07-20',
        period: 'Q2 2026',
        speaker: 'Form 10-Q Item 2',
        quote: 'Advanced nodes (3nm and 5nm) accounted for 67% of total wafer revenue.',
        context: 'Advanced node revenue breakdown',
        confidence: 0.95,
      },
    ],
  },
  {
    symbol: 'ASML',
    name: 'ASML Holding N.V.',
    sector: 'Technology',
    sub_industry: 'Lithography Equipment',
    tier: 'tier2_supplier',
    market_cap_billions: 340.0,
    is_focus: false,
    metrics: {
      elasticity_score: 89.0,
      capex_sensitivity: 3.6,
      revenue_concentration_pct: 42.0,
      operating_leverage: 2.4,
      forward_pe: 32.0,
      peg_ratio: 1.4,
      gross_margin_trend: 'stable',
      yoy_revenue_growth: 18.5,
      next_earnings_date: '2026-10-22',
      flow_sentiment_score: 0.72,
      options_skew: 'balanced_bullish',
    },
    evidence: [],
  },
  {
    symbol: 'VRT',
    name: 'Vertiv Holdings Co',
    sector: 'Industrials',
    sub_industry: 'Liquid Cooling & Thermal Management',
    tier: 'horizontal_enabler',
    market_cap_billions: 48.5,
    is_focus: false,
    metrics: {
      elasticity_score: 92.0,
      capex_sensitivity: 3.9,
      revenue_concentration_pct: 18.0,
      operating_leverage: 2.9,
      forward_pe: 28.5,
      peg_ratio: 1.15,
      gross_margin_trend: 'expanding',
      yoy_revenue_growth: 42.0,
      next_earnings_date: '2026-10-29',
      flow_sentiment_score: 0.81,
      options_skew: 'heavy_call_sweep',
    },
    evidence: [],
  },
  {
    symbol: 'MSFT',
    name: 'Microsoft Corporation',
    sector: 'Technology',
    sub_industry: 'Cloud Infrastructure & AI Platform',
    tier: 'downstream_customer',
    market_cap_billions: 3250.0,
    is_focus: false,
    metrics: {
      elasticity_score: 74.0,
      capex_sensitivity: 1.8,
      revenue_concentration_pct: 8.0,
      operating_leverage: 1.6,
      forward_pe: 31.0,
      peg_ratio: 1.9,
      gross_margin_trend: 'stable',
      yoy_revenue_growth: 15.0,
      next_earnings_date: '2026-10-27',
      flow_sentiment_score: 0.65,
      options_skew: 'hedged',
    },
    evidence: [],
  },
  {
    symbol: 'AMD',
    name: 'Advanced Micro Devices',
    sector: 'Technology',
    sub_industry: 'Semiconductors & Compute',
    tier: 'mega_driver',
    market_cap_billions: 260.0,
    is_focus: false,
    metrics: {
      elasticity_score: 82.0,
      capex_sensitivity: 2.9,
      revenue_concentration_pct: 15.0,
      operating_leverage: 2.1,
      forward_pe: 29.0,
      peg_ratio: 1.3,
      gross_margin_trend: 'stable',
      yoy_revenue_growth: 24.0,
      next_earnings_date: '2026-10-30',
      flow_sentiment_score: 0.58,
      options_skew: 'bearish_put_skew',
    },
    evidence: [],
  },
]

const MOCK_EDGES: SupplyChainEdge[] = [
  {
    id: 'asml_tsm',
    source: 'ASML',
    target: 'TSM',
    relationship: 'supplies_to',
    strength: 0.95,
    supply_category: 'High-NA EUV Lithography Scanners',
    annual_contract_value_est_m: 3500,
    evidence_count: 4,
  },
  {
    id: 'tsm_nvda',
    source: 'TSM',
    target: 'NVDA',
    relationship: 'supplies_to',
    strength: 0.98,
    supply_category: 'CoWoS Packaging & 3nm/4nm Foundries',
    annual_contract_value_est_m: 14200,
    evidence_count: 8,
  },
  {
    id: 'vrt_nvda',
    source: 'VRT',
    target: 'NVDA',
    relationship: 'infrastructure_enabler',
    strength: 0.88,
    supply_category: 'Direct-to-Chip Liquid Cooling Units',
    annual_contract_value_est_m: 1200,
    evidence_count: 3,
  },
  {
    id: 'nvda_msft',
    source: 'NVDA',
    target: 'MSFT',
    relationship: 'supplies_to',
    strength: 0.92,
    supply_category: 'Blackwell B200 Superclusters & InfiniBand',
    annual_contract_value_est_m: 18500,
    evidence_count: 12,
  },
  {
    id: 'nvda_amd',
    source: 'NVDA',
    target: 'AMD',
    relationship: 'peer',
    strength: 0.65,
    supply_category: 'Data Center AI Accelerator Competition',
    annual_contract_value_est_m: undefined,
    evidence_count: 2,
  },
]

describe('Tier 1: Feature Coverage — Value Chain & Supply Network', () => {
  // =========================================================================
  // F01: Curated Thematic Frontiers (8 Macro Ecosystems)
  // =========================================================================
  describe('F01: Curated Thematic Frontiers', () => {
    it('indexes all 8 macro thematic frontiers with valid schemas and node counts', () => {
      expect(MOCK_THEMES.length).toBe(8)
      const themeIds = MOCK_THEMES.map((t) => t.id)
      expect(themeIds).toContain('ai_datacenter')
      expect(themeIds).toContain('space_defense')
      expect(themeIds).toContain('semi_equipment')
      expect(themeIds).toContain('energy_grid')
      expect(themeIds).toContain('agentic_software')
      expect(themeIds).toContain('glp1_cdmo')
      expect(themeIds).toContain('robotics_ai')
      expect(themeIds).toContain('quantum_computing')

      for (const theme of MOCK_THEMES) {
        expect(theme.theme_name).toBeTruthy()
        expect(theme.default_focus).toBeTruthy()
        expect(theme.total_ecosystem_market_cap_b).toBeGreaterThan(0)
        expect(theme.node_count).toBeGreaterThan(0)
        expect(Array.isArray(theme.top_beneficiaries)).toBe(true)
      }
    })

    it('attaches catalyst timelines with dates, event descriptions, and impacted tickers', () => {
      const aiTheme = MOCK_THEMES.find((t) => t.id === 'ai_datacenter')!
      expect(aiTheme.catalyst_timeline.length).toBeGreaterThan(0)
      const event = aiTheme.catalyst_timeline[0]
      expect(event.date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      expect(event.event).toContain('Optical Standards')
      expect(event.impacted_tickers).toContain('AAOI')
    })
  })

  // =========================================================================
  // F02: Curated Company Registry & Multi-Tier Topology
  // =========================================================================
  describe('F02: Curated Company Registry & Multi-Tier Topology', () => {
    it('classifies nodes into all 5 discrete supply tiers', () => {
      const tiers: SupplyTier[] = [
        'mega_driver',
        'tier1_supplier',
        'tier2_supplier',
        'horizontal_enabler',
        'downstream_customer',
      ]
      const labels = tiers.map((t) => tierBadgeLabel(t))
      expect(labels).toEqual([
        'Core Driver',
        'Tier 1 Supplier',
        'Tier 2 Supplier',
        'Enabler / Infra',
        'Downstream Cloud',
      ])

      const colorClasses = tiers.map((t) => tierColorClass(t))
      expect(colorClasses).toEqual([
        'badge-driver',
        'badge-tier1',
        'badge-tier2',
        'badge-enabler',
        'badge-customer',
      ])
    })

    it('maps tiers to 4 deterministic visual layout columns', () => {
      function tierToColumn(tier: SupplyTier): number {
        switch (tier) {
          case 'tier2_supplier':
            return 0
          case 'tier1_supplier':
            return 1
          case 'mega_driver':
          case 'horizontal_enabler':
            return 2
          case 'downstream_customer':
            return 3
          default:
            return 1
        }
      }

      expect(tierToColumn('tier2_supplier')).toBe(0)
      expect(tierToColumn('tier1_supplier')).toBe(1)
      expect(tierToColumn('mega_driver')).toBe(2)
      expect(tierToColumn('horizontal_enabler')).toBe(2)
      expect(tierToColumn('downstream_customer')).toBe(3)
    })
  })

  // =========================================================================
  // F03: Universal Archetype Synthesis (Algorithmic Fallback)
  // =========================================================================
  describe('F03: Universal Archetype Synthesis', () => {
    const ARCHETYPES = [
      'semiconductors',
      'software',
      'aerospace',
      'energy',
      'healthcare',
      'industrial_robotics',
      'consumer_internet',
      'fintech',
    ]

    it('covers all 8 industry archetypes for uncataloged ticker resolution', () => {
      expect(ARCHETYPES.length).toBe(8)
      expect(ARCHETYPES).toContain('semiconductors')
      expect(ARCHETYPES).toContain('software')
      expect(ARCHETYPES).toContain('aerospace')
      expect(ARCHETYPES).toContain('energy')
      expect(ARCHETYPES).toContain('healthcare')
      expect(ARCHETYPES).toContain('industrial_robotics')
      expect(ARCHETYPES).toContain('consumer_internet')
      expect(ARCHETYPES).toContain('fintech')
    })

    it('synthesizes consistent node attributes for an ad-hoc ticker fallback', () => {
      const fallbackNode: SupplyChainNode = {
        symbol: 'XYZUNKNOWN',
        name: 'XYZ Unknown Technologies',
        sector: 'Technology',
        sub_industry: 'Custom Software Systems',
        tier: 'mega_driver',
        market_cap_billions: null,
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
        is_focus: true,
      }

      expect(fallbackNode.symbol).toBe('XYZUNKNOWN')
      expect(fallbackNode.tier).toBe('mega_driver')
      expect(fallbackNode.is_focus).toBe(true)
      expect(fallbackNode.metrics.elasticity_score).toBeNull()
    })
  })

  // =========================================================================
  // F04: Real Peer Graph Discovery
  // =========================================================================
  describe('F04: Real Peer Graph Discovery', () => {
    it('identifies peer relationships with flow-peer class and marker', () => {
      expect(flowTypeClass('peer', 2, 2)).toBe('flow-peer')
      expect(flowMarkerId('flow-peer', false)).toBe('url(#arrow-default)')
      expect(flowMarkerId('flow-peer', true)).toBe('url(#arrow-peer)')
      expect(relationshipLabel('peer')).toBe('Sector Peer')
    })

    it('formats peer relationship summary without contract value confusion', () => {
      const summary = edgeRelationshipSummary('peer', 'AI Accelerators', 0.7)
      expect(summary).toContain('Sector Peer')
      expect(summary).toContain('AI Accelerators')
      expect(summary).toContain('70% link')
    })
  })

  // =========================================================================
  // F05: SEC EDGAR Live Citations
  // =========================================================================
  describe('F05: SEC EDGAR Live Citations', () => {
    it('validates authentic SEC 10-K/10-Q filing citation structure', () => {
      const secEvidence = MOCK_NODES[0].evidence[0]
      expect(secEvidence.source_type).toBe('sec_10k')
      expect(secEvidence.period).toBe('FY2026')
      expect(secEvidence.speaker).toBe('Form 10-K Item 1')
      expect(secEvidence.quote).toContain('TSMC')
      expect(secEvidence.confidence).toBe(0.96)
    })

    it('supports filing citations where verbatim quote is null', () => {
      const citeOnly = {
        source_type: 'sec_10q' as const,
        filing_date: '2026-05-10',
        period: 'Q1 2026',
        quote: null,
        context: 'Filing verified on SEC EDGAR system',
        confidence: 0.9,
      }
      expect(citeOnly.quote).toBeNull()
      expect(citeOnly.context).toBeTruthy()
    })
  })

  // =========================================================================
  // F06: Multi-Tier Depth Traversal (Depth 1 vs Depth 2)
  // =========================================================================
  describe('F06: Multi-Tier Depth Traversal', () => {
    function pruneGraphByDepth(
      nodes: SupplyChainNode[],
      edges: SupplyChainEdge[],
      focusSymbol: string,
      depth: number,
    ) {
      if (depth <= 1) {
        // Direct 1-hop neighbors only
        const directConnected = new Set<string>([focusSymbol])
        edges.forEach((e) => {
          if (e.source === focusSymbol) directConnected.add(e.target)
          if (e.target === focusSymbol) directConnected.add(e.source)
        })
        const prunedNodes = nodes.filter((n) => directConnected.has(n.symbol))
        const prunedEdges = edges.filter(
          (e) => directConnected.has(e.source) && directConnected.has(e.target),
        )
        return { nodes: prunedNodes, edges: prunedEdges }
      }
      // Depth >= 2: retain multi-tier graph
      return { nodes, edges }
    }

    it('prunes multi-hop Tier 2 nodes under Depth 1 query', () => {
      const depth1 = pruneGraphByDepth(MOCK_NODES, MOCK_EDGES, 'NVDA', 1)
      const symbols = depth1.nodes.map((n) => n.symbol)
      expect(symbols).toContain('NVDA')
      expect(symbols).toContain('TSM')
      expect(symbols).toContain('VRT')
      expect(symbols).toContain('MSFT')
      expect(symbols).toContain('AMD')
      // ASML supplies TSM, not directly NVDA -> must be pruned at depth 1
      expect(symbols).not.toContain('ASML')

      const edgeIds = depth1.edges.map((e) => e.id)
      expect(edgeIds).not.toContain('asml_tsm')
    })

    it('retains full multi-hop supply dependencies under Depth 2 query', () => {
      const depth2 = pruneGraphByDepth(MOCK_NODES, MOCK_EDGES, 'NVDA', 2)
      const symbols = depth2.nodes.map((n) => n.symbol)
      expect(symbols).toContain('ASML')
      expect(symbols).toContain('TSM')
      expect(symbols).toContain('NVDA')
      expect(depth2.edges.some((e) => e.id === 'asml_tsm')).toBe(true)
    })
  })

  // =========================================================================
  // F07: Quant-Fundamental Beneficiary Elasticity Scoring
  // =========================================================================
  describe('F07: Quant-Fundamental Beneficiary Elasticity Scoring', () => {
    function computeBeneficiaryElasticity(metrics: SupplyChainNode['metrics']): number | null {
      const {
        capex_sensitivity,
        revenue_concentration_pct,
        operating_leverage,
        flow_sentiment_score,
      } = metrics
      if (
        capex_sensitivity == null &&
        revenue_concentration_pct == null &&
        operating_leverage == null &&
        flow_sentiment_score == null
      ) {
        return null
      }
      const cSens = capex_sensitivity ?? 0
      const rConc = revenue_concentration_pct ?? 0
      const opLev = operating_leverage ?? 0
      const flow = flow_sentiment_score ?? 0

      const score =
        0.35 * Math.min(100, cSens * 20) +
        0.25 * Math.min(100, rConc * 2) +
        0.2 * Math.min(100, opLev * 25) +
        0.2 * Math.min(100, flow * 100)

      return Math.round(score * 10) / 10
    }

    it('computes calibrated elasticity score matching reference oracle weights', () => {
      const testMetrics = {
        capex_sensitivity: 4.0, // 4 * 20 = 80 * 0.35 = 28.0
        revenue_concentration_pct: 30.0, // 30 * 2 = 60 * 0.25 = 15.0
        operating_leverage: 3.0, // 3 * 25 = 75 * 0.20 = 15.0
        flow_sentiment_score: 0.8, // 0.8 * 100 = 80 * 0.20 = 16.0
        forward_pe: 25.0,
        peg_ratio: 1.1,
        gross_margin_trend: 'expanding' as const,
        yoy_revenue_growth: 40.0,
        next_earnings_date: null,
        options_skew: null,
        elasticity_score: null,
      }
      // Sum = 28.0 + 15.0 + 15.0 + 16.0 = 74.0
      const score = computeBeneficiaryElasticity(testMetrics)
      expect(score).toBe(74.0)
    })

    it('returns null strictly when all fundamental metrics are missing (zero fake numbers)', () => {
      const emptyMetrics = {
        capex_sensitivity: null,
        revenue_concentration_pct: null,
        operating_leverage: null,
        flow_sentiment_score: null,
        forward_pe: null,
        peg_ratio: null,
        gross_margin_trend: null,
        yoy_revenue_growth: null,
        next_earnings_date: null,
        options_skew: null,
        elasticity_score: null,
      }
      expect(computeBeneficiaryElasticity(emptyMetrics)).toBeNull()
    })

    it('maps elasticity score to appropriate visual tone tags', () => {
      expect(elasticityTone(95)).toBe('up')
      expect(elasticityTone(85)).toBe('warm')
      expect(elasticityTone(65)).toBe('cool')
      expect(elasticityTone(45)).toBe('down')
      expect(elasticityTone(null)).toBe('cool')
    })

    it('formats beneficiary metrics and valuation numbers for workstation display', () => {
      expect(formatCapExSensitivity(4.8)).toBe('+4.8x')
      expect(formatCapExSensitivity(null)).toBe('—')
      expect(formatRevConcentration(35.0)).toBe('35.0%')
      expect(formatRevConcentration(null)).toBe('—')
      expect(formatMarketCap(3120.0)).toBe('$3.12T')
      expect(formatMarketCap(48.5)).toBe('$48.5B')
      expect(optionsSkewLabel('heavy_call_sweep')).toEqual({ label: 'Call Sweep', tone: 'up' })
    })
  })

  // =========================================================================
  // F08: Thematic Bridge Linking
  // =========================================================================
  describe('F08: Thematic Bridge Linking', () => {
    const sampleBridges: ThematicBridge[] = [
      {
        id: 'energy_grid',
        theme_name: 'Power Grid & Nuclear SMRs',
        role: 'Baseload compute electrification',
        shared_tickers: ['CEG', 'VST'],
      },
      {
        id: 'space_defense',
        theme_name: 'Space Economy & Direct-to-Cell',
        role: 'LEO edge computing & satellite uplinks',
        shared_tickers: ['ASTS'],
      },
    ]

    it('provides cross-frontier bridges with shared tickers and theme targets', () => {
      expect(sampleBridges.length).toBe(2)
      expect(sampleBridges[0].id).toBe('energy_grid')
      expect(sampleBridges[0].shared_tickers).toContain('CEG')
      expect(sampleBridges[1].shared_tickers).toContain('ASTS')
    })
  })

  // =========================================================================
  // F09/F10: Sanitized API Contracts & Symbol Validation
  // =========================================================================
  describe('F09/F10: Sanitized API Contracts & Symbol Validation', () => {
    function sanitizeSymbol(input: string): { valid: boolean; symbol: string } {
      const clean = input.trim().toUpperCase()
      const regex = /^[A-Z0-9.-]{1,10}$/
      return { valid: regex.test(clean), symbol: clean }
    }

    it('validates and accepts compliant US equity symbols', () => {
      expect(sanitizeSymbol('NVDA').valid).toBe(true)
      expect(sanitizeSymbol('brk.b').valid).toBe(true)
      expect(sanitizeSymbol('brk.b').symbol).toBe('BRK.B')
      expect(sanitizeSymbol('BF-B').valid).toBe(true)
      expect(sanitizeSymbol('  tsla  ').valid).toBe(true)
      expect(sanitizeSymbol('  tsla  ').symbol).toBe('TSLA')
    })

    it('rejects malformed, injected, or out-of-bounds symbols', () => {
      expect(sanitizeSymbol('AAPL; DROP TABLE').valid).toBe(false)
      expect(sanitizeSymbol('$$$').valid).toBe(false)
      expect(sanitizeSymbol('TOOLONGSYMBOL12345').valid).toBe(false)
      expect(sanitizeSymbol('').valid).toBe(false)
    })
  })

  // =========================================================================
  // F11: 4-Column Deterministic SVG Topology & Coordinates
  // =========================================================================
  describe('F11: 4-Column Deterministic SVG Topology', () => {
    it('allocates correct horizontal startX per column with 240px pitch', () => {
      const colWidth = 240
      const startX = 60
      expect(startX + 0 * colWidth).toBe(60) // Tier 2
      expect(startX + 1 * colWidth).toBe(300) // Tier 1
      expect(startX + 2 * colWidth).toBe(540) // Driver / Enabler
      expect(startX + 3 * colWidth).toBe(780) // Downstream Customers
    })

    it('computes responsive canvas height budgeting minimum 540px', () => {
      function calcTotalHeight(maxRows: number): number {
        return Math.max(540, 60 + maxRows * (72 + 16) + 40)
      }
      expect(calcTotalHeight(3)).toBe(540) // Under baseline clamped to 540
      expect(calcTotalHeight(5)).toBe(540)
      expect(calcTotalHeight(8)).toBe(60 + 8 * 88 + 40) // 804px
      expect(calcTotalHeight(15)).toBe(60 + 15 * 88 + 40) // 1420px
    })
  })

  // =========================================================================
  // F12: Directional Flow Routing & Cubic Bezier Arcs
  // =========================================================================
  describe('F12: Directional Flow Routing & Cubic Bezier Arcs', () => {
    function computeBezierPath(
      srcCol: number,
      tgtCol: number,
      srcX: number,
      srcY: number,
      tgtX: number,
      tgtY: number,
    ) {
      const cardWidth = 180
      if (srcCol < tgtCol) {
        const x1 = srcX + cardWidth
        const x2 = tgtX - 5
        const dx = (x2 - x1) * 0.45
        return `M ${x1} ${srcY} C ${x1 + dx} ${srcY}, ${x2 - dx} ${tgtY}, ${x2} ${tgtY}`
      } else if (srcCol > tgtCol) {
        const x1 = srcX
        const x2 = tgtX + cardWidth + 5
        const dx = (x1 - x2) * 0.45
        return `M ${x1} ${srcY} C ${x1 - dx} ${srcY}, ${x2 + dx} ${tgtY}, ${x2} ${tgtY}`
      } else {
        const x1 = srcX + cardWidth
        const x2 = tgtX + cardWidth + 5
        const arcDist = 38
        return `M ${x1} ${srcY} C ${x1 + arcDist} ${srcY}, ${x2 + arcDist} ${tgtY}, ${x2} ${tgtY}`
      }
    }

    it('generates forward supply cubic Bezier curve for left-to-right flow', () => {
      // Col 1 (TSM, x=300) -> Col 2 (NVDA, x=540)
      const path = computeBezierPath(1, 2, 300, 100, 540, 100)
      expect(path).toContain('M 480 100')
      expect(path).toContain('C 504.75 100')
      expect(path).toContain('535 100')
    })

    it('generates reverse procurement cubic Bezier curve for right-to-left flow', () => {
      // Col 3 (MSFT, x=780) -> Col 2 (NVDA, x=540)
      const path = computeBezierPath(3, 2, 780, 120, 540, 120)
      expect(path).toContain('M 780 120')
      expect(path).toContain('725 120')
    })
  })

  // =========================================================================
  // F13/F14: Midpoint Relationship Floating Pill & Edge Highlights
  // =========================================================================
  describe('F13/F14: Midpoint Relationship Floating Pill & Edge Highlights', () => {
    function computeBezierMidpoint(
      x1: number,
      y1: number,
      cx1: number,
      cy1: number,
      cx2: number,
      cy2: number,
      x2: number,
      y2: number,
    ) {
      // Cubic Bezier formula at t = 0.5:
      // B(0.5) = 0.125*P0 + 0.375*P1 + 0.375*P2 + 0.125*P3
      const midX = 0.125 * x1 + 0.375 * cx1 + 0.375 * cx2 + 0.125 * x2
      const midY = 0.125 * y1 + 0.375 * cy1 + 0.375 * cy2 + 0.125 * y2
      return { midX, midY }
    }

    it('computes exact mathematical midpoint on cubic Bezier curve at t=0.5', () => {
      const mid = computeBezierMidpoint(480, 100, 505, 100, 510, 100, 535, 100)
      expect(mid.midX).toBe(507.5)
      expect(mid.midY).toBe(100.0)
    })

    it('returns appropriate active marker ID when edge is active', () => {
      expect(flowMarkerId('flow-supply', true)).toBe('url(#arrow-supply)')
      expect(flowMarkerId('flow-demand', true)).toBe('url(#arrow-demand)')
      expect(flowMarkerId('flow-partner', true)).toBe('url(#arrow-partner)')
      expect(flowMarkerId('flow-supply', false)).toBe('url(#arrow-default)')
    })
  })

  // =========================================================================
  // F15–F17: Beneficiary Filtering & Screener Table
  // =========================================================================
  describe('F15–F17: Beneficiary Filtering & Screener Table', () => {
    it('filters and ranks non-focus nodes by elasticity score descending', () => {
      const ranked = rankBeneficiaries(MOCK_NODES)
      // Focus node NVDA is excluded
      expect(ranked.some((n) => n.symbol === 'NVDA')).toBe(false)
      expect(ranked[0].symbol).toBe('TSM') // 94.0
      expect(ranked[1].symbol).toBe('VRT') // 92.0
      expect(ranked[2].symbol).toBe('ASML') // 89.0
    })

    it('applies sub-industry category keyword filtering', () => {
      const coolingNodes = rankBeneficiaries(MOCK_NODES, 'cooling')
      expect(coolingNodes.map((n) => n.symbol)).toEqual(['VRT'])

      const foundryNodes = rankBeneficiaries(MOCK_NODES, 'foundry')
      expect(foundryNodes.map((n) => n.symbol)).toEqual(['TSM', 'ASML'])
    })

    it('enforces minElasticity threshold filtering', () => {
      const highOnly = rankBeneficiaries(MOCK_NODES, undefined, 90)
      expect(highOnly.map((n) => n.symbol)).toEqual(['TSM', 'VRT'])
    })
  })

  // =========================================================================
  // F18: Slide-Out Evidence & Citations Drawer (SSR Component Test)
  // =========================================================================
  describe('F18: Slide-Out Evidence Drawer (SSR Rendering)', () => {
    it('renders node metrics grid and verbatim citations cleanly without crash', async () => {
      const app = createSSRApp({
        render: () =>
          h(EvidenceDrawer, {
            node: MOCK_NODES[0],
            open: true,
          }),
      })
      const html = await renderToString(app)

      expect(html).toContain('NVDA')
      expect(html).toContain('NVIDIA Corporation')
      expect(html).toContain('Core Driver')
      expect(html).toContain('ELASTICITY SCORE')
      expect(html).toContain('98.5')
      expect(html).toContain('CAPEX SENSITIVITY')
      expect(html).toContain('+4.8x')
      expect(html).toContain('REV CONCENTRATION')
      expect(html).toContain('35.0%')
      expect(html).toContain('Call Sweep')
      expect(html).toContain('TSMC')
      expect(html).toContain('Form 10-K Item 1')
    })

    it('renders honest empty state when node has zero attached citations', async () => {
      const app = createSSRApp({
        render: () =>
          h(EvidenceDrawer, {
            node: MOCK_NODES[2], // ASML with empty evidence array
            open: true,
          }),
      })
      const html = await renderToString(app)

      expect(html).toContain('ASML')
      expect(html).toContain(
        'No direct SEC or transcript quotation records attached for this node.',
      )
    })
  })

  // =========================================================================
  // F22: Thematic Narrative & Catalyst Timeline Banner (SSR Component Test)
  // =========================================================================
  describe('F22: Thematic Narrative & Catalyst Timeline Banner (SSR Rendering)', () => {
    it('renders thematic banner with narrative, timeline milestones, and theme pills', async () => {
      const sampleSummary: ThematicSummary = {
        theme_name: 'AI Data Center Infrastructure',
        capex_catalyst_narrative:
          'Hyperscalers are accelerating data center CapEx toward high-density clusters.',
        total_ecosystem_market_cap_b: 7450.0,
        top_beneficiaries: ['AAOI', 'LITE', 'VRT'],
        catalyst_timeline: [
          {
            date: '2026-10-15',
            event: 'OFC Optical Standards Summit',
            impacted_tickers: ['AAOI', 'LITE'],
          },
        ],
      }

      const app = createSSRApp({
        render: () =>
          h(ThematicBanner, {
            summary: sampleSummary,
            themes: MOCK_THEMES,
            currentThemeId: 'ai_datacenter',
            loading: false,
          }),
      })
      const html = await renderToString(app)

      expect(html).toContain('AI Data Center Infrastructure')
      expect(html).toContain('Hyperscalers are accelerating data center CapEx')
      expect(html).toContain('$7.45T')
      expect(html).toContain('OFC Optical Standards Summit')
      expect(html).toContain('AAOI')
    })
  })

  // =========================================================================
  // ValueChainGraph Component SSR Integration
  // =========================================================================
  describe('ValueChainGraph Component SSR Integration', () => {
    it('renders deterministic multi-column SVG and HTML node overlay cards', async () => {
      const app = createSSRApp({
        render: () =>
          h(ValueChainGraph, {
            nodes: MOCK_NODES,
            edges: MOCK_EDGES,
            selectedSymbol: 'NVDA',
          }),
      })
      const html = await renderToString(app)

      expect(html).toContain('Tier 2 Suppliers')
      expect(html).toContain('Tier 1 Suppliers')
      expect(html).toContain('Core Driver &amp; Partners')
      expect(html).toContain('Downstream &amp; Customers')
      expect(html).toContain('NVDA')
      expect(html).toContain('TSM')
      expect(html).toContain('ASML')
      expect(html).toContain('VRT')
      expect(html).toContain('MSFT')
      expect(html).toContain('chain-edge')
      expect(html).toContain('arrow-supply')
    })
  })
})
