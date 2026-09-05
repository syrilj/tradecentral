/**
 * Shared Flow display helpers — token classes, named empties, and pulse copy.
 * Kept pure so tests can drive the shipped labels without mounting Vue/Clerk.
 */
import { compact, DASH, num, signed, signedPct, usd } from '@/format'

export type FlowLeanState =
  'bullish' | 'bearish' | 'mixed' | 'unknown' | 'model-bullish' | 'model-bearish'

export type FlowPriority = 'now' | 'soon' | 'watch' | 'skip'

export const NO_SIGNED_SIDE = 'NO SIGNED SIDE'
export const NO_SIGNAL = 'NO SIGNAL'
export const NO_MIX_IN_SAMPLE = 'NO MIX IN SAMPLE'
export const NO_STRIKE_IN_TAPE = 'NO STRIKE IN TAPE'
export const FIRST_WINDOW_BASELINE = 'first window baseline'
export const PREVIOUS_PROVIDER_WINDOW = 'previous provider window'
export const DTE_MISSING = 'DTE MISSING'
export const OI_MISSING = 'OI MISSING'
export const VOL_MISSING = 'VOL MISSING'
export const VOL_OI_MISSING = 'VOL/OI MISSING'
export const OTM_MISSING = 'OTM MISSING'
export const UNSIGNED_PRINT = 'UNSIGNED'
export const HTTP_POLL_NOT_WEBSOCKET = 'HTTP POLL · NOT A WEBSOCKET'
export const CACHE_UNKNOWN = 'CACHE UNKNOWN'
export const CLASS_SOURCE_MISSING = 'CLASS SOURCE MISSING'
export const NO_PROVIDER_TIME = 'NO PROVIDER TIME'

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
  const normalized = String(side ?? '')
    .trim()
    .toLowerCase()
  if (normalized === 'buy' || normalized === 'long' || normalized === 'bullish') return 'token-long'
  if (normalized === 'sell' || normalized === 'short' || normalized === 'bearish')
    return 'token-short'
  return 'token-unsigned'
}

/** Instrument token class for desk-priority chips. */
export function flowPriorityTokenClass(priority: string | null | undefined): string {
  if (priority === 'now') return 'token-long'
  if (priority === 'soon') return 'token-warn'
  if (priority === 'skip') return 'token-unsigned'
  return 'token-ink'
}

export function namedEmpty(value: unknown, emptyLabel: string): string {
  if (value == null || value === '') return emptyLabel
  if (typeof value === 'number' && !Number.isFinite(value)) return emptyLabel
  return String(value)
}

export function mixShareLabel(share: number | null | undefined, formatted: string): string {
  if (share == null || !Number.isFinite(share)) return NO_MIX_IN_SAMPLE
  return formatted
}

