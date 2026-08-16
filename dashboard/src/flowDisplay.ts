/**
 * Shared Flow display helpers — token classes, named empties, and pulse copy.
 * Kept pure so tests can drive the shipped labels without mounting Vue/Clerk.
 */

export type FlowLeanState =
  | 'bullish'
  | 'bearish'
  | 'mixed'
  | 'unknown'
  | 'model-bullish'
  | 'model-bearish'

export type FlowPriority = 'now' | 'soon' | 'watch' | 'skip'

export const NO_SIGNED_SIDE = 'NO SIGNED SIDE'
export const NO_SIGNAL = 'NO SIGNAL'
export const NO_MIX_IN_SAMPLE = 'NO MIX IN SAMPLE'
export const NO_STRIKE_IN_TAPE = 'NO STRIKE IN TAPE'
export const FIRST_WINDOW_BASELINE = 'first window baseline'
export const PREVIOUS_PROVIDER_WINDOW = 'previous provider window'

/** Instrument token class for lean / direction chips. */
export function flowLeanTokenClass(state: string | null | undefined): string {
  if (state === 'bullish' || state === 'model-bullish') return 'token-long'
  if (state === 'bearish' || state === 'model-bearish') return 'token-short'
  if (state === 'mixed') return 'token-warn'
  return 'token-unsigned'
}

/**
 * Signed buy/sell print encoding. Green = long/buy, red = short/sell.
 * Call/put identity and missing side stay unsigned.
 */
export function signedPrintTokenClass(side: string | null | undefined): string {
  const normalized = String(side ?? '').trim().toLowerCase()
  if (normalized === 'buy' || normalized === 'long' || normalized === 'bullish') return 'token-long'
  if (normalized === 'sell' || normalized === 'short' || normalized === 'bearish') return 'token-short'
  return 'token-unsigned'
}

/** Instrument token class for desk-priority chips. */
export function flowPriorityTokenClass(priority: string | null | undefined): string {
  if (priority === 'now') return 'token-long'
  if (priority === 'soon') return 'token-warn'
  if (priority === 'skip') return 'token-unsigned'
  return 'token-ink'
}

export function namedEmpty(
  value: unknown,
  emptyLabel: string,
): string {
  if (value == null || value === '') return emptyLabel
  if (typeof value === 'number' && !Number.isFinite(value)) return emptyLabel
  return String(value)
}

export function mixShareLabel(share: number | null | undefined, formatted: string): string {
  if (share == null || !Number.isFinite(share)) return NO_MIX_IN_SAMPLE
  return formatted
}

export function concentrationLabel(
  topStrike: string | null | undefined,
  fallback: string,
): string {
  if (!topStrike || topStrike === 'Unavailable') {
    return fallback || NO_STRIKE_IN_TAPE
  }
  return topStrike
}

export function pulseWindowCopy(input: {
  baseline: boolean
  newPrints: number
  newPremiumLabel: string
  windowDeltaLabel: string
}): string {
  if (input.baseline) return FIRST_WINDOW_BASELINE
  if (input.newPrints > 0) {
    return `${input.newPremiumLabel} · ${input.newPrints} new vs ${PREVIOUS_PROVIDER_WINDOW}`
  }
  return `${input.windowDeltaLabel} vs ${PREVIOUS_PROVIDER_WINDOW}`
}

/* ------------------------------------------------------------------ Flow Order Taxonomy & Ratios */

export type FlowOrderType =
  | 'golden_sweep'
  | 'sweep'
  | 'block'
  | 'split'
  | 'multileg'
  | 'standard'

export interface FlowBadgeMeta {
  type: FlowOrderType
  label: string
  className: string
  description: string
}

export interface FlowOrderInput {
  trade_class?: string | null
  is_sweep?: boolean | null
  is_block?: boolean | null
  aggressor?: string | null
  aggressor_label?: string | null
  premium?: number | null
  volume?: number | null
  contracts?: number | null
  open_interest?: number | null
  flags?: string[] | null
  anomaly_flags?: string[] | null
  presets?: string[] | null
}

