/**
 * gammaRegime — live dealer gamma read from a fixed GEX profile + a ticking
 * live spot price.
 *
 * The profile (`gex_price_profile`) is a chain snapshot: it only refreshes on
 * chain refetch (~75s). Spot moves every tick in between. This module's whole
 * job is to answer "given the shape we already measured, what does the
 * *current* price imply" — by interpolating net dealer gamma at live spot and
 * reading its local slope, without ever re-deriving the shape itself.
 *
 * Pure function, no I/O: same inputs always produce the same RegimeState.
 */

import type { OptionsIntelligence } from '@/api'
import type { GammaRegime, RegimeState } from '@/regimeContracts'

/** Half-width of the neutral band around zero gamma, as a fraction of spot. */
const DEFAULT_FLIP_BAND_PCT = 0.0025

type ProfilePoint = { spot: number; net_gex_m: number }

function finite(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/**
 * Sorted, strictly-increasing-by-spot profile with only finite points.
 * A duplicate spot tick would make the interpolation/slope segment below
 * degenerate (zero width); keep the later entry so the profile stays usable
 * instead of throwing it away entirely.
 */
function sanitizeProfile(raw: OptionsIntelligence['gex_price_profile']): ProfilePoint[] {
  const finitePoints = (raw ?? []).filter(
    (p): p is ProfilePoint => Number.isFinite(p?.spot) && Number.isFinite(p?.net_gex_m),
  )
  finitePoints.sort((a, b) => a.spot - b.spot)
  const out: ProfilePoint[] = []
  for (const p of finitePoints) {
    if (out.length > 0 && out[out.length - 1].spot === p.spot) {
      out[out.length - 1] = p
    } else {
      out.push(p)
    }
  }
  return out
}

/**
 * Index i such that [profile[i], profile[i+1]] is the segment to use for a
 * given target: the bracketing pair when target is inside the range, or the
 * boundary segment when target falls outside it (so callers clamp instead of
 * extrapolating). Requires profile.length >= 2; returns null otherwise.
 */
function locateSegment(profile: ProfilePoint[], target: number): number | null {
  if (profile.length < 2) return null
  const last = profile.length - 1
  if (target <= profile[0].spot) return 0
  if (target >= profile[last].spot) return last - 1
  let lo = 0
  let hi = last - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (profile[mid].spot <= target) lo = mid
    else hi = mid - 1
  }
  return lo
}

/**
 * Linear interpolation of net_gex_m at `spot`. A single-point profile has
 * nothing to interpolate against, so its one reading is returned as-is
 * (better than refusing a read the pipeline did provide). Spot outside the
 * measured range clamps to the nearest edge value rather than extrapolating
 * a shape we never actually observed past the last measured strike.
 */
function interpolateNetGamma(profile: ProfilePoint[], spot: number): number | null {
  if (profile.length === 0) return null
  if (profile.length === 1) return profile[0].net_gex_m
  const seg = locateSegment(profile, spot)
  if (seg == null) return null
  const a = profile[seg]
  const b = profile[seg + 1]
  const dx = b.spot - a.spot
  if (dx === 0) return a.net_gex_m // guard: duplicate/zero spacing
  const clampedSpot = Math.min(Math.max(spot, profile[0].spot), profile[profile.length - 1].spot)
  const t = (clampedSpot - a.spot) / dx
  return a.net_gex_m + t * (b.net_gex_m - a.net_gex_m)
}

/**
 * Central finite difference of net_gex_m at `spot`, using the two grid
 * points that bracket it (the same segment interpolateNetGamma reads from).
 * "Central" here means spot sits inside the bracket rather than the
 * difference being taken one-sided from a single anchor point — the spec
 * calls for a two-point difference, not a wider three-point stencil.
 * Spot outside the range reuses the boundary segment's slope as the best
 * available local estimate; a duplicate/zero-width segment guards to null
 * rather than dividing by zero.
 */
function bracketSlope(profile: ProfilePoint[], spot: number): number | null {
  if (profile.length < 2) return null
  const seg = locateSegment(profile, spot)
  if (seg == null) return null
  const a = profile[seg]
  const b = profile[seg + 1]
  const dx = b.spot - a.spot
  if (dx === 0) return null
  return (b.net_gex_m - a.net_gex_m) / dx
}

