/**
 * Financial math for the landing page hero visual.
 *
 * Every shape on the page is computed from a named quantitative model:
 *   · Black-Scholes implied volatility surface (strike × maturity grid)
 *   · Black-Scholes gamma → GEX-by-strike profile
 *   · Geometric Brownian Motion price path
 *   · Monte Carlo terminal distribution (multiple GBM paths → histogram)
 *   · Lognormal risk-neutral density → implied range cone
 *
 * This is pure arithmetic — no DOM, no I/O. Parameters are structural
 * anatomy only; live values appear exclusively after operator sign-in.
 */

import { linearScale } from './scale'
import { linePath, smoothPath, areaPath, bandPath, type Pt } from './path'

/* ── Normal CDF / PDF ──────────────────────────────────────────────────────── */

/** Standard normal PDF: φ(x) = exp(-x²/2) / √(2π). */
export function normPdf(x: number): number {
  return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI)
}

/** Standard normal CDF via A&S 7.1.26 erf: Φ(z) = ½·[1 + erf(z/√2)], |ε| ≤ 1.5e-7. */
export function normCdf(x: number): number {
  const z = Math.abs(x) / Math.SQRT2
  const p = 0.3275911
  const a1 = 0.254829592,
    a2 = -0.284496736,
    a3 = 1.421413741,
    a4 = -1.453152027,
    a5 = 1.061405429
  const t = 1 / (1 + p * z)
  const poly = ((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t
  const erfVal = (1 - poly * Math.exp(-z * z)) * (x < 0 ? -1 : 1)
  return 0.5 * (1 + erfVal)
}

/* ── Black-Scholes ────────────────────────────────────────────────────────── */

export interface BSParams {
  S: number
  K: number
  T: number
  sigma: number
  r: number
  q: number
}

/** d₁ = (ln(S/K) + (r - q + σ²/2)T) / (σ√T). */
export function d1({ S, K, T, sigma, r, q }: BSParams): number {
  const sigT = sigma * Math.sqrt(T)
  if (sigT === 0) return 0
  return (Math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / sigT
}

/** d₂ = d₁ - σ√T. */
export function d2(p: BSParams): number {
  return d1(p) - p.sigma * Math.sqrt(p.T)
}

/** Black-Scholes call price. */
export function bsCall(p: BSParams): number {
  const { S, K, T, r, q, sigma } = p
  const d1v = d1(p),
    d2v = d1v - sigma * Math.sqrt(T)
  return S * Math.exp(-q * T) * normCdf(d1v) - K * Math.exp(-r * T) * normCdf(d2v)
}

/** Black-Scholes put price. */
export function bsPut(p: BSParams): number {
  const { S, K, T, r, q, sigma } = p
  const d1v = d1(p),
    d2v = d1v - sigma * Math.sqrt(T)
  return K * Math.exp(-r * T) * normCdf(-d2v) - S * Math.exp(-q * T) * normCdf(-d1v)
}

/** BS gamma: Γ = φ(d₁) / (S σ √T e^{-qT}). Peaks ATM, falls off in wings. */
export function bsGamma(p: BSParams): number {
  const { S, T, sigma, q } = p
  const sigT = sigma * Math.sqrt(T)
  if (sigT === 0) return 0
  return normPdf(d1(p)) / (S * sigT * Math.exp(-q * T))
}

/** BS vega: ν = S φ(d₁) √T e^{-qT}. Same for calls and puts. */
export function bsVega(p: BSParams): number {
  const { S, T, q } = p
  return S * normPdf(d1(p)) * Math.sqrt(T) * Math.exp(-q * T)
}

/** BS delta for a call: Δ_c = e^{-qT} Φ(d₁). */
export function bsCallDelta(p: BSParams): number {
  return Math.exp(-p.q * p.T) * normCdf(d1(p))
}

/** BS delta for a put: Δ_p = -e^{-qT} Φ(-d₁). */
export function bsPutDelta(p: BSParams): number {
  return -Math.exp(-p.q * p.T) * normCdf(-d1(p))
}

/* ── Implied volatility surface ──────────────────────────────────────────────
   Models the volatility smile + term structure across a strike × maturity
   grid. The smile is a quadratic in moneyness (ln(K/F)), and the term
   structure decays with √T. This produces the 3D mesh seen in the reference
   image — a real parametric vol surface, not a decorative shape. */

export interface VolSurfacePoint {
  K: number
  T: number
  moneyness: number
  iv: number
}

/**
 * Parametric implied volatility surface:
 *
 *   σ(K,T) = σ_ATM · [1 + skew·m + curve·m²] · [1 + term·(1-√T/Tmax)]
 *
 * where m = ln(K/F) is log-moneyness, F = S·e^{(r-q)T} is the forward.
 *
 * The skew (linear in m) produces the equity put skew (higher IV for
 * downside strikes). The curve (quadratic in m) produces the smile wings.
 * The term structure decays with √T (shorter-dated options have steeper
 * smiles in normalized terms).
 */
export function volSurface(
  S: number,
  r: number,
  q: number,
  strikes: number[],
  maturities: number[],
  sigmaAtm: number,
  skew: number,
  curve: number,
  termDecay: number,
): VolSurfacePoint[] {
  const Tmax = Math.max(...maturities, 1e-6)
  const points: VolSurfacePoint[] = []
  for (const T of maturities) {
    const F = S * Math.exp((r - q) * T)
    const termFactor = 1 + termDecay * (1 - Math.sqrt(T / Tmax))
    for (const K of strikes) {
      const m = Math.log(K / F)
      const smileFactor = 1 + skew * m + curve * m * m
      const iv = sigmaAtm * smileFactor * termFactor
      points.push({ K, T, moneyness: m, iv: Math.max(iv, 0.01) })
    }
  }
  return points
}

/* ── GBM price path simulation ─────────────────────────────────────────────── */

export interface GBMParams {
  S0: number
  mu: number
  sigma: number
  T: number
  steps: number
  rand: () => number
}

/** Geometric Brownian Motion via exact log-Euler (always positive, terminal is lognormal). */
export function gbmPath({ S0, mu, sigma, T, steps, rand }: GBMParams): number[] {
  const dt = T / steps
  const drift = (mu - 0.5 * sigma * sigma) * dt
  const diffusion = sigma * Math.sqrt(dt)
  const path: number[] = [S0]
  for (let i = 1; i <= steps; i++) {
    const z = boxMuller(rand)
    path.push(path[i - 1] * Math.exp(drift + diffusion * z))
  }
  return path
}

/** Box-Muller: two uniforms → one standard normal. */
function boxMuller(rand: () => number): number {
  let u = 0,
    v = 0
  while (u === 0) u = rand()
  while (v === 0) v = rand()
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}

/** Mulberry32 PRNG — deterministic, reproducible anatomy. */
export function mulberry32(seed: number): () => number {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/* ── Monte Carlo terminal distribution ───────────────────────────────────────
   Runs N GBM paths and bins the terminal prices into a histogram. This is
   the *empirical* distribution — the landing page can overlay it with the
   *theoretical* lognormal density to show model vs simulation agreement. */

export interface McResult {
  paths: number[][]
  terminals: number[]
  histogram: { x: number; count: number }[]
  meanTerminal: number
  stdTerminal: number
}

export function monteCarlo(
  S0: number,
  mu: number,
  sigma: number,
  T: number,
  nPaths: number,
  steps: number,
  seed: number,
  nBins: number,
): McResult {
  const rand = mulberry32(seed)
  const paths: number[][] = []
  const terminals: number[] = []

  for (let p = 0; p < nPaths; p++) {
    const path = gbmPath({ S0, mu, sigma, T, steps, rand })
    paths.push(path)
    terminals.push(path[path.length - 1])
  }

  const meanTerminal = terminals.reduce((a, b) => a + b, 0) / terminals.length
  const variance = terminals.reduce((a, b) => a + (b - meanTerminal) ** 2, 0) / terminals.length
  const stdTerminal = Math.sqrt(variance)

  const minT = Math.min(...terminals)
  const maxT = Math.max(...terminals)
  const binWidth = (maxT - minT) / nBins || 1
  const histogram: { x: number; count: number }[] = Array.from({ length: nBins }, (_, i) => ({
    x: minT + binWidth * (i + 0.5),
    count: 0,
  }))
  for (const t of terminals) {
    const binIdx = Math.min(Math.floor((t - minT) / binWidth), nBins - 1)
    histogram[binIdx].count++
  }
  const maxCount = Math.max(...histogram.map((h) => h.count), 1)
  for (const h of histogram) h.count = h.count / maxCount // normalize to [0,1]

  return { paths, terminals, histogram, meanTerminal, stdTerminal }
}

/* ── GEX (gamma exposure) profile ──────────────────────────────────────────── */

export interface GexPoint {
  K: number
  gamma: number
  gex: number
}

export function gexProfile(
  S: number,
  T: number,
  sigma: number,
  r: number,
  q: number,
  nStrikes: number,
  strikeRange: number,
): GexPoint[] {
  const points: GexPoint[] = []
  const Klow = S * (1 - strikeRange),
    Khigh = S * (1 + strikeRange)
  let maxGamma = 0
  const rawGamma: number[] = []
  for (let i = 0; i < nStrikes; i++) {
    const K = Klow + ((Khigh - Klow) * i) / (nStrikes - 1)
    const g = bsGamma({ S, K, T, sigma, r, q })
    rawGamma.push(g)
    maxGamma = Math.max(maxGamma, g)
  }
  for (let i = 0; i < nStrikes; i++) {
    const K = Klow + ((Khigh - Klow) * i) / (nStrikes - 1)
    const normGamma = maxGamma > 0 ? rawGamma[i] / maxGamma : 0
    const gex = K < S ? normGamma : -normGamma * 0.7
    points.push({ K, gamma: normGamma, gex })
  }
  return points
}

/* ── Risk-neutral implied range ────────────────────────────────────────────── */

export interface ImpliedRange {
  p1Low: number
  p1High: number
  p2Low: number
  p2High: number
  mean: number
  median: number
}

export function impliedRange(
  S0: number,
  T: number,
  sigma: number,
  r: number,
  q: number,
): ImpliedRange {
  const muLog = Math.log(S0) + (r - q - 0.5 * sigma * sigma) * T
  const sigT = sigma * Math.sqrt(T)
  const median = Math.exp(muLog)
  return {
    p1Low: median / Math.exp(sigT),
    p1High: median * Math.exp(sigT),
    p2Low: median / Math.exp(2 * sigT),
    p2High: median * Math.exp(2 * sigT),
    mean: S0 * Math.exp((r - q) * T),
    median,
  }
}

/* ── SVG geometry builders ────────────────────────────────────────────────── */

/** GBM price path → SVG polyline. */
export function pricePathSvg(
  prices: number[],
  box: { x: number; y: number; w: number; h: number },
): { d: string; lastPt: Pt } {
  const xScale = linearScale([0, prices.length - 1], [box.x, box.x + box.w])
  const yScale = linearScale([Math.min(...prices), Math.max(...prices)], [box.y + box.h, box.y])
  const pts: Pt[] = prices.map((p, i) => ({ x: xScale(i), y: yScale(p) }))
  return { d: linePath(pts), lastPt: pts[pts.length - 1] }
}

/** Multiple GBM paths → array of SVG polylines (for the MC fan chart). */
export function mcPathsSvg(
  paths: number[][],
  box: { x: number; y: number; w: number; h: number },
): { d: string; opacity: number }[] {
  const allPrices = paths.flat()
  const minP = Math.min(...allPrices),
    maxP = Math.max(...allPrices)
  const xScale = linearScale([0, paths[0].length - 1], [box.x, box.x + box.w])
  const yScale = linearScale([minP, maxP], [box.y + box.h, box.y])
  return paths.map((path, i) => ({
    d: linePath(path.map((p, j) => ({ x: xScale(j), y: yScale(p) }))),
    opacity: 0.12 + 0.08 * ((i % 3) / 3),
  }))
}

/** MC histogram → SVG bar paths. */
export function histogramSvg(
  hist: { x: number; count: number }[],
  box: { x: number; y: number; w: number; h: number },
  barWidth: number,
): string {
  const xScale = linearScale(
    [hist[0].x - (hist[1]?.x ?? 1) * 0.5, hist[hist.length - 1].x + (hist[1]?.x ?? 1) * 0.5],
    [box.x, box.x + box.w],
  )
  let d = ''
  for (const bar of hist) {
    const cx = xScale(bar.x)
    const barH = bar.count * box.h
    d += `M${cx - barWidth / 2},${box.y + box.h}v${-barH}h${barWidth}v${barH}z`
  }
  return d
}

/** GEX profile → call/put bar paths + zero line + flip x. */
export function gexBarsSvg(
  profile: GexPoint[],
  box: { x: number; y: number; w: number; h: number },
  barWidth: number,
): { callBars: string; putBars: string; zeroY: number; flipX: number } {
  const zeroY = box.y + box.h / 2
  const maxAbsGex = Math.max(...profile.map((p) => Math.abs(p.gex)))
  if (maxAbsGex === 0) return { callBars: '', putBars: '', zeroY, flipX: box.x + box.w / 2 }
  const xScale = linearScale([profile[0].K, profile[profile.length - 1].K], [box.x, box.x + box.w])
  const halfH = box.h / 2
  let flipK = profile[0].K
  for (let i = 1; i < profile.length; i++) {
    if (profile[i - 1].gex > 0 && profile[i].gex <= 0) {
      flipK = profile[i].K
      break
    }
  }
  const flipX = xScale(flipK)
  let callBars = '',
    putBars = ''
  for (const p of profile) {
    const cx = xScale(p.K)
    const barH = (Math.abs(p.gex) / maxAbsGex) * halfH
    if (p.gex >= 0)
      callBars += `M${cx - barWidth / 2},${zeroY - barH}h${barWidth}v${barH}h${-barWidth}z`
    else putBars += `M${cx - barWidth / 2},${zeroY}h${barWidth}v${barH}h${-barWidth}z`
  }
  return { callBars, putBars, zeroY, flipX }
}

/** Vol surface → 3D-projected mesh lines (isometric projection). */
export function volSurfaceMeshSvg(
  surface: VolSurfacePoint[],
  strikes: number[],
  maturities: number[],
  box: { x: number; y: number; w: number; h: number },
  rotation: number,
  tilt: number,
): { gridLines: string[]; surfaceLines: string[]; contourLines: string[] } {
  const ivMin = Math.min(...surface.map((p) => p.iv))
  const ivMax = Math.max(...surface.map((p) => p.iv))
  const ivScale = linearScale([ivMin, ivMax], [0, 1])
  const strikeScale = linearScale([strikes[0], strikes[strikes.length - 1]], [-0.5, 0.5])
  const matScale = linearScale([maturities[0], maturities[maturities.length - 1]], [-0.5, 0.5])

  // Isometric-ish projection
  const project = (sx: number, mx: number, iv: number): Pt => {
    const x3d = strikeScale(sx)
    const z3d = matScale(mx)
    const y3d = ivScale(iv)
    const cosR = Math.cos(rotation),
      sinR = Math.sin(rotation)
    const cosT = Math.cos(tilt),
      sinT = Math.sin(tilt)
    const x = x3d * cosR - z3d * sinR
    const z = x3d * sinR + z3d * cosR
    const y = y3d * cosT - z * sinT
    const depth = y3d * sinT + z * cosT
    return {
      x: box.x + box.w / 2 + x * box.w * 0.42,
      y: box.y + box.h / 2 - y * box.h * 0.38 - depth * box.h * 0.15,
    }
  }

  // Build grid: for each maturity, a line across strikes; for each strike, a line across maturities
  const gridLines: string[] = []
  const surfaceLines: string[] = []

  // Lines along constant maturity (strike → strike)
  for (const T of maturities) {
    const pts: Pt[] = strikes.map((K) => {
      const p = surface.find((s) => s.K === K && s.T === T)!
      return project(K, T, p.iv)
    })
    gridLines.push(linePath(pts))
  }
  // Lines along constant strike (maturity → maturity)
  for (const K of strikes) {
    const pts: Pt[] = maturities.map((T) => {
      const p = surface.find((s) => s.K === K && s.T === T)!
      return project(K, T, p.iv)
    })
    gridLines.push(linePath(pts))
  }

  // Surface fill ribbons between adjacent maturities (for depth)
  for (let mi = 0; mi < maturities.length - 1; mi++) {
    const upper: Pt[] = strikes.map((K) => {
      const p = surface.find((s) => s.K === K && s.T === maturities[mi])!
      return project(K, maturities[mi], p.iv)
    })
    const lower: Pt[] = strikes.map((K) => {
      const p = surface.find((s) => s.K === K && s.T === maturities[mi + 1])!
      return project(K, maturities[mi + 1], p.iv)
    })
    surfaceLines.push(bandPath(upper, lower))
  }

  // Contour lines at specific IV levels
  const contourLevels = [0.25, 0.5, 0.75]
  const contourLines: string[] = []
  for (const level of contourLevels) {
    const targetIv = ivMin + level * (ivMax - ivMin)
    const pts: Pt[] = []
    for (const T of maturities) {
      // Find the strike where IV is closest to targetIv for this maturity
      let bestK = strikes[0],
        bestDiff = Infinity
      for (const K of strikes) {
        const p = surface.find((s) => s.K === K && s.T === T)!
        const diff = Math.abs(p.iv - targetIv)
        if (diff < bestDiff) {
          bestDiff = diff
          bestK = K
        }
      }
      pts.push(project(bestK, T, targetIv))
    }
    contourLines.push(smoothPath(pts))
  }

  return { gridLines, surfaceLines, contourLines }
}

/** Lognormal density → smooth curve + area fill. */
export function lognormalDensitySvg(
  S0: number,
  T: number,
  sigma: number,
  r: number,
  q: number,
  box: { x: number; y: number; w: number; h: number },
  nPoints: number,
): { d: string; area: string; p1LowX: number; p1HighX: number; medianX: number } {
  const muLog = Math.log(S0) + (r - q - 0.5 * sigma * sigma) * T
  const sigT = sigma * Math.sqrt(T)
  const median = Math.exp(muLog)
  const p1Low = median / Math.exp(sigT),
    p1High = median * Math.exp(sigT)
  const xMin = S0 * (1 - 3 * sigT),
    xMax = S0 * (1 + 3 * sigT)
  const xScale = linearScale([xMin, xMax], [box.x, box.x + box.w])
  const samples: Pt[] = []
  let maxPdf = 0
  const pdfValues: number[] = []
  for (let i = 0; i < nPoints; i++) {
    const x = xMin + ((xMax - xMin) * i) / (nPoints - 1)
    const z = (Math.log(x) - muLog) / sigT
    const pdf = (1 / (x * sigT * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * z * z)
    pdfValues.push(pdf)
    maxPdf = Math.max(maxPdf, pdf)
  }
  const yScale = linearScale([0, maxPdf], [box.y + box.h, box.y])
  for (let i = 0; i < nPoints; i++) {
    const x = xMin + ((xMax - xMin) * i) / (nPoints - 1)
    samples.push({ x: xScale(x), y: yScale(pdfValues[i]) })
  }
  return {
    d: smoothPath(samples),
    area: areaPath(samples, box.y + box.h),
    p1LowX: xScale(p1Low),
    p1HighX: xScale(p1High),
    medianX: xScale(median),
  }
}
