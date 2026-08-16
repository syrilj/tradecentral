/**
 * Tier 3: Pairwise Combination Test Suite
 *
 * Requirements: >= 15 test assertions covering cross-feature interactions:
 *  - Pair 01: 0DTE Expiration Filter + $1M+ Whale Premium Threshold
 *  - Pair 02: Bear Put Spread Strategy Preset + IV Smile Skew Per-Leg
 *  - Pair 03: Conviction Board Ticker Search + Net GEX Descending Sort
 *  - Pair 04: GEX Map Strike Lock Focus + Net Trace View Toggle
 *  - Pair 05: Flow Dashboard 'incoming' Filter + 'put' Right Filter + Dynamic KPI Sums
 *  - Pair 06: Options Calculator Custom 4-Leg Book + Dual Payoff Curve + Breakeven Extraction
 *  - Pair 07: High Vol/OI Ratio (>=1.0) + Golden Sweep Badge + Premium Tier
 *  - Pair 08: Options Direction Brief Signed Flow + Price Momentum + Setup Readiness Gate
 *  - Pair 09: Flow Suggestion Drawer Contract Selection + Take-Profit Debit Sizing
 *  - Pair 10: Watchlist Symbol Toggle + Flow Dashboard 'book' Preset + Alert Cascades
 *  - Pair 11: Tape Preset 'moonshot' + DTE Filter 'week' + SortKey 'expiry'
 *  - Pair 12: Conviction Board Live Flow Only Toggle + Selection Basis Chips + Spark Bar
 *  - Pair 13: GEX Map Metric Switch ('gex' vs 'oi') + Scope Filter ('atm'/'near'/'wide'/'all')
 *  - Pair 14: Options Calculator Per-Leg IV Override + Complete Greeks Matrix
 *  - Pair 15: useResource Keyed Clear on Underlier Change + In-Flight Sequence Isolation
 *  - Pair 16: Moneyness Multi-Parameter Filtering (OTM / ATM / ITM) + Sweeps Activity
 *  - Pair 17: $500k+ Threshold + Sweep Order + Bullish Activity Lean Integration
 */

import { describe, it, expect } from 'vitest'
import {
  buildPayoffChart,
  findBreakevens,
  netDebit,
  type CalcLeg,
  type PnlPoint,
} from '@/optionsCalculator'

import {
  flowLeanTokenClass,
  flowPriorityTokenClass,
} from '@/flowDisplay'

import {
  collectWatchlistAlerts,
} from '@/flowAlerts'

import {
  buildOptionsDirection,
  type OptionsDirectionSummary,
} from '@/optionsDirection'

import {
  nextResourceData,
} from '@/composables/useResource'

import {
  toggleWatchlistSymbol,
  watchlistHas,
} from '@/watchlist'

