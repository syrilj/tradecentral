import { describe, it, expect } from 'vitest'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { routerKey, type Router } from 'vue-router'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import ValueChainGraph from '@/components/ValueChainGraph.vue'
import EvidenceDrawer from '@/components/EvidenceDrawer.vue'
import type {
  BeneficiaryMetrics,
  RelationshipType,
  SupplyChainEdge,
  SupplyChainNode,
  SupplyTier,
} from '@/api'
import {
  generateRelationshipNarrative,
  formatContractValue,
  strengthTone,
  flowTypeClass,
} from '@/chainDisplay'

function makeMetrics(elasticity: number | null = 80): BeneficiaryMetrics {
  return {
    elasticity_score: elasticity,
    capex_sensitivity: 2.5,
    revenue_concentration_pct: 20.0,
    operating_leverage: 2.0,
    forward_pe: 25.0,
    peg_ratio: 1.2,
    gross_margin_trend: 'stable',
    yoy_revenue_growth: 15.0,
    next_earnings_date: '2026-10-15',
    flow_sentiment_score: 0.75,
    options_skew: 'balanced_bullish',
  }
}

function makeMockNode(
  symbol: string,
  tier: SupplyTier,
  options: Partial<SupplyChainNode> = {},
): SupplyChainNode {
  return {
    symbol,
    name: `${symbol} Corporation`,
    sector: 'Technology',
    sub_industry: 'General Infrastructure',
    tier,
    market_cap_billions: 100,
    evidence: [],
    metrics: makeMetrics(),
    ...options,
  }
}

function makeMockEdge(
  id: string,
  source: string,
  target: string,
  relationship: RelationshipType = 'supplies_to',
  options: Partial<SupplyChainEdge> = {},
): SupplyChainEdge {
  return {
    id,
    source,
    target,
    relationship,
    strength: 0.8,
    supply_category: 'Hardware Component',
    evidence_count: 1,
    ...options,
  }
}

