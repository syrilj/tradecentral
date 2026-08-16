/**
 * Closed-form Black-Scholes pricing engine, Greeks matrix with Rho, multi-leg portfolio aggregator,
 * dual payoff evaluator (Expiry P/L + T+0 theoretical), and analytical risk/reward bounds.
 */

import { areaPath, linePath } from '@/charts/path'
import { linearScale, niceDomain, niceTicks } from '@/charts/scale'

export type CalcStrategy =
  | 'long_call'
  | 'long_put'
  | 'bull_call_spread'
  | 'bear_put_spread'
  | 'bull_put_spread'
  | 'bear_call_spread'
  | 'long_straddle'
  | 'long_strangle'
  | 'iron_condor'
  | 'covered_call'
  | 'calendar_spread'
  | 'custom'

export type OptionRight = 'call' | 'put'

export interface CalcLeg {
  id: string
  right: OptionRight
  strike: number
  quantity: number
  premium: number
  dte?: number
  vol?: number // per-leg IV override % (e.g. 35 for 35%)
}

export interface ApiLeg {
  right: OptionRight
  strike: number
  quantity: number
  premium: number
  dte?: number
  vol?: number
}

export interface GreekMetrics {
  delta: number
  gamma: number
  theta: number // Daily theta ($ / day per contract multiplier 100)
  vega: number  // $ / 1% vol change per contract multiplier 100
  rho: number   // $ / 1% interest rate change per contract multiplier 100
  theo: number  // Model theoretical price per share
}

export interface BookGreeks extends GreekMetrics {
  netDebit: number
}

export interface PnlPoint {
  spot: number
  pnl: number
}

export interface DualPnlPoint {
  spot: number
  pnlExpiry: number
  pnlTheo: number
  pnl?: number
}

export interface RiskRewardBounds {
  maxProfit: number | null
  maxLoss: number | null
  isProfitUnbounded: boolean
  isLossUnbounded: boolean
  formattedMaxProfit: string
  formattedMaxLoss: string
}

export interface RiskRewardAssessment {
  maxProfit: number | 'unlimited'
  maxLoss: number | 'unlimited'
  maxProfitLabel: string
  maxLossLabel: string
  isProfitUnlimited: boolean
  isLossUnlimited: boolean
}

export interface StrategyPresetMeta {
  key: Exclude<CalcStrategy, 'custom'>
  label: string
  category: 'Directional' | 'Income' | 'Volatility'
  description: string
  factory: (spot: number, dte?: number, volPct?: number, premiumHint?: number) => CalcLeg[]
}

export interface RiskNeutralModel {
  mu: number
  sigma: number
  sigma2: number
  T: number
  iv: number
  low: number
  high: number
  horizon: number
  expectedMove: number
  expectedLow: number
  expectedHigh: number
  twoSigmaLow: number
  twoSigmaHigh: number
}

export interface TargetRiskMetrics {
  targetPrice: number
  chgPct: number
  zScore: number
  probAbove: number
  probBelow: number
  probBetweenWalls: number | null
}

export interface StrategyPoPMetrics {
  pop: number
  popPctFormatted: string
  breakevens: number[]
  profitZoneDesc: string
}

export const MULTIPLIER = 100
export const DEFAULT_RATE = 4.5 // 4.5%
export const DEFAULT_DIVIDEND = 0.0
const INV_SQRT_2PI = 0.3989422804014327 // 1 / sqrt(2*pi)

/* ------------------------------------------------------------------ Normal Distribution Math */

export function normPdf(x: number): number {
  return INV_SQRT_2PI * Math.exp(-0.5 * x * x)
}

/** Abramowitz & Stegun formula 7.1.26 (maximum error: 1.5e-7) */
export function erf(x: number): number {
  const sign = x >= 0 ? 1 : -1
  const a1 = 0.254829592
  const a2 = -0.284496736
  const a3 = 1.421413741
  const a4 = -1.453152027
  const a5 = 1.061405429
  const p = 0.3275911
  const absX = Math.abs(x)
  const t = 1.0 / (1.0 + p * absX)
  const y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-absX * absX)
  return sign * y
}

export function normCdf(x: number): number {
  return 0.5 * (1.0 + erf(x / Math.SQRT2))
}

