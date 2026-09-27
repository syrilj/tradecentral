import type { OptionsTapeRow } from '@/api'

export type ActivityLean = 'bullish' | 'bearish' | 'mixed' | 'neutral'

export interface ActivityLeanRead {
  lean: ActivityLean
  label: string
  source: string
  sourceLabel: string
  authorized: false
  title: string
}

const SOURCE_LABELS: Record<string, string> = {
  signed_flow: 'signed aggressor premium',
  model_context: 'model / PEAD context',
  premium_and_price: 'call/put premium + price',
  call_put_premium: 'call vs put premium',
  call_put_premium_vs_price: 'call/put premium vs price',
  price_impulse: 'price impulse',
  none: 'no lean',
}

export function activityLeanRead(input: {
  activity_lean?: string | null
  activity_lean_source?: string | null
  activity_lean_label?: string | null
  decision_authorized?: boolean | null
}): ActivityLeanRead {
  const raw = String(input.activity_lean || 'neutral').toLowerCase()
  const lean: ActivityLean =
    raw === 'bullish' || raw === 'bearish' || raw === 'mixed' ? raw : 'neutral'
  const source = String(input.activity_lean_source || 'none')
  const sourceLabel = SOURCE_LABELS[source] || source.replaceAll('_', ' ')
  const label = String(input.activity_lean_label || lean).toUpperCase()
  const title =
    lean === 'neutral'
      ? 'No bullish/bearish activity sign. Call/put identity is not a trade side.'
      : `${label} activity sign from ${sourceLabel}. Not trade-authorized.`
  return {
    lean,
    label,
    source,
    sourceLabel,
    authorized: false,
    title,
  }
}

export function printWhy(
  row: Pick<
    OptionsTapeRow,
    'why' | 'anomaly_flags' | 'is_unusual' | 'is_sweep' | 'is_momentum' | 'is_moonshot'
  >,
): string[] {
  if (Array.isArray(row.why) && row.why.length) return row.why.map(String)
  const flags = (row.anomaly_flags || []).map(String)
  const reasons: string[] = []
  if (row.is_unusual) reasons.push('near-dated OTM')
  if (row.is_sweep || flags.includes('sweep_burst')) reasons.push('sweep')
  if (flags.includes('premium_outlier')) reasons.push('premium outlier')
  if (flags.includes('volume_outlier')) reasons.push('size outlier')
  if (flags.includes('repeat_cluster')) reasons.push('repeat cluster')
  if (row.is_momentum) reasons.push('high relative volume')
  if (row.is_moonshot) reasons.push('cheap far-OTM')
  return reasons
}

export function formatTapeTime(ts: string | null | undefined): string {
  if (!ts) return '—'
  const str = String(ts).trim()
  if (!str) return '—'
  if (/^\d{2}:\d{2}(:\d{2})?$/.test(str)) {
    return str.length === 5 ? `${str}:00` : str
  }
  if (str.includes('T')) {
    const timePart = str.split('T')[1]
    if (timePart && timePart.length >= 8) return timePart.slice(0, 8)
  }
  const ms = Date.parse(str)
  if (!Number.isNaN(ms)) {
    const d = new Date(ms)
    return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}:${String(d.getUTCSeconds()).padStart(2, '0')}`
  }
  return str.length >= 19 ? str.slice(11, 19) : str.slice(0, 8)
}

/**
 * Calendar date of a print, as `DD MMM` (UTC), for the tape's Time column.
 *
 * The tape spans more than one session whenever the premium floor is high
 * enough that the provider's row budget reaches back past today, so a bare
 * wall-clock time is ambiguous — `09:15:30` alone cannot say which day the
 * print landed on. Returns `''` (not a dash) when the stamp carries no date
 * at all, so the caller can simply omit the date rather than render a hole.
 */
export function formatTapeDate(ts: string | null | undefined): string {
  if (!ts) return ''
  const str = String(ts).trim()
  if (!str) return ''
  // Time-only stamps ("14:32:05") have no date to show.
  if (/^\d{2}:\d{2}(:\d{2})?$/.test(str)) return ''
  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(str)
  const d = iso
    ? new Date(Date.UTC(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3])))
    : new Date(Date.parse(str))
  if (Number.isNaN(d.getTime())) return ''
  const months = [
    'JAN',
    'FEB',
    'MAR',
    'APR',
    'MAY',
    'JUN',
    'JUL',
    'AUG',
    'SEP',
    'OCT',
    'NOV',
    'DEC',
  ]
  return `${String(d.getUTCDate()).padStart(2, '0')} ${months[d.getUTCMonth()]}`
}

/**
 * True when a print's stamp is a bare calendar date (midnight, no intraday
 * clock) — an end-of-day roll-up rather than a timed print. Rendering those
 * as `00:00:00` reads as a real fill at midnight, which no options tape has.
 */
export function isDateOnlyStamp(ts: string | null | undefined): boolean {
  if (!ts) return false
  const str = String(ts).trim()
  if (!str) return false
  if (!str.includes('T')) return /^\d{4}-\d{2}-\d{2}$/.test(str)
  return /T00:00:00(\.0+)?(Z|[+-]\d{2}:?\d{2})?$/.test(str)
}
