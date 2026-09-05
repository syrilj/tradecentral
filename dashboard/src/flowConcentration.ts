/**
 * Where the tape's premium actually sits on the expiry curve.
 *
 * The provider window carries `expiry` and `dte` on every print, so premium
 * concentration by expiration is directly measurable — unlike direction
 * (`aggressor`, `signed_premium` and `bias` come back null on every print) or
 * open interest (never populated). Nothing here infers a side; it reports how
 * much measured premium landed on each expiration and nothing more.
 *
 * `otm_pct` is deliberately NOT used as a moneyness source. The provider
 * clamps it at 0, so a genuinely in-the-money print reports 0 and reads as
 * "ATM". True moneyness is recomputed from `strike` against
 * `underlying_price`, both of which are populated on every print.
 */

import { DTE_MISSING } from './flowDisplay'

export const EXPIRY_MISSING = 'EXPIRY MISSING'

/** Only the print fields this module measures. */
export interface ConcentrationPrint {
  premium?: number | null
  contracts?: number | null
  volume?: number | null
  dte?: number | null
  expiry?: string | null
  right?: string | null
  strike?: number | null
  underlying_price?: number | null
}

export type HorizonKey = 'zero' | 'week' | 'month' | 'beyond'

/** A disjoint slice of the expiry curve. The four shares sum to 1. */
export interface HorizonShare {
  key: HorizonKey
  label: string
  /** Shorthand for the DTE range this bucket covers. */
  range: string
  premium: number
  prints: number
  /** Fraction of measured premium, or null when nothing was measured. */
  share: number | null
}

/** One expiration date, aggregated across every symbol on the tape. */
export interface ExpiryBucket {
  /** ISO date as the provider reported it. */
  key: string
  /** Short display date, e.g. `Sep 11`. */
  label: string
  dte: number | null
  dteLabel: string
  premium: number
  callPremium: number
  putPremium: number
  contracts: number
  prints: number
  /** Fraction of measured premium, or null when nothing was measured. */
  share: number | null
}

export interface FlowConcentration {
  /** Premium across prints that carried a usable figure. */
  totalPremium: number
  /** Prints that carried a usable premium figure. */
  measuredPrints: number
  /** Prints skipped for want of a premium figure. */
  unmeasuredPrints: number
  /** Measured prints with no expiry — excluded from `expiries`. */
  missingExpiry: number
  /** Measured prints with no DTE — still bucketed by expiry, not by horizon. */
  missingDte: number
  horizons: HorizonShare[]
  /** Every expiration on the tape, richest premium first. */
  expiries: ExpiryBucket[]
  /** Largest single-expiry share, or null when nothing was measured. */
  peakShare: number | null
}

const HORIZON_META: Array<{ key: HorizonKey; label: string; range: string }> = [
  { key: 'zero', label: 'Same day', range: '0DTE' },
  { key: 'week', label: 'This week', range: '1–7D' },
  { key: 'month', label: 'This month', range: '8–31D' },
  { key: 'beyond', label: 'Beyond', range: '32D+' },
]

function horizonFor(dte: number): HorizonKey {
  if (dte <= 0) return 'zero'
  if (dte <= 7) return 'week'
  if (dte <= 31) return 'month'
  return 'beyond'
}

/**
 * `Number(null)` is 0 and `Number('')` is 0, so a bare `Number.isFinite` check
 * turns a missing DTE into a same-day print and a missing contract count into
 * a real zero. Absent values are rejected before the coercion.
 */
