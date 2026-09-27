import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { OptionsTapeRow } from '@/api'
import { classifyFlowOrder } from '@/flowDisplay'
import { num, shortDate } from '@/format'

function mockRow(partial: Partial<OptionsTapeRow>): OptionsTapeRow {
  return {
    timestamp: '2026-09-07T14:30:00Z',
    right: 'call',
    premium: 50_000,
    volume: 100,
    strike: 100,
    aggressor: null,
    signed_premium: null,
    expiry: '2026-09-18',
    premium_estimated: false,
    anomaly_flags: [],
    anomaly_score: 0,
    premium_percentile: 50,
    ...partial,
  }
}

describe('Options Table & Flow Bar Bug Fixes & Improvements', () => {
  describe('1. computeRowDte calendar 0DTE and expiry parsing', () => {
    // Pure replica of computeRowDte in OptionsView.vue
    function computeRowDte(row: OptionsTapeRow, now: Date = new Date()): number | null {
      if (row.dte != null && Number.isFinite(row.dte)) return Math.max(0, Math.floor(row.dte))
      if (!row.expiry) return null
      const expClean = row.expiry.slice(0, 10)
      if (!/^\d{4}-\d{2}-\d{2}$/.test(expClean)) {
        const expDate = new Date(row.expiry)
        if (isNaN(expDate.getTime())) return null
        const diffMs = expDate.getTime() - now.getTime()
        return Math.max(0, Math.ceil(diffMs / 86_400_000))
      }
      const [y, m, d] = expClean.split('-').map(Number)
      const expUtc = Date.UTC(y, m - 1, d)
      const todayUtc = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
      const diffDays = Math.round((expUtc - todayUtc) / 86_400_000)
      return Math.max(0, diffDays)
    }

    it('preserves row.dte when explicitly supplied by provider', () => {
      const row = mockRow({
        timestamp: '2026-09-07T14:30:00Z',
        right: 'call',
        premium: 50_000,
        volume: 100,
        strike: 200,
        aggressor: 'buy',
        signed_premium: 50_000,
        expiry: '2026-09-07',
        dte: 0,
      })
      expect(computeRowDte(row)).toBe(0)
    })

    it('accurately computes 0DTE on expiration day during active trading hours (not 1)', () => {
      // Simulate now at 15:30:00 UTC on expiration date
      const now = new Date('2026-09-07T15:30:00Z')
      const row = mockRow({
        timestamp: '2026-09-07T15:25:00Z',
        right: 'put',
        premium: 25_000,
        volume: 50,
        strike: 195,
        aggressor: 'sell',
        signed_premium: -25_000,
        expiry: '2026-09-07',
        dte: null,
      })
      const dte = computeRowDte(row, now)
      expect(dte).toBe(0)
    })

    it('accurately computes 1DTE for next-day expiration', () => {
      const now = new Date('2026-09-07T15:30:00Z')
      const row = mockRow({
        expiry: '2026-09-08',
        dte: null,
      })
      expect(computeRowDte(row, now)).toBe(1)
    })

    it('returns null when expiry and dte are both absent', () => {
      const row = mockRow({
        timestamp: '2026-09-07T14:30:00Z',
        right: 'call',
        premium: 10_000,
        volume: 10,
        strike: 100,
        aggressor: null,
        signed_premium: null,
        expiry: null,
        dte: null,
      })
      expect(computeRowDte(row)).toBeNull()
    })
  })

  describe('2. matchesSearchQuery comprehensive filter resilience', () => {
    function computeRowDte(row: OptionsTapeRow, now: Date = new Date()): number | null {
      if (row.dte != null && Number.isFinite(row.dte)) return Math.max(0, Math.floor(row.dte))
      if (!row.expiry) return null
      const expClean = row.expiry.slice(0, 10)
      if (!/^\d{4}-\d{2}-\d{2}$/.test(expClean)) {
        const expDate = new Date(row.expiry)
        if (isNaN(expDate.getTime())) return null
        const diffMs = expDate.getTime() - now.getTime()
        return Math.max(0, Math.ceil(diffMs / 86_400_000))
      }
      const [y, m, d] = expClean.split('-').map(Number)
      const expUtc = Date.UTC(y, m - 1, d)
      const todayUtc = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
      const diffDays = Math.round((expUtc - todayUtc) / 86_400_000)
      return Math.max(0, diffDays)
    }

    function matchesSearchQuery(
      row: OptionsTapeRow,
      symbolStr: string,
      searchQuery: string,
    ): boolean {
      const rawQ = searchQuery.trim().toLowerCase()
      if (!rawQ) return true
      const q = rawQ.startsWith('$') ? rawQ.slice(1).trim() : rawQ
      const strikeStr = row.strike != null ? String(row.strike) : ''
      const strikeWithDollar = row.strike != null ? `$${row.strike}` : ''
      const expStr = row.expiry ? row.expiry.toLowerCase() : ''
      const expFormatted = row.expiry ? shortDate(row.expiry).toLowerCase() : ''
      const dteVal = computeRowDte(row, new Date('2026-09-07T14:30:00Z'))
      const dteStr = dteVal != null ? `${dteVal}d` : ''
      const dteFull = dteVal != null ? `${dteVal}dte` : ''
      const rightStr = (row.right || row.activity_side || '').toLowerCase()
      const classStr = (row.trade_class || '').toLowerCase()
      const occStr = (row.occ_symbol || '').toLowerCase()
      const flags = (row.anomaly_flags ?? []).join(' ').toLowerCase()
      const classLabel = classifyFlowOrder(row).label.toLowerCase()
      const sym = symbolStr.toLowerCase()
      const agg = (row.aggressor ?? '').toLowerCase()
      const aggLabel = (row.aggressor_label ?? '').toLowerCase()

      const strikeRightCombo = `${strikeStr}${rightStr}`
      const strikeRightComboShort = `${strikeStr}${rightStr ? rightStr[0] : ''}`
      const strikeSpaceCombo = `${strikeStr} ${rightStr}`
      const isCallsSearch =
        q === 'calls' || q === 'call' || q.endsWith('calls') || q.endsWith('call')
      const isPutsSearch = q === 'puts' || q === 'put' || q.endsWith('puts') || q.endsWith('put')

      return (
        strikeStr.includes(q) ||
        strikeWithDollar.toLowerCase().includes(rawQ) ||
        expStr.includes(q) ||
        expFormatted.includes(q) ||
        (dteStr.length > 0 && (q === dteStr || q === dteFull || dteStr.includes(q))) ||
        (q === '0dte' && dteVal === 0) ||
        (isCallsSearch && rightStr === 'call') ||
        (isPutsSearch && rightStr === 'put') ||
        rightStr.includes(q) ||
        classStr.includes(q) ||
        occStr.includes(q) ||
        flags.includes(q) ||
        classLabel.includes(q) ||
        sym.includes(q) ||
        agg.includes(q) ||
        aggLabel.includes(q) ||
        strikeRightCombo.includes(q) ||
        strikeRightComboShort.includes(q) ||
        strikeSpaceCombo.includes(q) ||
        (q === 'whale' && (row.premium ?? 0) >= 100_000) ||
        (q === 'golden' && classifyFlowOrder(row).type === 'golden_sweep') ||
        (q === 'sweep' && (classLabel === 'sweep' || row.is_sweep === true)) ||
        (q === 'block' && (classLabel === 'block' || row.is_block === true))
      )
    }

    const testRow = mockRow({
      timestamp: '2026-09-07T14:30:00Z',
      right: 'call',
      premium: 250_000,
      volume: 500,
      contracts: 500,
      strike: 150,
      aggressor: 'buy',
      signed_premium: 250_000,
      expiry: '2026-09-18',
      trade_class: 'sweep',
      is_sweep: true,
      anomaly_flags: ['repeat_cluster'],
    })

    it('matches strike with or without dollar sign ($150 and 150)', () => {
      expect(matchesSearchQuery(testRow, 'NVDA', '$150')).toBe(true)
      expect(matchesSearchQuery(testRow, 'NVDA', '150')).toBe(true)
      expect(matchesSearchQuery(testRow, 'NVDA', '$200')).toBe(false)
    })

    it('matches combo searches like 150c, 150 call, 150 c', () => {
      expect(matchesSearchQuery(testRow, 'NVDA', '150c')).toBe(true)
      expect(matchesSearchQuery(testRow, 'NVDA', '150 call')).toBe(true)
      expect(matchesSearchQuery(testRow, 'NVDA', '150 calls')).toBe(true)
      expect(matchesSearchQuery(testRow, 'NVDA', '150p')).toBe(false)
    })

    it('matches underlier ticker symbol', () => {
      expect(matchesSearchQuery(testRow, 'NVDA', 'nvda')).toBe(true)
      expect(matchesSearchQuery(testRow, 'NVDA', 'aapl')).toBe(false)
    })

    it('matches month name (e.g. SEP)', () => {
      expect(matchesSearchQuery(testRow, 'NVDA', 'sep')).toBe(true)
      expect(matchesSearchQuery(testRow, 'NVDA', 'oct')).toBe(false)
    })

    it('matches whale, sweep, and anomaly flags', () => {
      expect(matchesSearchQuery(testRow, 'NVDA', 'whale')).toBe(true)
      expect(matchesSearchQuery(testRow, 'NVDA', 'sweep')).toBe(true)
      expect(matchesSearchQuery(testRow, 'NVDA', 'repeat_cluster')).toBe(true)
      expect(matchesSearchQuery(testRow, 'NVDA', 'buy')).toBe(true)
    })

    it('matches plural calls and puts searches', () => {
      expect(matchesSearchQuery(testRow, 'NVDA', 'calls')).toBe(true)
      expect(matchesSearchQuery(testRow, 'NVDA', 'puts')).toBe(false)
    })
  })

  describe('3. volOiRatio calculation contracts fallback and pricePaid multiplier', () => {
    function contractsOf(row: OptionsTapeRow): number {
      return row.contracts != null && row.contracts > 0 ? row.contracts : (row.volume ?? 0)
    }

    function volOiRatio(row: OptionsTapeRow): number | null {
      const oi = row.open_interest
      const vol = contractsOf(row)
      if (!oi || oi <= 0 || vol <= 0) return null
      return vol / oi
    }

    function pricePaid(row: OptionsTapeRow): number | null {
      if (row.price != null && Number.isFinite(row.price)) return row.price
      const n = contractsOf(row)
      const mult =
        row.contract_multiplier && row.contract_multiplier > 0 ? row.contract_multiplier : 100
      if (n > 0 && row.premium > 0) return row.premium / (n * mult)
      return null
    }

    it('calculates ratio when volume is 0 or null but contracts is positive', () => {
      const row = mockRow({
        timestamp: '2026-09-07T14:30:00Z',
        right: 'call',
        premium: 10_000,
        volume: 0,
        contracts: 200,
        open_interest: 100,
        strike: 100,
      })
      expect(volOiRatio(row)).toBe(2.0)
    })

    it('returns null when open interest is 0 or absent', () => {
      const row = mockRow({
        volume: 200,
        open_interest: 0,
      })
      expect(volOiRatio(row)).toBeNull()
    })

    it('respects custom contract_multiplier in pricePaid', () => {
      const standardRow = mockRow({
        price: null,
        contracts: 10,
        premium: 2_000,
        contract_multiplier: 100,
      })
      expect(pricePaid(standardRow)).toBe(2.0) // 2000 / (10 * 100) = 2.0

      const miniOptionRow = mockRow({
        price: null,
        contracts: 10,
        premium: 200,
        contract_multiplier: 10,
      })
      expect(pricePaid(miniOptionRow)).toBe(2.0) // 200 / (10 * 10) = 2.0
    })
  })

  describe('4. OptionsFlowContext.vue ratioBadge logic', () => {
    function computeRatioBadge(call: number, put: number) {
      const total = call + put
      const hasPrem = total > 0
      const callPct = hasPrem ? Math.round((call / total) * 100) : 0

      if (!hasPrem || total <= 0) {
        return { text: 'NO FLOW', cls: 'balance-pill' }
      }
      if (call > 0 && put <= 0) {
        return { text: '100% CALLS', cls: 'call' }
      }
      if (put > 0 && call <= 0) {
        return { text: '100% PUTS', cls: 'put' }
      }
      if (callPct >= 47 && callPct <= 53) {
        return { text: 'BALANCED', cls: 'balanced' }
      }
      const cpRatio = call / put
      return {
        text: `${num(cpRatio, 2)}x C/P`,
        cls: callPct > 53 ? 'call' : 'put',
      }
    }

    it('reports NO FLOW when total premium is 0', () => {
      expect(computeRatioBadge(0, 0)).toEqual({ text: 'NO FLOW', cls: 'balance-pill' })
    })

    it('reports 100% CALLS when puts are 0 (NOT false BALANCED)', () => {
      expect(computeRatioBadge(500_000, 0)).toEqual({ text: '100% CALLS', cls: 'call' })
    })

    it('reports 100% PUTS when calls are 0', () => {
      expect(computeRatioBadge(0, 300_000)).toEqual({ text: '100% PUTS', cls: 'put' })
    })

    it('reports BALANCED when split is 50/50', () => {
      expect(computeRatioBadge(100_000, 100_000)).toEqual({ text: 'BALANCED', cls: 'balanced' })
    })

    it('reports numeric ratio when asymmetric with both sides present', () => {
      const res = computeRatioBadge(300_000, 100_000)
      expect(res.text).toBe('3.00x C/P')
      expect(res.cls).toBe('call')

      const resPut = computeRatioBadge(50_000, 100_000)
      expect(resPut.text).toBe('0.50x C/P')
      expect(resPut.cls).toBe('put')
    })
  })

  describe('5. OptionsView.vue source structure conformance', () => {
    const viewPath = resolve(__dirname, '..', 'views', 'OptionsView.vue')
    const viewSrc = readFileSync(viewPath, 'utf-8')

    it('ships Strike · Type header and strike-lockup with Call/Put type-chip', () => {
      expect(viewSrc).toContain('Strike · Type')
      expect(viewSrc).toContain('strike-lockup')
      expect(viewSrc).toContain('type-chip label')
      expect(viewSrc).toContain('row.right')
    })

    it('uses computeRowDte in table expiry column and historical table', () => {
      expect(viewSrc).toContain('computeRowDte(row)')
    })

    it('empty state button resets all filters', () => {
      expect(viewSrc).toMatch(/<button[^>]*@click="resetAllFilters"[^>]*>\s*RESET ALL FILTERS/s)
    })

    it('preserves strike-head and strike-cell nowrap styling', () => {
      expect(viewSrc).toContain('.strike-head')
      expect(viewSrc).toMatch(/\.strike-head\s*\{[^}]*white-space:\s*nowrap/)
      expect(viewSrc).toMatch(/\.strike-cell\s*\{[^}]*white-space:\s*nowrap/)
    })
  })

  describe('6. OptionsFlowContext.vue flow bar enhancements', () => {
    const contextPath = resolve(__dirname, '..', 'components', 'OptionsFlowContext.vue')
    const contextSrc = readFileSync(contextPath, 'utf-8')

    it('binds tone, conviction, and direction to the root container', () => {
      expect(contextSrc).toContain(':class="[')
      expect(contextSrc).toContain('premium.tone')
      expect(contextSrc).toContain('deskAction.direction')
    })

    it('includes centerline notch and C/P ratio badge', () => {
      expect(contextSrc).toContain('track-center-notch')
      expect(contextSrc).toContain('premium-center-ratio')
      expect(contextSrc).toContain('ratio-pill')
      expect(contextSrc).toContain('ratioBadge')
    })

    it('uses clean CSS token variables and no forbidden patterns', () => {
      expect(contextSrc).not.toContain('#059669')
      expect(contextSrc).not.toContain('#ef4444')
      expect(contextSrc).not.toMatch(/text-shadow\s*:/)
      expect(contextSrc).not.toMatch(/filter\s*:\s*brightness\(/)
      expect(contextSrc).toContain('var(--call)')
      expect(contextSrc).toContain('var(--put)')
      expect(contextSrc).toContain('var(--glass-')
    })
  })
})