export function concentrationLabel(topStrike: string | null | undefined, fallback: string): string {
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

export type FlowOrderType = 'golden_sweep' | 'sweep' | 'block' | 'split' | 'multileg' | 'standard'

export interface FlowBadgeMeta {
  type: FlowOrderType
  label: string
  className: string
  description: string
}

export interface FlowOrderInput {
  trade_class?: string | null
  trade_class_source?: string | null
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
  const tradeClass = String(print.trade_class || '')
    .toLowerCase()
    .trim()
  const isSweep = Boolean(
    print.is_sweep || tradeClass === 'sweep' || flags.has('sweep') || flags.has('sweep_burst'),
  )
  const isBlock = Boolean(
    print.is_block || tradeClass === 'block' || flags.has('block') || flags.has('cross'),
  )
  const isSplit =
    tradeClass === 'split' ||
    flags.has('split') ||
    flags.has('intermarket_split') ||
    flags.has('cross_exchange')
  const isMultiLeg =
    tradeClass === 'multileg' ||
    tradeClass === 'multi_leg' ||
    tradeClass === 'spread' ||
    tradeClass === 'complex' ||
    tradeClass === 'combo' ||
    flags.has('multileg') ||
    flags.has('multi_leg') ||
    flags.has('spread') ||
    flags.has('combo') ||
    flags.has('straddle') ||
    flags.has('strangle')
  const isExplicitGolden = flags.has('golden_sweep') || flags.has('goldensweep')
  const classSource = String(print.trade_class_source || '').toLowerCase()
  const vendorClass = classSource === 'vendor'

  // Vendor-tagged golden only. Size + ask-side never certifies a golden sweep.
  if (isExplicitGolden) {
    return {
      type: 'golden_sweep',
      label: 'VENDOR GOLDEN FLAG',
      className: 'badge-golden-sweep',
      description:
        'Vendor tagged this print golden_sweep. Descriptive flag only — not certified and not ENTER.',
    }
  }

  if (isSweep) {
    const heuristic = classSource === 'burst_heuristic' || flags.has('sweep_burst')
    return {
      type: 'sweep',
      label: heuristic && !vendorClass ? 'BURST SWEEP' : 'SWEEP',
      className: 'badge-sweep',
      description: heuristic
        ? 'App-side ≤3s same-contract burst heuristic. Not a vendor sweep certification.'
        : vendorClass
          ? 'Vendor trade_class sweep. Descriptive execution tag — not ENTER.'
          : 'Sweep-class print. Descriptive flag only — not a live institutional firehose.',
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
  const vol =
    volume != null && Number.isFinite(Number(volume)) && Number(volume) > 0 ? Number(volume) : null
  const oi =
    openInterest != null && Number.isFinite(Number(openInterest)) && Number(openInterest) >= 0
      ? Number(openInterest)
      : null

  if (vol === null && oi === null) {
    return { ratio: null, formatted: VOL_OI_MISSING, isHigh: false, isExtreme: false }
  }
  if (vol === null || vol <= 0) {
    return { ratio: null, formatted: VOL_MISSING, isHigh: false, isExtreme: false }
  }
  if (oi === null) {
    return { ratio: null, formatted: OI_MISSING, isHigh: false, isExtreme: false }
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

export function formatDteBadge(dte?: number | null): { label: string; className: string } {
  if (dte == null || !Number.isFinite(Number(dte))) {
    return { label: DTE_MISSING, className: 'dte-unknown' }
  }
  const d = Math.round(Number(dte))
  if (d === 0) return { label: '0D', className: 'dte-0d' }
  if (d <= 7) return { label: `${d}D`, className: 'dte-weekly' }
  if (d <= 30) return { label: `${d}D`, className: 'dte-monthly' }
  if (d <= 90) return { label: `${d}D`, className: 'dte-quarterly' }
  return { label: `${d}D`, className: 'dte-leap' }
}

export function formatMoneyness(otmPct?: number | null): { label: string; className: string } {
  if (otmPct == null || !Number.isFinite(Number(otmPct))) {
    return { label: OTM_MISSING, className: 'moneyness-none' }
  }
  const p = Number(otmPct)
  if (Math.abs(p) < 0.015) {
    return { label: 'ATM', className: 'moneyness-atm' }
  }
  if (p > 0) {
    const formatted = p >= 0.1 ? `+${(p * 100).toFixed(0)}%` : `+${(p * 100).toFixed(1)}%`
    return { label: `OTM ${formatted}`, className: 'moneyness-otm' }
  }
  const formatted = Math.abs(p) >= 0.1 ? `${(p * 100).toFixed(0)}%` : `${(p * 100).toFixed(1)}%`
  return { label: `ITM ${formatted}`, className: 'moneyness-itm' }
}

export function tradeClassSourceLabel(source?: string | null): string {
  const value = String(source || '')
    .trim()
    .toLowerCase()
  if (value === 'vendor') return 'VENDOR CLASS'
  if (value === 'burst_heuristic') return 'BURST HEURISTIC'
  if (value === 'size_heuristic') return 'SIZE HEURISTIC'
  if (value === 'unclassified') return 'UNCLASSIFIED'
  return CLASS_SOURCE_MISSING
}

export function flowCacheCopy(
  cache?: {
    hit?: boolean
    age_seconds?: number
    ttl_seconds?: number
  } | null,
): string {
  if (!cache) return CACHE_UNKNOWN
  const hit = cache.hit ? 'HIT' : 'MISS'
  const age =
    cache.age_seconds != null && Number.isFinite(Number(cache.age_seconds))
      ? `${Math.round(Number(cache.age_seconds))}s`
      : 'AGE MISSING'
  const ttl =
    cache.ttl_seconds != null && Number.isFinite(Number(cache.ttl_seconds))
      ? `${Math.round(Number(cache.ttl_seconds))}s TTL`
      : 'TTL MISSING'
  return `CACHE ${hit} · ${age} / ${ttl}`
}

export function flowTransportCopy(pollMs?: number | null): string {
  if (pollMs == null || !Number.isFinite(Number(pollMs))) return HTTP_POLL_NOT_WEBSOCKET
  const seconds = Math.max(1, Math.round(Number(pollMs) / 1000))
  return `${seconds}s ${HTTP_POLL_NOT_WEBSOCKET}`
}

export function feedStatusCopy(status?: string | null): string {
  const value = String(status || '')
    .trim()
    .toLowerCase()
  if (!value) return 'FEED STATUS MISSING'
  if (value === 'live') return 'PROVIDER SAMPLE'
  if (value === 'no_prints') return 'NO PRINTS IN SAMPLE'
  if (value === 'credential_missing') return 'CREDENTIAL MISSING'
  if (value === 'unavailable' || value === 'timeout') return 'FEED UNAVAILABLE'
  return value.replaceAll('_', ' ').toUpperCase()
}

export function signedVsUnsignedLabel(input: {
  aggressor?: string | null
  signed_premium?: number | null
}): string {
  const aggressor = String(input.aggressor || '')
    .trim()
    .toLowerCase()
  if (aggressor === 'buy' || aggressor === 'sell' || input.signed_premium != null) {
    return aggressor === 'buy' ? 'SIGNED BUY' : aggressor === 'sell' ? 'SIGNED SELL' : 'SIGNED'
  }
  return UNSIGNED_PRINT
}

/* ------------------------------------------------------------------ Quote & mix accuracy */

export const DAY_RANGE_UNMEASURED = 'DAY RANGE UNMEASURED'
export const FLOW_UNMEASURED = 'FLOW UNMEASURED'
export const NO_PRICE_TRACE = 'NO PRICE TRACE'

function finiteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

/**
 * Quote readout for the Flow workspace.
 *
 * `move` is a fractional return. When spot is present, the dollar move is
 * reconstructed from the prior close implied by that return:
 * prior = spot / (1 + move), dollars = spot - prior. When spot is missing the
 * percentage is still shown, but no dollar amount is invented.
 */
export interface QuoteStatsInput {
  spot?: number | null
  move?: number | null
  contractCount?: number | null
}

export interface QuoteStatsOutput {
  spot: string
  move: string
  moveTone: 'pos' | 'neg' | 'neutral'
  dayRange: string
  volume: string
}

export function quoteStats(input: QuoteStatsInput): QuoteStatsOutput {
  const spot = finiteNumber(input.spot)
  const move = finiteNumber(input.move)
  const volume = finiteNumber(input.contractCount)
  const moveDollars = spot != null && move != null && move > -1 ? spot - spot / (1 + move) : null
  const movePct = move == null ? null : move * 100
  const moveLabel =
    move == null
      ? DASH
      : moveDollars == null
        ? signedPct(movePct, 2)
        : `${signed(moveDollars, 2)} (${signedPct(movePct, 2)})`

  return {
    spot: spot == null ? DASH : usd(spot, 2),
    move: moveLabel,
    moveTone: move == null ? 'neutral' : move > 0 ? 'pos' : move < 0 ? 'neg' : 'neutral',
    dayRange: DAY_RANGE_UNMEASURED,
    volume: volume == null ? DASH : compact(volume),
  }
}

/**
 * Bullish/bearish flow mix. Both sides must be measured before a percentage
 * split is rendered; a one-sided or absent read stays explicitly unmeasured.
 */
export interface FlowMixInput {
  totalPremiumM?: number | null
  bullishPremiumM?: number | null
  bearishPremiumM?: number | null
  netFlowM?: number | null
}

export interface FlowMixOutput {
  totalPremium: string
  bullishPct: number | null
  bearishPct: number | null
  bullishLabel: string
  bearishLabel: string
  netFlow: string
  hasMix: boolean
}

export function flowMixStats(input: FlowMixInput): FlowMixOutput {
  const bullish = finiteNumber(input.bullishPremiumM)
  const bearish = finiteNumber(input.bearishPremiumM)
  const total = finiteNumber(input.totalPremiumM)
  const netFlow = finiteNumber(input.netFlowM)
  const mixTotal = bullish != null && bearish != null ? bullish + bearish : null
  const hasMix = mixTotal != null && mixTotal > 0
  const bullishPct =
    hasMix && bullish != null && mixTotal != null ? Math.round((bullish / mixTotal) * 100) : null
  const bearishPct = bullishPct == null ? null : 100 - bullishPct

  return {
    totalPremium: total == null ? DASH : `$${num(total, 1)}M`,
    bullishPct,
    bearishPct,
    bullishLabel: bullishPct == null ? FLOW_UNMEASURED : `${bullishPct}%`,
    bearishLabel: bearishPct == null ? FLOW_UNMEASURED : `${bearishPct}%`,
    netFlow: netFlow == null ? DASH : `${signed(netFlow, 1)}M`,
    hasMix,
  }
}

/** Signed print side. Call/put identity never becomes bullish/bearish. */
export type FlowPrintSide = 'Bullish' | 'Bearish' | 'Neutral'

export function printSide(input: {
  bias?: string | null
  aggressor?: string | null
  aggressor_label?: string | null
}): FlowPrintSide {
  const bias = String(input.bias ?? '')
    .trim()
    .toLowerCase()
  const aggressor = String(input.aggressor ?? input.aggressor_label ?? '')
    .trim()
    .toLowerCase()
  if (bias === 'bullish' || aggressor === 'buy' || aggressor === 'long') return 'Bullish'
  if (bias === 'bearish' || aggressor === 'sell' || aggressor === 'short') return 'Bearish'
  return 'Neutral'
}

/**
 * Premium from an explicit provider value, or from a fully measured
 * price × volume × contract multiplier. Missing components stay missing —
 * they never collapse to zero.
 */
export function printPremium(input: {
  premium?: number | null
  price?: number | null
  volume?: number | null
  contract_multiplier?: number | null
}): number | null {
  const premium = finiteNumber(input.premium)
  if (premium != null) return premium
  const price = finiteNumber(input.price)
  const volume = finiteNumber(input.volume)
  const multiplier = finiteNumber(input.contract_multiplier)
  if (price == null || volume == null || multiplier == null) return null
  return price * volume * multiplier
}