/**
 * Largest |net_gex_m| across the whole profile — a symbol-relative scale
 * reference for consumers (gammaTilt's normalization) that would otherwise
 * have to pick one fixed $M constant for every instrument. An index's net
 * gamma runs orders of magnitude above a single name's, so a fixed divisor
 * either saturates instantly on the index or never engages on the name;
 * scaling against the symbol's own measured range is scale-free instead.
 * Requires >= 2 points (a lone reading doesn't establish a range) and a
 * strictly positive max — a zero-magnitude "scale" is not a scale, and a
 * null here tells the consumer to fall back to its own constant rather than
 * silently dividing by zero.
 */
function maxAbsGamma(profile: ProfilePoint[]): number | null {
  if (profile.length < 2) return null
  let max = 0
  for (const p of profile) {
    max = Math.max(max, Math.abs(p.net_gex_m))
  }
  return Number.isFinite(max) && max > 0 ? max : null
}

/** Same idea as maxAbsGamma, but over the adjacent-pair slopes rather than
 *  the levels — the largest |Δnet_gex_m / Δspot| across the profile. */
function maxAbsSlope(profile: ProfilePoint[]): number | null {
  if (profile.length < 2) return null
  let max = 0
  for (let i = 0; i < profile.length - 1; i++) {
    const a = profile[i]
    const b = profile[i + 1]
    const dx = b.spot - a.spot
    if (dx === 0) continue // guard: duplicate/zero spacing pair, skip it
    max = Math.max(max, Math.abs((b.net_gex_m - a.net_gex_m) / dx))
  }
  return Number.isFinite(max) && max > 0 ? max : null
}

export function buildRegimeState(
  payload: OptionsIntelligence | null,
  liveSpot: number | null,
  opts?: { flipBandPct?: number },
): RegimeState {
  const flipBandPct = finite(opts?.flipBandPct) ?? DEFAULT_FLIP_BAND_PCT

  const blank = (measurable: boolean): RegimeState => ({
    netGammaM: null,
    gammaSlope: null,
    distanceToFlip: null,
    regime: 'unmeasurable',
    flipBandPct,
    spot: null,
    zeroGamma: null,
    pinStrike: null,
    callWall: null,
    putWall: null,
    measurable,
    gammaScaleM: null,
    slopeScaleM: null,
  })

  if (!payload) return blank(false)

  // Literal `=== false` check: a payload that omits the flag entirely is
  // treated as measurable rather than going dark on a field the pipeline
  // simply hasn't started sending yet. Only an explicit false — open
  // interest confirmed absent — withholds the read.
  const measurable = payload.quality?.gex_measurable !== false

  const spot = finite(liveSpot) ?? finite(payload.summary?.spot)
  const profile = sanitizeProfile(payload.gex_price_profile)

  // Split into two checks (rather than one combined `!measurable ||
  // netGammaM == null` condition) so TypeScript can narrow `spot` to
  // `number` for the rest of the function — it has no way to know
  // netGammaM's nullness implies spot's from a ternary two lines away.
  if (!measurable || spot == null) {
    return blank(measurable)
  }

  const netGammaM = interpolateNetGamma(profile, spot)
  if (netGammaM == null) {
    // Every numeric field goes null together, not just the one that was
    // literally unmeasurable. A partially-populated regime read — say spot
    // and the walls rendering fine while netGamma sits blank — reads as
    // "mostly fine" to an operator glancing at a tile; it must read as "no
    // read", so nothing numeric survives once the regime call itself can't
    // be trusted.
    return blank(measurable)
  }

  const gammaSlope = bracketSlope(profile, spot)
  const zeroGamma = finite(payload.summary?.zero_gamma) ?? finite(payload.summary?.gamma_flip)
  const distanceToFlip = zeroGamma != null && spot !== 0 ? (spot - zeroGamma) / spot : null

  let regime: GammaRegime
  if (distanceToFlip != null && Math.abs(distanceToFlip) <= flipBandPct) {
    regime = 'flip'
  } else if (netGammaM < 0) {
    regime = 'short'
  } else if (netGammaM > 0) {
    regime = 'long'
  } else {
    // netGammaM is exactly 0 with no zero-gamma level to check it against —
    // there is no basis to assert a side, so treat it as the flip boundary.
    regime = 'flip'
  }

  return {
    netGammaM,
    gammaSlope,
    distanceToFlip,
    regime,
    flipBandPct,
    spot,
    zeroGamma,
    pinStrike: finite(payload.summary?.pin_strike),
    callWall: finite(payload.summary?.call_wall),
    putWall: finite(payload.summary?.put_wall),
    measurable,
    gammaScaleM: maxAbsGamma(profile),
    slopeScaleM: maxAbsSlope(profile),
  }
}
