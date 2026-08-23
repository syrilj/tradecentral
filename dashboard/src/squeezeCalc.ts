import type { SqueezeSetup } from '@/api'
import { usd } from '@/format'

export const RING_RADIUS = 42
export const RING_CIRCUMFERENCE = 263.89

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
  const normPrimary = String(primary || 'quiet').trim().toLowerCase()
  const bs = bull?.score ?? 0
  const rs = bear?.score ?? 0

  if (normPrimary.includes('bear')) {
    return { side: 'bearish', setup: bear ?? bull }
  }
  if (normPrimary.includes('bull')) {
    return { side: 'bullish', setup: bull ?? bear }
  }
  if (rs > bs) {
    return { side: 'bearish', setup: bear ?? bull }
  }
  if (bs > rs) {
    return { side: 'bullish', setup: bull ?? bear }
  }

  // bs === rs: tie-break using signedScore (positive -> bullish, negative -> bearish)
  const sc = signedScore ?? 0
  if (sc < 0) {
    return { side: 'bearish', setup: bear ?? bull }
  }
  return { side: 'bullish', setup: bull ?? bear }
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
  if (val === Infinity) return '+$InfinityM'
  if (val === -Infinity) return '-$InfinityM'
  const a = Math.abs(val)
  const roundedAbs = Number(a.toFixed(1))
  if (roundedAbs === 0) return '+$0.0M'
  if (val < 0) {
    return `-$${a.toFixed(1)}M`
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
    const pctTxt = wallPct == null ? '' : ` (${wallPct >= 0 ? '+' : ''}${(wallPct * 100).toFixed(1)}%)`
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

/* ==========================================================================
   Live-desk correlates.

   Everything below is *derived* from measured chain fields — spot, the gamma
   walls, the zero-gamma flip, the pin strike, and the payload's own as-of
   stamp. Nothing here invents a level, a distance, or a freshness class: when
   an input is unmeasured the helper returns `null` and the UI renders the
   em-dash placeholder rather than a zero that a trader could mistake for a
   real price.
   ========================================================================== */

/** Signed distance from spot to a level, in dollars and as a fraction. */
export interface LevelDistance {
  /** level - spot, in dollars. Positive = level sits above spot. */
  delta: number
  /** (level - spot) / spot as a fraction. 0.021 = +2.1%. */
  pct: number
}

/**
 * Distance from spot to a level. Returns null when either side is unmeasured
 * or spot is non-positive, so callers cannot accidentally print "+0.00%" for
 * a level that was never computed.
 */
export function distanceFromSpot(
  level: number | null | undefined,
  spot: number | null | undefined,
): LevelDistance | null {
  if (level == null || !Number.isFinite(level)) return null
  if (spot == null || !Number.isFinite(spot) || spot <= 0) return null
  const delta = level - spot
  return { delta, pct: delta / spot }
}

/** What a level means to someone sizing a trade right now. */
export type LevelRole = 'spot' | 'trigger' | 'invalidation' | 'magnet'

export interface LevelRow {
  id: string
  label: string
  /** Measured price, or null when the chain could not produce it. */
  level: number | null
  role: LevelRole
  tone: 'call' | 'put' | 'accent' | 'ink'
  /** Null whenever `level` or spot is unmeasured. */
  distance: LevelDistance | null
  /** Short plain-English note. Static text, never a number. */
  note: string
}

/**
 * Order the tradable levels into a price ladder: measured levels sort high to
 * low so the board reads like a DOM, and unmeasured levels sink to the bottom
 * where their em-dash is obvious rather than hidden mid-stack.
 *
 * The featured side decides which wall is the squeeze *trigger*; the opposite
 * wall is still listed, because a trader needs to see the level that caps the
 * move as much as the one that starts it.
 */
export function buildLevelLadder(input: {
  side: 'bullish' | 'bearish'
  spot?: number | null
  callWall?: number | null
  putWall?: number | null
  gammaFlip?: number | null
  pinStrike?: number | null
}): LevelRow[] {
  const { side, spot, callWall, putWall, gammaFlip, pinStrike } = input
  const bullish = side === 'bullish'

  const rows: LevelRow[] = [
    {
      id: 'call_wall',
      label: 'CALL WALL',
      level: callWall ?? null,
      role: bullish ? 'trigger' : 'magnet',
      tone: 'call',
      distance: distanceFromSpot(callWall, spot),
      note: bullish ? 'Squeeze trigger — dealer short-gamma chase above' : 'Upside cap',
    },
    {
      id: 'put_wall',
      label: 'PUT WALL',
      level: putWall ?? null,
      role: bullish ? 'magnet' : 'trigger',
      tone: 'put',
      distance: distanceFromSpot(putWall, spot),
      note: bullish ? 'Downside support' : 'Squeeze trigger — hedging accelerates below',
    },
    {
      id: 'gamma_flip',
      label: 'GAMMA FLIP',
      level: gammaFlip ?? null,
      role: 'invalidation',
      tone: 'accent',
      distance: distanceFromSpot(gammaFlip, spot),
      note: 'Regime boundary — long gamma above, short gamma below',
    },
    {
      id: 'pin_strike',
      label: 'PIN',
      level: pinStrike ?? null,
      role: 'magnet',
      tone: 'accent',
      distance: distanceFromSpot(pinStrike, spot),
      note: 'Peak open interest — pins price into expiry',
    },
    {
      id: 'spot',
      label: 'SPOT',
      level: spot ?? null,
      role: 'spot',
      tone: 'ink',
      distance: spot != null && Number.isFinite(spot) ? { delta: 0, pct: 0 } : null,
      note: 'Last measured underlier price',
    },
  ]

  const measured = rows.filter((r) => r.level != null && Number.isFinite(r.level))
  const unmeasured = rows.filter((r) => r.level == null || !Number.isFinite(r.level))
  measured.sort((a, b) => (b.level as number) - (a.level as number))
  return [...measured, ...unmeasured]
}

/**
 * Where spot sits relative to the zero-gamma flip. This is the single most
 * load-bearing fact on the panel — short gamma below the flip is what makes a
 * squeeze mechanically possible — so it is reported as a measured state or
 * not at all.
 */
export function gammaRegimeSide(
  spot: number | null | undefined,
  gammaFlip: number | null | undefined,
): 'above_flip' | 'below_flip' | 'at_flip' | 'unmeasured' {
  if (spot == null || !Number.isFinite(spot)) return 'unmeasured'
  if (gammaFlip == null || !Number.isFinite(gammaFlip)) return 'unmeasured'
  if (spot > gammaFlip) return 'above_flip'
  if (spot < gammaFlip) return 'below_flip'
  return 'at_flip'
}

/** Freshness class for the payload driving this board. */
export type FreshnessTier = 'live' | 'delayed' | 'stale' | 'history' | 'unknown'

/**
 * Classify payload age for a live-trading surface.
 *
 * A dated/history payload is never labelled "live" no matter how recently it
 * was rendered, and a missing age is reported as `unknown` rather than being
 * optimistically rounded down to fresh.
 */
export function freshnessTier(
  ageSeconds: number | null | undefined,
  mode?: string | null,
): FreshnessTier {
  const m = String(mode || '').toLowerCase()
  if (m.includes('history')) return 'history'
  if (m === 'unavailable') return 'unknown'
  if (ageSeconds == null || !Number.isFinite(ageSeconds) || ageSeconds < 0) return 'unknown'
  if (ageSeconds < 90) return 'live'
  if (ageSeconds < 900) return 'delayed'
  return 'stale'
}

/** Compact age label. Returns the em-dash placeholder when unmeasured. */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '—'
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
  return `${Math.floor(s / 86400)}d`
}

/**
 * True only when the chain actually scored this setup. A setup object with no
 * factor meters carries no measurement, so the board must not render a 0/100
 * dial and an "UNLIKELY" verdict for it — that reads as a confident negative
 * when the honest answer is "not measured".
 */
export function isSetupMeasured(setup: SqueezeSetup | null | undefined): boolean {
  if (!setup) return false
  if (typeof setup.score !== 'number' || !Number.isFinite(setup.score)) return false
  return Array.isArray(setup.factors) && setup.factors.some((f) => (f?.max ?? 0) > 0)
}

/** Signed gex_core score with an explicit sign, or the placeholder when null. */
export function formatSignedScore(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const rounded = Number(v.toFixed(1))
  if (rounded === 0 || Object.is(rounded, -0)) return '0'
  return `${rounded > 0 ? '+' : ''}${rounded}`
}
