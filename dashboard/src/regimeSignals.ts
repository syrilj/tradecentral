/**
 * Real-time signal primitives and parser helpers for multi-dimensional market regime and /regime.
 *
 * Provides:
 *  - Visual parsers for Primary Regime, Calibrated Confidence, Transition Risk, Model Agreement, and 4 Pillars.
 *  - Client-side trigger machinery and level-crossing detection between consecutive ticks.
 *  - Strict zero-spoofing honest unmeasured handling.
 */
import type {
  MarketRegimePayload,
  PrimaryRegimeType,
  CalibratedConfidence,
  TransitionRisk,
  TransitionRiskLevel,
  ModelAgreement,
  AgreementBand,
  RegimeStructuralLevels,
  RegimeProbabilities,
} from '@/regimeContracts'

/** Levels the operator can act on; crossings against these are signal events. */
export interface WatchedLevel {
  key: 'call' | 'put' | 'flip' | 'pin' | 'vwap'
  label: string
  price: number
}

export interface LevelCrossing {
  key: WatchedLevel['key']
  label: string
  price: number
  /** 'up' = spot rose through the level, 'down' = spot fell through it. */
  dir: 'up' | 'down'
}

/**
 * Levels crossed as spot moved from prevSpot to nextSpot, in the order they
 * were met (nearest to the origin first) rather than by price. An empty span
 * (no movement) crosses nothing.
 */
export function levelCrossings(
  prevSpot: number,
  nextSpot: number,
  levels: WatchedLevel[],
): LevelCrossing[] {
  if (!Number.isFinite(prevSpot) || !Number.isFinite(nextSpot) || prevSpot === nextSpot) return []
  const rising = nextSpot > prevSpot
  const lo = Math.min(prevSpot, nextSpot)
  const hi = Math.max(prevSpot, nextSpot)
  const crossed = levels.filter((l) => l.price > lo && l.price < hi)
  crossed.sort((a, b) => (rising ? a.price - b.price : b.price - a.price))
  return crossed.map((l) => ({
    key: l.key,
    label: l.label,
    price: l.price,
    dir: rising ? 'up' : 'down',
  }))
}

export interface TriggerDistance {
  /** Signed % from spot: positive above, negative below. */
  pct: number
  /** |distance| as a multiple of the 1-day expected move, when one exists. */
  emMultiple: number | null
}

export function triggerDistance(
  spot: number,
  price: number,
  em1dDollars: number | null,
): TriggerDistance {
  const emMultiple =
    em1dDollars != null && em1dDollars > 0 ? Math.abs(price - spot) / em1dDollars : null
  return { pct: ((price - spot) / spot) * 100, emMultiple }
}

/** Extract active numerical watched levels from a MarketRegimePayload. */
export function extractWatchedLevelsFromPayload(
  payload: MarketRegimePayload | null | undefined,
): WatchedLevel[] {
  if (!payload || !payload.levels) return []
  const out: WatchedLevel[] = []
  const { callWall, putWall, gammaFlip, sessionVwap } = payload.levels

  if (callWall != null && Number.isFinite(callWall) && callWall > 0) {
    out.push({ key: 'call', label: 'CALL WALL', price: callWall })
  }
  if (putWall != null && Number.isFinite(putWall) && putWall > 0) {
    out.push({ key: 'put', label: 'PUT WALL', price: putWall })
  }
  if (gammaFlip != null && Number.isFinite(gammaFlip) && gammaFlip > 0) {
    out.push({ key: 'flip', label: 'GAMMA FLIP', price: gammaFlip })
  }
  if (sessionVwap != null && Number.isFinite(sessionVwap) && sessionVwap > 0) {
    out.push({ key: 'vwap', label: 'SESSION VWAP', price: sessionVwap })
  }
  return out
}

/** Compute distance to each level in MarketRegimePayload.levels, returning null for absent levels. */
export function computePayloadLevelDistances(
  spot: number | null | undefined,
  levels: RegimeStructuralLevels | null | undefined,
  em1dDollars: number | null | undefined,
): Record<'call' | 'put' | 'flip' | 'vwap', TriggerDistance | null> {
  const res: Record<'call' | 'put' | 'flip' | 'vwap', TriggerDistance | null> = {
    call: null,
    put: null,
    flip: null,
    vwap: null,
  }
  if (spot == null || !Number.isFinite(spot) || spot <= 0 || !levels) return res
  const em =
    em1dDollars != null && Number.isFinite(em1dDollars) && em1dDollars > 0 ? em1dDollars : null

  if (levels.callWall != null && Number.isFinite(levels.callWall) && levels.callWall > 0) {
    res.call = triggerDistance(spot, levels.callWall, em)
  }
  if (levels.putWall != null && Number.isFinite(levels.putWall) && levels.putWall > 0) {
    res.put = triggerDistance(spot, levels.putWall, em)
  }
  if (levels.gammaFlip != null && Number.isFinite(levels.gammaFlip) && levels.gammaFlip > 0) {
    res.flip = triggerDistance(spot, levels.gammaFlip, em)
  }
  if (levels.sessionVwap != null && Number.isFinite(levels.sessionVwap) && levels.sessionVwap > 0) {
    res.vwap = triggerDistance(spot, levels.sessionVwap, em)
  }
  return res
}

