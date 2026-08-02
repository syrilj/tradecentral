/**
 * Number and date formatting for the readouts.
 *
 * Everything here refuses to invent precision. `null`, `undefined`, `NaN` and
 * non-finite values all render as the em-dash placeholder rather than `0.00`,
 * because on a trading surface a zero that means "missing" is a lie.
 */

export const DASH = '—'

function bad(v: unknown): boolean {
  return v === null || v === undefined || (typeof v === 'number' && !Number.isFinite(v))
}

/** Fixed-decimal number. Returns "—" for missing/non-finite input. */
export function num(v: unknown, dp = 2): string {
  if (bad(v)) return DASH
  const n = Number(v)
  if (!Number.isFinite(n)) return DASH
  return n.toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
}

/** Percentage, input already in percent units (12.5 → "12.50%"). */
export function pct(v: unknown, dp = 2): string {
  if (bad(v)) return DASH
  return `${num(v, dp)}%`
}

/** Percentage from a fraction (0.125 → "12.50%"). */
export function pctFrac(v: unknown, dp = 2): string {
  if (bad(v)) return DASH
  return `${num(Number(v) * 100, dp)}%`
}

/** Signed percentage with an explicit + so direction is never ambiguous. */
export function signedPct(v: unknown, dp = 2): string {
  if (bad(v)) return DASH
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${num(n, dp)}%`
}

export function signed(v: unknown, dp = 2): string {
  if (bad(v)) return DASH
  const n = Number(v)
  return `${n > 0 ? '+' : ''}${num(n, dp)}`
}

/** Compact magnitude for volume / notional: 1.2B, 340.5M, 12.1K. */
export function compact(v: unknown, dp = 1): string {
  if (bad(v)) return DASH
  const n = Number(v)
  const a = Math.abs(n)
  const s = n < 0 ? '-' : ''
  if (a >= 1e12) return `${s}${(a / 1e12).toFixed(dp)}T`
  if (a >= 1e9) return `${s}${(a / 1e9).toFixed(dp)}B`
  if (a >= 1e6) return `${s}${(a / 1e6).toFixed(dp)}M`
  if (a >= 1e3) return `${s}${(a / 1e3).toFixed(dp)}K`
  return `${s}${a.toFixed(0)}`
}

export function usd(v: unknown, dp = 2): string {
  if (bad(v)) return DASH
  return `$${num(v, dp)}`
}

/** Sign class for colouring a signed figure. Neutral when missing. */
export function tone(v: unknown, flip = false): 'pos' | 'neg' | 'flat' {
  if (bad(v)) return 'flat'
  const n = Number(v)
  if (n === 0) return 'flat'
  const positive = flip ? n < 0 : n > 0
  return positive ? 'pos' : 'neg'
}

/** "2026-07-29" → "29 JUL 26" — unambiguous across locales. */
export function shortDate(d: string | null | undefined): string {
  if (!d) return DASH
  const t = new Date(d.length <= 10 ? `${d}T00:00:00Z` : d)
  if (Number.isNaN(t.getTime())) return String(d)
  const mon = t.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' }).toUpperCase()
  return `${String(t.getUTCDate()).padStart(2, '0')} ${mon} ${String(t.getUTCFullYear()).slice(2)}`
}

/** Seconds since an ISO/UTC stamp, rendered as a terse age: 4s / 12m / 3h. */
export function age(since: string | null | undefined): string {
  if (!since) return DASH
  const t = new Date(since.replace(' UTC', 'Z').replace(' ', 'T'))
  if (Number.isNaN(t.getTime())) return DASH
  const s = Math.max(0, (Date.now() - t.getTime()) / 1000)
  if (s < 60) return `${Math.floor(s)}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

/** Read a value out of a loosely-typed record without throwing. */
export function pick(o: unknown, ...keys: string[]): unknown {
  if (!o || typeof o !== 'object') return undefined
  for (const k of keys) {
    const v = (o as Record<string, unknown>)[k]
    if (v !== undefined && v !== null) return v
  }
  return undefined
}
