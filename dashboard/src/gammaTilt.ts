/**
 * gammaTilt — deforms the risk-neutral density with the live gamma regime.
 *
 * The risk-neutral density (riskNeutralDensity.ts) is derived purely from
 * option prices: it is driftless and arbitrage-free by construction, and it
 * knows nothing about dealer hedging flows. This module is the ONE place in
 * the stack that asserts a model on top of that market-implied distribution
 * — "dealers who are short gamma amplify realized vol and chase the tape;
 * dealers who are long gamma suppress it and pin price". That claim is not
 * observable in option prices themselves, so every constant here is a named,
 * exported default and every effect is built to be monotone and auditable.
 * The untilted density must always be recoverable: identity tilt is a true
 * no-op (see applyTilt), so a reader can always compare "what the market
 * prices in" against "what the regime model adds on top".
 */

import type {
  DensityGrid,
  RegimeProbabilities,
  RegimeState,
  RiskNeutralResult,
  Smile,
  SmilePoint,
  TiltParams,
} from '@/regimeContracts'
import type { CharmSummary } from '@/api'
import { riskNeutralDensity } from '@/riskNeutralDensity'

// ---------------------------------------------------------------------------
// Tunable constants — surfaced in TiltParams.constants so the UI can render
// them next to the chart. These are the two knobs that turn the regime read
// into density deformation strength; changing them changes every tilt this
// module produces, which is exactly why they are named and not buried.
// ---------------------------------------------------------------------------

/**
 * Drift strength. Scales how far the Esscher tilt leans the density along
 * gammaSlope (theta = lambda * tanh(gammaSlope / SLOPE_NORMALIZATION_M) in
 * the short-gamma case, halved for the long/flip restoring case). 0.35 was
 * chosen so a saturated slope produces a visible but modest lean — the
 * [-3, 3] clamp is a hard backstop this constant does not reach in normal
 * operation; see the module report for why that headroom is flagged.
 */
export const LAMBDA_DRIFT = 0.35

/**
 * Vol-scaling strength. Multiplies the tanh-saturated, normalized net gamma
 * before it is added to 1.0 to produce volScale. 0.25 combined with the
 * [0.6, 1.8] hard clamp means an extreme reading saturates the tanh long
 * before the clamp would even bind for kappa — the clamp is the true limit,
 * kappa just sets how quickly "ordinary" GEX prints move volScale off 1.0.
 */
export const KAPPA_VOL = 0.25

/**
 * FALLBACK normalization scale for |netGammaM| ($M per 1% move), used only
 * when `state.gammaScaleM` is unavailable (null or <= 0).
 *
 * This surface's primary universe is SPY/QQQ/IWM and the 11 sector ETFs,
 * whose index-scale net gamma runs orders of magnitude above a single name's
 * — a fixed $M divisor pinned `tanh` to ~1.0 for nearly every index reading,
 * collapsing volScale to its bound and destroying discrimination exactly
 * where the tab is pointed most of the time. That was a real correctness
 * defect (see git history / module report), not just a calibration nitpick.
 *
 * The fix is scale-free: deriveTilt normalizes against `state.gammaScaleM`,
 * the largest |net_gex_m| observed across the symbol's own GEX profile
 * (the same idea `GammaExposureMap.vue` uses to scale its bars), so the
 * *same relative* gamma posture — e.g. 80% of the symbol's own max — produces
 * the same volScale whether the symbol is a single name or an index. This
 * constant only fires when that profile-derived scale isn't available, and
 * is kept as a defensive fallback: even a wrong fallback is still tanh- and
 * clamp-bounded, so nothing downstream can blow up from its absence.
 */
export const GAMMA_NORMALIZATION_M = 500

/**
 * FALLBACK normalization scale for |gammaSlope|, used only when
 * `state.slopeScaleM` is unavailable (null or <= 0). Same index-vs-single-name
 * scale problem and the same scale-free fix as GAMMA_NORMALIZATION_M above:
 * deriveTilt prefers `state.slopeScaleM` (the largest |slope| observed across
 * the symbol's own profile) and only falls back to this fixed constant when
 * that isn't available.
 */
export const SLOPE_NORMALIZATION_M = 200

