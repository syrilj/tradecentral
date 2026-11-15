/**
 * Pre-trade gamma reads.
 *
 * The API owns the math (call resistance, absolute gamma, zero gamma, nearby
 * support). This module only decides what the screen is allowed to show:
 * a missing input stays an em dash with a reason, never a zero.
 */
import { DASH, optGex, usd } from '@/format'

export const HORIZONS = [
  { dte: 7, label: '7D' },
  { dte: 30, label: '30D' },
  { dte: 90, label: '90D' },
  { dte: 365, label: 'ALL' },
] as const

export type HorizonDte = (typeof HORIZONS)[number]['dte']

export interface GammaLevel {
  level: number
  distance: number
  distance_pct: number
  dollar_gamma_m: number
  abs_dollar_gamma_m: number
  share?: number | null
  concentrated?: boolean
  share_of_peak?: number | null
}

export interface GammaStrikeRow {
  strike: number
  call_gex_m: number
  put_gex_m: number
  net_gex_m: number
  abs_gex_m: number
  call_oi: number
  put_oi: number
}

export type GammaRegime = 'positive' | 'negative' | 'neutral' | 'unmeasured'
export type ZeroGammaSide = 'above' | 'below' | 'at'

export interface GammaResistancePayload {
  symbol?: string
  asof: string | null
  stale: boolean
  stale_reason: string | null
  spot: number | null
  max_dte: number
  min_dte: number
  rate: number
  measurable: boolean
  reason: string | null
  absolute_gamma_m: number | null
  absolute_gamma_strike: number | null
  absolute_gamma_strike_m: number | null
  net_gamma_m: number | null
  call_gamma_m: number | null
  put_gamma_m: number | null
  regime: GammaRegime
  call_resistance: GammaLevel | null
  call_resistance_reason: string | null
  zero_gamma: number | null
  zero_gamma_distance: number | null
  zero_gamma_distance_pct: number | null
  zero_gamma_side: ZeroGammaSide | null
  zero_gamma_reason: string | null
  nearby_support: GammaLevel | null
  nearby_support_reason: string | null
  put_wall: GammaLevel | null
  by_strike: GammaStrikeRow[]
  quality: {
    contracts_measured: number
    contracts_in: number
    revalue_coverage: number | null
  } | null
  unit: string
  sign_convention: string
}

export type ScreenPhase = 'loading' | 'error' | 'empty' | 'populated'
export type ReadTone = 'call' | 'abs' | 'flip' | 'put'

export interface ReadCardModel {
  id: 'call_resistance' | 'absolute_gamma' | 'zero_gamma' | 'nearby_support'
  label: string
  kicker: string
  value: string | null
  sub: string | null
  note: string | null
  missing: boolean
  missingReason: string
  tone: ReadTone
}

export interface StatusNote {
  kind: 'error' | 'stale'
  text: string
}

const REASONS: Record<string, string> = {
  no_calls_above_spot: 'No call gamma above spot.',
  no_puts_below_spot: 'No put gamma below spot.',
  no_put_gamma_inside_band: 'No material put-gamma shelf inside 8% of spot.',
  put_gamma_immaterial: 'Put gamma below spot is too small to call support.',
  iv_coverage_insufficient: 'Not enough of the book has implied vol to reprice gamma.',
  no_sign_change: 'Net gamma does not cross zero in the band around spot.',
  not_revaluable: 'Gamma cannot be repriced from implied vol.',
  open_interest_unavailable: 'Open interest is missing, so gamma exposure is withheld.',
  gamma_unavailable: 'No contract has a usable gamma or implied vol.',
  outside_dte: 'No contracts fall inside this expiry window.',
  spot_missing: 'The chain has no underlying price.',
  unmeasured: 'The chain cannot be measured.',
  invalid_dte_window: 'The expiry window is empty.',
  asof_missing: 'The chain has no timestamp.',
  chain_older_than_20h: 'The chain is more than 20 hours old.',
}

export function reasonCopy(code: string | null | undefined): string {
  if (!code) return 'This read is withheld.'
  return REASONS[code] ?? 'This read is withheld.'
}

