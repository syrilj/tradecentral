/**
 * The Brief's reading logic, kept out of the view so it can be tested.
 *
 * The direction call is NOT computed here. It comes from `/api/adaptive-signal`,
 * which already blends the repo's own streams under weights the stack derives
 * (a regime map, optionally tilted by measured shadow-outcome hit rates). An
 * earlier version of this page invented its own weights and mapped dealer
 * gamma onto a direction axis; that read NVDA as "leans bullish, +1.00" on a
 * day the calibrated blend called neutral at +0.007. This module now only
 * shapes that payload for display, and says plainly when the weights behind
 * it were never performance-tilted.
 */

export type Side = 'long' | 'short' | 'neutral'

export interface StreamRead {
  name: string
  /** Raw stream score, ordinal and unbounded in practice. */
  score: number
  /** Weight the stack assigned this stream, 0..1. */
  weight: number
  /** weight × score — what it actually moved the composite by. */
  contribution: number
}

export interface CallRead {
  side: Side
  score: number
  /** thin | moderate | strong | conflicted, from the stack. */
  band: string
  streams: StreamRead[]
  /** How the weights were arrived at, verbatim from the payload. */
  adaptationMode: string
  /**
   * True only when measured outcomes actually tilted the weights. When false
   * the blend is a regime map — defensible, but not validated against
   * historical performance, and the UI must not imply otherwise.
   */
  performanceTilted: boolean
  /** Human sentence for the weight provenance, always shown. */
  weightNote: string
  reasons: string[]
}

export interface AdaptiveLike {
  side?: string
  composite_score?: number | null
  agreement_band?: string
  stream_scores?: Record<string, number | null>
  weights?: {
    base?: Record<string, number>
    adapted?: Record<string, number>
    adaptation_mode?: string
    contributions?: Record<string, number>
  }
  reasons?: string[]
}

export interface HitRatesLike {
  events_scored?: number
  min_events?: number
  stream_performance?: Record<string, number>
}

function normaliseSide(raw: string | undefined): Side {
  return raw === 'long' || raw === 'short' ? raw : 'neutral'
}

/**
 * Shape one adaptive-signal row for the call card.
 *
 * Streams are ordered by absolute contribution, not by weight: a heavily
 * weighted stream that scored near zero moved nothing, and listing it first
 * would misrepresent what produced the number.
 */
export function readCall(
  signal: AdaptiveLike | null | undefined,
  hitRates?: HitRatesLike | null,
): CallRead | null {
  if (!signal) return null

  const weights = signal.weights?.adapted ?? signal.weights?.base ?? {}
  const scores = signal.stream_scores ?? {}
  const contributions = signal.weights?.contributions ?? {}

  const streams: StreamRead[] = Object.keys(weights)
    .map((name) => {
      const score = scores[name]
      const weight = weights[name] ?? 0
      const contribution = contributions[name] ?? (typeof score === 'number' ? weight * score : 0)
      return {
        name,
        score: typeof score === 'number' ? score : 0,
        weight,
        contribution,
      }
    })
    .filter((s) => s.weight > 0)
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))

  const scored = hitRates?.events_scored ?? 0
  const required = hitRates?.min_events ?? 0
  const perfKeys = Object.keys(hitRates?.stream_performance ?? {})
  const mode = signal.weights?.adaptation_mode ?? 'unknown'
  /* `regime_map_only` is the stack's own label for "no performance tilt was
     applied". Trust that over guessing from the hit-rate payload. */
  const performanceTilted = mode !== 'regime_map_only' && perfKeys.length > 0

  const weightNote = performanceTilted
    ? `Weights tilted by measured outcomes across ${scored} scored events.`
    : required > 0 && scored < required
      ? `Weights come from the regime map only — ${scored} of ${required} outcome events needed to tilt them by measured performance.`
      : 'Weights come from the regime map only — not tilted by measured performance.'

  return {
    side: normaliseSide(signal.side),
    score: typeof signal.composite_score === 'number' ? signal.composite_score : 0,
    band: signal.agreement_band ?? 'unknown',
    streams,
    adaptationMode: mode,
    performanceTilted,
    weightNote,
    reasons: signal.reasons ?? [],
  }
}

