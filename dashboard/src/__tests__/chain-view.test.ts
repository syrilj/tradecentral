import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createSSRApp } from 'vue'
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

vi.mock('@/api', async () => {
  const actual = await vi.importActual<typeof import('@/api')>('@/api')
  return {
    ...actual,
    api: {
      ...actual.api,
      supplyChainThemes: vi.fn().mockResolvedValue({
        themes: [
          {
            id: 'ai_datacenter',
            name: 'AI Data Center Infrastructure',
            description: 'Hyperscale clusters and power infrastructure',
            driver_count: 5,
            supplier_count: 12,
            catalysts: [],
          },
        ],
      }),
      supplyChain: vi.fn().mockResolvedValue({
        asof: '2026-09-20T12:00:00Z',
        query: { symbol: 'NVDA', depth: 2, mode: 'dedicated' },
        focal_entity: {
          symbol: 'NVDA',
          name: 'NVIDIA Corporation',
          sector: 'Technology',
          sub_industry: 'Semiconductors',
          tier: 'mega_driver',
          market_cap_billions: 3100,
          metrics: {
            elasticity_score: 99,
            capex_sensitivity: 4.8,
            revenue_concentration_pct: 35,
            operating_leverage: 3.2,
            forward_pe: 38,
            peg_ratio: 1.2,
            gross_margin_trend: 'expanding',
            yoy_revenue_growth: 122,
            next_earnings_date: '2026-11-18',
            flow_sentiment_score: 0.89,
            options_skew: 'heavy_call_sweep',
          },
          evidence: [],
          is_focus: true,
        },
        nodes: [
          {
            symbol: 'NVDA',
            name: 'NVIDIA Corporation',
            sector: 'Technology',
            sub_industry: 'Semiconductors',
            tier: 'mega_driver',
            market_cap_billions: 3100,
            metrics: { elasticity_score: 99 },
            evidence: [],
            is_focus: true,
          },
        ],
        edges: [
          {
            id: 'tsm_nvda',
            source: 'TSM',
            target: 'NVDA',
            relationship: 'supplies_to',
            strength: 0.95,
            supply_category: 'Foundry & CoWoS',
            evidence_count: 3,
          },
        ],
        thematic_summary: {
          id: 'ai_datacenter',
          theme_name: 'AI Data Center Infrastructure',
          narrative_lead: 'Hyperscale CapEx accelerating',
          catalysts: [],
          connected_value_chains: [],
        },
        thematic_bridges: [],
      }),
      search: vi.fn().mockResolvedValue([
        {
          symbol: 'UBER',
          name: 'Uber Technologies Inc.',
          category: 'Mobility & Delivery',
          tier: 'core',
        },
      ]),
    },
  }
})

import ChainView from '@/views/ChainView.vue'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function source(path: string): string {
  return readFileSync(join(root, path), 'utf8')
}