const VOL_SCALE_MIN = 0.6
const VOL_SCALE_MAX = 1.8
const THETA_MIN = -3
const THETA_MAX = 3
const PIN_PULL_MIN = 0
const PIN_PULL_MAX = 1

/** Identity tilt: the exact no-deformation TiltParams, reused everywhere the regime cannot be asserted. */
function identityTilt(): TiltParams {
  return {
    volScale: 1,
    theta: 0,
    pinPull: 0,
    constants: { lambda: LAMBDA_DRIFT, kappa: KAPPA_VOL },
  }
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min
  return Math.min(max, Math.max(min, value))
}

/** Guards every constant/derived numeric against non-finite propagation (Infinity/NaN inputs must never leak into TiltParams). */
function finiteOr(value: number, fallback: number): number {
  return Number.isFinite(value) ? value : fallback
}

/**
 * Picks the normalization divisor for the tanh saturation: the symbol's own
 * profile-derived scale when it's usable, otherwise the fixed fallback
 * constant. This is the scale-free fix — normalizing "how strong is this
 * gamma reading" against the range this specific symbol's own profile has
 * shown, rather than a fixed $M figure that only fits one order of magnitude.
 */
function resolveScale(profileScale: number | null, fallback: number): number {
  return profileScale != null && Number.isFinite(profileScale) && profileScale > 0
    ? profileScale
    : fallback
}

// ---------------------------------------------------------------------------
// deriveTilt
// ---------------------------------------------------------------------------

/**
 * Turn a regime read + charm summary into deformation parameters. Every
 * output is clamped to the documented range so a bad upstream print (a
 * garbage GEX profile, a stale charm feed) cannot produce an absurd or
 * NaN-poisoned tilt — see the "extreme inputs" test for the contract this
 * function must hold.
 */