export function normalizeMaxDte(raw: unknown): HorizonDte {
  const value = Array.isArray(raw) ? raw[0] : raw
  const n = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN
  switch (n) {
    case 7:
    case 30:
    case 90:
    case 365:
      return n
    default:
      return 365
  }
}

export function cleanSymbol(raw: unknown, fallback = 'SPY'): string {
  const text = typeof raw === 'string' ? raw : ''
  const clean = text
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9.-]/g, '')
    .slice(0, 10)
  return clean || fallback
}

export function gammaResistancePath(symbol: string, maxDte: number): string {
  const sym = cleanSymbol(symbol, '')
  const dte = normalizeMaxDte(maxDte)
  return `/api/gamma/resistance?symbol=${encodeURIComponent(sym)}&max_dte=${dte}`
}

/** A payload on screen wins over a spinner. Missing payload is loading, then error. */
export function screenPhase(opts: {
  loading: boolean
  error: string | null
  payload: GammaResistancePayload | null
}): ScreenPhase {
  if (opts.payload) return opts.payload.measurable ? 'populated' : 'empty'
  if (opts.loading) return 'loading'
  if (opts.error) return 'error'
  return 'loading'
}

export function statusNotes(opts: {
  error: string | null
  payload: GammaResistancePayload | null
}): StatusNote[] {
  const notes: StatusNote[] = []
  if (opts.error && !opts.payload) {
    notes.push({ kind: 'error', text: opts.error })
    return notes
  }
  if (opts.error && opts.payload) {
    notes.push({ kind: 'error', text: opts.error })
  }
  if (opts.payload?.stale) {
    notes.push({ kind: 'stale', text: reasonCopy(opts.payload.stale_reason) })
  }
  return notes
}