export function lognormalDensity(x: number, mu: number, sigma: number): number {
  if (x <= 0 || sigma <= 0) return 0
  const z = (Math.log(x) - mu) / sigma
  return (1 / (x * sigma * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * z * z)
}

/* ------------------------------------------------------------------ Risk-Neutral Distribution Engine */

export function computeRiskNeutralModel(input: {
  spot: number
  dteDays: number
  volPct: number
  ratePct?: number
  dividendPct?: number
  callWall?: number | null
  putWall?: number | null
  focusPrice?: number | null
  breakevens?: readonly number[]
}): RiskNeutralModel | null {
  const S = Number(input.spot)
  const dte = Number(input.dteDays)
  const volPct = Number(input.volPct)
  if (!Number.isFinite(S) || S <= 0 || !Number.isFinite(dte) || dte <= 0 || !Number.isFinite(volPct) || volPct <= 0) {
    return null
  }

  const r = normalizeRate(input.ratePct)
  const q = normalizeRate(input.dividendPct)
  const T = Math.max(dte, 1) / 365.0
  const iv = volPct > 2.0 ? volPct / 100 : volPct
  const sigma = iv * Math.sqrt(T)
  if (!(sigma > 0)) return null

  const mu = Math.log(S) + (r - q - 0.5 * iv * iv) * T
  const sigma2 = 2 * sigma
  const expectedMove = S * sigma
  const expectedLow = Math.max(0.01, S - expectedMove)
  const expectedHigh = S + expectedMove
  const twoSigmaLow = Math.max(0.01, S - 2 * expectedMove)
  const twoSigmaHigh = S + 2 * expectedMove

  let low = Math.max(0.01, S * Math.exp(-2.5 * sigma))
  let high = S * Math.exp(2.5 * sigma)

  if (input.focusPrice != null && input.focusPrice > 0) {
    low = Math.min(low, input.focusPrice * 0.95)
    high = Math.max(high, input.focusPrice * 1.05)
  }
  if (input.callWall != null && input.callWall > 0) {
    high = Math.max(high, input.callWall * 1.05)
  }
  if (input.putWall != null && input.putWall > 0) {
    low = Math.min(low, input.putWall * 0.95)
  }
  for (const be of input.breakevens ?? []) {
    if (be > 0) {
      low = Math.min(low, be * 0.95)
      high = Math.max(high, be * 1.05)
    }
  }

  return {
    mu,
    sigma,
    sigma2,
    T,
    iv,
    low,
    high,
    horizon: dte,
    expectedMove,
    expectedLow,
    expectedHigh,
    twoSigmaLow,
    twoSigmaHigh,
  }
}

export function probTerminalAbove(
  strike: number,
  spot: number,
  dteDays: number,
  volPct: number,
  ratePct = DEFAULT_RATE,
  dividendPct = DEFAULT_DIVIDEND,
): number {
  const K = Number(strike)
  const S = Number(spot)
  const dte = Number(dteDays)
  const vol = normalizeVol(volPct)
  const r = normalizeRate(ratePct)
  const q = normalizeRate(dividendPct)
  const T = Math.max(dte, 1) / 365.0
  if (K <= 0 || S <= 0 || vol <= 0 || T <= 0) return 0.5
  const rootT = Math.sqrt(T)
  const d2 = (Math.log(S / K) + (r - q - 0.5 * vol * vol) * T) / (vol * rootT)
  return normCdf(d2)
}

export function probTerminalBelow(
  strike: number,
  spot: number,
  dteDays: number,
  volPct: number,
  ratePct = DEFAULT_RATE,
  dividendPct = DEFAULT_DIVIDEND,
): number {
  return 1 - probTerminalAbove(strike, spot, dteDays, volPct, ratePct, dividendPct)
}

export function computeTargetRiskMetrics(input: {
  targetPrice: number
  spot: number
  dteDays: number
  volPct: number
  callWall?: number | null
  putWall?: number | null
  ratePct?: number
  dividendPct?: number
}): TargetRiskMetrics | null {
  const tp = Number(input.targetPrice)
  const S = Number(input.spot)
  const dte = Number(input.dteDays)
  const volPct = Number(input.volPct)
  if (!Number.isFinite(tp) || tp <= 0 || !Number.isFinite(S) || S <= 0 || !Number.isFinite(dte) || dte <= 0 || !Number.isFinite(volPct) || volPct <= 0) {
    return null
  }

  const model = computeRiskNeutralModel({
    spot: S,
    dteDays: dte,
    volPct,
    ratePct: input.ratePct,
    dividendPct: input.dividendPct,
  })
  if (!model) return null

  const chgPct = ((tp - S) / S) * 100
  const zScore = (Math.log(tp / S) - (model.mu - Math.log(S))) / model.sigma
  const probAbove = probTerminalAbove(tp, S, dte, volPct, input.ratePct, input.dividendPct)
  const probBelow = 1 - probAbove

  let probBetweenWalls: number | null = null
  if (input.putWall && input.callWall && input.putWall < input.callWall) {
    const pPut = probTerminalAbove(input.putWall, S, dte, volPct, input.ratePct, input.dividendPct)
    const pCall = probTerminalAbove(input.callWall, S, dte, volPct, input.ratePct, input.dividendPct)
    probBetweenWalls = Math.max(0, pPut - pCall)
  }

  return {
    targetPrice: tp,
    chgPct,
    zScore,
    probAbove,
    probBelow,
    probBetweenWalls,
  }
}

/**
 * Calculates the exact analytical Probability of Profit (PoP) for the multi-leg book
 * under the risk-neutral terminal price lognormal distribution.
 */
export function calculateStrategyPoP(input: {
  legs: readonly CalcLeg[]
  spot: number
  dteDays: number
  volPct: number
  ratePct?: number
  dividendPct?: number
  breakevens?: readonly number[]
}): StrategyPoPMetrics {
  const { legs, spot, dteDays, volPct, ratePct = DEFAULT_RATE, dividendPct = DEFAULT_DIVIDEND } = input
  const usable = usableLegs(legs)
  const bes = input.breakevens ?? findBreakevens(evaluateBookDualCurves({ legs, spot, dteDays, volPct, ratePct }))

  if (!usable.length || !Number.isFinite(spot) || spot <= 0) {
    return { pop: 0.5, popPctFormatted: '50.0%', breakevens: [], profitZoneDesc: 'No active legs' }
  }

  const model = computeRiskNeutralModel({ spot, dteDays, volPct, ratePct, dividendPct })
  if (!model) {
    return { pop: 0.5, popPctFormatted: '50.0%', breakevens: [...bes], profitZoneDesc: 'Standard distribution' }
  }

  // Fast evaluation of PnL at a given terminal spot
  const debit = netDebit(legs)
  const evalPnlAt = (s: number) => {
    let payoff = -debit
    for (const leg of usable) {
      const intrinsic = leg.right === 'call' ? Math.max(s - leg.strike, 0) : Math.max(leg.strike - s, 0)
      payoff += intrinsic * MULTIPLIER * leg.quantity
    }
    return payoff
  }

  // High precision numerical integration over the probability density
  const nSteps = 240
  const minS = Math.max(0.01, spot * 0.2)
  const maxS = spot * 2.5
  const step = (maxS - minS) / (nSteps - 1)
  let totalProb = 0
  let profitProb = 0

  for (let i = 0; i < nSteps; i++) {
    const s = minS + i * step
    const d = lognormalDensity(s, model.mu, model.sigma)
    const mass = d * step
    totalProb += mass
    if (evalPnlAt(s) > 0) {
      profitProb += mass
    }
  }

  const rawPoP = totalProb > 0 ? Math.min(1.0, Math.max(0.0, profitProb / totalProb)) : 0.5
  const pop = Math.round(rawPoP * 1000) / 1000
  const popPctFormatted = `${(pop * 100).toFixed(1)}%`

  let profitZoneDesc = ''
  if (!bes.length) {
    profitZoneDesc = evalPnlAt(spot) > 0 ? 'All price zones profitable' : 'Net debit / Defined loss zone'
  } else if (bes.length === 1) {
    const be = bes[0]
    const aboveProfit = evalPnlAt(be + 5) > 0
    profitZoneDesc = aboveProfit ? `Profitable above $${be.toFixed(2)}` : `Profitable below $${be.toFixed(2)}`
  } else if (bes.length === 2) {
    const [be1, be2] = [...bes].sort((a, b) => a - b)
    const midProfit = evalPnlAt((be1 + be2) / 2) > 0
    profitZoneDesc = midProfit
      ? `Profitable between $${be1.toFixed(2)} and $${be2.toFixed(2)}`
      : `Profitable outside $${be1.toFixed(2)} – $${be2.toFixed(2)}`
  } else {
    profitZoneDesc = `${bes.length} breakeven thresholds`
  }

  return {
    pop,
    popPctFormatted,
    breakevens: [...bes],
    profitZoneDesc,
  }
}

/* ------------------------------------------------------------------ Black-Scholes Solver */

function normalizeRate(ratePct?: number): number {
  if (ratePct == null || !Number.isFinite(ratePct)) return DEFAULT_RATE / 100
  return ratePct > 1.0 ? ratePct / 100 : ratePct
}

function normalizeVol(volPct: number): number {
  if (!Number.isFinite(volPct) || volPct <= 0) return 0.01
  return volPct > 2.0 ? volPct / 100 : volPct
}

export function blackScholesPrice(
  type: OptionRight,
  spot: number,
  strike: number,
  dteDays: number,
  volPct: number,
  ratePct = DEFAULT_RATE,
  dividendPct = DEFAULT_DIVIDEND,
): number {
  return computeGreeks(type, spot, strike, dteDays, volPct, ratePct, dividendPct).theo
}

export function computeGreeks(
  type: OptionRight,
  spot: number,
  strike: number,
  dteDays: number,
  volPct: number,
  ratePct = DEFAULT_RATE,
  dividendPct = DEFAULT_DIVIDEND,
): GreekMetrics {
  const S = Number(spot)
  const K = Number(strike)
  const isCall = type === 'call'
  if (!Number.isFinite(S) || S <= 0 || !Number.isFinite(K) || K <= 0) {
    return { delta: 0, gamma: 0, theta: 0, vega: 0, rho: 0, theo: 0 }
  }

  const dte = Math.max(0, Number(dteDays) || 0)
  const vol = normalizeVol(volPct)
  const r = normalizeRate(ratePct)
  const q = normalizeRate(dividendPct)
  const T = dte / 365.0

  if (T <= 0 || vol <= 0) {
    const theo = isCall ? Math.max(S - K, 0) : Math.max(K - S, 0)
    let delta = 0
    if (isCall) delta = S > K ? 1.0 : S < K ? 0.0 : 0.5
    else delta = S < K ? -1.0 : S > K ? 0.0 : -0.5
    return { delta, gamma: 0, theta: 0, vega: 0, rho: 0, theo }
  }

  const rootT = Math.sqrt(T)
  const d1 = (Math.log(S / K) + (r - q + 0.5 * vol * vol) * T) / (vol * rootT)
  const d2 = d1 - vol * rootT
  const discountR = Math.exp(-r * T)
  const discountQ = Math.exp(-q * T)
  const n1 = normPdf(d1)

  const theo = isCall
    ? Math.max(0, S * discountQ * normCdf(d1) - K * discountR * normCdf(d2))
    : Math.max(0, K * discountR * normCdf(-d2) - S * discountQ * normCdf(-d1))

  const delta = isCall ? discountQ * normCdf(d1) : discountQ * (normCdf(d1) - 1.0)
  const gamma = (discountQ * n1) / (S * vol * rootT)
  const vega = S * discountQ * n1 * rootT * 0.01 * MULTIPLIER // $ per 1% vol per contract

  const thetaYear = isCall
    ? -((S * discountQ * n1 * vol) / (2.0 * rootT)) - r * K * discountR * normCdf(d2) + q * S * discountQ * normCdf(d1)
    : -((S * discountQ * n1 * vol) / (2.0 * rootT)) + r * K * discountR * normCdf(-d2) - q * S * discountQ * normCdf(-d1)
  const theta = (thetaYear / 365.0) * MULTIPLIER // $ per calendar day per contract

  const rho = isCall
    ? K * T * discountR * normCdf(d2) * 0.01 * MULTIPLIER // $ per 1% rate per contract
    : -K * T * discountR * normCdf(-d2) * 0.01 * MULTIPLIER

  return { delta, gamma, theta, vega, rho, theo }
}

/* ------------------------------------------------------------------ Portfolio Greeks Aggregator */

export function computeBookGreeks(
  legs: readonly CalcLeg[],
  spot: number,
  globalDte: number,
  globalVolPct: number,
  ratePct = DEFAULT_RATE,
  dividendPct = DEFAULT_DIVIDEND,
): BookGreeks {
  const usable = usableLegs(legs)
  const totals: BookGreeks = {
    delta: 0,
    gamma: 0,
    theta: 0,
    vega: 0,
    rho: 0,
    theo: 0,
    netDebit: 0,
  }

  for (const leg of usable) {
    const qty = leg.quantity
    const legVol = leg.vol ?? globalVolPct
    const legDte = leg.dte ?? globalDte
    const g = computeGreeks(leg.right, spot, leg.strike, legDte, legVol, ratePct, dividendPct)

    totals.delta += g.delta * qty
    totals.gamma += g.gamma * qty
    totals.theta += g.theta * qty
    totals.vega += g.vega * qty
    totals.rho += g.rho * qty
    totals.theo += g.theo * qty
    totals.netDebit += leg.premium * MULTIPLIER * qty
  }

  return totals
}

/* ------------------------------------------------------------------ Volatility Smile & Skew */

export function smileAdjustedVol(
  strike: number,
  spot: number,
  baseVolPct: number,
  skewPct = 0,
  smilePct = 0,
): number {
  const S = Math.max(0.01, spot)
  const m = (strike - S) / S
  const skewFactor = (skewPct / 100) * -m
  const smileFactor = (smilePct / 100) * m * m
  const factor = Math.max(0.1, 1.0 + skewFactor + smileFactor)
  return Math.max(1, baseVolPct * factor)
}

/* ------------------------------------------------------------------ Analytical Risk/Reward Bounds */

export function evaluateRiskRewardBounds(
  legs: readonly CalcLeg[],
  series: readonly (PnlPoint | DualPnlPoint)[],
): RiskRewardBounds {
  const usable = usableLegs(legs)
  if (!usable.length) {
    return {
      maxProfit: 0,
      maxLoss: 0,
      isProfitUnbounded: false,
      isLossUnbounded: false,
      formattedMaxProfit: '$0',
      formattedMaxLoss: '$0',
    }
  }

  // Net asymptotic call quantity as spot -> +infinity
  const netCallQty = usable.filter((l) => l.right === 'call').reduce((sum, l) => sum + l.quantity, 0)
  const isProfitUnbounded = netCallQty > 0
  const isLossUnbounded = netCallQty < 0

  const ys = series.map((p) => ('pnlExpiry' in p ? p.pnlExpiry : p.pnl))
  const finiteMaxProfit = Math.max(0, ...ys)
  const finiteMaxLoss = Math.min(0, ...ys)

  const formatMoney = (v: number) => {
    const abs = Math.abs(v)
    const sign = v < 0 ? '−$' : '+$'
    return `${sign}${Math.round(abs).toLocaleString('en-US')}`
  }

  return {
    maxProfit: isProfitUnbounded ? null : finiteMaxProfit,
    maxLoss: isLossUnbounded ? null : finiteMaxLoss,
    isProfitUnbounded,
    isLossUnbounded,
    formattedMaxProfit: isProfitUnbounded ? '+∞ Unlimited' : formatMoney(finiteMaxProfit),
    formattedMaxLoss: isLossUnbounded ? '−∞ Unlimited Risk' : formatMoney(finiteMaxLoss),
  }
}

export function detectBookRiskReward(
  legs: readonly CalcLeg[],
  multiplier = MULTIPLIER,
): RiskRewardAssessment {
  const usable = usableLegs(legs)
  if (!usable.length) {
    return {
      maxProfit: 0,
      maxLoss: 0,
      maxProfitLabel: '$0',
      maxLossLabel: '$0',
      isProfitUnlimited: false,
      isLossUnlimited: false,
    }
  }

  const netCallQty = usable.filter((l) => l.right === 'call').reduce((sum, l) => sum + l.quantity, 0)
  const isProfitUnlimited = netCallQty > 0
  const isLossUnlimited = netCallQty < 0

  const debit = netDebit(legs, multiplier)
  const criticalSpots = new Set<number>([0])
  for (const leg of usable) {
    criticalSpots.add(leg.strike)
  }

  const evalExpiryPnl = (s: number): number => {
    let val = 0
    for (const leg of usable) {
      const intrinsic = leg.right === 'call' ? Math.max(s - leg.strike, 0) : Math.max(leg.strike - s, 0)
      val += intrinsic * multiplier * leg.quantity
    }
    return val - debit
  }

  const criticalPnl = [...criticalSpots].map(evalExpiryPnl)
  const asymptoticCallPnl =
    -usable.filter((l) => l.right === 'call').reduce((sum, l) => sum + l.quantity * l.strike * multiplier, 0) - debit
  const allFinitePnls = [...criticalPnl, asymptoticCallPnl]

  const finiteMaxProfit = Math.max(0, ...allFinitePnls)
  const finiteMaxLoss = Math.min(0, ...allFinitePnls)

  const formatMoney = (v: number) => {
    const abs = Math.abs(v)
    const sign = v < 0 ? '−$' : '+$'
    return `${sign}${Math.round(abs).toLocaleString('en-US')}`
  }

  return {
    maxProfit: isProfitUnlimited ? 'unlimited' : finiteMaxProfit,
    maxLoss: isLossUnlimited ? 'unlimited' : finiteMaxLoss,
    maxProfitLabel: isProfitUnlimited ? '+∞ Unlimited' : formatMoney(finiteMaxProfit),
    maxLossLabel: isLossUnlimited ? '−∞ Unlimited Risk' : formatMoney(finiteMaxLoss),
    isProfitUnlimited,
    isLossUnlimited,
  }
}

/* ------------------------------------------------------------------ Dual Curve Evaluation */

export function evaluateBookAtSpot(
  legs: readonly CalcLeg[],
  evalSpot: number,
  dteDays: number,
  evalDaysAhead = 0,
  baseVolPct = 30,
  ratePct = DEFAULT_RATE,
  skewPct = 0,
  smilePct = 0,
  multiplier = MULTIPLIER,
): { pnlExpiry: number; pnlTheo: number; theoValue: number } {
  const usable = usableLegs(legs)
  const debit = netDebit(legs, multiplier)
  let pnlExpiry = -debit
  let theoValue = 0

  for (const leg of usable) {
    const intrinsic = leg.right === 'call' ? Math.max(evalSpot - leg.strike, 0) : Math.max(leg.strike - evalSpot, 0)
    pnlExpiry += intrinsic * multiplier * leg.quantity

    const legDte = leg.dte != null && leg.dte >= 0 ? leg.dte : dteDays
    const remDte = Math.max(0, legDte - evalDaysAhead)
    const legVol = leg.vol != null && leg.vol > 0 ? leg.vol : smileAdjustedVol(leg.strike, evalSpot, baseVolPct, skewPct, smilePct)
    const legTheo = blackScholesPrice(leg.right, evalSpot, leg.strike, remDte, legVol, ratePct)
    theoValue += legTheo * multiplier * leg.quantity
  }

  const pnlTheo = theoValue - debit
  return { pnlExpiry, pnlTheo, theoValue }
}

export function evaluateBookDualCurves(input: {
  legs: readonly CalcLeg[]
  spot: number
  dteDays: number
  evalDaysAhead?: number
  volPct?: number
  ratePct?: number
  skewPct?: number
  smilePct?: number
  multiplier?: number
  spotRangePct?: number
  gridPoints?: number
}): DualPnlPoint[] {
  const {
    legs,
    spot,
    dteDays,
    evalDaysAhead = 0,
    volPct = 30,
    ratePct = DEFAULT_RATE,
    skewPct = 0,
    smilePct = 0,
    multiplier = MULTIPLIER,
    spotRangePct = 0.4,
    gridPoints = 81,
  } = input

  const usable = usableLegs(legs)
  if (!usable.length || !Number.isFinite(spot) || spot <= 0) return []

  const strikes = usable.map((l) => l.strike)
  const minK = Math.min(...strikes)
  const maxK = Math.max(...strikes)
  const minSpot = Math.max(0.01, Math.min(spot * (1 - spotRangePct), minK * 0.85))
  const maxSpot = Math.max(spot * (1 + spotRangePct), maxK * 1.15)

  const spotSet = new Set<number>()
  const step = (maxSpot - minSpot) / (gridPoints - 1)
  for (let i = 0; i < gridPoints; i++) {
    spotSet.add(Math.round((minSpot + i * step) * 100) / 100)
  }
  spotSet.add(Math.round(spot * 100) / 100)
  for (const k of strikes) {
    spotSet.add(Math.round(k * 100) / 100)
  }

  const sortedSpots = [...spotSet].sort((a, b) => a - b)
  return sortedSpots.map((s) => {
    const res = evaluateBookAtSpot(legs, s, dteDays, evalDaysAhead, volPct, ratePct, skewPct, smilePct, multiplier)
    const pnlExpiry = Math.round(res.pnlExpiry * 100) / 100
    const pnlTheo = Math.round(res.pnlTheo * 100) / 100
    return {
      spot: s,
      pnlExpiry,
      pnlTheo,
      pnl: pnlExpiry,
    }
  })
}

/* ------------------------------------------------------------------ 11 Strategy Presets Registry */

function roundStrike(val: number): number {
  if (val >= 200) return Math.round(val / 5) * 5
  if (val >= 50) return Math.round(val)
  return Math.round(val * 2) / 2
}

function cleanLeg(leg: CalcLeg, dte?: number, vol?: number): CalcLeg {
  const res: CalcLeg = {
    id: leg.id,
    right: leg.right,
    strike: leg.strike,
    quantity: leg.quantity,
    premium: leg.premium,
  }
  if (leg.dte != null) res.dte = leg.dte
  else if (dte != null) res.dte = dte
  if (leg.vol != null) res.vol = leg.vol
  else if (vol != null) res.vol = vol
  return res
}

export const STRATEGY_PRESETS: Record<Exclude<CalcStrategy, 'custom'>, StrategyPresetMeta> = {
  long_call: {
    key: 'long_call',
    label: 'Long Call',
    category: 'Directional',
    description: 'Bullish directional bet with defined risk and unlimited profit potential.',
    factory: (spot, dte, vol, prem = 5) => [
      cleanLeg({ id: 'leg-1', right: 'call', strike: roundStrike(spot), quantity: 1, premium: prem }, dte, vol),
    ],
  },
  long_put: {
    key: 'long_put',
    label: 'Long Put',
    category: 'Directional',
    description: 'Bearish directional bet with defined risk and large downside profit potential.',
    factory: (spot, dte, vol, prem = 5) => [
      cleanLeg({ id: 'leg-1', right: 'put', strike: roundStrike(spot), quantity: 1, premium: prem }, dte, vol),
    ],
  },
  bull_call_spread: {
    key: 'bull_call_spread',
    label: 'Bull Call Spread',
    category: 'Directional',
    description: 'Debit vertical spread reducing entry cost in exchange for capped upside.',
    factory: (spot, dte, vol, prem = 5) => {
      const k1 = roundStrike(spot)
      const dK = Math.max(1, Math.round(spot * 0.05 * 2) / 2)
      const k2 = roundStrike(k1 + dK)
      return [
        cleanLeg({ id: 'leg-1', right: 'call', strike: k1, quantity: 1, premium: prem }, dte, vol),
        cleanLeg({ id: 'leg-2', right: 'call', strike: k2, quantity: -1, premium: Math.max(0.05, Math.round(prem * 0.45 * 100) / 100) }, dte, vol),
      ]
    },
  },
  bear_put_spread: {
    key: 'bear_put_spread',
    label: 'Bear Put Spread',
    category: 'Directional',
    description: 'Debit put vertical spread targeting moderate downside with lower theta cost.',
    factory: (spot, dte, vol, prem = 5) => {
      const k1 = roundStrike(spot)
      const dK = Math.max(1, Math.round(spot * 0.05 * 2) / 2)
      const k2 = roundStrike(Math.max(0.5, k1 - dK))
      return [
        cleanLeg({ id: 'leg-1', right: 'put', strike: k1, quantity: 1, premium: prem }, dte, vol),
        cleanLeg({ id: 'leg-2', right: 'put', strike: k2, quantity: -1, premium: Math.max(0.05, Math.round(prem * 0.45 * 100) / 100) }, dte, vol),
      ]
    },
  },
  bull_put_spread: {
    key: 'bull_put_spread',
    label: 'Bull Put Spread',
    category: 'Income',
    description: 'Credit put vertical spread collecting premium from bullish or neutral price action.',
    factory: (spot, dte, vol, prem = 5) => {
      const dK = Math.max(1, Math.round(spot * 0.05 * 2) / 2)
      const k1 = roundStrike(spot)
      const k2 = roundStrike(Math.max(0.5, k1 - dK))
      return [
        cleanLeg({ id: 'leg-1', right: 'put', strike: k1, quantity: -1, premium: prem }, dte, vol),
        cleanLeg({ id: 'leg-2', right: 'put', strike: k2, quantity: 1, premium: Math.max(0.05, Math.round(prem * 0.45 * 100) / 100) }, dte, vol),
      ]
    },
  },
  bear_call_spread: {
    key: 'bear_call_spread',
    label: 'Bear Call Spread',
    category: 'Income',
    description: 'Credit call vertical spread profiting from bearish drift or time decay.',
    factory: (spot, dte, vol, prem = 5) => {
      const dK = Math.max(1, Math.round(spot * 0.05 * 2) / 2)
      const k1 = roundStrike(spot)
      const k2 = roundStrike(k1 + dK)
      return [
        cleanLeg({ id: 'leg-1', right: 'call', strike: k1, quantity: -1, premium: prem }, dte, vol),
        cleanLeg({ id: 'leg-2', right: 'call', strike: k2, quantity: 1, premium: Math.max(0.05, Math.round(prem * 0.45 * 100) / 100) }, dte, vol),
      ]
    },
  },
  long_straddle: {
    key: 'long_straddle',
    label: 'Long Straddle',
    category: 'Volatility',
    description: 'Market-neutral volatility structure profiting from sharp breakout moves in either direction.',
    factory: (spot, dte, vol, prem = 5) => {
      const k = roundStrike(spot)
      return [
        cleanLeg({ id: 'leg-1', right: 'call', strike: k, quantity: 1, premium: prem }, dte, vol),
        cleanLeg({ id: 'leg-2', right: 'put', strike: k, quantity: 1, premium: prem }, dte, vol),
      ]
    },
  },
  long_strangle: {
    key: 'long_strangle',
    label: 'Long Strangle',
    category: 'Volatility',
    description: 'OTM volatility structure offering lower cost than a straddle for explosive breakouts.',
    factory: (spot, dte, vol, prem = 5) => {
      const dK = Math.max(1, Math.round(spot * 0.05 * 2) / 2)
      const kPut = roundStrike(Math.max(0.5, spot - dK))
      const kCall = roundStrike(spot + dK)
      return [
        cleanLeg({ id: 'leg-1', right: 'put', strike: kPut, quantity: 1, premium: Math.max(0.05, Math.round(prem * 0.7 * 100) / 100) }, dte, vol),
        cleanLeg({ id: 'leg-2', right: 'call', strike: kCall, quantity: 1, premium: Math.max(0.05, Math.round(prem * 0.7 * 100) / 100) }, dte, vol),
      ]
    },
  },
  iron_condor: {
    key: 'iron_condor',
    label: 'Iron Condor',
    category: 'Income',
    description: '4-leg range-bound income structure collecting premium between two defined wings.',
    factory: (spot, dte, vol, prem = 5) => {
      const dK = Math.max(1, Math.round(spot * 0.05 * 2) / 2)
      const pWing = roundStrike(Math.max(0.5, spot - 2 * dK))
      const pShort = roundStrike(Math.max(0.5, spot - dK))
      const cShort = roundStrike(spot + dK)
      const cWing = roundStrike(spot + 2 * dK)
      return [
        cleanLeg({ id: 'leg-1', right: 'put', strike: pWing, quantity: 1, premium: Math.max(0.05, Math.round(prem * 0.3 * 100) / 100) }, dte, vol),
        cleanLeg({ id: 'leg-2', right: 'put', strike: pShort, quantity: -1, premium: Math.max(0.05, Math.round(prem * 0.7 * 100) / 100) }, dte, vol),
        cleanLeg({ id: 'leg-3', right: 'call', strike: cShort, quantity: -1, premium: Math.max(0.05, Math.round(prem * 0.7 * 100) / 100) }, dte, vol),
        cleanLeg({ id: 'leg-4', right: 'call', strike: cWing, quantity: 1, premium: Math.max(0.05, Math.round(prem * 0.3 * 100) / 100) }, dte, vol),
      ]
    },
  },
  covered_call: {
    key: 'covered_call',
    label: 'Covered Call',
    category: 'Income',
    description: 'Yield generation strategy selling upside call options against long stock.',
    factory: (spot, dte, vol, prem = 5) => {
      const dK = Math.max(1, Math.round(spot * 0.05 * 2) / 2)
      return [
        cleanLeg({ id: 'leg-1', right: 'call', strike: roundStrike(spot + dK), quantity: -1, premium: Math.max(0.05, Math.round(prem * 0.8 * 100) / 100) }, dte, vol),
      ]
    },
  },
  calendar_spread: {
    key: 'calendar_spread',
    label: 'Calendar Spread',
    category: 'Volatility',
    description: 'Time decay play selling near-dated option while owning longer-dated protection.',
    factory: (spot, dte, vol, prem = 5) => {
      const k = roundStrike(spot)
      const baseDte = dte ?? 30
      const nearDte = Math.max(7, Math.round(baseDte * 0.5))
      const farDte = Math.max(14, baseDte)
      return [
        cleanLeg({ id: 'leg-1', right: 'call', strike: k, quantity: -1, premium: prem, dte: nearDte }, undefined, vol),
        cleanLeg({ id: 'leg-2', right: 'call', strike: k, quantity: 1, premium: Math.max(0.05, Math.round(prem * 1.45 * 100) / 100), dte: farDte }, undefined, vol),
      ]
    },
  },
}

/* ------------------------------------------------------------------ Strategy & Right Parsers */

export function asStrategy(value: unknown): CalcStrategy {
  const raw = String(value || '').toLowerCase()
  if (raw === 'long_put' || raw === 'put') return 'long_put'
  if (raw === 'bull_call_spread' || raw === 'call_spread') return 'bull_call_spread'
  if (raw === 'bear_put_spread' || raw === 'put_spread') return 'bear_put_spread'
  if (raw === 'bull_put_spread') return 'bull_put_spread'
  if (raw === 'bear_call_spread') return 'bear_call_spread'
  if (raw === 'long_straddle' || raw === 'straddle') return 'long_straddle'
  if (raw === 'long_strangle' || raw === 'strangle') return 'long_strangle'
  if (raw === 'iron_condor' || raw === 'condor') return 'iron_condor'
  if (raw === 'covered_call') return 'covered_call'
  if (raw === 'calendar_spread' || raw === 'calendar') return 'calendar_spread'
  if (raw === 'custom') return 'custom'
  return 'long_call'
}

export function asRight(value: unknown): OptionRight {
  const raw = String(value || '').toLowerCase()
  return raw === 'put' || raw === 'p' || raw === 'puts' ? 'put' : 'call'
}

export function seedBook(input: {
  strategy: CalcStrategy
  strike: number
  premium: number
  quantity?: number
  dte?: number
  vol?: number
}): CalcLeg[] {
  const strike = Number(input.strike)
  const premium = Number(input.premium)
  const quantity = Number(input.quantity)
  const dte = input.dte != null ? Number(input.dte) : undefined
  const vol = input.vol != null ? Number(input.vol) : undefined
  const qty = Number.isFinite(quantity) && quantity !== 0 ? quantity : 1
  const k = Number.isFinite(strike) && strike > 0 ? strike : 100
  const p = Number.isFinite(premium) && premium >= 0 ? premium : 0

  const stratKey = input.strategy === 'custom' ? 'long_call' : input.strategy
  const preset = STRATEGY_PRESETS[stratKey as keyof typeof STRATEGY_PRESETS]
  if (preset) {
    const generated = preset.factory(k, dte, vol, p)
    if (qty !== 1) {
      return generated.map((leg) => ({ ...leg, quantity: leg.quantity * qty }))
    }
    return generated
  }
  const fallback = cleanLeg({ id: 'leg-1', right: 'call', strike: k, quantity: qty, premium: p }, dte, vol)
  return [fallback]
}

export function usableLegs(legs: readonly (CalcLeg | ApiLeg)[]): ApiLeg[] {
  const out: ApiLeg[] = []
  for (const leg of legs) {
    const strike = Number(leg.strike)
    const quantity = Number(leg.quantity)
    const premium = Number(leg.premium)
    if (!Number.isFinite(strike) || strike <= 0) continue
    if (!Number.isFinite(quantity) || quantity === 0) continue
    if (!Number.isFinite(premium) || premium < 0) continue
    out.push({
      right: asRight(leg.right),
      strike,
      quantity,
      premium,
      dte: leg.dte,
      vol: leg.vol,
    })
  }
  return out
}

export function netDebit(legs: readonly (CalcLeg | ApiLeg)[], multiplier = MULTIPLIER): number {
  return usableLegs(legs).reduce((sum, leg) => sum + leg.premium * multiplier * leg.quantity, 0)
}

export function findBreakevens(series: readonly (PnlPoint | DualPnlPoint)[]): number[] {
  const out: number[] = []
  const getPnl = (p: PnlPoint | DualPnlPoint) => ('pnlExpiry' in p ? p.pnlExpiry : p.pnl)
  for (let i = 1; i < series.length; i++) {
    const a = series[i - 1]
    const b = series[i]
    const aPnl = getPnl(a)
    const bPnl = getPnl(b)
    if (!Number.isFinite(aPnl) || !Number.isFinite(bPnl)) continue
    if (!Number.isFinite(a.spot) || !Number.isFinite(b.spot)) continue
    if (aPnl === 0) {
      if (!out.includes(a.spot)) out.push(a.spot)
      continue
    }
    if ((aPnl < 0 && bPnl > 0) || (aPnl > 0 && bPnl < 0)) {
      const span = bPnl - aPnl
      if (span === 0) continue
      const spot = a.spot + (b.spot - a.spot) * (-aPnl / span)
      const rounded = Math.round(spot * 100) / 100
      if (!out.includes(rounded)) out.push(rounded)
    } else if (bPnl === 0 && i === series.length - 1) {
      if (!out.includes(b.spot)) out.push(b.spot)
    }
  }
  return out
}

export function samplePnlRows<T extends PnlPoint | DualPnlPoint>(
  series: readonly T[],
  extraSpots: readonly number[] = [],
): T[] {
  if (!series.length) return []
  const last = series.length - 1
  const picks = [0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1]
    .map((t) => series[Math.min(last, Math.round(t * last))])
  const extras = extraSpots
    .filter((spot) => Number.isFinite(spot) && spot > 0)
    .map((spot) => nearestPointInSeries(series, spot))
  const bySpot = new Map<number, T>()
  for (const point of [...picks, ...extras]) {
    if (!point || !Number.isFinite(point.spot)) continue
    bySpot.set(point.spot, point)
  }
  return [...bySpot.values()].sort((a, b) => a.spot - b.spot)
}

function nearestPointInSeries<T extends PnlPoint | DualPnlPoint>(series: readonly T[], spot: number): T {
  let best = series[0]
  let bestDist = Math.abs(best.spot - spot)
  for (const point of series) {
    const dist = Math.abs(point.spot - spot)
    if (dist < bestDist) {
      best = point
      bestDist = dist
    }
  }
  return best
}

export function nextLegId(legs: readonly { id: string }[]): string {
  let max = 0
  for (const leg of legs) {
    const n = Number(String(leg.id).replace(/^leg-/, ''))
    if (Number.isFinite(n) && n > max) max = n
  }
  return `leg-${max + 1}`
}

export interface BookAllocation {
  callDebit: number
  putDebit: number
  longNotional: number
  shortCredit: number
  net: number
  callAbs: number
  putAbs: number
  callShare: number | null
  putShare: number | null
}

/** Signed cash and mix for the book. Debit is positive; short premium is credit. */
export function bookAllocation(legs: readonly CalcLeg[], multiplier = MULTIPLIER): BookAllocation {
  let callDebit = 0
  let putDebit = 0
  let longNotional = 0
  let shortCredit = 0
  for (const leg of usableLegs(legs)) {
    const cash = leg.premium * multiplier * leg.quantity
    if (leg.right === 'put') putDebit += cash
    else callDebit += cash
    if (cash > 0) longNotional += cash
    else if (cash < 0) shortCredit += -cash
  }
  const callAbs = Math.abs(callDebit)
  const putAbs = Math.abs(putDebit)
  const totalAbs = callAbs + putAbs
  return {
    callDebit,
    putDebit,
    longNotional,
    shortCredit,
    net: callDebit + putDebit,
    callAbs,
    putAbs,
    callShare: totalAbs > 0 ? callAbs / totalAbs : null,
    putShare: totalAbs > 0 ? putAbs / totalAbs : null,
  }
}

export interface PayoffChartGeom {
  width: number
  height: number
  pad: { l: number; r: number; t: number; b: number }
  line: string
  t0Line?: string
  profitArea: string
  lossArea: string
  zeroY: number
  spotX: number
  xTicks: Array<{ x: number; label: number }>
  yTicks: Array<{ y: number; label: number }>
  strikes: Array<{ x: number; strike: number; right: OptionRight }>
  breakevens: Array<{ x: number; spot: number }>
  maxProfit: number
  maxLoss: number
  bounds?: RiskRewardBounds
  plotWidth: number
  plotHeight: number
}

export function buildPayoffChart(input: {
  series: readonly (PnlPoint | DualPnlPoint)[]
  spot: number
  strikes?: readonly { strike: number; right?: OptionRight }[]
  width: number
  height: number
  bounds?: RiskRewardBounds
}): PayoffChartGeom | null {
  const series = input.series.filter((point) => {
    const pnl = 'pnlExpiry' in point ? point.pnlExpiry : point.pnl
    return Number.isFinite(point.spot) && Number.isFinite(pnl)
  })
  if (series.length < 2) return null
  const width = Math.max(280, Math.round(input.width))
  const height = Math.max(160, Math.round(input.height))
  const pad = {
    l: width < 420 ? 40 : 52,
    r: 14,
    t: 16,
    b: 26,
  }

  const xs = series.map((point) => point.spot)
  const expYs = series.map((point) => ('pnlExpiry' in point ? point.pnlExpiry : point.pnl))
  const t0Ys = series.map((point) => ('pnlTheo' in point ? point.pnlTheo : ('pnl' in point ? point.pnl : 0)))
  const allYs = [...expYs, ...t0Ys]

  const xDomain = niceDomain(Math.min(...xs), Math.max(...xs), 0.02)
  const yDomain = niceDomain(Math.min(0, ...allYs), Math.max(0, ...allYs), 0.08)
  const x = linearScale(xDomain, [pad.l, width - pad.r])
  const y = linearScale(yDomain, [height - pad.b, pad.t])

  const expPts = series.map((point) => ({
    x: x(point.spot),
    y: y('pnlExpiry' in point ? point.pnlExpiry : point.pnl),
  }))

  const hasT0 = series.some((point) => 'pnlTheo' in point)
  const t0Pts = hasT0
    ? series.map((point) => ({
        x: x(point.spot),
        y: y('pnlTheo' in point ? point.pnlTheo : point.pnl),
      }))
    : []

  const zeroY = y(0)
  const areas = splitSignedAreas(expPts, zeroY)

  const seenStrike = new Set<string>()
  const strikes: PayoffChartGeom['strikes'] = []
  for (const leg of input.strikes ?? []) {
    if (!Number.isFinite(leg.strike) || leg.strike <= 0) continue
    const key = `${leg.right ?? 'call'}-${leg.strike}`
    if (seenStrike.has(key)) continue
    seenStrike.add(key)
    strikes.push({
      x: x(leg.strike),
      strike: leg.strike,
      right: asRight(leg.right),
    })
  }

  return {
    width,
    height,
    pad,
    line: linePath(expPts),
    t0Line: hasT0 ? linePath(t0Pts) : undefined,
    profitArea: areaPath(areas.profit, zeroY),
    lossArea: areaPath(areas.loss, zeroY),
    zeroY,
    spotX: x(input.spot),
    xTicks: niceTicks(xDomain[0], xDomain[1], 6).map((value) => ({ x: x(value), label: value })),
    yTicks: niceTicks(yDomain[0], yDomain[1], 5).map((value) => ({ y: y(value), label: value })),
    strikes,
    breakevens: findBreakevens(series).map((spot) => ({ x: x(spot), spot })),
    maxProfit: Math.max(0, ...expYs),
    maxLoss: Math.min(0, ...expYs),
    bounds: input.bounds,
    plotWidth: width - pad.l - pad.r,
    plotHeight: height - pad.t - pad.b,
  }
}

export function buildDualPayoffChart(input: {
  legs: readonly CalcLeg[]
  spot: number
  dte: number
  volPct: number
  ratePct?: number
  skewPct?: number
  smilePct?: number
  width: number
  height: number
}): PayoffChartGeom | null {
  const dualSeries = evaluateBookDualCurves({
    legs: input.legs,
    spot: input.spot,
    dteDays: input.dte,
    volPct: input.volPct,
    ratePct: input.ratePct,
    skewPct: input.skewPct,
    smilePct: input.smilePct,
  })

  const bounds = evaluateRiskRewardBounds(input.legs, dualSeries)

  return buildPayoffChart({
    series: dualSeries,
    spot: input.spot,
    strikes: input.legs,
    width: input.width,
    height: input.height,
    bounds,
  })
}

function splitSignedAreas(pts: Array<{ x: number; y: number }>, zeroY: number): {
  profit: Array<{ x: number; y: number }>
  loss: Array<{ x: number; y: number }>
} {
  const profit: Array<{ x: number; y: number }> = []
  const loss: Array<{ x: number; y: number }> = []
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i]
    const above = p.y <= zeroY
    if (i > 0) {
      const prev = pts[i - 1]
      const prevAbove = prev.y <= zeroY
      if (prevAbove !== above && prev.y !== zeroY && p.y !== zeroY) {
        const t = (zeroY - prev.y) / (p.y - prev.y)
        const cross = { x: prev.x + t * (p.x - prev.x), y: zeroY }
        profit.push(cross)
        loss.push(cross)
      }
    }
    if (above) {
      profit.push(p)
      loss.push({ x: p.x, y: zeroY })
    } else {
      loss.push(p)
      profit.push({ x: p.x, y: zeroY })
    }
  }
  return { profit, loss }
}