/** `technical:above_ma20` → `technical · above ma20`, for chip display. */
export function prettyReason(raw: string): string {
  const [stream, ...rest] = raw.split(':')
  const detail = rest.join(':').replace(/_/g, ' ')
  return detail ? `${stream} · ${detail}` : raw.replace(/_/g, ' ')
}

/**
 * Turn a transport-layer failure into something a reader can act on.
 *
 * The raw strings carry the internal path and the timeout budget
 * ("API request timed out after 30s: /api/supply-chain?symbol=INFQ&depth=2").
 * That is a debugging aid, not a product surface, and it should never reach a
 * user — so the endpoint is stripped and the lens is named instead.
 */
export function humaniseError(raw: string | null, lens: string): string | null {
  if (!raw) return null
  const text = raw.toLowerCase()
  if (text.includes('timed out') || text.includes('timeout')) {
    return `${lens} took too long to respond. It may not be available for this symbol.`
  }
  if (text.includes('404') || text.includes('not found')) {
    return `No ${lens.toLowerCase()} data exists for this symbol.`
  }
  if (text.includes('failed to fetch') || text.includes('networkerror')) {
    return `Could not reach the ${lens.toLowerCase()} service.`
  }
  if (/\b5\d\d\b/.test(text)) {
    return `The ${lens.toLowerCase()} service returned an error.`
  }
  return `${lens} is unavailable right now.`
}

export interface WorryItem {
  severity: 'high' | 'medium' | 'low'
  title: string
  detail: string
}

const SEVERITY_ORDER: Record<WorryItem['severity'], number> = { high: 0, medium: 1, low: 2 }

export function sortWorries(items: WorryItem[]): WorryItem[] {
  return [...items].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity])
}

export type LevelKind = 'call_wall' | 'put_wall' | 'gamma_flip' | 'pin' | 'vol_trigger' | 'peak'

export interface WatchLevel {
  kind: LevelKind
  label: string
  price: number
  /** Signed distance from spot, in percent. */
  distPct: number
  /** What price does when it gets there, from the level's own mechanics. */
  meaning: string
  side: 'above' | 'below'
}

const LEVEL_MEANING: Record<LevelKind, string> = {
  call_wall: 'dealers sell rallies',
  put_wall: 'dealers buy dips',
  gamma_flip: 'vol regime changes',
  pin: 'draws price in',
  vol_trigger: 'hedging turns pro-cyclical',
  peak: 'deepest gamma',
}

/**
 * Rank the levels a reader should actually watch: nearest first, because a
 * wall 12% away is trivia and a flip 0.3% away is the whole session.
 */
export function rankLevels(
  spot: number | null,
  raw: Array<{ kind: LevelKind; label: string; price: number | null | undefined }>,
): WatchLevel[] {
  if (typeof spot !== 'number' || !(spot > 0)) return []
  const out: WatchLevel[] = []
  for (const r of raw) {
    if (typeof r.price !== 'number' || !Number.isFinite(r.price) || r.price <= 0) continue
    const distPct = ((r.price - spot) / spot) * 100
    out.push({
      kind: r.kind,
      label: r.label,
      price: r.price,
      distPct,
      meaning: LEVEL_MEANING[r.kind],
      side: distPct >= 0 ? 'above' : 'below',
    })
  }
  return out.sort((a, b) => Math.abs(a.distPct) - Math.abs(b.distPct))
}

/* ── where price is being pulled ─────────────────────────────────────────
   "Which way does it lean" and "what price does it lean toward" are two
   different questions, and the second is the one a reader actually acts on.
   `/api/price-attractors` answers it: a gravitational pull score per candidate
   destination, scored across gamma, Kalman, volume and expiry lenses. This
   shapes that payload; it does not compute a target of its own. */

