/**
 * Price Draw and Market Regime Telemetry Contracts.
 *
 * Provides shared TypeScript types, type guards, telemetry calculation helpers,
 * and zero-spoofing formatting utilities for the Real-Time Market Regime Detection
 * and Price Attraction / Magnet Levels Engine.
 */

export type MarketRegimeType =
  | 'volatility_dampening' // Dealers Long Gamma (Mean-reverting, range-bound)
  | 'volatility_amplification' // Dealers Short Gamma (Trend acceleration, breakouts)
  | 'charm_decay_selling' // Positive Charm (Delta bleed forcing dealer selling)
  | 'charm_decay_buying' // Negative Charm (Delta bleed forcing dealer buying)
  | 'vanna_vol_expansion' // Vanna sensitivity amplifying vol shocks
  | 'neutral_transition' // Inside flip band / near-zero net gamma
  | 'unmeasurable' // Missing OI / chain quotes

export type PriceDrawLevelType =
  | 'call_wall'
  | 'put_wall'
  | 'gamma_flip'
  | 'max_pain_pin'
  | 'volume_poc'
  | 'kinematic_drift'
  | 'confluence_zone'

export type DominantDirectionType = 'bullish_pull' | 'bearish_pull' | 'neutral_pin' | 'unmeasured'

export interface PriceDrawLevel {
  id: string
  type: PriceDrawLevelType
  label: string
  price: number
  distance_pts: number | null
  distance_pct: number | null
  pull_score: number | null // 0 to 100 gravitational intensity score
  direction: 'above' | 'below' | 'at_spot'
  regime_role: string // e.g. "Overhead Resistance Cap", "Breakout Acceleration"
  supporting_lenses: string[] // e.g. ["GAMMA", "THETA", "VOLUME", "KALMAN"]
  lens_count: number
  is_primary_magnet: boolean
}

export interface ConfluenceCluster {
  level: number
  distance_pct: number | null
  supporting_lenses: string[]
  lens_count: number
  labels: string[]
  above_spot: boolean
}

export interface QualityBreakdown {
  measurable: boolean
  open_interest_available: boolean
  iv_available: boolean
  volume_available: boolean
  reason: string | null
}

export interface PriceDrawTelemetryPayload {
  symbol: string
  spot: number | null
  asof_utc: string
  regime_state: MarketRegimeType
  regime_label: string
  regime_strength: number | null // 0.0 to 1.0 scale-free strength
  dominant_direction: DominantDirectionType
  primary_magnet: PriceDrawLevel | null
  levels: PriceDrawLevel[]
  confluence_clusters: ConfluenceCluster[]
  quality: QualityBreakdown
  warnings: string[]
}

// ---------------------------------------------------------------------------
// Pure Helper Functions & Type Guards
// ---------------------------------------------------------------------------

export const UNMEASURED_PLACEHOLDER = '\u2014' // Em dash "—"

export function isRegimeMeasurable(regime: MarketRegimeType): boolean {
  return regime !== 'unmeasurable'
}

export function isLevelMeasurable(level: PriceDrawLevel): boolean {
  return level.distance_pts !== null && level.distance_pct !== null && level.pull_score !== null
}

export function getRegimeLabel(regime: MarketRegimeType): string {
  switch (regime) {
    case 'volatility_dampening':
      return 'Vol Dampening (Long \u0393)'
    case 'volatility_amplification':
      return 'Vol Amplification (Short \u0393)'
    case 'charm_decay_selling':
      return 'Charm Decay (Selling Drift)'
    case 'charm_decay_buying':
      return 'Charm Decay (Buying Drift)'
    case 'vanna_vol_expansion':
      return 'Vanna Expansion (Vol Shock)'
    case 'neutral_transition':
      return 'Neutral Transition (\u0393-Flip Band)'
    case 'unmeasurable':
    default:
      return 'Unmeasured Regime'
  }
}

export function getRegimeBadgeClass(regime: MarketRegimeType): string {
  switch (regime) {
    case 'volatility_dampening':
      return 'regime-badge--dampening'
    case 'volatility_amplification':
      return 'regime-badge--amplification'
    case 'charm_decay_selling':
    case 'charm_decay_buying':
      return 'regime-badge--charm'
    case 'vanna_vol_expansion':
      return 'regime-badge--vanna'
    case 'neutral_transition':
      return 'regime-badge--neutral'
    case 'unmeasurable':
    default:
      return 'regime-badge--unmeasured'
  }
}

export function formatDistancePoints(distancePts: number | null): string {
  if (distancePts === null || Number.isNaN(distancePts) || !Number.isFinite(distancePts)) {
    return UNMEASURED_PLACEHOLDER
  }
  const prefix = distancePts > 0 ? '+' : ''
  return `${prefix}${distancePts.toFixed(2)}`
}

export function formatDistancePercent(distancePct: number | null): string {
  if (distancePct === null || Number.isNaN(distancePct) || !Number.isFinite(distancePct)) {
    return UNMEASURED_PLACEHOLDER
  }
  const prefix = distancePct > 0 ? '+' : ''
  return `${prefix}${distancePct.toFixed(2)}%`
}

