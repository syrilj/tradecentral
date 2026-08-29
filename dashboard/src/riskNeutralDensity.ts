/**
 * riskNeutralDensity — Breeden-Litzenberger recovery of the market-implied
 * probability distribution of price at expiry, from the quoted IV smile.
 *
 * The chain gives us discrete, noisy IV quotes at a handful of strikes.
 * Differentiating raw quotes twice (the textbook Breeden-Litzenberger
 * definition, q(K) = e^{rT} d²C/dK²) amplifies that noise into garbage — a
 * naive second difference on real quotes routinely produces wild negative
 * spikes. The fix used here is standard in practice:
 *
 *   1. Fit a smooth, SHAPE-PRESERVING curve through the observed IVs in
 *      log-moneyness (PCHIP / Fritsch-Carlson monotone cubic Hermite). PCHIP
 *      cannot overshoot between knots the way a natural cubic spline can, so
 *      it cannot manufacture butterfly-arbitrage wiggles that were never in
 *      the quotes.
 *   2. Reprice a dense, uniform grid of Black-Scholes call values from that
 *      smooth IV curve — this is what makes the second difference in step 3
 *      well-conditioned; it is a difference of a smooth function, not of
 *      noisy quotes.
 *   3. Take the discrete second derivative of price w.r.t. strike.
 *   4. Clip whatever numerical noise still pushes density negative, and
 *      renormalize so the result integrates to exactly 1.
 *
 * Pure function, no I/O. Recomputed on chain refetch (~75s), not every tick.
 */

import type { OptionsIntelligence } from '@/api'
import type { RiskNeutralResult, Smile, SmilePoint } from '@/regimeContracts'

const DEFAULT_GRID_POINTS = 400
const DEFAULT_WIDTH_SIGMA = 4
/** Below this, central second differences don't have enough interior points
 *  to mean anything; guard rather than return a grid that's mostly zeros. */
const MIN_GRID_POINTS = 5

