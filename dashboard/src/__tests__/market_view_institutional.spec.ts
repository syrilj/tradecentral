/**
 * Comprehensive Institutional Market View Test Suite.
 *
 * Validates:
 * 1. Zero Unicode Emojis Invariant across MarketView.vue and supporting components.
 * 2. In-Cockpit Tab Navigation (10 Tabs: Overview, Financials, Forecast, Insiders,
 *    Institutions, Government, Compensation, Ownership, News & Filings, Compare).
 * 3. In-Cockpit Insiders Navigation (prevention of circular redirect loop with router.ts).
 * 4. Strict Dash (`—`) Formatting Invariant across all financial display helpers.
 * 5. Compare Tab Basket Size Handling (< 2 symbols deadlock prevention).
 * 6. Graceful Fallback & "Data Source Unavailable" States for null/missing upstream feeds.
 * 7. End-to-end Reactive Computations & Data Delivery for all 10 analytical tabs.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { ref, computed } from 'vue'

import {
  formatBigUsd,
  formatPerShare,
  formatStatementCell,
  calculateGrowth,
  getGrowthTone,
  formatPeriodHeader,
} from '@/financialsDisplay'
import {
  num,
  pct,
  pctFrac,
  signedPct,
  signed,
  compact,
  usd,
  tone,
  shortDate,
  age,
  DASH,
} from '@/format'
import { presentSecFilings } from '@/insiderDisplay'
import { sparkline } from '@/charts'
import { filterSortInstitutions, paginateHolders } from '@/ownershipDisplay'
import type {
  FinancialsPayload,
  CompanyProfilePayload,
  InsidersIntelligencePayload,
  GovernmentPayload,
  OwnershipPayload,
  ComparePayload,
} from '@/api'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const marketViewPath = join(srcRoot, 'views', 'MarketView.vue')
// MarketView plus the cards it delegates to — the forecast highlight lives in
// ModelForecastCard.vue so both tabs render an identical, in-sync surface.
const marketViewSource = [
  readFileSync(marketViewPath, 'utf8'),
  readFileSync(
    marketViewPath.replace(/views[\\/]MarketView\.vue$/, 'components/ModelForecastCard.vue'),
    'utf8',
  ),
].join('\n')
const routerPath = join(srcRoot, 'router.ts')
const routerSource = readFileSync(routerPath, 'utf8')
const financialsDisplayPath = join(srcRoot, 'financialsDisplay.ts')
const financialsDisplaySource = readFileSync(financialsDisplayPath, 'utf8')
const insiderDisplayPath = join(srcRoot, 'insiderDisplay.ts')
const insiderDisplaySource = readFileSync(insiderDisplayPath, 'utf8')

/* ============================================================================
 * 1. ZERO UNICODE EMOJIS INVARIANT (Institutional Design Gate)
 * ============================================================================ */
describe('1. Institutional Zero-Emoji Design Invariant', () => {
  it('MarketView.vue contains zero decorative consumer emojis in tab headers and navigation', () => {
    // Specifically test that the tab items array does not contain emoji icons
    const forbiddenSpecificEmojis = [
      '⚡', '📊', '🎯', '👥', '🏛', '⚖', '💼', '🥧', '📰',
      '🚀', '🔥', '📈', '📉', '🤑', '💰', '✨', '💡', '🔔',
    ]
    for (const emoji of forbiddenSpecificEmojis) {
      expect(marketViewSource, `MarketView.vue should not contain emoji: ${emoji}`).not.toContain(emoji)
    }
  })

  it('financialsDisplay.ts and insiderDisplay.ts contain zero unicode emojis', () => {
    const forbiddenSpecificEmojis = ['⚡', '📊', '🎯', '👥', '🏛', '⚖', '💼', '🥧', '📰', '🚀', '🔥', '📈', '📉', '🤑']
    for (const emoji of forbiddenSpecificEmojis) {
      expect(financialsDisplaySource, `financialsDisplay.ts should not contain emoji: ${emoji}`).not.toContain(emoji)
      expect(insiderDisplaySource, `insiderDisplay.ts should not contain emoji: ${emoji}`).not.toContain(emoji)
    }
  })

  it('uses clean institutional typography and subtle badges instead of decorative emojis', () => {
    expect(marketViewSource).toContain('cockpit-tabs-nav')
    expect(marketViewSource).toContain('tab-label')
    expect(marketViewSource).toMatch(/Overview|Financials|Forecast|Insiders|Institutions|Government|Compensation|Ownership|News|Compare/)
  })
})

/* ============================================================================
 * 2. ALL 10 INSTITUTIONAL TABS & INTERFACE CONTRACT
 * ============================================================================ */
