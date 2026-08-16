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
  ratios: import('@/api').FinancialRatios | Record<string, number | null | undefined> | undefined,
  incRows: Array<{ key?: string; label?: string; values?: (number | null)[] }> | undefined,
  key: string,
): number | null {
  if (ratios && (ratios as Record<string, unknown>)[key] != null && Number.isFinite((ratios as Record<string, number>)[key])) {
    return (ratios as Record<string, number>)[key]
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

/** Internal report-native ML forecast (not Street consensus). */
export type ModelForecastStatus = 'ok' | 'missing' | 'stale' | string

export interface ModelForecastFactor {
  key?: string
  label?: string
  value?: number | null
  display?: string | null
  tone?: string | null
}

export interface ModelForecastCase {
  price?: number | null
  label?: string | null
  thesis?: string | null
}

export interface ModelForecastPayload {
  predicted_price?: number | null
  forecast_score?: number | null
  gearing_up_towards?: string | null
  status?: ModelForecastStatus | null
  label?: string | null
  horizon?: string | null
  timeframe?: string | null
  timeframe_months?: number | null
  factors?: ModelForecastFactor[] | null
  cases?: {
    bear?: ModelForecastCase | null
    base?: ModelForecastCase | null
    bull?: ModelForecastCase | null
  } | null
  decision_authorized?: boolean
  spot_used?: number | null
  spot_source?: string | null
  lookthrough_growth?: number | null
}

export interface ModelForecastCaseView {
  price: number | null
  label: string
  thesis: string | null
}

export interface ModelForecastView {
  predictedPrice: number | null
  forecastScore: number | null
  gearingUpTowards: string | null
  spotUsed: number | null
  spotSource: string | null
  lookthroughGrowth: number | null
  timeframe: string | null
  timeframeMonths: number | null
  factors: Array<{ label: string; display: string; tone: string }>
  cases: {
    bear: ModelForecastCaseView
    base: ModelForecastCaseView
    bull: ModelForecastCaseView
  }
  status: ModelForecastStatus
  ready: boolean
}

function finiteOrNull(val: number | null | undefined): number | null {
  if (val == null || !Number.isFinite(val)) return null
  return val
}

const EMPTY_CASE: ModelForecastCaseView = { price: null, label: '', thesis: null }

function presentCase(raw: ModelForecastCase | null | undefined, fallback: string): ModelForecastCaseView {
  if (!raw) return { ...EMPTY_CASE, label: fallback }
  const thesis = raw.thesis && raw.thesis.trim() && raw.thesis !== '0' ? raw.thesis : null
  return {
    price: finiteOrNull(raw.price),
    label: raw.label || fallback,
    thesis,
  }
}

function emptyForecastView(status: ModelForecastStatus): ModelForecastView {
  return {
    predictedPrice: null,
    forecastScore: null,
    gearingUpTowards: null,
    spotUsed: null,
    spotSource: null,
    lookthroughGrowth: null,
    timeframe: null,
    timeframeMonths: null,
    factors: [],
    cases: {
      bear: { ...EMPTY_CASE, label: 'Bear' },
      base: { ...EMPTY_CASE, label: 'Base' },
      bull: { ...EMPTY_CASE, label: 'Bull' },
    },
    status,
    ready: false,
  }
}

/** Present the model forecast. Missing inputs stay dash-ready nulls — never a fake 0. */
export function presentModelForecast(
  raw: ModelForecastPayload | null | undefined,
): ModelForecastView {
  const status = (raw?.status || 'missing') as ModelForecastStatus
  if (raw == null || status === 'missing') {
    return emptyForecastView('missing')
  }
  const predictedPrice = finiteOrNull(raw.predicted_price)
  const forecastScore = finiteOrNull(raw.forecast_score)
  const gearingRaw = raw.gearing_up_towards
  const gearingUpTowards =
    !gearingRaw || gearingRaw.trim() === '' || gearingRaw === '0' ? null : gearingRaw
  const factors = (raw.factors || [])
    .filter((f) => f && f.display && f.display !== '0' && f.display.trim() !== '')
    .map((f) => ({
      label: f.label || f.key || 'Factor',
      display: f.display as string,
      tone: f.tone || 'flat',
    }))
  const timeframe =
    raw.timeframe && raw.timeframe.trim() && raw.timeframe !== '0' ? raw.timeframe : null
  return {
    predictedPrice,
    forecastScore,
    gearingUpTowards,
    spotUsed: finiteOrNull(raw.spot_used),
    spotSource: raw.spot_source || null,
    lookthroughGrowth: finiteOrNull(raw.lookthrough_growth),
    timeframe,
    timeframeMonths: finiteOrNull(raw.timeframe_months),
    factors,
    cases: {
      bear: presentCase(raw.cases?.bear, 'Bear'),
      base: presentCase(raw.cases?.base, 'Base'),
      bull: presentCase(raw.cases?.bull, 'Bull'),
    },
    status,
    ready: status === 'ok' && predictedPrice != null && forecastScore != null,
  }
}

export function formatModelPredictedPrice(val: number | null | undefined): string {
  if (val == null || !Number.isFinite(val)) return DASH
  return `$${val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export function formatModelForecastScore(val: number | null | undefined): string {
  if (val == null || !Number.isFinite(val)) return DASH
  return val.toFixed(1)
}

export function formatGearingUp(val: string | null | undefined): string {
  if (val == null || val.trim() === '' || val === '0') return DASH
  return val
}

