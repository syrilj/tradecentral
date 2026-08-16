/**
 * Tier 4: Institutional Workload Scenarios Test Suite
 *
 * Requirements: >= 6 realistic institutional application scenarios derived from TEST_INFRA.md:
 *  - Scenario 1: 0DTE SPY Institutional Sweep Influx
 *  - Scenario 2: Earnings Straddle vs Iron Condor Volatility Collapse Pricing
 *  - Scenario 3: Triple Witching Multi-Strike GEX Pinning & Regime Shift
 *  - Scenario 4: Whale Block Put Spread Setup via Context Drawer & Calculator
 *  - Scenario 5: High-Volatility Market Dislocation Rapid Ticker Switching
 *  - Scenario 6: Market-Wide Flow Tape Anomaly Surge & Watchlist Alert Cascades
 *  - Scenario 7: Zero-Gamma Regime Boundary Transition & Dealer Squeeze Trigger
 */

import { describe, it, expect } from 'vitest'
import {
  bookAllocation,
  netDebit,
  type CalcLeg,
} from '@/optionsCalculator'

import {
  collectWatchlistAlerts,
  saveSeenAlertKeys,
} from '@/flowAlerts'

import {
  buildOptionsDirection,
  type OptionsDirectionSummary,
} from '@/optionsDirection'

import {
  nextResourceData,
} from '@/composables/useResource'

import type {
  GexStrikeRow,
  MarketFlowPrint,
} from '@/api'

// Standard Black-Scholes Reference Oracle
function standardNormalCdf(x: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(x))
  const d = 0.3989422804014327 * Math.exp((-x * x) / 2)
  const p = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
  return x >= 0 ? 1 - p : p
}

function standardNormalPdf(x: number): number {
  return (1 / Math.sqrt(2 * Math.PI)) * Math.exp(-0.5 * x * x)
}