export interface TargetLevel {
  id: string
  label: string
  price: number
  /** 0–100 gravitational intensity from the stack. */
  pull: number
  distancePct: number | null
  /** e.g. "Overhead Resistance Cap". */
  role: string
  /** Independent lenses that placed this level. More lenses, more agreement. */
  lensCount: number
  lenses: string[]
  side: 'above' | 'below' | 'at_spot'
  isPrimary: boolean
}

export interface TargetRead {
  /** bullish_pull | bearish_pull | neutral… verbatim from the stack. */
  direction: string
  /** Plain-language headline: which way the net pull points. */
  pullLabel: string
  regimeLabel: string
  regimeStrength: number | null
  primary: TargetLevel | null
  levels: TargetLevel[]
  /** Where two or more independent lenses land on the same price. */
  confluence: { price: number; distancePct: number | null; lenses: string[] } | null
  measurable: boolean
  reason: string | null
}

/** Structural shapes, so this module stays testable without the full payload. */
export interface LevelLike {
  id?: string
  type?: string
  label?: string
  price?: number
  pull_score?: number | null
  distance_pct?: number | null
  regime_role?: string
  lens_count?: number
  supporting_lenses?: string[]
  direction?: string
  is_primary_magnet?: boolean
}

export interface ClusterLike {
  level?: number
  distance_pct?: number | null
  lens_count?: number
  supporting_lenses?: string[]
}

export interface AttractorLike {
  spot?: number | null
  regime_label?: string
  regime_strength?: number | null
  dominant_direction?: string
  primary_magnet?: LevelLike | null
  levels?: LevelLike[]
  confluence_clusters?: ClusterLike[]
  quality?: { measurable?: boolean; reason?: string | null }
}

function toTarget(raw: LevelLike): TargetLevel | null {
  const price = Number(raw.price)
  if (!Number.isFinite(price) || price <= 0) return null
  const dist = raw.distance_pct
  return {
    id: String(raw.id ?? raw.type ?? raw.label ?? price),
    label: String(raw.label ?? 'Level'),
    price,
    pull: Number(raw.pull_score) || 0,
    distancePct: typeof dist === 'number' && Number.isFinite(dist) ? dist : null,
    role: String(raw.regime_role ?? ''),
    lensCount: Number(raw.lens_count) || 0,
    lenses: raw.supporting_lenses?.map(String) ?? [],
    side: raw.direction === 'above' || raw.direction === 'below' ? raw.direction : 'at_spot',
    isPrimary: raw.is_primary_magnet === true,
  }
}

const PULL_LABEL: Record<string, string> = {
  bullish_pull: 'Pulling up',
  bearish_pull: 'Pulling down',
  neutral: 'No net pull',
}

/**
 * Shape the attractor payload into a ranked set of destinations.
 *
 * Ordered by pull score, strongest first — that ordering is the answer to
 * "where does it make sense for price to go", and it is the stack's ranking,
 * not one imposed here. An unmeasurable payload yields no levels at all
 * rather than a target drawn from a chain that could not be read.
 */
export function readTargets(payload: AttractorLike | null | undefined): TargetRead | null {
  if (!payload) return null
  const measurable = payload.quality?.measurable !== false
  const levels = measurable
    ? (payload.levels ?? [])
        .map(toTarget)
        .filter((l): l is TargetLevel => l !== null)
        .sort((a, b) => b.pull - a.pull)
    : []

  const primary = payload.primary_magnet ? toTarget(payload.primary_magnet) : (levels[0] ?? null)

  const cluster = (payload.confluence_clusters ?? []).find(
    (c) => Number(c.lens_count) >= 2 && Number.isFinite(Number(c.level)),
  )
  const clusterDist = cluster?.distance_pct

  const direction = payload.dominant_direction ?? 'neutral'

  return {
    direction,
    pullLabel: PULL_LABEL[direction] ?? 'No net pull',
    regimeLabel: payload.regime_label ?? '',
    regimeStrength: typeof payload.regime_strength === 'number' ? payload.regime_strength : null,
    primary: measurable ? primary : null,
    levels,
    confluence: cluster
      ? {
          price: Number(cluster.level),
          distancePct:
            typeof clusterDist === 'number' && Number.isFinite(clusterDist) ? clusterDist : null,
          lenses: cluster.supporting_lenses?.map(String) ?? [],
        }
      : null,
    measurable,
    reason: payload.quality?.reason ?? null,
  }
}