function finite(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

// ---------------------------------------------------------------------------
// buildSmile
// ---------------------------------------------------------------------------

/**
 * Server-side default in `OptionsFilters` (daily_plays/options_intelligence.py).
 * Used only when the payload carries no usable rate.
 */
const FALLBACK_RISK_FREE_RATE = 0.045

/**
 * The rate the chain was actually priced with, off the payload's `filters`
 * block. `filters` is typed loosely on the wire, so the value is validated
 * against the same bounds the server enforces rather than trusted.
 */
function resolveRiskFreeRate(payload: OptionsIntelligence): number {
  const raw = (payload.filters as Record<string, unknown> | undefined)?.risk_free_rate
  const rate = typeof raw === 'number' ? raw : Number.NaN
  // Server bounds: -0.05 <= r <= 0.25. Anything outside is a malformed payload,
  // not a market condition, so fall back rather than propagate it into pricing.
  if (!Number.isFinite(rate) || rate < -0.05 || rate > 0.25) return FALLBACK_RISK_FREE_RATE
  return rate
}

/**
 * How many standard deviations of quoted strike the smile keeps. Wider than
 * the density grid's own `widthSigma` (4) on purpose: the grid edges must be
 * interpolated between real quotes, never flat-extrapolated off the end.
 */
const SMILE_WINDOW_SIGMA = 8
/** Floor and cap on the window, so a near-zero or absurd sigma still yields a
 *  usable, bounded strike set. */
const SMILE_WINDOW_MIN = 0.03
const SMILE_WINDOW_MAX = 0.4
/** PCHIP needs 4 nodes; below this the window is widened rather than obeyed. */
const MIN_SMILE_POINTS = 4

function medianIv(points: SmilePoint[]): number {
  const ivs = points.map((p) => p.iv).sort((a, b) => a - b)
  return ivs[Math.floor(ivs.length / 2)]
}

/**
 * Restrict the smile to the strikes that can actually inform this horizon.
 *
 * A chain quotes one strike ladder regardless of expiry, so a 1DTE contract is
 * quoted across the same 500-900 range as a LEAP. At sigma*sqrt(T) ~ 1.1%,
 * everything past a few percent is tens of sigmas out, priced in pennies, and
 * its implied vol is dominated by bid-ask width rather than any view. Those
 * points are not signal to be preserved — they are noise that makes the
 * repriced call curve non-convex and drives density negative.
 *
 * Widening on sparse chains is deliberate: too few nodes breaks the
 * interpolator outright, which is a worse failure than admitting a wide window.
 */
function restrictToHorizonWindow(
  points: SmilePoint[],
  atmIv: number,
  tYears: number,
): { windowed: SmilePoint[]; halfWidth: number } {
  const sigmaT = atmIv * Math.sqrt(tYears)
  if (!Number.isFinite(sigmaT) || sigmaT <= 0) {
    return { windowed: points, halfWidth: SMILE_WINDOW_MAX }
  }

  let halfWidth = Math.min(
    SMILE_WINDOW_MAX,
    Math.max(SMILE_WINDOW_MIN, SMILE_WINDOW_SIGMA * sigmaT),
  )
  for (;;) {
    const windowed = points.filter((p) => Math.abs(p.logMoneyness) <= halfWidth)
    if (windowed.length >= MIN_SMILE_POINTS) return { windowed, halfWidth }
    if (halfWidth >= SMILE_WINDOW_MAX) return { windowed: points, halfWidth: SMILE_WINDOW_MAX }
    halfWidth = Math.min(SMILE_WINDOW_MAX, halfWidth * 1.5)
  }
}

export function buildSmile(payload: OptionsIntelligence | null): Smile | null {
  if (!payload) return null

  const spot = finite(payload.summary?.spot)
  if (spot == null || spot <= 0) return null

  const rows = payload.stacked_signals?.iv_surface ?? []
  const points: SmilePoint[] = []
  for (const row of rows) {
    const strike = finite(row?.strike)
    if (strike == null || strike <= 0) continue
    // Each strike carries an OI-weighted call IV and put IV independently.
    // Prefer the out-of-the-money side: OTM quotes are the actively traded,
    // tightly-spread half of the chain, while the ITM mirror at the same
    // strike is frequently stale or purely synthetic (derived from put-call
    // parity rather than its own quote flow). Fall back to whichever side
    // actually printed a usable value.
    const otmIv = strike <= spot ? row.put_iv : row.call_iv
    const itmIv = strike <= spot ? row.call_iv : row.put_iv
    const iv = finite(otmIv) ?? finite(itmIv)
    if (iv == null || iv <= 0) continue
    points.push({ strike, iv, logMoneyness: Math.log(strike / spot) })
  }

  points.sort((a, b) => a.logMoneyness - b.logMoneyness)
  // Defensive dedup by log-moneyness: iv_surface is already one row per
  // strike so this shouldn't fire, but PCHIP requires strictly increasing x
  // and a repeat would otherwise produce a zero-width segment downstream.
  const deduped: SmilePoint[] = []
  for (const p of points) {
    if (deduped.length > 0 && deduped[deduped.length - 1].logMoneyness === p.logMoneyness) {
      deduped[deduped.length - 1] = p
    } else {
      deduped.push(p)
    }
  }

  if (deduped.length < 4) return null

  const horizonDays = finite(payload.probability?.horizon_days)
  const tYears = horizonDays != null && horizonDays > 0 ? horizonDays / 365 : 30 / 365

  const atmIv = finite(payload.probability?.atm_iv) ?? medianIv(deduped)
  const { windowed, halfWidth } = restrictToHorizonWindow(deduped, atmIv, tYears)

  return {
    points: windowed,
    windowHalfWidth: halfWidth,
    strikesDropped: deduped.length - windowed.length,
    spot,
    tYears,
    // The rate the server actually priced this chain with. It rides the wire
    // in `filters` (`asdict(OptionsFilters)`, default 0.045), so using 0 here
    // would silently disagree with the Greeks in the same payload.
    //
    // It matters more than the small number suggests. The exp(rT) prefactor in
    // Breeden-Litzenberger cancels under renormalization, but the Black-Scholes
    // forward S*exp(rT) does not: at r=0 the whole density sits ~0.37% low over
    // a 30-day horizon. That bias lands squarely on `modalTarget` — the "where
    // is it trying to go" figure — and it is one-directional, so it never
    // averages out.
    riskFreeRate: resolveRiskFreeRate(payload),
    expiry: payload.chain_context?.selected_expiry ?? '',
    observedStrikes: windowed.length,
  }
}

// ---------------------------------------------------------------------------
// PCHIP (Fritsch-Carlson monotone cubic Hermite interpolation)
// ---------------------------------------------------------------------------

interface PchipSpline {
  xs: number[]
  ys: number[]
  /** Tangent (dy/dx) at each knot. */
  ms: number[]
}

/**
 * One-sided three-point derivative estimate at a curve endpoint, clipped to
 * preserve monotonicity (Fritsch-Carlson / the same edge rule MATLAB's
 * pchipend uses). Without the clip, an endpoint tangent can overshoot past
 * the adjacent knot — exactly the wing-arbitrage behavior PCHIP exists to
 * prevent, so the clip is not optional polish.
 */
function endpointTangent(h0: number, h1: number, d0: number, d1: number): number {
  let m = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
  if (Math.sign(m) !== Math.sign(d0)) {
    m = 0
  } else if (Math.sign(d0) !== Math.sign(d1) && Math.abs(m) > 3 * Math.abs(d0)) {
    m = 3 * d0
  }
  return m
}

function buildPchip(xs: number[], ys: number[]): PchipSpline {
  const n = xs.length
  if (n === 1) return { xs, ys, ms: [0] }

  const h: number[] = []
  const delta: number[] = []
  for (let i = 0; i < n - 1; i++) {
    h.push(xs[i + 1] - xs[i])
    delta.push((ys[i + 1] - ys[i]) / h[i])
  }

  if (n === 2) {
    return { xs, ys, ms: [delta[0], delta[0]] }
  }

  const ms = new Array<number>(n).fill(0)
  for (let i = 1; i < n - 1; i++) {
    const d0 = delta[i - 1]
    const d1 = delta[i]
    // Opposite-signed (or flat) adjacent secants: force the tangent to 0.
    // This is the step that makes PCHIP shape-preserving — a spline that
    // insisted on a nonzero slope through a local extremum in the quotes
    // would overshoot past it and could dip the reconstructed IV, and
    // eventually the density, negative for no reason in the data.
    if (d0 === 0 || d1 === 0 || Math.sign(d0) !== Math.sign(d1)) {
      ms[i] = 0
    } else {
      const w1 = 2 * h[i] + h[i - 1]
      const w2 = h[i] + 2 * h[i - 1]
      ms[i] = (w1 + w2) / (w1 / d0 + w2 / d1)
    }
  }
  ms[0] = endpointTangent(h[0], h[1], delta[0], delta[1])
  ms[n - 1] = endpointTangent(h[n - 2], h[n - 3], delta[n - 2], delta[n - 3])

  return { xs, ys, ms }
}

/** Evaluate the Hermite cubic; flat-extrapolates by holding the edge value
 *  constant outside the observed range rather than projecting the curve's
 *  endpoint tangent into the unobserved wings. */
function evalPchip(spline: PchipSpline, x: number): number {
  const { xs, ys, ms } = spline
  const n = xs.length
  if (n === 1) return ys[0]
  if (x <= xs[0]) return ys[0]
  if (x >= xs[n - 1]) return ys[n - 1]

  let lo = 0
  let hi = n - 2
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (xs[mid] <= x) lo = mid
    else hi = mid - 1
  }
  const i = lo
  const h = xs[i + 1] - xs[i]
  const t = (x - xs[i]) / h
  const t2 = t * t
  const t3 = t2 * t
  const h00 = 2 * t3 - 3 * t2 + 1
  const h10 = t3 - 2 * t2 + t
  const h01 = -2 * t3 + 3 * t2
  const h11 = t3 - t2
  return h00 * ys[i] + h10 * h * ms[i] + h01 * ys[i + 1] + h11 * h * ms[i + 1]
}