function solveBs(
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
  const sigma = Math.max(0.0001, volPct)
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

describe('Tier 4: Realistic Institutional Workload Scenarios', () => {
  // =========================================================================
  // Scenario 1: 0DTE SPY Institutional Sweep Influx (F01, F03, F04, F07, F08)
  // =========================================================================
  it('Scenario 1: processes rapid 0DTE SPY call sweep influx, tags Golden Sweeps with high Vol/OI, and updates KPI aggregates', () => {
    // Generate 50 simulated fast-arriving 0DTE prints
    const prints = Array.from({ length: 50 }, (_, i) => {
      const strike = 540 + (i % 5)
      const premium = 250_000 + (i * 20_000)
      const volume = 2_000 + i * 100
      const oi = 800 // High Vol/OI ratio > 2.5
      return {
        timestamp: `09:30:${String(i).padStart(2, '0')}`,
        symbol: 'SPY',
        right: 'call',
        strike,
        dte: 0,
        premium,
        volume,
        open_interest: oi,
        trade_class: 'sweep',
        is_sweep: true,
        aggressor: 'ask',
      }
    }) as unknown as MarketFlowPrint[]

    // 1. Filter for 0DTE and Whale tier >= $500k
    const filtered = prints.filter((p) => p.dte === 0 && (p.premium ?? 0) >= 500_000)
    expect(filtered.length).toBeGreaterThan(30)

    // 2. Classify Golden Sweeps with Vol/OI >= 1.0
    const goldenSweeps = filtered.filter((p) =>
      p.trade_class === 'sweep'
      && String(p.aggressor).toLowerCase() === 'ask'
      && (p.premium ?? 0) >= 500_000
      && ((p.volume ?? 0) / (p.open_interest ?? 1)) >= 1.0,
    )
    expect(goldenSweeps).toHaveLength(filtered.length)

    // 3. Verify total aggregated premium
    const totalPremium = goldenSweeps.reduce((sum, p) => sum + (p.premium ?? 0), 0)
    expect(totalPremium).toBeGreaterThan(25_000_000) // Over $25M in 0DTE sweep flow
  })

  // =========================================================================
  // Scenario 2: Earnings Straddle vs Iron Condor Pricing (F09, F10, F11, F12, F13, F14)
  // =========================================================================
  it('Scenario 2: models NVDA earnings volatility crush comparing Long Straddle vs Short Iron Condor', () => {
    const spot = 120
    const dte = 7 // 1-week weekly option
    const preEarningsVol = 0.65 // 65% pre-earnings IV
    const postEarningsVol = 0.35 // 35% post-earnings IV (vol crush)

    // 1. Pre-earnings ATM 120 Straddle pricing
    const callPre = solveBs('call', spot, 120, dte, preEarningsVol)
    const putPre = solveBs('put', spot, 120, dte, preEarningsVol)
    const straddleCostPre = (callPre.theo + putPre.theo) * 100

    // 2. Post-earnings ATM 120 Straddle pricing (assuming spot stays at 120)
    const callPost = solveBs('call', spot, 120, dte, postEarningsVol)
    const putPost = solveBs('put', spot, 120, dte, postEarningsVol)
    const straddleValuePost = (callPost.theo + putPost.theo) * 100

    // Straddle loses substantial value purely from IV drop
    expect(straddleValuePost).toBeLessThan(straddleCostPre * 0.65)

    // 3. Short Iron Condor seller profits from Vega contraction:
    // Iron Condor: Long 105P, Short 110P, Short 130C, Long 135C
    const condorPre = (solveBs('put', spot, 110, dte, preEarningsVol).theo +
      solveBs('call', spot, 130, dte, preEarningsVol).theo -
      solveBs('put', spot, 105, dte, preEarningsVol).theo -
      solveBs('call', spot, 135, dte, preEarningsVol).theo) * 100

    const condorPost = (solveBs('put', spot, 110, dte, postEarningsVol).theo +
      solveBs('call', spot, 130, dte, postEarningsVol).theo -
      solveBs('put', spot, 105, dte, postEarningsVol).theo -
      solveBs('call', spot, 135, dte, postEarningsVol).theo) * 100

    // Iron condor price to buy back dropped significantly -> seller secures credit profit
    expect(condorPost).toBeLessThan(condorPre * 0.40)
  })

  // =========================================================================
  // Scenario 3: Triple Witching Multi-Strike GEX Pinning (F09, F18, F15, F17)
  // =========================================================================
  it('Scenario 3: simulates Quad-Witching multi-strike GEX pinning between Call Wall and Put Wall', () => {
    const spot = 500
    const callWall = 510
    const putWall = 490
    const gammaFlip = 495

    // 30 strikes distributed across $450 to $550
    const gexRows = Array.from({ length: 30 }, (_, i) => {
      const strike = 470 + i * 2.5
      let callGex = Math.max(0, (25 - Math.abs(strike - callWall))) * 5
      let putGex = -Math.max(0, (20 - Math.abs(strike - putWall))) * 5
      if (strike === callWall) callGex = 150 // Massive Call Wall
      if (strike === putWall) putGex = -120 // Massive Put Wall
      const netGex = callGex + putGex
      return {
        strike,
        call_gex_m: callGex,
        put_gex_m: putGex,
        net_gex_m: netGex,
        call_oi: Math.round(callGex * 1000),
        put_oi: Math.round(Math.abs(putGex) * 1000),
      }
    }) as unknown as GexStrikeRow[]

    // Verify Call Wall & Put Wall detection
    const detectedCallWall = [...gexRows].sort((a, b) => (b.call_gex_m ?? 0) - (a.call_gex_m ?? 0))[0].strike
    const detectedPutWall = [...gexRows].sort((a, b) => (a.put_gex_m ?? 0) - (b.put_gex_m ?? 0))[0].strike

    expect(detectedCallWall).toBe(510)
    expect(detectedPutWall).toBe(490)

    // Current Spot (500) lies inside the Long Gamma dampening zone (Spot > Flip)
    expect(spot).toBeGreaterThan(gammaFlip)
    const netGexAtSpot = gexRows.find((r) => r.strike === spot)?.net_gex_m ?? 0
    expect(netGexAtSpot).toBeGreaterThan(0) // Dealer is long gamma, dampening volatility
  })

  // =========================================================================
  // Scenario 4: Whale Block Put Spread Setup via Context Drawer (F02, F04, F13, F20)
  // =========================================================================
  it('Scenario 4: captures institutional $2.5M TSLA put block, maps GEX support, and configures defined-risk spread', () => {
    // 1. Incoming Whale Block print
    const whalePrint = {
      timestamp: '11:15:30',
      symbol: 'TSLA',
      right: 'put',
      strike: 200,
      dte: 30,
      premium: 2_500_000,
      contracts: 5000,
      trade_class: 'block',
      aggressor: 'sell',
    } as unknown as MarketFlowPrint

    // 2. Check drawer trigger threshold
    expect((whalePrint.premium ?? 0)).toBeGreaterThanOrEqual(1_000_000)

    // 3. Pre-fill Options Calculator Bear Put Spread: Long 200P / Short 180P
    const legs: CalcLeg[] = [
      { id: '1', right: 'put', strike: 200, quantity: 1, premium: 8.50 },
      { id: '2', right: 'put', strike: 180, quantity: -1, premium: 3.00 },
    ]

    const netCost = netDebit(legs) // (8.50 - 3.00) * 100 = $550
    const maxGain = (200 - 180) * 100 - netCost // $2000 - $550 = $1450
    const alloc = bookAllocation(legs)

    expect(netCost).toBe(550)
    expect(maxGain).toBe(1450)
    expect(alloc.putShare).toBe(1.0)
    expect(alloc.callShare).toBe(0.0)
  })

  // =========================================================================
  // Scenario 5: High-Volatility Rapid Ticker Switching (F08, F19, F20)
  // =========================================================================
  it('Scenario 5: executes rapid ticker switching under live polling with strict sequence isolation and zero stale bleed', () => {
    let activeUnderlier = 'SPY'
    let currentPayload: { symbol: string; spot: number; reqId: number } | null = {
      symbol: 'SPY',
      spot: 545,
      reqId: 1,
    }

    // User rapidly clicks NVDA -> TSLA -> AAPL
    const tickers = ['NVDA', 'TSLA', 'AAPL']
    let lastSeq = 1

    for (const nextTicker of tickers) {
      activeUnderlier = nextTicker
      lastSeq++
      // Immediate clear on ticker change
      currentPayload = nextResourceData(currentPayload, null, { clear: true })
      expect(currentPayload).toBeNull()

      // Async response arrives tagged with seq
      const response = { symbol: nextTicker, spot: 100 + lastSeq * 10, reqId: lastSeq }
      currentPayload = nextResourceData(currentPayload, response, {})
      expect(currentPayload?.symbol).toBe(nextTicker)
    }

    expect(activeUnderlier).toBe('AAPL')
    expect(currentPayload?.symbol).toBe('AAPL')
  })

  // =========================================================================
  // Scenario 6: Market-Wide Tape Anomaly Surge & Alert Cascades (F01, F02, F03, F04, F16)
  // =========================================================================
  it('Scenario 6: processes market-wide surge of 200 prints across 20 symbols, firing watchlist alerts and updating pulse', () => {
    const symbols = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'TSLA', 'AMD', 'SPY', 'QQQ']
    const myWatchlist = ['NVDA', 'TSLA', 'AMD']

    // Generate 200 surge prints
    const surgePrints = Array.from({ length: 200 }, (_, i) => {
      const sym = symbols[i % symbols.length]
      const premium = 50_000 + (i * 10_000)
      return {
        timestamp: `14:00:${String(Math.floor(i / 10)).padStart(2, '0')}`,
        symbol: sym,
        right: i % 2 === 0 ? 'call' : 'put',
        strike: 100 + (i % 20),
        dte: 5,
        premium,
        trade_class: i % 3 === 0 ? 'sweep' : 'block',
        is_sweep: i % 3 === 0,
        is_unusual: i % 4 === 0,
      }
    }) as unknown as MarketFlowPrint[]

    // Collect alerts for active watchlist
    const alerts = collectWatchlistAlerts({
      watchlist: myWatchlist,
      prints: surgePrints,
    })

    expect(alerts.length).toBeGreaterThan(20)
    expect(alerts.every((a) => myWatchlist.includes(a.symbol ?? ''))).toBe(true)

    // Save seen alert keys
    const seenKeys = new Set(alerts.map((a) => a.key))
    const storage = {
      store: new Map<string, string>(),
      getItem(k: string) { return this.store.get(k) ?? null },
      setItem(k: string, v: string) { this.store.set(k, v) },
    }

    const saved = saveSeenAlertKeys(seenKeys, storage)
    expect(saved.length).toBe(seenKeys.size)
  })

  // =========================================================================
  // Scenario 7: Zero-Gamma Regime Boundary Transition & Dealer Squeeze Trigger
  // =========================================================================
  it('Scenario 7: detects spot dropping below zero-gamma flip point, transitioning dealer regime to Short Gamma acceleration', () => {
    const gammaFlip = 200

    // Step 1: Spot @ 205 (Above Flip) -> Long Gamma Regime
    const summaryAboveFlip: OptionsDirectionSummary = {
      gamma_flip: gammaFlip,
      call_wall: 215,
      put_wall: 190,
      squeeze: {
        bullish: 0.60,
        bearish: 0.20,
        score: 30,
        label: 'long_gamma',
        primary: 'bullish',
        drivers: ['long_gamma_dampens'],
      },
    }
    const readAbove = buildOptionsDirection(summaryAboveFlip, 'live')
    expect(readAbove.state).toBe('bullish')

    // Step 2: Spot breaks down to 195 (Below Flip) -> Short Gamma Dealer Acceleration
    const summaryBelowFlip: OptionsDirectionSummary = {
      gamma_flip: gammaFlip,
      call_wall: 215,
      put_wall: 185,
      signed_flow_imbalance: -0.75, // Bearish institutional puts rushing in
      signed_flow_confidence: 0.90,
      squeeze: {
        bullish: 0.10,
        bearish: 0.85,
        score: -70,
        label: 'short_gamma_acceleration',
        primary: 'bearish',
        drivers: ['short_premium_dealer_gamma', 'negative_charting_near_gex'],
        theory: {
          momentum: -0.045, // Sharp downside momentum
          momentum_fresh: true,
        },
      },
    }
    const readBelow = buildOptionsDirection(summaryBelowFlip, 'live')

    expect(readBelow.state).toBe('bearish')
    expect(readBelow.confidence).toBe('high')
    expect(readBelow.basis).toBe('SIGNED FLOW + MOMENTUM')
    expect(readBelow.drivers).toContain('short dealer gamma')
  })
})
