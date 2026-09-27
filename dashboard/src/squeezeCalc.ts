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
  /** DTE used in fuel (front-book under the current calibration). */
  weightedDte: number | null
  /** Full-book |GEX|-weighted DTE; shown only when it differs from fuel DTE. */
  fullBookDte: number | null
  urgency: number | null
  urgencyDteBasis: string
  fuelScale: number
  flowImbalance: number | null
  flowWeight: number
  momentum: number | null
  momentumFresh: boolean
  /** Calendar age of the price series behind momentum, when shipped. */
  momentumAgeDays: number | null
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
/** Percentile-calibrated display transform; payload `fuel_scale` always wins. */
export const DEFAULT_FUEL_SCALE = 25
const MOM_REF = 0.03

/**
 * Unpack the shipped theory squeeze identity for the board.
 *
 *   SR   = |GEX⁻_1%| / ADV · e^{−c T_front40} · ATM share
 *   fuel = tanh(fuel_scale · SR)     fuel_scale defaults to 25
 *   conv = w · signed_flow + (1−w) · clip(|mom| / 3%)
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
    finiteNum(t.liquidity_ratio) ??
    finiteNum(c.theory_liquidity_ratio) ??
    (gexM != null && advFromTheory != null && advFromTheory > 0
      ? Math.abs(gexM) / advFromTheory
      : null)
  const atmShare = finiteNum(c.theory_atm_share) ?? finiteNum(gex.atm_share)
  const fullBookDte = finiteNum(c.theory_weighted_dte) ?? finiteNum(gex.weighted_dte)
  const urgencyDte =
    finiteNum(t.urgency_dte) ??
    finiteNum(c.theory_urgency_dte) ??
    finiteNum(t.front40_weighted_dte) ??
    finiteNum(c.theory_front40_weighted_dte) ??
    finiteNum(gex.front40_weighted_dte) ??
    fullBookDte
  const urgency =
    finiteNum(t.urgency) ??
    finiteNum(c.theory_urgency) ??
    (urgencyDte == null ? null : Math.exp(-URGENCY_C * urgencyDte))
  const weightedDte = urgencyDte
  const urgencyDteBasis = String(t.urgency_dte_basis ?? 'front40')
  const fuelScale = finiteNum(t.fuel_scale) ?? finiteNum(c.theory_fuel_scale) ?? DEFAULT_FUEL_SCALE
  const flowImbalanceRaw =
    finiteNum(t.directional_flow_imbalance) ?? finiteNum(c.theory_directional_flow_imbalance)
  // A 0.0 with zero confidence is not a measurement — the tape carried no
  // buy/sell side, so the honest value is "unmeasured", not a flat zero.
  const flowConfidence = finiteNum(c.theory_imbalance_confidence)
  const flowDropped = t.flow_measured === false || c.theory_flow_measured === false
  const flowImbalance =
    flowDropped || (flowImbalanceRaw != null && flowConfidence === 0) ? null : flowImbalanceRaw
  const flowWeight =
    finiteNum(t.flow_weight) ?? finiteNum(c.flow_weight) ?? (flowDropped ? 0 : DEFAULT_FLOW_WEIGHT)
  const momentum = finiteNum(t.momentum) ?? finiteNum(c.theory_momentum)
  const momentumFresh = Boolean(t.momentum_fresh ?? c.theory_momentum_fresh)
  const momentumAgeDays =
    finiteNum(t.momentum_price_age_days) ?? finiteNum(c.theory_momentum_price_age_days)
  const convictionBull = finiteNum(t.conviction_bull) ?? finiteNum(c.theory_conviction_bull)
  const convictionBear = finiteNum(t.conviction_bear) ?? finiteNum(c.theory_conviction_bear)
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
      detail:
        fullBookDte != null && weightedDte != null && Math.abs(fullBookDte - weightedDte) > 1
          ? `e^{−${URGENCY_C} · T_${urgencyDteBasis}}. Fuel uses ${weightedDte.toFixed(1)}D; full book is ${fullBookDte.toFixed(1)}D and does not drain this term.`
          : `e^{−${URGENCY_C} · T_${urgencyDteBasis}}. Near-dated gamma is more urgent; 45D is ~0.11.`,
      tone: 'fuel',
    },
    {
      id: 'fuel',
      label: `FUEL tanh(${fuelScale}·SR)`,
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
        : momentumAgeDays != null
          ? `Price series is ${momentumAgeDays} calendar days old — momentum does not drive this score.`
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
    fullBookDte,
    urgency,
    urgencyDteBasis,
    fuelScale,
    flowImbalance,
    flowWeight,
    momentum,
    momentumFresh,
    momentumAgeDays,
    convictionBull,
    convictionBear,
    bullUi,
    bearUi,
    advM,
    advAvailable,
    state,
    stateLabel: THEORY_STATE_LABEL[state],
    formula: `tanh(${fuelScale}·SR) × (${flowWeight.toFixed(1)}·flow + ${(1 - flowWeight).toFixed(1)}·mom)`,
    terms,
  }
}

/* ==========================================================================
   Plain-English explanation — the board's "how it got here".

   The squeeze score is a three-step identity: FUEL × DIRECTION = SCORE. This
   walks the shipped payload through those steps and prints the actual numbers
   at each one, so a trader can check the arithmetic instead of trusting a dial.
   Every figure is read from the payload; an input the payload did not carry is
   named as missing and never rendered as a zero.
   ========================================================================== */

