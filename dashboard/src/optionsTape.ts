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

export function printWhy(row: Pick<OptionsTapeRow, 'why' | 'anomaly_flags' | 'is_unusual' | 'is_sweep' | 'is_momentum' | 'is_moonshot'>): string[] {
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
