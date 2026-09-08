import type { OptionsSqueeze, SqueezeSetup } from '@/api'
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
 *    - Align with signedScore / directional flow lean if measured and non-zero:
 *      - signedScore > 0 -> bullish
 *      - signedScore < 0 -> bearish
 *    - When signedScore is zero or unmeasured (null/undefined/NaN), fall back to comparing wall proximity:
 *      - Highest structure score wins (rs > bs -> bearish, bs > rs -> bullish).
 *      - On a tie (bs === rs), defaults to bullish.
 */
export function calculateFeaturedSetup(
  primary: string = 'quiet',
  bull?: SqueezeSetup,
  bear?: SqueezeSetup,
  signedScore?: number | null,
): { side: 'bullish' | 'bearish'; setup: SqueezeSetup | undefined } {
  const normPrimary = String(primary || 'quiet')
    .trim()
    .toLowerCase()
  const bs = bull?.score ?? 0
  const rs = bear?.score ?? 0

  // 1. Explicit directional primary takes absolute precedence
  if (normPrimary.includes('bear')) {
    return { side: 'bearish', setup: bear ?? bull }
  }
  if (normPrimary.includes('bull')) {
    return { side: 'bullish', setup: bull ?? bear }
  }

  // 2. Non-directional primary (quiet / two_way / unmeasured): Prioritize signed flow / theory score
  const sc = typeof signedScore === 'number' && Number.isFinite(signedScore) ? signedScore : 0
  if (sc > 0) {
    return { side: 'bullish', setup: bull ?? bear }
  }
  if (sc < 0) {
    return { side: 'bearish', setup: bear ?? bull }
  }

  // 3. Fall back to structure score comparison (bs vs rs) only when signedScore is zero or unmeasured
  if (rs > bs) {
    return { side: 'bearish', setup: bear ?? bull }
  }
  if (bs > rs) {
    return { side: 'bullish', setup: bull ?? bear }
  }

  return { side: 'bullish', setup: bull ?? bear }
}

/**
 * Calculate SVG circle stroke-dashoffset for the squeeze theory-score ring.
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

function finiteNum(value: unknown): number | null {
  if (value == null || typeof value === 'boolean') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

export type TheoryState =
  'unmeasured' | 'dampened' | 'no_fuel' | 'fuel_only' | 'bull_lean' | 'bear_lean' | 'two_way'

export type TheoryTermTone = 'fuel' | 'flow' | 'mom' | 'bull' | 'bear' | 'warn' | 'ink'

export interface TheoryTerm {
  id: string
  label: string
  display: string
  fill01: number
  detail: string
  tone: TheoryTermTone
}

export interface TheoryIdentity {
  measurable: boolean
  signed: number | null
  fuelUi: number | null
  squeezeRisk: number | null
  liquidityRatio: number | null
  atmShare: number | null
  weightedDte: number | null
  urgency: number | null
  flowImbalance: number | null
  flowWeight: number
  momentum: number | null
  momentumFresh: boolean
  convictionBull: number | null
  convictionBear: number | null
  bullUi: number | null
  bearUi: number | null
  advM: number | null
  advAvailable: boolean
  state: TheoryState
  stateLabel: string
  formula: string
  terms: TheoryTerm[]
}

const THEORY_STATE_LABEL: Record<TheoryState, string> = {
  unmeasured: 'UNMEASURED',
  dampened: 'LONG Γ DAMPENS',
  no_fuel: 'NO FUEL',
  fuel_only: 'FUEL, NO SIDE',
  bull_lean: 'BULL LEAN',
  bear_lean: 'BEAR LEAN',
  two_way: 'TWO-WAY',
}

const URGENCY_C = 0.05
const DEFAULT_FLOW_WEIGHT = 0.5
const FUEL_SCALE = 40
const MOM_REF = 0.03

/**
 * Unpack the shipped theory squeeze identity for the board.
 *
 *   SR   = |GEX⁻_1%| / ADV · e^{−c T} · ATM share
 *   fuel = tanh(40 · SR)
 *   conv = 0.5 · signed_flow + 0.5 · clip(|mom| / 3%)
 *   score = 100 · fuel · conv   (signed bull − bear)
 *
 * This is a gamma-structure diagnostic, not a calibrated probability. Do not
 * map the 0–100 board onto Unlikely / Likely / Imminent — walk-forward 1d
 * hit rate on the fired score has not beaten a momentum baseline.
 */
