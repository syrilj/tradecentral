/**
 * Market Institutions / Ownership presentation against a >30-row fixture.
 * Drives the shipped helpers used by MarketView — not a reimplementation.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { OwnershipPayload, TopInstitutionalHolder } from '@/api'
import {
  filterSortInstitutions,
  formatHolderChange,
  formatHolderShareDelta,
  formatInstitutionsKpi,
  formatInstitutionsPanelMeta,
  holderChangeTone,
  holderPctBarWidth,
  institutionPageCount,
  listedInstitutionCount,
  paginateHolders,
  reportedInstitutionCount,
  tableMaxPctOut,
} from '@/ownershipDisplay'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
const marketViewSource = readFileSync(join(srcRoot, 'views', 'MarketView.vue'), 'utf8')

function fixtureHolders(n: number): TopInstitutionalHolder[] {
  return Array.from({ length: n }, (_, i) => ({
    holder: `Named Filer ${String(i + 1).padStart(3, '0')} LP`,
    shares: 1_000_000 + i,
    date_reported: '2026-06-30',
    pct_out: Number((4.5 - i * 0.01).toFixed(2)),
    value: 35_000_000 + i * 1000,
    change_pct: i % 2 === 0 ? 1.2 : -5.0,
    change_shares: i % 2 === 0 ? 11858 : -52632,
  }))
}

const FIXTURE_N = 234
const REPORTED = 234
const holders = fixtureHolders(FIXTURE_N)
const own: OwnershipPayload = {
  symbol: 'INFQ',
  breakdown: {
    institutional_pct: 62.4,
    insider_pct: 8.1,
    retail_float_pct: 29.5,
    shares_outstanding: 400_000_000,
    float_shares: 310_000_000,
  },
  top_institutions: holders,
  top_funds: [],
  short_interest: { shares_short: 12_000_000 },
  institutions_count: REPORTED,
}

describe('ownership display — reported count vs named rows', () => {
  it('MarketView wires Institutions and Ownership meta/KPI through shipped helpers', () => {
    expect(marketViewSource).toContain("from '@/ownershipDisplay'")
    expect(marketViewSource).toContain('formatInstitutionsPanelMeta')
    expect(marketViewSource).toContain('formatInstitutionsKpi')
    expect(marketViewSource).toContain('reportedInstitutionCount')
    expect(marketViewSource).toContain('filterSortInstitutions')
    expect(marketViewSource).toContain('paginateHolders')
    expect(marketViewSource).not.toContain('${ownData?.top_institutions?.length || 0} Institutions')
  })

  it('KPI uses reported count 234, not listed-length 30', () => {
    expect(listedInstitutionCount(own)).toBe(234)
    expect(reportedInstitutionCount(own)).toBe(234)
    expect(formatInstitutionsKpi(own.top_institutions.length, reportedInstitutionCount(own))).toBe(
      '234 Institutions',
    )
    expect(formatInstitutionsKpi(30, 234)).toBe('234 Institutions')
    expect(formatInstitutionsKpi(30, null)).toBe('30 Institutions')
  })

  it('panel meta is K of N when the feed names a subset of the reported count', () => {
    expect(
      formatInstitutionsPanelMeta({
        filtered: 12,
        listed: 12,
        reported: 243,
        searching: false,
      }),
    ).toBe('12 of 243 Institutions')
    expect(
      formatInstitutionsPanelMeta({
        filtered: 234,
        listed: 234,
        reported: 234,
        searching: false,
      }),
    ).toBe('234 Institutions')
    expect(
      formatInstitutionsPanelMeta({
        filtered: 3,
        listed: 12,
        reported: 243,
        searching: true,
      }),
    ).toBe('3 of 12 named · 243 reported')
  })

  it('page sizes 10 / 25 / 50 / all cover the full 234-row fixture', () => {
    const sorted = filterSortInstitutions(own.top_institutions, '', 'shares', false)
    expect(sorted).toHaveLength(234)
    expect(sorted[0].holder).toBe('Named Filer 234 LP')

    expect(institutionPageCount(234, 10)).toBe(24)
    expect(paginateHolders(sorted, 1, 10)).toHaveLength(10)
    expect(paginateHolders(sorted, 24, 10)).toHaveLength(4)

    expect(institutionPageCount(234, 25)).toBe(10)
    expect(paginateHolders(sorted, 1, 25)).toHaveLength(25)
    expect(paginateHolders(sorted, 10, 25)).toHaveLength(9)

    expect(institutionPageCount(234, 50)).toBe(5)
    expect(paginateHolders(sorted, 5, 50)).toHaveLength(34)

    const all = paginateHolders(sorted, 1, 'all')
    expect(all).toHaveLength(234)
    expect(all.map((row) => row.holder)).toEqual(sorted.map((row) => row.holder))
    expect(institutionPageCount(234, 'all')).toBe(1)
  })

  it('search + All still pages only matching named rows, not a 30-row cap', () => {
    const filtered = filterSortInstitutions(own.top_institutions, 'filer 00', 'holder', true)
    expect(filtered.length).toBeGreaterThan(0)
    expect(filtered.length).toBeLessThan(234)
    expect(paginateHolders(filtered, 1, 'all')).toHaveLength(filtered.length)
    expect(filtered.every((row) => /filer 00/i.test(row.holder))).toBe(true)
  })
})

describe('ownership display — last-quarter change and % bars', () => {
  it('MarketView binds share counts, last-quarter change, and helper-driven bars', () => {
    expect(marketViewSource).toContain('formatHolderChange')
    expect(marketViewSource).toContain('holderPctBarWidth')
    expect(marketViewSource).toContain('holderChangeTone')
    expect(marketViewSource).toContain('Last Quarter')
    expect(marketViewSource).toContain('Shares Held')
    expect(marketViewSource).toContain("ref<number | 'all'>('all')")
    expect(marketViewSource).not.toContain('(inst.pct_out || 0) * 8')
    expect(marketViewSource).not.toContain('* 8)}%')
  })

  it('change formatter uses the shipped change fields, not pct_out', () => {
    const row = holders[0]
    expect(row.change_pct).toBe(1.2)
    expect(row.pct_out).not.toBe(row.change_pct)
    expect(formatHolderChange(row)).toBe('+1.20% · +11,858')
    expect(formatHolderChange(row)).not.toContain(String(row.pct_out))
    expect(formatHolderChange({ change_pct: -5 })).toBe('-5.00%')
    expect(formatHolderChange({ change_shares: -52632 })).toBe('-52,632')
    expect(formatHolderChange({ change_label: 'New', change_shares: 11_573_878 })).toBe(
      'New · +11,573,878',
    )
    expect(formatHolderChange({ change_label: 'Sold Out', change_pct: -100, change_shares: -2500 })).toBe(
      'Sold Out · -100.00% · -2,500',
    )
    expect(formatHolderChange({})).toBe('—')
    expect(formatHolderShareDelta(0)).toBe('0')
    expect(holderChangeTone(row)).toBe('pos')
    expect(holderChangeTone({ change_pct: -5 })).toBe('neg')
    expect(holderChangeTone({})).toBe('flat')
  })

  it('bar width is a positive fraction and larger weights get strictly wider bars', () => {
    const max = tableMaxPctOut(holders)
    expect(max).toBe(holders[0].pct_out)
    const wide = holderPctBarWidth(holders[0].pct_out, max)
    const mid = holderPctBarWidth(holders[50].pct_out, max)
    const thin = holderPctBarWidth(holders[200].pct_out, max)
    expect(wide).toBe(1)
    expect(mid).toBeGreaterThan(0)
    expect(mid).toBeLessThan(1)
    expect(thin).toBeGreaterThan(0)
    expect(wide).toBeGreaterThan(mid)
    expect(mid).toBeGreaterThan(thin)
    expect(holderPctBarWidth(null, max)).toBe(0)
    expect(holderPctBarWidth(0, max)).toBe(0)
  })

  it('sorts named rows by last-quarter change using the shipped change field', () => {
    const byChange = filterSortInstitutions(own.top_institutions, '', 'change', false)
    expect(byChange).toHaveLength(234)
    expect(byChange[0].change_pct).toBe(1.2)
    expect(byChange[byChange.length - 1].change_pct).toBe(-5.0)
  })
})