export type SqueezeSide = 'bullish' | 'bearish' | 'neutral'
export type SqueezeVerdictTone = 'bullish' | 'bearish' | 'neutral' | 'warn' | 'unmeasured'

/**
 * How much of the direction pair actually voted.
 *  - measured: signed flow AND fresh 5-day momentum
 *  - partial: exactly one of the two
 *  - degraded: neither — the direction half of fuel × direction is absent, so
 *    any numeric score the payload carries is an artifact, not a read.
 */
export type SqueezeDirectionStatus = 'measured' | 'partial' | 'degraded'

export interface SqueezeChip {
  text: string
  tone: 'warn' | 'muted'
}

export interface SqueezeDirLeg {
  id: 'flow' | 'mom'
  label: string
  display: string
  fill01: number | null
  votes: boolean
  tone: 'flow' | 'mom' | 'warn'
}

export interface SqueezeStep {
  id: 'fuel' | 'direction' | 'score'
  title: string
  /** Headline value for the step, or the em-dash placeholder. */
  value: string
  /** 0–1 meter fill, or null when the step has no measured value. */
  fill01: number | null
  tone: 'fuel' | 'bullish' | 'bearish' | 'neutral' | 'warn'
  lines: string[]
}

export interface SqueezeLevel {
  id: 'call_wall' | 'put_wall' | 'gamma_flip' | 'spot'
  label: string
  price: number | null
  pct: number | null
  note: string
  tone: 'call' | 'put' | 'accent' | 'ink'
  /** True for the level that starts the move on the leaning side. */
  trigger: boolean
}

export interface SqueezeExplanation {
  measurable: boolean
  side: SqueezeSide
  tone: SqueezeVerdictTone
  verdict: string
  summary: string
  score: number | null
  scoreDisplay: string
  /** How many of the direction pair (signed flow, momentum) actually voted. */
  dirStatus: SqueezeDirectionStatus
  /** A compact "why the score looks like this" chip for the header; null when fully measured. */
  dirChip: SqueezeChip | null
  leanAt: number
  squeezeAt: number
  fuelScale: number
  formula: string
  /** Marker position on a −100…+100 scale as 0–100%, or null when unscored. */
  markerPct: number | null
  steps: SqueezeStep[]
  dirLegs: SqueezeDirLeg[]
  levels: SqueezeLevel[]
  watch: string[]
}

const DEFAULT_LEAN_AT = 20
const DEFAULT_SQUEEZE_AT = 40
const EM_DASH = '—'

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v))
}