export function buildTheoryIdentity(squeeze: OptionsSqueeze | null | undefined): TheoryIdentity {
  const c = squeeze?.components ?? {}
  const t = squeeze?.theory ?? {}
  const gex = t.short_premium_gex_m ?? {}

  const squeezeRisk = finiteNum(t.squeeze_risk) ?? finiteNum(c.theory_squeeze_risk)
  const fuelUi = finiteNum(t.fuel_ui) ?? finiteNum(squeeze?.negative_fuel)
  const gexM = finiteNum(gex.total_gex_m)
  const advFromTheory = finiteNum(t.adv_m)
  const liquidityRatio =
    finiteNum(c.theory_liquidity_ratio) ??
    (gexM != null && advFromTheory != null && advFromTheory > 0
      ? Math.abs(gexM) / advFromTheory
      : null)
  const atmShare = finiteNum(c.theory_atm_share) ?? finiteNum(gex.atm_share)
  const weightedDte = finiteNum(c.theory_weighted_dte) ?? finiteNum(gex.weighted_dte)
  const urgency = weightedDte == null ? null : Math.exp(-URGENCY_C * weightedDte)
  const flowImbalanceRaw =
    finiteNum(t.directional_flow_imbalance) ?? finiteNum(c.theory_directional_flow_imbalance)
  // A 0.0 with zero confidence is not a measurement — the tape carried no
  // buy/sell side, so the honest value is "unmeasured", not a flat zero.
  const flowConfidence = finiteNum(c.theory_imbalance_confidence)
  const flowImbalance = flowImbalanceRaw != null && flowConfidence === 0 ? null : flowImbalanceRaw
  const flowWeight = finiteNum(c.flow_weight) ?? DEFAULT_FLOW_WEIGHT
  const momentum = finiteNum(t.momentum) ?? finiteNum(c.theory_momentum)
  const momentumFresh = Boolean(t.momentum_fresh ?? c.theory_momentum_fresh)
  const convictionBull = finiteNum(c.theory_conviction_bull)
  const convictionBear = finiteNum(c.theory_conviction_bear)
  const bullRaw = finiteNum(squeeze?.bullish)
  const bearRaw = finiteNum(squeeze?.bearish)
  const bullUi = finiteNum(t.bullish_ui) ?? (bullRaw != null ? bullRaw * 100 : null)
  const bearUi = finiteNum(t.bearish_ui) ?? (bearRaw != null ? bearRaw * 100 : null)
  const signed = finiteNum(squeeze?.score)
  const advM = finiteNum(t.adv_m)
  const advAvailable = t.adv_available !== false && (advM == null || advM > 0)
  const measurable = t.measurable !== false && squeeze != null

  let state: TheoryState = 'unmeasured'
  if (!measurable || squeeze == null) {
    state = 'unmeasured'
  } else if (squeeze.long_gamma_dampened) {
    state = 'dampened'
  } else if ((fuelUi ?? 0) < 0.05) {
    state = 'no_fuel'
  } else if ((bullUi ?? 0) > 8 && (bearUi ?? 0) > 8) {
    state = 'two_way'
  } else if ((signed ?? 0) >= 20 || (bullUi ?? 0) >= 20) {
    state = 'bull_lean'
  } else if ((signed ?? 0) <= -20 || (bearUi ?? 0) >= 20) {
    state = 'bear_lean'
  } else {
    state = 'fuel_only'
  }

  const momGate =
    momentum == null || !momentumFresh
      ? null
      : Math.max(0, Math.min(1, Math.abs(momentum) / MOM_REF))
  const flowGate = flowImbalance == null ? null : Math.max(0, Math.min(1, Math.abs(flowImbalance)))

  const terms: TheoryTerm[] = [
    {
      id: 'liquidity',
      label: '|GEX⁻| / ADV',
      display: liquidityRatio == null ? '—' : liquidityRatio.toFixed(3),
      fill01: liquidityRatio == null ? 0 : Math.max(0, Math.min(1, liquidityRatio)),
      detail:
        'Short-premium dealer gamma for a 1% move, as a fraction of average daily dollar volume.',
      tone: 'fuel',
    },
    {
      id: 'atm',
      label: 'ATM SHARE',
      display: atmShare == null ? '—' : `${Math.round(atmShare * 100)}%`,
      fill01: atmShare == null ? 0 : Math.max(0, Math.min(1, atmShare)),
      detail: 'Share of short-premium |GEX| sitting in the ATM band. Higher = more gamma at spot.',
      tone: 'fuel',
    },
    {
      id: 'urgency',
      label: 'EXPIRY URGENCY',
      display:
        weightedDte == null
          ? '—'
          : `${weightedDte.toFixed(1)}D · ${urgency == null ? '—' : urgency.toFixed(2)}`,
      fill01: urgency == null ? 0 : Math.max(0, Math.min(1, urgency)),
      detail: `e^{−${URGENCY_C} · weighted DTE}. Near-dated gamma is more urgent; 45D is ~0.11.`,
      tone: 'fuel',
    },
    {
      id: 'fuel',
      label: 'FUEL tanh(40·SR)',
      display: fuelUi == null ? '—' : `${Math.round(fuelUi * 100)}%`,
      fill01: fuelUi == null ? 0 : Math.max(0, Math.min(1, fuelUi)),
      detail: `SR=${squeezeRisk == null ? '—' : squeezeRisk.toFixed(4)}. Fuel is unsigned: no short gamma ⇒ no squeeze either way.`,
      tone: 'fuel',
    },
    {
      id: 'flow',
      label: 'SIGNED FLOW',
      display: flowImbalance == null ? 'UNSIGNED' : formatSignedScore(flowImbalance),
      fill01: flowGate ?? 0,
      detail:
        flowImbalance == null
          ? 'Tape has no buy/sell side. Unsigned call/put mix is identity, not direction.'
          : `Aggressor-signed premium imbalance. Weight ${flowWeight.toFixed(2)} of conviction.`,
      tone: 'flow',
    },
    {
      id: 'mom',
      label: '5D MOMENTUM',
      display: !momentumFresh || momentum == null ? 'STALE' : `${(momentum * 100).toFixed(2)}%`,
      fill01: momGate ?? 0,
      detail: momentumFresh
        ? `Close-to-close lookback, saturates at |r|=${(MOM_REF * 100).toFixed(0)}%. Weight ${(1 - flowWeight).toFixed(2)} of conviction.`
        : 'Price series older than the freshness gate — momentum does not drive this score.',
      tone: momentumFresh ? 'mom' : 'warn',
    },
    {
      id: 'bull',
      label: 'BULL LEG',
      display: bullUi == null ? '—' : `${bullUi.toFixed(1)}`,
      fill01: bullUi == null ? 0 : Math.max(0, Math.min(1, bullUi / 100)),
      detail: `fuel × conviction_bull. Conviction ${convictionBull == null ? '—' : (convictionBull * 100).toFixed(0)}%.`,
      tone: 'bull',
    },
    {
      id: 'bear',
      label: 'BEAR LEG',
      display: bearUi == null ? '—' : `${bearUi.toFixed(1)}`,
      fill01: bearUi == null ? 0 : Math.max(0, Math.min(1, bearUi / 100)),
      detail: `fuel × conviction_bear. Conviction ${convictionBear == null ? '—' : (convictionBear * 100).toFixed(0)}%.`,
      tone: 'bear',
    },
  ]

  return {
    measurable,
    signed,
    fuelUi,
    squeezeRisk,
    liquidityRatio,
    atmShare,
    weightedDte,
    urgency,
    flowImbalance,
    flowWeight,
    momentum,
    momentumFresh,
    convictionBull,
    convictionBear,
    bullUi,
    bearUi,
    advM,
    advAvailable,
    state,
    stateLabel: THEORY_STATE_LABEL[state],
    formula: `tanh(${FUEL_SCALE}·SR) × (${flowWeight.toFixed(1)}·flow + ${(1 - flowWeight).toFixed(1)}·mom)`,
    terms,
  }
}
