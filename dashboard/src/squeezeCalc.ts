import type { SqueezeSetup } from '@/api'
import { usd } from '@/format'

export const RING_RADIUS = 42
/**
 * Derived from RING_RADIUS (2πr) rather than hardcoded, so the stroke-dasharray
 * math can never drift out of sync with the SVG's `r` attribute if the radius
 * is ever changed in SqueezeScreener.vue without updating a separate literal.
 */
export const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS

export type TakeawayType = 'pos' | 'neg' | 'warn' | 'info'

export interface TakeawayItem {
  line: string
  icon: string
  type: TakeawayType
}

/**
 * Determine the featured squeeze setup.
 *
 * Rules:
 * 1. Explicit primary direction ('bullish' or 'bearish') takes precedence.
 * 2. When primary is not directional (e.g. 'quiet', 'two_way', or undefined):
 *    - Highest structure score wins (rs > bs -> bearish, bs > rs -> bullish).
 *    - On a tie (bs === rs), tie-break using signedScore:
 *      - signedScore > 0 -> bullish
 *      - signedScore < 0 -> bearish
 *      - signedScore === 0 / null -> defaults to bullish
 */
export function calculateFeaturedSetup(
  primary: string = 'quiet',
  bull?: SqueezeSetup,
  bear?: SqueezeSetup,
  signedScore?: number | null,
): { side: 'bullish' | 'bearish'; setup: SqueezeSetup | undefined } {
  const bs = bull?.score ?? 0
  const rs = bear?.score ?? 0

  if (primary === 'bearish') {
    return { side: 'bearish', setup: bear }
  }
  if (primary === 'bullish') {
    return { side: 'bullish', setup: bull }
  }
  if (rs > bs) {
    return { side: 'bearish', setup: bear }
  }
  if (bs > rs) {
    return { side: 'bullish', setup: bull }
  }

  // bs === rs: tie-break using signedScore (positive -> bullish, negative -> bearish)
  const sc = signedScore ?? 0
  if (sc < 0) {
    return { side: 'bearish', setup: bear }
  }
  return { side: 'bullish', setup: bull }
}

/**
 * Calculate SVG circle stroke-dashoffset for the squeeze probability ring.
 *
 * Formula: RING_CIRCUMFERENCE * (1 - Math.min(100, Math.max(0, Math.abs(score))) / 100)
 * Handles negative scores (via Math.abs), bounds [0, 100], and invalid inputs.
 */
export function calculateRingOffset(
  score: number | null | undefined,
  circumference: number = RING_CIRCUMFERENCE,
): number {
  const num = typeof score === 'number' && !Number.isNaN(score) ? score : 0
  const boundedPct = Math.min(100, Math.max(0, Math.abs(num)))
  return circumference * (1 - boundedPct / 100)
}

/**
 * Format Near-Spot Net GEX in millions with proper signed currency notation.
 * Negative values format as -$X.XM (not $-X.XM), and positive values format as +$X.XM.
 */
export function formatNearSpotGex(val: number | null | undefined): string {
  if (val == null || Number.isNaN(val)) return '—'
  if (val < 0) {
    return `-$${Math.abs(val).toFixed(1)}M`
  }
  return `+$${val.toFixed(1)}M`
}

/**
 * Calculate factor track or alternate setup fill percentage, clamped strictly to [0, 100]%.
 * Prevents negative percentages from rendering invalid layout widths.
 */
export function calculateTrackWidthPct(
  score: number | null | undefined,
  max: number | null | undefined = 100,
): number {
  if (score == null || Number.isNaN(score) || max == null || max <= 0 || Number.isNaN(max)) {
    return 0
  }
  const ratio = (score / max) * 100
  return Math.max(0, Math.min(100, ratio))
}

/**
 * Build structured takeaways with appropriate icon and dot tone.
 * Bullish setups use 'pos' (emerald), Bearish setups use 'neg' (crimson),
 * regimes/warnings use 'warn' (amber), and general details use 'info' (phosphor).
 */
export function buildTakeaways(options: {
  analysis?: string[] | null
  side: 'bullish' | 'bearish'
  wallLevel?: number | null
  wallPct?: number | null
  wallLabel?: string
  dampened?: boolean
  implication?: string | null
}): TakeawayItem[] {
  const { analysis, side, wallLevel, wallPct, wallLabel, dampened, implication } = options

  if (analysis && analysis.length > 0) {
    return analysis.map((line) => {
      const l = line.toLowerCase()
      let icon = side === 'bullish' ? '↑' : '↓'
      let type: TakeawayType = side === 'bullish' ? 'pos' : 'neg'

      if (l.includes('dampen') || l.includes('zero-gamma') || l.includes('long gamma')) {
        icon = '●'
        type = 'warn'
      } else if (
        l.includes('partial') ||
        l.includes('structure') ||
        l.includes('alone') ||
        l.includes('lean')
      ) {
        icon = '●'
        type = 'info'
      } else if (l.includes('put') || l.includes('downside')) {
        icon = '↓'
        type = 'neg'
      } else if (l.includes('call') || l.includes('upside')) {
        icon = '↑'
        type = 'pos'
      } else if (l.includes('near') || l.includes('magnet')) {
        icon = side === 'bullish' ? '↑' : '↓'
        type = side === 'bullish' ? 'pos' : 'neg'
      }
      return { line, icon, type }
    })
  }

  const lines: TakeawayItem[] = []
  if (wallLevel != null) {
    const pctTxt =
      wallPct == null ? '' : ` (${wallPct >= 0 ? '+' : ''}${(wallPct * 100).toFixed(1)}%)`
    lines.push({
      line: `${wallLabel || (side === 'bullish' ? 'Call Wall' : 'Put Wall')} at ${usd(wallLevel)}${pctTxt}.`,
      icon: side === 'bullish' ? '↑' : '↓',
      type: side === 'bullish' ? 'pos' : 'neg',
    })
  }
  if (dampened) {
    lines.push({
      line: 'Long-gamma regime dampens squeeze follow-through below flip.',
      icon: '●',
      type: 'warn',
    })
  }
  if (implication) {
    lines.push({ line: implication, icon: '●', type: 'info' })
  }
  if (!lines.length) {
    lines.push({
      line: 'Insufficient structure factors for a squeeze read on this chain.',
      icon: '●',
      type: 'info',
    })
  }
  return lines
}