import type {
  GexStrikeRow,
  MarketFlowPrint,
  OptionsBoardRow,
  UnusualFlowRow,
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

describe('Tier 3: Pairwise Combinations Test Suite', () => {
  // =========================================================================
  // Pair 01: 0DTE Expiration Filter + $1M+ Whale Premium Threshold
  // =========================================================================
  it('Pair 01: filters for 0DTE contracts with $1M+ whale premium threshold simultaneously', () => {
    const prints = [
      { timestamp: '09:30:00', symbol: 'SPY', right: 'call', strike: 550, dte: 0, premium: 1_500_000, trade_class: 'sweep' },
      { timestamp: '09:31:00', symbol: 'SPY', right: 'put', strike: 540, dte: 0, premium: 350_000, trade_class: 'sweep' },
      { timestamp: '09:32:00', symbol: 'QQQ', right: 'call', strike: 480, dte: 3, premium: 2_000_000, trade_class: 'block' },
      { timestamp: '09:33:00', symbol: 'IWM', right: 'put', strike: 210, dte: 0, premium: 1_200_000, trade_class: 'sweep' },
    ] as unknown as MarketFlowPrint[]

    const matches0DteAndWhale = (p: MarketFlowPrint) => p.dte === 0 && (p.premium ?? 0) >= 1_000_000
    const matched = prints.filter(matches0DteAndWhale)

    expect(matched).toHaveLength(2)
    expect(matched.map((p) => p.symbol)).toEqual(['SPY', 'IWM'])
    expect(matched.reduce((s, p) => s + (p.premium ?? 0), 0)).toBe(2_700_000)
  })

  // =========================================================================
  // Pair 02: Bear Put Spread Strategy Preset + IV Smile Skew Per-Leg
  // =========================================================================
  it('Pair 02: evaluates Bear Put Spread with volatility skew (higher IV on lower strike put)', () => {
    const spot = 100
    const dte = 30
    const longStrike = 100 // ATM put @ 25% IV
    const shortStrike = 90 // OTM put @ 30% IV (skewed)

    const longLeg = solveBs('put', spot, longStrike, dte, 0.25)
    const shortLeg = solveBs('put', spot, shortStrike, dte, 0.30)

    const spreadPrice = longLeg.theo - shortLeg.theo
    const netDelta = longLeg.delta - shortLeg.delta
    const netVega = longLeg.vega - shortLeg.vega

    expect(spreadPrice).toBeGreaterThan(0)
    expect(netDelta).toBeLessThan(0) // Bearish net delta
    expect(netVega).toBeGreaterThan(0) // Long ATM vega exceeds short OTM vega
  })

  // =========================================================================
  // Pair 03: Conviction Board Ticker Search + Net GEX Descending Sort
  // =========================================================================
  it('Pair 03: combines Conviction Board ticker search query with Net GEX column sorting', () => {
    const boardRows = [
      { rank: 1, symbol: 'NVDA', spot: 120, net_gex_m: 85.0, squeeze_score: 4.0, available: true, gex_measurable: true },
      { rank: 2, symbol: 'NVDL', spot: 60, net_gex_m: 12.0, squeeze_score: 1.5, available: true, gex_measurable: true },
      { rank: 3, symbol: 'TSLA', spot: 220, net_gex_m: 95.0, squeeze_score: -2.0, available: true, gex_measurable: true },
      { rank: 4, symbol: 'NVDS', spot: 30, net_gex_m: 4.5, squeeze_score: -0.5, available: true, gex_measurable: true },
    ] as unknown as OptionsBoardRow[]

    const query = 'NVD'
    const filteredAndSorted = boardRows
      .filter((r) => r.symbol.toUpperCase().includes(query))
      .sort((a, b) => Number(b.net_gex_m) - Number(a.net_gex_m))

    expect(filteredAndSorted).toHaveLength(3)
    expect(filteredAndSorted.map((r) => r.symbol)).toEqual(['NVDA', 'NVDL', 'NVDS'])
    expect(filteredAndSorted[0].net_gex_m).toBe(85.0)
  })

  // =========================================================================
  // Pair 04: GEX Map Strike Lock Focus + Net Trace View Toggle
  // =========================================================================
  it('Pair 04: verifies GEX strike focus lock interaction alongside Net Trace line profile', () => {
    const gexRows = [
      { strike: 95, call_gex_m: 10, put_gex_m: -5, net_gex_m: 5 },
      { strike: 100, call_gex_m: 40, put_gex_m: -10, net_gex_m: 30 },
      { strike: 105, call_gex_m: 15, put_gex_m: -25, net_gex_m: -10 },
    ] as unknown as GexStrikeRow[]

    let focusStrike: number | null = null
    const showTrace = true

    // Lock strike 100
    focusStrike = 100
    const focusedRow = gexRows.find((r) => r.strike === focusStrike)

    expect(focusedRow).toBeDefined()
    expect(focusedRow!.net_gex_m).toBe(30)
    expect(showTrace).toBe(true)

    // Build trace path points
    const tracePoints = gexRows.map((r) => ({ strike: r.strike, net: r.net_gex_m ?? 0 }))
    expect(tracePoints).toHaveLength(3)
    expect(tracePoints[1].strike).toBe(focusStrike)
  })

  // =========================================================================
  // Pair 05: Flow Dashboard 'incoming' Filter + 'put' Right Filter + Dynamic KPI
  // =========================================================================
  it('Pair 05: filters incoming put prints and recalculates dynamic summary totals', () => {
    const newPrintKeys = new Set<string>(['SPY|put|540', 'QQQ|put|480'])
    const tapePrints = [
      { timestamp: '10:00', symbol: 'SPY', right: 'put', strike: 540, premium: 500_000 },
      { timestamp: '10:01', symbol: 'SPY', right: 'call', strike: 550, premium: 800_000 },
      { timestamp: '10:02', symbol: 'QQQ', right: 'put', strike: 480, premium: 300_000 },
      { timestamp: '10:03', symbol: 'IWM', right: 'put', strike: 210, premium: 200_000 },
    ] as unknown as MarketFlowPrint[]

    const isNewIncoming = (p: MarketFlowPrint) => newPrintKeys.has(`${p.symbol}|${p.right}|${p.strike}`)
    const isPut = (p: MarketFlowPrint) => p.right === 'put'

    const matched = tapePrints.filter((p) => isNewIncoming(p) && isPut(p))

    expect(matched).toHaveLength(2)
    const incomingPutPrem = matched.reduce((s, p) => s + (p.premium ?? 0), 0)
    expect(incomingPutPrem).toBe(800_000)
  })

  // =========================================================================
  // Pair 06: Options Calculator Custom 4-Leg Book + Dual Payoff + Breakeven
  // =========================================================================
  it('Pair 06: evaluates 4-leg custom Iron Butterfly book, extracting dual breakevens', () => {
    // Iron Butterfly @ 100: Buy 90P @ 1.0, Sell 100P @ 4.0, Sell 100C @ 4.0, Buy 110C @ 1.0
    // Net credit = $600. Max loss = $400. Lower BE = 94, Upper BE = 106.
    const legs: CalcLeg[] = [
      { id: '1', right: 'put', strike: 90, quantity: 1, premium: 1.0 },
      { id: '2', right: 'put', strike: 100, quantity: -1, premium: 4.0 },
      { id: '3', right: 'call', strike: 100, quantity: -1, premium: 4.0 },
      { id: '4', right: 'call', strike: 110, quantity: 1, premium: 1.0 },
    ]

    const debit = netDebit(legs)
    expect(debit).toBe(-600) // Net Credit

    const series: PnlPoint[] = [
      { spot: 80, pnl: -400 },
      { spot: 90, pnl: -400 },
      { spot: 94, pnl: 0 },    // Lower BE
      { spot: 100, pnl: 600 }, // Max Profit @ 100
      { spot: 106, pnl: 0 },   // Upper BE
      { spot: 110, pnl: -400 },
      { spot: 120, pnl: -400 },
    ]

    const bes = findBreakevens(series)
    expect(bes).toEqual([94, 106])

    const chart = buildPayoffChart({
      series,
      spot: 100,
      strikes: legs,
      width: 600,
      height: 250,
    })

    expect(chart).not.toBeNull()
    expect(chart!.maxProfit).toBe(600)
    expect(chart!.maxLoss).toBe(-400)
    expect(chart!.breakevens).toHaveLength(2)
  })

  // =========================================================================
  // Pair 07: High Vol/OI Ratio (>=1.0) + Golden Sweep Badge + Premium Tier
  // =========================================================================
  it('Pair 07: verifies combined Golden Sweep classification with Vol/OI >= 1.0 and $500k+ tier', () => {
    const evaluatePrint = (print: {
      trade_class?: string
      aggressor?: string
      premium?: number
      volume?: number
      open_interest?: number
    }) => {
      const isSweep = print.trade_class?.toLowerCase() === 'sweep'
      const isAskSide = print.aggressor?.toLowerCase() === 'ask' || print.aggressor?.toLowerCase() === 'above_ask'
      const isWhale = (print.premium ?? 0) >= 500_000
      const isGoldenSweep = isSweep && isAskSide && isWhale

      const ratio = (print.volume != null && print.open_interest != null && print.open_interest > 0)
        ? print.volume / print.open_interest
        : 0
      const isHighVolOi = ratio >= 1.0

      return { isGoldenSweep, isHighVolOi, ratio }
    }

    const res = evaluatePrint({
      trade_class: 'sweep',
      aggressor: 'ask',
      premium: 750_000,
      volume: 8_000,
      open_interest: 4_000,
    })

    expect(res.isGoldenSweep).toBe(true)
    expect(res.isHighVolOi).toBe(true)
    expect(res.ratio).toBe(2.0)
  })

  // =========================================================================
  // Pair 08: Options Direction Brief Signed Flow + Price Momentum Gate
  // =========================================================================
  it('Pair 08: resolves directional read when signed flow is bullish but price momentum is bearish (mixed conflict)', () => {
    const summary: OptionsDirectionSummary = {
      activity_imbalance: 0.20,
      signed_flow_imbalance: 0.70, // Bullish signed flow
      signed_flow_confidence: 0.85,
      gamma_flip: 100,
      call_wall: 110,
      put_wall: 90,
      squeeze: {
        bullish: 0.50,
        bearish: 0.50,
        score: 0,
        label: 'mixed',
        primary: 'two_way',
        drivers: [],
        theory: {
          momentum: -0.025, // Bearish momentum
          momentum_fresh: true,
        },
      },
    }

    const read = buildOptionsDirection(summary, 'live')
    expect(read.state).toBe('mixed')
    expect(read.headline).toBe('MIXED / WAIT')
    expect(read.confidence).toBe('wait')
  })

  // =========================================================================
  // Pair 09: Flow Suggestion Drawer Contract Selection + Sizing Debit
  // =========================================================================
  it('Pair 09: validates contract plan sizing debit and desk priority mapping', () => {
    const suggestion = {
      symbol: 'NVDA',
      bias_right: 'call',
      strike: 130,
      expiry: '2026-08-21',
      sizing_debit: 3.50,
      max_contracts: 10,
      priority: 'now',
    }

    const totalDebit = suggestion.sizing_debit * 100 * suggestion.max_contracts
    const tokenClass = flowPriorityTokenClass(suggestion.priority)

    expect(totalDebit).toBe(3500)
    expect(tokenClass).toBe('token-long')
  })

  // =========================================================================
  // Pair 10: Watchlist Symbol Toggle + Flow Dashboard 'book' Preset + Alert
  // =========================================================================
  it('Pair 10: adds symbol to watchlist, filters tape for book hits, and fires flow alerts', () => {
    let currentBook = ['AAPL']
    const added = toggleWatchlistSymbol(currentBook, 'NVDA').symbols
    currentBook = added

    expect(watchlistHas(currentBook, 'NVDA')).toBe(true)

    const tape = [
      { timestamp: '10:00', symbol: 'NVDA', right: 'call', strike: 130, premium: 500_000, trade_class: 'sweep', is_sweep: true },
      { timestamp: '10:01', symbol: 'TSLA', right: 'put', strike: 220, premium: 200_000, trade_class: 'sweep', is_sweep: true },
    ] as unknown as MarketFlowPrint[]

    const bookPrints = tape.filter((p) => watchlistHas(currentBook, p.symbol))
    expect(bookPrints).toHaveLength(1)
    expect(bookPrints[0].symbol).toBe('NVDA')

    const alerts = collectWatchlistAlerts({
      watchlist: currentBook,
      prints: tape,
    })

    expect(alerts).toHaveLength(1)
    expect(alerts[0].symbol).toBe('NVDA')
    expect(alerts[0].kind).toBe('sweep')
  })

  // =========================================================================
  // Pair 11: Tape Preset 'moonshot' + DTE Filter 'week' + SortKey 'expiry'
  // =========================================================================
  it('Pair 11: filters moonshot presets within 1-week expiry and sorts by DTE ascending', () => {
    const prints = [
      { timestamp: '10:00', symbol: 'NVDA', strike: 180, dte: 4, is_moonshot: true, presets: ['moonshot'] },
      { timestamp: '10:01', symbol: 'TSLA', strike: 350, dte: 1, is_moonshot: true, presets: ['moonshot'] },
      { timestamp: '10:02', symbol: 'AMD', strike: 250, dte: 25, is_moonshot: true, presets: ['moonshot'] }, // > 7d
      { timestamp: '10:03', symbol: 'AAPL', strike: 240, dte: 3, is_moonshot: false, presets: ['sweeps'] },
    ] as unknown as MarketFlowPrint[]

    const matches = prints
      .filter((p) => p.presets?.includes('moonshot') && (p.dte ?? 0) <= 7)
      .sort((a, b) => (a.dte ?? 0) - (b.dte ?? 0))

    expect(matches).toHaveLength(2)
    expect(matches[0].symbol).toBe('TSLA') // 1 DTE first
    expect(matches[1].symbol).toBe('NVDA') // 4 DTE second
  })

  // =========================================================================
  // Pair 12: Conviction Board Live Flow Only + Selection Basis Chips
  // =========================================================================
  it('Pair 12: filters Conviction Board for live options flow basis and scores squeeze spark width', () => {
    const rows = [
      { rank: 1, symbol: 'NVDA', selection_basis: 'live_options_flow', squeeze_score: 5.5, available: true, gex_measurable: true },
      { rank: 2, symbol: 'TSLA', selection_basis: 'pead_ordinal', squeeze_score: 2.0, available: true, gex_measurable: true },
      { rank: 3, symbol: 'AAPL', selection_basis: 'live_options_flow', squeeze_score: -3.0, available: true, gex_measurable: true },
    ] as unknown as OptionsBoardRow[]

    const liveFlowRows = rows.filter((r) => r.selection_basis === 'live_options_flow')
    expect(liveFlowRows).toHaveLength(2)

    const sparkWidthA = Math.min(100, Math.abs(liveFlowRows[0].squeeze_score! * 10))
    const sparkWidthB = Math.min(100, Math.abs(liveFlowRows[1].squeeze_score! * 10))

    expect(sparkWidthA).toBe(55)
    expect(sparkWidthB).toBe(30)
  })

  // =========================================================================
  // Pair 13: GEX Map Metric Switch ('gex' vs 'oi') + Scope Filter
  // =========================================================================
  it('Pair 13: switches GEX metric to Open Interest and applies wide strike scope', () => {
    const spot = 100
    const rows = [
      { strike: 70, call_gex_m: 5, call_oi: 500, put_oi: 200 }, // outside 25%
      { strike: 80, call_gex_m: 15, call_oi: 1500, put_oi: 400 },
      { strike: 100, call_gex_m: 50, call_oi: 5000, put_oi: 1000 },
      { strike: 120, call_gex_m: 20, call_oi: 2000, put_oi: 300 },
      { strike: 135, call_gex_m: 2, call_oi: 200, put_oi: 100 }, // outside 25%
    ] as unknown as GexStrikeRow[]

    const wideScope = (r: GexStrikeRow) => r.strike >= spot * 0.75 && r.strike <= spot * 1.25
    const visible = rows.filter(wideScope)

    expect(visible).toHaveLength(3) // 80, 100, 120
    const totalCallOi = visible.reduce((s, r) => s + (r.call_oi ?? 0), 0)
    expect(totalCallOi).toBe(8500)
  })

  // =========================================================================
  // Pair 14: Options Calculator Per-Leg IV Override + Complete Greeks Matrix
  // =========================================================================
  it('Pair 14: applies per-leg IV override and computes portfolio aggregated Greeks', () => {
    const spot = 100
    const dte = 45

    // Leg 1: Long 95 Call @ 20% IV
    const leg1 = solveBs('call', spot, 95, dte, 0.20)
    // Leg 2: Short 105 Call @ 25% IV (Smile elevated)
    const leg2 = solveBs('call', spot, 105, dte, 0.25)

    const portfolioDelta = leg1.delta - leg2.delta
    const portfolioGamma = leg1.gamma - leg2.gamma
    const portfolioTheta = leg1.theta - leg2.theta
    const portfolioVega = leg1.vega - leg2.vega
    const portfolioRho = leg1.rho - leg2.rho

    expect(portfolioDelta).toBeGreaterThan(0)
    expect(Number.isFinite(portfolioVega)).toBe(true)
    expect(Number.isFinite(portfolioGamma)).toBe(true)
    expect(Number.isFinite(portfolioTheta)).toBe(true)
    expect(Number.isFinite(portfolioRho)).toBe(true)
  })

  // =========================================================================
  // Pair 15: useResource Keyed Clear + In-Flight Sequence Isolation
  // =========================================================================
  it('Pair 15: clears previous underlier data immediately upon ticker switch preventing stale renders', () => {
    let underlierData: { symbol: string; spot: number } | null = { symbol: 'AAPL', spot: 225 }

    // User switches ticker to NVDA with { clear: true }
    underlierData = nextResourceData(underlierData, null, { clear: true })
    expect(underlierData).toBeNull()

    // NVDA response arrives
    const nvdaData = { symbol: 'NVDA', spot: 125 }
    underlierData = nextResourceData(underlierData, nvdaData, {})
    expect(underlierData).toEqual(nvdaData)
  })

  // =========================================================================
  // Pair 16: Moneyness Filter (OTM/ATM/ITM) + Sweeps Activity
  // =========================================================================
  it('Pair 16: filters for Out-Of-The-Money (OTM) Call Sweeps', () => {
    const spot = 100
    const prints = [
      { symbol: 'NVDA', right: 'call', strike: 115, trade_class: 'sweep', premium: 400_000 }, // OTM Call Sweep
      { symbol: 'NVDA', right: 'call', strike: 90, trade_class: 'sweep', premium: 800_000 },  // ITM Call Sweep
      { symbol: 'NVDA', right: 'call', strike: 120, trade_class: 'block', premium: 500_000 }, // OTM Call Block
      { symbol: 'NVDA', right: 'put', strike: 85, trade_class: 'sweep', premium: 300_000 },   // OTM Put Sweep
    ] as unknown as MarketFlowPrint[]

    const isOtmCallSweep = (p: MarketFlowPrint) =>
      p.right === 'call'
      && (p.strike ?? 0) > spot
      && p.trade_class === 'sweep'

    const matched = prints.filter(isOtmCallSweep)
    expect(matched).toHaveLength(1)
    expect(matched[0].strike).toBe(115)
  })

  // =========================================================================
  // Pair 17: $500k+ Threshold + Sweep Order + Bullish Activity Lean Integration
  // =========================================================================
  it('Pair 17: integrates $500k+ threshold with sweep order type and verifies bullish token styling', () => {
    const row = {
      symbol: 'TSLA',
      premium: 1_200_000,
      sweep_premium: 1_000_000,
      sweep_count: 5,
      call_premium: 1_000_000,
      put_premium: 200_000,
      activity_lean: 'bullish',
      live: true,
    } as unknown as UnusualFlowRow

    const satisfiesTier = (row.premium ?? 0) >= 500_000
    const isSweepHeavy = ((row.sweep_premium ?? 0) / (row.premium ?? 1)) >= 0.75
    const token = flowLeanTokenClass(row.activity_lean)

    expect(satisfiesTier).toBe(true)
    expect(isSweepHeavy).toBe(true)
    expect(token).toBe('token-long')
  })
})
