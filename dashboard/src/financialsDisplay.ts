/**
 * Formatting and presentation helpers for Financial Statements, Company Profile,
 * Insiders, Government, and Ownership views in TradeCentral.
 */
import { DASH } from './format'

/** Format financial values (Revenue, Net Income, Assets) with sensible B/M/K units */
export function formatBigUsd(val: number | null | undefined, decimals = 2): string {
  if (val == null || !Number.isFinite(val)) return DASH
  const abs = Math.abs(val)
  const sign = val < 0 ? '-' : ''
  if (abs >= 1_000_000_000_000) {
    return `${sign}$${(abs / 1_000_000_000_000).toFixed(decimals)}T`
  }
  if (abs >= 1_000_000_000) {
    return `${sign}$${(abs / 1_000_000_000).toFixed(decimals)}B`
  }
  if (abs >= 1_000_000) {
    return `${sign}$${(abs / 1_000_000).toFixed(decimals)}M`
  }
  if (abs >= 1_000) {
    return `${sign}$${(abs / 1_000).toFixed(decimals)}K`
  }
  return `${sign}$${abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** Format currency per-share (e.g. EPS $0.45 or -$0.15) */
export function formatPerShare(val: number | null | undefined, decimals = 2): string {
  if (val == null || !Number.isFinite(val)) return DASH
  const sign = val < 0 ? '-' : ''
  const abs = Math.abs(val)
  return `${sign}$${abs.toFixed(decimals)}`
}

/** Format table row value depending on row format specification */
export function formatStatementCell(
  val: number | null | undefined,
  format?: 'currency' | 'pct' | 'compact' | 'ratio' | string,
): string {
  if (val == null || !Number.isFinite(val)) return DASH
  if (format === 'currency') {
    return formatPerShare(val, 2)
  }
  if (format === 'pct') {
    return `${val >= 0 ? '+' : ''}${val.toFixed(1)}%`
  }
  if (format === 'ratio') {
    return val.toFixed(2)
  }
  return formatBigUsd(val, 2)
}

/** Compute year-over-year or period-over-period percentage change */
export function calculateGrowth(
  curr: number | null | undefined,
  prev: number | null | undefined,
): number | null {
  if (curr == null || prev == null || prev === 0 || !Number.isFinite(curr) || !Number.isFinite(prev)) {
    return null
  }
  return ((curr - prev) / Math.abs(prev)) * 100
}

/** Helper tone class for margin/growth cells */
export function getGrowthTone(growth: number | null | undefined): 'pos' | 'neg' | 'flat' {
  if (growth == null || !Number.isFinite(growth)) return 'flat'
  if (growth > 0.05) return 'pos'
  if (growth < -0.05) return 'neg'
  return 'flat'
}

/** Return human readable period name: '2026-06-30' -> 'Q2 2026' or '2025' */
export function formatPeriodHeader(periodDate: string, isQuarterly: boolean): string {
  if (!periodDate) return DASH
  if (!isQuarterly) {
    return periodDate.slice(0, 4)
  }
  const parts = periodDate.split('-')
  if (parts.length < 2) return periodDate
  const yr = parts[0]
  const mo = parseInt(parts[1], 10)
  const q = Math.ceil(mo / 3)
  return `Q${q} '${yr.slice(2)}`
}

/** Sanitize and format data source identifiers for clean institutional display */
export function formatSourceLabel(source: string | null | undefined): string {
  if (!source) return 'EXCHANGE BARS'
  const s = source.trim().toUpperCase()
  if (s.includes('LSE_EQUITY_CANDLES') || s.includes('EQUITY_CANDLES')) return 'EXCHANGE BARS'
  if (s.includes('QLIB_DAILY_CANDLES') || s.includes('QLIB')) return 'DAILY BARS'
  if (s.includes('SYNTHETIC')) return 'SYNTHETIC BARS'
  if (s.includes('YFINANCE')) return 'EXCHANGE BARS'
  if (s.includes('POLYGON') || s.includes('ALPACA')) return 'REAL-TIME FEED'
  return s.replace(/_/g, ' ')
}

/** Derive ratio with statement fallback if summary ratio is unavailable */
export function getDerivedRatio(
  ratios: Record<string, number | null | undefined> | undefined,
  incRows: Array<{ key?: string; label?: string; values?: (number | null)[] }> | undefined,
  key: string,
): number | null {
  if (ratios && ratios[key] != null && Number.isFinite(ratios[key])) {
    return ratios[key] as number
  }
  if (!incRows || !incRows.length) return null

  if (key === 'gross_margin') {
    const revRow = incRows.find((r) => /revenue|sales/i.test(r.key || r.label || ''))
    const gpRow = incRows.find((r) => /gross[ _]?profit/i.test(r.key || r.label || ''))
    if (revRow?.values?.[0] && gpRow?.values?.[0]) {
      return Number(((gpRow.values[0] / revRow.values[0]) * 100).toFixed(2))
    }
  }

  if (key === 'net_margin') {
    const revRow = incRows.find((r) => /revenue|sales/i.test(r.key || r.label || ''))
    const niRow = incRows.find((r) => /net[ _]?income/i.test(r.key || r.label || ''))
    if (revRow?.values?.[0] && niRow?.values?.[0]) {
      return Number(((niRow.values[0] / revRow.values[0]) * 100).toFixed(2))
    }
  }

  if (key === 'operating_margin') {
    const revRow = incRows.find((r) => /revenue|sales/i.test(r.key || r.label || ''))
    const opRow = incRows.find((r) => /operating[ _]?(income|profit)/i.test(r.key || r.label || ''))
    if (revRow?.values?.[0] && opRow?.values?.[0]) {
      return Number(((opRow.values[0] / revRow.values[0]) * 100).toFixed(2))
    }
  }

  return null
}