export interface PrimaryBadgeVisual {
  label: string
  tone: 'bullish' | 'bearish' | 'neutral' | 'warning' | 'stale'
  description: string
  isUncertain: boolean
}

export function parsePrimaryRegimeBadge(
  regime: PrimaryRegimeType | string | null | undefined,
): PrimaryBadgeVisual {
  const raw = String(regime || '').trim().toLowerCase()
  switch (raw) {
    case 'bull_trend':
    case 'bullish_trend':
      return {
        label: 'BULLISH TREND',
        tone: 'bullish',
        description: 'Persistent positive kinematic velocity with supporting flow alignment.',
        isUncertain: false,
      }
    case 'bear_trend':
    case 'bearish_trend':
      return {
        label: 'BEARISH TREND',
        tone: 'bearish',
        description: 'Persistent negative kinematic velocity with breakdown pressure.',
        isUncertain: false,
      }
    case 'compression_range':
      return {
        label: 'COMPRESSION RANGE',
        tone: 'neutral',
        description: 'Compressed volatility environment with tight boundary containment.',
        isUncertain: false,
      }
    case 'mean_reverting':
      return {
        label: 'MEAN REVERTING',
        tone: 'neutral',
        description: 'Sub-diffusive Ornstein-Uhlenbeck mean-reverting decay.',
        isUncertain: false,
      }
    case 'vol_expansion_breakout':
      return {
        label: 'VOL EXPANSION BREAKOUT',
        tone: 'warning',
        description: 'Realized vol expansion breaking past historical percentile bounds.',
        isUncertain: false,
      }
    case 'uncertain_transitional':
      return {
        label: 'UNCERTAIN / TRANSITIONAL',
        tone: 'warning',
        description: 'Conflicting model signals, active changepoint hazard, or boundary proximity.',
        isUncertain: true,
      }
    case 'unmeasurable':
      return {
        label: 'UNMEASURABLE',
        tone: 'stale',
        description: 'Insufficient point-in-time data or missing options chain.',
        isUncertain: true,
      }
    default:
      return {
        label: 'UNKNOWN',
        tone: 'stale',
        description: 'Regime telemetry unavailable.',
        isUncertain: true,
      }
  }
}

export interface ConfidenceVisual {
  scorePct: number | null
  bandLabel: string
  tone: 'bullish' | 'warning' | 'danger' | 'stale'
  penaltyCount: number
  displayScore: string
  penaltySummary: string
}

export function parseConfidenceVisuals(
  confidence: CalibratedConfidence | null | undefined,
): ConfidenceVisual {
  if (!confidence || confidence.score == null || !Number.isFinite(confidence.score)) {
    return {
      scorePct: null,
      bandLabel: 'N/A',
      tone: 'stale',
      penaltyCount: 0,
      displayScore: '—',
      penaltySummary: 'No confidence score measured',
    }
  }
  const score = Math.max(0, Math.min(1, confidence.score))
  const scorePct = Math.round(score * 100)
  const band = confidence.band || (score >= 0.75 ? 'high' : score >= 0.45 ? 'moderate' : 'low')
  const tone = band === 'high' ? 'bullish' : band === 'moderate' ? 'warning' : 'danger'
  const bandLabel = band.toUpperCase()
  const penalties = Array.isArray(confidence.penaltyFactors) ? confidence.penaltyFactors : []

  return {
    scorePct,
    bandLabel,
    tone,
    penaltyCount: penalties.length,
    displayScore: `${scorePct}%`,
    penaltySummary: penalties.length > 0 ? penalties.join('; ') : 'No confidence penalties applied',
  }
}

export interface TransitionRiskVisual {
  level: TransitionRiskLevel
  tone: 'normal' | 'warning' | 'critical' | 'stale'
  isHighHazard: boolean
  displayPct: string
  stabilityPct: string
}

