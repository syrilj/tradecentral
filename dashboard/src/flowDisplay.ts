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
