/**
 * Interactive model geometry for the public landing page.
 *
 * Pure arithmetic — no DOM, no I/O. Every figure on the page is computed from
 * a named quantitative model (Black-Scholes, geometric Brownian motion,
 * lognormal risk-neutral density), never hand-picked decorative shapes.
 * Parameters are structural anatomy only; live values appear after sign-in.
 *
 * Companion to landing-math.ts: that module serves the static hero diagram,
 * this one serves the interactive workbenches (live Monte Carlo, Greeks lab).
 */

import { linearScale } from './scale'
import { smoothPath, areaPath, type Pt } from './path'

/* ── Deterministic PRNG (reproducible anatomy, same family as landing-math) ── */

/** Mulberry32 — small, fast, deterministic. */
export function mulberry32(seed: number): () => number {
  let a = seed | 0
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Box-Muller transform: two uniforms → one standard normal. */
function boxMuller(rand: () => number): number {
  let u = 0
  let v = 0
  while (u === 0) u = rand()
  while (v === 0) v = rand()
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}

/* ── Geometric Brownian Motion ────────────────────────────────────────────── */

export interface PathBundle {
  /** One polyline per simulated path; coordinates already mapped to the box. */
  lines: { pts: Pt[] }[]
  terminals: number[]
}

/**
 * Simulate `nPaths` GBM paths and map them into an SVG box.
 * Exact log-Euler discretisation keeps every path strictly positive.
 */
export function simulatePaths(
  S0: number,
  mu: number,
  sigma: number,
  T: number,
  steps: number,
  nPaths: number,
  seed: number,
  box: { x: number; y: number; w: number; h: number },
): PathBundle {
  void mu // reserved for future drift-display variants; paths use log-space directly
  const dt = T / steps
  const drift = (mu - 0.5 * sigma * sigma) * dt
  const diffusion = sigma * Math.sqrt(dt)
  const rand = mulberry32(seed)

  // First pass: raw log-paths, tracking the envelope for scaling.
  const logPaths: number[][] = []
  let lo = Infinity
  let hi = -Infinity
  for (let p = 0; p < nPaths; p++) {
    const row: number[] = [0]
    for (let i = 1; i <= steps; i++) {
      row.push(row[i - 1] + drift + diffusion * boxMuller(rand))
    }
    for (const v of row) {
      if (v < lo) lo = v
      if (v > hi) hi = v
    }
    logPaths.push(row)
  }

  const pad = (hi - lo) * 0.04 || 1e-6
  const yScale = linearScale([lo - pad, hi + pad], [box.y + box.h, box.y])
  const xScale = linearScale([0, steps], [box.x, box.x + box.w])

  const lines = logPaths.map((row) => ({
    pts: row.map((v, i) => ({ x: xScale(i), y: yScale(v) })),
  }))
  const terminals = logPaths.map((row) => S0 * Math.exp(row[row.length - 1]))
  return { lines, terminals }
}

/* ── Terminal distribution: empirical histogram + theoretical density ──────── */

export interface DistributionFigure {
  histogramPath: string
  bars: { d: string; countFrac: number }[]
  densityLine: string
  densityArea: string
  medianX: number
  p1LowX: number
  p1HighX: number
}

/**
 * Bin MC terminal prices and overlay the closed-form lognormal density.
 * Both are drawn in the SAME box so model-vs-simulation agreement is visible.
 */
export function terminalDistribution(
  S0: number,
  mu: number,
  sigma: number,
  T: number,
  r: number,
  q: number,
  terminals: number[],
  nBins: number,
  box: { x: number; y: number; w: number; h: number },
): DistributionFigure {
  void mu // the density is risk-neutral (r − q); physical drift reserved for future variants
  const sigT = sigma * Math.sqrt(T)
  const muLog = Math.log(S0) + (r - q - 0.5 * sigma * sigma) * T

  // Histogram domain spans both samples AND ±3σ of the theory curve.
  const tMin = terminals.length ? Math.min(...terminals) : S0 * 0.6
  const tMax = terminals.length ? Math.max(...terminals) : S0 * 1.6
  const domainLo = Math.min(tMin, S0 * Math.exp(-3 * sigT))
  const domainHi = Math.max(tMax, S0 * Math.exp(3 * sigT))
  const xScale = linearScale([domainLo, domainHi], [box.x, box.x + box.w])

  const binW = (domainHi - domainLo) / nBins || 1
  const counts = new Array<number>(nBins).fill(0)
  for (const t of terminals) {
    const idx = Math.min(Math.max(Math.floor((t - domainLo) / binW), 0), nBins - 1)
    counts[idx]++
  }
  const maxCount = Math.max(...counts, 1)

  // Theory density sampled over the same domain.
  const nPts = 120
  const pdf: number[] = []
  let maxPdf = 0
  for (let i = 0; i < nPts; i++) {
    const x = domainLo + ((domainHi - domainLo) * i) / (nPts - 1)
    const z = (Math.log(x) - muLog) / sigT
    const p = (1 / (x * sigT * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * z * z)
    pdf.push(p)
    if (p > maxPdf) maxPdf = p
  }

  const baseY = box.y + box.h
  const histTop = box.y + box.h * 0.62 // histogram occupies lower band
  const densTop = box.y // density uses full height

  // Bars, normalised to the histogram band.
  const bars = counts.map((c, i) => {
    const frac = c / maxCount
    const cx = xScale(domainLo + binW * (i + 0.5))
    const bw = Math.max(xScale(domainLo + binW) - xScale(domainLo) - 1.5, 1)
    const h = frac * (baseY - histTop)
    return { d: `M${cx - bw / 2},${baseY}v${-h}h${bw}v${h}z`, countFrac: frac }
  })

  // Density curve scaled to full height.
  const densPts: Pt[] = pdf.map((p, i) => {
    const x = domainLo + ((domainHi - domainLo) * i) / (nPts - 1)
    return { x: xScale(x), y: densTop + (1 - p / maxPdf) * (baseY - densTop) }
  })
  const median = Math.exp(muLog)
  return {
    histogramPath: bars.map((b) => b.d).join(''),
    bars,
    densityLine: smoothPath(densPts),
    densityArea: areaPath(densPts, baseY),
    medianX: xScale(median),
    p1LowX: xScale(median / Math.exp(sigT)),
    p1HighX: xScale(median * Math.exp(sigT)),
  }
}

/* ── Black-Scholes Greeks across a strike grid ─────────────────────────────── */

export type GreekKind = 'value' | 'delta' | 'gamma' | 'vega' | 'theta'

export interface GreekCurve {
  call: Pt[]
  put: Pt[]
  /** Strike axis ticks in price space. */
  strikes: number[]
  /**
   * Raw value range the y coordinates were mapped from. The workbench needs
   * it to place the zero line and to draw the intrinsic payoff boundary on
   * the same scale as the curves.
   */
  domain: { lo: number; hi: number }
}

/** φ(z) standard normal pdf. */
export function normPdf(z: number): number {
  return Math.exp(-0.5 * z * z) / Math.sqrt(2 * Math.PI)
}

/** Abramowitz & Stegun 7.1.26 error function (|ε| ≤ 1.5e-7). */
export function erf(x: number): number {
  const s = x < 0 ? -1 : 1
  const ax = Math.abs(x)
  const p = 0.3275911
  const a1 = 0.254829592
  const a2 = -0.284496736
  const a3 = 1.421413741
  const a4 = -1.453152027
  const a5 = 1.061405429
  const t = 1 / (1 + p * ax)
  const poly = ((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t
  return s * (1 - poly * Math.exp(-ax * ax))
}

/**
 * Standard normal CDF: Φ(z) = ½·[1 + erf(z/√2)].
 * Verified against tabulated values: Φ(0)=0.5, Φ(1.96)≈0.975, Φ(10)≈1.
 */
export function normCdf(z: number): number {
  return 0.5 * (1 + erf(z / Math.SQRT2))
}

export interface BSInputs {
  S: number
  K: number
  T: number
  sigma: number
  r: number
  q: number
}

/** d₁ = (ln(S/K) + (r − q + σ²/2)·T) / σ√T. */
export function bsD1(p: BSInputs): number {
  const s = p.sigma * Math.sqrt(p.T)
  if (s <= 0) return 0
  return (Math.log(p.S / p.K) + (p.r - p.q + 0.5 * p.sigma * p.sigma) * p.T) / s
}

/** Black-Scholes call price. */
export function bsCall(p: BSInputs): number {
  return (
    p.S * Math.exp(-p.q * p.T) * normCdf(bsD1(p)) -
    p.K * Math.exp(-p.r * p.T) * normCdf(bsD1(p) - p.sigma * Math.sqrt(p.T))
  )
}

/** Black-Scholes put price. */
export function bsPutPrice(p: BSInputs): number {
  return (
    p.K * Math.exp(-p.r * p.T) * normCdf(-(bsD1(p) - p.sigma * Math.sqrt(p.T))) -
    p.S * Math.exp(-p.q * p.T) * normCdf(-bsD1(p))
  )
}

/** BS gamma: Γ = φ(d₁)/(S·σ·√T·e^{−qT}). */
export function bsGamma(p: BSInputs): number {
  const s = p.sigma * Math.sqrt(p.T)
  if (s <= 0) return 0
  return normPdf(bsD1(p)) / (p.S * s * Math.exp(-p.q * p.T))
}

/** BS vega per 1 vol point: ν = S·φ(d₁)·√T·e^{−qT}/100. */
export function bsVega(p: BSInputs): number {
  return (p.S * normPdf(bsD1(p)) * Math.sqrt(p.T) * Math.exp(-p.q * p.T)) / 100
}

/**
 * Per-day theta (calendar-day): Θ_day/365. Call theta by default.
 *
 * Hull signs — the carry terms are NOT symmetric between legs:
 *   Θ_call = −S·φ(d₁)·σ·e^{−qT}/(2√T) − rK·e^{−rT}·Φ(d₂) + qS·e^{−qT}·Φ(d₁)
 *   Θ_put  = −S·φ(d₁)·σ·e^{−qT}/(2√T) + rK·e^{−rT}·Φ(−d₂) − qS·e^{−qT}·Φ(−d₁)
 * (Earlier this had +rK on the call and −rK on the put, which handed
 * deep-ITM calls positive theta and swapped the ATM pair; the identity
 * Θ_put − Θ_call = rK·e^{−rT} at q=0 pins the correction in the tests.)
 */
export function bsThetaDay(p: BSInputs, kind: 'call' | 'put'): number {
  const s = p.sigma * Math.sqrt(p.T)
  if (s <= 0) return 0
  const d1 = bsD1(p)
  const nd1 = normPdf(d1)
  const rTT = p.r * p.K * Math.exp(-p.r * p.T)
  const qTS = p.q * p.S * Math.exp(-p.q * p.T)
  const common = -(p.S * nd1 * p.sigma * Math.exp(-p.q * p.T)) / (2 * Math.sqrt(p.T))
  if (kind === 'call') {
    return (common - rTT * normCdf(d1 - s) + qTS * normCdf(d1)) / 365
  }
  return (common + rTT * normCdf(s - d1) - qTS * normCdf(-d1)) / 365
}

/**
 * Evaluate any supported Greek for call & put legs across a strike grid,
 * normalised to [-1, 1] over the pair's shared value range for plotting.
 *
 * The mapping is domain-based (min/max of BOTH legs -> band edges), not
 * symmetric maxAbs: value/gamma/vega are non-negative and theta is
 * non-positive, so a symmetric scale pinned every curve to one half of the
 * plot and left the other half permanently empty. One shared domain keeps
 * call vs put honestly comparable; the rendered pair always spans the band.
 */
export function greekCurves(
  greek: GreekKind,
  S: number,
  T: number,
  sigma: number,
  r: number,
  q: number,
  kLow: number,
  kHigh: number,
  n: number,
): GreekCurve {
  const evalK = (K: number, kind: 'call' | 'put'): number => {
    switch (greek) {
      case 'value':
        return kind === 'call'
          ? bsCall({ S, K, T, sigma, r, q })
          : bsPutPrice({ S, K, T, sigma, r, q })
      case 'delta': {
        const d = bsD1({ S, K, T, sigma, r, q })
        const disc = Math.exp(-q * T)
        return kind === 'call' ? disc * normCdf(d) : -disc * normCdf(-d)
      }
      case 'gamma':
        return bsGamma({ S, K, T, sigma, r, q })
      case 'vega':
        return bsVega({ S, K, T, sigma, r, q })
      case 'theta':
        return bsThetaDay({ S, K, T, sigma, r, q }, kind)
    }
  }

  const callRaw: number[] = []
  const putRaw: number[] = []
  const strikes: number[] = []
  for (let i = 0; i < n; i++) {
    const K = kLow + ((kHigh - kLow) * i) / (n - 1)
    strikes.push(K)
    callRaw.push(evalK(K, 'call'))
    putRaw.push(evalK(K, 'put'))
  }

  // Shared call+put domain: the two legs share one scale so their relative
  // size stays truthful. For value curves the floor includes 0 so the
  // intrinsic payoff boundary (which touches 0) stays inside the band.
  let lo = Infinity
  let hi = -Infinity
  for (const v of [...callRaw, ...putRaw]) {
    if (v < lo) lo = v
    if (v > hi) hi = v
  }
  if (greek === 'value') lo = Math.min(lo, 0)
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) {
    lo = 0
    hi = 1
  }
  const span = hi - lo || 1 // flat curve guard: degenerates to a midline

  // x is the STRIKE mapped onto [0, 100] — the scale's domain is the strike
  // range, so it must be fed a strike, not the loop's 0..1 fraction. Feeding
  // the fraction pushed every point to x ≈ -75 and drew the whole curve off
  // the left of the viewBox, which is why the lab plot rendered empty.
  const kScale = linearScale([strikes[0]!, strikes[strikes.length - 1]!], [0, 100])
  const toPoints = (raw: number[]): Pt[] =>
    raw.map((v, i) => ({
      x: kScale(strikes[i]!),
      y: (2 * (v - lo)) / span - 1, // [lo, hi] -> [-1, 1]
    }))

  return { call: toPoints(callRaw), put: toPoints(putRaw), strikes, domain: { lo, hi } }
}

/* ── Multi-leg option structures (options workbench plate) ──────────────────
   The lab's structure figure sums real Black-Scholes legs — long/short signs
   attached — so the payoff curve, today's value curve, and the Greeks strip
   all come from one engine instead of a hand-drawn kinked line. */

export interface OptionLeg {
  kind: 'call' | 'put'
  strike: number
  /** +1 long, -1 short. */
  dir: 1 | -1
}

/** Market environment shared by every leg of a structure (each leg has its own K). */
export type SpotEnv = Omit<BSInputs, 'K'>

/** Signed BS value of a single leg. */
export function legValue(leg: OptionLeg, env: SpotEnv): number {
  const p: BSInputs = { ...env, K: leg.strike }
  return leg.dir * (leg.kind === 'call' ? bsCall(p) : bsPutPrice(p))
}

/** Intrinsic value of a single leg at expiry, signed. */
export function legExpiryValue(leg: OptionLeg, S: number): number {
  const intrinsic = leg.kind === 'call' ? Math.max(S - leg.strike, 0) : Math.max(leg.strike - S, 0)
  return leg.dir * intrinsic
}

/**
 * Net Greeks of the whole structure at the current spot, legs summed with
 * their long/short signs. Delta is φ-based here (same closed form the lab's
 * strike curves use), theta is the per-calendar-day carry from bsThetaDay.
 */
export function structureGreeks(
  legs: OptionLeg[],
  env: SpotEnv,
): { value: number; delta: number; gamma: number; vega: number; thetaDay: number } {
  let value = 0,
    delta = 0,
    gamma = 0,
    vega = 0,
    thetaDay = 0
  for (const leg of legs) {
    const p: BSInputs = { ...env, K: leg.strike }
    const disc = Math.exp(-env.q * env.T)
    const d1 = bsD1(p)
    const d = leg.kind === 'call' ? disc * normCdf(d1) : -disc * normCdf(-d1)
    value += leg.dir * (leg.kind === 'call' ? bsCall(p) : bsPutPrice(p))
    delta += leg.dir * d
    gamma += leg.dir * bsGamma(p)
    vega += leg.dir * bsVega(p)
    thetaDay += leg.dir * bsThetaDay(p, leg.kind)
  }
  return { value, delta, gamma, vega, thetaDay }
}

export interface PayoffColumns {
  /** Spot ladder the curves were sampled on. */
  spots: number[]
  /** Today's structure value across the ladder (BS, signed). */
  today: number[]
  /** Expiry P&L across the ladder (intrinsic − entry premium). */
  expiry: number[]
  /** Net premium of the structure at the reference spot (positive = debit). */
  premium: number
}

/** Sample today's value curve and the expiry P&L curve across a spot ladder. */
export function payoffColumns(
  legs: OptionLeg[],
  env: SpotEnv,
  sLow: number,
  sHigh: number,
  n: number,
): PayoffColumns {
  const premium = structureGreeks(legs, env).value
  const spots: number[] = []
  const today: number[] = []
  const expiry: number[] = []
  for (let i = 0; i < n; i++) {
    const S = sLow + ((sHigh - sLow) * i) / (n - 1)
    spots.push(S)
    today.push(structureGreeks(legs, { ...env, S }).value - premium)
    const intrinsic = legs.reduce((acc, leg) => acc + legExpiryValue(leg, S), 0)
    expiry.push(intrinsic - premium)
  }
  return { spots, today, expiry, premium }
}

/* ── Walk-forward IC decay model (governance plate) ─────────────────────────
   A parametric stand-in for the measured diagnostics: the desk's real signal
   ledger lives behind sign-in, so the public page shows the *shape* the
   measurement takes. Every cell is derived from (ic1d, sd, periods) through
   the stated formulas — no decorative literals.

     meanIc(h)  = ic1d · shape(h)            pinned decay curvature
     se(h)      = sd / sqrt(periods(h))      daily-IC noise, periods shrink with h
     nwT(h)     = meanIc(h) / se(h)          Newey-West-style t
     icIr(h)    = nwT(h) · sqrt(252 / h)     annualised IC information ratio
     pctPos(h)  = Φ(meanIc(h) / sd)          fraction of positive days
*/

export interface IcHorizonRow {
  days: number
  meanIc: number
  nwT: number
  icIr: number
  pctPositive: number
  periods: number
}

export interface IcDecayModel {
  horizons: number[]
  rows: IcHorizonRow[]
  /** Mean IC at 1D. */
  ic1d: number
  /** Horizon where meanIc peaks. */
  peakDays: number
  /** First horizon where meanIc falls below half its peak (interpolated). */
  halfLifeDays: number
  /** Share of horizons whose mean IC keeps the 1D sign. */
  signPersistence: number
}

/* ── Structural GEX profile (desk telemetry plate) ──────────────────────────
   Gamma exposure concentrated at named walls: calls above the flip (net
   long-gamma, dampening), puts below it (short-gamma, amplifying). The desk's
   live profile is measured from chain OI after sign-in; this is the
   parametric anatomy of the same figure. */

export interface StructuralGex {
  /** {K, gex} with gex normalised to ±1 (call side positive). */
  points: { K: number; gex: number }[]
  /** Sum of gex before normalisation — the sign drives the regime label. */
  net: number
  netMax: number
}

function gauss(x: number, mu: number, sd: number): number {
  return Math.exp(-0.5 * ((x - mu) / sd) ** 2)
}

export function structuralGexProfile(opts: {
  S: number
  flipK: number
  callWallK: number
  putWallK: number
  nStrikes: number
  /** Half-width of the strike range as a fraction of spot. */
  range: number
}): StructuralGex {
  const { S, flipK, callWallK, putWallK, nStrikes, range } = opts
  const kLow = S * (1 - range)
  const kHigh = S * (1 + range)
  const wallSd = S * 0.045
  const ambientSd = S * 0.11
  const points: { K: number; gex: number }[] = []
  let rawNet = 0
  let maxAbs = 0
  for (let i = 0; i < nStrikes; i++) {
    const K = kLow + ((kHigh - kLow) * i) / (nStrikes - 1)
    const calls = gauss(K, callWallK, wallSd)
    const puts = gauss(K, putWallK, wallSd) * 0.8
    const ambient = gauss(K, S, ambientSd) * 0.3 * (K >= flipK ? 1 : -1)
    const gex = calls - puts + ambient
    points.push({ K, gex })
    rawNet += gex
    if (Math.abs(gex) > maxAbs) maxAbs = Math.abs(gex)
  }
  const scale = maxAbs || 1
  return {
    points: points.map((p) => ({ K: p.K, gex: p.gex / scale })),
    net: rawNet,
    netMax: maxAbs * nStrikes,
  }
}

export function icDecayModel(opts: {
  ic1d: number
  icSdDaily: number
  periods1d: number
  shape: readonly number[]
}): IcDecayModel {
  const horizons = [1, 2, 3, 5, 10, 20]
  const rows: IcHorizonRow[] = horizons.map((h, i) => {
    const meanIc = opts.ic1d * (opts.shape[i] ?? 0)
    const periods = Math.max(1, opts.periods1d - h)
    const se = opts.icSdDaily / Math.sqrt(periods)
    const nwT = se > 0 ? meanIc / se : 0
    const icIr = nwT * Math.sqrt(252 / h)
    const pctPositive = normCdf(meanIc / opts.icSdDaily)
    return { days: h, meanIc, nwT, icIr, pctPositive, periods }
  })
  const peak = rows.reduce((best, r) => (Math.abs(r.meanIc) > Math.abs(best.meanIc) ? r : best))
  const target = Math.abs(peak.meanIc) / 2
  let halfLifeDays = rows[rows.length - 1]!.days
  for (let i = 1; i < rows.length; i++) {
    const prev = rows[i - 1]!,
      cur = rows[i]!
    if (Math.abs(prev.meanIc) >= target && Math.abs(cur.meanIc) < target) {
      const frac =
        (Math.abs(prev.meanIc) - target) / (Math.abs(prev.meanIc) - Math.abs(cur.meanIc) || 1e-9) ||
        0
      halfLifeDays = prev.days + frac * (cur.days - prev.days)
      break
    }
  }
  const sign = Math.sign(opts.ic1d) || 1
  const signPersistence = rows.filter((r) => r.meanIc * sign > 0).length / Math.max(rows.length, 1)
  return { horizons, rows, ic1d: opts.ic1d, peakDays: peak.days, halfLifeDays, signPersistence }
}