export function parseTransitionRiskVisuals(
  transition: TransitionRisk | null | undefined,
): TransitionRiskVisual {
  if (!transition || !transition.measured) {
    return {
      level: 'low',
      tone: 'stale',
      isHighHazard: false,
      displayPct: '—',
      stabilityPct: '—',
    }
  }
  const prob5d = Math.max(0, Math.min(1, transition.changepointProb5d ?? 0))
  const level =
    transition.level ||
    (prob5d >= 0.7 ? 'critical' : prob5d >= 0.45 ? 'high' : prob5d >= 0.25 ? 'moderate' : 'low')
  const isHighHazard = level === 'critical' || level === 'high' || prob5d >= 0.45
  const tone =
    level === 'critical' || level === 'high'
      ? 'critical'
      : level === 'moderate'
        ? 'warning'
        : 'normal'
  const stability = Math.max(0, Math.min(1, transition.stabilityScore ?? 1 - prob5d))

  return {
    level,
    tone,
    isHighHazard,
    displayPct: `${Math.round(prob5d * 100)}%`,
    stabilityPct: `${Math.round(stability * 100)}%`,
  }
}

export interface AgreementVisual {
  scorePct: number | null
  band: AgreementBand
  tone: 'high' | 'moderate' | 'low' | 'conflict' | 'stale'
  hasConflict: boolean
  consensusRatio: string
  summary: string
}

export function parseAgreementVisuals(
  agreement: ModelAgreement | null | undefined,
): AgreementVisual {
  if (!agreement) {
    return {
      scorePct: null,
      band: 'low',
      tone: 'stale',
      hasConflict: false,
      consensusRatio: '—',
      summary: 'No model agreement data available',
    }
  }
  const score =
    agreement.agreementScore != null && Number.isFinite(agreement.agreementScore)
      ? Math.max(0, Math.min(1, agreement.agreementScore))
      : 0
  const scorePct = Math.round(score * 100)
  const band = agreement.band || 'moderate'
  const hasConflict =
    band === 'conflict' || (agreement.conflictingModels && agreement.conflictingModels.length > 0)
  const totalModels =
    (agreement.agreeingModels?.length ?? 0) + (agreement.conflictingModels?.length ?? 0)
  const consensusRatio =
    totalModels > 0
      ? `${agreement.agreeingModels?.length ?? 0}/${totalModels}`
      : `${scorePct}%`
  const summary =
    agreement.divergenceSummary || (hasConflict ? 'Model divergence detected' : 'Models in consensus')

  return {
    scorePct,
    band,
    tone: band === 'conflict' ? 'conflict' : band,
    hasConflict,
    consensusRatio,
    summary,
  }
}

export interface PillarItemVisual {
  stateLabel: string
  tone: 'bullish' | 'bearish' | 'neutral' | 'warning' | 'danger' | 'stale'
  measured: boolean
  metricLabel: string
  metricValue: string
}

export interface PillarVisuals {
  trend: PillarItemVisual
  volatility: PillarItemVisual
  structure: PillarItemVisual
  flow: PillarItemVisual
}

export function parsePillars(payload: MarketRegimePayload | null | undefined): PillarVisuals {
  // Trend
  const trend = payload?.trend
  let trendTone: PillarItemVisual['tone'] = 'stale'
  let trendLabel = 'UNMEASURED'
  if (trend?.measured) {
    trendLabel = trend.state.toUpperCase().replace('_', ' ')
    if (trend.state === 'strong_up' || trend.state === 'up') trendTone = 'bullish'
    else if (trend.state === 'strong_down' || trend.state === 'down') trendTone = 'bearish'
    else trendTone = 'neutral'
  }
  const trendZ = trend?.kalmanZScore != null ? `z=${trend.kalmanZScore.toFixed(2)}` : '—'

  // Volatility
  const vol = payload?.volatility
  let volTone: PillarItemVisual['tone'] = 'stale'
  let volLabel = 'UNMEASURED'
  if (vol?.measured) {
    volLabel = vol.state.toUpperCase()
    if (vol.state === 'shock') volTone = 'danger'
    else if (vol.state === 'elevated') volTone = 'warning'
    else if (vol.state === 'compression') volTone = 'neutral'
    else volTone = 'neutral'
  }
  const volPct = vol?.volPercentile != null ? `${Math.round(vol.volPercentile * 100)}th %tile` : '—'

  // Structure
  const struct = payload?.structure
  let structTone: PillarItemVisual['tone'] = 'stale'
  let structLabel = 'UNMEASURED'
  if (struct?.measured) {
    structLabel = struct.state.toUpperCase().replace('_', ' ')
    structTone = struct.state === 'trending' ? 'bullish' : 'neutral'
  }
  const structHL = struct?.ouHalfLifeBars != null ? `t½=${struct.ouHalfLifeBars.toFixed(1)}b` : '—'

  // Flow
  const flow = payload?.flow
  let flowTone: PillarItemVisual['tone'] = 'stale'
  let flowLabel = 'UNMEASURED'
  if (flow?.measured) {
    flowLabel = flow.state.toUpperCase()
    if (flow.state === 'accumulation') flowTone = 'bullish'
    else if (flow.state === 'distribution') flowTone = 'bearish'
    else if (flow.state === 'churn') flowTone = 'warning'
    else flowTone = 'neutral'
  }
  const flowGex = flow?.dealerGammaRegime ? `Gamma: ${flow.dealerGammaRegime.toUpperCase()}` : '—'

  return {
    trend: {
      stateLabel: trendLabel,
      tone: trendTone,
      measured: !!trend?.measured,
      metricLabel: 'Kalman Velocity',
      metricValue: trendZ,
    },
    volatility: {
      stateLabel: volLabel,
      tone: volTone,
      measured: !!vol?.measured,
      metricLabel: 'Vol Environment',
      metricValue: volPct,
    },
    structure: {
      stateLabel: structLabel,
      tone: structTone,
      measured: !!struct?.measured,
      metricLabel: 'Structure Dynamics',
      metricValue: structHL,
    },
    flow: {
      stateLabel: flowLabel,
      tone: flowTone,
      measured: !!flow?.measured,
      metricLabel: 'Dealer Gamma',
      metricValue: flowGex,
    },
  }
}