export function formatPullScore(pullScore: number | null): string {
  if (pullScore === null || Number.isNaN(pullScore) || !Number.isFinite(pullScore)) {
    return UNMEASURED_PLACEHOLDER
  }
  const clamped = Math.min(100, Math.max(0, pullScore))
  return clamped.toFixed(0)
}

export function getDirectionalVector(
  price: number,
  spot: number | null,
): 'above' | 'below' | 'at_spot' {
  if (spot === null || Number.isNaN(spot) || !Number.isFinite(spot)) {
    return 'at_spot'
  }
  const diff = price - spot
  if (Math.abs(diff) < 1e-4) {
    return 'at_spot'
  }
  return diff > 0 ? 'above' : 'below'
}

export function computeDistanceTelemetry(
  price: number,
  spot: number | null,
): {
  distance_pts: number | null
  distance_pct: number | null
  direction: 'above' | 'below' | 'at_spot'
} {
  if (spot === null || Number.isNaN(spot) || !Number.isFinite(spot) || spot <= 0) {
    return {
      distance_pts: null,
      distance_pct: null,
      direction: 'at_spot',
    }
  }
  const pts = price - spot
  const pct = (pts / spot) * 100.0
  return {
    distance_pts: Number(pts.toFixed(4)),
    distance_pct: Number(pct.toFixed(4)),
    direction: getDirectionalVector(price, spot),
  }
}

export function computeConfluenceClusters(
  levels: PriceDrawLevel[],
  spot: number | null,
  clusterThresholdPct: number = 0.75,
): ConfluenceCluster[] {
  if (!levels || levels.length === 0 || spot === null || spot <= 0) {
    return []
  }

  const validLevels = levels.filter((l) => Number.isFinite(l.price) && l.price > 0)
  if (validLevels.length === 0) {
    return []
  }

  // Sort by price ascending
  const sorted = [...validLevels].sort((a, b) => a.price - b.price)
  const clusters: ConfluenceCluster[] = []
  let currentGroup: PriceDrawLevel[] = [sorted[0]]

  for (let i = 1; i < sorted.length; i++) {
    const prev = currentGroup[currentGroup.length - 1]
    const curr = sorted[i]
    const pctDiff = (Math.abs(curr.price - prev.price) / spot) * 100.0

    if (pctDiff <= clusterThresholdPct) {
      currentGroup.push(curr)
    } else {
      if (currentGroup.length >= 2) {
        clusters.push(buildCluster(currentGroup, spot))
      }
      currentGroup = [curr]
    }
  }

  if (currentGroup.length >= 2) {
    clusters.push(buildCluster(currentGroup, spot))
  }

  return clusters
}

function buildCluster(group: PriceDrawLevel[], spot: number): ConfluenceCluster {
  const avgPrice = group.reduce((sum, item) => sum + item.price, 0) / group.length
  const allLenses = new Set<string>()
  const labels: string[] = []

  for (const item of group) {
    labels.push(item.label)
    if (item.supporting_lenses) {
      for (const lens of item.supporting_lenses) {
        allLenses.add(lens)
      }
    }
  }

  const distPct = ((avgPrice - spot) / spot) * 100.0

  return {
    level: Number(avgPrice.toFixed(2)),
    distance_pct: Number(distPct.toFixed(2)),
    supporting_lenses: Array.from(allLenses),
    lens_count: allLenses.size,
    labels,
    above_spot: avgPrice >= spot,
  }
}

export function determineDominantDirection(
  levels: PriceDrawLevel[],
  spot: number | null,
): DominantDirectionType {
  if (!levels || levels.length === 0 || spot === null || spot <= 0) {
    return 'unmeasured'
  }

  let totalAboveScore = 0
  let totalBelowScore = 0
  let measuredCount = 0

  for (const lvl of levels) {
    if (lvl.pull_score !== null && lvl.pull_score > 0) {
      measuredCount++
      if (lvl.price > spot) {
        totalAboveScore += lvl.pull_score
      } else if (lvl.price < spot) {
        totalBelowScore += lvl.pull_score
      }
    }
  }

  if (measuredCount === 0) {
    return 'unmeasured'
  }

  const diff = Math.abs(totalAboveScore - totalBelowScore)
  const sum = totalAboveScore + totalBelowScore

  if (sum === 0 || diff / sum < 0.15) {
    return 'neutral_pin'
  }

  return totalAboveScore > totalBelowScore ? 'bullish_pull' : 'bearish_pull'
}

export function createUnmeasuredPayload(
  symbol: string,
  reason: string = 'Open interest and chain feed unavailable',
): PriceDrawTelemetryPayload {
  return {
    symbol: symbol.toUpperCase(),
    spot: null,
    asof_utc: new Date().toISOString(),
    regime_state: 'unmeasurable',
    regime_label: getRegimeLabel('unmeasurable'),
    regime_strength: null,
    dominant_direction: 'unmeasured',
    primary_magnet: null,
    levels: [],
    confluence_clusters: [],
    quality: {
      measurable: false,
      open_interest_available: false,
      iv_available: false,
      volume_available: false,
      reason,
    },
    warnings: [reason],
  }
}
