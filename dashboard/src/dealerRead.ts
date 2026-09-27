import type { OptionsIntelligence } from './api'

export type DealerReadStatus =
  | 'unavailable'
  | 'stale'
  | 'in_range'
  | 'above_call_wall'
  | 'below_put_wall'

export interface DealerRead {
  status: DealerReadStatus
  headline: string
  tone: 'neutral' | 'caution' | 'positive' | 'negative'
  narrative: string
  watch: string
  position: string
  evidence: {
    spot: number | null
    callWall: number | null
    putWall: number | null
    totalGexM: number | null
    netCharmFlow: number | null
    charmPressure: string | null
    pressureVerdict: string | null
    pressureActionable: boolean | null
    asofUtc: string | null
    ageSeconds: number | null
    freshness: 'fresh' | 'stale' | 'unknown'
  }
}

const MAX_FRESH_AGE_SECONDS = 5 * 60

function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function resolveFreshnessAndAge(payload: OptionsIntelligence, nowMs: number): {
  ageSeconds: number | null
  freshness: 'fresh' | 'stale' | 'unknown'
} {
  const sourceAges = [
    finite(payload.freshness?.age_seconds),
    finite(payload.freshness?.feed_age_seconds),
    finite(payload.freshness?.tape_age_seconds),
  ].filter((age): age is number => age !== null && age >= 0)
  const asof = Date.parse(payload.asof_utc)
  const asofAge = Number.isFinite(asof) ? Math.max(0, (nowMs - asof) / 1000) : null

  if (asofAge !== null && asofAge > MAX_FRESH_AGE_SECONDS) {
    const ageSeconds = sourceAges.length ? Math.max(...sourceAges, asofAge) : asofAge
    return { ageSeconds, freshness: 'stale' }
  }

  if (!sourceAges.length) {
    return { ageSeconds: null, freshness: 'unknown' }
  }

  const ageSeconds = asofAge !== null ? Math.max(...sourceAges, asofAge) : Math.max(...sourceAges)
  const freshness = ageSeconds > MAX_FRESH_AGE_SECONDS ? 'stale' : 'fresh'
  return { ageSeconds, freshness }
}

/**
 * Produce one conservative structural read from the options snapshot.
 * This classifies spot against supplied walls; it does not predict direction,
 * infer a gamma flip, or authorize an execution.
 */