export function isRegimeMeasurable(payload: MarketRegimePayload | null | undefined): boolean {
  if (!payload) return false
  if (payload.primary === 'unmeasurable') return false
  if (payload.quality && payload.quality.measurable === false) return false
  return true
}

// ---------------------------------------------------------------------------
// Lognormal probability fallback
// ---------------------------------------------------------------------------

/** Abramowitz & Stegun 7.1.26 erf, |error| < 1.5e-7 — far tighter than a
 *  displayed probability can ever express. */
function erf(x: number): number {
  const sign = x < 0 ? -1 : 1
  const ax = Math.abs(x)
  const t = 1 / (1 + 0.3275911 * ax)
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) *
      t *
      Math.exp(-ax * ax)
  return sign * y
}

export function normalCdf(z: number): number {
  return 0.5 * (1 + erf(z / Math.SQRT2))
}

export interface ApproxProbabilitiesInput {
  spot: number
  /** Annualized implied volatility as a decimal (0.24 = 24%). */
  iv: number
  /** Year fraction to the stated horizon. A 0DTE intraday read passes the
   *  remaining session fraction as trading time (remaining / 252). */
  tYears: number
  callWall: number | null
  putWall: number | null
}

/**
 * P(price beyond each wall) under a flat lognormal at the given IV and
 * horizon: z = ln(K/S) / (sigma * sqrt(T)). Fulfils the RegimeProbabilities
 * contract so the probability panel renders one shape of data regardless of
 * which model produced it; the view labels the source, so the operator always
 * knows they are reading an approximation rather than the risk-neutral density.
 */
export function approxProbabilities(input: ApproxProbabilitiesInput): RegimeProbabilities | null {
  const { spot, iv, tYears } = input
  if (!Number.isFinite(spot) || spot <= 0) return null
  if (!Number.isFinite(iv) || iv <= 0) return null
  if (!Number.isFinite(tYears) || tYears <= 0) return null
  const sigma = iv * Math.sqrt(tYears)
  if (!(sigma > 0)) return null

  const call = input.callWall
  const put = input.putWall
  const probAboveCallWall =
    call != null && Number.isFinite(call) && call > 0
      ? 1 - normalCdf(Math.log(call / spot) / sigma)
      : null
  const probBelowPutWall =
    put != null && Number.isFinite(put) && put > 0 ? normalCdf(Math.log(put / spot) / sigma) : null
  const probBetweenWalls =
    probAboveCallWall != null && probBelowPutWall != null
      ? Math.max(0, 1 - probAboveCallWall - probBelowPutWall)
      : null

  // One-sigma log band; the lognormal's mode S*exp(-sigma^2) is the natural
  // "modal target" analogue of the density read.
  const band68 = { low: Math.max(0, spot * Math.exp(-sigma)), high: spot * Math.exp(sigma) }
  return {
    probAboveCallWall,
    probBelowPutWall,
    probBetweenWalls,
    modalTarget: spot * Math.exp(-sigma * sigma),
    expectedMove: (band68.high - band68.low) / 2,
    band68,
  }
}