export function deriveTilt(
  state: RegimeState,
  charm: CharmSummary | null | undefined,
  sessionFractionRemaining: number,
): TiltParams {
  // No measurable open interest => no regime can be asserted. Returning the
  // identity tilt here (rather than e.g. a "neutral-ish" small deformation)
  // is a deliberate fail-closed choice: fabricating a small drift from
  // absent OI would still be fabrication.
  if (state.regime === 'unmeasurable') {
    return identityTilt()
  }

  // --- volScale -------------------------------------------------------
  // Short gamma (netGammaM < 0): dealers sell into drops and buy into
  // rallies to stay hedged, which *feeds* realized vol above what the
  // smile implies => volScale > 1. Long gamma (netGammaM > 0): dealers
  // buy dips and sell rips, damping realized vol => volScale < 1.
  // tanh saturates the normalized magnitude so an extreme GEX print
  // cannot blow past the multiplier the clamp would allow anyway; the
  // clamp itself remains the hard backstop per the spec.
  const netGammaM = finiteOr(state.netGammaM ?? 0, 0)
  // Scale-free: normalize against this symbol's own profile range
  // (state.gammaScaleM) when available, so an index reading and a
  // single-name reading at the same *relative* posture saturate the same
  // way. Falls back to the fixed constant only when the profile scale is
  // absent — see GAMMA_NORMALIZATION_M's doc comment for why that matters.
  const gammaScale = resolveScale(state.gammaScaleM, GAMMA_NORMALIZATION_M)
  const normalizedGamma = netGammaM / gammaScale
  // tanh sign tracks netGammaM's sign: negative (short) => saturatedGamma < 0.
  const saturatedGamma = Math.tanh(normalizedGamma)
  // Sign flip: negative netGamma (short) must produce volScale > 1, so the
  // vol-scaling term is the negative of the saturated normalized gamma.
  // Bounded to [1 - kappa, 1 + kappa] by tanh alone (kappa=0.25 => [0.75,
  // 1.25]) — the [0.6, 1.8] clamp is a hard backstop that this formula does
  // not reach under normal operation; see report for why that is flagged.
  const volScaleRaw = 1 - KAPPA_VOL * saturatedGamma
  const volScale = clamp(finiteOr(volScaleRaw, 1), VOL_SCALE_MIN, VOL_SCALE_MAX)

  // --- theta (Esscher coefficient) ------------------------------------
  // Short gamma: the tape "extends" along whatever direction gammaSlope is
  // already pulling it (dealer hedging is pro-cyclical), so theta takes the
  // *sign and rough magnitude* of gammaSlope directly. Long gamma: dealer
  // hedging is mean-reverting toward the pin, so we lean the opposite way —
  // back toward pinStrike — rather than extending along the slope. Without
  // a pinStrike there is nothing to lean back toward, so long-gamma theta
  // is left at the slope-based value (already small/inward by construction
  // of gammaSlope near a flip) scaled down rather than fabricated.
  const gammaSlope = finiteOr(state.gammaSlope ?? 0, 0)
  // Same scale-free normalization as volScale above, against this symbol's
  // own observed slope range.
  const slopeScale = resolveScale(state.slopeScaleM, SLOPE_NORMALIZATION_M)
  const normalizedSlope = gammaSlope / slopeScale
  const saturatedSlope = Math.tanh(normalizedSlope)
  let thetaRaw: number
  if (state.regime === 'short') {
    // Extend along the slope at full drift strength: bounded to
    // (-lambda, lambda) by tanh, i.e. (-0.35, 0.35) at the default.
    thetaRaw = LAMBDA_DRIFT * saturatedSlope
  } else {
    // 'long' or 'flip': lean back toward pinStrike — invert the slope's
    // sign and halve the strength, since a restoring force is weaker and
    // qualitatively different from a trending one.
    thetaRaw = -0.5 * LAMBDA_DRIFT * saturatedSlope
  }
  // As with volScale, the [-3, 3] clamp is a hard backstop this formula
  // does not reach under normal operation given the default lambda.
  const theta = clamp(finiteOr(thetaRaw, 0), THETA_MIN, THETA_MAX)

  // --- pinPull ----------------------------------------------------------
  // charm = dDelta/dTime: dealers must re-hedge purely from time passing,
  // even with spot unchanged, and that flow concentrates near the pin as
  // expiry approaches. Weighting by (1 - sessionFractionRemaining) is the
  // direct encoding of "charm bites harder into the close": at the open
  // (sessionFractionRemaining ~= 1) the weight is ~0, at the close
  // (sessionFractionRemaining ~= 0) the weight is ~1.
  let pinPull = 0
  if (charm) {
    const netCharmFlow = finiteOr(charm.net_charm_flow, 0)
    const timeWeight = clamp(finiteOr(1 - sessionFractionRemaining, 0), 0, 1)
    // abs_charm_flow, when present and positive, gives a natural per-symbol
    // scale to normalize against so pinPull is a genuine [0,1] "how much of
    // today's charm flow is this" rather than an arbitrary magic number.
    const scale =
      charm.abs_charm_flow && charm.abs_charm_flow > 0
        ? charm.abs_charm_flow
        : Math.abs(netCharmFlow) || 1
    const normalizedCharm = Math.abs(netCharmFlow) / scale
    pinPull = clamp(finiteOr(normalizedCharm * timeWeight, 0), PIN_PULL_MIN, PIN_PULL_MAX)
  }

  return {
    volScale,
    theta,
    pinPull,
    constants: { lambda: LAMBDA_DRIFT, kappa: KAPPA_VOL },
  }
}

// ---------------------------------------------------------------------------
// applyTilt
// ---------------------------------------------------------------------------

/**
 * Apply a TiltParams deformation to a Smile, producing a tilted density.
 *
 * Order of operations (both required to keep the result a valid normalized
 * density):
 *   1. Scale every IV by volScale, then re-run riskNeutralDensity() on the
 *      scaled smile. Repricing through Breeden-Litzenberger on a wider/
 *      narrower smile keeps non-negativity and no-arbitrage by construction
 *      — this is strictly safer than trying to reweight an already-built
 *      density to "look wider", which has no guarantee of staying a valid
 *      density.
 *   2. Esscher-tilt the resulting grid: w(K) = exp(theta * ln(K/spot)),
 *      optionally multiplied by a Gaussian pin term when pinStrike is
 *      non-null, then renormalize by trapezoidal integration so the result
 *      integrates to 1 again.
 */