export function resolveDealerRead(
  payload: OptionsIntelligence | null,
  now: Date | number = Date.now(),
): DealerRead {
  const nowMs = now instanceof Date ? now.getTime() : now
  const emptyEvidence: DealerRead['evidence'] = {
    spot: null,
    callWall: null,
    putWall: null,
    totalGexM: null,
    netCharmFlow: null,
    charmPressure: null,
    pressureVerdict: null,
    pressureActionable: null,
    asofUtc: null,
    ageSeconds: null,
    freshness: 'unknown',
  }
  if (!payload) {
    return {
      status: 'unavailable', headline: 'Dealer read unavailable', tone: 'neutral',
      narrative: 'No options snapshot is available, so spot location and dealer positioning cannot be read.',
      watch: 'Wait for a usable options snapshot.', position: 'No structural read', evidence: emptyEvidence,
    }
  }

  const spot = finite(payload.summary?.spot)
  const callWall = finite(payload.summary?.call_wall)
  const putWall = finite(payload.summary?.put_wall)
  const gex = payload.quality?.gex_measurable === false ? null : finite(payload.summary?.total_gex_m)
  const charm = (finite(payload.charm_summary?.contracts_measured) ?? 0) > 0
    ? finite(payload.charm_summary?.net_charm_flow)
    : null
  const { ageSeconds, freshness } = resolveFreshnessAndAge(payload, nowMs)
  const staleMode = payload.mode_resolved !== 'live'
  // A nominally live mode is not proof that the underlying snapshot is fresh.
  // If no source age/as-of is available, do not promote the read as current.
  const stale = freshness !== 'fresh' || staleMode || payload.pressure?.underlying?.stale === true
  const evidence: DealerRead['evidence'] = {
    spot, callWall, putWall, totalGexM: gex, netCharmFlow: charm,
    charmPressure: payload.charm_summary?.pressure ?? null,
    pressureVerdict: payload.pressure?.verdict ?? null,
    pressureActionable: typeof payload.pressure?.actionable === 'boolean' ? payload.pressure.actionable : null,
    asofUtc: payload.asof_utc || null, ageSeconds, freshness,
  }

  const missing: string[] = []
  if (spot === null || spot <= 0) missing.push('spot')
  if (callWall === null || callWall <= 0) missing.push('call wall')
  if (putWall === null || putWall <= 0) missing.push('put wall')
  if (callWall !== null && putWall !== null && callWall <= putWall) missing.push('ordered call/put walls')
  const missingText = missing.length ? ` Missing or invalid: ${missing.join(', ')}.` : ''
  const charmText = charm === null
    ? 'Charm is unavailable.'
    : `Charm model proxy is ${payload.charm_summary?.pressure ?? 'unclassified'} (${charm.toLocaleString()} net flow); it is context, not confirmation.`
  const gexText = gex === null ? 'GEX is unavailable or not measurable.' : `Net GEX is ${gex.toLocaleString()}M; this is gamma context, separate from directional evidence.`

  if (stale) {
    return {
      status: 'stale', headline: 'Stale dealer snapshot', tone: 'caution',
      narrative: `The snapshot is ${freshness === 'stale' ? 'older than five minutes' : freshness === 'unknown' ? 'of unverified age' : staleMode ? `from ${payload.mode_resolved} mode` : 'marked stale by the underlying feed'}. Do not use its wall location as a current read. ${charmText} ${gexText}`,
      watch: 'Refresh the live snapshot before interpreting current price location.',
      position: spot === null ? 'Spot unavailable' : `Last reported spot ${spot.toFixed(2)}; current position is unverified.`,
      evidence,
    }
  }

  if (missing.length || spot === null || callWall === null || putWall === null || callWall <= putWall) {
    return {
      status: 'unavailable', headline: 'Dealer location unavailable', tone: 'neutral',
      narrative: `The snapshot does not contain a valid spot and ordered call/put walls.${missingText} ${charmText} ${gexText}`,
      watch: 'Use only the wall levels that are explicitly present; no complete range can be stated.',
      position: spot === null ? 'Spot unavailable' : `Spot ${spot.toFixed(2)}; wall position incomplete.`,
      evidence,
    }
  }

  let status: DealerReadStatus
  let headline: string
  let position: string
  if (spot > callWall) {
    status = 'above_call_wall'; headline = 'Spot above call wall'; position = `${spot.toFixed(2)} > call wall ${callWall.toFixed(2)}`
  } else if (spot < putWall) {
    status = 'below_put_wall'; headline = 'Spot below put wall'; position = `${spot.toFixed(2)} < put wall ${putWall.toFixed(2)}`
  } else {
    status = 'in_range'; headline = 'Spot inside dealer walls'; position = `${putWall.toFixed(2)} ≤ spot ${spot.toFixed(2)} ≤ ${callWall.toFixed(2)}`
  }
  const location = status === 'in_range'
    ? 'Spot is between the supplied put and call walls, including equality at either wall.'
    : status === 'above_call_wall'
      ? 'Spot is strictly above the supplied call wall. This is a location, not evidence of a breakout or follow-through.'
      : 'Spot is strictly below the supplied put wall. This is a location, not evidence of a breakdown or follow-through.'
  return {
    status, headline, tone: 'neutral',
    narrative: `${location} ${gexText} ${charmText} Pressure/actionable fields are reported as source evidence only and do not confirm this structural read.`,
    watch: `Watch whether spot holds relative to ${putWall.toFixed(2)} put wall and ${callWall.toFixed(2)} call wall; a wall crossing alone does not establish a gamma flip.`,
    position, evidence,
  }
}
