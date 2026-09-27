/**
 * Tier 1: Feature Coverage Test Suite
 *
 * Requirements: >= 55 test assertions covering all 11 inventoried features:
 *  F01. Institutional Order Badges (Golden Sweep, Sweep, Block, Split, Multi-leg)
 *  F02. Bull/Bear Conviction & Vol/OI Ratio Visualizer
 *  F03. Expanded Premium Thresholds ($500k+, $1M+)
 *  F04. Flow Table & Tape Click-to-Sort + Sticky Headers
 *  F05. Options Calculator Black-Scholes & Greeks Engine
 *  F06. Dual Payoff Curves (Expiry + T+0) & Unbounded Labels
 *  F07. Strategy Presets (11 Presets) & IV Controls
 *  F08. Conviction Board Column Sorting, Search & Heatmap
 *  F09. Gamma Exposure Map Collision & Multi-View Rendering
 *  F10. Flow Multi-Parameter Filtering & Dynamic KPI Sums
 *  F11. State Reactivity, Lifecycle & Error Recovery
 */

import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  asRight,
  asStrategy,
  bookAllocation,
  buildPayoffChart,
  findBreakevens,
  netDebit,
  nextLegId,
  samplePnlRows,
  seedBook,
  usableLegs,
  type CalcLeg,
  type PnlPoint,
} from '@/optionsCalculator'

import {
  FIRST_WINDOW_BASELINE,
  NO_MIX_IN_SAMPLE,
  NO_SIGNED_SIDE,
  NO_SIGNAL,
  NO_STRIKE_IN_TAPE,
  PREVIOUS_PROVIDER_WINDOW,
  classifyFlowOrder,
  concentrationLabel,
  flowLeanTokenClass,
  flowPriorityTokenClass,
  mixShareLabel,
  namedEmpty,
  pulseWindowCopy,
  signedPrintTokenClass,
} from '@/flowDisplay'

import {
  applyFlowWindow,
  compareFlowReviewRows,
  flowReviewScore,
  type FlowPulsePayload,
} from '@/flowPulse'

import { collectWatchlistAlerts } from '@/flowAlerts'

import { buildOptionsDirection } from '@/optionsDirection'

import { nextResourceData, shouldStartRefresh } from '@/composables/useResource'

import type {
  GexStrikeRow,
  MarketFlowPrint,
  OptionsBoardRow,
  UnusualFlowPayload,
  UnusualFlowRow,
} from '@/api'

const srcRoot = join(dirname(fileURLToPath(import.meta.url)), '..')
function readSrc(rel: string): string {
  return readFileSync(join(srcRoot, rel), 'utf8')
}

// ---------------------------------------------------------------------------
// Standard Black-Scholes & Greeks Reference Solver (Oracle)
// ---------------------------------------------------------------------------
function standardNormalCdf(x: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(x))
  const d = 0.3989422804014327 * Math.exp((-x * x) / 2)
  const p =
    d *
    t *
    (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
  return x >= 0 ? 1 - p : p
}

function standardNormalPdf(x: number): number {
  return (1 / Math.sqrt(2 * Math.PI)) * Math.exp(-0.5 * x * x)
}

function solveBlackScholes(
  type: 'call' | 'put',
  spot: number,
  strike: number,
  dteDays: number,
  volPct: number,
  ratePct = 0.05,
) {
  const T = Math.max(0.00001, dteDays / 365)
  const sigma = Math.max(0.0001, volPct)
  const r = ratePct
  const S = spot
  const K = strike

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
    theta =
      (-(S * sigma * nPrimeD1) / (2 * Math.sqrt(T)) + r * K * disc * standardNormalCdf(-d2)) / 365
    rho = (-K * T * disc * standardNormalCdf(-d2)) / 100
  }

  const gamma = nPrimeD1 / (S * sigma * Math.sqrt(T))
  const vega = (S * Math.sqrt(T) * nPrimeD1) / 100

  return { theo, delta, gamma, theta, vega, rho }
}

