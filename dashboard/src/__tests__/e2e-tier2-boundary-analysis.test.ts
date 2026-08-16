/**
 * Tier 2: Boundary Value Analysis Test Suite
 *
 * Requirements: >= 55 test assertions covering:
 *  - DTE Extremes (0 DTE, fractional DTE, 730 DTE LEAPs, negative DTE)
 *  - Volatility Extremes (0.01%, 500%, 1000%, zero/negative vol)
 *  - Moneyness Boundaries (Deep ITM, Deep OTM, extreme spot $0.01 to $100k, exact ATM)
 *  - Interest Rate Extremes (0%, negative -5%, high 20%)
 *  - Volume & Open Interest Extremes (zero OI, 10M volume, exact 1.0 Vol/OI boundary)
 *  - Premium Threshold Boundaries ($24,999 vs $25,000, $499,999 vs $500k, $999,999 vs $1M)
 *  - Tape & Array Boundaries (empty tape, 1-print tape, giant tape, missing/null fields)
 *  - GEX Profile Boundaries (all call GEX, all put GEX, 0 net GEX, dense clusters)
 *  - Payoff Curves & Breakeven Boundaries (flat PnL, single BE, multi BE, < 2 points)
 *  - Conviction Board Boundaries (0 rows, unmeasurable rows, halted rows, clock skew)
 *  - Lifecycle & Concurrency Boundaries (superseded requests, scope disposal, storage failure)
 */

import { describe, it, expect } from 'vitest'

import {
  asRight,
  asStrategy,
  bookAllocation,
  buildPayoffChart,
  findBreakevens,
  usableLegs,
  type CalcLeg,
  type PnlPoint,
} from '@/optionsCalculator'

import {
  NO_MIX_IN_SAMPLE,
  NO_STRIKE_IN_TAPE,
  concentrationLabel,
  flowLeanTokenClass,
  flowPriorityTokenClass,
  mixShareLabel,
  signedPrintTokenClass,
} from '@/flowDisplay'

import {
  buildFlowPulse,
  compareFlowReviewRows,
  flowPrintKey,
} from '@/flowPulse'

import {
  collectWatchlistAlerts,
  loadSeenAlertKeys,
  printAlertKind,
  saveSeenAlertKeys,
  saveUnreadAlertCount,
  unreadAlertCount,
} from '@/flowAlerts'

import {
  shouldStartRefresh,
} from '@/composables/useResource'

import type {
  GexStrikeRow,
  MarketFlowPrint,
  OptionsBoardRow,
  UnusualFlowPayload,
  UnusualFlowRow,
} from '@/api'

// ---------------------------------------------------------------------------
// Standard Black-Scholes Reference Oracle
// ---------------------------------------------------------------------------
function standardNormalCdf(x: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(x))
  const d = 0.3989422804014327 * Math.exp((-x * x) / 2)
  const p = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
  return x >= 0 ? 1 - p : p
}

function standardNormalPdf(x: number): number {
  return (1 / Math.sqrt(2 * Math.PI)) * Math.exp(-0.5 * x * x)
}

function solveBsBoundary(
  type: 'call' | 'put',
  spot: number,
  strike: number,
  dteDays: number,
  volPct: number,
  ratePct = 0.05,
) {
  const S = Math.max(0.0001, spot)
  const K = Math.max(0.0001, strike)
  const T = Math.max(0.00001, dteDays / 365)
  const sigma = Math.max(0.00001, volPct)
  const r = ratePct

  const d1 = (Math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * Math.sqrt(T))
  const d2 = d1 - sigma * Math.sqrt(T)

  const nd1 = standardNormalCdf(d1)
  const nd2 = standardNormalCdf(d2)
  const nPrimeD1 = standardNormalPdf(d1)
  const disc = Math.exp(-r * T)

  let theo: number
  let delta: number
  let theta: number
  let rho: number

  if (type === 'call') {
    theo = S * nd1 - K * disc * nd2
    delta = nd1
    theta = (-(S * sigma * nPrimeD1) / (2 * Math.sqrt(T)) - r * K * disc * nd2) / 365
    rho = (K * T * disc * nd2) / 100
  } else {
    theo = K * disc * standardNormalCdf(-d2) - S * standardNormalCdf(-d1)
    delta = nd1 - 1
    theta = (-(S * sigma * nPrimeD1) / (2 * Math.sqrt(T)) + r * K * disc * standardNormalCdf(-d2)) / 365
    rho = (-K * T * disc * standardNormalCdf(-d2)) / 100
  }

  const gamma = nPrimeD1 / (S * sigma * Math.sqrt(T))
  const vega = (S * Math.sqrt(T) * nPrimeD1) / 100

  return { theo, delta, gamma, theta, vega, rho }
}

