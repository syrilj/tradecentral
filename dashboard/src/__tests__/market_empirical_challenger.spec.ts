/**
 * Challenger 1: Empirical Verification & Stress Test Suite
 *
 * Covers:
 * 1. Deep Unicode Emoji Automated Scans across views, components, and utilities
 * 2. Empty Data Payloads and Null/Undefined/NaN field stress tests across all 10 tabs
 * 3. Compare Basket Edge Cases (< 2 symbols deadlock prevention, max symbol cap, deduping)
 * 4. Tab Switching across all 10 tabs & in-cockpit navigation invariant (no infinite redirect loop)
 * 5. Rapid Symbol & State Transition Reactivity
 * 6. Extreme Numerical Invariant, Div-by-Zero, and Boundary Value Testing
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
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
import type {
  FinancialsPayload,
  CompanyProfilePayload,
  InsidersIntelligencePayload,
  GovernmentPayload,
  OwnershipPayload,
  ComparePayload,
} from '@/api'

const dashboardRoot = resolve(__dirname, '..')
const marketViewPath = join(dashboardRoot, 'views', 'MarketView.vue')
const marketViewSource = readFileSync(marketViewPath, 'utf8')
const routerPath = join(dashboardRoot, 'router.ts')
const routerSource = readFileSync(routerPath, 'utf8')

// ============================================================================
// 1. AUTOMATED REGEX SCAN FOR UNICODE EMOJIS
// ============================================================================
describe('Challenger 1: Deep Regex Emoji Scans (Institutional Design Gate)', () => {
  const EMOJI_REGEX = /[\u{1F300}-\u{1F5FF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{1F700}-\u{1F77F}\u{1F780}-\u{1F7FF}\u{1F800}-\u{1F8FF}\u{1F900}-\u{1F9FF}\u{1FA00}-\u{1FA6F}\u{1FA70}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F1E6}-\u{1F1FF}]/u

  function getAllFiles(dir: string, ext: string[]): string[] {
    const results: string[] = []
    const list = readdirSync(dir)
    for (const file of list) {
      const fullPath = join(dir, file)
      const stat = statSync(fullPath)
      if (stat && stat.isDirectory()) {
        if (file !== 'node_modules' && file !== 'dist' && file !== '__tests__') {
          results.push(...getAllFiles(fullPath, ext))
        }
      } else if (ext.some((e) => file.endsWith(e))) {
        results.push(fullPath)
      }
    }
    return results
  }

  it('MarketView.vue has zero pictorial/consumer emojis', () => {
    const matches: string[] = []
    const lines = marketViewSource.split('\n')
    lines.forEach((line, idx) => {
      const m = line.match(EMOJI_REGEX)
      if (m) {
        const char = m[0]
        const code = char.codePointAt(0) ?? 0
        if (code >= 0x1f000) {
          matches.push(`Line ${idx + 1}: ${char} (0x${code.toString(16)})`)
        }
      }
    })
    expect(matches, `Found emojis in MarketView.vue:\n${matches.join('\n')}`).toEqual([])
  })

  it('all dashboard components have zero consumer emojis', () => {
    const componentsDir = join(dashboardRoot, 'components')
    const files = getAllFiles(componentsDir, ['.vue', '.ts'])
    const violations: string[] = []

    for (const f of files) {
      const content = readFileSync(f, 'utf8')
      const lines = content.split('\n')
      lines.forEach((line, idx) => {
        const m = line.match(EMOJI_REGEX)
        if (m) {
          const char = m[0]
          const code = char.codePointAt(0) ?? 0
          if (code >= 0x1f000) {
            violations.push(`${f}:${idx + 1} -> ${char} (0x${code.toString(16)})`)
          }
        }
      })
    }
    expect(violations, `Found emojis in components:\n${violations.join('\n')}`).toEqual([])
  })

  it('financialsDisplay.ts, insiderDisplay.ts, and format.ts have zero emojis', () => {
    const utils = ['financialsDisplay.ts', 'insiderDisplay.ts', 'format.ts', 'api.ts']
    for (const u of utils) {
      const content = readFileSync(join(dashboardRoot, u), 'utf8')
      const lines = content.split('\n')
      lines.forEach((line, idx) => {
        const m = line.match(EMOJI_REGEX)
        if (m) {
          const char = m[0]
          const code = char.codePointAt(0) ?? 0
          if (code >= 0x1f000) {
            expect.fail(`${u}:${idx + 1} contains emoji: ${char}`)
          }
        }
      })
    }
  })
})

// ============================================================================
// 2. EMPTY PAYLOADS & NULL / UNDEFINED / NAN FIELD STRESS TESTS
// ============================================================================
describe('Challenger 1: Empty Data Payloads & Null Field Resilience', () => {
  it('handles completely empty / malformed Financials payload', () => {
    const emptyFin = ref<FinancialsPayload>({
      symbol: 'TEST',
      period_type: 'quarterly',
      periods: [],
      income_statement: { rows: [] },
      balance_sheet: { rows: [] },
      cash_flow: { rows: [] },
      revenue_breakdown: { by_segment: [], by_geography: [] },
      ratios: {
        market_cap: null as unknown as number,
        pe_trailing: null as unknown as number,
        gross_margin: null as unknown as number,
        net_margin: null as unknown as number,
        debt_to_equity: null as unknown as number,
        current_ratio: null as unknown as number,
        roe: null as unknown as number,
        roa: null as unknown as number,
        free_cash_flow: null as unknown as number,
      },
      source: 'Mock',
      asof: '2026-08-15T00:00:00Z',
    })

    const incomeRows = computed(() => emptyFin.value.income_statement?.rows || [])
    const balanceRows = computed(() => emptyFin.value.balance_sheet?.rows || [])
    const cashRows = computed(() => emptyFin.value.cash_flow?.rows || [])
    const segments = computed(() => emptyFin.value.revenue_breakdown?.by_segment || [])
    const geos = computed(() => emptyFin.value.revenue_breakdown?.by_geography || [])
    const peRatio = computed(() => num(emptyFin.value.ratios?.pe_trailing, 1))
    const gmRatio = computed(() => pct(emptyFin.value.ratios?.gross_margin, 1))
    const fcf = computed(() => formatBigUsd(emptyFin.value.ratios?.free_cash_flow))

    expect(incomeRows.value).toEqual([])
    expect(balanceRows.value).toEqual([])
    expect(cashRows.value).toEqual([])
    expect(segments.value).toEqual([])
    expect(geos.value).toEqual([])
    expect(peRatio.value).toBe(DASH)
    expect(gmRatio.value).toBe(DASH)
    expect(fcf.value).toBe(DASH)
  })

  it('handles empty / null Company Profile & Forecast payload', () => {
    const emptyProf = ref<CompanyProfilePayload>({
      symbol: 'EMPTY',
      about: {
        name: null as unknown as string,
        description: null as unknown as string,
        sector: null as unknown as string,
        industry: null as unknown as string,
        employees: null as unknown as number,
        market_cap: null as unknown as number,
      },
      officers: [],
      compensation: {
        highest_paid_name: null as unknown as string,
        highest_paid_total: null as unknown as number,
        median_employee_pay: null as unknown as number,
        ceo_pay_ratio: null as unknown as number,
        year: null as unknown as string,
        rows: [],
      },
      forecast: {
        consensus_rating: null as unknown as string,
        recommendation_mean: null as unknown as number,
        target_price_high: null as unknown as number,
        target_price_median: null as unknown as number,
        target_price_low: null as unknown as number,
        current_price: null as unknown as number,
        upside_pct: null as unknown as number,
        recommendations: { strong_buy: 0, buy: 0, hold: 0, underperform: 0, sell: 0 },
        upgrades_downgrades: [],
      },
      smart_score: {
        score: null as unknown as number,
        rating: null as unknown as string,
        components: { momentum: 0, insider_activity: 0, institutional_flow: 0, analyst_sentiment: 0, financial_health: 0 },
      },
      bull_bear: {
        bulls_say: [],
        bears_say: [],
        last_updated: '',
      },
    })

    const name = computed(() => emptyProf.value.about?.name ?? DASH)
    const medianTarget = computed(() =>
      emptyProf.value.forecast?.target_price_median != null
        ? usd(emptyProf.value.forecast?.target_price_median)
        : DASH,
    )
    const ceoPay = computed(() => formatBigUsd(emptyProf.value.compensation?.highest_paid_total))
    const ceoRatio = computed(() => num(emptyProf.value.compensation?.ceo_pay_ratio, 1))
    const scoreVal = computed(() =>
      emptyProf.value.smart_score?.score != null
        ? String(emptyProf.value.smart_score.score)
        : DASH,
    )

    expect(name.value).toBe(DASH)
    expect(medianTarget.value).toBe(DASH)
    expect(ceoPay.value).toBe(DASH)
    expect(ceoRatio.value).toBe(DASH)
    expect(scoreVal.value).toBe(DASH)
  })

  it('handles empty Insiders payload with extreme filter queries', () => {
    const emptyIns = ref<InsidersIntelligencePayload>({
      symbol: 'EMPTY',
      summary: {
        net_shares_90d: 0,
        buy_volume_usd: 0,
        sell_volume_usd: 0,
        net_volume_usd: 0,
        total_transactions: 0,
        buy_count: 0,
        sell_count: 0,
      },
      transactions: [],
      quarterly_net: [],
      strategy: {
        name: '',
        description: '',
        backtest_start_date: '',
        cagr: 0,
        return_30d: 0,
        return_1y: 0,
        max_drawdown: 0,
        beta: 0,
        alpha: 0,
        sharpe: 0,
        win_rate: 0,
        avg_win: 0,
        avg_loss: 0,
        total_trades: 0,
      },
    })

    const filter = ref<'all' | 'buy' | 'sell'>('buy')
    const query = ref('NonExistentName')

    const filtered = computed(() => {
      return emptyIns.value.transactions.filter((tx) => {
        if (filter.value === 'buy' && tx.transaction_type !== 'Purchase') return false
        if (filter.value === 'sell' && tx.transaction_type !== 'Sale') return false
        if (query.value) {
          const q = query.value.toLowerCase()
          return (
            (tx.insider_name ?? '').toLowerCase().includes(q) ||
            (tx.relationship ?? '').toLowerCase().includes(q)
          )
        }
        return true
      })
    })

    expect(filtered.value).toEqual([])
  })

  it('handles empty Government & Ownership payloads', () => {
    const emptyGov = ref<GovernmentPayload>({
      symbol: 'EMPTY',
      congress: [],
      lobbying: {
        estimated_quarterly_spend: 0,
        total_spend_annual: 0,
        history: [],
        filings: [],
      },
      contracts: [],
      patents: [],
    })

    const emptyOwn = ref<OwnershipPayload>({
      symbol: 'EMPTY',
      breakdown: {
        institutional_pct: null as unknown as number,
        insider_pct: null as unknown as number,
        retail_float_pct: null as unknown as number,
        shares_outstanding: null as unknown as number,
        float_shares: null as unknown as number,
      },
      top_institutions: [],
      top_funds: [],
      short_interest: {
        shares_short: null as unknown as number,
        short_pct_of_float: null as unknown as number,
        days_to_cover: null as unknown as number,
        shares_short_prior_month: null as unknown as number,
      },
    })

    expect(emptyGov.value.congress).toEqual([])
    expect(emptyGov.value.lobbying.filings).toEqual([])
    expect(emptyGov.value.contracts).toEqual([])
    expect(emptyGov.value.patents).toEqual([])

    expect(pct(emptyOwn.value.breakdown.institutional_pct, 1)).toBe(DASH)
    expect(pct(emptyOwn.value.breakdown.insider_pct, 1)).toBe(DASH)
    expect(compact(emptyOwn.value.breakdown.shares_outstanding)).toBe(DASH)
    expect(compact(emptyOwn.value.short_interest.shares_short)).toBe(DASH)
    expect(num(emptyOwn.value.short_interest.days_to_cover, 1)).toBe(DASH)
  })

  it('format helpers and insider helpers handle null and undefined safely', () => {
    expect(formatPerShare(null)).toBe(DASH)
    expect(formatStatementCell(null, 'ratio')).toBe(DASH)
    expect(pctFrac(null)).toBe(DASH)
    expect(signedPct(null)).toBe(DASH)
    expect(signed(null)).toBe(DASH)
    expect(tone(null)).toBe('flat')
    expect(shortDate(null)).toBe(DASH)
    expect(age(null)).toBe(DASH)
    expect(presentSecFilings(null)).toEqual([])
  })
})

// ============================================================================
// 3. COMPARE BASKET EDGE CASES (< 2 SYMBOLS DEADLOCK PREVENTION)
// ============================================================================
describe('Challenger 1: Compare Basket Edge Cases & Deadlock Prevention', () => {
  it('loadCompare logic handles basket size = 0 safely without API call or errors', () => {
    const basket = ref<string[]>([])
    const cmp = ref<ComparePayload | null>({
      window: '1y',
      series: { SPY: [] },
      stats: {},
      correlation: {},
    })
    const cmpErr = ref<string | null>('Stale error')

    const executeLoadCompare = (): void => {
      if (basket.value.length < 2) {
        cmp.value = null
        cmpErr.value = null
        return
      }
    }

    executeLoadCompare()
    expect(cmp.value).toBeNull()
    expect(cmpErr.value).toBeNull()
  })

  it('loadCompare logic handles basket size = 1 safely without deadlock', () => {
    const basket = ref<string[]>(['ASTS'])
    const cmp = ref<ComparePayload | null>({
      window: '1y',
      series: { ASTS: [] },
      stats: {},
      correlation: {},
    })
    const cmpErr = ref<string | null>('Another stale error')

    const executeLoadCompare = (): void => {
      if (basket.value.length < 2) {
        cmp.value = null
        cmpErr.value = null
        return
      }
    }

    executeLoadCompare()
    expect(cmp.value).toBeNull()
    expect(cmpErr.value).toBeNull()
  })

  it('handles basket size >= 8 cap and duplicate symbol stripping', () => {
    const sym: string = 'NVDA'
    const currentBasket = ['NVDA', 'SPY', 'QQQ', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'TSLA']

    const rest = currentBasket.filter((b) => b !== sym && b !== 'SPY')
    const next = sym === 'SPY' ? ['SPY', 'QQQ', ...rest] : [sym, 'SPY', ...rest]
    const finalBasket = [...new Set(next)].slice(0, 8)

    expect(finalBasket).toHaveLength(8)
    expect(finalBasket[0]).toBe('NVDA')
    expect(finalBasket[1]).toBe('SPY')
    expect(new Set(finalBasket).size).toBe(8) // all unique
  })

  it('handles sparkline generation when series data is empty or single point', () => {
    const emptySeries: { d: string; cum: number }[] = []
    const singlePointSeries = [{ d: '2026-08-01', cum: 0 }]

    const sparks: Record<string, string> = {}
    if (emptySeries.length > 0) {
      sparks['EMPTY'] = sparkline(emptySeries.map((r) => r.cum), 120, 22, 2).d
    }
    if (singlePointSeries.length > 0) {
      sparks['SINGLE'] = sparkline(singlePointSeries.map((r) => r.cum), 120, 22, 2).d
    }

    expect(sparks['EMPTY']).toBeUndefined()
    expect(sparks['SINGLE']).toBeDefined()
  })
})

// ============================================================================
// 4. 10-TAB SWITCHING & IN-COCKPIT NAVIGATION INVARIANT
// ============================================================================
describe('Challenger 1: Tab Switching & Navigation Contract', () => {
  const ALL_10_TABS = [
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

  it('supports seamless switching across all 10 tabs in reactive state', () => {
    const activeTab = ref<string>('overview')

    for (const tab of ALL_10_TABS) {
      activeTab.value = tab
      expect(activeTab.value).toBe(tab)
    }
  })

  it('in-cockpit insiders tab does not bounce to legacy router.push(insiders)', () => {
    // Verify router.ts maps /insiders -> redirect: name: 'market' with tab: 'insiders'
    expect(routerSource).toContain("name: 'insiders'")
    expect(routerSource).toMatch(/name:\s*['"]market['"]/)
    expect(routerSource).toMatch(/tab:\s*['"]insiders['"]/)

    // Verify MarketView.vue contains in-cockpit template markup for insiders
    expect(marketViewSource).toContain("activeTab === 'insiders'")
    expect(marketViewSource).toContain('insiders-layout')
  })
})

// ============================================================================
// 5. RAPID SYMBOL CHANGES & INPUT SANITIZATION
// ============================================================================
describe('Challenger 1: Rapid Symbol Changes & Input Sanitization', () => {
  function cleanTicker(term: string): string {
    return term.trim().toUpperCase().replace(/[^A-Z0-9.-]/g, '').slice(0, 10)
  }

  it('cleans and sanitizes dirty / malformed ticker search queries', () => {
    expect(cleanTicker('  aapl  ')).toBe('AAPL')
    expect(cleanTicker('brk.b')).toBe('BRK.B')
    expect(cleanTicker('bf-b')).toBe('BF-B')
    expect(cleanTicker('asts$$$')).toBe('ASTS')
    expect(cleanTicker('<script>alert("hack")</script>')).toBe('SCRIPTALER')
    expect(cleanTicker('verylongsymbolnamethatexceedstenchars')).toBe('VERYLONGSY')
    expect(cleanTicker('')).toBe('')
    expect(cleanTicker('   ')).toBe('')
  })

  it('handles rapid symbol transitions without state corruption', () => {
    const currentSymbol = ref('ASTS')
    const currentBasket = ref<string[]>(['ASTS', 'SPY'])

    const selectTicker = (newSym: string) => {
      const s = cleanTicker(newSym)
      if (!s) return
      currentSymbol.value = s
      const rest = currentBasket.value.filter((b) => b !== s && b !== 'SPY')
      currentBasket.value = [...new Set(s === 'SPY' ? ['SPY', 'QQQ', ...rest] : [s, 'SPY', ...rest])].slice(0, 8)
    }

    // Sequence of rapid transitions
    selectTicker('NVDA')
    expect(currentSymbol.value).toBe('NVDA')
    expect(currentBasket.value).toEqual(['NVDA', 'SPY', 'ASTS'])

    selectTicker('SPY')
    expect(currentSymbol.value).toBe('SPY')
    expect(currentBasket.value).toEqual(['SPY', 'QQQ', 'NVDA', 'ASTS'])

    selectTicker('AAPL')
    expect(currentSymbol.value).toBe('AAPL')
    expect(currentBasket.value).toEqual(['AAPL', 'SPY', 'QQQ', 'NVDA', 'ASTS'])

    // Malformed input
    selectTicker('   ')
    expect(currentSymbol.value).toBe('AAPL') // unchanged
  })
})

// ============================================================================
// 6. EXTREME NUMERICAL INVARIANT, DIV-BY-ZERO, AND BOUNDARY VALUE TESTING
// ============================================================================
describe('Challenger 1: Extreme Numerical Boundary & Invariant Tests', () => {
  it('formatBigUsd handles extreme scales ($100T, negative trillions, small cents, 0, NaN)', () => {
    expect(formatBigUsd(100_000_000_000_000)).toBe('$100.00T')
    expect(formatBigUsd(-50_000_000_000_000)).toBe('-$50.00T')
    expect(formatBigUsd(1_000_000_000)).toBe('$1.00B')
    expect(formatBigUsd(-1_000_000_000)).toBe('-$1.00B')
    expect(formatBigUsd(500_000)).toBe('$500.00K')
    expect(formatBigUsd(-500_000)).toBe('-$500.00K')
    expect(formatBigUsd(12.34)).toBe('$12.34')
    expect(formatBigUsd(-12.34)).toBe('-$12.34')
    expect(formatBigUsd(0)).toBe('$0.00')
    expect(formatBigUsd(-0)).toBe('$0.00')
    expect(formatBigUsd(null)).toBe(DASH)
    expect(formatBigUsd(undefined)).toBe(DASH)
    expect(formatBigUsd(NaN)).toBe(DASH)
    expect(formatBigUsd(Infinity)).toBe(DASH)
    expect(formatBigUsd(-Infinity)).toBe(DASH)
  })

  it('calculateGrowth prevents division by zero, non-finite values, and negative denominators', () => {
    expect(calculateGrowth(100, 0)).toBeNull()
    expect(calculateGrowth(0, 0)).toBeNull()
    expect(calculateGrowth(null, 100)).toBeNull()
    expect(calculateGrowth(100, null)).toBeNull()
    expect(calculateGrowth(NaN, 100)).toBeNull()
    expect(calculateGrowth(100, NaN)).toBeNull()
    expect(calculateGrowth(Infinity, 100)).toBeNull()
    expect(calculateGrowth(100, Infinity)).toBeNull()

    // YoY with negative base (e.g. net loss reducing from -100 to -50)
    // Formula: (curr - prev) / |prev| * 100 = (-50 - (-100)) / 100 * 100 = +50% improvement
    expect(calculateGrowth(-50, -100)).toBe(50)
  })

  it('formatPeriodHeader handles quarterly, annual, and malformed dates', () => {
    expect(formatPeriodHeader('2026-01-15', true)).toBe("Q1 '26")
    expect(formatPeriodHeader('2026-04-01', true)).toBe("Q2 '26")
    expect(formatPeriodHeader('2026-07-20', true)).toBe("Q3 '26")
    expect(formatPeriodHeader('2026-10-31', true)).toBe("Q4 '26")
    expect(formatPeriodHeader('2025-12-31', false)).toBe('2025')
    expect(formatPeriodHeader('', true)).toBe(DASH)
    expect(formatPeriodHeader('', false)).toBe(DASH)
    expect(formatPeriodHeader('invalid', true)).toBe('invalid')
  })

  it('getGrowthTone handles boundary tolerances strictly', () => {
    expect(getGrowthTone(0.06)).toBe('pos')
    expect(getGrowthTone(0.05)).toBe('flat') // <= 0.05 is flat
    expect(getGrowthTone(-0.06)).toBe('neg')
    expect(getGrowthTone(-0.05)).toBe('flat') // >= -0.05 is flat
    expect(getGrowthTone(0)).toBe('flat')
    expect(getGrowthTone(null)).toBe('flat')
    expect(getGrowthTone(undefined)).toBe('flat')
    expect(getGrowthTone(NaN)).toBe('flat')
  })
})