/* ── one price scale ─────────────────────────────────────────────────────
   The levels list and the attractor list describe the same axis and kept
   printing the same number: AMD showed 400.00 four times across two cards
   (put wall, pin, vol trigger, volume POC). Merging by price collapses that
   into one rung carrying every role, which is also what makes a ladder
   drawable — two markers cannot share a pixel row and stay readable. */

export interface Rung {
  price: number
  /** Every role this price plays, deduped, strongest-pull first. */
  roles: string[]
  /** Best pull score at this price, or null when no attractor scored it. */
  pull: number | null
  /** Signed distance from spot in percent — positive means above spot. */
  distPct: number
  side: 'above' | 'below'
  /** Independent lenses that placed anything at this price. */
  lenses: string[]
}

/** Prices within this fraction of each other are the same rung. */
const RUNG_TOLERANCE = 0.0015

/**
 * Rungs further than this from spot are dropped.
 *
 * The attractor solver occasionally returns a degenerate root — AMD came back
 * with a "Zero-Gamma Flip" at 5.00 against a 465 spot, i.e. -98.9%. Plotting
 * it is worse than useless: it is not a level anyone watches, and on a shared
 * scale it drags every real rung into the noise. Dropped rungs are counted and
 * reported rather than silently discarded.
 */
export const LADDER_MAX_DIST_PCT = 40

export interface Ladder {
  rungs: Rung[]
  /** How many rungs were beyond LADDER_MAX_DIST_PCT, for an honest footnote. */
  dropped: number
}

/** Roles differ in case between lenses ("Put Wall" vs "Put wall"). */
function sameRole(a: string, b: string): boolean {
  return a.toLowerCase() === b.toLowerCase()
}

export function buildLadder(
  spot: number | null,
  levels: WatchLevel[],
  targets: TargetLevel[],
): Ladder {
  if (typeof spot !== 'number' || !(spot > 0)) return { rungs: [], dropped: 0 }

  const rungs: Rung[] = []

  const place = (price: number, role: string, pull: number | null, lenses: string[]) => {
    if (!Number.isFinite(price) || price <= 0) return
    const hit = rungs.find((r) => Math.abs(r.price - price) / spot < RUNG_TOLERANCE)
    if (hit) {
      if (!hit.roles.some((r) => sameRole(r, role))) hit.roles.push(role)
      for (const l of lenses) if (!hit.lenses.includes(l)) hit.lenses.push(l)
      if (pull !== null && (hit.pull === null || pull > hit.pull)) hit.pull = pull
      return
    }
    const distPct = ((price - spot) / spot) * 100
    rungs.push({
      price,
      roles: [role],
      pull,
      distPct,
      side: distPct >= 0 ? 'above' : 'below',
      lenses: [...lenses],
    })
  }

  /* Attractors first so a scored price keeps the attractor's own label at the
     head of its role list. */
  for (const t of targets) place(t.price, t.label, t.pull, t.lenses)
  for (const l of levels) place(l.price, l.label, null, [])

  const keep = rungs.filter((r) => Math.abs(r.distPct) <= LADDER_MAX_DIST_PCT)
  return {
    rungs: keep.sort((a, b) => b.price - a.price),
    dropped: rungs.length - keep.length,
  }
}

/**
 * Net pull mass either side of spot.
 *
 * The stack's `dominant_direction` is an aggregate, so it can read
 * "bearish_pull" while the single nearest magnet sits above spot — exactly
 * what AMD showed. Presenting those two facts adjacent and unlabelled reads
 * as a contradiction, so the card states them separately and this supplies
 * the mass split behind the aggregate.
 */
export function pullMass(targets: TargetLevel[]): { above: number; below: number } {
  let above = 0
  let below = 0
  for (const t of targets) {
    if (t.side === 'above') above += t.pull
    else if (t.side === 'below') below += t.pull
  }
  return { above, below }
}