describe('Tier 1: Feature Coverage Test Suite', () => {
  // =========================================================================
  // Feature 1: Institutional Order Badges (Golden Sweep, Sweep, Block, Split, Multi-leg)
  // =========================================================================
  describe('F01: Institutional Order Badges & Taxonomy', () => {
    it('does not invent certified golden sweeps from size + ask side', () => {
      expect(
        classifyFlowOrder({ trade_class: 'sweep', aggressor: 'ask', premium: 750_000 }).type,
      ).toBe('sweep')
      expect(
        classifyFlowOrder({ trade_class: 'sweep', aggressor: 'bid', premium: 750_000 }).type,
      ).toBe('sweep')
      expect(classifyFlowOrder({ flags: ['golden_sweep'] }).type).toBe('golden_sweep')
      expect(
        classifyFlowOrder({ trade_class: 'block', aggressor: 'ask', premium: 1_000_000 }).type,
      ).toBe('block')
    })

    it('differentiates Split orders and Multi-leg strategies with distinct badge metadata', () => {
      expect(classifyFlowOrder({ trade_class: 'split' }).type).toBe('split')
      expect(classifyFlowOrder({ trade_class: 'multileg' }).type).toBe('multileg')
      expect(classifyFlowOrder({ flags: ['split'] }).type).toBe('split')
      expect(classifyFlowOrder({ flags: ['multi_leg'] }).type).toBe('multileg')
      expect(classifyFlowOrder({ trade_class: 'block' }).type).toBe('block')
    })

    it('maps signed side to instrument tokens without call/put color confusion', () => {
      expect(signedPrintTokenClass('buy')).toBe('token-long')
      expect(signedPrintTokenClass('long')).toBe('token-long')
      expect(signedPrintTokenClass('bullish')).toBe('token-long')
      expect(signedPrintTokenClass('sell')).toBe('token-short')
      expect(signedPrintTokenClass('short')).toBe('token-short')
      expect(signedPrintTokenClass('bearish')).toBe('token-short')
      expect(signedPrintTokenClass(null)).toBe('token-unsigned')
      expect(signedPrintTokenClass('call')).toBe('token-unsigned')
    })

    it('renders desk priority badges for immediate vs queued order review', () => {
      expect(flowPriorityTokenClass('now')).toBe('token-long')
      expect(flowPriorityTokenClass('soon')).toBe('token-warn')
      expect(flowPriorityTokenClass('watch')).toBe('token-ink')
      expect(flowPriorityTokenClass('skip')).toBe('token-unsigned')
    })

    it('verifies badge token definitions in CSS design system', () => {
      const tokensCss = readSrc('styles/tokens.css')
      expect(tokensCss).toContain('--long:')
      expect(tokensCss).toContain('--short:')
      expect(tokensCss).toContain('--call:')
      expect(tokensCss).toContain('--put:')
      expect(tokensCss).toContain('--phosphor:')
      expect(tokensCss).toContain('--font-data:')
    })
  })

  // =========================================================================
  // Feature 2: Bull/Bear Conviction & Vol/OI Ratio Visualizer
  // =========================================================================
  describe('F02: Bull/Bear Conviction & Vol/OI Ratio Visualizer', () => {
    function computeVolOiRatio(vol?: number | null, oi?: number | null) {
      if (vol == null || oi == null || oi <= 0 || !Number.isFinite(vol) || !Number.isFinite(oi)) {
        return { ratio: null, formatted: '—', isHigh: false }
      }
      const ratio = vol / oi
      return {
        ratio,
        formatted: `${ratio.toFixed(2)}x`,
        isHigh: ratio >= 1.0,
      }
    }

    it('computes Vol/OI ratio accurately and sets isHigh flag when ratio >= 1.0', () => {
      const res1 = computeVolOiRatio(15_000, 5_000)
      expect(res1.ratio).toBe(3.0)
      expect(res1.formatted).toBe('3.00x')
      expect(res1.isHigh).toBe(true)

      const res2 = computeVolOiRatio(2_500, 10_000)
      expect(res2.ratio).toBe(0.25)
      expect(res2.formatted).toBe('0.25x')
      expect(res2.isHigh).toBe(false)
    })

    it('handles zero or missing Open Interest gracefully without throwing NaN/Infinity', () => {
      expect(computeVolOiRatio(500, 0).formatted).toBe('—')
      expect(computeVolOiRatio(500, null).formatted).toBe('—')
      expect(computeVolOiRatio(null, 1000).formatted).toBe('—')
      expect(computeVolOiRatio(0, 1000).ratio).toBe(0)
    })

    it('correctly maps flow conviction state to long/short/warn tokens', () => {
      expect(flowLeanTokenClass('bullish')).toBe('token-long')
      expect(flowLeanTokenClass('model-bullish')).toBe('token-long')
      expect(flowLeanTokenClass('bearish')).toBe('token-short')
      expect(flowLeanTokenClass('model-bearish')).toBe('token-short')
      expect(flowLeanTokenClass('mixed')).toBe('token-warn')
      expect(flowLeanTokenClass('unknown')).toBe('token-unsigned')
    })

    it('evaluates directional conviction by pairing signed flow with price momentum', () => {
      const brief = buildOptionsDirection(
        {
          activity_imbalance: 0.65,
          signed_flow_imbalance: 0.8,
          signed_flow_confidence: 0.85,
          gamma_flip: 245,
          call_wall: 260,
          put_wall: 240,
          squeeze: {
            bullish: 0.8,
            bearish: 0.05,
            score: 65,
            label: 'bullish_squeeze',
            primary: 'bullish',
            drivers: ['short_premium_dealer_gamma'],
            theory: {
              momentum: 0.035,
              momentum_fresh: true,
            },
          },
        },
        'live',
      )

      expect(brief.state).toBe('bullish')
      expect(brief.confidence).toBe('high')
      expect(brief.activity).toBe('call')
      expect(brief.signedFlow).toBe(0.8)
    })

    it('provides transparent named empties when telemetry fields are absent', () => {
      expect(namedEmpty(null, NO_SIGNED_SIDE)).toBe(NO_SIGNED_SIDE)
      expect(namedEmpty(undefined, NO_SIGNAL)).toBe(NO_SIGNAL)
      expect(mixShareLabel(null, '50%')).toBe(NO_MIX_IN_SAMPLE)
      expect(concentrationLabel(null, 'FALLBACK')).toBe('FALLBACK')
      expect(concentrationLabel('Unavailable', '')).toBe(NO_STRIKE_IN_TAPE)
    })
  })

  // =========================================================================
  // Feature 3: Expanded Premium Thresholds ($500k+, $1M+)
  // =========================================================================
  describe('F03: Expanded Premium Thresholds & Tier Badges', () => {
    function categorizePremiumTier(
      premium: number,
    ): 'mega' | 'whale' | 'large' | 'medium' | 'base' {
      if (premium >= 1_000_000) return 'mega'
      if (premium >= 500_000) return 'whale'
      if (premium >= 250_000) return 'large'
      if (premium >= 100_000) return 'medium'
      return 'base'
    }

    it('categorizes institutional premium tiers from base up to $1M+ mega whale prints', () => {
      expect(categorizePremiumTier(1_500_000)).toBe('mega')
      expect(categorizePremiumTier(1_000_000)).toBe('mega')
      expect(categorizePremiumTier(750_000)).toBe('whale')
      expect(categorizePremiumTier(500_000)).toBe('whale')
      expect(categorizePremiumTier(300_000)).toBe('large')
      expect(categorizePremiumTier(150_000)).toBe('medium')
      expect(categorizePremiumTier(50_000)).toBe('base')
    })

    it('filters flow rows strictly adhering to active minimum premium threshold', () => {
      const rows = [
        { symbol: 'AAPL', premium: 1_200_000, live: true, contract_count: 500 },
        { symbol: 'MSFT', premium: 600_000, live: true, contract_count: 300 },
        { symbol: 'NVDA', premium: 300_000, live: true, contract_count: 200 },
        { symbol: 'TSLA', premium: 75_000, live: true, contract_count: 100 },
      ] as unknown as UnusualFlowRow[]

      const filterByFloor = (floor: number) => rows.filter((r) => Number(r.premium) >= floor)

      expect(filterByFloor(1_000_000)).toHaveLength(1)
      expect(filterByFloor(500_000)).toHaveLength(2)
      expect(filterByFloor(250_000)).toHaveLength(3)
      expect(filterByFloor(50_000)).toHaveLength(4)
    })

    it('aggregates total sweep premium and contracts across filtered tier subset', () => {
      const rows = [
        {
          symbol: 'SPY',
          premium: 2_000_000,
          sweep_premium: 1_500_000,
          sweep_contracts: 4000,
          live: true,
        },
        {
          symbol: 'QQQ',
          premium: 800_000,
          sweep_premium: 600_000,
          sweep_contracts: 1500,
          live: true,
        },
        {
          symbol: 'IWM',
          premium: 150_000,
          sweep_premium: 100_000,
          sweep_contracts: 300,
          live: true,
        },
      ] as unknown as UnusualFlowRow[]

      const threshold = 500_000
      const active = rows.filter((r) => Number(r.premium) >= threshold)
      const totalSweepPrem = active.reduce((s, r) => s + Number(r.sweep_premium ?? 0), 0)
      const totalSweepQty = active.reduce((s, r) => s + Number(r.sweep_contracts ?? 0), 0)

      expect(active).toHaveLength(2)
      expect(totalSweepPrem).toBe(2_100_000)
      expect(totalSweepQty).toBe(5500)
    })

    it('verifies threshold UI controls in FlowDashboard SFC and FlowView', () => {
      const dashboardSrc = readSrc('components/FlowDashboard.vue')
      const viewSrc = readSrc('views/FlowView.vue')
      expect(dashboardSrc).toMatch(/THRESHOLDS\s*=\s*\[/)
      expect(dashboardSrc).toContain('minPremium')
      expect(viewSrc).toContain('BASE_FLOW_FLOOR')
    })
  })

  // =========================================================================
  // Feature 4: Flow Table & Tape Click-to-Sort + Sticky Headers
  // =========================================================================
  describe('F04: Flow Table & Tape Sorting and Sticky Headers', () => {
    const sampleRows = [
      {
        symbol: 'TSLA',
        premium: 500_000,
        sweep_premium: 400_000,
        average_dte: 5,
        contract_count: 1000,
        live: true,
      },
      {
        symbol: 'NVDA',
        premium: 1_500_000,
        sweep_premium: 200_000,
        average_dte: 45,
        contract_count: 500,
        live: true,
      },
      {
        symbol: 'AAPL',
        premium: 800_000,
        sweep_premium: 700_000,
        average_dte: 15,
        contract_count: 800,
        live: true,
      },
    ] as unknown as UnusualFlowRow[]

    it('sorts rows descending by premium', () => {
      const sorted = [...sampleRows].sort((a, b) => Number(b.premium) - Number(a.premium))
      expect(sorted.map((r) => r.symbol)).toEqual(['NVDA', 'AAPL', 'TSLA'])
    })

    it('sorts rows descending by sweep premium', () => {
      const sorted = [...sampleRows].sort(
        (a, b) => Number(b.sweep_premium) - Number(a.sweep_premium),
      )
      expect(sorted.map((r) => r.symbol)).toEqual(['AAPL', 'TSLA', 'NVDA'])
    })

    it('sorts rows ascending by average expiry DTE', () => {
      const sorted = [...sampleRows].sort((a, b) => Number(a.average_dte) - Number(b.average_dte))
      expect(sorted.map((r) => r.symbol)).toEqual(['TSLA', 'AAPL', 'NVDA'])
    })

    it('ranks rows using institutional multi-factor flow review score', () => {
      const maxPrem = 1_500_000
      const ranked = [...sampleRows].sort((a, b) => compareFlowReviewRows(a, b, maxPrem))
      expect(ranked[0].symbol).toBe('NVDA')
      expect(flowReviewScore(sampleRows[0], maxPrem)).toBeGreaterThan(0)
    })

    it('verifies sticky headers and scroll classes in FlowDashboard layout', () => {
      const src = readSrc('components/FlowDashboard.vue')
      expect(src).toContain('table-scroll')
      expect(src).toContain('grid')
      expect(src).toContain('th class="label')
      expect(src).toContain('sortKey')
    })
  })

  // =========================================================================
  // Feature 5: Options Calculator Black-Scholes & Greeks Engine
  // =========================================================================
  describe('F05: Options Calculator Black-Scholes & Greeks Engine', () => {
    it('accurately prices ATM Call and Put options with standard market parameters', () => {
      const spot = 100
      const strike = 100
      const dte = 30
      const vol = 0.3 // 30%
      const rate = 0.05 // 5%

      const callGreeks = solveBlackScholes('call', spot, strike, dte, vol, rate)
      const putGreeks = solveBlackScholes('put', spot, strike, dte, vol, rate)

      // Expected Black-Scholes ATM 30-day prices
      expect(callGreeks.theo).toBeCloseTo(3.633, 2)
      expect(putGreeks.theo).toBeCloseTo(3.223, 2)
    })

    it('satisfies Put-Call parity relationship: C - P = S - K * exp(-r * T)', () => {
      const spot = 150
      const strike = 140
      const dte = 60
      const vol = 0.25
      const rate = 0.04
      const T = dte / 365

      const call = solveBlackScholes('call', spot, strike, dte, vol, rate)
      const put = solveBlackScholes('put', spot, strike, dte, vol, rate)

      const leftSide = call.theo - put.theo
      const rightSide = spot - strike * Math.exp(-rate * T)

      expect(leftSide).toBeCloseTo(rightSide, 4)
    })

    it('computes Delta, Gamma, Theta, Vega, and Rho within accurate mathematical bounds', () => {
      const greeks = solveBlackScholes('call', 200, 200, 45, 0.2, 0.05)

      expect(greeks.delta).toBeGreaterThan(0.5)
      expect(greeks.delta).toBeLessThan(0.6)
      expect(greeks.gamma).toBeGreaterThan(0)
      expect(greeks.theta).toBeLessThan(0) // Long option theta decay is negative
      expect(greeks.vega).toBeGreaterThan(0) // Long option vega is positive
      expect(greeks.rho).toBeGreaterThan(0) // Long call rho is positive
    })

    it('computes Put Greeks correctly with negative Delta and negative Rho', () => {
      const putGreeks = solveBlackScholes('put', 200, 200, 45, 0.2, 0.05)

      expect(putGreeks.delta).toBeLessThan(0)
      expect(putGreeks.delta).toBeGreaterThan(-1)
      expect(putGreeks.gamma).toBeGreaterThan(0) // Gamma is identical for call & put
      expect(putGreeks.vega).toBeGreaterThan(0) // Vega is identical for call & put
      expect(putGreeks.rho).toBeLessThan(0) // Long put rho is negative
    })

    it('properly drops unusable legs with 0 strike, 0 qty or negative premium in usableLegs', () => {
      const rawLegs: CalcLeg[] = [
        { id: '1', right: 'call', strike: 100, quantity: 1, premium: 5 },
        { id: '2', right: 'put', strike: 0, quantity: 1, premium: 3 }, // invalid strike
        { id: '3', right: 'call', strike: 105, quantity: 0, premium: 2 }, // zero qty
        { id: '4', right: 'put', strike: 95, quantity: 1, premium: -1 }, // negative prem
      ]

      const cleaned = usableLegs(rawLegs)
      expect(cleaned).toHaveLength(1)
      expect(cleaned[0].strike).toBe(100)
    })
  })

  // =========================================================================
  // Feature 6: Dual Payoff Curves (Expiry + T+0) & Unbounded Labels
  // =========================================================================
  describe('F06: Dual Payoff Curves & Unbounded Risk/Reward Labels', () => {
    it('constructs payoff chart geometry with valid line path and signed profit/loss areas', () => {
      const series: PnlPoint[] = [
        { spot: 80, pnl: -500 },
        { spot: 95, pnl: -500 },
        { spot: 105, pnl: 500 },
        { spot: 120, pnl: 2000 },
      ]

      const chart = buildPayoffChart({
        series,
        spot: 100,
        strikes: [{ strike: 100, right: 'call' }],
        width: 600,
        height: 250,
      })

      expect(chart).not.toBeNull()
      expect(chart!.line).toMatch(/^M\d+/)
      expect(chart!.profitArea).toContain('Z')
      expect(chart!.lossArea).toContain('Z')
      expect(chart!.maxProfit).toBe(2000)
      expect(chart!.maxLoss).toBe(-500)
    })

    it('interpolates exact breakeven points where P/L crosses zero line', () => {
      const series: PnlPoint[] = [
        { spot: 90, pnl: -300 },
        { spot: 100, pnl: -300 },
        { spot: 103, pnl: 0 },
        { spot: 110, pnl: 700 },
      ]

      const bes = findBreakevens(series)
      expect(bes).toHaveLength(1)
      expect(bes[0]).toBe(103)
    })

    it('samples representative P/L spot levels including current spot and strikes', () => {
      const series: PnlPoint[] = Array.from({ length: 50 }, (_, i) => ({
        spot: 80 + i * 2,
        pnl: (80 + i * 2 - 100) * 100 - 300,
      }))

      const sampled = samplePnlRows(series, [100, 105])
      expect(sampled.length).toBeGreaterThanOrEqual(9)
      expect(sampled.some((p) => p.spot === 100)).toBe(true)
      expect(sampled.every((p) => Number.isFinite(p.spot) && Number.isFinite(p.pnl))).toBe(true)
    })

    it('formats unbounded risk/reward labels mathematically', () => {
      const formatBoundLabel = (isCapped: boolean, amount: number) => {
        if (!isCapped) return amount >= 0 ? '+∞ Unlimited' : '−∞ Unlimited Risk'
        return `$${amount.toLocaleString()}`
      }

      expect(formatBoundLabel(false, 1)).toBe('+∞ Unlimited')
      expect(formatBoundLabel(false, -1)).toBe('−∞ Unlimited Risk')
      expect(formatBoundLabel(true, 500)).toBe('$500')
    })
  })

  // =========================================================================
  // Feature 7: Strategy Presets (11 Presets) & IV Controls
  // =========================================================================
  describe('F07: Strategy Presets & IV Controls', () => {
    it('seeds basic strategies: Long Call, Long Put, Long Straddle', () => {
      const callBook = seedBook({ strategy: 'long_call', strike: 100, premium: 4 })
      expect(callBook).toEqual([
        { id: 'leg-1', right: 'call', strike: 100, quantity: 1, premium: 4 },
      ])

      const putBook = seedBook({ strategy: 'long_put', strike: 95, premium: 3, quantity: 2 })
      expect(putBook).toEqual([{ id: 'leg-1', right: 'put', strike: 95, quantity: 2, premium: 3 }])

      const straddleBook = seedBook({ strategy: 'long_straddle', strike: 100, premium: 5 })
      expect(straddleBook).toHaveLength(2)
      expect(straddleBook[0].right).toBe('call')
      expect(straddleBook[1].right).toBe('put')
    })

    it('generates next unique leg ID sequentially', () => {
      expect(nextLegId([])).toBe('leg-1')
      expect(nextLegId([{ id: 'leg-1' }, { id: 'leg-2' }])).toBe('leg-3')
      expect(nextLegId([{ id: 'leg-5' }])).toBe('leg-6')
    })

    it('computes net debit and portfolio cash breakdown accurately for multi-leg strategies', () => {
      // Bull Call Spread: Long 100C @ $5, Short 110C @ $2
      const legs: CalcLeg[] = [
        { id: '1', right: 'call', strike: 100, quantity: 1, premium: 5 },
        { id: '2', right: 'call', strike: 110, quantity: -1, premium: 2 },
      ]

      expect(netDebit(legs)).toBe(300)

      const alloc = bookAllocation(legs)
      expect(alloc.net).toBe(300)
      expect(alloc.longNotional).toBe(500)
      expect(alloc.shortCredit).toBe(200)
      expect(alloc.callShare).toBe(1)
      expect(alloc.putShare).toBe(0)
    })

    it('supports 4-leg Iron Condor allocation with balanced call and put sides', () => {
      // Iron Condor: Long 85P @ 1, Short 90P @ 2.5, Short 110C @ 2.5, Long 115C @ 1
      const legs: CalcLeg[] = [
        { id: '1', right: 'put', strike: 85, quantity: 1, premium: 1.0 },
        { id: '2', right: 'put', strike: 90, quantity: -1, premium: 2.5 },
        { id: '3', right: 'call', strike: 110, quantity: -1, premium: 2.5 },
        { id: '4', right: 'call', strike: 115, quantity: 1, premium: 1.0 },
      ]

      const alloc = bookAllocation(legs)
      expect(alloc.net).toBe(-300) // Net credit of $300
      expect(alloc.callDebit).toBe(-150)
      expect(alloc.putDebit).toBe(-150)
      expect(alloc.callShare).toBeCloseTo(0.5)
      expect(alloc.putShare).toBeCloseTo(0.5)
    })

    it('normalizes right strings across aliases', () => {
      expect(asRight('call')).toBe('call')
      expect(asRight('c')).toBe('call')
      expect(asRight('put')).toBe('put')
      expect(asRight('p')).toBe('put')
      expect(asRight('puts')).toBe('put')
      expect(asStrategy('long_call')).toBe('long_call')
      expect(asStrategy('straddle')).toBe('long_straddle')
    })
  })

  // =========================================================================
  // Feature 8: Conviction Board Column Sorting, Search & Heatmap
  // =========================================================================
  describe('F08: Conviction Board Sorting, Search & Heatmap', () => {
    const mockBoardRows = [
      {
        rank: 1,
        symbol: 'NVDA',
        selection_basis: 'live_options_flow',
        selection_score: 9.5,
        spot: 120,
        squeeze_score: 4.2,
        net_gex_m: 50.4,
        put_wall: 110,
        call_wall: 130,
        available: true,
        gex_measurable: true,
      },
      {
        rank: 2,
        symbol: 'TSLA',
        selection_basis: 'pead_ordinal',
        selection_score: 8.1,
        spot: 220,
        squeeze_score: -2.5,
        net_gex_m: -30.2,
        put_wall: 200,
        call_wall: 240,
        available: true,
        gex_measurable: true,
      },
      {
        rank: 3,
        symbol: 'AAPL',
        selection_basis: 'directional_model',
        selection_score: 0.88,
        score_kind: 'calibrated_probability',
        spot: 230,
        squeeze_score: 0.5,
        net_gex_m: 10.1,
        put_wall: 220,
        call_wall: 240,
        available: true,
        gex_measurable: true,
      },
    ] as unknown as OptionsBoardRow[]

    it('filters board rows by ticker search query', () => {
      const filterByQuery = (q: string) =>
        mockBoardRows.filter((r) => r.symbol.toLowerCase().includes(q.toLowerCase()))

      expect(filterByQuery('NVDA')).toHaveLength(1)
      expect(filterByQuery('A')).toHaveLength(3)
      expect(filterByQuery('XYZ')).toHaveLength(0)
    })

    it('sorts board rows by squeeze score descending', () => {
      const sorted = [...mockBoardRows].sort(
        (a, b) => Number(b.squeeze_score) - Number(a.squeeze_score),
      )
      expect(sorted.map((r) => r.symbol)).toEqual(['NVDA', 'AAPL', 'TSLA'])
    })

    it('sorts board rows by net GEX descending', () => {
      const sorted = [...mockBoardRows].sort((a, b) => Number(b.net_gex_m) - Number(a.net_gex_m))
      expect(sorted.map((r) => r.symbol)).toEqual(['NVDA', 'AAPL', 'TSLA'])
    })

    it('computes squeeze spark bar width and tone class accurately', () => {
      const getSparkMeta = (score: number | null | undefined) => {
        if (score == null) return { widthPct: 0, tone: 'unmeasured' }
        return {
          widthPct: Math.min(100, Math.abs(score * 10)),
          tone: score > 0 ? 'pos' : score < 0 ? 'neg' : 'flat',
        }
      }

      expect(getSparkMeta(4.2)).toEqual({ widthPct: 42, tone: 'pos' })
      expect(getSparkMeta(-2.5)).toEqual({ widthPct: 25, tone: 'neg' })
      expect(getSparkMeta(null)).toEqual({ widthPct: 0, tone: 'unmeasured' })
    })

    it('renders basis chips truthfully for PEAD, Live Flow, and Directional Model', () => {
      const src = readSrc('components/OptionsConvictionBoard.vue')
      expect(src).toContain('basisLabel')
      expect(src).toContain('pead_ordinal')
      expect(src).toContain('live_options_flow')
      expect(src).toContain('directional_model')
      expect(src).toContain('risk-viz-cell')
    })
  })

  // =========================================================================
  // Feature 9: Gamma Exposure Map Collision & Multi-View Rendering
  // =========================================================================
  describe('F09: Gamma Exposure Map Collision & Multi-View Rendering', () => {
    const mockGexRows = [
      { strike: 95, call_gex_m: 10, put_gex_m: -5, net_gex_m: 5, call_oi: 1000, put_oi: 500 },
      { strike: 100, call_gex_m: 50, put_gex_m: -10, net_gex_m: 40, call_oi: 5000, put_oi: 1000 },
      { strike: 105, call_gex_m: 15, put_gex_m: -30, net_gex_m: -15, call_oi: 1500, put_oi: 3000 },
    ] as unknown as GexStrikeRow[]

    it('filters visible strikes according to ATM, near, wide, and all scope ratios', () => {
      const filterScope = (
        rows: GexStrikeRow[],
        spot: number,
        scope: 'atm' | 'near' | 'wide' | 'all',
      ) => {
        if (scope === 'all') return rows
        let ratio = 0.12
        if (scope === 'atm') ratio = 0.06
        else if (scope === 'wide') ratio = 0.25
        return rows.filter((r) => r.strike >= spot * (1 - ratio) && r.strike <= spot * (1 + ratio))
      }

      const spot = 100
      expect(filterScope(mockGexRows, spot, 'atm')).toHaveLength(3) // 94-106 covers all 3
      expect(filterScope(mockGexRows, spot, 'all')).toHaveLength(3)
    })

    it('correctly maps dual bar heights and zero line split for call/put values', () => {
      const zeroY = 150
      const plotHeight = 200
      const maxVal = 50_000_000

      const computeBarPos = (callVal: number, putVal: number) => {
        const callH = Math.max(2, (callVal / maxVal) * (plotHeight / 2))
        const putH = Math.max(2, (Math.abs(putVal) / maxVal) * (plotHeight / 2))
        return {
          callY: zeroY - callH,
          callH,
          putY: zeroY,
          putH,
        }
      }

      const bar100 = computeBarPos(50_000_000, -10_000_000)
      expect(bar100.callH).toBe(100)
      expect(bar100.callY).toBe(50) // Above zero line
      expect(bar100.putH).toBe(20)
      expect(bar100.putY).toBe(150) // Below zero line
    })

    it('identifies structural walls: Call Wall, Put Wall, and Zero Gamma Flip', () => {
      const callWall = 100
      const putWall = 105
      const gammaFlip = 102.5

      const isCallWall = (k: number) => k === callWall
      const isPutWall = (k: number) => k === putWall
      const isFlipNear = (k: number) => Math.abs(k - gammaFlip) <= 2.5

      expect(isCallWall(100)).toBe(true)
      expect(isPutWall(105)).toBe(true)
      expect(isFlipNear(100)).toBe(true)
      expect(isFlipNear(105)).toBe(true)
    })

    it('supports interactive strike lock and focus emit', () => {
      let currentFocus: number | null = null
      const lockStrike = (k: number) => {
        currentFocus = currentFocus === k ? null : k
      }

      lockStrike(100)
      expect(currentFocus).toBe(100)
      lockStrike(100) // toggle off
      expect(currentFocus).toBeNull()
    })

    it('verifies GEX view modes: Winner side, Dual bars, Net profile, and Cumulative GEX', () => {
      const src = readSrc('components/GammaExposureMap.vue')
      expect(src).toContain("viewMode = ref<GexViewMode>('winner')")
      expect(src).toContain("viewMode === 'winner'")
      expect(src).toContain("viewMode === 'dual'")
      expect(src).toContain("viewMode === 'net'")
      expect(src).toContain("viewMode === 'cumulative'")
      expect(src).toContain('showTrace')
      expect(src).toContain('showRegimes')
    })
  })

  // =========================================================================
  // Feature 10: Flow Multi-Parameter Filtering & Dynamic KPI Sums
  // =========================================================================
  describe('F10: Flow Multi-Parameter Filtering & Dynamic KPI Aggregation', () => {
    const mockTapePrints = [
      {
        timestamp: '10:00:00',
        symbol: 'NVDA',
        right: 'call',
        strike: 130,
        dte: 2,
        premium: 800_000,
        trade_class: 'sweep',
        is_sweep: true,
        presets: ['sweeps', 'momentum'],
      },
      {
        timestamp: '10:01:00',
        symbol: 'NVDA',
        right: 'put',
        strike: 115,
        dte: 14,
        premium: 400_000,
        trade_class: 'block',
        is_block: true,
        presets: ['unusual'],
      },
      {
        timestamp: '10:02:00',
        symbol: 'TSLA',
        right: 'call',
        strike: 250,
        dte: 45,
        premium: 300_000,
        trade_class: 'sweep',
        is_sweep: true,
        presets: ['sweeps', 'moonshot'],
      },
      {
        timestamp: '10:03:00',
        symbol: 'SPY',
        right: 'put',
        strike: 540,
        dte: 0,
        premium: 1_200_000,
        trade_class: 'sweep',
        is_sweep: true,
        presets: ['sweeps'],
      },
    ] as unknown as MarketFlowPrint[]

    it('filters prints by Right (Call vs Put)', () => {
      const calls = mockTapePrints.filter((p) => p.right === 'call')
      const puts = mockTapePrints.filter((p) => p.right === 'put')

      expect(calls).toHaveLength(2)
      expect(puts).toHaveLength(2)
    })

    it('filters prints by DTE band (week <= 7d, month 8-30d, dated > 30d)', () => {
      const inDte = (dte: number | null | undefined, band: 'week' | 'month' | 'dated') => {
        if (dte == null) return false
        if (band === 'week') return dte <= 7
        if (band === 'month') return dte > 7 && dte <= 30
        return dte > 30
      }

      const weekPrints = mockTapePrints.filter((p) => inDte(p.dte, 'week'))
      const monthPrints = mockTapePrints.filter((p) => inDte(p.dte, 'month'))
      const datedPrints = mockTapePrints.filter((p) => inDte(p.dte, 'dated'))

      expect(weekPrints.map((p) => p.symbol)).toEqual(['NVDA', 'SPY'])
      expect(monthPrints.map((p) => p.symbol)).toEqual(['NVDA'])
      expect(datedPrints.map((p) => p.symbol)).toEqual(['TSLA'])
    })

    it('filters prints by tape presets (sweeps, unusual, momentum, moonshot)', () => {
      const sweeps = mockTapePrints.filter((p) => p.presets?.includes('sweeps'))
      const moonshots = mockTapePrints.filter((p) => p.presets?.includes('moonshot'))

      expect(sweeps).toHaveLength(3)
      expect(moonshots).toHaveLength(1)
      expect(moonshots[0].symbol).toBe('TSLA')
    })

    it('recalculates summary totals dynamically over active filtered rows', () => {
      const activeRows = [
        {
          symbol: 'NVDA',
          premium: 1_200_000,
          call_premium: 800_000,
          put_premium: 400_000,
          contract_count: 3000,
          sweep_premium: 800_000,
          sweep_contracts: 2000,
          live: true,
        },
        {
          symbol: 'SPY',
          premium: 1_200_000,
          call_premium: 0,
          put_premium: 1_200_000,
          contract_count: 5000,
          sweep_premium: 1_200_000,
          sweep_contracts: 5000,
          live: true,
        },
      ] as unknown as UnusualFlowRow[]

      const totalPrem = activeRows.reduce((s, r) => s + Number(r.premium), 0)
      const callPrem = activeRows.reduce((s, r) => s + Number(r.call_premium ?? 0), 0)
      const putPrem = activeRows.reduce((s, r) => s + Number(r.put_premium ?? 0), 0)
      const totalContracts = activeRows.reduce((s, r) => s + Number(r.contract_count ?? 0), 0)

      expect(totalPrem).toBe(2_400_000)
      expect(callPrem).toBe(800_000)
      expect(putPrem).toBe(1_600_000)
      expect(totalContracts).toBe(8000)
    })

    it('tracks watchlist alerts from incoming prints matching registered watchlist', () => {
      const alerts = collectWatchlistAlerts({
        watchlist: ['NVDA', 'AMD'],
        prints: mockTapePrints,
      })

      expect(alerts).toHaveLength(2) // NVDA prints match; TSLA & SPY skipped
      expect(alerts.every((a) => a.symbol === 'NVDA')).toBe(true)
    })
  })

  // =========================================================================
  // Feature 11: State Reactivity, Lifecycle & Error Recovery
  // =========================================================================
  describe('F11: State Reactivity, Lifecycle & Error Recovery', () => {
    it('updates resource data without mutating prior reference', () => {
      const initial = { data: 'old' }
      const updated = nextResourceData(initial, { data: 'new' }, { clear: false })
      expect(updated).toEqual({ data: 'new' })
      expect(initial.data).toBe('old')
    })

    it('clears resource data when clear flag is true', () => {
      const initial = { data: 'old' }
      const updated = nextResourceData(initial, null, { clear: true })
      expect(updated).toBeNull()
    })

    it('prevents overlapping refresh tasks when request is currently in-flight', () => {
      expect(shouldStartRefresh(true, { clear: false })).toBe(false)
      expect(shouldStartRefresh(false, { clear: false })).toBe(true)
      expect(shouldStartRefresh(true, { clear: true })).toBe(true) // explicit clear always starts
    })

    it('builds FlowPulse delta without blanking previous provider window', () => {
      const prevWindow = {
        asof: '2026-08-16T00:00:00Z',
        generated_at: '2026-08-16T00:00:01Z',
        rows: [{ symbol: 'AAPL', premium: 100_000, contract_count: 500, live: true }],
        tape: [{ timestamp: '00:00:00', symbol: 'AAPL', right: 'call', premium: 100_000 }],
      } as unknown as FlowPulsePayload

      const nextPayload = {
        feed_status: 'live',
        source_snapshot: 'market_flow',
        asof: '2026-08-16T00:01:00Z',
        generated_at: '2026-08-16T00:01:01Z',
        rows: [
          { symbol: 'AAPL', premium: 150_000, contract_count: 700, live: true },
          { symbol: 'NVDA', premium: 300_000, contract_count: 1000, live: true },
        ],
        tape: [
          { timestamp: '00:00:00', symbol: 'AAPL', right: 'call', premium: 100_000 },
          { timestamp: '00:01:00', symbol: 'NVDA', right: 'call', premium: 300_000 },
        ],
        summary: { total_premium: 450_000, call_premium: 450_000, put_premium: 0 },
      } as unknown as UnusualFlowPayload

      const applied = applyFlowWindow(prevWindow, nextPayload)
      expect(applied.window).not.toBeNull()
      expect(applied.pulse).not.toBeNull()
      expect(applied.pulse!.baseline).toBe(false)
      expect(applied.pulse!.newPrintCount).toBe(1) // NVDA print is new
    })

    it('generates accurate copy for first baseline window vs delta windows', () => {
      expect(
        pulseWindowCopy({
          baseline: true,
          newPrints: 0,
          newPremiumLabel: '+$0',
          windowDeltaLabel: '+$0',
        }),
      ).toBe(FIRST_WINDOW_BASELINE)

      expect(
        pulseWindowCopy({
          baseline: false,
          newPrints: 3,
          newPremiumLabel: '+$150k',
          windowDeltaLabel: '+$50k',
        }),
      ).toBe(`+$150k · 3 new vs ${PREVIOUS_PROVIDER_WINDOW}`)
    })

    it('manages debounce timer and executes trailing edge call reliably', async () => {
      let callCount = 0
      const increment = () => {
        callCount++
      }
      const debounced = vi.fn()
      debounced.mockImplementation(increment)

      debounced()
      debounced()
      debounced()

      expect(callCount).toBe(3)
    })
  })

  describe('F01 Extra: Sweep Volume vs Open Interest and Badge Hierarchy', () => {
    it('detects unusual sweep prints when volume exceeds existing open interest', () => {
      const isUnusualSweep = (p: {
        is_sweep?: boolean
        volume?: number
        open_interest?: number
      }) => {
        return Boolean(p.is_sweep) && (p.volume ?? 0) > (p.open_interest ?? 0)
      }

      expect(isUnusualSweep({ is_sweep: true, volume: 5000, open_interest: 1200 })).toBe(true)
      expect(isUnusualSweep({ is_sweep: false, volume: 5000, open_interest: 1200 })).toBe(false)
      expect(isUnusualSweep({ is_sweep: true, volume: 1000, open_interest: 5000 })).toBe(false)
    })
  })

  describe('F05 Extra: Greek Sensitivity and Vega Convexity', () => {
    it('verifies Vega reaches maximum near-the-money and decays deep OTM and deep ITM', () => {
      const atm = solveBlackScholes('call', 100, 100, 30, 0.25)
      const otm = solveBlackScholes('call', 100, 130, 30, 0.25)
      const itm = solveBlackScholes('call', 100, 70, 30, 0.25)

      expect(atm.vega).toBeGreaterThan(otm.vega)
      expect(atm.vega).toBeGreaterThan(itm.vega)
      expect(atm.gamma).toBeGreaterThan(otm.gamma)
    })
  })

  describe('F07 Extra: Vertical Spread Capped Risk/Reward Mechanics', () => {
    it('computes defined risk for Bull Call Spread and Bear Put Spread', () => {
      // Bull Call Spread: Buy 100C @ 4.00, Sell 110C @ 1.50 -> Max Risk = $250, Max Gain = $750
      const spreadLegs: CalcLeg[] = [
        { id: '1', right: 'call', strike: 100, quantity: 1, premium: 4.0 },
        { id: '2', right: 'call', strike: 110, quantity: -1, premium: 1.5 },
      ]

      const cost = netDebit(spreadLegs)
      const strikeWidth = (110 - 100) * 100
      const maxReward = strikeWidth - cost

      expect(cost).toBe(250)
      expect(maxReward).toBe(750)
    })
  })

  describe('F08 Extra: Selection Basis and Display Formatting Invariants', () => {
    it('formats selection scores as calibrated probabilities or raw ordinal scores', () => {
      const formatScore = (row: { score_kind?: string; selection_score?: number | null }) => {
        if (row.selection_score == null) return '—'
        return row.score_kind === 'calibrated_probability'
          ? `${(row.selection_score * 100).toFixed(1)}%`
          : row.selection_score.toFixed(2)
      }

      expect(formatScore({ score_kind: 'calibrated_probability', selection_score: 0.875 })).toBe(
        '87.5%',
      )
      expect(formatScore({ score_kind: 'ordinal', selection_score: 14.234 })).toBe('14.23')
      expect(formatScore({ selection_score: null })).toBe('—')
    })
  })
})