export function applyTilt(
  smile: Smile | null,
  tilt: TiltParams,
  state: RegimeState,
): RiskNeutralResult {
  if (!smile) {
    return { grid: null, clippedMass: 0, unavailableReason: 'no smile available' }
  }

  // Step 1: scale IVs and reprice.
  const scaledPoints: SmilePoint[] = smile.points.map((p) => ({
    ...p,
    iv: p.iv * tilt.volScale,
  }))
  const scaledSmile: Smile = { ...smile, points: scaledPoints }
  const priced = riskNeutralDensity(scaledSmile)

  if (!priced.grid) {
    // Repricing failed (e.g. too few observed strikes) — propagate the
    // reason rather than inventing a density.
    return priced
  }

  // Step 2: Esscher tilt + pin term, then renormalize.
  const { strikes, density, spot, tYears } = priced.grid
  const pinStrike = state.pinStrike

  const weighted = strikes.map((k, i) => {
    const logMoneyness = Math.log(k / spot)
    let w = Math.exp(tilt.theta * logMoneyness)
    if (pinStrike != null && tilt.pinPull > 0) {
      const pinTerm = ((k - pinStrike) / spot) ** 2
      w *= Math.exp(-tilt.pinPull * pinTerm)
    }
    const raw = density[i] * w
    return Number.isFinite(raw) && raw >= 0 ? raw : 0
  })

  const mass = trapezoidalIntegral(strikes, weighted)
  const normalized =
    mass > 0
      ? weighted.map((v) => v / mass)
      : // Degenerate weighting (e.g. theta pushed everything to ~0) — fall
        // back to the unweighted density rather than dividing by zero.
        density

  const tiltedGrid: DensityGrid = {
    strikes,
    density: normalized,
    spot,
    tYears,
    kind: 'tilted',
  }

  return {
    grid: tiltedGrid,
    clippedMass: priced.clippedMass,
    unavailableReason: null,
  }
}

// ---------------------------------------------------------------------------
// regimeProbabilities
// ---------------------------------------------------------------------------

function trapezoidalIntegral(xs: number[], ys: number[]): number {
  let sum = 0
  for (let i = 1; i < xs.length; i++) {
    const dx = xs[i] - xs[i - 1]
    sum += (dx * (ys[i] + ys[i - 1])) / 2
  }
  return sum
}

/** Trapezoidal integral of density over [xs[0], x], for building a CDF. */
function trapezoidalCdf(xs: number[], ys: number[]): number[] {
  const cdf = new Array(xs.length).fill(0)
  for (let i = 1; i < xs.length; i++) {
    const dx = xs[i] - xs[i - 1]
    cdf[i] = cdf[i - 1] + (dx * (ys[i] + ys[i - 1])) / 2
  }
  return cdf
}

function nullProbabilities(): RegimeProbabilities {
  return {
    probAboveCallWall: null,
    probBelowPutWall: null,
    probBetweenWalls: null,
    modalTarget: null,
    expectedMove: null,
    band68: null,
  }
}

/**
 * Integrate the tilted grid into the summary numbers the UI renders.
 * Everything here is a trapezoidal integral or a walk over the CDF — no
 * new modelling assumptions are introduced in this function, it only reads
 * off the density that deriveTilt/applyTilt already built.
 */