describe('Supply Chain & Thematic Beneficiaries Workspace', () => {
  const chainView = source('views/ChainView.vue')
  const banner = source('components/ThematicBanner.vue')
  const graph = source('components/ValueChainGraph.vue')
  const table = source('components/BeneficiaryTable.vue')
  const drawer = source('components/EvidenceDrawer.vue')
  const routerSrc = source('router.ts')
  const appSrc = source('App.vue')

  let originalWindow: unknown
  let originalDocument: unknown

  beforeEach(() => {
    originalWindow = (globalThis as Record<string, unknown>).window
    originalDocument = (globalThis as Record<string, unknown>).document

    ;(globalThis as Record<string, unknown>).window = {
      setInterval: (fn: (...args: unknown[]) => void, ms: number) =>
        setInterval(fn, ms) as unknown as number,
      clearInterval: (id: number) => clearInterval(id),
      setTimeout: (fn: (...args: unknown[]) => void, ms: number) =>
        setTimeout(fn, ms) as unknown as number,
      clearTimeout: (id: number) => clearTimeout(id),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }
    ;(globalThis as Record<string, unknown>).document = {
      visibilityState: 'visible',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }
  })

  afterEach(() => {
    ;(globalThis as Record<string, unknown>).window = originalWindow
    ;(globalThis as Record<string, unknown>).document = originalDocument
  })

  it('registers /chain route and primary navigation tab', () => {
    expect(routerSrc).toMatch(/path:\s*['"]\/chain['"]/)
    expect(routerSrc).toMatch(/name:\s*['"]chain['"]/)
    expect(appSrc).toMatch(/name:\s*['"]chain['"]/)
    expect(appSrc).toMatch(/title:\s*['"]Chain['"]/)
  })

  it('ChainView connects components and API resources', () => {
    expect(chainView).toContain('ThematicBanner')
    expect(chainView).toContain('ValueChainGraph')
    expect(chainView).toContain('BeneficiaryTable')
    expect(chainView).toContain('EvidenceDrawer')
    expect(chainView).toMatch(/api\.supplyChain/)
    expect(chainView).toMatch(/api\.supplyChainThemes/)
    expect(chainView).toContain('mode-toggle-group')
    expect(chainView).toContain('Dedicated Chain')
    expect(chainView).toContain('Thematic Intertwine')
    expect(chainView).toContain('thematic-bridges-strip')
  })

  it('ThematicBanner displays narrative and timeline', () => {
    expect(banner).toContain('CAPEX & DEMAND CASCADE')
    expect(banner).toContain('Upcoming Catalyst Milestones')
    expect(banner).toContain('select-theme')
    expect(banner).toContain('select-ticker')
  })

  it('ValueChainGraph implements multi-tier deterministic SVG layout', () => {
    expect(graph).toContain('Tier 2 Suppliers')
    expect(graph).toContain('Tier 1 Suppliers')
    expect(graph).toContain('Core Driver & Partners')
    expect(graph).toContain('Downstream & Customers')
    expect(graph).toContain('chain-edge')
    expect(graph).toContain('node-card')
    expect(graph).toContain('arrow-supply')
    expect(graph).toContain('arrow-demand')
    expect(graph).toContain('relationship-legend')
    expect(graph).toContain('floating-edge-pill')
  })

  it('BeneficiaryTable provides filtering and elasticity ranking', () => {
    expect(table).toContain('ELASTICITY SCORE')
    expect(table).toContain('CAPEX SENS.')
    expect(table).toContain('REV CONC. %')
    expect(table).toContain('FWD P/E')
    expect(table).toContain('CITATIONS')
    expect(table).toContain('Optics & Lasers')
    expect(table).toContain('Liquid Cooling')
  })

  it('EvidenceDrawer displays verbatim transcript quotes and SEC citations', () => {
    expect(drawer).toContain('VERBATIM TRANSCRIPT & FILING CITATIONS')
    expect(drawer).toContain('ELASTICITY SCORE')
    expect(drawer).toContain('CAPEX SENSITIVITY')
    expect(drawer).toContain('quote-body')
  })

  // =========================================================================
  // Milestone 3: Autocomplete & Keyboard Navigation (GAP-03)
  // =========================================================================
  describe('Milestone 3: Symbol Search Bar Autocomplete (GAP-03)', () => {
    it('implements ARIA combobox pattern and keyboard navigation attributes on search input', () => {
      expect(chainView).toContain('role="combobox"')
      expect(chainView).toContain('aria-autocomplete="list"')
      expect(chainView).toContain(':aria-expanded="showSuggestions && suggestions.length > 0"')
      expect(chainView).toContain('aria-controls="suggestions-list"')
      expect(chainView).toContain('aria-label="Search equity symbol"')
      expect(chainView).toContain(':aria-activedescendant')
    })

    it('renders autocomplete suggestions dropdown listbox with accessible options', () => {
      expect(chainView).toContain('id="suggestions-list"')
      expect(chainView).toContain('role="listbox"')
      expect(chainView).toContain('aria-label="Symbol suggestions"')
      expect(chainView).toContain('role="option"')
      expect(chainView).toContain(':aria-selected="highlightedIndex === idx"')
      expect(chainView).toContain('class="suggestion-item"')
      expect(chainView).toContain('sugg-symbol')
      expect(chainView).toContain('sugg-name')
      expect(chainView).toContain('sugg-badge')
    })

    it('distinguishes curated ecosystem leaders from algorithmic discovery candidates', () => {
      expect(chainView).toContain('Curated Ecosystem Leader')
      expect(chainView).toContain('Algorithmic Discovery')
      expect(chainView).toContain('badge-curated')
      expect(chainView).toContain('badge-discovery')
    })

    it('handles keyboard navigation (ArrowDown, ArrowUp, Enter, Escape) in onSearchKeydown', () => {
      expect(chainView).toContain('onSearchKeydown')
      expect(chainView).toContain("e.key === 'ArrowDown'")
      expect(chainView).toContain("e.key === 'ArrowUp'")
      expect(chainView).toContain("e.key === 'Enter'")
      expect(chainView).toContain("e.key === 'Escape'")
    })
  })

  // =========================================================================
  // Milestone 3: 4-Stage Progressive Loading Stepper (GAP-01)
  // =========================================================================
  describe('Milestone 3: Multi-Stage Progressive Loading Stepper (GAP-01)', () => {
    it('defines the 4 required progressive loading stages', () => {
      expect(chainView).toContain('Resolving symbol & sector taxonomy')
      expect(chainView).toContain('Discovering multi-tier suppliers & customers')
      expect(chainView).toContain('Computing elasticity & CapEx exposure')
      expect(chainView).toContain('Compiling topology & rendering graph')
    })

    it('renders loading stepper panel with accessible status role and live region', () => {
      expect(chainView).toContain('class="loading-stepper-panel"')
      expect(chainView).toContain('data-test="loading-stepper"')
      expect(chainView).toContain('role="status"')
      expect(chainView).toContain('aria-live="polite"')
      expect(chainView).toContain('stepper-progress-bar')
      expect(chainView).toContain('telemetry-elapsed')
      expect(chainView).toContain('telemetry-pct')
    })

    it('tracks progressive stage advancement and telemetry', () => {
      expect(chainView).toContain('startLoadingStages')
      expect(chainView).toContain('completeLoadingStages')
      expect(chainView).toContain('failLoadingStages')
      expect(chainView).toContain('elapsedSeconds')
      expect(chainView).toContain('loadingProgress')
      expect(chainView).toContain('stageBadgeText')
    })
  })

  // =========================================================================
  // Milestone 3: Resilient Error Handling (GAP-02)
  // =========================================================================
  describe('Milestone 3: Resilient Error Handling (GAP-02)', () => {
    it('decouples error banner display from !payload to prevent silent error swallowing', () => {
      // Must NOT contain old pattern: v-if="chainResource.error.value && !payload"
      expect(chainView).not.toMatch(/v-if="chainResource\.error\.value\s*&&\s*!payload"/)
      expect(chainView).toContain('v-if="activeError"')
      expect(chainView).toContain('data-test="error-banner"')
      expect(chainView).toContain('role="alert"')
    })

    it('renders retry and dismiss action buttons in error banner', () => {
      expect(chainView).toContain('data-test="retry-btn"')
      expect(chainView).toContain('data-test="dismiss-btn"')
      expect(chainView).toContain('@click="retryFetch"')
      expect(chainView).toContain('@click="dismissError"')
    })
  })

  // =========================================================================
  // Milestone 3: Evidence Drawer Incident Edge Wiring
  // =========================================================================
  describe('Milestone 3: Evidence Drawer Incident Edge Wiring', () => {
    it('passes :edges and :focal-node to EvidenceDrawer component', () => {
      expect(chainView).toMatch(/:edges="payload\?\.edges\s*\|\|\s*\[\]"/)
      expect(chainView).toMatch(/:focal-node="payload\?\.focal_entity\s*\|\|\s*null"/)
    })
  })

  // =========================================================================
  // SSR Mount Validation
  // =========================================================================
  describe('Milestone 3: SSR Component Render', () => {
    it('mounts ChainView component cleanly via SSR and renders controls and sections', async () => {
      const app = createSSRApp(ChainView)
      const html = await renderToString(app)

      expect(html).toContain('SUPPLY CHAIN &amp; VALUE ECOSYSTEMS')
      expect(html).toContain('Dedicated Chain')
      expect(html).toContain('Thematic Intertwine')
      expect(html).toContain('role="combobox"')
      expect(html).toContain('aria-autocomplete="list"')
      expect(html).toContain('aria-label="Search equity symbol"')
      expect(html).toContain('VALUE CHAIN TOPOLOGY')
      expect(html).toContain('BENEFICIARY ELASTICITY &amp; REVENUE PROPAGATION')
    })
  })
})