function pct0(v: number | null): string {
  return v == null ? EM_DASH : `${Math.round(v * 100)}%`
}

function signedPct2(v: number | null): string {
  if (v == null) return EM_DASH
  const r = v * 100
  return `${r > 0 ? '+' : r < 0 ? '−' : ''}${Math.abs(r).toFixed(2)}%`
}

/** $M → compact dollars: 1511.2 → "$1.51B", 115.1 → "$115M", 0.84 → "$0.84M". */
export function formatMillions(m: number | null | undefined): string {
  if (m == null || !Number.isFinite(m)) return EM_DASH
  const a = Math.abs(m)
  const sign = m < 0 ? '−' : ''
  if (a >= 1000) return `${sign}$${(a / 1000).toFixed(2)}B`
  if (a >= 100) return `${sign}$${a.toFixed(0)}M`
  if (a >= 10) return `${sign}$${a.toFixed(1)}M`
  return `${sign}$${a.toFixed(2)}M`
}

function money(v: number): string {
  return `$${v.toFixed(2)}`
}

function signedScoreText(v: number): string {
  const r = Math.round(v)
  if (r === 0) return '0'
  return `${r > 0 ? '+' : '−'}${Math.abs(r)}`
}

export function buildSqueezeExplanation(
  squeeze: OptionsSqueeze | null | undefined,
  spotProp?: number | null,
): SqueezeExplanation {
  const id = buildTheoryIdentity(squeeze)
  const t = squeeze?.theory ?? {}
  const c = squeeze?.components ?? {}
  const kl = squeeze?.key_levels

  const leanAt = finiteNum(t.lean_threshold) ?? DEFAULT_LEAN_AT
  const squeezeAt = finiteNum(t.squeeze_threshold) ?? DEFAULT_SQUEEZE_AT
  const momRef = finiteNum(t.mom_ref) ?? MOM_REF
  const fuelScale = id.fuelScale

  const spotCandidate = finiteNum(spotProp) ?? finiteNum(kl?.spot)
  const spot = spotCandidate != null && spotCandidate > 0 ? spotCandidate : null
  const score = id.signed
  // Fuel is tanh(·) ∈ [0, 1). Anything outside that is a different quantity on a
  // different scale (legacy payloads), so it is unmeasured — not clamped to 100%.
  const fuel = id.fuelUi != null && id.fuelUi >= 0 && id.fuelUi <= 1 ? id.fuelUi : null
  const dampened = Boolean(squeeze?.long_gamma_dampened)
  const flowMeasured = id.flowImbalance != null
  const momFresh = id.momentum != null && id.momentumFresh

  // Direction is a two-leg vote: signed flow and fresh 5-day momentum. When
  // neither votes, "score 0" is an artifact of conviction being suppressed to
  // zero behind the scenes — the board shows the suppressed state, not a fake
  // flat zero that reads as measured conviction.
  const flowVotes = flowMeasured
  const momVotes = momFresh
  const dirStatus: SqueezeDirectionStatus =
    flowVotes && momVotes ? 'measured' : flowVotes || momVotes ? 'partial' : 'degraded'

  // Gates: prefer the shipped values, else re-derive from the shipped inputs.
  const momUp =
    finiteNum(t.mom_up_gate) ??
    finiteNum(c.theory_mom_up_gate) ??
    (momFresh ? clamp01(Math.max(0, id.momentum as number) / momRef) : null)
  const momDn =
    finiteNum(t.mom_dn_gate) ??
    finiteNum(c.theory_mom_dn_gate) ??
    (momFresh ? clamp01(Math.max(0, -(id.momentum as number)) / momRef) : null)
  const wFlow = flowMeasured ? id.flowWeight : 0
  const convBull =
    id.convictionBull ??
    (momUp != null || flowMeasured
      ? wFlow * clamp01(Math.max(0, id.flowImbalance ?? 0)) + (1 - wFlow) * (momUp ?? 0)
      : null)
  const convBear =
    id.convictionBear ??
    (momDn != null || flowMeasured
      ? wFlow * clamp01(Math.max(0, -(id.flowImbalance ?? 0))) + (1 - wFlow) * (momDn ?? 0)
      : null)

  const measurable = squeeze != null && id.measurable && score != null
  // The score is a read only when direction had at least one vote. In the
  // degraded state the shipped number (usually 0, because conviction is zeroed
  // out behind the scenes) is an artifact, so it is suppressed to the em-dash.
  const scoreShown = measurable && dirStatus !== 'degraded' ? score : null
  const side: SqueezeSide =
    !measurable || scoreShown == null || Math.round(scoreShown) === 0
      ? 'neutral'
      : scoreShown > 0
        ? 'bullish'
        : 'bearish'

  // ---- verdict ------------------------------------------------------------
  const label = String(squeeze?.label ?? '').toLowerCase()
  const mag = scoreShown == null ? 0 : Math.abs(scoreShown)
  const dirWord = side === 'bullish' ? 'BULL' : 'BEAR'
  const upDown = side === 'bullish' ? 'up' : 'down'
  let verdict: string
  let tone: SqueezeVerdictTone
  let summary: string
  if (!measurable) {
    verdict = 'UNMEASURED'
    tone = 'unmeasured'
    summary =
      id.advAvailable === false
        ? 'No average dollar volume for this name, so dealer gamma cannot be sized against liquidity.'
        : 'The chain did not carry enough gamma and volume data to score a squeeze.'
  } else if (dirStatus === 'degraded') {
    // Neither direction leg voted. This is an absent measurement, never a
    // quiet market and never a numeric zero.
    verdict = 'DIRECTION UNMEASURED'
    tone = 'unmeasured'
    const structure = dampened
      ? 'Dealers are long gamma, so hedging leans against moves rather than chasing them.'
      : fuel != null
        ? fuel * 100 < leanAt
          ? `Short-gamma fuel runs only ${pct0(fuel)} — under the ±${leanAt} lean band anyway.`
          : `Short-gamma fuel runs ${pct0(fuel)}.`
        : 'Even the fuel term could not be sized.'
    summary =
      `Structure only: ${structure} Neither signed flow nor a fresh momentum read was measured, ` +
      'so no direction vote stands behind this name — the score is suppressed, not a zero.'
  } else if (dampened) {
    verdict = 'DAMPENED'
    tone = 'warn'
    summary =
      'Dealers are long gamma here, so their hedging leans against moves rather than chasing them.'
  } else if (fuel != null && fuel * 100 < leanAt) {
    verdict = 'NO FUEL'
    tone = 'neutral'
    summary =
      'Dealer short gamma is small next to how much this name trades — hedging is too light to force a move.'
  } else if (
    // The readout's own label wins; the leg test only applies below the lean band,
    // which is where the backend applies it too.
    label === 'two_way' ||
    (!/_(lean|squeeze)$/.test(label) &&
      mag < leanAt &&
      (id.bullUi ?? 0) > 8 &&
      (id.bearUi ?? 0) > 8)
  ) {
    verdict = 'TWO-WAY'
    tone = 'warn'
    summary = 'Fuel is loaded but the signals disagree — a squeeze could break either way.'
  } else if (side !== 'neutral' && (label.endsWith('_squeeze') || mag >= squeezeAt)) {
    verdict = `${dirWord} SQUEEZE`
    tone = side
    summary = `Dealers are short enough gamma that hedging can feed a move ${upDown}, and direction is pointing ${upDown}.`
  } else if (side !== 'neutral' && (label.endsWith('_lean') || mag >= leanAt)) {
    verdict = `${dirWord} LEAN`
    tone = side
    summary = `Squeeze fuel is there and direction tilts ${upDown}, but not strongly enough to call a squeeze.`
  } else {
    verdict = 'NO SQUEEZE'
    tone = 'neutral'
    summary =
      'Dealers are short gamma, but nothing is pushing price hard either way — fuel without a spark.'
  }

  // ---- step 1: fuel -------------------------------------------------------
  const gexM = finiteNum(t.short_premium_gex_m?.total_gex_m)
  const fuelLines: string[] = []
  if (gexM != null) {
    fuelLines.push(`Dealers are short ${formatMillions(Math.abs(gexM))} of gamma per 1% move.`)
  }
  if (id.advAvailable && id.advM != null && id.liquidityRatio != null) {
    fuelLines.push(
      `That is ${(id.liquidityRatio * 100).toFixed(1)}% of the ${formatMillions(id.advM)} traded per day.`,
    )
  } else {
    fuelLines.push('No average dollar volume — fuel cannot be sized against liquidity.')
  }
  if (id.atmShare != null || id.weightedDte != null) {
    const atm =
      id.atmShare == null ? null : `${Math.round(id.atmShare * 100)}% sits within ±2% of spot`
    const dte =
      id.weightedDte == null
        ? null
        : id.weightedDte < 1
          ? 'mostly expiring today'
          : `front-book expiry ${id.weightedDte.toFixed(1)} days`
    const tail =
      id.fullBookDte != null &&
      id.weightedDte != null &&
      Math.abs(id.fullBookDte - id.weightedDte) > 1
        ? `full book ${id.fullBookDte.toFixed(1)}D is not in fuel`
        : null
    fuelLines.push([atm, dte, tail].filter(Boolean).join(', ') + '.')
  }
  if (id.squeezeRisk != null && fuel != null) {
    fuelLines.push(
      `Squeeze risk ${id.squeezeRisk.toFixed(4)} → tanh(${fuelScale} × risk) = ${pct0(fuel)} fuel.`,
    )
  }

  // ---- step 2: direction --------------------------------------------------
  const dirLines: string[] = []
  if (flowMeasured) {
    dirLines.push(
      `Signed flow ${formatSignedScore(id.flowImbalance)} (buyers minus sellers), weight ${pct0(wFlow)}.`,
    )
  } else {
    dirLines.push("Signed flow — UNMEASURED: the tape has no buy/sell side, so it doesn't vote.")
  }
  if (momFresh) {
    const gate = (id.momentum as number) >= 0 ? momUp : momDn
    dirLines.push(
      `5-day move ${signedPct2(id.momentum)} → ${pct0(gate)} of the ±${(momRef * 100).toFixed(0)}% cap, weight ${pct0(1 - wFlow)}.`,
    )
  } else {
    dirLines.push(
      id.momentumAgeDays != null
        ? `5-day momentum — UNMEASURED: the price series is ${id.momentumAgeDays} calendar days old, so it doesn't vote.`
        : "5-day momentum — UNMEASURED: price data is stale, so it doesn't vote.",
    )
  }
  // Conviction is a blend of the two legs; with no legs voting, printing
  // "bull 0% · bear 0%" would present the artifact as a measured flat zero.
  if (dirStatus !== 'degraded' && (convBull != null || convBear != null)) {
    dirLines.push(`Conviction: bull ${pct0(convBull)} · bear ${pct0(convBear)}.`)
  }
  const dirLead =
    convBull == null && convBear == null
      ? null
      : (convBull ?? 0) >= (convBear ?? 0)
        ? { word: 'BULL', v: convBull ?? 0, tone: 'bullish' as const }
        : { word: 'BEAR', v: convBear ?? 0, tone: 'bearish' as const }
  const dirValue =
    dirStatus === 'degraded' || dirLead == null
      ? EM_DASH
      : dirLead.v < 0.005
        ? 'NONE'
        : `${dirLead.word} ${pct0(dirLead.v)}`

  // ---- step 3: score ------------------------------------------------------
  const scoreLines: string[] = []
  if (dirStatus === 'degraded' && measurable) {
    scoreLines.push(
      'Neither direction leg voted, so fuel × direction is suppressed instead of computed.',
    )
    scoreLines.push('A printed 0 here would be an artifact, not a quiet market.')
  } else if (id.bullUi != null && id.bearUi != null) {
    if (fuel != null && convBull != null && convBear != null) {
      scoreLines.push(`Bull leg: ${pct0(fuel)} fuel × ${pct0(convBull)} = ${id.bullUi.toFixed(1)}.`)
      scoreLines.push(`Bear leg: ${pct0(fuel)} fuel × ${pct0(convBear)} = ${id.bearUi.toFixed(1)}.`)
    } else {
      // Inputs to re-derive the legs were not shipped — report the legs as given.
      scoreLines.push(`Bull leg ${id.bullUi.toFixed(1)} · bear leg ${id.bearUi.toFixed(1)}.`)
    }
  }
  if (scoreShown != null) {
    scoreLines.push(
      `Bull − bear = ${signedScoreText(scoreShown)}. Lean at ±${leanAt}, squeeze at ±${squeezeAt}.`,
    )
  }

  const steps: SqueezeStep[] = [
    {
      id: 'fuel',
      title: 'FUEL',
      value: pct0(fuel),
      fill01: fuel == null ? null : clamp01(fuel),
      tone: dampened ? 'warn' : 'fuel',
      lines: fuelLines,
    },
    {
      id: 'direction',
      title: 'DIRECTION',
      value: dirValue,
      fill01: dirStatus === 'degraded' || dirLead == null ? null : clamp01(dirLead.v),
      tone:
        dirStatus === 'degraded'
          ? 'warn'
          : dirLead == null || dirLead.v < 0.005
            ? 'neutral'
            : dirLead.tone,
      lines: dirLines,
    },
    {
      id: 'score',
      title: 'SCORE',
      value: scoreShown == null ? EM_DASH : signedScoreText(scoreShown),
      fill01: scoreShown == null ? null : clamp01(Math.abs(scoreShown) / 100),
      tone: scoreShown == null || side === 'neutral' ? 'neutral' : side,
      lines: scoreLines,
    },
  ]

  // ---- levels -------------------------------------------------------------
  const lvl = (v: unknown) => {
    const n = finiteNum(v)
    return n != null && n > 0 ? n : null
  }
  const callWall = lvl(kl?.call_wall)
  const putWall = lvl(kl?.put_wall)
  const flip = lvl(kl?.gamma_flip)
  const dist = (p: number | null) => (p == null ? null : (distanceFromSpot(p, spot)?.pct ?? null))
  const regime = gammaRegimeSide(spot, flip)
  const levels: SqueezeLevel[] = [
    {
      id: 'call_wall',
      label: 'CALL WALL',
      price: callWall,
      pct: dist(callWall),
      note:
        side === 'bullish'
          ? 'Trigger — a break above makes dealers buy more'
          : 'Largest call gamma — tends to cap rallies',
      tone: 'call',
      trigger: side === 'bullish',
    },
    {
      id: 'gamma_flip',
      label: 'GAMMA FLIP',
      price: flip,
      pct: dist(flip),
      note:
        regime === 'below_flip'
          ? 'Spot is below — dealers amplify moves'
          : regime === 'above_flip'
            ? 'Spot is above — dealers absorb moves'
            : 'Where dealer hedging changes sides',
      tone: 'accent',
      trigger: false,
    },
    {
      id: 'spot',
      label: 'SPOT',
      price: spot,
      pct: spot == null ? null : 0,
      note: 'Last price',
      tone: 'ink',
      trigger: false,
    },
    {
      id: 'put_wall',
      label: 'PUT WALL',
      price: putWall,
      pct: dist(putWall),
      note:
        side === 'bearish'
          ? 'Trigger — a break below makes dealers sell more'
          : 'Largest put gamma — tends to hold dips',
      tone: 'put',
      trigger: side === 'bearish',
    },
  ]
  const measuredLevels = levels.filter((l) => l.price != null)
  measuredLevels.sort((a, b) => (b.price as number) - (a.price as number))

  // ---- what would change it -----------------------------------------------
  const watch: string[] = []
  if (measurable && fuel != null) {
    const ceiling = fuel * 100
    if (ceiling < leanAt) {
      watch.push(
        `Fuel caps the score at ±${Math.round(ceiling)} — it needs more dealer short gamma before any lean is possible.`,
      )
    } else if (!dampened && mag < squeezeAt) {
      const target = mag < leanAt ? leanAt : squeezeAt
      const needConv = target / ceiling
      if (needConv <= 1 && !flowMeasured) {
        const needMove = needConv * momRef * 100
        watch.push(
          `A 5-day move of ±${needMove.toFixed(1)}% would lift it to a ${target === leanAt ? 'lean' : 'squeeze'} at this fuel.`,
        )
      } else if (needConv <= 1) {
        watch.push(
          `Conviction of ${Math.round(needConv * 100)}% on one side would lift it to a ${target === leanAt ? 'lean' : 'squeeze'}.`,
        )
      } else {
        watch.push(`At ${pct0(fuel)} fuel a full squeeze (±${squeezeAt}) is out of reach.`)
      }
    }
  }
  if (flip != null && spot != null) {
    const d = dist(flip)
    const where = d == null ? '' : ` (${signedPct2(d)})`
    watch.push(
      regime === 'below_flip'
        ? `Reclaiming the flip at ${money(flip)}${where} puts dealers back on the absorbing side.`
        : `Losing the flip at ${money(flip)}${where} puts dealers on the chasing side.`,
    )
  }
  if (measurable && !flowMeasured) {
    watch.push(
      dirStatus === 'degraded'
        ? 'Signed prints with a buyer/seller side would give flow a direction vote.'
        : 'Buy/sell-signed prints would add flow as a second vote on direction.',
    )
  }
  if (measurable && !momVotes) {
    watch.push(
      id.momentumAgeDays != null
        ? `Momentum data is ${id.momentumAgeDays} calendar days old — a fresh 5-day close would restore the momentum vote.`
        : 'A fresh 5-day close would restore the momentum vote.',
    )
  }
  if (measurable && id.weightedDte != null && id.weightedDte < 1) {
    watch.push(
      'Most of this front-book gamma expires today — the fuel resets with the next expiry.',
    )
  }

  const dirChip: SqueezeChip | null = !measurable
    ? null
    : dirStatus === 'measured'
      ? null
      : dirStatus === 'partial'
        ? {
            text: `DIRECTION PARTIAL · ${flowVotes ? 'MOMENTUM' : 'SIGNED FLOW'} UNMEASURED`,
            tone: 'warn',
          }
        : { text: 'DIRECTION UNMEASURED · SCORE SUPPRESSED', tone: 'warn' }

  const dirLegs: SqueezeDirLeg[] = [
    {
      id: 'flow',
      label: 'SIGNED FLOW',
      display: flowMeasured ? formatSignedScore(id.flowImbalance) : 'UNMEASURED',
      fill01: flowMeasured ? clamp01(Math.abs(id.flowImbalance ?? 0)) : null,
      votes: flowVotes,
      tone: flowVotes ? 'flow' : 'warn',
    },
    {
      id: 'mom',
      label: '5D MOMENTUM',
      display: momFresh
        ? signedPct2(id.momentum)
        : id.momentumAgeDays != null
          ? `STALE ${id.momentumAgeDays}D`
          : 'UNMEASURED',
      fill01: momFresh ? clamp01(Math.abs(id.momentum as number) / momRef) : null,
      votes: momVotes,
      tone: momVotes ? 'mom' : 'warn',
    },
  ]

  return {
    measurable,
    side,
    tone,
    verdict,
    summary,
    score: scoreShown,
    scoreDisplay: scoreShown != null ? signedScoreText(scoreShown) : EM_DASH,
    dirStatus,
    dirChip,
    leanAt,
    squeezeAt,
    fuelScale,
    formula: id.formula,
    markerPct: scoreShown != null ? 50 + Math.max(-100, Math.min(100, scoreShown)) / 2 : null,
    steps,
    dirLegs,
    levels: measuredLevels,
    watch: watch.slice(0, 4),
  }
}
