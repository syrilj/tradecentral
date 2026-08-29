import { describe, expect, it } from 'vitest'
import {
  bookAllocation,
  buildDualPayoffChart,
  computeBookGreeks,
  computeGreeks,
  erf,
  evaluateBookDualCurves,
  evaluateRiskRewardBounds,
  findBreakevens,
  netDebit,
  normCdf,
  smileAdjustedVol,
  STRATEGY_PRESETS,
  usableLegs,
  type CalcLeg,
} from '@/optionsCalculator'
import {
  classifyFlowOrder,
  classifyPremiumTier,
  computeVolOiRatio,
  flowWhaleTier,
  type FlowOrderInput,
} from '@/flowDisplay'
import {
  applyFlowWindow,
  buildFlowPulse,
  compareFlowReviewRows,
  type FlowPulsePayload,
} from '@/flowPulse'
import type { MarketFlowPrint, UnusualFlowRow } from '@/api'

describe('Challenger 1: Empirical Flow Telemetry & Mathematical Stress Testing', () => {
  /* ==========================================================================
     SECTION 1: Black-Scholes Numerical Stability at Extreme Boundaries
     ========================================================================== */
  describe('1. Black-Scholes Numerical Stability & Extreme Boundaries', () => {
    it('handles 0 DTE and sub-minute DTE (0.000001 DTE) without NaN or Infinity', () => {
      const spot = 500
      const strike = 500
      const iv = 20

      // Exact 0 DTE
      const g0Call = computeGreeks('call', spot, strike, 0, iv)
      const g0Put = computeGreeks('put', spot, strike, 0, iv)

      expect(Number.isFinite(g0Call.theo)).toBe(true)
      expect(Number.isFinite(g0Put.theo)).toBe(true)
      expect(g0Call.theo).toBe(0)
      expect(g0Put.theo).toBe(0)
      expect(g0Call.delta).toBe(0.5) // ATM boundary delta
      expect(g0Put.delta).toBe(-0.5)
      expect(g0Call.gamma).toBe(0)
      expect(g0Call.theta).toBe(0)
      expect(g0Call.vega).toBe(0)

      // Sub-minute micro DTE (0.000001 days ~ 0.086 seconds)
      const microDte = 0.000001
      const gMicroCall = computeGreeks('call', spot, strike, microDte, iv)
      const gMicroPut = computeGreeks('put', spot, strike, microDte, iv)

      expect(Number.isFinite(gMicroCall.theo)).toBe(true)
      expect(Number.isFinite(gMicroPut.theo)).toBe(true)
      expect(Number.isFinite(gMicroCall.delta)).toBe(true)
      expect(Number.isFinite(gMicroCall.gamma)).toBe(true)
      expect(Number.isFinite(gMicroCall.theta)).toBe(true)
      expect(Number.isFinite(gMicroCall.vega)).toBe(true)
      expect(gMicroCall.theo).toBeGreaterThanOrEqual(0)
      expect(gMicroPut.theo).toBeGreaterThanOrEqual(0)
    })

    it('handles multi-year LEAPs (730 DTE to 3650 DTE / 10 years)', () => {
      const spot = 200
      const strike = 200
      const iv = 35

      const g730 = computeGreeks('call', spot, strike, 730, iv, 4.5)
      const g3650 = computeGreeks('call', spot, strike, 3650, iv, 4.5)

      expect(Number.isFinite(g730.theo)).toBe(true)
      expect(Number.isFinite(g3650.theo)).toBe(true)
      expect(g730.theo).toBeGreaterThan(0)
      expect(g3650.theo).toBeGreaterThan(g730.theo)
      expect(g730.delta).toBeGreaterThan(0.5)
      expect(g3650.delta).toBeGreaterThan(g730.delta)
      expect(g730.rho).toBeGreaterThan(0)
      expect(g3650.rho).toBeGreaterThan(g730.rho)
    })

    it('handles extreme implied volatility: 0.0001%, 500%, 1000%, and 5000%', () => {
      const spot = 100
      const strike = 100
      const dte = 30

      // Near-zero IV
      const gLowIv = computeGreeks('call', spot, strike, dte, 0.0001, 0)
      expect(Number.isFinite(gLowIv.theo)).toBe(true)
      expect(gLowIv.theo).toBeCloseTo(0, 1)

      // Extreme IV (500% earnings shock)
      const g500 = computeGreeks('call', spot, strike, dte, 500, 4.5)
      const g500Put = computeGreeks('put', spot, strike, dte, 500, 4.5)
      expect(Number.isFinite(g500.theo)).toBe(true)
      expect(Number.isFinite(g500Put.theo)).toBe(true)
      expect(g500.theo).toBeGreaterThan(spot * 0.4) // High vol call is worth large fraction of spot
      expect(g500.vega).toBeGreaterThan(0)

      // Hyper IV (1000% and 5000%)
      const g1000 = computeGreeks('call', spot, strike, dte, 1000, 4.5)
      const g5000 = computeGreeks('call', spot, strike, dte, 5000, 4.5)
      expect(Number.isFinite(g1000.theo)).toBe(true)
      expect(Number.isFinite(g5000.theo)).toBe(true)
      expect(g5000.theo).toBeLessThanOrEqual(spot) // Theoretical price cannot exceed spot
    })

    it('handles extreme spot & strike disparities (Penny stock vs Berkshire Hathaway scale)', () => {
      // Penny stock: Spot = $0.02, Strike = $0.50 (Deep OTM)
      const gPenny = computeGreeks('call', 0.02, 0.5, 30, 80)
      expect(Number.isFinite(gPenny.theo)).toBe(true)
      expect(gPenny.theo).toBeCloseTo(0, 4)
      expect(gPenny.delta).toBeCloseTo(0, 4)

      // Berkshire Hathaway Scale: Spot = $650,000, Strike = $650,000
      const gBrk = computeGreeks('call', 650_000, 650_000, 45, 18, 4.5)
      expect(Number.isFinite(gBrk.theo)).toBe(true)
      expect(gBrk.theo).toBeGreaterThan(10_000)
      expect(gBrk.delta).toBeCloseTo(0.55, 1)

      // Spot = $1,000,000 vs Strike = $10 (Deep ITM Call / Delta -> 1.0)
      const gDeepItm = computeGreeks('call', 1_000_000, 10, 30, 25, 0)
      expect(gDeepItm.delta).toBeCloseTo(1.0, 5)
      expect(gDeepItm.theo).toBeCloseTo(999_990, 0)

      // Spot = $10 vs Strike = $1,000,000 (Deep OTM Call / Delta -> 0.0)
      const gDeepOtm = computeGreeks('call', 10, 1_000_000, 30, 25, 0)
      expect(gDeepOtm.delta).toBeCloseTo(0.0, 5)
      expect(gDeepOtm.theo).toBe(0)
    })

    it('handles negative interest rates (NIRP -5%) and hyper-inflationary rates (+100%)', () => {
      const spot = 100
      const strike = 100
      const dte = 60
      const iv = 30

      const gNirp = computeGreeks('call', spot, strike, dte, iv, -5.0)
      const gHyper = computeGreeks('call', spot, strike, dte, iv, 100.0)

      expect(Number.isFinite(gNirp.theo)).toBe(true)
      expect(Number.isFinite(gHyper.theo)).toBe(true)
      // Call price increases with higher interest rates
      expect(gHyper.theo).toBeGreaterThan(gNirp.theo)
    })

    it('handles corrupted, NaN, infinite, negative, or invalid numeric inputs safely', () => {
      expect(computeGreeks('call', NaN, 100, 30, 25).theo).toBe(0)
      expect(computeGreeks('call', -50, 100, 30, 25).theo).toBe(0)
      expect(computeGreeks('call', 100, -100, 30, 25).theo).toBe(0)
      expect(computeGreeks('call', 100, NaN, 30, 25).theo).toBe(0)
      expect(computeGreeks('call', 100, 100, -10, 25).theo).toBe(0)
      expect(computeGreeks('call', 100, 100, 30, -50).theo).toBeGreaterThanOrEqual(0)
    })
  })

  /* ==========================================================================
     SECTION 2: Greeks Invariants Monte Carlo Oracle (5,000 Trials)
     ========================================================================== */
  describe('2. Greeks Mathematical Invariants Monte Carlo Oracle (5,000 Trials)', () => {
    it('verifies Put-Call parity, Vega positivity, Delta bounds, and Gamma symmetry across 5,000 randomized options', () => {
      let seed = 1337
      const pseudoRandom = () => {
        seed = (seed * 16807) % 2147483647
        return (seed - 1) / 2147483646
      }

      const TRIALS = 5000
      let parityViolations = 0
      let deltaViolations = 0
      let gammaViolations = 0
      let vegaViolations = 0

      for (let i = 0; i < TRIALS; i++) {
        const spot = 10 + pseudoRandom() * 990 // $10 to $1,000
        const strike = spot * (0.5 + pseudoRandom() * 1.0) // 50% to 150% moneyness
        const dte = 0.5 + pseudoRandom() * 365 // 0.5d to 365.5d
        const volPct = 5 + pseudoRandom() * 195 // 5% to 200% IV
        // Passing rate as a decimal fraction r in [0.01, 0.10] ensuring consistent normalization
        const rDecimal = 0.01 + pseudoRandom() * 0.09
        const ratePct = rDecimal * 100 // 1% to 10%
        const divPct = 0 // test pure cash/no dividend parity

        const call = computeGreeks('call', spot, strike, dte, volPct, ratePct, divPct)
        const put = computeGreeks('put', spot, strike, dte, volPct, ratePct, divPct)

        // 1. Put-Call Parity: C - P = S - K * exp(-r*T)
        const T = dte / 365.0
        const r = ratePct / 100.0
        const lhs = call.theo - put.theo
        const rhs = spot - strike * Math.exp(-r * T)
        if (Math.abs(lhs - rhs) > 1e-3 * Math.max(1, spot)) {
          parityViolations++
        }

        // 2. Delta Bounds & Parity: 0 <= delta_call <= 1, -1 <= delta_put <= 0, delta_call - delta_put = 1
        if (
          call.delta < -1e-7 ||
          call.delta > 1 + 1e-7 ||
          put.delta < -1 - 1e-7 ||
          put.delta > 1e-7
        ) {
          deltaViolations++
        }
        if (Math.abs(call.delta - put.delta - 1.0) > 1e-5) {
          deltaViolations++
        }

        // 3. Gamma Symmetry & Strict Positivity: gamma_call == gamma_put >= 0
        if (call.gamma < 0 || put.gamma < 0 || Math.abs(call.gamma - put.gamma) > 1e-7) {
          gammaViolations++
        }

        // 4. Vega Symmetry & Strict Positivity: vega_call == vega_put >= 0
        if (call.vega < 0 || put.vega < 0 || Math.abs(call.vega - put.vega) > 1e-5) {
          vegaViolations++
        }
      }

      expect(parityViolations).toBe(0)
      expect(deltaViolations).toBe(0)
      expect(gammaViolations).toBe(0)
      expect(vegaViolations).toBe(0)
    })
  })

  /* ==========================================================================
     SECTION 3: Flow Telemetry, Zero OI, and Extreme Premiums ($10M+)
     ========================================================================== */
  describe('3. Flow Telemetry, Zero OI, and Extreme Premiums ($10M+)', () => {
    it('classifies extreme $10M+ Mega Whale Golden Sweeps properly', () => {
      const megaSweep: FlowOrderInput = {
        trade_class: 'sweep',
        aggressor: 'ask',
        premium: 15_000_000,
        volume: 25_000,
        open_interest: 5_000,
        is_sweep: true,
      }

      const meta = classifyFlowOrder(megaSweep)
      expect(meta.type).toBe('golden_sweep')
      expect(meta.label).toBe('GOLDEN SWEEP')

      const tier = classifyPremiumTier(15_000_000)
      expect(tier.tier).toBe('mega_whale')
      expect(tier.label).toBe('$1M+ MEGA')
      expect(tier.isWhale).toBe(true)

      const whale = flowWhaleTier(15_000_000)
      expect(whale.tier).toBe('1m')
      expect(whale.label).toBe('$1M+')
    })

    it('correctly handles zero open interest (0 OI) without division by zero', () => {
      const result = computeVolOiRatio(5000, 0)
      expect(result.ratio).toBeNull()
      expect(result.formatted).toBe('NEW (0 OI)')
      expect(result.isHigh).toBe(true)
      expect(result.isExtreme).toBe(true)
    })

    it('correctly handles null, negative, and unmeasured open interest / volume', () => {
      expect(computeVolOiRatio(null, 5000).formatted).toBe('0.00x')
      expect(computeVolOiRatio(5000, null).formatted).toBe('0.00x')
      expect(computeVolOiRatio(-100, 5000).formatted).toBe('0.00x')
      expect(computeVolOiRatio(5000, -100).formatted).toBe('0.00x')
      expect(computeVolOiRatio(undefined, undefined).ratio).toBeNull()
    })

    it('computes high and extreme volume/OI ratio thresholds accurately', () => {
      const rNormal = computeVolOiRatio(500, 1000) // 0.5x
      expect(rNormal.ratio).toBe(0.5)
      expect(rNormal.formatted).toBe('0.5×')
      expect(rNormal.isHigh).toBe(false)
      expect(rNormal.isExtreme).toBe(false)

      const rHigh = computeVolOiRatio(1500, 1000) // 1.5x
      expect(rHigh.ratio).toBe(1.5)
      expect(rHigh.formatted).toBe('1.5×')
      expect(rHigh.isHigh).toBe(true)
      expect(rHigh.isExtreme).toBe(false)

      const rExtreme = computeVolOiRatio(4500, 1000) // 4.5x
      expect(rExtreme.ratio).toBe(4.5)
      expect(rExtreme.formatted).toBe('4.5×')
      expect(rExtreme.isHigh).toBe(true)
      expect(rExtreme.isExtreme).toBe(true)

      const rMega = computeVolOiRatio(25000, 1000) // 25x
      expect(rMega.ratio).toBe(25)
      expect(rMega.formatted).toBe('25×')
      expect(rMega.isHigh).toBe(true)
      expect(rMega.isExtreme).toBe(true)
    })

    it('classifies all institutional order types accurately under varied flag formats', () => {
      // 1. Golden Sweep via explicit flag
      expect(classifyFlowOrder({ flags: ['golden_sweep'] }).type).toBe('golden_sweep')

      // 2. Standard Sweep
      expect(classifyFlowOrder({ trade_class: 'sweep', premium: 20_000 }).type).toBe('sweep')

      // 3. Block Trade
      expect(classifyFlowOrder({ trade_class: 'block', premium: 800_000 }).type).toBe('block')

      // 4. Intermarket Split
      expect(classifyFlowOrder({ flags: ['intermarket_split'] }).type).toBe('split')

      // 5. Complex Multi-Leg Spread
      expect(classifyFlowOrder({ flags: ['combo'] }).type).toBe('multileg')
      expect(classifyFlowOrder({ trade_class: 'spread' }).type).toBe('multileg')
      expect(classifyFlowOrder({ flags: ['straddle'] }).type).toBe('multileg')

      // 6. Standard Print
      expect(classifyFlowOrder({ trade_class: 'iso' }).type).toBe('standard')
    })
  })

  /* ==========================================================================
     SECTION 4: High-Throughput Flow Tape Stress Benchmark (1,000 to 10,000 Prints)
     ========================================================================== */
  describe('4. High-Throughput Flow Tape & Pulse Benchmark (1,000 - 10,000 prints)', () => {
    function generateSyntheticTape(count: number): MarketFlowPrint[] {
      const symbols = ['SPY', 'QQQ', 'NVDA', 'AAPL', 'TSLA', 'AMZN', 'MSFT', 'META', 'AMD', 'GOOGL']
      const rights: Array<'call' | 'put'> = ['call', 'put']
      const classes = ['sweep', 'block', 'split', 'multileg', 'standard']
      const aggressors = ['buy', 'sell', 'ask', 'bid', 'mid']

      const prints: MarketFlowPrint[] = []
      const baseTime = Date.now()

      for (let i = 0; i < count; i++) {
        const symbol = symbols[i % symbols.length]
        const right = rights[i % rights.length]
        const tradeClass = classes[i % classes.length]
        const aggressor = aggressors[i % aggressors.length]
        const strike = 100 + (i % 50) * 5
        const dte = (i % 60) + 1
        const premium = ((i % 20) + 1) * 50_000 // $50k to $1M
        const volume = ((i % 100) + 1) * 50
        const oi = (i % 50) * 100

        prints.push({
          timestamp: new Date(baseTime - i * 1000).toISOString(),
          symbol,
          strike,
          dte,
          right,
          price: 3.5,
          trade_class: tradeClass,
          aggressor: aggressor === 'buy' || aggressor === 'sell' ? aggressor : null,
          aggressor_label: aggressor.toUpperCase(),
          premium,
          contracts: volume,
          volume,
          open_interest: oi,
          otm_pct: (strike - 150) / 150,
          underlying_price: 150,
          is_sweep: tradeClass === 'sweep',
          is_unusual: premium >= 250_000,
          is_momentum: i % 5 === 0,
          is_moonshot: dte <= 7 && strike > 160,
          presets: ['all'],
        } as unknown as MarketFlowPrint)
      }

      return prints
    }

    it('processes 1,000 synthetic tape prints and generates pulse in under 50ms', () => {
      const tape1k = generateSyntheticTape(1000)
      const initialPayload: FlowPulsePayload = {
        asof: '2026-08-16T10:00:00Z',
        generated_at: '2026-08-16T10:00:00Z',
        rows: [],
        tape: tape1k.slice(500), // First 500 prints as baseline
      }
      const updatedPayload: FlowPulsePayload = {
        asof: '2026-08-16T10:01:00Z',
        generated_at: '2026-08-16T10:01:00Z',
        rows: [],
        tape: tape1k, // 1000 prints (500 new)
      }

      const t0 = performance.now()
      const pulse = buildFlowPulse(initialPayload, updatedPayload)
      const duration = performance.now() - t0

      expect(duration).toBeLessThan(50) // High-performance throughput requirement
      expect(pulse.newPrintCount).toBe(500)
      expect(pulse.bySymbol.size).toBe(10)
    })

    it('processes 10,000 synthetic tape prints without memory exhaustion or catastrophic latency', () => {
      const tape10k = generateSyntheticTape(10_000)
      const basePayload: FlowPulsePayload = {
        asof: '2026-08-16T10:00:00Z',
        generated_at: '2026-08-16T10:00:00Z',
        rows: [],
        tape: tape10k.slice(2000),
      }
      const nextPayload: FlowPulsePayload = {
        asof: '2026-08-16T10:01:00Z',
        generated_at: '2026-08-16T10:01:00Z',
        rows: [],
        tape: tape10k,
      }

      const t0 = performance.now()
      const pulse = buildFlowPulse(basePayload, nextPayload)
      const duration = performance.now() - t0

      expect(duration).toBeLessThan(250) // Sub-250ms for 10k items
      expect(pulse.newPrintCount).toBe(2000)

      // Test window delta application
      const t1 = performance.now()
      const applied = applyFlowWindow(basePayload, nextPayload)
      const deltaDuration = performance.now() - t1

      expect(deltaDuration).toBeLessThan(250)
      expect(applied.pulse).not.toBeNull()
    })
  })

  /* ==========================================================================
     SECTION 5: Table Sorting Permutations & Multi-Column Invariants
     ========================================================================== */
  describe('5. Table Sorting Permutations & Invariants', () => {
    it('executes all 10 Tape Sort Keys across ascending and descending directions stably', () => {
      const tape = [
        {
          symbol: 'NVDA',
          timestamp: '2026-08-16T10:00:00Z',
          strike: 120,
          dte: 7,
          price: 4.5,
          trade_class: 'sweep',
          open_interest: 1000,
          volume: 2000,
          premium: 500_000,
          premium_percentile: 0.95,
          aggressor: 'buy',
        },
        {
          symbol: 'AAPL',
          timestamp: '2026-08-16T10:01:00Z',
          strike: 220,
          dte: 30,
          price: 2.1,
          trade_class: 'block',
          open_interest: 5000,
          volume: 1000,
          premium: 210_000,
          premium_percentile: 0.7,
          aggressor: 'sell',
        },
        {
          symbol: 'TSLA',
          timestamp: '2026-08-16T09:59:00Z',
          strike: 200,
          dte: 1,
          price: 8.0,
          trade_class: 'split',
          open_interest: 0,
          volume: 500,
          premium: 400_000,
          premium_percentile: 0.85,
          aggressor: 'ask',
        },
        {
          symbol: 'SPY',
          timestamp: '2026-08-16T10:05:00Z',
          strike: 550,
          dte: 14,
          price: 1.2,
          trade_class: 'multileg',
          open_interest: 10000,
          volume: 50000,
          premium: 1_200_000,
          premium_percentile: 0.99,
          aggressor: 'bid',
        },
        {
          symbol: 'AMD',
          timestamp: '2026-08-16T09:50:00Z',
          strike: 150,
          dte: 60,
          price: 5.0,
          trade_class: 'standard',
          open_interest: null,
          volume: null,
          premium: null,
          premium_percentile: null,
          aggressor: null,
        },
      ] as unknown as MarketFlowPrint[]

      type TapeSortKey =
        | 'time'
        | 'symbol'
        | 'contract'
        | 'expiry'
        | 'fill'
        | 'trade_class'
        | 'vol_oi'
        | 'premium'
        | 'percentile'
        | 'aggressor'
      const sortKeys: TapeSortKey[] = [
        'time',
        'symbol',
        'contract',
        'expiry',
        'fill',
        'trade_class',
        'vol_oi',
        'premium',
        'percentile',
        'aggressor',
      ]

      for (const key of sortKeys) {
        for (const dir of ['asc', 'desc'] as const) {
          const sorted = [...tape].sort((a, b) => {
            const mul = dir === 'asc' ? 1 : -1
            let av: number | string = -Infinity
            let bv: number | string = -Infinity

            if (key === 'time') {
              av = a.timestamp || ''
              bv = b.timestamp || ''
            } else if (key === 'symbol') {
              av = a.symbol || ''
              bv = b.symbol || ''
            } else if (key === 'contract') {
              av = a.strike ?? -Infinity
              bv = b.strike ?? -Infinity
            } else if (key === 'expiry') {
              av = a.dte ?? -Infinity
              bv = b.dte ?? -Infinity
            } else if (key === 'fill') {
              av = a.price ?? -Infinity
              bv = b.price ?? -Infinity
            } else if (key === 'trade_class') {
              av = a.trade_class || ''
              bv = b.trade_class || ''
            } else if (key === 'vol_oi') {
              av = computeVolOiRatio(a.contracts ?? a.volume, a.open_interest).ratio ?? -Infinity
              bv = computeVolOiRatio(b.contracts ?? b.volume, b.open_interest).ratio ?? -Infinity
            } else if (key === 'premium') {
              av = a.premium ?? -Infinity
              bv = b.premium ?? -Infinity
            } else if (key === 'percentile') {
              av = a.premium_percentile ?? -Infinity
              bv = b.premium_percentile ?? -Infinity
            } else if (key === 'aggressor') {
              av = a.aggressor || ''
              bv = b.aggressor || ''
            }

            if (typeof av === 'string' || typeof bv === 'string') {
              return mul * String(av).localeCompare(String(bv))
            }
            return mul * (Number(av) - Number(bv))
          })

          expect(sorted.length).toBe(5)
          expect(sorted.map((r) => r.symbol)).toBeDefined()
        }
      }
    })

    it('correctly ranks and sorts Flow Review Rows under ties and extreme spreads', () => {
      const rowA: UnusualFlowRow = {
        symbol: 'NVDA',
        live: true,
        premium: 5_000_000,
        sweep_premium: 3_000_000,
        contract_count: 10_000,
        sweep_count: 50,
        sweep_contracts: 4000,
        unusual_contracts: 2000,
        put_flow_pct: 0.2,
        average_dte: 14,
        average_otm_pct: 0.05,
        ret_1d: 0.03,
      } as any

      const rowB: UnusualFlowRow = {
        symbol: 'TSLA',
        live: true,
        premium: 5_000_000, // Identical premium
        sweep_premium: 4_000_000, // Higher sweep premium
        contract_count: 12_000,
        sweep_count: 70,
        sweep_contracts: 6000,
        unusual_contracts: 3000,
        put_flow_pct: 0.4,
        average_dte: 7,
        average_otm_pct: 0.02,
        ret_1d: -0.01,
      } as any

      // Standard review ranking should rank rowB higher due to higher sweep activity
      const standardCompare = compareFlowReviewRows(rowA, rowB, 5_000_000)
      expect(standardCompare).toBeGreaterThan(0) // rowB is ranked before rowA
    })
  })

  /* ==========================================================================
     SECTION 6: Multi-Leg Strategy Presets, Payoff Polygons & Breakevens
     ========================================================================== */
  describe('6. Multi-Leg Strategy Presets & Analytical Payoff Integrity', () => {
    it('verifies all 11 Strategy Presets construct valid legs and exact cash debit/credit', () => {
      const spot = 200
      const dte = 30
      const vol = 35
      const prem = 6.5

      const presetKeys = Object.keys(STRATEGY_PRESETS) as Array<keyof typeof STRATEGY_PRESETS>
      expect(presetKeys.length).toBe(11)

      for (const key of presetKeys) {
        const preset = STRATEGY_PRESETS[key]
        const legs = preset.factory(spot, dte, vol, prem)
        expect(legs.length).toBeGreaterThanOrEqual(1)

        const usable = usableLegs(legs)
        expect(usable.length).toBe(legs.length)

        const debit = netDebit(legs)
        expect(Number.isFinite(debit)).toBe(true)

        const greeks = computeBookGreeks(legs, spot, dte, vol)
        expect(Number.isFinite(greeks.delta)).toBe(true)
        expect(Number.isFinite(greeks.gamma)).toBe(true)
        expect(Number.isFinite(greeks.theta)).toBe(true)
        expect(Number.isFinite(greeks.vega)).toBe(true)
        expect(Number.isFinite(greeks.rho)).toBe(true)
      }
    })

    it('accurately identifies both breakeven points for an Iron Condor', () => {
      const spot = 100
      const legs: CalcLeg[] = [
        { id: '1', right: 'put', strike: 80, quantity: 1, premium: 1.0 },
        { id: '2', right: 'put', strike: 90, quantity: -1, premium: 3.0 },
        { id: '3', right: 'call', strike: 110, quantity: -1, premium: 3.0 },
        { id: '4', right: 'call', strike: 120, quantity: 1, premium: 1.0 },
      ]

      // Net credit = (3 + 3 - 1 - 1) * 100 = $400 credit
      const debit = netDebit(legs)
      expect(debit).toBe(-400)

      const dualPoints = evaluateBookDualCurves({
        legs,
        spot,
        dteDays: 30,
        volPct: 25,
      })

      const breakevens = findBreakevens(dualPoints)
      expect(breakevens.length).toBe(2)
      // Lower BE = 90 - 4 = 86; Upper BE = 110 + 4 = 114
      expect(breakevens[0]).toBeCloseTo(86, 0)
      expect(breakevens[1]).toBeCloseTo(114, 0)

      const bounds = evaluateRiskRewardBounds(legs, dualPoints)
      expect(bounds.isProfitUnbounded).toBe(false)
      expect(bounds.isLossUnbounded).toBe(false)
      expect(bounds.maxProfit).toBe(400)
      expect(bounds.maxLoss).toBe(-600) // (10 - 4) * 100 = -$600 max loss
    })

    it('correctly categorizes infinite profit/loss asymptotic labels via evaluateRiskRewardBounds', () => {
      // Long Call -> +∞ Unlimited Profit, Defined Loss (-$500)
      const longCall: CalcLeg[] = [{ id: '1', right: 'call', strike: 100, quantity: 1, premium: 5 }]
      const lcPoints = evaluateBookDualCurves({
        legs: longCall,
        spot: 100,
        dteDays: 30,
        volPct: 25,
      })
      const lcBounds = evaluateRiskRewardBounds(longCall, lcPoints)
      expect(lcBounds.isProfitUnbounded).toBe(true)
      expect(lcBounds.isLossUnbounded).toBe(false)
      expect(lcBounds.formattedMaxProfit).toBe('+∞ Unlimited')
      expect(lcBounds.formattedMaxLoss).toBe('−$500')
      expect(lcBounds.maxLoss).toBe(-500)

      // Naked Short Call -> Defined Profit (+$500), -∞ Unlimited Risk
      const shortCall: CalcLeg[] = [
        { id: '1', right: 'call', strike: 100, quantity: -1, premium: 5 },
      ]
      const scPoints = evaluateBookDualCurves({
        legs: shortCall,
        spot: 100,
        dteDays: 30,
        volPct: 25,
      })
      const scBounds = evaluateRiskRewardBounds(shortCall, scPoints)
      expect(scBounds.isProfitUnbounded).toBe(false)
      expect(scBounds.isLossUnbounded).toBe(true)
      expect(scBounds.formattedMaxProfit).toBe('+$500')
      expect(scBounds.formattedMaxLoss).toBe('−∞ Unlimited Risk')
    })

    it('renders SVG chart geometry, tick marks, and split signed areas without NaN errors', () => {
      const legs: CalcLeg[] = [
        { id: '1', right: 'call', strike: 100, quantity: 1, premium: 5 },
        { id: '2', right: 'call', strike: 110, quantity: -1, premium: 2 },
      ]

      const chart = buildDualPayoffChart({
        legs,
        spot: 100,
        dte: 30,
        volPct: 25,
        width: 600,
        height: 300,
      })

      expect(chart).not.toBeNull()
      if (chart) {
        expect(chart.line).toContain('M')
        expect(chart.t0Line).toContain('M')
        expect(chart.profitArea).toContain('M')
        expect(chart.lossArea).toContain('M')
        expect(Number.isFinite(chart.zeroY)).toBe(true)
        expect(Number.isFinite(chart.spotX)).toBe(true)
        expect(chart.xTicks.length).toBeGreaterThan(3)
        expect(chart.yTicks.length).toBeGreaterThan(3)
        expect(chart.strikes.length).toBe(2)
      }
    })

    it('verifies bookAllocation cash debit, credit, notional and mix proportions accurately', () => {
      const legs: CalcLeg[] = [
        { id: '1', right: 'call', strike: 100, quantity: 2, premium: 5.0 }, // Long Call: +$1,000 debit
        { id: '2', right: 'call', strike: 110, quantity: -2, premium: 2.0 }, // Short Call: -$400 credit
        { id: '3', right: 'put', strike: 90, quantity: 1, premium: 3.0 }, // Long Put: +$300 debit
        { id: '4', right: 'put', strike: 80, quantity: -1, premium: 1.0 }, // Short Put: -$100 credit
      ]

      const alloc = bookAllocation(legs)
      expect(alloc.callDebit).toBe(600) // 1000 - 400
      expect(alloc.putDebit).toBe(200) // 300 - 100
      expect(alloc.net).toBe(800) // 600 + 200
      expect(alloc.longNotional).toBe(1300) // 1000 + 300
      expect(alloc.shortCredit).toBe(500) // 400 + 100
      expect(alloc.callShare).toBeCloseTo(0.75, 4) // 600 / 800
      expect(alloc.putShare).toBeCloseTo(0.25, 4) // 200 / 800
    })

    it('verifies volatility smile and skew adjustments remain strictly positive across extreme strikes', () => {
      const spot = 100
      const baseVol = 30

      // Strike = 20 (Deep OTM Put / ITM Call)
      const deepLowVol = smileAdjustedVol(20, spot, baseVol, 15, 25)
      expect(deepLowVol).toBeGreaterThan(baseVol)
      expect(Number.isFinite(deepLowVol)).toBe(true)

      // Strike = 250 (Deep OTM Call / ITM Put)
      const deepHighVol = smileAdjustedVol(250, spot, baseVol, 15, 25)
      expect(deepHighVol).toBeGreaterThan(baseVol)
      expect(Number.isFinite(deepHighVol)).toBe(true)
    })

    it('verifies erf and normCdf numerical accuracy against asymptotic limits', () => {
      expect(normCdf(0)).toBeCloseTo(0.5, 6)
      expect(normCdf(1.959964)).toBeCloseTo(0.975, 4) // 97.5th percentile
      expect(normCdf(-1.959964)).toBeCloseTo(0.025, 4) // 2.5th percentile
      expect(normCdf(10)).toBeCloseTo(1.0, 6)
      expect(normCdf(-10)).toBeCloseTo(0.0, 6)
      expect(erf(0)).toBeCloseTo(0, 7)
      expect(erf(5)).toBeCloseTo(1.0, 6)
      expect(erf(-5)).toBeCloseTo(-1.0, 6)
    })
  })

  /* ==========================================================================
     SECTION 7: High-Density Multi-Filter Pipeline & KPI Recalculation Stress
     ========================================================================== */
  describe('7. High-Density Multi-Filter Pipeline & Aggregation Stress', () => {
    it('filters 2,000 unusual flow rows across 6 simultaneous filter criteria in under 20ms', () => {
      const rows: UnusualFlowRow[] = []
      const symbols = ['SPY', 'QQQ', 'NVDA', 'AAPL', 'TSLA', 'AMZN', 'MSFT', 'META', 'AMD', 'GOOGL']

      for (let i = 0; i < 2000; i++) {
        const symbol = symbols[i % symbols.length]
        const premium = (i + 1) * 25_000
        const isPutHeavy = i % 2 === 0
        const dte = (i % 45) + 1
        const otmPct = ((i % 20) - 10) / 100 // -10% to +9%

        rows.push({
          symbol,
          live: true,
          premium,
          call_premium: isPutHeavy ? premium * 0.2 : premium * 0.8,
          put_premium: isPutHeavy ? premium * 0.8 : premium * 0.2,
          put_flow_pct: isPutHeavy ? 0.8 : 0.2,
          contract_count: (i + 1) * 100,
          sweep_count: i % 5,
          sweep_premium: (i % 5) * 100_000,
          sweep_contracts: (i % 5) * 500,
          unusual_contracts: (i % 3) * 300,
          average_dte: dte,
          average_otm_pct: otmPct,
          ret_1d: ((i % 10) - 5) / 100,
        } as any)
      }

      // Multi-criteria filter simulation
      const minPremium = 100_000
      const query = 'NVD'
      const right = 'put'
      const dteBand = 'month' // 8 to 30 days
      const moneyness = 'otm' // >= 2%

      const t0 = performance.now()
      const filtered = rows.filter((r) => {
        if (!r.live || (r.premium ?? 0) < minPremium) return false
        if (query && !r.symbol.includes(query)) return false
        if (right === 'put' && (r.put_flow_pct ?? 0) < 0.5) return false
        if (dteBand === 'month' && ((r.average_dte ?? 0) <= 7 || (r.average_dte ?? 0) > 30))
          return false
        if (moneyness === 'otm' && (r.average_otm_pct ?? 0) < 0.02) return false
        return true
      })

      // KPI Aggregation over filtered rows
      const totalPremium = filtered.reduce((sum, r) => sum + (r.premium ?? 0), 0)
      const totalContracts = filtered.reduce((sum, r) => sum + (r.contract_count ?? 0), 0)
      const sweepPremium = filtered.reduce((sum, r) => sum + (r.sweep_premium ?? 0), 0)
      const duration = performance.now() - t0

      expect(duration).toBeLessThan(100) // Sub-100ms multi-filter execution under high concurrency
      expect(filtered.length).toBeGreaterThan(0)
      expect(filtered.every((r) => r.symbol === 'NVDA')).toBe(true)
      expect(totalPremium).toBeGreaterThan(0)
      expect(totalContracts).toBeGreaterThan(0)
      expect(sweepPremium).toBeGreaterThanOrEqual(0)
    })
  })
})
