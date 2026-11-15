/**
 * Live options panel.
 *
 * Gamma math stays on the server. This module only decides what the screen
 * may draw: a missing close, level, or chain stays blank, never a zero.
 */
import type { GammaResistancePayload, GammaStrikeRow } from '@/gammaResistance'

export interface ProfileRow {
  strike: number
  call_gex_m: number
  put_gex_m: number
  net_gex_m: number
  call_oi: number
  put_oi: number
}

export type ChartStance = 'agrees' | 'opposite' | 'stretched'
export type WatchRole =
  'call_resistance' | 'absolute_gamma' | 'zero_gamma' | 'nearby_support' | 'put_wall'

export interface WatchLevel {
  role: WatchRole
  label: string
  level: number
  distance_pct: number
}

export interface ChartClose {
  date: string | null
  close: number
}

export interface LiveChart {
  closes: ChartClose[]
  stance: ChartStance | null
  reason: string | null
  sentence: string
  move_pct: number | null
  reference_role: string | null
  reference_level: number | null
}

export interface LiveOptionsPayload {
  symbol?: string
  decision_authorized: false
  gamma: GammaResistancePayload
  chart: LiveChart
  levels: WatchLevel[]
}

export interface PriceGuide {
  y: number
  level: number
}

export interface PriceGeometry {
  line: string
  guides: PriceGuide[]
}

const GUIDE_BAND = 0.15

export function liveOptionsPath(symbol: string, maxDte: number): string {
  const sym = symbol
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9.-]/g, '')
    .slice(0, 10)
  const dte = maxDte === 7 || maxDte === 30 || maxDte === 90 || maxDte === 365 ? maxDte : 365
  return `/api/live-options?symbol=${encodeURIComponent(sym)}&max_dte=${dte}`
}

export function stanceWord(stance: ChartStance | null): string {
  switch (stance) {
    case 'agrees':
      return 'Agrees'
    case 'opposite':
      return 'Opposite'
    case 'stretched':
      return 'Stretched'
    case null:
      return '—'
    default: {
      const unreachable: never = stance
      return unreachable
    }
  }
}

function finite(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

/** Strike rows the profile can draw. A missing greek is dropped, not drawn as zero. */
export function profileRows(rows: GammaStrikeRow[]): ProfileRow[] {
  const out: ProfileRow[] = []
  for (const row of rows) {
    if (
      !finite(row.strike) ||
      row.strike <= 0 ||
      !finite(row.call_gex_m) ||
      !finite(row.put_gex_m) ||
      !finite(row.net_gex_m) ||
      !finite(row.call_oi) ||
      !finite(row.put_oi)
    ) {
      continue
    }
    out.push({
      strike: row.strike,
      call_gex_m: row.call_gex_m,
      put_gex_m: row.put_gex_m,
      net_gex_m: row.net_gex_m,
      call_oi: row.call_oi,
      put_oi: row.put_oi,
    })
  }
  return out
}

export function positiveLevel(value: number | null | undefined): number | null {
  if (!finite(value) || value <= 0) return null
  return value
}

/**
 * Close path in a fixed box. Guides far from the last close are left off so
 * one distant shelf cannot flatten the path. Fewer than two closes draws nothing.
 */
export function priceGeometry(
  closes: readonly number[],
  guides: readonly number[],
  width: number,
  height: number,
): PriceGeometry | null {
  const ys = closes.filter((value) => finite(value) && value > 0)
  if (ys.length < 2 || width < 40 || height < 24) return null
  const last = ys[ys.length - 1]
  const near = guides.filter(
    (level) => finite(level) && level > 0 && Math.abs(level - last) / last <= GUIDE_BAND,
  )
  let lo = Math.min(...ys, ...near)
  let hi = Math.max(...ys, ...near)
  if (!(hi > lo)) {
    lo -= last * 0.01
    hi += last * 0.01
  }
  const padX = 8
  const padY = 10
  const innerW = width - padX * 2
  const innerH = height - padY * 2
  const xAt = (index: number) => padX + (innerW * index) / (ys.length - 1)
  const yAt = (price: number) => padY + ((hi - price) / (hi - lo)) * innerH
  const line = ys
    .map(
      (price, index) =>
        `${index === 0 ? 'M' : 'L'}${xAt(index).toFixed(2)} ${yAt(price).toFixed(2)}`,
    )
    .join(' ')
  return {
    line,
    guides: near.map((level) => ({ y: yAt(level), level })),
  }
}