export function classifyFlowOrder(print: FlowOrderInput): FlowBadgeMeta {
  const rawFlags = [
    ...(print.flags || []),
    ...(print.anomaly_flags || []),
    ...(print.presets || []),
  ].map((f) => String(f).toLowerCase())
  const flags = new Set(rawFlags)
  const tradeClass = String(print.trade_class || '').toLowerCase().trim()
  const aggressor = String(print.aggressor || print.aggressor_label || '').toLowerCase().trim()
  const isSweep = Boolean(print.is_sweep || tradeClass === 'sweep' || flags.has('sweep') || flags.has('sweep_burst'))
  const isBlock = Boolean(print.is_block || tradeClass === 'block' || flags.has('block') || flags.has('cross'))
  const isSplit = tradeClass === 'split' || flags.has('split') || flags.has('intermarket_split') || flags.has('cross_exchange')
  const isMultiLeg = tradeClass === 'multileg'
    || tradeClass === 'multi_leg'
    || tradeClass === 'spread'
    || tradeClass === 'complex'
    || tradeClass === 'combo'
    || flags.has('multileg')
    || flags.has('multi_leg')
    || flags.has('spread')
    || flags.has('combo')
    || flags.has('straddle')
    || flags.has('strangle')
  const premium = Number(print.premium ?? 0)
  const volume = Number(print.volume ?? print.contracts ?? 0)
  const oi = print.open_interest != null && Number.isFinite(Number(print.open_interest)) ? Number(print.open_interest) : null
  const isAskAggressor = aggressor === 'buy'
    || aggressor === 'long'
    || aggressor === 'ask'
    || aggressor === 'above_ask'
    || flags.has('at_ask')
    || flags.has('above_ask')
  const isExplicitGolden = flags.has('golden_sweep') || flags.has('goldensweep')

  // Golden Sweep: Sweep executed at/above ask with institutional size (>= $100k) or Vol > OI, or >= $500k
  if (
    isExplicitGolden
    || (isSweep && isAskAggressor && (premium >= 100_000 || (oi != null && oi > 0 && volume > oi)))
    || (isSweep && isAskAggressor && premium >= 500_000)
    || (isSweep && premium >= 1_000_000 && isAskAggressor)
  ) {
    return {
      type: 'golden_sweep',
      label: 'GOLDEN SWEEP',
      className: 'badge-golden-sweep',
      description: 'High-conviction intermarket sweep executed at/above ask with institutional size',
    }
  }

  if (isSweep) {
    return {
      type: 'sweep',
      label: 'SWEEP',
      className: 'badge-sweep',
      description: 'Intermarket sweep order routing across multiple exchanges to fill immediately',
    }
  }

  if (isBlock) {
    return {
      type: 'block',
      label: 'BLOCK',
      className: 'badge-block',
      description: 'Large privately negotiated single-venue block trade',
    }
  }

  if (isSplit) {
    return {
      type: 'split',
      label: 'SPLIT',
      className: 'badge-split',
      description: 'Order split across multiple venues or price levels simultaneously',
    }
  }

  if (isMultiLeg) {
    return {
      type: 'multileg',
      label: 'MULTI-LEG',
      className: 'badge-multileg',
      description: 'Complex multi-leg options strategy execution (spread, condor, straddle)',
    }
  }

  return {
    type: 'standard',
    label: print.trade_class ? String(print.trade_class).toUpperCase() : 'STANDARD',
    className: 'badge-standard',
    description: 'Standard single-exchange options trade',
  }
}

export interface VolOiRatioResult {
  ratio: number | null
  formatted: string
  isHigh: boolean // ratio >= 1.0
  isExtreme?: boolean // ratio >= 3.0
}

export function computeVolOiRatio(
  volume?: number | null,
  openInterest?: number | null,
): VolOiRatioResult {
  const vol = volume != null && Number.isFinite(Number(volume)) && Number(volume) > 0 ? Number(volume) : null
  const oi = openInterest != null && Number.isFinite(Number(openInterest)) && Number(openInterest) >= 0 ? Number(openInterest) : null

  if (vol === null || oi === null) {
    return { ratio: null, formatted: '—', isHigh: false, isExtreme: false }
  }

  if (oi === 0) {
    return { ratio: null, formatted: 'NEW (0 OI)', isHigh: true, isExtreme: true }
  }

  const r = vol / oi
  const rounded = Number(r.toFixed(2))
  const formatted = r >= 10 ? `${r.toFixed(0)}×` : `${r.toFixed(1)}×`
  const isHigh = r >= 1.0
  const isExtreme = r >= 3.0

  return {
    ratio: rounded,
    formatted,
    isHigh,
    isExtreme,
  }
}

export type PremiumTier = 'mega_whale' | 'whale' | 'large' | 'medium' | 'standard'

export interface PremiumTierMeta {
  tier: PremiumTier
  label: string
  className: string
  threshold: number
  isWhale: boolean
}

export function classifyPremiumTier(premium?: number | null): PremiumTierMeta {
  const p = typeof premium === 'number' && Number.isFinite(premium) ? premium : 0
  if (p >= 1_000_000) {
    return {
      tier: 'mega_whale',
      label: '$1M+ MEGA',
      className: 'tier-mega-whale',
      threshold: 1_000_000,
      isWhale: true,
    }
  }
  if (p >= 500_000) {
    return {
      tier: 'whale',
      label: '$500k+ WHALE',
      className: 'tier-whale',
      threshold: 500_000,
      isWhale: true,
    }
  }
  if (p >= 100_000) {
    return {
      tier: 'large',
      label: '$100k+',
      className: 'tier-large',
      threshold: 100_000,
      isWhale: false,
    }
  }
  if (p >= 50_000) {
    return {
      tier: 'medium',
      label: '$50k+',
      className: 'tier-medium',
      threshold: 50_000,
      isWhale: false,
    }
  }
  return {
    tier: 'standard',
    label: '<$50k',
    className: 'tier-standard',
    threshold: 0,
    isWhale: false,
  }
}

export function flowWhaleTier(premium?: number | null): {
  tier: '1m' | '500k' | '100k' | null
  label: string | null
  className: string | null
} {
  const p = Number(premium ?? 0)
  if (p >= 1_000_000) return { tier: '1m', label: '$1M+', className: 'tier-1m' }
  if (p >= 500_000) return { tier: '500k', label: '$500k+', className: 'tier-500k' }
  if (p >= 100_000) return { tier: '100k', label: '$100k+', className: 'tier-100k' }
  return { tier: null, label: null, className: null }
}