function renderDrawer(props: {
  node?: SupplyChainNode | null
  open: boolean
  edges?: SupplyChainEdge[]
  focalNode?: SupplyChainNode | null
  incidentEdges?: SupplyChainEdge[]
}) {
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

function renderGraph(props: {
  nodes: SupplyChainNode[]
  edges: SupplyChainEdge[]
  selectedSymbol?: string | null
}) {
  const app = createSSRApp({
    render: () => h(ValueChainGraph, props),
  })
  return renderToString(app)
}

describe('Challenger 2: Adversarial Layout, SVG Geometry & Workload Stress', () => {
  // =========================================================================
  // 1. ADVERSARIAL LAYOUT & HIGH-DENSITY COLUMN STRESS
  // =========================================================================
  describe('High-Density Column Stress & Non-Overlapping Invariants', () => {
    it('handles 25+ nodes in Column 3 with zero overlapping cards and strictly non-negative coordinates', async () => {
      // Stress test: 25 customer nodes in Column 3
      const highDensityNodes: SupplyChainNode[] = []
      const edges: SupplyChainEdge[] = []

      // 1 Core Driver in Col 2
      highDensityNodes.push(
        makeMockNode('NVDA', 'mega_driver', {
          name: 'NVIDIA Corp',
          sector: 'Technology',
          sub_industry: 'Semiconductors',
          market_cap_billions: 3100,
          is_focus: true,
          metrics: makeMetrics(99),
        }),
      )

      // 25 Downstream Customers in Col 3
      for (let i = 0; i < 25; i++) {
        const sym = `CUST_${i.toString().padStart(2, '0')}`
        highDensityNodes.push(
          makeMockNode(sym, 'downstream_customer', {
            name: `Customer Entity ${i}`,
            sector: 'Technology',
            sub_industry: 'Cloud Infrastructure',
            market_cap_billions: 50 + i * 10,
            metrics: makeMetrics(60 + (i % 30)),
          }),
        )
        edges.push(
          makeMockEdge(`edge_nvda_${sym}`, 'NVDA', sym, 'purchases_from', {
            strength: 0.75,
            supply_category: 'AI Clusters',
          }),
        )
      }

      const html = await renderGraph({
        nodes: highDensityNodes,
        edges,
        selectedSymbol: 'NVDA',
      })

      // Extract total height from SVG viewBox
      const viewBoxMatch = html.match(/viewBox="0 0 1080 (\d+)"/)
      expect(viewBoxMatch).not.toBeNull()
      const totalHeight = parseInt(viewBoxMatch![1], 10)

      // Expected height: Math.max(540, 60 + 25 * 88 + 40) = 2300px
      expect(totalHeight).toBeGreaterThanOrEqual(2300)

      // Extract all card top positions in Column 3 (left: 780px)
      const cardRegex = /left:\s*780px;\s*top:\s*(\d+(\.\d+)?)px;/g
      const matches = [...html.matchAll(cardRegex)]
      expect(matches.length).toBe(25)

      const tops = matches.map((m) => parseFloat(m[1])).sort((a, b) => a - b)

      // Verify strict non-overlap: top[i+1] - top[i] == 88px (cardHeight 72px + gap 16px)
      for (let i = 0; i < tops.length - 1; i++) {
        const diff = tops[i + 1] - tops[i]
        expect(diff).toBeCloseTo(88, 1)
        // Verify gap between bottom of card i and top of card i+1 is >= 16px
        expect(tops[i + 1] - (tops[i] + 72)).toBeGreaterThanOrEqual(15.9)
      }

      // Verify all card tops are non-negative and all card bottoms stay within totalHeight
      for (const top of tops) {
        expect(top).toBeGreaterThanOrEqual(40)
        expect(top + 72).toBeLessThanOrEqual(totalHeight)
      }
    })

    it('handles mixed asymmetric column distributions (e.g. Col 0: 20, Col 1: 3, Col 2: 1, Col 3: 15)', async () => {
      const mixedNodes: SupplyChainNode[] = []

      // Col 0: 20 Tier 2 nodes
      for (let i = 0; i < 20; i++) {
        mixedNodes.push(
          makeMockNode(`T2_${i}`, 'tier2_supplier', {
            name: `Tier 2 Raw Materials ${i}`,
            sector: 'Materials',
            sub_industry: 'Specialty Chemicals',
            market_cap_billions: 10,
            metrics: makeMetrics(80),
          }),
        )
      }

      // Col 1: 3 Tier 1 nodes
      for (let i = 0; i < 3; i++) {
        mixedNodes.push(
          makeMockNode(`T1_${i}`, 'tier1_supplier', {
            name: `Tier 1 Fabricator ${i}`,
            sector: 'Semiconductors',
            sub_industry: 'Foundry Subsystems',
            market_cap_billions: 40,
            metrics: makeMetrics(88),
          }),
        )
      }

      // Col 2: 1 Core Driver
      mixedNodes.push(
        makeMockNode('CORE_DRIVER', 'mega_driver', {
          name: 'Core Megacap',
          sector: 'Technology',
          sub_industry: 'Semiconductors',
          market_cap_billions: 2500,
          is_focus: true,
          metrics: makeMetrics(99),
        }),
      )

      // Col 3: 15 Customers
      for (let i = 0; i < 15; i++) {
        mixedNodes.push(
          makeMockNode(`CUST_${i}`, 'downstream_customer', {
            name: `Enterprise Buyer ${i}`,
            sector: 'Technology',
            sub_industry: 'Software',
            market_cap_billions: 100,
            metrics: makeMetrics(70),
          }),
        )
      }

      const html = await renderGraph({
        nodes: mixedNodes,
        edges: [],
      })

      // Column 0 cards start at left: 60px
      const col0Matches = [...html.matchAll(/left:\s*60px;\s*top:\s*(\d+(\.\d+)?)px;/g)]
      expect(col0Matches.length).toBe(20)

      // Column 1 cards start at left: 300px
      const col1Matches = [...html.matchAll(/left:\s*300px;\s*top:\s*(\d+(\.\d+)?)px;/g)]
      expect(col1Matches.length).toBe(3)

      // Column 2 cards start at left: 540px
      const col2Matches = [...html.matchAll(/left:\s*540px;\s*top:\s*(\d+(\.\d+)?)px;/g)]
      expect(col2Matches.length).toBe(1)

      // Column 3 cards start at left: 780px
      const col3Matches = [...html.matchAll(/left:\s*780px;\s*top:\s*(\d+(\.\d+)?)px;/g)]
      expect(col3Matches.length).toBe(15)

      // Verify colOffsetY centering behavior: sparse columns (col 1, 2) have greater offset than col 0 (max rows = 20)
      const col0FirstTop = parseFloat(col0Matches[0][1])
      const col1FirstTop = parseFloat(col1Matches[0][1])
      const col2FirstTop = parseFloat(col2Matches[0][1])

      // Col 0 has 20 rows, so colOffsetY is 0; top is exactly 40px
      expect(col0FirstTop).toBe(40)
      // Col 1 has 3 rows, so (20 - 3) * 88 * 0.12 ~ 179.52px offset; top > 40px
      expect(col1FirstTop).toBeGreaterThan(col0FirstTop)
      // Col 2 has 1 row, so (20 - 1) * 88 * 0.12 ~ 200.64px offset; top > col1FirstTop
      expect(col2FirstTop).toBeGreaterThan(col1FirstTop)
    })
  })

  // =========================================================================
  // 2. LATERAL ARC GEOMETRY & VIEWBOX CLIPPING STRESS (Col 3 & Col 0)
  // =========================================================================
  describe('Lateral Peer Arc Geometry & Boundary Clipping', () => {
    it('confirms Column 3 lateral peer arcs never exceed 1005px (staying >= 75px inside the 1080px viewBox)', async () => {
      // Create 4 customer nodes in Column 3 and multiple lateral peer edges
      const nodes: SupplyChainNode[] = [
        makeMockNode('CLOUD_A', 'downstream_customer', {
          name: 'Cloud Platform A',
          sector: 'Cloud',
          sub_industry: 'Hyperscale Infrastructure',
          market_cap_billions: 2000,
          metrics: makeMetrics(80),
        }),
        makeMockNode('CLOUD_B', 'downstream_customer', {
          name: 'Cloud Platform B',
          sector: 'Cloud',
          sub_industry: 'Hyperscale Infrastructure',
          market_cap_billions: 1800,
          metrics: makeMetrics(75),
        }),
        makeMockNode('CLOUD_C', 'downstream_customer', {
          name: 'Cloud Platform C',
          sector: 'Cloud',
          sub_industry: 'Enterprise Cloud',
          market_cap_billions: 900,
          metrics: makeMetrics(70),
        }),
        makeMockNode('CLOUD_D', 'downstream_customer', {
          name: 'Cloud Platform D',
          sector: 'Cloud',
          sub_industry: 'AI Cloud Hosting',
          market_cap_billions: 600,
          metrics: makeMetrics(72),
        }),
      ]

      const edges: SupplyChainEdge[] = [
        makeMockEdge('peer_a_b', 'CLOUD_A', 'CLOUD_B', 'peer', {
          strength: 0.85,
          supply_category: 'Direct Peer Cloud',
        }),
        makeMockEdge('peer_a_d', 'CLOUD_A', 'CLOUD_D', 'peer', {
          strength: 0.9,
          supply_category: 'AI Cloud Competitor',
          evidence_count: 2,
        }),
        makeMockEdge('peer_d_b', 'CLOUD_D', 'CLOUD_B', 'peer', {
          strength: 0.8,
          supply_category: 'Host Competitor',
        }),
      ]

      const html = await renderGraph({ nodes, edges, selectedSymbol: 'CLOUD_A' })

      // Find all SVG path tags
      const pathMatches = [
        ...html.matchAll(/<path[^>]*\bd="([^"]+)"[^>]*class="[^"]*flow-peer[^"]*"/g),
      ]
      expect(pathMatches.length).toBe(3)

      for (const match of pathMatches) {
        const d = match[1]
        // Example: M 960 62 C 980 62, 985 150, 965 150
        const coords = d.match(/-?\d+(\.\d+)?/g)?.map(Number) ?? []
        // Extract all X coordinates (even indices)
        const xCoords = coords.filter((_, idx) => idx % 2 === 0)

        for (const x of xCoords) {
          // Absolute zero clipping invariant: no point may exceed 1005px
          expect(x).toBeLessThanOrEqual(1005)
          // Must stay strictly within the 1080px canvas
          expect(x).toBeLessThan(1080)
          // Must start at or beyond card right edge in Col 3 (x = 780 + 180 = 960)
          expect(x).toBeGreaterThanOrEqual(960)
        }
      }
    })

    it('confirms Column 0 lateral peer arcs stay within the Col 0-to-Col 1 gutter (< 300px) and never collide with Column 1 cards', async () => {
      // Column 0 cards start at x=60, width=180, right edge = 240.
      // Column 1 starts at x=300.
      // Any lateral arc in Column 0 must stay < 300px so it never overlaps Column 1 cards!
      const nodes: SupplyChainNode[] = [
        makeMockNode('T2_MAT_A', 'tier2_supplier', {
          name: 'Tier 2 Material A',
          sector: 'Materials',
          sub_industry: 'Quartz',
          market_cap_billions: 5,
          metrics: makeMetrics(85),
        }),
        makeMockNode('T2_MAT_B', 'tier2_supplier', {
          name: 'Tier 2 Material B',
          sector: 'Materials',
          sub_industry: 'Silicon Ingots',
          market_cap_billions: 8,
          metrics: makeMetrics(82),
        }),
        makeMockNode('T2_MAT_C', 'tier2_supplier', {
          name: 'Tier 2 Material C',
          sector: 'Materials',
          sub_industry: 'Polysilicon',
          market_cap_billions: 12,
          metrics: makeMetrics(79),
        }),
      ]

      const edges: SupplyChainEdge[] = [
        makeMockEdge('peer_t2_ab', 'T2_MAT_A', 'T2_MAT_B', 'peer', {
          strength: 0.75,
          supply_category: 'Raw Silicon Feedstock',
        }),
        makeMockEdge('peer_t2_ac', 'T2_MAT_A', 'T2_MAT_C', 'peer', {
          strength: 0.7,
          supply_category: 'Ingot Crystal Pulling',
        }),
      ]

      const html = await renderGraph({ nodes, edges, selectedSymbol: 'T2_MAT_A' })

      const pathMatches = [
        ...html.matchAll(/<path[^>]*\bd="([^"]+)"[^>]*class="[^"]*flow-peer[^"]*"/g),
      ]
      expect(pathMatches.length).toBe(2)

      for (const match of pathMatches) {
        const d = match[1]
        const coords = d.match(/-?\d+(\.\d+)?/g)?.map(Number) ?? []
        const xCoords = coords.filter((_, idx) => idx % 2 === 0)

        for (const x of xCoords) {
          // Col 0 right edge is 240px
          expect(x).toBeGreaterThanOrEqual(240)
          // Must stay strictly below 300px (Column 1 start boundary)
          expect(x).toBeLessThan(300)
        }
      }
    })
  })

  // =========================================================================
  // 3. FLOATING RELATIONSHIP PILL BEZIER MIDPOINT STRESS
  // =========================================================================
  describe('Floating Relationship Pill Bezier Midpoint Bounding', () => {
    it('mathematically bounds floating pill midX between 90px and 990px across all tier transitions', async () => {
      // Test 4 extreme transitions:
      // 1. Extreme left-to-right: Col 0 -> Col 3 (T2 -> Cust)
      // 2. Extreme right-to-left: Col 3 -> Col 0 (Cust -> T2)
      // 3. Col 0 same-column peer: Col 0 -> Col 0
      // 4. Col 3 same-column peer: Col 3 -> Col 3
      const nodes: SupplyChainNode[] = [
        makeMockNode('T2_LEFT', 'tier2_supplier', {
          name: 'T2 Leftmost',
          sector: 'Materials',
          sub_industry: 'Raw Minerals',
          market_cap_billions: 2,
          metrics: makeMetrics(90),
        }),
        makeMockNode('T2_PEER', 'tier2_supplier', {
          name: 'T2 Peer',
          sector: 'Materials',
          sub_industry: 'Raw Minerals',
          market_cap_billions: 3,
          metrics: makeMetrics(85),
        }),
        makeMockNode('CUST_RIGHT', 'downstream_customer', {
          name: 'Cust Rightmost',
          sector: 'Technology',
          sub_industry: 'Enterprise Software',
          market_cap_billions: 2500,
          metrics: makeMetrics(65),
        }),
        makeMockNode('CUST_PEER', 'downstream_customer', {
          name: 'Cust Peer',
          sector: 'Technology',
          sub_industry: 'Enterprise Software',
          market_cap_billions: 1800,
          metrics: makeMetrics(68),
        }),
      ]

      const edges: SupplyChainEdge[] = [
        makeMockEdge('edge_long_span_fwd', 'T2_LEFT', 'CUST_RIGHT', 'supplies_to', {
          strength: 0.95,
          supply_category: 'End-to-End Delivery',
          evidence_count: 2,
        }),
        makeMockEdge('edge_long_span_rev', 'CUST_RIGHT', 'T2_LEFT', 'purchases_from', {
          strength: 0.88,
          supply_category: 'Reverse Sourcing',
        }),
        makeMockEdge('edge_col0_peer', 'T2_LEFT', 'T2_PEER', 'peer', {
          strength: 0.75,
          supply_category: 'Mineral Exploration Peer',
        }),
        makeMockEdge('edge_col3_peer', 'CUST_RIGHT', 'CUST_PEER', 'peer', {
          strength: 0.8,
          supply_category: 'Enterprise SaaS Competitor',
        }),
      ]

      for (const edge of edges) {
        const html = await renderGraph({
          nodes,
          edges: [edge],
          selectedSymbol: edge.source,
        })

        // Verify floating-edge-pill renders
        expect(html).toContain('floating-edge-pill')

        // Extract left and top inline styles: left: (\d+)px; top: (\d+)px
        const pillMatch = html.match(
          /class="floating-edge-pill"[^>]*style="left:\s*(\d+(\.\d+)?)px;\s*top:\s*(\d+(\.\d+)?)px;"/,
        )
        expect(pillMatch).not.toBeNull()

        const midX = parseFloat(pillMatch![1])
        const midY = parseFloat(pillMatch![3])

        // Clamping invariant: midX must be >= 90 and <= 990 (1080 - 90)
        expect(midX).toBeGreaterThanOrEqual(90)
        expect(midX).toBeLessThanOrEqual(990)

        // midY must be non-negative and within canvas height
        expect(midY).toBeGreaterThanOrEqual(0)
        expect(midY).toBeLessThan(1000)
      }
    })
  })

  // =========================================================================
  // 4. COMPONENT & INTERACTION STATE STRESS (ChainView & EvidenceDrawer)
  // =========================================================================
  describe('Multi-Stage Loading Stepper & Sequential Search Cancellation', () => {
    it('defines the required multi-stage loading progression and clearAllTimers cleanup', async () => {
      const fs = await import('node:fs')
      const path = await import('node:path')
      const chainViewCode = fs.readFileSync(
        path.join(process.cwd(), 'src/views/ChainView.vue'),
        'utf-8',
      )

      // Verify clearAllTimers clears all 5 timer handles
      expect(chainViewCode).toContain('function clearAllTimers()')
      expect(chainViewCode).toContain('clearTimeout(stageTimer1)')
      expect(chainViewCode).toContain('clearTimeout(stageTimer2)')
      expect(chainViewCode).toContain('clearTimeout(stageTimer3)')
      expect(chainViewCode).toContain('clearInterval(elapsedInterval)')
      expect(chainViewCode).toContain('clearTimeout(completeDismissTimer)')
      expect(chainViewCode).toContain('clearTimeout(debounceTimer)')

      // Verify startLoadingStages resets state and initiates stage timers
      expect(chainViewCode).toContain('function startLoadingStages')
      expect(chainViewCode).toContain("loadingStage.value = 'resolving'")
      expect(chainViewCode).toContain('loadingProgress.value = 20')
      expect(chainViewCode).toContain("loadingStage.value = 'fetching'")
      expect(chainViewCode).toContain('loadingProgress.value = 50')
      expect(chainViewCode).toContain("loadingStage.value = 'mapping'")
      expect(chainViewCode).toContain('loadingProgress.value = 75')
      expect(chainViewCode).toContain("loadingStage.value = 'rendering'")
      expect(chainViewCode).toContain('loadingProgress.value = 90')
      expect(chainViewCode).toContain("loadingStage.value = 'complete'")
      expect(chainViewCode).toContain('loadingProgress.value = 100')

      // Verify failLoadingStages transitions to error state
      expect(chainViewCode).toContain('function failLoadingStages')
      expect(chainViewCode).toContain("loadingStage.value = 'error'")
    })

    it('verifies error banner display, dismiss, and retry action semantics', async () => {
      const fs = await import('node:fs')
      const path = await import('node:path')
      const chainViewCode = fs.readFileSync(
        path.join(process.cwd(), 'src/views/ChainView.vue'),
        'utf-8',
      )

      // Verify activeError is decoupled from !payload
      expect(chainViewCode).toContain('v-if="activeError"')
      expect(chainViewCode).not.toContain('v-if="chainResource.error.value && !payload"')

      // Verify retryFetch resets dismissed error and calls triggerRefresh
      expect(chainViewCode).toContain('function retryFetch()')
      expect(chainViewCode).toContain('dismissedError.value = null')
      expect(chainViewCode).toContain('triggerRefresh()')

      // Verify dismissError sets dismissedError to current error
      expect(chainViewCode).toContain('function dismissError()')
      expect(chainViewCode).toContain('dismissedError.value = chainResource.error.value')
    })
  })

  // =========================================================================
  // 5. EVIDENCE DRAWER RATIONALE & FALLBACK NARRATIVE STRESS
  // =========================================================================
  describe('EvidenceDrawer Rationale & Fallback Stress', () => {
    it('displays full relationship rationale when incident edges are present', async () => {
      const testNode = makeMockNode('ALAB', 'tier1_supplier', {
        name: 'Astera Labs Inc.',
        sub_industry: 'PCIe Connectivity Retimers',
        market_cap_billions: 14.5,
        metrics: {
          elasticity_score: 95.0,
          capex_sensitivity: 4.6,
          revenue_concentration_pct: 38.0,
          operating_leverage: 3.1,
          forward_pe: 45.0,
          peg_ratio: 1.4,
          gross_margin_trend: 'expanding',
          yoy_revenue_growth: 140.0,
          next_earnings_date: '2026-11-04',
          flow_sentiment_score: 0.91,
          options_skew: 'heavy_call_sweep',
        },
      })

      const incidentEdge = makeMockEdge('edge_alab_nvda', 'ALAB', 'NVDA', 'technology_partner', {
        strength: 0.92,
        supply_category: 'PCIe Gen 5/6 Smart Cable Modules & Retimers',
        annual_contract_value_est_m: 450,
        evidence_count: 3,
      })

      const html = await renderDrawer({
        node: testNode,
        open: true,
        incidentEdges: [incidentEdge],
      })

      // Header & ticker details
      expect(html).toContain('ALAB')
      expect(html).toContain('Astera Labs Inc.')
      expect(html).toContain('Tier 1 Supplier')

      // Relationship Section
      expect(html).toContain('RELATIONSHIP RATIONALE &amp; CONTRACT CONTEXT')
      expect(html).toContain('ALAB ➔ NVDA')
      expect(html).toContain('Tech Partner of')
      expect(html).toContain('PCIe Gen 5/6 Smart Cable Modules &amp; Retimers')
      expect(html).toContain('$450M / yr')
      expect(html).toContain('92%')
      expect(html).toContain('strength-high')

      // Generated Narrative verification
      const narrative = generateRelationshipNarrative(incidentEdge, testNode)
      expect(narrative).toContain(
        'critical partner that tech partner of NVDA supplying PCIe Gen 5/6 Smart Cable Modules & Retimers',
      )
      expect(narrative).toContain('92% dependency link')
      expect(narrative).toContain('Estimated annual procurement / contract value is ~$450M / yr')
      expect(narrative).toContain('Revenue concentration to key driver is ~38.0%')
      expect(html).toContain('Revenue concentration to key driver is ~38.0%')
    })

    it('falls back gracefully to CORE ECOSYSTEM ANCHOR narrative when focal/mega_driver node has no incident edges', async () => {
      const focalDriverNode = makeMockNode('NVDA', 'mega_driver', {
        name: 'NVIDIA Corporation',
        sub_industry: 'Accelerated Compute',
        market_cap_billions: 3100,
        is_focus: true,
        metrics: makeMetrics(99),
      })

      const html = await renderDrawer({
        node: focalDriverNode,
        open: true,
        incidentEdges: [],
        edges: [],
      })

      expect(html).toContain('CORE ECOSYSTEM ANCHOR')
      expect(html).toContain(
        'NVIDIA Corporation (NVDA) is the central anchor entity for this value chain',
      )
      expect(html).toContain(
        'Capital expenditures, architectural roadmap decisions, and procurement volume',
      )
    })

    it('falls back gracefully to standard sector narrative when unlinked non-focal node has no incident edges', async () => {
      const unlinkedNode = makeMockNode('ISOLATED', 'tier2_supplier', {
        name: 'Isolated Tech Inc.',
        sub_industry: 'Specialty Testing',
        market_cap_billions: 1.2,
        metrics: makeMetrics(55),
      })

      const html = await renderDrawer({
        node: unlinkedNode,
        open: true,
        incidentEdges: [],
        edges: [],
      })

      expect(html).toContain('Tier 2 Supplier')
      expect(html).toContain('fallback-role-tag')
      expect(html).toContain(
        'Isolated Tech Inc. (ISOLATED) operates within Specialty Testing (Technology)',
      )
      expect(html).toContain(
        'Financial elasticity and revenue concentration propagate through correlated demand shifts',
      )
    })

    it('renders explicit dashes for all missing or null metrics in EvidenceDrawer with zero fake values', async () => {
      const nullMetricsNode: SupplyChainNode = {
        symbol: 'EARLY_STAGE',
        name: 'Pre-Revenue Tech',
        sector: 'Space',
        sub_industry: 'Lunar Payload',
        tier: 'tier2_supplier',
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
      }

      const html = await renderDrawer({
        node: nullMetricsNode,
        open: true,
      })

      // Market cap formatted as dash
      expect(html).toContain('Lunar Payload · —')
      // Metric values formatted as dash
      expect(html).toContain('ELASTICITY SCORE')
      expect(html).toContain('CAPEX SENSITIVITY')
      expect(html).toContain('REV CONCENTRATION')
      expect(html).toContain('OPTIONS SKEW')
      // None of the metrics should display fake zeros
      expect(html).not.toContain('>0.0<')
      expect(html).not.toContain('>$0.0B<')
      expect(html).not.toContain('>+0.0x<')
      expect(html).not.toContain('>0.0%<')
    })
  })

  // =========================================================================
  // 6. KEYBOARD ACCESSIBILITY & DESIGN TOKEN CONFORMANCE (HEX BAN)
  // =========================================================================
  describe('Keyboard Accessibility & Strict Design Token Conformance', () => {
    it('verifies ValueChainGraph and EvidenceDrawer conform to design token rules with ZERO hardcoded hex codes', () => {
      const graphSrc = readFileSync(
        join(process.cwd(), 'src/components/ValueChainGraph.vue'),
        'utf-8',
      )
      const drawerSrc = readFileSync(
        join(process.cwd(), 'src/components/EvidenceDrawer.vue'),
        'utf-8',
      )

      // Hex code regex in CSS: #[0-9a-fA-F]{3,8}\b (excluding comments)
      const cssRegex = /<style[^>]*>([\s\S]*?)<\/style>/g

      const checkNoHexInStyle = (src: string, componentName: string) => {
        let match: RegExpExecArray | null
        while ((match = cssRegex.exec(src)) !== null) {
          const styleBlock = match[1]
          // Filter out comments
          const cleaned = styleBlock.replace(/\/\*[\s\S]*?\*\//g, '')
          const hexMatches = cleaned.match(/#[0-9a-fA-F]{3,8}\b/g)
          expect(
            hexMatches,
            `Component ${componentName} contains hardcoded hex colors in <style>: ${hexMatches?.join(', ')}`,
          ).toBeNull()
        }
      }

      checkNoHexInStyle(graphSrc, 'ValueChainGraph.vue')
      checkNoHexInStyle(drawerSrc, 'EvidenceDrawer.vue')
    })

    it('verifies keyboard focusable attributes and :focus-visible rules across all interactive elements', () => {
      const graphSrc = readFileSync(
        join(process.cwd(), 'src/components/ValueChainGraph.vue'),
        'utf-8',
      )
      const drawerSrc = readFileSync(
        join(process.cwd(), 'src/components/EvidenceDrawer.vue'),
        'utf-8',
      )

      // Card attributes
      expect(graphSrc).toContain('tabindex="0"')
      expect(graphSrc).toContain('role="button"')
      expect(graphSrc).toContain('@keydown.enter')
      expect(graphSrc).toContain('@keydown.space.prevent')

      // Focus-visible CSS
      expect(graphSrc).toContain('.node-card:focus-visible')
      expect(graphSrc).toContain('.tier-filter-btn:focus-visible')
      expect(graphSrc).toContain('.node-focus-tag:focus-visible')
      expect(graphSrc).toContain('outline: 2px solid var(--accent, var(--phosphor));')

      // EvidenceDrawer Focus-visible & Esc
      expect(drawerSrc).toContain('@keydown.esc')
      expect(drawerSrc).toContain('.close-btn:focus-visible')
      expect(drawerSrc).toContain('.desk-btn:focus-visible')
      expect(drawerSrc).toContain('outline: 2px solid var(--accent, var(--phosphor));')
    })
  })

  // =========================================================================
  // 7. UTILITY FUNCTION STRESS & ORACLE PRECISION
  // =========================================================================
  describe('chainDisplay Precision & Flow Type Oracle', () => {
    it('validates strengthTone thresholds and contract value formatting edge cases', () => {
      expect(strengthTone(null)).toBe('mid')
      expect(strengthTone(undefined)).toBe('mid')
      expect(strengthTone(0.8)).toBe('high')
      expect(strengthTone(0.99)).toBe('high')
      expect(strengthTone(0.5)).toBe('mid')
      expect(strengthTone(0.79)).toBe('mid')
      expect(strengthTone(0.49)).toBe('low')
      expect(strengthTone(0.0)).toBe('low')

      expect(formatContractValue(null)).toBe('—')
      expect(formatContractValue(undefined)).toBe('—')
      expect(formatContractValue(NaN)).toBe('—')
      expect(formatContractValue(Infinity)).toBe('—')
      expect(formatContractValue(150)).toBe('$150M / yr')
      expect(formatContractValue(999)).toBe('$999M / yr')
      expect(formatContractValue(1000)).toBe('$1.0B / yr')
      expect(formatContractValue(8500)).toBe('$8.5B / yr')
      expect(formatContractValue(14250)).toBe('$14.3B / yr')
    })

    it('validates flowTypeClass across reverse procurement, lateral peer, and technology partner edges', () => {
      // Lateral peer
      expect(flowTypeClass('peer', 3, 3)).toBe('flow-peer')
      expect(flowTypeClass('peer', 0, 0)).toBe('flow-peer')

      // Technology partner & co-dependent
      expect(flowTypeClass('technology_partner', 1, 2)).toBe('flow-partner')
      expect(flowTypeClass('co_dependent', 2, 2)).toBe('flow-partner')

      // Reverse procurement (purchases_from or srcCol > tgtCol)
      expect(flowTypeClass('purchases_from', 2, 3)).toBe('flow-demand')
      expect(flowTypeClass('supplies_to', 3, 2)).toBe('flow-demand')

      // Standard forward supply flow (srcCol < tgtCol)
      expect(flowTypeClass('supplies_to', 0, 1)).toBe('flow-supply')
      expect(flowTypeClass('supplies_to', 1, 2)).toBe('flow-supply')
      expect(flowTypeClass('infrastructure_enabler', 2, 3)).toBe('flow-supply')
    })
  })
})