function finite(value: unknown): number | null {
  if (value == null || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

/**
 * `2026-09-11` → `Sep 11`. Parsed as a plain calendar date rather than through
 * `Date`, so an expiry never slides a day on a westward timezone.
 */
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function expiryLabel(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return iso
  const month = MONTHS[Number(m[2]) - 1]
  if (!month) return iso
  return `${month} ${Number(m[3])}`
}

/** `0D` for same-day, `11D` otherwise — matching the tape's DTE badges. */
export function dteLabel(dte: number | null): string {
  if (dte == null) return DTE_MISSING
  return `${Math.max(0, Math.round(dte))}D`
}

/**
 * True moneyness from strike against spot: positive is out-of-the-money.
 * Returns null when either leg is missing or spot is non-positive.
 */
export function trueMoneyness(print: ConcentrationPrint): number | null {
  const strike = finite(print.strike)
  const spot = finite(print.underlying_price)
  if (strike == null || spot == null || spot <= 0) return null
  const right = String(print.right || '').toLowerCase()
  if (right !== 'call' && right !== 'put') return null
  return right === 'call' ? (strike - spot) / spot : (spot - strike) / spot
}

/**
 * Aggregate a provider window by expiration.
 *
 * A print counts only when it carries a finite premium above zero — the tape
 * reports premium in dollars, so a zero or negative figure is a gap rather
 * than a reading, and averaging it in would understate every share.
 */
export function computeFlowConcentration(
  prints: readonly ConcentrationPrint[] | null | undefined,
): FlowConcentration {
  const empty: FlowConcentration = {
    totalPremium: 0,
    measuredPrints: 0,
    unmeasuredPrints: 0,
    missingExpiry: 0,
    missingDte: 0,
    horizons: HORIZON_META.map((h) => ({ ...h, premium: 0, prints: 0, share: null })),
    expiries: [],
    peakShare: null,
  }
  if (!prints || prints.length === 0) return empty

  let totalPremium = 0
  let measuredPrints = 0
  let unmeasuredPrints = 0
  let missingExpiry = 0
  let missingDte = 0

  const horizonPremium = new Map<HorizonKey, { premium: number; prints: number }>()
  const byExpiry = new Map<string, ExpiryBucket>()

  for (const print of prints) {
    const premium = finite(print.premium)
    if (premium == null || premium <= 0) {
      unmeasuredPrints++
      continue
    }
    totalPremium += premium
    measuredPrints++

    const dte = finite(print.dte)
    if (dte == null) {
      missingDte++
    } else {
      const key = horizonFor(dte)
      const slot = horizonPremium.get(key) ?? { premium: 0, prints: 0 }
      slot.premium += premium
      slot.prints++
      horizonPremium.set(key, slot)
    }

    const expiry = String(print.expiry || '').trim()
    if (!expiry) {
      missingExpiry++
      continue
    }

    let bucket = byExpiry.get(expiry)
    if (!bucket) {
      bucket = {
        key: expiry,
        label: expiryLabel(expiry),
        dte: dte == null ? null : Math.round(dte),
        dteLabel: dteLabel(dte),
        premium: 0,
        callPremium: 0,
        putPremium: 0,
        contracts: 0,
        prints: 0,
        share: null,
      }
      byExpiry.set(expiry, bucket)
    }
    // A later print can supply the DTE an earlier one lacked.
    if (bucket.dte == null && dte != null) {
      bucket.dte = Math.round(dte)
      bucket.dteLabel = dteLabel(dte)
    }
    bucket.premium += premium
    bucket.prints++
    const contracts = finite(print.contracts) ?? finite(print.volume)
    if (contracts != null && contracts > 0) bucket.contracts += contracts
    const right = String(print.right || '').toLowerCase()
    if (right === 'call') bucket.callPremium += premium
    else if (right === 'put') bucket.putPremium += premium
  }

  const denominator = totalPremium > 0 ? totalPremium : null

  const horizons: HorizonShare[] = HORIZON_META.map((meta) => {
    const slot = horizonPremium.get(meta.key)
    return {
      ...meta,
      premium: slot?.premium ?? 0,
      prints: slot?.prints ?? 0,
      share: denominator == null ? null : (slot?.premium ?? 0) / denominator,
    }
  })

  const expiries = [...byExpiry.values()]
    .map((bucket) => ({
      ...bucket,
      share: denominator == null ? null : bucket.premium / denominator,
    }))
    .sort((a, b) => b.premium - a.premium)

  return {
    totalPremium,
    measuredPrints,
    unmeasuredPrints,
    missingExpiry,
    missingDte,
    horizons,
    expiries,
    peakShare: expiries.length > 0 ? expiries[0].share : null,
  }
}