export function regimeProbabilities(
  grid: DensityGrid | null,
  state: RegimeState,
): RegimeProbabilities {
  if (!grid || state.regime === 'unmeasurable') {
    return nullProbabilities()
  }

  const { strikes, density, spot } = grid
  if (strikes.length < 2) {
    return nullProbabilities()
  }

  const totalMass = trapezoidalIntegral(strikes, density)
  if (!(totalMass > 0)) {
    return nullProbabilities()
  }

  // modalTarget: argmax density.
  let modalIdx = 0
  for (let i = 1; i < density.length; i++) {
    if (density[i] > density[modalIdx]) modalIdx = i
  }
  const modalTarget = strikes[modalIdx]

  // expectedMove: mass-weighted mean absolute distance from spot — a single
  // number for "how far is price expected to travel", not signed drift.
  let expectedMoveAcc = 0
  for (let i = 1; i < strikes.length; i++) {
    const dx = strikes[i] - strikes[i - 1]
    const midDensity = (density[i] + density[i - 1]) / 2
    const midDistance = (Math.abs(strikes[i] - spot) + Math.abs(strikes[i - 1] - spot)) / 2
    expectedMoveAcc += dx * midDensity * midDistance
  }
  const expectedMove = expectedMoveAcc / totalMass

  // probAboveCallWall / probBelowPutWall / probBetweenWalls via direct
  // trapezoidal integration over the relevant sub-ranges of the grid.
  const callWall = state.callWall
  const putWall = state.putWall
  const probAboveCallWall =
    callWall != null ? integrateAbove(strikes, density, callWall) / totalMass : null
  const probBelowPutWall =
    putWall != null ? integrateBelow(strikes, density, putWall) / totalMass : null
  const probBetweenWalls =
    callWall != null && putWall != null
      ? clamp(1 - (probAboveCallWall ?? 0) - (probBelowPutWall ?? 0), 0, 1)
      : null

  // band68: central 68% interval, walked outward from the median on the CDF
  // (not from the mode) — this is the standard "1-sigma equivalent"
  // definition and is well-defined even for a skewed/tilted density.
  const cdf = trapezoidalCdf(strikes, density)
  const normalizedCdf = cdf.map((v) => v / totalMass)
  const medianIdx = findCrossing(normalizedCdf, 0.5)
  const lowIdx = findCrossing(normalizedCdf, medianIdx.frac - 0.34 < 0 ? 0 : medianIdx.frac - 0.34)
  const highIdx = findCrossing(normalizedCdf, Math.min(1, medianIdx.frac + 0.34))
  const band68 = {
    low: interpolateStrike(strikes, normalizedCdf, lowIdx.frac),
    high: interpolateStrike(strikes, normalizedCdf, highIdx.frac),
  }

  return {
    probAboveCallWall,
    probBelowPutWall,
    probBetweenWalls,
    modalTarget,
    expectedMove,
    band68,
  }
}

function integrateAbove(xs: number[], ys: number[], threshold: number): number {
  // Trapezoidal integral of ys over the sub-range [threshold, xs[last]],
  // linearly interpolating ys at the threshold crossing so the wall does
  // not need to sit exactly on a grid point.
  return integrateRange(xs, ys, threshold, xs[xs.length - 1])
}

function integrateBelow(xs: number[], ys: number[], threshold: number): number {
  return integrateRange(xs, ys, xs[0], threshold)
}

function interpolateY(xs: number[], ys: number[], x: number): number {
  if (x <= xs[0]) return ys[0]
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1]
  for (let i = 1; i < xs.length; i++) {
    if (xs[i] >= x) {
      const t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
      return ys[i - 1] + t * (ys[i] - ys[i - 1])
    }
  }
  return ys[ys.length - 1]
}

function integrateRange(xs: number[], ys: number[], from: number, to: number): number {
  if (to <= from) return 0
  const lo = clamp(from, xs[0], xs[xs.length - 1])
  const hi = clamp(to, xs[0], xs[xs.length - 1])
  // Build the point list: lo, every grid point strictly between, hi.
  const points: Array<{ x: number; y: number }> = [{ x: lo, y: interpolateY(xs, ys, lo) }]
  for (let i = 0; i < xs.length; i++) {
    if (xs[i] > lo && xs[i] < hi) points.push({ x: xs[i], y: ys[i] })
  }
  points.push({ x: hi, y: interpolateY(xs, ys, hi) })
  let sum = 0
  for (let i = 1; i < points.length; i++) {
    const dx = points[i].x - points[i - 1].x
    sum += (dx * (points[i].y + points[i - 1].y)) / 2
  }
  return sum
}

function findCrossing(cdf: number[], target: number): { index: number; frac: number } {
  const t = clamp(target, 0, 1)
  for (let i = 0; i < cdf.length; i++) {
    if (cdf[i] >= t) {
      return { index: i, frac: t }
    }
  }
  return { index: cdf.length - 1, frac: t }
}

function interpolateStrike(strikes: number[], cdf: number[], targetFrac: number): number {
  const t = clamp(targetFrac, 0, 1)
  if (t <= cdf[0]) return strikes[0]
  if (t >= cdf[cdf.length - 1]) return strikes[strikes.length - 1]
  for (let i = 1; i < cdf.length; i++) {
    if (cdf[i] >= t) {
      const span = cdf[i] - cdf[i - 1]
      const frac = span > 0 ? (t - cdf[i - 1]) / span : 0
      return strikes[i - 1] + frac * (strikes[i] - strikes[i - 1])
    }
  }
  return strikes[strikes.length - 1]
}