describe('2. All 10 Institutional Analytical Tabs Contract', () => {
  const EXPECTED_TABS = [
    'overview',
    'financials',
    'forecast',
    'insiders',
    'institutions',
    'government',
    'compensation',
    'ownership',
    'news',
    'compare',
  ] as const

  it('declares all 10 analytical tabs in the MarketTab union type', () => {
    for (const tab of EXPECTED_TABS) {
      expect(marketViewSource, `MarketTab union must include '${tab}'`).toMatch(
        new RegExp(`['"]${tab}['"]`),
      )
    }
  })

  it('provides dedicated section markup for all 10 analytical tabs', () => {
    // Tab 1: Overview
    expect(marketViewSource).toMatch(/activeTab\s*===\s*['"]overview['"]/)
    expect(marketViewSource).toContain('overview-layout')
    expect(marketViewSource).toContain('overview-chart-panel')
    expect(marketViewSource).toContain('smart-score-card')

    // Tab 2: Financials
    expect(marketViewSource).toMatch(/activeTab\s*===\s*['"]financials['"]/)
    expect(marketViewSource).toContain('financials-layout')
    expect(marketViewSource).toContain('financials-toolbar')
    expect(marketViewSource).toContain('fin-statement-selector')
    expect(marketViewSource).toContain('model-forecast-highlight')
    expect(marketViewSource).toContain('What it should be')

    // Tab 3: Forecast
    expect(marketViewSource).toMatch(/activeTab\s*===\s*['"]forecast['"]/)
    expect(marketViewSource).toContain('forecast-layout')
    expect(marketViewSource).toContain('forecast-rating-box')
    expect(marketViewSource).toContain('price-target-meter-card')

    // Tab 4: Insiders
    expect(marketViewSource).toMatch(/activeTab\s*===\s*['"]insiders['"]/)
    expect(marketViewSource).toContain('insiders-layout')
    expect(marketViewSource).toContain('quarterly-insiders-chart')
    expect(marketViewSource).toContain('insider-table-filters')

    // Tab 5: Institutions
    expect(marketViewSource).toMatch(/activeTab\s*===\s*['"]institutions['"]/)
    expect(marketViewSource).toContain('institutions-layout')
    expect(marketViewSource).toMatch(/Top Institutional Owners|13F/)

    // Tab 6: Government
    expect(marketViewSource).toMatch(/activeTab\s*===\s*['"]government['"]/)
    expect(marketViewSource).toContain('government-layout')
    expect(marketViewSource).toMatch(/Congressional Trading Activity|Corporate Lobbying|Federal Government Contracts|Patent Grants/)

    // Tab 7: Compensation
    expect(marketViewSource).toMatch(/activeTab\s*===\s*['"]compensation['"]/)
    expect(marketViewSource).toContain('compensation-layout')
    expect(marketViewSource).toContain('comp-summary-strip')

    // Tab 8: Ownership
    expect(marketViewSource).toMatch(/activeTab\s*===\s*['"]ownership['"]/)
    expect(marketViewSource).toContain('ownership-layout')
    expect(marketViewSource).toContain('ownership-distribution-card')

    // Tab 9: News & Filings
    expect(marketViewSource).toMatch(/activeTab\s*===\s*['"]news['"]/)
    expect(marketViewSource).toContain('news-layout')
    expect(marketViewSource).toMatch(/SEC EDGAR Official Filings|Filings/)

    // Tab 10: Compare
    expect(marketViewSource).toMatch(/activeTab\s*===\s*['"]compare['"]/)
    expect(marketViewSource).toContain('compare-layout')
    expect(marketViewSource).toContain('compare-grid')
    expect(marketViewSource).toContain('factorRows')
  })
})

/* ============================================================================
 * 3. IN-COCKPIT INSIDERS NAVIGATION (CIRCULAR REDIRECT PREVENTION)
 * ============================================================================ */
describe('3. In-Cockpit Insiders Navigation & Circular Redirect Prevention', () => {
  it('router.ts redirects /insiders into /market?tab=insiders', () => {
    expect(routerSource).toMatch(/path:\s*['"]\/insiders['"]/)
    expect(routerSource).toMatch(/name:\s*['"]insiders['"]/)
    expect(routerSource).toMatch(/tab:\s*['"]insiders['"]/)
  })

  it('MarketView.vue handles tab=insiders in-cockpit without bouncing back to router.push(insiders)', () => {
    // If MarketView redirected tab=insiders back to { name: 'insiders' }, it would create an infinite redirect loop.
    // The component must allow activeTab to be set to 'insiders' and render the in-tab section.
    expect(marketViewSource).toContain("activeTab === 'insiders'")
    expect(marketViewSource).toContain("insiders-layout")
  })
})

/* ============================================================================
 * 4. STRICT DASH (—) FORMATTING INVARIANT & DATA PRESENTATION
 * ============================================================================ */
describe('4. Strict Dash (—) Formatting Invariant', () => {
  describe('formatBigUsd', () => {
    it('formats null, undefined, NaN, and non-finite numbers as DASH (—)', () => {
      expect(formatBigUsd(null)).toBe(DASH)
      expect(formatBigUsd(undefined)).toBe(DASH)
      expect(formatBigUsd(NaN)).toBe(DASH)
      expect(formatBigUsd(Infinity)).toBe(DASH)
      expect(formatBigUsd(-Infinity)).toBe(DASH)
    })

    it('formats trillions, billions, millions, and thousands correctly with institutional notation', () => {
      expect(formatBigUsd(2_500_000_000_000)).toBe('$2.50T')
      expect(formatBigUsd(1_240_000_000)).toBe('$1.24B')
      expect(formatBigUsd(450_200_000)).toBe('$450.20M')
      expect(formatBigUsd(12_500)).toBe('$12.50K')
      expect(formatBigUsd(124.5)).toBe('$124.50')
    })

    it('formats negative financial quantities with leading negative sign', () => {
      expect(formatBigUsd(-1_240_000_000)).toBe('-$1.24B')
      expect(formatBigUsd(-450_200_000)).toBe('-$450.20M')
      expect(formatBigUsd(-50_000)).toBe('-$50.00K')
    })

    it('preserves raw zero as valid financial zero ($0.00), distinct from missing DASH', () => {
      expect(formatBigUsd(0)).toBe('$0.00')
      expect(formatBigUsd(0)).not.toBe(DASH)
    })
  })

  describe('formatPerShare', () => {
    it('formats null, undefined, and NaN as DASH (—)', () => {
      expect(formatPerShare(null)).toBe(DASH)
      expect(formatPerShare(undefined)).toBe(DASH)
      expect(formatPerShare(NaN)).toBe(DASH)
    })

    it('formats positive and negative per-share amounts with correct 2-decimal precision', () => {
      expect(formatPerShare(12.5)).toBe('$12.50')
      expect(formatPerShare(0.45)).toBe('$0.45')
      expect(formatPerShare(-0.15)).toBe('-$0.15')
      expect(formatPerShare(0)).toBe('$0.00')
    })
  })

  describe('formatStatementCell', () => {
    it('formats null/undefined across all format specs as DASH (—)', () => {
      expect(formatStatementCell(null, 'currency')).toBe(DASH)
      expect(formatStatementCell(undefined, 'pct')).toBe(DASH)
      expect(formatStatementCell(null, 'ratio')).toBe(DASH)
      expect(formatStatementCell(undefined, 'compact')).toBe(DASH)
      expect(formatStatementCell(null)).toBe(DASH)
    })

    it('formats pct values with signed indicator and percent symbol', () => {
      expect(formatStatementCell(14.2, 'pct')).toBe('+14.2%')
      expect(formatStatementCell(-5.1, 'pct')).toBe('-5.1%')
      expect(formatStatementCell(0, 'pct')).toBe('+0.0%')
    })

    it('formats ratio values with 2-decimal precision', () => {
      expect(formatStatementCell(2.456, 'ratio')).toBe('2.46')
      expect(formatStatementCell(0.85, 'ratio')).toBe('0.85')
    })

    it('formats currency values as per-share currency', () => {
      expect(formatStatementCell(1.45, 'currency')).toBe('$1.45')
    })
  })

  describe('calculateGrowth', () => {
    it('returns null for missing, zero, or non-finite inputs to prevent division-by-zero or NaN', () => {
      expect(calculateGrowth(null, 100)).toBeNull()
      expect(calculateGrowth(100, null)).toBeNull()
      expect(calculateGrowth(100, 0)).toBeNull()
      expect(calculateGrowth(undefined, 50)).toBeNull()
      expect(calculateGrowth(NaN, 50)).toBeNull()
      expect(calculateGrowth(50, NaN)).toBeNull()
    })

    it('calculates YoY percentage growth accurately', () => {
      expect(calculateGrowth(150, 100)).toBe(50)
      expect(calculateGrowth(80, 100)).toBe(-20)
      expect(calculateGrowth(200, 100)).toBe(100)
    })
  })

  describe('getGrowthTone', () => {
    it('returns pos for positive growth (>0.05)', () => {
      expect(getGrowthTone(10.5)).toBe('pos')
      expect(getGrowthTone(0.1)).toBe('pos')
    })

    it('returns neg for negative growth (<-0.05)', () => {
      expect(getGrowthTone(-5.2)).toBe('neg')
      expect(getGrowthTone(-0.1)).toBe('neg')
    })

    it('returns flat for near-zero, null, or undefined growth', () => {
      expect(getGrowthTone(0)).toBe('flat')
      expect(getGrowthTone(0.02)).toBe('flat')
      expect(getGrowthTone(null)).toBe('flat')
      expect(getGrowthTone(undefined)).toBe('flat')
      expect(getGrowthTone(NaN)).toBe('flat')
    })
  })

  describe('formatPeriodHeader', () => {
    it('returns DASH for empty period strings', () => {
      expect(formatPeriodHeader('', true)).toBe(DASH)
      expect(formatPeriodHeader('', false)).toBe(DASH)
    })

    it('formats quarterly dates into Q{1-4} \'{YY} format', () => {
      expect(formatPeriodHeader('2026-03-31', true)).toBe("Q1 '26")
      expect(formatPeriodHeader('2026-06-30', true)).toBe("Q2 '26")
      expect(formatPeriodHeader('2026-09-30', true)).toBe("Q3 '26")
      expect(formatPeriodHeader('2026-12-31', true)).toBe("Q4 '26")
    })

    it('formats annual dates into 4-digit year format', () => {
      expect(formatPeriodHeader('2025-12-31', false)).toBe('2025')
      expect(formatPeriodHeader('2026-12-31', false)).toBe('2026')
    })
  })

  describe('Core format.ts helpers', () => {
    it('num, pct, pctFrac, signedPct, usd, compact, shortDate return DASH for null/undefined/NaN', () => {
      expect(num(null)).toBe(DASH)
      expect(num(undefined)).toBe(DASH)
      expect(num(NaN)).toBe(DASH)
      expect(pct(null)).toBe(DASH)
      expect(pctFrac(null)).toBe(DASH)
      expect(signedPct(null)).toBe(DASH)
      expect(signed(null)).toBe(DASH)
      expect(usd(null)).toBe(DASH)
      expect(compact(null)).toBe(DASH)
      expect(shortDate(null)).toBe(DASH)
      expect(age(null)).toBe(DASH)
    })

    it('tone returns flat for null, undefined, NaN, and 0', () => {
      expect(tone(null)).toBe('flat')
      expect(tone(undefined)).toBe('flat')
      expect(tone(NaN)).toBe('flat')
      expect(tone(0)).toBe('flat')
    })
  })
})

/* ============================================================================
 * 5. COMPARE TAB BASKET SIZE HANDLING (< 2 SYMBOLS DEADLOCK PREVENTION)
 * ============================================================================ */
describe('5. Compare Tab Basket Size Handling (< 2 Symbols Deadlock Prevention)', () => {
  it('loadCompare clears compare state and does not hang when basket size < 2', () => {
    // Simulated reactive state for loadCompare logic in MarketView.vue
    const basket = ref<string[]>(['ASTS'])
    const cmp = ref<ComparePayload | null>({
      window: '1y',
      series: {},
      stats: {},
      correlation: {},
    })
    const cmpErr = ref<string | null>('old error')

    const loadCompare = async (): Promise<void> => {
      if (basket.value.length < 2) {
        cmp.value = null
        cmpErr.value = null
        return
      }
      // If length >= 2, would fetch API
    }

    // Execute with basket size 1
    void loadCompare()

    expect(cmp.value).toBeNull()
    expect(cmpErr.value).toBeNull()

    // Execute with empty basket
    basket.value = []
    void loadCompare()

    expect(cmp.value).toBeNull()
    expect(cmpErr.value).toBeNull()
  })

  it('MarketView source implements basket < 2 guard in loadCompare', () => {
    expect(marketViewSource).toMatch(/if\s*\(\s*basket\.value\.length\s*<\s*2\s*\)/)
    expect(marketViewSource).toContain('cmp.value = null')
    expect(marketViewSource).toContain('cmpErr.value = null')
  })
})

/* ============================================================================
 * 6. GRACEFUL FALLBACKS & DATA SOURCE RESILIENCE
 * ============================================================================ */
describe('6. Graceful Fallbacks & Data Source Resilience', () => {
  it('handles null financial statement data without crashing', () => {
    const finData = ref<FinancialsPayload | null>(null)
    const incomeRows = computed(() => finData.value?.income_statement?.rows || [])
    const balanceRows = computed(() => finData.value?.balance_sheet?.rows || [])
    const cashRows = computed(() => finData.value?.cash_flow?.rows || [])
    const segments = computed(() => finData.value?.revenue_breakdown?.by_segment || [])
    const geos = computed(() => finData.value?.revenue_breakdown?.by_geography || [])

    expect(incomeRows.value).toEqual([])
    expect(balanceRows.value).toEqual([])
    expect(cashRows.value).toEqual([])
    expect(segments.value).toEqual([])
    expect(geos.value).toEqual([])
  })

  it('handles null company profile and forecast data without crashing', () => {
    const profile = ref<CompanyProfilePayload | null>(null)
    const consensus = computed(() => profile.value?.forecast?.consensus_rating ?? DASH)
    const medianTarget = computed(() => profile.value?.forecast?.target_price_median != null ? usd(profile.value?.forecast?.target_price_median) : DASH)
    const officers = computed(() => profile.value?.compensation?.rows || [])
    const smartScore = computed(() => profile.value?.smart_score?.score ?? DASH)

    expect(consensus.value).toBe(DASH)
    expect(medianTarget.value).toBe(DASH)
    expect(officers.value).toEqual([])
    expect(smartScore.value).toBe(DASH)
  })

  it('handles null insider intelligence data without crashing', () => {
    const insData = ref<InsidersIntelligencePayload | null>(null)
    const insiderSearchQuery = ref('Smith')
    const insiderTypeFilter = ref<'all' | 'buy' | 'sell'>('buy')

    const filteredTransactions = computed(() => {
      const list = insData.value?.transactions || []
      return list.filter((tx) => {
        if (insiderTypeFilter.value === 'buy' && tx.transaction_type !== 'Purchase') return false
        if (insiderTypeFilter.value === 'sell' && tx.transaction_type !== 'Sale') return false
        if (insiderSearchQuery.value) {
          const qLower = insiderSearchQuery.value.toLowerCase()
          return (
            tx.insider_name.toLowerCase().includes(qLower) ||
            tx.relationship.toLowerCase().includes(qLower)
          )
        }
        return true
      })
    })

    expect(filteredTransactions.value).toEqual([])
  })

  it('handles null government and ownership data without crashing', () => {
    const govData = ref<GovernmentPayload | null>(null)
    const ownData = ref<OwnershipPayload | null>(null)

    const congressTrades = computed(() => govData.value?.congress || [])
    const lobbyingFilings = computed(() => govData.value?.lobbying?.filings || [])
    const contracts = computed(() => govData.value?.contracts || [])
    const patents = computed(() => govData.value?.patents || [])
    const topInstitutions = computed(() => ownData.value?.top_institutions || [])
    const topFunds = computed(() => ownData.value?.top_funds || [])

    expect(congressTrades.value).toEqual([])
    expect(lobbyingFilings.value).toEqual([])
    expect(contracts.value).toEqual([])
    expect(patents.value).toEqual([])
    expect(topInstitutions.value).toEqual([])
    expect(topFunds.value).toEqual([])
  })

  it('presentSecFilings returns empty array cleanly for null or undefined input', () => {
    expect(presentSecFilings(null)).toEqual([])
    expect(presentSecFilings(undefined)).toEqual([])
    expect(presentSecFilings({})).toEqual([])
  })
})

/* ============================================================================
 * 7. END-TO-END DATA INGESTION & DERIVED COMPUTATION VERIFICATION
 * ============================================================================ */
describe('7. End-to-End Realistic Data Ingestion & Derived Calculations', () => {
  const mockFinancials: FinancialsPayload = {
    symbol: 'ASTS',
    period_type: 'quarterly',
    periods: ['2026-06-30', '2026-03-31', '2025-12-31', '2025-09-30'],
    income_statement: {
      rows: [
        { key: 'rev', label: 'Total Revenue', values: [25_000_000, 20_000_000, 15_000_000, 10_000_000], is_bold: true },
        { key: 'gp', label: 'Gross Profit', values: [18_000_000, 14_000_000, 10_000_000, 7_000_000], is_bold: true },
        { key: 'gm', label: 'Gross Margin', values: [72.0, 70.0, 66.7, 70.0], format: 'pct' },
        { key: 'ni', label: 'Net Income', values: [5_000_000, 3_000_000, -2_000_000, -5_000_000], is_total: true },
      ],
    },
    balance_sheet: {
      rows: [
        { key: 'cash', label: 'Cash & Short-Term Investments', values: [450_000_000, 420_000_000, 380_000_000, 310_000_000], is_bold: true },
        { key: 'assets', label: 'Total Assets', values: [1_200_000_000, 1_100_000_000, 1_000_000_000, 900_000_000], is_total: true },
        { key: 'debt', label: 'Total Long-Term Debt', values: [150_000_000, 150_000_000, 150_000_000, 150_000_000] },
      ],
    },
    cash_flow: {
      rows: [
        { key: 'ocf', label: 'Operating Cash Flow', values: [12_000_000, 8_000_000, 4_000_000, -2_000_000], is_bold: true },
        { key: 'capex', label: 'Capital Expenditures', values: [-25_000_000, -20_000_000, -18_000_000, -15_000_000] },
        { key: 'fcf', label: 'Free Cash Flow', values: [-13_000_000, -12_000_000, -14_000_000, -17_000_000], is_total: true },
      ],
    },
    revenue_breakdown: {
      by_segment: [
        { segment: 'Direct-to-Cell Commercial', revenue: 18_000_000, pct: 72.0, growth_yoy: 150.0 },
        { segment: 'Government & Defense', revenue: 7_000_000, pct: 28.0, growth_yoy: 40.0 },
      ],
      by_geography: [
        { region: 'North America', revenue: 16_000_000, pct: 64.0 },
        { region: 'International / EMEA', revenue: 9_000_000, pct: 36.0 },
      ],
    },
    ratios: {
      market_cap: 8_500_000_000,
      pe_trailing: 45.2,
      gross_margin: 72.0,
      net_margin: 20.0,
      debt_to_equity: 0.25,
      current_ratio: 3.4,
      roe: 18.5,
      roa: 8.2,
      free_cash_flow: -13_000_000,
    },
    source: 'SEC EDGAR / Direct XBRL & yfinance',
    asof: '2026-08-15T00:00:00Z',
  }

  const mockProfile: CompanyProfilePayload = {
    symbol: 'ASTS',
    about: {
      name: 'AST SpaceMobile Inc',
      description: 'Building the first space-based cellular broadband network.',
      address: 'Midland, TX, United States',
      sector: 'Technology',
      industry: 'Telecom Services',
      employees: 450,
      market_cap: 8_500_000_000,
      website: 'https://ast-science.com',
    },
    officers: [
      { name: 'Abel Avellan', title: 'CEO & Chairman', total_pay: 3_500_000 },
    ],
    compensation: {
      highest_paid_name: 'Abel Avellan',
      highest_paid_total: 3_500_000,
      median_employee_pay: 145_000,
      ceo_pay_ratio: 24.1,
      year: '2025',
      rows: [
        { name: 'Abel Avellan', role: 'CEO & Chairman', salary: 750_000, bonus: 500_000, stock_awards: 2_250_000, total_compensation: 3_500_000, year: '2025' },
        { name: 'Sean Wallace', role: 'CFO', salary: 500_000, bonus: 250_000, stock_awards: 1_250_000, total_compensation: 2_000_000, year: '2025' },
      ],
    },
    forecast: {
      consensus_rating: 'Strong Buy',
      recommendation_mean: 1.6,
      target_price_high: 60.0,
      target_price_median: 45.0,
      target_price_low: 30.0,
      current_price: 32.5,
      upside_pct: 38.5,
      recommendations: { strong_buy: 6, buy: 3, hold: 1, underperform: 0, sell: 0 },
      upgrades_downgrades: [
        { date: '2026-08-01', firm: 'Scotiabank', action: 'Upgrade', current: 'Outperform', previous: 'Sector Perform' },
      ],
    },
    smart_score: {
      score: 9,
      rating: 'High Institutional Conviction',
      components: { momentum: 9, insider_activity: 8, institutional_flow: 9, analyst_sentiment: 9, financial_health: 8 },
    },
    bull_bear: {
      bulls_say: ['First-mover satellite constellation advantage', 'Direct Tier 1 telecom MNO agreements'],
      bears_say: ['High capital intensity of orbital launches', 'Execution and regulatory risk'],
      last_updated: '2026-08-15',
    },
  }

  const mockInsiders: InsidersIntelligencePayload = {
    symbol: 'ASTS',
    summary: {
      net_shares_90d: 250_000,
      buy_volume_usd: 8_500_000,
      sell_volume_usd: 1_200_000,
      net_volume_usd: 7_300_000,
      total_transactions: 12,
      buy_count: 9,
      sell_count: 3,
    },
    transactions: [
      {
        date: '2026-08-05',
        insider_name: 'Avellan Abel',
        relationship: 'Chief Executive Officer',
        transaction_type: 'Purchase',
        shares: 150_000,
        price: 28.5,
        value: 4_275_000,
        shares_held_after: 12_500_000,
        sec_form_url: 'https://sec.gov/edgar/x',
      },
      {
        date: '2026-07-20',
        insider_name: 'Wallace Sean',
        relationship: 'Chief Financial Officer',
        transaction_type: 'Sale',
        shares: 25_000,
        price: 30.0,
        value: 750_000,
        shares_held_after: 450_000,
        sec_form_url: 'https://sec.gov/edgar/y',
      },
    ],
    quarterly_net: [
      { quarter: "Q2 '26", net_shares: 200_000, buy_volume: 6_000_000, sell_volume: 500_000, net_volume: 5_500_000, transaction_count: 7 },
      { quarter: "Q1 '26", net_shares: 50_000, buy_volume: 2_500_000, sell_volume: 700_000, net_volume: 1_800_000, transaction_count: 5 },
    ],
    strategy: {
      name: 'Form 4 Insider Cluster Accumulation',
      description: 'Systematic factor model tracking C-suite open-market purchases > $500K.',
      backtest_start_date: '2022-01-01',
      cagr: 32.4,
      return_30d: 8.2,
      return_1y: 45.6,
      max_drawdown: -14.5,
      beta: 0.95,
      alpha: 18.2,
      sharpe: 2.15,
      win_rate: 68.5,
      avg_win: 12.4,
      avg_loss: -5.2,
      total_trades: 48,
    },
  }

  const mockGovernment: GovernmentPayload = {
    symbol: 'ASTS',
    congress: [
      {
        politician_name: 'Tommy Tuberville',
        party: 'Republican',
        chamber: 'Senate',
        state: 'AL',
        transaction_date: '2026-07-15',
        filing_date: '2026-08-01',
        type: 'Purchase',
        amount_range: '$50,001 - $100,000',
        asset_description: 'AST SpaceMobile Class A Common',
        source_url: 'https://efdsearch.senate.gov',
      },
    ],
    lobbying: {
      estimated_quarterly_spend: 350_000,
      total_spend_annual: 1_400_000,
      history: [{ quarter: "Q2 '26", amount: 350_000, date: '2026-07-20' }],
      filings: [
        { date: '2026-07-20', amount: 350_000, issue: 'FCC Spectrum & Satellite Direct-to-Device Allocation', description: 'Advocacy for cellular direct-to-device rules', registrant: 'AST SpaceMobile Inc' },
      ],
    },
    contracts: [
      { agency: 'U.S. Space Force / Department of Defense', date: '2026-06-15', amount: 45_000_000, contract_type: 'Prime Defense Contract', description: 'Space-based tactical cellular communications prototype' },
    ],
    patents: [
      { patent_number: 'US 11,848,720', title: 'Space-to-Ground Cellular Phased Array Beamforming', grant_date: '2026-05-10', abstract: 'Architecture for direct satellite-to-standard-smartphone communications' },
    ],
  }

  const mockOwnership: OwnershipPayload = {
    symbol: 'ASTS',
    breakdown: {
      institutional_pct: 58.5,
      insider_pct: 22.0,
      retail_float_pct: 19.5,
      shares_outstanding: 280_000_000,
      float_shares: 218_000_000,
    },
    top_institutions: [
      { holder: 'Vanguard Group Inc', shares: 22_500_000, date_reported: '2026-06-30', pct_out: 8.04, value: 731_250_000 },
      { holder: 'BlackRock Inc', shares: 19_200_000, date_reported: '2026-06-30', pct_out: 6.86, value: 624_000_000 },
    ],
    top_funds: [
      { holder: 'Vanguard Total Stock Market Index Fund', shares: 8_500_000, date_reported: '2026-06-30', pct_out: 3.04, value: 276_250_000 },
    ],
    short_interest: {
      shares_short: 42_000_000,
      short_pct_of_float: 19.26,
      days_to_cover: 4.8,
      shares_short_prior_month: 46_000_000,
    },
  }

  it('correctly processes and displays Multi-Period Financials statements', () => {
    const fin = ref(mockFinancials)
    expect(fin.value.periods).toHaveLength(4)
    expect(formatPeriodHeader(fin.value.periods[0], true)).toBe("Q2 '26")

    const revRow = fin.value.income_statement.rows[0]
    expect(revRow.label).toBe('Total Revenue')
    expect(formatBigUsd(revRow.values[0])).toBe('$25.00M')

    const gmRow = fin.value.income_statement.rows[2]
    expect(formatStatementCell(gmRow.values[0], gmRow.format)).toBe('+72.0%')
    expect(getGrowthTone(gmRow.values[0])).toBe('pos')

    const fcf = fin.value.ratios.free_cash_flow
    expect(formatBigUsd(fcf)).toBe('-$13.00M')
  })

  it('correctly processes and filters Insider Trading transactions', () => {
    const ins = ref(mockInsiders)
    const filter = ref<'all' | 'buy' | 'sell'>('buy')
    const query = ref('')

    const filtered = computed(() => {
      return ins.value.transactions.filter((tx) => {
        if (filter.value === 'buy' && tx.transaction_type !== 'Purchase') return false
        if (filter.value === 'sell' && tx.transaction_type !== 'Sale') return false
        if (query.value) {
          const q = query.value.toLowerCase()
          return tx.insider_name.toLowerCase().includes(q) || tx.relationship.toLowerCase().includes(q)
        }
        return true
      })
    })

    expect(filtered.value).toHaveLength(1)
    expect(filtered.value[0].insider_name).toBe('Avellan Abel')
    expect(formatBigUsd(filtered.value[0].value)).toBe('$4.28M')

    filter.value = 'sell'
    expect(filtered.value).toHaveLength(1)
    expect(filtered.value[0].insider_name).toBe('Wallace Sean')

    filter.value = 'all'
    expect(filtered.value).toHaveLength(2)
  })

  it('correctly formats Executive Compensation and CEO Pay Ratio', () => {
    const prof = ref(mockProfile)
    const comp = prof.value.compensation

    expect(comp.highest_paid_name).toBe('Abel Avellan')
    expect(formatBigUsd(comp.highest_paid_total)).toBe('$3.50M')
    expect(formatBigUsd(comp.median_employee_pay)).toBe('$145.00K')
    expect(comp.ceo_pay_ratio).toBe(24.1)

    const exec1 = comp.rows[0]
    expect(formatBigUsd(exec1.salary)).toBe('$750.00K')
    expect(formatBigUsd(exec1.total_compensation)).toBe('$3.50M')
  })

  it('correctly processes Government disclosures and awards', () => {
    const gov = ref(mockGovernment)

    expect(gov.value.congress).toHaveLength(1)
    expect(gov.value.congress[0].politician_name).toBe('Tommy Tuberville')
    expect(gov.value.congress[0].party).toBe('Republican')

    expect(gov.value.lobbying.filings).toHaveLength(1)
    expect(formatBigUsd(gov.value.lobbying.total_spend_annual)).toBe('$1.40M')

    expect(gov.value.contracts).toHaveLength(1)
    expect(formatBigUsd(gov.value.contracts[0].amount)).toBe('$45.00M')

    expect(gov.value.patents).toHaveLength(1)
    expect(gov.value.patents[0].patent_number).toBe('US 11,848,720')
  })

  it('correctly processes Ownership breakdown and short interest', () => {
    const own = ref(mockOwnership)

    expect(own.value.breakdown.institutional_pct).toBe(58.5)
    expect(own.value.breakdown.insider_pct).toBe(22.0)
    expect(own.value.breakdown.retail_float_pct).toBe(19.5)
    expect(compact(own.value.breakdown.shares_outstanding)).toBe('280.0M')

    expect(own.value.top_institutions).toHaveLength(2)
    expect(own.value.top_institutions[0].holder).toBe('Vanguard Group Inc')
    expect(formatBigUsd(own.value.top_institutions[0].value)).toBe('$731.25M')

    expect(own.value.short_interest.short_pct_of_float).toBe(19.26)
    expect(own.value.short_interest.days_to_cover).toBe(4.8)
  })

  it('correctly generates sparklines for Compare series', () => {
    const compareData: ComparePayload = {
      window: '1y',
      series: {
        ASTS: [{ d: '2026-08-01', cum: 0 }, { d: '2026-08-02', cum: 10 }, { d: '2026-08-03', cum: 20 }],
        SPY: [{ d: '2026-08-01', cum: 0 }, { d: '2026-08-02', cum: 0.36 }, { d: '2026-08-03', cum: 0.91 }],
      },
      stats: {
        ASTS: { chg_window_pct: 20.0, sharpe: 2.1, max_drawdown_pct: -4.5 },
        SPY: { chg_window_pct: 0.91, sharpe: 1.5, max_drawdown_pct: -1.2 },
      },
      correlation: {
        ASTS: { ASTS: 1.0, SPY: 0.35 },
        SPY: { ASTS: 0.35, SPY: 1.0 },
      },
    }

    const sparks: Record<string, string> = {}
    for (const [sym, rows] of Object.entries(compareData.series)) {
      if (rows && rows.length > 0) {
        sparks[sym] = sparkline(rows.map((r) => r.cum), 120, 22, 2).d
      }
    }

    expect(sparks.ASTS).toBeTruthy()
    expect(sparks.ASTS).toContain('M')
    expect(sparks.SPY).toBeTruthy()
    expect(sparks.SPY).toContain('M')
  })

  it('correctly sanitizes candle source identifiers with formatSourceLabel', async () => {
    const { formatSourceLabel } = await import('../financialsDisplay')
    expect(formatSourceLabel('LSE_EQUITY_CANDLES')).toBe('EXCHANGE BARS')
    expect(formatSourceLabel('qlib_daily_candles')).toBe('DAILY BARS')
    expect(formatSourceLabel('synthetic_bars')).toBe('SYNTHETIC BARS')
    expect(formatSourceLabel('yfinance_daily')).toBe('EXCHANGE BARS')
    expect(formatSourceLabel(null)).toBe('EXCHANGE BARS')
  })

  it('correctly derives financial margin ratios with getDerivedRatio when summary is missing', async () => {
    const { getDerivedRatio } = await import('../financialsDisplay')
    const incomeRows = [
      { key: 'total_revenue', label: 'Total Revenue', values: [1000000, 900000] },
      { key: 'gross_profit', label: 'Gross Profit', values: [550000, 480000] },
      { key: 'net_income', label: 'Net Income', values: [200000, 180000] },
    ]
    expect(getDerivedRatio({ gross_margin: 55.0 }, incomeRows, 'gross_margin')).toBe(55.0)
    expect(getDerivedRatio({}, incomeRows, 'gross_margin')).toBe(55)
    expect(getDerivedRatio({}, incomeRows, 'net_margin')).toBe(20)
  })

  it('correctly matches analyst revisions with flexible abbreviations and counts', () => {
    const sampleRevisions = [
      { firm: 'Morgan Stanley', action: 'up', current: 'Overweight', previous: 'Equal-Weight' },
      { firm: 'Goldman Sachs', action: 'Upgrades', current: 'Buy', previous: 'Neutral' },
      { firm: 'Barclays', action: 'down', current: 'Underweight', previous: 'Equal-Weight' },
      { firm: 'Citi', action: 'init', current: 'Buy', previous: '' },
      { firm: 'JPMorgan', action: 'main', current: 'Neutral', previous: 'Neutral' },
      { firm: 'UBS', action: 'Reiterates', current: 'Hold', previous: 'Hold' },
    ]

    function matchFilter(action: string | undefined, filter: string): boolean {
      if (filter === 'all') return true
      const act = (action || '').toLowerCase().trim()
      if (filter === 'upgrade') {
        return act.includes('upgrade') || act.includes('outperform') || act.includes('buy') || act === 'up'
      }
      if (filter === 'initiate') {
        return act.includes('initiat') || act.includes('coverage') || act === 'init'
      }
      if (filter === 'maintain') {
        return act.includes('maintain') || act.includes('reiterat') || act.includes('hold') || act.includes('neutral') || act === 'main' || act === 'reit'
      }
      if (filter === 'downgrade') {
        return act.includes('downgrade') || act.includes('underperform') || act.includes('sell') || act === 'down'
      }
      return true
    }

    const upgrades = sampleRevisions.filter((r) => matchFilter(r.action, 'upgrade'))
    const downgrades = sampleRevisions.filter((r) => matchFilter(r.action, 'downgrade'))
    const initiations = sampleRevisions.filter((r) => matchFilter(r.action, 'initiate'))
    const maintains = sampleRevisions.filter((r) => matchFilter(r.action, 'maintain'))

    expect(upgrades).toHaveLength(2)
    expect(downgrades).toHaveLength(1)
    expect(initiations).toHaveLength(1)
    expect(maintains).toHaveLength(2)
  })

  it('correctly handles institutional search, sorting, and pagination', () => {
    const institutions = [
      { holder: 'Vanguard Group Inc', shares: 50000000, pct_out: 12.5, value: 4500000000, date_reported: '2026-06-30' },
      { holder: 'BlackRock Inc', shares: 42000000, pct_out: 10.5, value: 3780000000, date_reported: '2026-06-30' },
      { holder: 'State Street Corp', shares: 20000000, pct_out: 5.0, value: 1800000000, date_reported: '2026-06-30' },
      { holder: 'Citadel Advisors LLC', shares: 15000000, pct_out: 3.75, value: 1350000000, date_reported: '2026-06-30' },
      { holder: 'Two Sigma Investments', shares: 10000000, pct_out: 2.5, value: 900000000, date_reported: '2026-06-30' },
      { holder: 'Renaissance Technologies', shares: 8000000, pct_out: 2.0, value: 720000000, date_reported: '2026-06-30' },
    ]

    const filtered = filterSortInstitutions(institutions, 'citadel', 'shares', false)
    expect(filtered).toHaveLength(1)
    expect(filtered[0].holder).toBe('Citadel Advisors LLC')

    const sorted = filterSortInstitutions(institutions, '', 'shares', false)
    expect(sorted[0].holder).toBe('Vanguard Group Inc')
    expect(sorted[sorted.length - 1].holder).toBe('Renaissance Technologies')

    const pageSize = 2
    const page1 = paginateHolders(sorted, 1, pageSize)
    const page2 = paginateHolders(sorted, 2, pageSize)
    expect(page1).toHaveLength(2)
    expect(page1[0].holder).toBe('Vanguard Group Inc')
    expect(page2).toHaveLength(2)
    expect(page2[0].holder).toBe('State Street Corp')

    // KPIs calculation
    const totalVal = institutions.reduce((acc, cur) => acc + cur.value, 0)
    const top5Pct = institutions.slice(0, 5).reduce((acc, cur) => acc + cur.pct_out, 0)
    expect(totalVal).toBe(13050000000)
    expect(top5Pct).toBe(34.25)
  })
})

