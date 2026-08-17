/**
 * Institution-table presentation: reported count vs named rows, filter/sort,
 * pagination, last-quarter change text, and proportional % bars.
 */
import type { OwnershipPayload, TopInstitutionalHolder } from './api'
import { DASH, signedPct, tone } from './format'

export type InstitutionSortField = 'shares' | 'pct_out' | 'value' | 'holder' | 'date' | 'change'
export type InstitutionPageSize = number | 'all'

export type HolderChangeFields = {
  change_pct?: number | null
  change_shares?: number | null
  change_label?: string | null
}

export function listedInstitutionCount(
  own: Pick<OwnershipPayload, 'top_institutions'> | null | undefined,
): number {
  return own?.top_institutions?.length ?? 0
}

export function reportedInstitutionCount(
  own: Pick<OwnershipPayload, 'institutions_count' | 'top_institutions'> | null | undefined,
): number | null {
  const raw = own?.institutions_count
  if (raw == null || !Number.isFinite(raw) || raw < 0) return null
  return Math.trunc(raw)
}

export function formatInstitutionsKpi(listed: number, reported: number | null): string {
  if (reported != null && Number.isFinite(reported)) {
    return `${reported} Institutions`
  }
  return `${listed} Institutions`
}

export function formatInstitutionsPanelMeta(opts: {
  filtered: number
  listed: number
  reported: number | null
  searching: boolean
}): string {
  const { filtered, listed, reported, searching } = opts
  if (searching) {
    const named = `${filtered} of ${listed} named`
    if (reported != null && Number.isFinite(reported)) {
      return `${named} · ${reported} reported`
    }
    return named
  }
  if (reported != null && Number.isFinite(reported) && reported > listed) {
    return `${listed} of ${reported} Institutions`
  }
  if (reported != null && Number.isFinite(reported)) {
    return `${reported} Institutions`
  }
  return `${listed} Institutions`
}

export function filterSortInstitutions(
  list: TopInstitutionalHolder[],
  query: string,
  sortField: InstitutionSortField,
  sortAsc: boolean,
): TopInstitutionalHolder[] {
  let filtered = list.slice()
  const q = query.trim().toLowerCase()
  if (q) {
    filtered = filtered.filter((inst) => (inst.holder || '').toLowerCase().includes(q))
  }
  filtered.sort((a, b) => {
    let diff = 0
    if (sortField === 'holder') {
      diff = (a.holder || '').localeCompare(b.holder || '')
    } else if (sortField === 'pct_out') {
      diff = (a.pct_out ?? 0) - (b.pct_out ?? 0)
    } else if (sortField === 'value') {
      diff = (a.value ?? 0) - (b.value ?? 0)
    } else if (sortField === 'date') {
      diff = (a.date_reported || '').localeCompare(b.date_reported || '')
    } else if (sortField === 'change') {
      const av = a.change_pct ?? a.change_shares ?? 0
      const bv = b.change_pct ?? b.change_shares ?? 0
      diff = av - bv
    } else {
      diff = (a.shares ?? 0) - (b.shares ?? 0)
    }
    return sortAsc ? diff : -diff
  })
  return filtered
}

export function institutionPageCount(filteredLen: number, pageSize: InstitutionPageSize): number {
  if (pageSize === 'all') return 1
  const size = Number(pageSize)
  if (!Number.isFinite(size) || size <= 0) return 1
  return Math.max(1, Math.ceil(filteredLen / size))
}

export function paginateHolders<T>(list: T[], page: number, pageSize: InstitutionPageSize): T[] {
  if (pageSize === 'all') return list
  const size = Number(pageSize)
  if (!Number.isFinite(size) || size <= 0) return list
  const safePage = Math.max(1, page)
  const start = (safePage - 1) * size
  return list.slice(start, start + size)
}

export function formatHolderShareDelta(shares: number | null | undefined): string {
  if (shares == null || !Number.isFinite(shares)) return DASH
  const n = Math.trunc(shares)
  const formatted = Math.abs(n).toLocaleString('en-US')
  if (n > 0) return `+${formatted}`
  if (n < 0) return `-${formatted}`
  return '0'
}

/** Last-quarter change: period % and/or share delta. Never % of outstanding. */
export function formatHolderChange(row: HolderChangeFields | null | undefined): string {
  if (!row) return DASH
  const bits: string[] = []
  if (row.change_label) bits.push(row.change_label)
  if (row.change_pct != null && Number.isFinite(row.change_pct)) {
    bits.push(signedPct(row.change_pct))
  }
  if (row.change_shares != null && Number.isFinite(row.change_shares)) {
    bits.push(formatHolderShareDelta(row.change_shares))
  }
  return bits.length ? bits.join(' · ') : DASH
}

export function holderChangeTone(row: HolderChangeFields | null | undefined): 'pos' | 'neg' | 'flat' {
  if (!row) return 'flat'
  if (row.change_pct != null && Number.isFinite(row.change_pct)) return tone(row.change_pct)
  if (row.change_shares != null && Number.isFinite(row.change_shares)) return tone(row.change_shares)
  return 'flat'
}

export function tableMaxPctOut(rows: Array<{ pct_out?: number | null }> | null | undefined): number {
  let max = 0
  for (const row of rows ?? []) {
    const pct = row.pct_out
    if (pct != null && Number.isFinite(pct) && pct > max) max = pct
  }
  return max
}

/** Positive fraction of the track (0–1). Scaled to the table max, not a fixed stub. */
export function holderPctBarWidth(
  pct: number | null | undefined,
  tableMaxPct: number | null | undefined,
): number {
  if (pct == null || !Number.isFinite(pct) || pct <= 0) return 0
  const scale = tableMaxPct != null && Number.isFinite(tableMaxPct) && tableMaxPct > 0 ? tableMaxPct : pct
  return Math.min(1, pct / scale)
}

export type OwnershipMixKey = 'inst' | 'insider' | 'retail'

export interface OwnershipMixRow {
  key: OwnershipMixKey
  label: string
  pct: number | null
  widthPct: number | null
}

export interface OwnershipMixView {
  rows: OwnershipMixRow[]
  observedSum: number | null
  /** True only when the three slices look like a 100% partition. */
  partition: boolean
}

function finitePct(val: number | null | undefined): number | null {
  if (val == null || !Number.isFinite(val)) return null
  return val
}

/**
 * Institutions, insiders, and retail/float are not a clean partition —
 * 13F + insider holdings can overlap. Render independent meters, never a
 * stacked bar that overflows 100% and clips the labels.
 */
export function presentOwnershipMix(
  breakdown: OwnershipPayload['breakdown'] | null | undefined,
): OwnershipMixView {
  const parts: Array<{ key: OwnershipMixKey; label: string; raw: number | null }> = [
    { key: 'inst', label: 'Institutions', raw: finitePct(breakdown?.institutional_pct) },
    { key: 'insider', label: 'Insiders', raw: finitePct(breakdown?.insider_pct) },
    { key: 'retail', label: 'Retail / float', raw: finitePct(breakdown?.retail_float_pct) },
  ]
  const observed = parts.filter((p) => p.raw != null)
  const sum = observed.reduce((acc, p) => acc + (p.raw as number), 0)
  return {
    rows: parts.map((p) => ({
      key: p.key,
      label: p.label,
      pct: p.raw,
      widthPct: p.raw == null ? null : Math.min(100, Math.max(0, p.raw)),
    })),
    observedSum: observed.length ? Number(sum.toFixed(1)) : null,
    partition: observed.length >= 2 && sum >= 90 && sum <= 100.5,
  }
}