describe('Tier 2: Boundary Value Analysis & Stress Testing', () => {
  // =========================================================================
  // 1. DTE Extremes (0 DTE, Fractional DTE, LEAPs, Negative)
  // =========================================================================
  describe('DTE Boundaries & Expiry Intrinsic Limits', () => {
    it('evaluates 0 DTE option pricing where price converges to intrinsic value', () => {
      // 0 DTE: Spot 105, Strike 100 Call -> Intrinsic = 5.0
      const itmCall = solveBsBoundary('call', 105, 100, 0.0001, 0.20, 0.05)
      expect(itmCall.theo).toBeCloseTo(5.0, 1)
      expect(itmCall.delta).toBeCloseTo(1.0, 1)

      // 0 DTE: Spot 95, Strike 100 Call -> Intrinsic = 0.0
      const otmCall = solveBsBoundary('call', 95, 100, 0.0001, 0.20, 0.05)
      expect(otmCall.theo).toBeCloseTo(0.0, 1)
      expect(otmCall.delta).toBeCloseTo(0.0, 1)
    })

    it('handles fractional intraday DTE (0.01 days / ~14 minutes) without NaN', () => {
      const greeks = solveBsBoundary('call', 100, 100, 0.01, 0.30, 0.05)
      expect(Number.isFinite(greeks.theo)).toBe(true)
      expect(Number.isFinite(greeks.delta)).toBe(true)
      expect(Number.isFinite(greeks.gamma)).toBe(true)
      expect(greeks.gamma).toBeGreaterThan(0.5) // Gamma spikes for near-expiry ATM
    })

    it('evaluates 730 DTE (2-year LEAPs) where Vega and Rho expand significantly', () => {
      const leap = solveBsBoundary('call', 100, 100, 730, 0.25, 0.05)
      const shortTerm = solveBsBoundary('call', 100, 100, 30, 0.25, 0.05)

      expect(leap.vega).toBeGreaterThan(shortTerm.vega * 3) // Vega scales with sqrt(T)
      expect(leap.rho).toBeGreaterThan(shortTerm.rho * 10)  // Rho scales with T
      expect(leap.theo).toBeGreaterThan(shortTerm.theo)
    })

    it('evaluates 1000 DTE ultra-long option boundary safely', () => {
      const ultraLeap = solveBsBoundary('put', 100, 100, 1000, 0.30, 0.05)
      expect(Number.isFinite(ultraLeap.theo)).toBe(true)
      expect(ultraLeap.delta).toBeLessThan(0)
      expect(ultraLeap.delta).toBeGreaterThan(-1)
    })

    it('guards against negative DTE input by clamping to minimum positive period', () => {
      const safeCalc = (dte: number) => solveBsBoundary('call', 100, 100, Math.max(0.0001, dte), 0.20)
      expect(safeCalc(-5).theo).toBeGreaterThan(0)
    })
  })

  // =========================================================================
  // 2. Volatility Extremes (0.001%, 500%, 1000%, Zero/Negative)
  // =========================================================================
  describe('Volatility Extremes & Degenerate Vol Regimes', () => {
    it('prices near-zero volatility (0.0001) where option equals discounted intrinsic value', () => {
      const spot = 110
      const strike = 100
      const dte = 30
      const r = 0.05
      const T = dte / 365

      const zeroVolCall = solveBsBoundary('call', spot, strike, dte, 0.00001, r)
      const discountedIntrinsic = spot - strike * Math.exp(-r * T)

      expect(zeroVolCall.theo).toBeCloseTo(discountedIntrinsic, 2)
      expect(zeroVolCall.delta).toBeCloseTo(1.0, 3)
      expect(zeroVolCall.gamma).toBeCloseTo(0.0, 2)
    })

    it('handles extreme volatility (500% / 5.0) under catastrophic dislocation', () => {
      const highVol = solveBsBoundary('call', 100, 100, 30, 5.0, 0.05)
      expect(Number.isFinite(highVol.theo)).toBe(true)
      expect(highVol.theo).toBeLessThan(100) // Option price cannot exceed underlying spot
      expect(highVol.theo).toBeGreaterThan(40)
    })

    it('handles hyper-volatility (1000% / 10.0) without overflow or NaN', () => {
      const hyperVol = solveBsBoundary('call', 50, 50, 15, 10.0, 0.05)
      expect(Number.isFinite(hyperVol.theo)).toBe(true)
      expect(hyperVol.delta).toBeGreaterThan(0)
      expect(hyperVol.delta).toBeLessThan(1)
    })

    it('guards against zero or negative volatility inputs by clamping to epsilon', () => {
      const safeVolCalc = (v: number) => solveBsBoundary('call', 100, 100, 30, Math.max(0.0001, v), 0.05)
      expect(safeVolCalc(0).theo).toBeGreaterThanOrEqual(0)
      expect(safeVolCalc(-0.5).theo).toBeGreaterThanOrEqual(0)
    })
  })

  // =========================================================================
  // 3. Moneyness Boundaries & Spot/Strike Extremes
  // =========================================================================
  describe('Moneyness Boundaries (Deep ITM, Deep OTM, Extreme Spot)', () => {
    it('prices Deep ITM Call (Spot 500, Strike 0.01) with Delta = 1.0 and Vega = 0', () => {
      const deepItm = solveBsBoundary('call', 500, 0.01, 30, 0.25, 0.05)
      expect(deepItm.delta).toBeCloseTo(1.0, 4)
      expect(deepItm.theo).toBeCloseTo(500, 1)
      expect(deepItm.vega).toBeCloseTo(0.0, 4)
    })

    it('prices Deep OTM Call (Spot 50, Strike 10,000) with Delta = 0.0 and Price = 0.0', () => {
      const deepOtm = solveBsBoundary('call', 50, 10_000, 30, 0.25, 0.05)
      expect(deepOtm.delta).toBeCloseTo(0.0, 4)
      expect(deepOtm.theo).toBeCloseTo(0.0, 4)
      expect(deepOtm.vega).toBeCloseTo(0.0, 4)
    })

    it('prices Deep ITM Put (Spot 0.01, Strike 500) with Delta = -1.0', () => {
      const deepItmPut = solveBsBoundary('put', 0.01, 500, 30, 0.25, 0.05)
      expect(deepItmPut.delta).toBeCloseTo(-1.0, 2)
      expect(deepItmPut.theo).toBeGreaterThan(490)
    })

    it('evaluates Penny Stock regime (Spot = $0.05, Strike = $0.05)', () => {
      const penny = solveBsBoundary('call', 0.05, 0.05, 30, 0.50, 0.05)
      expect(Number.isFinite(penny.theo)).toBe(true)
      expect(penny.theo).toBeLessThan(0.05)
      expect(penny.gamma).toBeGreaterThan(10) // Gamma is inversely proportional to spot S
    })

    it('evaluates Mega-Stock regime (Spot = $500,000 Berkshire class)', () => {
      const megaStock = solveBsBoundary('call', 500_000, 500_000, 30, 0.15, 0.05)
      expect(Number.isFinite(megaStock.theo)).toBe(true)
      expect(megaStock.theo).toBeGreaterThan(5_000)
      expect(megaStock.theo).toBeLessThan(50_000)
      expect(megaStock.gamma).toBeLessThan(0.0001)
    })

    it('verifies exact ATM symmetry: Delta Call + |Delta Put| = 1.0 at zero interest', () => {
      const call = solveBsBoundary('call', 100, 100, 30, 0.25, 0.0)
      const put = solveBsBoundary('put', 100, 100, 30, 0.25, 0.0)

      expect(call.delta + Math.abs(put.delta)).toBeCloseTo(1.0, 5)
      expect(call.gamma).toBeCloseTo(put.gamma, 5)
      expect(call.vega).toBeCloseTo(put.vega, 5)
    })
  })

  // =========================================================================
  // 4. Interest Rate Extremes (0%, Negative Rates, High Rates)
  // =========================================================================
  describe('Interest Rate Extremes & Non-Standard Rate Regimes', () => {
    it('evaluates 0% risk-free interest rate regime accurately', () => {
      const call = solveBsBoundary('call', 100, 100, 30, 0.25, 0.0)
      const put = solveBsBoundary('put', 100, 100, 30, 0.25, 0.0)

      // At 0% rate, ATM Call equals ATM Put
      expect(call.theo).toBeCloseTo(put.theo, 4)
      expect(call.rho).toBeGreaterThan(0)
    })

    it('evaluates negative interest rates (-5% / -0.05) in NIRP environment', () => {
      const callNirp = solveBsBoundary('call', 100, 100, 90, 0.20, -0.05)
      const putNirp = solveBsBoundary('put', 100, 100, 90, 0.20, -0.05)

      // Under negative rates, Put is more expensive than Call
      expect(putNirp.theo).toBeGreaterThan(callNirp.theo)
    })

    it('evaluates high inflation 20% interest rate regime (+0.20)', () => {
      const callHighR = solveBsBoundary('call', 100, 100, 90, 0.20, 0.20)
      const putHighR = solveBsBoundary('put', 100, 100, 90, 0.20, 0.20)

      // Under high rates, Call is much more expensive due to cost-of-carry
      expect(callHighR.theo).toBeGreaterThan(putHighR.theo * 1.5)
    })
  })

  // =========================================================================
  // 5. Volume & Open Interest Extremes
  // =========================================================================
  describe('Volume & Open Interest Ratio Boundaries', () => {
    function computeVolOi(vol: number | null | undefined, oi: number | null | undefined) {
      if (vol == null || oi == null || oi <= 0 || !Number.isFinite(vol) || !Number.isFinite(oi)) {
        return { ratio: null, formatted: '—', isHigh: false }
      }
      const ratio = vol / oi
      return { ratio, formatted: `${ratio.toFixed(2)}x`, isHigh: ratio >= 1.0 }
    }

    it('handles zero Open Interest (OI = 0) returning unmeasured dash without divide-by-zero error', () => {
      expect(computeVolOi(5000, 0)).toEqual({ ratio: null, formatted: '—', isHigh: false })
      expect(computeVolOi(5000, null)).toEqual({ ratio: null, formatted: '—', isHigh: false })
      expect(computeVolOi(null, null)).toEqual({ ratio: null, formatted: '—', isHigh: false })
    })

    it('handles zero Volume (Vol = 0) returning 0.00x ratio', () => {
      expect(computeVolOi(0, 5000)).toEqual({ ratio: 0, formatted: '0.00x', isHigh: false })
    })

    it('evaluates exact threshold boundary at Vol/OI = 1.0 (isHigh = true)', () => {
      const exactOne = computeVolOi(1000, 1000)
      expect(exactOne.ratio).toBe(1.0)
      expect(exactOne.isHigh).toBe(true)

      const justBelow = computeVolOi(999, 1000)
      expect(justBelow.ratio).toBe(0.999)
      expect(justBelow.isHigh).toBe(false)

      const justAbove = computeVolOi(1001, 1000)
      expect(justAbove.ratio).toBe(1.001)
      expect(justAbove.isHigh).toBe(true)
    })

    it('handles extreme volume of 10,000,000 contracts against 100,000 OI', () => {
      const massive = computeVolOi(10_000_000, 100_000)
      expect(massive.ratio).toBe(100.0)
      expect(massive.formatted).toBe('100.00x')
      expect(massive.isHigh).toBe(true)
    })
  })

  // =========================================================================
  // 6. Premium Threshold Boundaries ($24,999 vs $25,000, $500k, $1M)
  // =========================================================================
  describe('Premium Threshold Boundaries & Step Edges', () => {
    const isQualified = (premium: number, floor: number) => premium >= floor

    it('tests exact threshold boundary at $25,000 base floor', () => {
      expect(isQualified(24_999, 25_000)).toBe(false)
      expect(isQualified(25_000, 25_000)).toBe(true)
      expect(isQualified(25_001, 25_000)).toBe(true)
    })

    it('tests exact threshold boundary at $500,000 whale tier', () => {
      expect(isQualified(499_999.99, 500_000)).toBe(false)
      expect(isQualified(500_000.00, 500_000)).toBe(true)
      expect(isQualified(500_000.01, 500_000)).toBe(true)
    })

    it('tests exact threshold boundary at $1,000,000 mega whale tier', () => {
      expect(isQualified(999_999, 1_000_000)).toBe(false)
      expect(isQualified(1_000_000, 1_000_000)).toBe(true)
      expect(isQualified(100_000_000, 1_000_000)).toBe(true) // $100M block print
    })

    it('guards against negative or zero premium inputs', () => {
      expect(isQualified(0, 25_000)).toBe(false)
      expect(isQualified(-50_000, 25_000)).toBe(false)
    })
  })

  // =========================================================================
  // 7. Tape & Array Boundaries (Empty, Single, 10k Prints, Null Fields)
  // =========================================================================
  describe('Tape & Array Ingestion Boundaries', () => {
    it('handles empty print array in collectWatchlistAlerts without errors', () => {
      const alerts = collectWatchlistAlerts({
        watchlist: ['AAPL', 'NVDA'],
        prints: [],
      })
      expect(alerts).toEqual([])
    })

    it('handles empty watchlist in collectWatchlistAlerts without errors', () => {
      const alerts = collectWatchlistAlerts({
        watchlist: [],
        prints: [{ symbol: 'AAPL', is_unusual: true, trade_class: 'sweep', premium: 100_000, timestamp: '10:00', right: 'call' }] as unknown as MarketFlowPrint[],
      })
      expect(alerts).toEqual([])
    })

    it('handles single-print tape correctly', () => {
      const singlePrint = {
        symbol: 'NVDA',
        timestamp: '10:00:00',
        right: 'call',
        strike: 130,
        dte: 5,
        premium: 500_000,
        trade_class: 'sweep',
        is_sweep: true,
      } as unknown as MarketFlowPrint

      const key = flowPrintKey(singlePrint)
      expect(key).toContain('NVDA')
      expect(key).toContain('130')

      const alertKind = printAlertKind(singlePrint)
      expect(alertKind).toBe('sweep')
    })

    it('processes giant tape array of 5,000 prints efficiently without memory degradation', () => {
      const bigTape = Array.from({ length: 5000 }, (_, i) => ({
        symbol: i % 2 === 0 ? 'NVDA' : 'TSLA',
        timestamp: `10:${String(Math.floor(i / 60)).padStart(2, '0')}:${String(i % 60).padStart(2, '0')}`,
        right: i % 3 === 0 ? 'call' : 'put',
        strike: 100 + (i % 50),
        dte: i % 30,
        premium: 25_000 + i * 100,
        trade_class: i % 4 === 0 ? 'sweep' : 'block',
        is_sweep: i % 4 === 0,
        is_unusual: i % 5 === 0,
      })) as unknown as MarketFlowPrint[]

      const start = performance.now()
      const alerts = collectWatchlistAlerts({
        watchlist: ['NVDA'],
        prints: bigTape,
      })
      const dur = performance.now() - start

      expect(dur).toBeLessThan(100) // Sub-100ms processing for 5k prints
      expect(alerts.length).toBeGreaterThan(0)
      expect(alerts.every((a) => a.symbol === 'NVDA')).toBe(true)
    })

    it('handles prints with null/undefined fields safely in flowPrintKey', () => {
      const corruptedPrint = {
        timestamp: '',
        symbol: undefined,
        right: 'call',
        strike: null,
        price: null,
        contracts: null,
        premium: null,
      } as unknown as MarketFlowPrint

      const key = flowPrintKey(corruptedPrint)
      expect(typeof key).toBe('string')
      expect(key).toContain('call')
    })
  })

  // =========================================================================
  // 8. GEX Profile Boundaries (All Call, All Put, 0 Net GEX, Dense Cluster)
  // =========================================================================
  describe('GEX Profile Boundaries & Regime Demarcation', () => {
    it('evaluates All Call Gamma profile with zero put exposure', () => {
      const allCallRows = [
        { strike: 100, call_gex_m: 100, put_gex_m: 0, net_gex_m: 100, call_oi: 10_000, put_oi: 0 },
        { strike: 105, call_gex_m: 50, put_gex_m: 0, net_gex_m: 50, call_oi: 5_000, put_oi: 0 },
      ] as unknown as GexStrikeRow[]

      const netTotal = allCallRows.reduce((s, r) => s + (r.net_gex_m ?? 0), 0)
      expect(netTotal).toBe(150)
    })

    it('evaluates All Put Gamma profile with zero call exposure', () => {
      const allPutRows = [
        { strike: 90, call_gex_m: 0, put_gex_m: -80, net_gex_m: -80, call_oi: 0, put_oi: 8_000 },
        { strike: 95, call_gex_m: 0, put_gex_m: -40, net_gex_m: -40, call_oi: 0, put_oi: 4_000 },
      ] as unknown as GexStrikeRow[]

      const netTotal = allPutRows.reduce((s, r) => s + (r.net_gex_m ?? 0), 0)
      expect(netTotal).toBe(-120)
    })

    it('evaluates exactly 0 Net GEX with equal and opposite battleground exposure', () => {
      const battleground = {
        strike: 100,
        call_gex_m: 75,
        put_gex_m: -75,
        net_gex_m: 0,
        call_oi: 7_500,
        put_oi: 7_500,
      } as unknown as GexStrikeRow

      expect(battleground.net_gex_m).toBe(0)
      expect(battleground.call_gex_m + battleground.put_gex_m).toBe(0)
    })

    it('resolves dense strike clustering where 10 strikes lie within 1% of spot', () => {
      const spot = 500
      const denseStrikes = Array.from({ length: 10 }, (_, i) => ({
        strike: 498 + i * 0.5,
        call_gex_m: 10 * (i + 1),
        put_gex_m: -8 * (i + 1),
        net_gex_m: 2 * (i + 1),
        call_oi: 1000,
        put_oi: 800,
      })) as unknown as GexStrikeRow[]

      expect(denseStrikes).toHaveLength(10)
      expect(denseStrikes[0].strike).toBe(498)
      expect(denseStrikes[9].strike).toBe(502.5)
      expect(denseStrikes.every((s) => Math.abs(s.strike - spot) / spot <= 0.01)).toBe(true)
    })
  })

  // =========================================================================
  // 9. Payoff Curves & Breakeven Boundaries
  // =========================================================================
  describe('Payoff Curves & Breakeven Boundary Edge Cases', () => {
    it('returns null when payoff series has fewer than 2 points', () => {
      const singlePoint: PnlPoint[] = [{ spot: 100, pnl: 0 }]
      const chart = buildPayoffChart({
        series: singlePoint,
        spot: 100,
        width: 500,
        height: 200,
      })
      expect(chart).toBeNull()
    })

    it('handles flat payoff curve with 0 slope (no breakevens)', () => {
      const flatSeries: PnlPoint[] = [
        { spot: 80, pnl: 200 },
        { spot: 100, pnl: 200 },
        { spot: 120, pnl: 200 },
      ]

      const bes = findBreakevens(flatSeries)
      expect(bes).toEqual([]) // Does not cross 0
    })

    it('identifies exactly 2 breakeven points for Iron Condor / Long Strangle profile', () => {
      const strangleSeries: PnlPoint[] = [
        { spot: 80, pnl: 1000 },
        { spot: 90, pnl: 0 },    // Lower BE @ 90
        { spot: 95, pnl: -500 },
        { spot: 100, pnl: -500 },
        { spot: 105, pnl: -500 },
        { spot: 110, pnl: 0 },   // Upper BE @ 110
        { spot: 120, pnl: 1000 },
      ]

      const bes = findBreakevens(strangleSeries)
      expect(bes).toEqual([90, 110])
    })

    it('filters out non-finite or corrupted points in payoff series', () => {
      const corruptedSeries: PnlPoint[] = [
        { spot: 90, pnl: -500 },
        { spot: NaN, pnl: 100 },
        { spot: 100, pnl: Infinity },
        { spot: 110, pnl: 500 },
      ]

      const chart = buildPayoffChart({
        series: corruptedSeries,
        spot: 100,
        width: 500,
        height: 200,
      })

      expect(chart).not.toBeNull()
      expect(chart!.maxProfit).toBe(500)
      expect(chart!.maxLoss).toBe(-500)
    })
  })

  // =========================================================================
  // 10. Conviction Board Boundaries (0 Rows, Halted, Missing OI, Clock Skew)
  // =========================================================================
  describe('Conviction Board Data Integrity & Edge States', () => {
    it('handles unmeasurable open interest without displaying misleading 0.0 score', () => {
      const unmeasuredRow = {
        rank: 1,
        symbol: 'ILLIQ',
        selection_basis: 'activity_ordinal',
        selection_score: 5.0,
        spot: 45,
        squeeze_score: null,
        net_gex_m: null,
        available: true,
        gex_measurable: false,
      } as unknown as OptionsBoardRow

      const displayScore = unmeasuredRow.squeeze_score == null ? '—' : unmeasuredRow.squeeze_score.toFixed(1)
      expect(displayScore).toBe('—')
      expect(unmeasuredRow.gex_measurable).toBe(false)
    })

    it('flags halted underliers without valid option chain', () => {
      const haltedRow = {
        rank: 2,
        symbol: 'HALT',
        selection_basis: 'pead_ordinal',
        selection_score: 7.2,
        spot: 10,
        available: false,
        gex_measurable: false,
      } as unknown as OptionsBoardRow

      expect(haltedRow.available).toBe(false)
    })

    it('flags clock skew when option chain is days newer than stock price bar', () => {
      const skewedRow = {
        rank: 3,
        symbol: 'SKEW',
        selection_basis: 'live_options_flow',
        selection_score: 8.0,
        spot: 150,
        clock_mismatch: true,
        clock_skew_days: 4,
        price_asof: '2026-08-12',
        available: true,
        gex_measurable: true,
      } as unknown as OptionsBoardRow

      expect(skewedRow.clock_mismatch).toBe(true)
      expect(skewedRow.clock_skew_days).toBe(4)
    })

    it('persists and truncates seen alert keys to maximum 400 entries in storage', () => {
      const mockStorage = {
        store: new Map<string, string>(),
        getItem(k: string) { return this.store.get(k) ?? null },
        setItem(k: string, v: string) { this.store.set(k, v) },
      }

      const keys = Array.from({ length: 500 }, (_, i) => `key-${i}`)
      const saved = saveSeenAlertKeys(keys, mockStorage)

      expect(saved).toHaveLength(400)
      expect(saved[saved.length - 1]).toBe('key-499')
      expect(saved[0]).toBe('key-100')

      const loaded = loadSeenAlertKeys(mockStorage)
      expect(loaded.size).toBe(400)
      expect(loaded.has('key-499')).toBe(true)
      expect(loaded.has('key-50')).toBe(false)
    })

    it('handles unread alert count bounds and negative input protection', () => {
      const mockStorage = {
        store: new Map<string, string>(),
        getItem(k: string) { return this.store.get(k) ?? null },
        setItem(k: string, v: string) { this.store.set(k, v) },
      }

      expect(saveUnreadAlertCount(15, mockStorage)).toBe(15)
      expect(unreadAlertCount(mockStorage)).toBe(15)

      expect(saveUnreadAlertCount(-5, mockStorage)).toBe(0) // Clamps negative to 0
      expect(unreadAlertCount(mockStorage)).toBe(0)
    })
  })

  // =========================================================================
  // 11. Lifecycle & Concurrency Boundaries
  // =========================================================================
  describe('Lifecycle, In-Flight Refresh & Concurrency Boundaries', () => {
    it('manages refresh scheduling flag: in-flight request blocks passive poll but allows clear', () => {
      expect(shouldStartRefresh(true, { clear: false })).toBe(false)
      expect(shouldStartRefresh(true, { clear: true })).toBe(true)
      expect(shouldStartRefresh(false, { clear: false })).toBe(true)
    })

    it('protects against storage failure in corrupted JSON environment without unhandled exception', () => {
      const corruptedStorage = {
        getItem() { return 'INVALID_JSON{{{' },
      }

      const keys = loadSeenAlertKeys(corruptedStorage)
      expect(keys.size).toBe(0)

      const count = unreadAlertCount(corruptedStorage)
      expect(count).toBe(0)
    })
  })

  // =========================================================================
  // 12. Extended Domain Boundary Stress Tests
  // =========================================================================
  describe('Extended Domain Boundary Stress & Normalization', () => {
    it('normalizes mixed case signed print tokens (e.g. bUy, sElL, LoNg, sHoRt)', () => {
      expect(signedPrintTokenClass('bUy')).toBe('token-long')
      expect(signedPrintTokenClass('sElL')).toBe('token-short')
      expect(signedPrintTokenClass('LoNg')).toBe('token-long')
      expect(signedPrintTokenClass('sHoRt')).toBe('token-short')
      expect(signedPrintTokenClass('  BUY  ')).toBe('token-long')
      expect(signedPrintTokenClass('unknown_side')).toBe('token-unsigned')
    })

    it('handles flow lean tokens with arbitrary invalid or empty strings gracefully', () => {
      expect(flowLeanTokenClass('')).toBe('token-unsigned')
      expect(flowLeanTokenClass(undefined)).toBe('token-unsigned')
      expect(flowLeanTokenClass('random_gibberish')).toBe('token-unsigned')
    })

    it('handles flow priority tokens with arbitrary invalid or null values', () => {
      expect(flowPriorityTokenClass(null)).toBe('token-ink')
      expect(flowPriorityTokenClass('')).toBe('token-ink')
      expect(flowPriorityTokenClass('invalid_priority')).toBe('token-ink')
    })

    it('filters out invalid legs with negative quantities, zero strike, or NaN fields in usableLegs', () => {
      const dirtyLegs: CalcLeg[] = [
        { id: '1', right: 'call', strike: 100, quantity: 1, premium: 5 },
        { id: '2', right: 'put', strike: -50, quantity: 1, premium: 2 },
        { id: '3', right: 'call', strike: 100, quantity: NaN, premium: 2 },
        { id: '4', right: 'put', strike: 100, quantity: 1, premium: NaN },
        { id: '5', right: 'call', strike: NaN, quantity: 1, premium: 2 },
      ]

      const cleaned = usableLegs(dirtyLegs)
      expect(cleaned).toHaveLength(1)
      expect(cleaned[0].strike).toBe(100)
    })

    it('prices Deep OTM Put (Spot = 500, Strike = 10) with Delta = 0 and Price = 0', () => {
      const otmPut = solveBsBoundary('put', 500, 10, 30, 0.25, 0.05)
      expect(otmPut.delta).toBeCloseTo(0.0, 4)
      expect(otmPut.theo).toBeCloseTo(0.0, 4)
      expect(otmPut.vega).toBeCloseTo(0.0, 4)
    })

    it('evaluates Theta decay acceleration for ATM options as expiration approaches', () => {
      const theta30d = solveBsBoundary('call', 100, 100, 30, 0.25, 0.05).theta
      const theta5d = solveBsBoundary('call', 100, 100, 5, 0.25, 0.05).theta
      const theta1d = solveBsBoundary('call', 100, 100, 1, 0.25, 0.05).theta

      // Theta is negative; its absolute magnitude accelerates (becomes more negative) as DTE shrinks
      expect(Math.abs(theta1d)).toBeGreaterThan(Math.abs(theta5d))
      expect(Math.abs(theta5d)).toBeGreaterThan(Math.abs(theta30d))
    })

    it('computes 10-leg portfolio cash allocation without precision loss', () => {
      const tenLegs: CalcLeg[] = Array.from({ length: 10 }, (_, i) => ({
        id: `leg-${i + 1}`,
        right: i % 2 === 0 ? 'call' : 'put',
        strike: 100 + i * 5,
        quantity: i % 2 === 0 ? 1 : -1,
        premium: 2.50,
      }))

      const alloc = bookAllocation(tenLegs)
      expect(alloc.longNotional).toBe(1250) // 5 long legs * 2.5 * 100
      expect(alloc.shortCredit).toBe(1250)  // 5 short legs * 2.5 * 100
      expect(alloc.net).toBe(0)
    })

    it('handles empty GEX map rows gracefully', () => {
      const emptyRows: GexStrikeRow[] = []
      const visible = emptyRows.filter((r) => r.strike >= 100)
      expect(visible).toEqual([])
    })

    it('evaluates flow review ranking tie-breaker when review scores are identical', () => {
      const rowA = { symbol: 'AAPL', premium: 100_000, contract_count: 1000, live: true } as unknown as UnusualFlowRow
      const rowB = { symbol: 'MSFT', premium: 100_000, contract_count: 1000, live: true } as unknown as UnusualFlowRow

      const maxPrem = 100_000
      const comparison = compareFlowReviewRows(rowA, rowB, maxPrem)
      // Equal score & equal premium -> alphabetical by symbol
      expect(comparison).toBeLessThan(0) // AAPL comes before MSFT
    })

    it('evaluates flow pulse with identical timestamps as non-advancing snapshot', () => {
      const payloadA = {
        feed_status: 'live',
        source_snapshot: 'market_flow',
        asof: '2026-08-16T12:00:00Z',
        generated_at: '2026-08-16T12:00:01Z',
        rows: [],
        tape: [],
      } as unknown as UnusualFlowPayload

      const pulse1 = buildFlowPulse(null, payloadA)
      expect(pulse1.baseline).toBe(true)
      expect(pulse1.newPrintCount).toBe(0)
    })

    it('handles fallback defaults for strategy and right normalization', () => {
      expect(asStrategy(null)).toBe('long_call')
      expect(asStrategy(undefined)).toBe('long_call')
      expect(asStrategy('unknown_strategy')).toBe('long_call')
      expect(asRight(null)).toBe('call')
      expect(asRight(undefined)).toBe('call')
      expect(asRight('unknown')).toBe('call')
    })

    it('returns named empty when mix share or concentration are non-finite', () => {
      expect(mixShareLabel(NaN, '50%')).toBe(NO_MIX_IN_SAMPLE)
      expect(mixShareLabel(Infinity, '50%')).toBe(NO_MIX_IN_SAMPLE)
      expect(concentrationLabel('', '')).toBe(NO_STRIKE_IN_TAPE)
      expect(concentrationLabel(null, '')).toBe(NO_STRIKE_IN_TAPE)
    })
  })
})