// ---------------------------------------------------------------------------
// Black-Scholes call pricing (inline — no deps)
// ---------------------------------------------------------------------------

/** Standard normal CDF via Abramowitz-Stegun 7.1.26, |ε| ≤ 1.5e-7. */
function normCdf(x: number): number {
  const z = Math.abs(x) / Math.SQRT2
  const p = 0.3275911
  const a1 = 0.254829592
  const a2 = -0.284496736
  const a3 = 1.421413741
  const a4 = -1.453152027
  const a5 = 1.061405429
  const t = 1 / (1 + p * z)
  const poly = ((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t
  const erf = 1 - poly * Math.exp(-z * z)
  return 0.5 * (1 + (x < 0 ? -erf : erf))
}

function bsCallPrice(S: number, K: number, T: number, sigma: number, r: number): number {
  if (!(S > 0) || !(K > 0) || !(T > 0) || !(sigma > 0)) {
    // Degenerate inputs (zero vol/time) fall back to discounted intrinsic
    // value instead of a divide-by-zero inside d1.
    return Math.max(S - K * Math.exp(-r * T), 0)
  }
  const sqrtT = Math.sqrt(T)
  const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrtT)
  const d2 = d1 - sigma * sqrtT
  return S * normCdf(d1) - K * Math.exp(-r * T) * normCdf(d2)
}

function trapezoid(xs: number[], ys: number[]): number {
  let sum = 0
  for (let i = 0; i < xs.length - 1; i++) {
    sum += ((ys[i] + ys[i + 1]) / 2) * (xs[i + 1] - xs[i])
  }
  return sum
}

// ---------------------------------------------------------------------------
// riskNeutralDensity
// ---------------------------------------------------------------------------

export function riskNeutralDensity(
  smile: Smile | null,
  opts?: { gridPoints?: number; widthSigma?: number },
): RiskNeutralResult {
  const fail = (reason: string): RiskNeutralResult => ({
    grid: null,
    clippedMass: 0,
    unavailableReason: reason,
  })

  if (!smile) return fail('no smile available')
  if (!Number.isFinite(smile.spot) || smile.spot <= 0)
    return fail('spot is not a positive finite number')
  if (!Number.isFinite(smile.tYears) || smile.tYears <= 0)
    return fail('time to expiry must be positive')

  // Defensive re-sort: buildSmile always hands back ascending log-moneyness,
  // but this function is also called directly (gammaTilt re-prices a scaled
  // copy of a Smile), so the sorted-strictly-increasing-x precondition PCHIP
  // needs is enforced here rather than assumed from the caller.
  const sortedPoints = [...smile.points].sort((a, b) => a.logMoneyness - b.logMoneyness)
  const points: SmilePoint[] = []
  for (const p of sortedPoints) {
    if (!Number.isFinite(p.logMoneyness) || !Number.isFinite(p.iv) || p.iv <= 0) continue
    if (points.length > 0 && points[points.length - 1].logMoneyness === p.logMoneyness) {
      points[points.length - 1] = p
    } else {
      points.push(p)
    }
  }
  if (points.length < 4) return fail('need at least 4 strikes to build a smile')

  const gridPoints = Math.max(MIN_GRID_POINTS, Math.floor(opts?.gridPoints ?? DEFAULT_GRID_POINTS))
  const widthSigma = opts?.widthSigma ?? DEFAULT_WIDTH_SIGMA
  if (!Number.isFinite(widthSigma) || widthSigma <= 0)
    return fail('widthSigma must be a positive finite number')

  const xs = points.map((p) => p.logMoneyness)
  const ys = points.map((p) => p.iv)
  const spline = buildPchip(xs, ys)

  const atmIv = evalPchip(spline, 0)
  if (!Number.isFinite(atmIv) || atmIv <= 0) return fail('ATM implied vol is not usable')

  const halfWidth = widthSigma * atmIv * Math.sqrt(smile.tYears)
  if (!Number.isFinite(halfWidth) || halfWidth <= 0) return fail('degenerate grid width')

  const kMin = smile.spot * Math.exp(-halfWidth)
  const kMax = smile.spot * Math.exp(halfWidth)
  if (!(kMax > kMin) || !Number.isFinite(kMin) || !Number.isFinite(kMax))
    return fail('degenerate strike grid')

  const dK = (kMax - kMin) / (gridPoints - 1)
  const strikes = new Array<number>(gridPoints)
  for (let i = 0; i < gridPoints; i++) strikes[i] = kMin + i * dK

  const prices = new Array<number>(gridPoints)
  for (let i = 0; i < gridPoints; i++) {
    const k = strikes[i]
    const iv = evalPchip(spline, Math.log(k / smile.spot))
    prices[i] = bsCallPrice(smile.spot, k, smile.tYears, iv, smile.riskFreeRate)
  }

  const discount = Math.exp(smile.riskFreeRate * smile.tYears)
  const rawDensity = new Array<number>(gridPoints).fill(0)
  for (let i = 1; i < gridPoints - 1; i++) {
    const d2C = prices[i + 1] - 2 * prices[i] + prices[i - 1]
    rawDensity[i] = (discount * d2C) / (dK * dK)
  }
  // rawDensity[0] and rawDensity[gridPoints - 1] stay 0: a central second
  // difference needs a neighbor on both sides, and with the default
  // widthSigma=4 the true density that far into the tail is already
  // negligible, so leaving the edge undefined-as-zero costs nothing material.

  const clipped = rawDensity.map((v) => Math.max(v, 0))
  const negativeMass = trapezoid(
    strikes,
    rawDensity.map((v) => Math.max(-v, 0)),
  )
  const clippedTotal = trapezoid(strikes, clipped)

  if (!Number.isFinite(clippedTotal) || clippedTotal <= 0) {
    return fail('density collapsed to zero after clipping negatives')
  }

  const density = clipped.map((v) => v / clippedTotal)
  // Fraction of total (surviving + removed) mass that clipping threw away —
  // bounded in [0, 1) by construction, unlike dividing by clippedTotal alone
  // which could blow past 1 when almost everything was noise.
  const totalMassPreRenormalize = clippedTotal + negativeMass
  const clippedMass = totalMassPreRenormalize > 0 ? negativeMass / totalMassPreRenormalize : 0

  return {
    grid: {
      strikes,
      density,
      spot: smile.spot,
      tYears: smile.tYears,
      kind: 'risk-neutral',
    },
    clippedMass: Number.isFinite(clippedMass) ? clippedMass : 0,
    unavailableReason: null,
  }
}
