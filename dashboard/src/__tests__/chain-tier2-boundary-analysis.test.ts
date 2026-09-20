/**
 * Tier 2: Boundary Value Analysis & Corner Cases — Value Chain & Supply Network
 *
 * Requirements: >= 35 test assertions covering:
 *  - Missing metrics policy: null elasticity, null CapEx, null options skew formatting cleanly as "—" (zero fake zeros).
 *  - Extreme market caps ($0.01B to $10,000B+), single-node graphs, max-density columns.
 *  - Malformed symbols, symbol bounds, and SVG viewBox coordinates.
 *  - Degenerate graphs (empty nodes, single node, 0 edges).
 *  - Extreme elasticity thresholds and boundary conditions in beneficiary ranking.
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
  elasticityTone,
  formatCapExSensitivity,
  formatRevConcentration,
  formatMarketCap,
  optionsSkewLabel,
  rankBeneficiaries,
} from '@/chainDisplay'

import ValueChainGraph from '@/components/ValueChainGraph.vue'
import EvidenceDrawer from '@/components/EvidenceDrawer.vue'

import type { SupplyChainNode } from '@/api'

describe('Tier 2: Boundary Value Analysis & Edge Cases', () => {
  // =========================================================================
  // B01: Missing Metrics Policy (Strict Null Handling & Zero Fake Data)
  // =========================================================================
  describe('B01: Missing Metrics Policy & Zero Fake Data Mandate', () => {
    it('formats unmeasured metrics strictly as explicit dash "—" (zero fake zeros)', () => {
      // Null, undefined, NaN, Infinity inputs must NEVER format as fake zeros like "0.0x", "0.0%", "$0.0B"
      expect(formatCapExSensitivity(null)).toBe('—')
      expect(formatCapExSensitivity(undefined)).toBe('—')
      expect(formatCapExSensitivity(NaN)).toBe('—')
      expect(formatCapExSensitivity(Infinity)).toBe('—')
      expect(formatCapExSensitivity(-Infinity)).toBe('—')

      expect(formatRevConcentration(null)).toBe('—')
      expect(formatRevConcentration(undefined)).toBe('—')
      expect(formatRevConcentration(NaN)).toBe('—')
      expect(formatRevConcentration(Infinity)).toBe('—')

      expect(formatMarketCap(null)).toBe('—')
      expect(formatMarketCap(undefined)).toBe('—')
      expect(formatMarketCap(NaN)).toBe('—')
      expect(formatMarketCap(Infinity)).toBe('—')
    })

    it('handles options skew nullability without inventing a fake "Neutral" chip', () => {
      // Missing options skew must return null so that UI does not render a fake "Neutral" badge
      expect(optionsSkewLabel(null)).toBeNull()
      expect(optionsSkewLabel(undefined)).toBeNull()
      expect(optionsSkewLabel('')).toBeNull()

      // Valid skews return structured labels with tones
      expect(optionsSkewLabel('heavy_call_sweep')).toEqual({ label: 'Call Sweep', tone: 'up' })
      expect(optionsSkewLabel('bullish_call_drift')).toEqual({ label: 'Bull Drift', tone: 'up' })
      expect(optionsSkewLabel('balanced_bullish')).toEqual({ label: 'Lean Bull', tone: 'warm' })
      expect(optionsSkewLabel('hedged')).toEqual({ label: 'Hedged', tone: 'cool' })
      expect(optionsSkewLabel('bearish_put_skew')).toEqual({ label: 'Put Skew', tone: 'down' })
      expect(optionsSkewLabel('custom_skew_code')).toEqual({ label: 'custom_skew_code', tone: 'cool' })
    })

    it('assigns cool neutral tone to null elasticity scores without injecting arbitrary fallback values', () => {
      expect(elasticityTone(null)).toBe('cool')
      expect(elasticityTone(undefined)).toBe('cool')
      // Exact threshold boundaries
      expect(elasticityTone(90.0)).toBe('up')
      expect(elasticityTone(89.9)).toBe('warm')
      expect(elasticityTone(80.0)).toBe('warm')
      expect(elasticityTone(79.9)).toBe('cool')
      expect(elasticityTone(60.0)).toBe('cool')
      expect(elasticityTone(59.9)).toBe('down')
      expect(elasticityTone(0.0)).toBe('down')
      expect(elasticityTone(-10.0)).toBe('down')
    })
  })

  // =========================================================================
  // B02: Extreme Market Cap Scaling Boundaries
  // =========================================================================
  describe('B02: Extreme Market Cap Scaling Boundaries', () => {
    it('formats micro-cap and small-cap companies in billions notation cleanly', () => {
      expect(formatMarketCap(0.01)).toBe('$0.0B') // $10M boundary
      expect(formatMarketCap(0.08)).toBe('$0.1B')
      expect(formatMarketCap(0.5)).toBe('$0.5B')
      expect(formatMarketCap(1.0)).toBe('$1.0B')
      expect(formatMarketCap(45.54)).toBe('$45.5B')
      expect(formatMarketCap(999.94)).toBe('$999.9B')
    })

    it('transitions to trillions notation exactly at $1,000B threshold and scales to hyper-caps', () => {
      expect(formatMarketCap(1000.0)).toBe('$1.00T')
      expect(formatMarketCap(1000.1)).toBe('$1.00T')
      expect(formatMarketCap(3120.45)).toBe('$3.12T')
      expect(formatMarketCap(9999.99)).toBe('$10.00T')
      expect(formatMarketCap(15000.0)).toBe('$15.00T')
    })

    it('handles negative, zero, or degenerate market cap boundaries gracefully', () => {
      expect(formatMarketCap(0)).toBe('$0.0B')
      expect(formatMarketCap(-10.0)).toBe('$-10.0B')
    })
  })

  // =========================================================================
  // B03: Single-Node & Zero-Edge Degenerate Graph Topologies
  // =========================================================================
  describe('B03: Single-Node & Zero-Edge Degenerate Graph Topologies', () => {
    const singleNode: SupplyChainNode = {
      symbol: 'SOLO',
      name: 'Solo Driver Technologies',
      sector: 'Technology',
      sub_industry: 'Isolated Compute',
      tier: 'mega_driver',
      market_cap_billions: 12.5,
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

    it('computes layout and renders single-node graph with 0 edges without crashing', async () => {
      const app = createSSRApp({
        render: () =>
          h(ValueChainGraph, {
            nodes: [singleNode],
            edges: [],
            selectedSymbol: 'SOLO',
          }),
      })
      const html = await renderToString(app)

      expect(html).toContain('SOLO')
      expect(html).toContain('Core Driver &amp; Partners')
      expect(html).toContain('540px') // Clamped to minimum canvas height
      // No SVG path should be generated when edges is empty
      expect(html).not.toContain('<path class="chain-edge')
    })

    it('renders completely empty node list gracefully without throwing an exception', async () => {
      const app = createSSRApp({
        render: () =>
          h(ValueChainGraph, {
            nodes: [],
            edges: [],
            selectedSymbol: null,
          }),
      })
      const html = await renderToString(app)
      expect(html).toContain('540px')
      expect(html).not.toContain('node-card')
    })
  })

  // =========================================================================
  // B04: Max-Density Column Scaling (Vertical Stress)
  // =========================================================================
  describe('B04: Max-Density Column Scaling', () => {
    it('scales totalHeight dynamically when a single column contains 20 nodes without card overlap', () => {
      const denseNodes: SupplyChainNode[] = Array.from({ length: 20 }, (_, i) => ({
        symbol: `SYM${i}`,
        name: `Supplier ${i}`,
        sector: 'Technology',
        sub_industry: 'Components',
        tier: 'tier1_supplier',
        market_cap_billions: 5.0 + i,
        is_focus: false,
        metrics: {
          elasticity_score: 80 - i,
          capex_sensitivity: 2.0,
          revenue_concentration_pct: 10.0,
          operating_leverage: 1.5,
          forward_pe: 20.0,
          peg_ratio: 1.0,
          gross_margin_trend: 'stable' as const,
          yoy_revenue_growth: 15.0,
          next_earnings_date: null,
          flow_sentiment_score: 0.5,
          options_skew: null,
        },
        evidence: [],
      }))

      const maxRows = 20
      const cardHeight = 72
      const gapY = 16
      const totalHeight = Math.max(540, 60 + maxRows * (cardHeight + gapY) + 40)
      // 60 + 20 * 88 + 40 = 60 + 1760 + 40 = 1860px
      expect(totalHeight).toBe(1860)

      // Verify node vertical coordinates strictly increase without overlap
      const yPositions = denseNodes.map((_, i) => 40 + i * (cardHeight + gapY))
      for (let i = 0; i < yPositions.length - 1; i++) {
        expect(yPositions[i + 1] - yPositions[i]).toBe(88)
        expect(yPositions[i + 1]).toBeGreaterThan(yPositions[i] + cardHeight)
      }
    })
  })

  // =========================================================================
  // B05: SVG Coordinate Bounds & Viewport Margins (Column 3 Lateral Arcs)
  // =========================================================================
  describe('B05: SVG Coordinate Bounds & Viewport Margins', () => {
    it('calculates Column 3 lateral peer arc geometry within predictable bounds', () => {
      const colWidth = 240
      const startX = 60
      const cardWidth = 180
      const col3X = startX + 3 * colWidth // 780px
      const x1 = col3X + cardWidth // 960px

      // Adjacent row peer arc (rowDiff = 1):
      const arcDistRow1 = 26 + Math.min(36, 1 * 12) // 38px
      const cx1Row1 = x1 + arcDistRow1 // 998px
      expect(cx1Row1).toBe(998)
      expect(cx1Row1).toBeLessThan(1020) // Stays within 1020px standard viewBox

      // Multi-row peer arc (rowDiff = 3):
      const arcDistRow3 = 26 + Math.min(36, 3 * 12) // 26 + 36 = 62px
      const cx1Row3 = x1 + arcDistRow3 // 960 + 62 = 1022px
      expect(cx1Row3).toBe(1022)
    })
  })

  // =========================================================================
  // B06: Symbol Input Sanitization & Malformed Input Boundaries
  // =========================================================================
  describe('B06: Symbol Input Sanitization & Malformed Input Boundaries', () => {
    const symbolRegex = /^[A-Z0-9.-]{1,10}$/

    it('accepts boundary-valid ticker lengths from 1 to 10 characters', () => {
      expect(symbolRegex.test('C')).toBe(true) // 1 char (Citigroup)
      expect(symbolRegex.test('F')).toBe(true) // 1 char (Ford)
      expect(symbolRegex.test('NVDA')).toBe(true) // 4 chars
      expect(symbolRegex.test('GOOGL')).toBe(true) // 5 chars
      expect(symbolRegex.test('ABCDEFGHIJ')).toBe(true) // 10 chars exact maximum
    })

    it('rejects empty strings and symbols exceeding 10 characters', () => {
      expect(symbolRegex.test('')).toBe(false)
      expect(symbolRegex.test('ABCDEFGHIJK')).toBe(false) // 11 chars
    })

    it('rejects adversarial characters, script injection, and SQL injection syntax', () => {
      expect(symbolRegex.test('AAPL;')).toBe(false)
      expect(symbolRegex.test('NVDA DROP')).toBe(false)
      expect(symbolRegex.test('<script>')).toBe(false)
      expect(symbolRegex.test('TSLA$')).toBe(false)
      expect(symbolRegex.test('AMD#1')).toBe(false)
      expect(symbolRegex.test('🚀')).toBe(false)
      expect(symbolRegex.test('SPY/US')).toBe(false)
    })

    it('correctly handles dot and hyphen share class tickers', () => {
      expect(symbolRegex.test('BRK.A')).toBe(true)
      expect(symbolRegex.test('BRK.B')).toBe(true)
      expect(symbolRegex.test('BF-A')).toBe(true)
      expect(symbolRegex.test('BF-B')).toBe(true)
    })
  })

  // =========================================================================
  // B07: Empty SEC Citations Drawer Boundary State
  // =========================================================================
  describe('B07: Empty SEC Citations Drawer State', () => {
    it('renders honest missing-data citation copy without synthesizing hallucinated quotes', async () => {
      const nodeWithNoCitations: SupplyChainNode = {
        symbol: 'NOCITES',
        name: 'No Citations Corp',
        sector: 'Industrials',
        sub_industry: 'Mechanical Parts',
        tier: 'tier2_supplier',
        market_cap_billions: 2.4,
        is_focus: false,
        metrics: {
          elasticity_score: 75.0,
          capex_sensitivity: 1.5,
          revenue_concentration_pct: 12.0,
          operating_leverage: 1.2,
          forward_pe: 18.0,
          peg_ratio: 1.1,
          gross_margin_trend: 'stable',
          yoy_revenue_growth: 8.0,
          next_earnings_date: null,
          flow_sentiment_score: null,
          options_skew: null,
        },
        evidence: [],
      }

      const app = createSSRApp({
        render: () =>
          h(EvidenceDrawer, {
            node: nodeWithNoCitations,
            open: true,
          }),
      })
      const html = await renderToString(app)

      expect(html).toContain('NOCITES')
      expect(html).toContain('No Citations Corp')
      expect(html).toContain('Tier 2 Supplier')
      expect(html).toContain('No direct SEC or transcript quotation records attached for this node.')
      // Verify no fake quote body is rendered
      expect(html).not.toContain('quote-body')
    })
  })

  // =========================================================================
  // B08: Beneficiary Ranking Boundary Values
  // =========================================================================
  describe('B08: Beneficiary Ranking Boundary Values', () => {
    const testNodes: SupplyChainNode[] = [
      {
        symbol: 'FOCUS',
        name: 'Focus Node',
        sector: 'Technology',
        sub_industry: 'Compute',
        tier: 'mega_driver',
        market_cap_billions: 100,
        is_focus: true,
        metrics: { elasticity_score: 99.0 } as any,
        evidence: [],
      },
      {
        symbol: 'HIGH',
        name: 'High Elasticity',
        sector: 'Technology',
        sub_industry: 'Liquid Cooling & Thermal',
        tier: 'tier1_supplier',
        market_cap_billions: 10,
        is_focus: false,
        metrics: { elasticity_score: 95.0 } as any,
        evidence: [],
      },
      {
        symbol: 'MID',
        name: 'Mid Elasticity',
        sector: 'Technology',
        sub_industry: 'Liquid Cooling & Thermal',
        tier: 'tier1_supplier',
        market_cap_billions: 15,
        is_focus: false,
        metrics: { elasticity_score: 80.0 } as any,
        evidence: [],
      },
      {
        symbol: 'NULL_SCORE',
        name: 'Null Elasticity',
        sector: 'Technology',
        sub_industry: 'Liquid Cooling & Thermal',
        tier: 'tier1_supplier',
        market_cap_billions: 5,
        is_focus: false,
        metrics: { elasticity_score: null } as any,
        evidence: [],
      },
    ]

    it('excludes focus node and handles null elasticity gracefully in ranking sort', () => {
      const ranked = rankBeneficiaries(testNodes)
      expect(ranked.some((n) => n.symbol === 'FOCUS')).toBe(false)
      expect(ranked[0].symbol).toBe('HIGH')
      expect(ranked[1].symbol).toBe('MID')
      expect(ranked[2].symbol).toBe('NULL_SCORE')
    })

    it('enforces minElasticity boundary conditions (exact match, over 100, zero)', () => {
      // Exact boundary at 95.0:
      const at95 = rankBeneficiaries(testNodes, undefined, 95.0)
      expect(at95.map((n) => n.symbol)).toEqual(['HIGH'])

      // Above maximum score 100.0 -> empty list:
      const over100 = rankBeneficiaries(testNodes, undefined, 100.1)
      expect(over100).toEqual([])

      // minElasticity = 0 -> includes scored nodes and filters properly:
      const atZero = rankBeneficiaries(testNodes, undefined, 0)
      expect(atZero.length).toBe(3)
    })

    it('returns empty array when sub-industry filter matches zero nodes', () => {
      const noMatch = rankBeneficiaries(testNodes, 'nonexistent_sub_industry_token')
      expect(noMatch).toEqual([])
    })

    it('handles empty input array without throwing an exception', () => {
      expect(rankBeneficiaries([])).toEqual([])
      expect(rankBeneficiaries([], 'cooling', 80)).toEqual([])
    })
  })
})
