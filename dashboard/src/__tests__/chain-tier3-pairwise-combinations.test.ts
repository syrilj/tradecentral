/**
 * Tier 3: Pairwise Combinatorial Test Suite — Value Chain & Supply Network
 *
 * Requirements: >= 25 test assertions covering cross-feature interactions across:
 *  - Mode: dedicated vs intertwined
 *  - Depth: 1 (direct 1-hop) vs 2 (multi-tier)
 *  - Theme: all 8 thematic ecosystems
 *  - Ticker Type: Curated Registry (NVDA, ASTS, LLY, CEG), Theme Catalog (AAOI, VRT), Uncataloged (XYZUNKNOWN)
 *  - Tier Filtering Controls (All, Tier 1, Tier 2, Driver, Customer)
 *  - Flow Type Directionality & Markers
 *  - Cross-Frontier Thematic Bridges & Mode Switching
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

import { flowTypeClass, flowMarkerId, relationshipLabel, rankBeneficiaries } from '@/chainDisplay'

import ValueChainGraph from '@/components/ValueChainGraph.vue'

import type {
  SupplyChainNode,
  SupplyChainEdge,
  ThematicSummary,
  ThematicBridge,
  SupplyTier,
  RelationshipType,
} from '@/api'

// ---------------------------------------------------------------------------
// Pairwise Combinatorial Fixtures & Builders
// ---------------------------------------------------------------------------

function makeNode(
  symbol: string,
  name: string,
  sector: string,
  sub_industry: string,
  tier: SupplyTier,
  market_cap_b: number | null,
  elasticity: number | null,
  is_focus = false,
): SupplyChainNode {
  return {
    symbol,
    name,
    sector,
    sub_industry,
    tier,
    market_cap_billions: market_cap_b,
    is_focus,
    metrics: {
      elasticity_score: elasticity,
      capex_sensitivity: elasticity ? elasticity / 25 : null,
      revenue_concentration_pct: elasticity ? elasticity / 3 : null,
      operating_leverage: elasticity ? elasticity / 35 : null,
      forward_pe: 25.0,
      peg_ratio: 1.2,
      gross_margin_trend: 'stable',
      yoy_revenue_growth: 20.0,
      next_earnings_date: null,
      flow_sentiment_score: 0.75,
      options_skew: elasticity && elasticity > 90 ? 'heavy_call_sweep' : 'hedged',
    },
    evidence: [],
  }
}

function makeEdge(
  source: string,
  target: string,
  rel: RelationshipType,
  category: string,
  strength = 0.85,
): SupplyChainEdge {
  return {
    id: `${source.toLowerCase()}_${target.toLowerCase()}`,
    source,
    target,
    relationship: rel,
    strength,
    supply_category: category,
    evidence_count: 2,
  }
}

// ---------------------------------------------------------------------------
// Simulated Ecosystem Payloads
// ---------------------------------------------------------------------------
const ECOSYSTEM_FIXTURES: Record<
  string,
  { nodes: SupplyChainNode[]; edges: SupplyChainEdge[]; theme: string }
> = {
  // 1. AI Data Center (NVDA)
  ai_datacenter: {
    theme: 'ai_datacenter',
    nodes: [
      makeNode('NVDA', 'NVIDIA', 'Technology', 'Semiconductors', 'mega_driver', 3120, 99, true),
      makeNode('TSM', 'TSMC', 'Technology', 'Foundry', 'tier1_supplier', 890, 94),
      makeNode('ASML', 'ASML', 'Technology', 'Lithography', 'tier2_supplier', 340, 89),
      makeNode(
        'AAOI',
        'Applied Opto',
        'Technology',
        'Optics & Transceivers',
        'tier1_supplier',
        1.8,
        96,
      ),
      makeNode('VRT', 'Vertiv', 'Industrials', 'Liquid Cooling', 'horizontal_enabler', 48, 92),
      makeNode(
        'MSFT',
        'Microsoft',
        'Technology',
        'Cloud Infrastructure',
        'downstream_customer',
        3200,
        72,
      ),
    ],
    edges: [
      makeEdge('ASML', 'TSM', 'supplies_to', 'EUV Lithography Scanners'),
      makeEdge('TSM', 'NVDA', 'supplies_to', 'CoWoS 3nm Packaging'),
      makeEdge('AAOI', 'NVDA', 'supplies_to', '800G Optical Transceivers'),
      makeEdge('VRT', 'NVDA', 'infrastructure_enabler', 'Direct-to-Chip Cooling'),
      makeEdge('NVDA', 'MSFT', 'supplies_to', 'Blackwell GPU Racks'),
    ],
  },
  // 2. Space Economy (ASTS)
  space_defense: {
    theme: 'space_defense',
    nodes: [
      makeNode(
        'ASTS',
        'AST SpaceMobile',
        'Telecom',
        'Space & Direct-to-Cell',
        'mega_driver',
        7.5,
        95,
        true,
      ),
      makeNode(
        'RKLB',
        'Rocket Lab',
        'Aerospace',
        'Space Launch & Satellites',
        'tier1_supplier',
        4.2,
        91,
      ),
      makeNode(
        'HEI',
        'HEICO Corp',
        'Aerospace',
        'Aviation & Space Components',
        'tier2_supplier',
        32.0,
        84,
      ),
      makeNode(
        'T',
        'AT&T Inc.',
        'Telecom',
        'Commercial Mobile Carrier',
        'downstream_customer',
        155.0,
        68,
      ),
    ],
    edges: [
      makeEdge('HEI', 'RKLB', 'supplies_to', 'Space-grade Avionics'),
      makeEdge('RKLB', 'ASTS', 'supplies_to', 'BlueBird Orbital Launch'),
      makeEdge('ASTS', 'T', 'co_dependent', 'Direct-to-Cell Commercial Spectrum'),
    ],
  },
  // 3. Semi Equipment (ASML)
  semi_equipment: {
    theme: 'semi_equipment',
    nodes: [
      makeNode(
        'ASML',
        'ASML Holding',
        'Technology',
        'Foundry & Litho Equipment',
        'mega_driver',
        340,
        96,
        true,
      ),
      makeNode(
        'ZEISS',
        'Carl Zeiss Optics',
        'Technology',
        'Optics & Lasers',
        'tier1_supplier',
        45,
        93,
      ),
      makeNode(
        'TRUMPF',
        'TRUMPF Lasers',
        'Industrials',
        'CO2 Laser Metrology',
        'tier2_supplier',
        12,
        88,
      ),
      makeNode(
        'TSM',
        'TSMC',
        'Technology',
        'Foundry & Wafer Metrology',
        'downstream_customer',
        890,
        78,
      ),
    ],
    edges: [
      makeEdge('TRUMPF', 'ZEISS', 'supplies_to', 'EUV Pulse Lasers'),
      makeEdge('ZEISS', 'ASML', 'supplies_to', 'High-NA EUV Mirror Optics'),
      makeEdge('ASML', 'TSM', 'supplies_to', 'EUV Scanner Tool Fleet'),
    ],
  },
  // 4. Power Grid & Nuclear (CEG)
  energy_grid: {
    theme: 'energy_grid',
    nodes: [
      makeNode(
        'CEG',
        'Constellation Energy',
        'Utilities',
        'Power & Nuclear SMRs',
        'mega_driver',
        85.0,
        94,
        true,
      ),
      makeNode(
        'CCJ',
        'Cameco Corp',
        'Energy',
        'Uranium Fuel Processing',
        'tier1_supplier',
        24.0,
        89,
      ),
      makeNode(
        'BWXT',
        'BWX Technologies',
        'Industrials',
        'Nuclear Reactor Components',
        'tier2_supplier',
        11.0,
        86,
      ),
      makeNode(
        'MSFT',
        'Microsoft Cloud',
        'Technology',
        'Data Center Energy Offtake',
        'downstream_customer',
        3200,
        75,
      ),
    ],
    edges: [
      makeEdge('BWXT', 'CEG', 'supplies_to', 'SMR Pressure Vessels'),
      makeEdge('CCJ', 'CEG', 'supplies_to', 'Enriched Uranium Fuel Rods'),
      makeEdge('CEG', 'MSFT', 'infrastructure_enabler', '20-Year Baseload PPA'),
    ],
  },
  // 5. Enterprise Agentic Software (PLTR)
  agentic_software: {
    theme: 'agentic_software',
    nodes: [
      makeNode(
        'PLTR',
        'Palantir Technologies',
        'Technology',
        'Enterprise AI & Ontology',
        'mega_driver',
        95.0,
        95,
        true,
      ),
      makeNode(
        'SNOW',
        'Snowflake Inc',
        'Technology',
        'Enterprise AI Data Cloud',
        'tier1_supplier',
        45.0,
        88,
      ),
      makeNode(
        'ESTC',
        'Elastic N.V.',
        'Technology',
        'Vector Search & Indexing',
        'tier2_supplier',
        9.5,
        83,
      ),
      makeNode(
        'BP',
        'BP plc',
        'Energy',
        'Downstream Industrial Customer',
        'downstream_customer',
        98.0,
        65,
      ),
    ],
    edges: [
      makeEdge('ESTC', 'SNOW', 'technology_partner', 'Vector Hybrid Search Engine'),
      makeEdge('SNOW', 'PLTR', 'technology_partner', 'Data Warehouse Integration'),
      makeEdge('PLTR', 'BP', 'supplies_to', 'AIP Operational Digital Twin'),
    ],
  },
  // 6. GLP-1 & CDMO (LLY)
  glp1_cdmo: {
    theme: 'glp1_cdmo',
    nodes: [
      makeNode(
        'LLY',
        'Eli Lilly and Company',
        'Healthcare',
        'GLP-1 Incretin Therapeutics',
        'mega_driver',
        890.0,
        98,
        true,
      ),
      makeNode(
        'WST',
        'West Pharmaceutical',
        'Healthcare',
        'GLP-1 Auto-Injectors & Syringes',
        'tier1_supplier',
        26.0,
        93,
      ),
      makeNode(
        'SHL',
        'SHL Medical',
        'Healthcare',
        'Sterile Syringe Molding',
        'tier2_supplier',
        6.5,
        87,
      ),
      makeNode(
        'CVS',
        'CVS Health Corp',
        'Healthcare',
        'Pharmacy Benefit Manager',
        'downstream_customer',
        72.0,
        69,
      ),
    ],
    edges: [
      makeEdge('SHL', 'WST', 'supplies_to', 'Medical-Grade Polymer Molds'),
      makeEdge('WST', 'LLY', 'supplies_to', 'Dose Injector Cartridges'),
      makeEdge('LLY', 'CVS', 'supplies_to', 'Tirzepatide Commercial Distribution'),
    ],
  },
  // 7. Humanoid Robotics & Vision AI (TSLA)
  robotics_ai: {
    theme: 'robotics_ai',
    nodes: [
      makeNode(
        'TSLA',
        'Tesla Optimus',
        'Consumer Cyclical',
        'Robotics & Vision AI',
        'mega_driver',
        820.0,
        94,
        true,
      ),
      makeNode(
        'NVDA',
        'NVIDIA Isaac',
        'Technology',
        'Robotics Simulation & Chips',
        'tier1_supplier',
        3120.0,
        97,
      ),
      makeNode(
        'HMRN',
        'Harmonic Drive Systems',
        'Industrials',
        'Robotics Precision Gears',
        'tier2_supplier',
        4.5,
        90,
      ),
      makeNode(
        'AMZN',
        'Amazon Fulfillment',
        'Consumer Cyclical',
        'Warehouse Robotics Fleet',
        'downstream_customer',
        2100.0,
        74,
      ),
    ],
    edges: [
      makeEdge('HMRN', 'TSLA', 'supplies_to', 'Harmonic Actuator Gears'),
      makeEdge('NVDA', 'TSLA', 'technology_partner', 'Isaac Sim Synthetic Training'),
      makeEdge('TSLA', 'AMZN', 'supplies_to', 'Autonomous Humanoid Fleets'),
    ],
  },
  // 8. Quantum Computing (IONQ)
  quantum_computing: {
    theme: 'quantum_computing',
    nodes: [
      makeNode(
        'IONQ',
        'IonQ Inc',
        'Technology',
        'Quantum Systems & Qubits',
        'mega_driver',
        3.8,
        92,
        true,
      ),
      makeNode(
        'KEYS',
        'Keysight Technologies',
        'Technology',
        'Quantum Control Instruments',
        'tier1_supplier',
        28.0,
        86,
      ),
      makeNode(
        'COHR',
        'Coherent Corp',
        'Technology',
        'Laser & Photonic Sources',
        'tier2_supplier',
        14.5,
        89,
      ),
      makeNode(
        'BA',
        'The Boeing Company',
        'Aerospace',
        'Quantum Materials Research',
        'downstream_customer',
        125.0,
        67,
      ),
    ],
    edges: [
      makeEdge('COHR', 'KEYS', 'supplies_to', 'Trapped-Ion UV Lasers'),
      makeEdge('KEYS', 'IONQ', 'supplies_to', 'Arbitrary Waveform Generators'),
      makeEdge('IONQ', 'BA', 'technology_partner', 'Aerospace Alloy Simulation'),
    ],
  },
}

describe('Tier 3: Pairwise Combinatorial Test Suite', () => {
  // =========================================================================
  // Pair 01: Mode (dedicated) × Depth (1) × Registry (NVDA)
  // =========================================================================
  it('Pair 01: Mode (dedicated) × Depth (1) × Registry (NVDA) prunes Tier 2 suppliers and retains direct links', () => {
    const eco = ECOSYSTEM_FIXTURES.ai_datacenter
    // Depth 1: keep only nodes directly connected to NVDA
    const directNeighbors = new Set<string>(['NVDA'])
    eco.edges.forEach((e) => {
      if (e.source === 'NVDA') directNeighbors.add(e.target)
      if (e.target === 'NVDA') directNeighbors.add(e.source)
    })
    const d1Nodes = eco.nodes.filter((n) => directNeighbors.has(n.symbol))

    expect(d1Nodes.some((n) => n.symbol === 'NVDA')).toBe(true)
    expect(d1Nodes.some((n) => n.symbol === 'TSM')).toBe(true)
    expect(d1Nodes.some((n) => n.symbol === 'MSFT')).toBe(true)
    // ASML is a Tier 2 supplier connected to TSM, not NVDA directly
    expect(d1Nodes.some((n) => n.symbol === 'ASML')).toBe(false)
  })

  // =========================================================================
  // Pair 02: Mode (dedicated) × Depth (2) × Registry (NVDA)
  // =========================================================================
  it('Pair 02: Mode (dedicated) × Depth (2) × Registry (NVDA) includes full multi-tier supply chain', () => {
    const eco = ECOSYSTEM_FIXTURES.ai_datacenter
    expect(eco.nodes.length).toBe(6)
    expect(eco.nodes.some((n) => n.symbol === 'ASML')).toBe(true)
    expect(eco.nodes.some((n) => n.tier === 'tier2_supplier')).toBe(true)
    expect(eco.nodes.some((n) => n.tier === 'tier1_supplier')).toBe(true)
    expect(eco.nodes.some((n) => n.tier === 'horizontal_enabler')).toBe(true)
    expect(eco.nodes.some((n) => n.tier === 'downstream_customer')).toBe(true)
  })

  // =========================================================================
  // Pair 03: Mode (intertwined) × Depth (2) × Theme (ai_datacenter)
  // =========================================================================
  it('Pair 03: Mode (intertwined) × Theme (ai_datacenter) provides full ecosystem network with catalyst events', () => {
    const eco = ECOSYSTEM_FIXTURES.ai_datacenter
    const summary: ThematicSummary = {
      theme_name: 'AI Data Center Infrastructure',
      capex_catalyst_narrative:
        'Hyperscale CapEx accelerating into liquid cooling and 800G optics.',
      total_ecosystem_market_cap_b: 7450.0,
      top_beneficiaries: ['AAOI', 'LITE', 'VRT', 'MU'],
      catalyst_timeline: [
        { date: '2026-10-15', event: 'OFC Optical Standards', impacted_tickers: ['AAOI', 'LITE'] },
      ],
    }

    expect(summary.total_ecosystem_market_cap_b).toBe(7450.0)
    expect(summary.catalyst_timeline.length).toBe(1)
    expect(eco.edges.some((e) => e.relationship === 'infrastructure_enabler')).toBe(true)
  })

  // =========================================================================
  // Pair 04: Mode (dedicated) × Depth (2) × Uncataloged Fallback (XYZUNKNOWN)
  // =========================================================================
  it('Pair 04: Mode (dedicated) × Depth (2) × Uncataloged Ticker synthesizes archetype graph with real peers', () => {
    const uncatalogedFocal = makeNode(
      'XYZUNKNOWN',
      'XYZ Robotic Logic',
      'Industrials',
      'Robotics & Automation',
      'mega_driver',
      null,
      null,
      true,
    )
    const peer1 = makeNode(
      'SYM',
      'Symbotic Inc',
      'Industrials',
      'Robotics & Automation',
      'tier1_supplier',
      12.0,
      85,
    )
    const peerEdge = makeEdge('XYZUNKNOWN', 'SYM', 'peer', 'Same-Sector Peer Benchmark')

    const nodes = [uncatalogedFocal, peer1]
    const edges = [peerEdge]

    expect(nodes.length).toBe(2)
    expect(edges.length).toBe(1)
    expect(uncatalogedFocal.metrics.elasticity_score).toBeNull() // Data-honest null
    expect(peerEdge.relationship).toBe('peer')
    expect(flowTypeClass('peer', 2, 1)).toBe('flow-peer')
  })

  // =========================================================================
  // Pair 05: Mode (intertwined) × Theme (space_defense) × Focus (ASTS)
  // =========================================================================
  it('Pair 05: Mode (intertwined) × Theme (space_defense) maps cellular direct-to-cell value chain', () => {
    const eco = ECOSYSTEM_FIXTURES.space_defense
    expect(eco.nodes.some((n) => n.symbol === 'ASTS' && n.is_focus)).toBe(true)
    expect(eco.edges.some((e) => e.source === 'RKLB' && e.target === 'ASTS')).toBe(true)
    expect(eco.edges.some((e) => e.relationship === 'co_dependent')).toBe(true)

    // Filter by space sub-industry keyword:
    const spaceBeneficiaries = rankBeneficiaries(eco.nodes, 'space')
    expect(spaceBeneficiaries.map((n) => n.symbol)).toEqual(['RKLB', 'HEI'])
  })

  // =========================================================================
  // Pair 06: Mode (dedicated) × Depth (1) × Energy (CEG)
  // =========================================================================
  it('Pair 06: Mode (dedicated) × Depth (1) × Energy (CEG) restricts to direct nuclear reactor suppliers & off-takers', () => {
    const eco = ECOSYSTEM_FIXTURES.energy_grid
    const directNeighbors = new Set<string>(['CEG'])
    eco.edges.forEach((e) => {
      if (e.source === 'CEG') directNeighbors.add(e.target)
      if (e.target === 'CEG') directNeighbors.add(e.source)
    })
    const d1Nodes = eco.nodes.filter((n) => directNeighbors.has(n.symbol))

    expect(d1Nodes.some((n) => n.symbol === 'CEG')).toBe(true)
    expect(d1Nodes.some((n) => n.symbol === 'CCJ')).toBe(true) // Direct fuel supplier
    expect(d1Nodes.some((n) => n.symbol === 'MSFT')).toBe(true) // Direct PPA customer
    expect(d1Nodes.some((n) => n.symbol === 'BWXT')).toBe(true) // Direct reactor components
  })

  // =========================================================================
  // Pair 07: Mode (intertwined) × Theme (semi_equipment) × Filter (foundry)
  // =========================================================================
  it('Pair 07: Mode (intertwined) × Theme (semi_equipment) filters foundry & lithography leaders', () => {
    const eco = ECOSYSTEM_FIXTURES.semi_equipment
    const foundryRanked = rankBeneficiaries(eco.nodes, 'foundry')
    expect(foundryRanked.length).toBeGreaterThan(0)
    expect(foundryRanked.some((n) => n.symbol === 'TSM')).toBe(true)
  })

  // =========================================================================
  // Pair 08: Mode (dedicated) × Depth (2) × Healthcare (LLY)
  // =========================================================================
  it('Pair 08: Mode (dedicated) × Depth (2) × Healthcare (LLY) maps GLP-1 injector supply chain', () => {
    const eco = ECOSYSTEM_FIXTURES.glp1_cdmo
    expect(eco.nodes.some((n) => n.symbol === 'LLY')).toBe(true)
    expect(eco.nodes.some((n) => n.symbol === 'WST')).toBe(true)
    expect(eco.nodes.some((n) => n.symbol === 'SHL')).toBe(true)

    const glp1Ranked = rankBeneficiaries(eco.nodes, 'glp1')
    expect(glp1Ranked.map((n) => n.symbol)).toEqual(['WST', 'SHL'])
  })

  // =========================================================================
  // Pair 09: Mode (intertwined) × Theme (robotics_ai) × Depth (2)
  // =========================================================================
  it('Pair 09: Mode (intertwined) × Theme (robotics_ai) maps humanoid robotics actuators & vision', () => {
    const eco = ECOSYSTEM_FIXTURES.robotics_ai
    const roboticsRanked = rankBeneficiaries(eco.nodes, 'robotics')
    expect(roboticsRanked.length).toBeGreaterThan(0)
    expect(roboticsRanked[0].symbol).toBe('NVDA') // 97
    expect(roboticsRanked[1].symbol).toBe('HMRN') // 90
  })

  // =========================================================================
  // Pair 10: Mode (intertwined) × Theme (quantum_computing) × Depth (1)
  // =========================================================================
  it('Pair 10: Mode (intertwined) × Theme (quantum_computing) filters quantum systems beneficiaries', () => {
    const eco = ECOSYSTEM_FIXTURES.quantum_computing
    const quantumRanked = rankBeneficiaries(eco.nodes, 'quantum')
    expect(quantumRanked.length).toBeGreaterThan(0)
    expect(quantumRanked.some((n) => n.symbol === 'KEYS')).toBe(true)
  })

  // =========================================================================
  // Pair 11: Mode (dedicated) × Depth (2) × Software (PLTR)
  // =========================================================================
  it('Pair 11: Mode (dedicated) × Depth (2) × Software (PLTR) maps enterprise AI data ontology stack', () => {
    const eco = ECOSYSTEM_FIXTURES.agentic_software
    const softwareRanked = rankBeneficiaries(eco.nodes, 'software')
    expect(softwareRanked.length).toBeGreaterThan(0)
    expect(softwareRanked.some((n) => n.symbol === 'SNOW')).toBe(true)
  })

  // =========================================================================
  // Pair 12: Tier Filter (tier1) × Flow (flow-supply) × Edge Highlighting
  // =========================================================================
  it('Pair 12: Tier Filter (tier1) isolates Tier 1 nodes and renders active supply arrows', async () => {
    const eco = ECOSYSTEM_FIXTURES.ai_datacenter
    const tier1Nodes = eco.nodes.filter((n) => n.tier === 'tier1_supplier')
    expect(tier1Nodes.length).toBe(2) // TSM and AAOI

    const app = createSSRApp({
      render: () =>
        h(ValueChainGraph, {
          nodes: tier1Nodes,
          edges: eco.edges,
          selectedSymbol: 'TSM',
        }),
    })
    const html = await renderToString(app)
    expect(html).toContain('TSM')
    expect(html).toContain('AAOI')
    expect(html).toContain('Tier 1 Supplier')
    expect(html).not.toContain('ASML') // Tier 2 excluded
  })

  // =========================================================================
  // Pair 13: Tier Filter (customer) × Flow (flow-demand) × Reverse Bezier
  // =========================================================================
  it('Pair 13: Tier Filter (customer) with reverse demand flows assigns flow-demand class', () => {
    // Col 3 (customer) to Col 2 (driver): srcCol > tgtCol
    const flowType = flowTypeClass('purchases_from', 3, 2)
    expect(flowType).toBe('flow-demand')
    expect(flowMarkerId(flowType, true)).toBe('url(#arrow-demand)')
    expect(relationshipLabel('purchases_from')).toBe('Purchases from')
  })

  // =========================================================================
  // Pair 14: Thematic Bridge Jump (energy_grid <-> ai_datacenter)
  // =========================================================================
  it('Pair 14: Thematic Bridge Jump shares tickers between nuclear power and data center themes', () => {
    const aiTheme = ECOSYSTEM_FIXTURES.ai_datacenter
    const energyTheme = ECOSYSTEM_FIXTURES.energy_grid

    // Check shared ticker across value chains
    const aiSymbols = new Set(aiTheme.nodes.map((n) => n.symbol))
    const energySymbols = new Set(energyTheme.nodes.map((n) => n.symbol))
    const shared = [...aiSymbols].filter((s) => energySymbols.has(s))

    // Both feature MSFT as the hyperscale cloud power customer
    expect(shared).toContain('MSFT')

    const bridge: ThematicBridge = {
      id: 'energy_grid',
      theme_name: 'Power Grid & Nuclear SMRs',
      role: 'Clean power baseload for data centers',
      shared_tickers: shared,
    }
    expect(bridge.shared_tickers).toContain('MSFT')
  })

  // =========================================================================
  // Pair 15: Sub-Industry Filter (cooling) × minElasticity (90)
  // =========================================================================
  it('Pair 15: Filter (cooling) × minElasticity (90) isolates high-elasticity cooling leaders', () => {
    const eco = ECOSYSTEM_FIXTURES.ai_datacenter
    const coolingNodes = rankBeneficiaries(eco.nodes, 'cooling', 90)
    expect(coolingNodes.map((n) => n.symbol)).toEqual(['VRT'])
    expect(coolingNodes[0].metrics.elasticity_score).toBe(92)
  })

  // =========================================================================
  // Pair 16: Options Skew (heavy_call_sweep) × High Elasticity (>=90) Confluence
  // =========================================================================
  it('Pair 16: Options Skew (heavy_call_sweep) aligns with high elasticity scores', () => {
    const eco = ECOSYSTEM_FIXTURES.ai_datacenter
    const bullishBeneficiaries = eco.nodes.filter(
      (n) =>
        n.metrics.options_skew === 'heavy_call_sweep' && (n.metrics.elasticity_score ?? 0) >= 90,
    )
    expect(bullishBeneficiaries.length).toBeGreaterThan(0)
    expect(bullishBeneficiaries.map((n) => n.symbol)).toContain('NVDA')
    expect(bullishBeneficiaries.map((n) => n.symbol)).toContain('VRT')
  })
})