function finite(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function price(value: number | null | undefined): string | null {
  if (!finite(value)) return null
  return usd(value, 2)
}

function gammaMoney(value: number | null | undefined): string | null {
  if (!finite(value)) return null
  return optGex(value)
}

function distanceText(pct: number | null | undefined): string | null {
  if (!finite(pct)) return null
  const points = pct * 100
  const sign = points > 0 ? '+' : ''
  return `${sign}${points.toFixed(2)}% from spot`
}

function regimeNote(regime: GammaRegime): string {
  switch (regime) {
    case 'positive':
      return 'Net gamma is positive at spot. In this sign convention hedges sell strength and buy weakness.'
    case 'negative':
      return 'Net gamma is negative at spot. Hedges buy strength and sell weakness, so the move extends.'
    case 'neutral':
      return 'Call and put dollar-gamma cancel at spot.'
    case 'unmeasured':
      return ''
    default: {
      const unreachable: never = regime
      return unreachable
    }
  }
}

function zeroNote(payload: GammaResistancePayload): string | null {
  const side = payload.zero_gamma_side
  if (side == null) return null
  let line: string
  switch (side) {
    case 'above':
      line = 'Spot is above the flip, where this convention dampens moves.'
      break
    case 'below':
      line = 'Spot is below the flip, where this convention amplifies moves.'
      break
    case 'at':
      line = 'Spot is on the flip.'
      break
    default: {
      const unreachable: never = side
      return unreachable
    }
  }
  const disagrees =
    (side === 'above' && payload.regime === 'negative') ||
    (side === 'below' && payload.regime === 'positive')
  if (disagrees) {
    line += ' Net gamma at spot disagrees — the book crosses zero more than once.'
  }
  return line
}

function supportNote(payload: GammaResistancePayload, missing: boolean): string | null {
  const wall = payload.put_wall
  const near = payload.nearby_support
  if (!wall || !finite(wall.level)) return null
  if (missing) {
    return `Heavier put wall ${price(wall.level) ?? DASH} is outside the nearby band.`
  }
  if (near && finite(near.level) && wall.level !== near.level) {
    return `Heavier put wall ${price(wall.level) ?? DASH}, ${distanceText(wall.distance_pct) ?? DASH}.`
  }
  return null
}

export function readCards(payload: GammaResistancePayload): ReadCardModel[] {
  const call = payload.call_resistance
  const callMissing = !call || !finite(call.level)
  const absMissing = !finite(payload.absolute_gamma_m)
  const zeroMissing = !finite(payload.zero_gamma)
  const support = payload.nearby_support
  const supportMissing = !support || !finite(support.level)

  const callSub =
    call && finite(call.level)
      ? [distanceText(call.distance_pct), gammaMoney(call.dollar_gamma_m)]
          .filter((part): part is string => part != null)
          .join(' · ')
      : null
  const absSub =
    finite(payload.absolute_gamma_m) && finite(payload.absolute_gamma_strike)
      ? `Peak ${price(payload.absolute_gamma_strike)} · ${gammaMoney(payload.absolute_gamma_strike_m) ?? DASH}`
      : null
  const zeroSub = finite(payload.zero_gamma) ? distanceText(payload.zero_gamma_distance_pct) : null
  const supportSub =
    support && finite(support.level)
      ? [distanceText(support.distance_pct), gammaMoney(support.dollar_gamma_m)]
          .filter((part): part is string => part != null)
          .join(' · ')
      : null

  return [
    {
      id: 'call_resistance',
      label: 'Call resistance',
      kicker: 'Above spot',
      value: callMissing ? null : price(call.level),
      sub: callSub || null,
      note: callMissing
        ? null
        : call.concentrated
          ? 'Dominant call dollar-gamma above spot.'
          : 'Heaviest call node above spot. The book above spot is diffuse.',
      missing: callMissing,
      missingReason: reasonCopy(payload.call_resistance_reason),
      tone: 'call',
    },
    {
      id: 'absolute_gamma',
      label: 'Absolute gamma',
      kicker: '1% move',
      value: absMissing ? null : gammaMoney(payload.absolute_gamma_m),
      sub: absSub,
      note: absMissing ? null : regimeNote(payload.regime),
      missing: absMissing,
      missingReason: reasonCopy(payload.reason ?? 'unmeasured'),
      tone: 'abs',
    },
    {
      id: 'zero_gamma',
      label: 'Zero gamma',
      kicker: 'Flip',
      value: zeroMissing ? null : price(payload.zero_gamma),
      sub: zeroSub,
      note: zeroMissing ? null : zeroNote(payload),
      missing: zeroMissing,
      missingReason: reasonCopy(payload.zero_gamma_reason),
      tone: 'flip',
    },
    {
      id: 'nearby_support',
      label: 'Nearby support',
      kicker: 'Below spot',
      value: supportMissing ? null : price(support.level),
      sub: supportSub || null,
      note: supportNote(payload, supportMissing),
      missing: supportMissing,
      missingReason: reasonCopy(payload.nearby_support_reason),
      tone: 'put',
    },
  ]
}

/** Strikes that bracket spot and the three levels, capped so the ladder stays readable. */
export function ladderRows(
  rows: GammaStrikeRow[],
  spot: number | null,
  marks: { call: number | null; zero: number | null; support: number | null },
  limit = 17,
): GammaStrikeRow[] {
  const finiteRows = rows.filter((row) => finite(row.strike) && finite(row.abs_gex_m))
  if (!finiteRows.length || !finite(spot)) return []
  const anchors = [spot, marks.call, marks.zero, marks.support].filter(finite)
  const lo = Math.min(...anchors)
  const hi = Math.max(...anchors)
  const pad = Math.max((hi - lo) * 0.15, spot * 0.01)
  let window = finiteRows.filter((row) => row.strike >= lo - pad && row.strike <= hi + pad)
  if (window.length < 5) {
    window = [...finiteRows]
      .sort((a, b) => Math.abs(a.strike - spot) - Math.abs(b.strike - spot))
      .slice(0, Math.min(limit, finiteRows.length))
  }
  window.sort((a, b) => a.strike - b.strike)
  if (window.length > limit) {
    let nearest = 0
    for (let i = 1; i < window.length; i += 1) {
      if (Math.abs(window[i].strike - spot) < Math.abs(window[nearest].strike - spot)) nearest = i
    }
    const start = Math.max(0, Math.min(nearest - Math.floor(limit / 2), window.length - limit))
    window = window.slice(start, start + limit)
  }
  return window
}
