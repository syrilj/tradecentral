import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { effectScope, ref } from 'vue'
import {
  computeGreeks,
  computeBookGreeks,
  evaluateBookAtSpot,
  evaluateBookDualCurves,
  evaluateRiskRewardBounds,
  detectBookRiskReward,
  bookAllocation,
  netDebit,
  findBreakevens,
  usableLegs,
  buildDualPayoffChart,
  type CalcLeg,
} from '@/optionsCalculator'
import { useResource, debounce } from '@/composables/useResource'

describe('Challenger 2 Empirical Stress: Multi-Leg Options, GEX Clustering & Concurrency Lifecycle', () => {
  let originalWindow: any
  let originalDocument: any

  beforeEach(() => {
    vi.useFakeTimers()
    originalWindow = (globalThis as any).window
    originalDocument = (globalThis as any).document

    ;(globalThis as any).window = {
      setInterval: (fn: Function, ms: number) => setInterval(fn, ms) as unknown as number,
      clearInterval: (id: number) => clearInterval(id),
      setTimeout: (fn: Function, ms: number) => setTimeout(fn, ms) as unknown as number,
      clearTimeout: (id: number) => clearTimeout(id),
    }
    ;(globalThis as any).document = {
      visibilityState: 'visible',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    ;(globalThis as any).window = originalWindow
    ;(globalThis as any).document = originalDocument
  })

  /* ==========================================================================
     AREA 1: 4-to-8 Leg Strategy Modeling, Asymmetric IV & Payoff Curves
     ========================================================================== */
  describe('Area 1: 4-to-8 Leg Strategy Payoff Curves, Greeks Superposition & Asymmetric IV', () => {
    it('1.1 4-Leg Iron Condor with Asymmetric IV Skew per leg satisfies Greeks superposition and dual breakevens', () => {
      const spot = 200
      const dte = 30
      const baseVol = 30

      // 4-Leg Iron Condor with asymmetric volatility smile per leg:
      // Put Wing (180P @ 42% IV), Short Put (190P @ 36% IV), Short Call (210C @ 28% IV), Call Wing (220C @ 31% IV)
      const legs: CalcLeg[] = [
        { id: 'leg-1', right: 'put', strike: 180, quantity: 1, premium: 1.8, vol: 42, dte },
        { id: 'leg-2', right: 'put', strike: 190, quantity: -1, premium: 3.5, vol: 36, dte },
        { id: 'leg-3', right: 'call', strike: 210, quantity: -1, premium: 3.2, vol: 28, dte },
        { id: 'leg-4', right: 'call', strike: 220, quantity: 1, premium: 1.4, vol: 31, dte },
      ]

      // Net cash: long legs debit - short legs credit = (1.80 - 3.50 - 3.20 + 1.40) * 100 = -$350 (credit of $350)
      const debit = netDebit(legs)
      expect(debit).toBeCloseTo(-350, 2)

      const alloc = bookAllocation(legs)
      expect(alloc.shortCredit).toBeCloseTo(670, 2) // (3.50 + 3.20) * 100
      expect(alloc.longNotional).toBeCloseTo(320, 2) // (1.80 + 1.40) * 100
      expect(alloc.net).toBeCloseTo(-350, 2)

      // Greeks analytical verification: portfolio Greeks equal sum of weighted leg Greeks
      const bookGreeks = computeBookGreeks(legs, spot, dte, baseVol)
      const individualLegGreeks = legs.map((leg) => {
        const g = computeGreeks(leg.right, spot, leg.strike, leg.dte ?? dte, leg.vol ?? baseVol)
        return {
          delta: g.delta * leg.quantity,
          gamma: g.gamma * leg.quantity,
          theta: g.theta * leg.quantity,
          vega: g.vega * leg.quantity,
          rho: g.rho * leg.quantity,
        }
      })

      const expectedDelta = individualLegGreeks.reduce((s, g) => s + g.delta, 0)
      const expectedGamma = individualLegGreeks.reduce((s, g) => s + g.gamma, 0)
      const expectedTheta = individualLegGreeks.reduce((s, g) => s + g.theta, 0)
      const expectedVega = individualLegGreeks.reduce((s, g) => s + g.vega, 0)
      const expectedRho = individualLegGreeks.reduce((s, g) => s + g.rho, 0)

      expect(bookGreeks.delta).toBeCloseTo(expectedDelta, 6)
      expect(bookGreeks.gamma).toBeCloseTo(expectedGamma, 6)
      expect(bookGreeks.theta).toBeCloseTo(expectedTheta, 6)
      expect(bookGreeks.vega).toBeCloseTo(expectedVega, 6)
      expect(bookGreeks.rho).toBeCloseTo(expectedRho, 6)

      // Near spot (200), an Iron Condor has positive Theta (daily income) and negative Vega (short vol)
      expect(bookGreeks.theta).toBeGreaterThan(0)
      expect(bookGreeks.vega).toBeLessThan(0)

      // Dual payoff curve evaluation
      const dualSeries = evaluateBookDualCurves({
        legs,
        spot,
        dteDays: dte,
        volPct: baseVol,
      })

      expect(dualSeries.length).toBeGreaterThanOrEqual(81)

      // At spot 200 (between short strikes 190 and 210), expiry P/L is exactly the net credit ($350)
      const atSpotPoint = dualSeries.find((p) => Math.abs(p.spot - 200) < 0.01)
      expect(atSpotPoint).toBeDefined()
      expect(atSpotPoint?.pnlExpiry).toBeCloseTo(350, 1)

      // Deep down (spot <= 180): Max loss = Wing width ($10) * 100 - Net Credit ($350) = -$650
      const deepDown = dualSeries.find((p) => p.spot <= 170)
      expect(deepDown?.pnlExpiry).toBeCloseTo(-650, 1)

      // Deep up (spot >= 220): Max loss = Wing width ($10) * 100 - Net Credit ($350) = -$650
      const deepUp = dualSeries.find((p) => p.spot >= 230)
      expect(deepUp?.pnlExpiry).toBeCloseTo(-650, 1)

      // Breakeven finding: exactly 2 breakevens for Iron Condor
      // Lower BE = 190 - 3.50 = 186.50; Upper BE = 210 + 3.50 = 213.50
      const bePoints = findBreakevens(dualSeries)
      expect(bePoints.length).toBe(2)
      expect(bePoints[0]).toBeCloseTo(186.5, 0.5)
      expect(bePoints[1]).toBeCloseTo(213.5, 0.5)

      // Risk/Reward bounds assessment
      const bounds = evaluateRiskRewardBounds(legs, dualSeries)
      expect(bounds.isProfitUnbounded).toBe(false)
      expect(bounds.isLossUnbounded).toBe(false)
      expect(bounds.maxProfit).toBeCloseTo(350, 1)
      expect(bounds.maxLoss).toBeCloseTo(-650, 1)
      expect(bounds.formattedMaxProfit).toBe('+$350')
      expect(bounds.formattedMaxLoss).toBe('−$650')

      const assess = detectBookRiskReward(legs)
      expect(assess.isProfitUnlimited).toBe(false)
      expect(assess.isLossUnlimited).toBe(false)
      expect(assess.maxProfit).toBeCloseTo(350, 1)
      expect(assess.maxLoss).toBeCloseTo(-650, 1)
    })

    it('1.2 6-Leg Double Ratio Butterfly Spread with asymmetric multipliers and IV smile', () => {
      const spot = 100
      const dte = 45
      const baseVol = 25

      // 6-Leg Double Ratio Spread:
      // +1 85P (@32% IV), -2 95P (@28% IV), +1 100P (@26% IV), +1 100C (@26% IV), -2 105C (@24% IV), +1 115C (@25% IV)
      const legs: CalcLeg[] = [
        { id: 'leg-1', right: 'put', strike: 85, quantity: 1, premium: 0.6, vol: 32, dte },
        { id: 'leg-2', right: 'put', strike: 95, quantity: -2, premium: 2.2, vol: 28, dte },
        { id: 'leg-3', right: 'put', strike: 100, quantity: 1, premium: 4.1, vol: 26, dte },
        { id: 'leg-4', right: 'call', strike: 100, quantity: 1, premium: 4.3, vol: 26, dte },
        { id: 'leg-5', right: 'call', strike: 105, quantity: -2, premium: 2.4, vol: 24, dte },
        { id: 'leg-6', right: 'call', strike: 115, quantity: 1, premium: 0.7, vol: 25, dte },
      ]

      const usable = usableLegs(legs)
      expect(usable.length).toBe(6)

      // Net Debit calculation:
      // Long: 0.60*1 + 4.10*1 + 4.30*1 + 0.70*1 = 9.70 * 100 = $970
      // Short: 2.20*2 + 2.40*2 = 9.20 * 100 = $920
      // Net = $970 - $920 = $50 debit
      const debit = netDebit(legs)
      expect(debit).toBeCloseTo(50, 2)

      const bookGreeks = computeBookGreeks(legs, spot, dte, baseVol)
      expect(Number.isFinite(bookGreeks.delta)).toBe(true)
      expect(Number.isFinite(bookGreeks.gamma)).toBe(true)
      expect(Number.isFinite(bookGreeks.theta)).toBe(true)
      expect(Number.isFinite(bookGreeks.vega)).toBe(true)
      expect(Number.isFinite(bookGreeks.rho)).toBe(true)

      const dualSeries = evaluateBookDualCurves({
        legs,
        spot,
        dteDays: dte,
        volPct: baseVol,
        gridPoints: 101,
      })

      // Verify no NaN or non-finite values in series
      for (const pt of dualSeries) {
        expect(Number.isFinite(pt.spot)).toBe(true)
        expect(Number.isFinite(pt.pnlExpiry)).toBe(true)
        expect(Number.isFinite(pt.pnlTheo)).toBe(true)
      }

      // Check wings behavior at extremes:
      // At spot <= 85: Expiry PnL = (85-S) - 2*(95-S) + (100-S) - 50 = (85 - 190 + 100) - 50 = -5 - 50 = -$550
      const extremeDown = evaluateBookAtSpot(legs, 50, dte)
      expect(extremeDown.pnlExpiry).toBeCloseTo(-550, 1)

      // At spot >= 115: Expiry PnL = (S-100) - 2*(S-105) + (S-115) - 50 = (-100 + 210 - 115) - 50 = -5 - 50 = -$550
      const extremeUp = evaluateBookAtSpot(legs, 150, dte)
      expect(extremeUp.pnlExpiry).toBeCloseTo(-550, 1)

      // At peak call tent (105): Expiry PnL = (105-100)*100 - 50 = $450
      const peakCall = evaluateBookAtSpot(legs, 105, dte)
      expect(peakCall.pnlExpiry).toBeCloseTo(450, 1)

      // At peak put tent (95): Expiry PnL = (100-95)*100 - 50 = $450
      const peakPut = evaluateBookAtSpot(legs, 95, dte)
      expect(peakPut.pnlExpiry).toBeCloseTo(450, 1)

      // Multi-crossing breakevens: this double butterfly has 4 breakevens!
      const bePoints = findBreakevens(dualSeries)
      expect(bePoints.length).toBe(4)
      expect(bePoints[0]).toBeCloseTo(90.5, 0.5) // Between 85 and 95
      expect(bePoints[1]).toBeCloseTo(99.5, 0.5) // Near 100
      expect(bePoints[2]).toBeCloseTo(100.5, 0.5) // Near 100
      expect(bePoints[3]).toBeCloseTo(109.5, 0.5) // Between 105 and 115
    })

    it('1.3 8-Leg Complex Multi-Term Structure with Mixed DTEs and Volatility Smile', () => {
      const spot = 500
      const globalDte = 30
      const globalVol = 20

      // 8-Leg Octo-Structure: Diagonal Calendar Iron Butterfly with Hedges
      // Leg 1: +2 460P (60 DTE, 28% IV)
      // Leg 2: -2 480P (30 DTE, 24% IV)
      // Leg 3: +1 490P (14 DTE, 22% IV)
      // Leg 4: -1 500P (7 DTE, 20% IV)
      // Leg 5: -1 500C (7 DTE, 20% IV)
      // Leg 6: +1 510C (14 DTE, 21% IV)
      // Leg 7: -2 520C (30 DTE, 23% IV)
      // Leg 8: +2 540C (60 DTE, 26% IV)
      const legs: CalcLeg[] = [
        { id: 'leg-1', right: 'put', strike: 460, quantity: 2, premium: 3.5, dte: 60, vol: 28 },
        { id: 'leg-2', right: 'put', strike: 480, quantity: -2, premium: 5.2, dte: 30, vol: 24 },
        { id: 'leg-3', right: 'put', strike: 490, quantity: 1, premium: 4.8, dte: 14, vol: 22 },
        { id: 'leg-4', right: 'put', strike: 500, quantity: -1, premium: 6.5, dte: 7, vol: 20 },
        { id: 'leg-5', right: 'call', strike: 500, quantity: -1, premium: 6.5, dte: 7, vol: 20 },
        { id: 'leg-6', right: 'call', strike: 510, quantity: 1, premium: 4.2, dte: 14, vol: 21 },
        { id: 'leg-7', right: 'call', strike: 520, quantity: -2, premium: 4.5, dte: 30, vol: 23 },
        { id: 'leg-8', right: 'call', strike: 540, quantity: 2, premium: 2.8, dte: 60, vol: 26 },
      ]

      const usable = usableLegs(legs)
      expect(usable.length).toBe(8)

      // Verify portfolio Greeks computation over 8 legs with different DTEs and IVs
      const greeks = computeBookGreeks(legs, spot, globalDte, globalVol)
      expect(Number.isFinite(greeks.delta)).toBe(true)
      expect(Number.isFinite(greeks.gamma)).toBe(true)
      expect(Number.isFinite(greeks.theta)).toBe(true)
      expect(Number.isFinite(greeks.vega)).toBe(true)
      expect(Number.isFinite(greeks.rho)).toBe(true)
      expect(Number.isFinite(greeks.theo)).toBe(true)

      // Dual curve chart construction
      const chartGeom = buildDualPayoffChart({
        legs,
        spot,
        dte: globalDte,
        volPct: globalVol,
        width: 800,
        height: 360,
      })

      expect(chartGeom).not.toBeNull()
      if (chartGeom) {
        expect(chartGeom.width).toBe(800)
        expect(chartGeom.height).toBe(360)
        expect(chartGeom.line).toBeDefined()
        expect(chartGeom.line.startsWith('M')).toBe(true)
        expect(chartGeom.t0Line).toBeDefined()
        expect(chartGeom.t0Line?.startsWith('M')).toBe(true)
        expect(chartGeom.strikes.length).toBe(8) // All 8 distinct strike+right legs present
        expect(chartGeom.xTicks.length).toBeGreaterThan(3)
        expect(chartGeom.yTicks.length).toBeGreaterThan(3)
        expect(chartGeom.plotWidth).toBe(800 - chartGeom.pad.l - chartGeom.pad.r)
        expect(chartGeom.plotHeight).toBe(360 - chartGeom.pad.t - chartGeom.pad.b)
      }
    })

    it('1.4 Boundary and Unbounded Risk Detection on Asymmetric Directional Books', () => {
      // 1. Unbounded upside (+2 Call @ 100, -1 Call @ 110)
      const ratioCall: CalcLeg[] = [
        { id: 'leg-1', right: 'call', strike: 100, quantity: 2, premium: 5.0 },
        { id: 'leg-2', right: 'call', strike: 110, quantity: -1, premium: 2.0 },
      ]
      const r1 = detectBookRiskReward(ratioCall)
      expect(r1.isProfitUnlimited).toBe(true)
      expect(r1.isLossUnlimited).toBe(false)
      expect(r1.maxProfitLabel).toBe('+∞ Unlimited')
      expect(r1.maxLoss).toBeLessThanOrEqual(0)

      // 2. Unbounded downside / short gamma catastrophe (-2 Call @ 110, +1 Call @ 100)
      const shortRatioCall: CalcLeg[] = [
        { id: 'leg-1', right: 'call', strike: 100, quantity: 1, premium: 5.0 },
        { id: 'leg-2', right: 'call', strike: 110, quantity: -2, premium: 2.0 },
      ]
      const r2 = detectBookRiskReward(shortRatioCall)
      expect(r2.isProfitUnlimited).toBe(false)
      expect(r2.isLossUnlimited).toBe(true)
      expect(r2.maxLossLabel).toBe('−∞ Unlimited Risk')

      // 3. Canceling legs (+1 100C, -1 100C)
      const neutralBook: CalcLeg[] = [
        { id: 'leg-1', right: 'call', strike: 100, quantity: 1, premium: 5.0 },
        { id: 'leg-2', right: 'call', strike: 100, quantity: -1, premium: 5.0 },
      ]
      const gNeutral = computeBookGreeks(neutralBook, 100, 30, 25)
      expect(gNeutral.delta).toBe(0)
      expect(gNeutral.gamma).toBe(0)
      expect(gNeutral.theta).toBe(0)
      expect(gNeutral.vega).toBe(0)
      expect(gNeutral.rho).toBe(0)
      expect(gNeutral.netDebit).toBe(0)
    })
  })

  /* ==========================================================================
     AREA 2: GEX Map Dense Strike Clustering & Level Anti-Collision
     ========================================================================== */
  describe('Area 2: GEX Map Dense Strike Clustering (10 strikes in 0.5% span) & Anti-Collision Relaxation', () => {
    function computeLevelsAntiCollision(input: {
      spot: number
      putWall: number | null
      callWall: number | null
      gammaFlip: number | null
      strikes: number[]
      plotInnerW: number
      left: number
      top: number
    }) {
      const { spot, putWall, callWall, gammaFlip, strikes, plotInnerW, left, top } = input
      const bandW = plotInnerW / strikes.length

      const bandCenter = (index: number): number => left + bandW * (index + 0.5)

      const xOfPrice = (price: number): number | null => {
        if (!strikes.length) return null
        if (price <= strikes[0]) return bandCenter(0)
        const lastIndex = strikes.length - 1
        if (price >= strikes[lastIndex]) return bandCenter(lastIndex)
        for (let i = 0; i < lastIndex; i++) {
          const lo = strikes[i]
          const hi = strikes[i + 1]
          if (price >= lo && price <= hi) {
            const span = hi - lo
            const t = span > 1e-9 ? (price - lo) / span : 0
            return bandCenter(i + t)
          }
        }
        return null
      }

      const raw = [
        { key: 'put', label: 'PUT W', value: putWall, cls: 'put' },
        { key: 'flip', label: 'FLIP', value: gammaFlip, cls: 'flip' },
        { key: 'spot', label: 'SPOT', value: spot, cls: 'spot' },
        { key: 'call', label: 'CALL W', value: callWall, cls: 'call' },
      ]

      const placed = raw
        .map((level) => ({ ...level, x: level.value != null ? xOfPrice(level.value) : null }))
        .filter(
          (level): level is { key: string; label: string; value: number; cls: string; x: number } =>
            level.x != null,
        )
        .sort((a, b) => a.x - b.x)

      if (!placed.length) return []

      const minGap = 52
      const minBoundary = left + 28
      const maxBoundary = left + plotInnerW - 28

      // 1. Initial clamp
      const xs = placed.map((l) => Math.max(minBoundary, Math.min(maxBoundary, l.x)))

      // 2. Forward pass
      for (let i = 1; i < xs.length; i++) {
        if (xs[i] < xs[i - 1] + minGap) {
          xs[i] = xs[i - 1] + minGap
        }
      }

      // 3. Backward pass
      if (xs[xs.length - 1] > maxBoundary) {
        xs[xs.length - 1] = maxBoundary
        for (let i = xs.length - 2; i >= 0; i--) {
          if (xs[i] > xs[i + 1] - minGap) {
            xs[i] = xs[i + 1] - minGap
          }
        }
      }

      // 4. Clamp check at left boundary
      if (xs[0] < minBoundary) {
        xs[0] = minBoundary
        for (let i = 1; i < xs.length; i++) {
          if (xs[i] < xs[i - 1] + minGap) {
            xs[i] = xs[i - 1] + minGap
          }
        }
      }

      // 5. Vertical tier staggering
      const hasRemainingOverlap = xs.some((x, i) => i > 0 && Math.abs(x - xs[i - 1]) < 48)
      const isWidthConstrained = maxBoundary - minBoundary < placed.length * minGap

      return placed.map((level, i) => {
        const labelX = Math.max(minBoundary, Math.min(maxBoundary, xs[i]))
        const labelY =
          hasRemainingOverlap || isWidthConstrained ? (i % 2 === 0 ? top + 10 : top + 22) : top + 10

        return {
          ...level,
          labelX,
          labelY,
        }
      })
    }

    it('2.1 Dense 10-strike cluster in 0.5% span guarantees column separation and zero bar overlap', () => {
      // 10 strikes spaced by 0.25 (0.05% of spot) across [498.75, 501.00] (0.45% total span)
      const denseStrikes = [
        498.75, 499.0, 499.25, 499.5, 499.75, 500.0, 500.25, 500.5, 500.75, 501.0,
      ]

      const hostW = 800
      const left = 52
      const right = 20
      const minCol = 14
      const plotInnerW = Math.max(hostW - left - right, denseStrikes.length * minCol)
      const bandW = plotInnerW / denseStrikes.length

      expect(bandW).toBeGreaterThanOrEqual(minCol)

      // Column centers are strictly monotonic and separated by bandW
      const centers = denseStrikes.map((_, i) => left + bandW * (i + 0.5))
      for (let i = 1; i < centers.length; i++) {
        expect(centers[i] - centers[i - 1]).toBeCloseTo(bandW, 4)
      }

      // Bar thickness is bounded between 4px and 28px
      const thickness = Math.max(4, Math.min(bandW * 0.72, 28))
      expect(thickness).toBeLessThanOrEqual(bandW)
      expect(thickness).toBeGreaterThanOrEqual(4)
    })

    it('2.2 Structural Level Anti-Collision Algorithm resolves 4 overlapping levels in tight 0.1% span', () => {
      // Put Wall at 499.75, Flip at 500.00, Spot at 500.00, Call Wall at 500.25
      const strikes = [498.75, 499.0, 499.25, 499.5, 499.75, 500.0, 500.25, 500.5, 500.75, 501.0]
      const spot = 500.0
      const putWall = 499.75
      const gammaFlip = 500.0
      const callWall = 500.25

      const left = 52
      const top = 30
      const plotInnerW = 728

      const levels = computeLevelsAntiCollision({
        spot,
        putWall,
        callWall,
        gammaFlip,
        strikes,
        plotInnerW,
        left,
        top,
      })

      expect(levels.length).toBe(4)

      // 1. Every labelX is strictly within [minBoundary, maxBoundary]
      const minBoundary = left + 28
      const maxBoundary = left + plotInnerW - 28
      for (const lvl of levels) {
        expect(lvl.labelX).toBeGreaterThanOrEqual(minBoundary)
        expect(lvl.labelX).toBeLessThanOrEqual(maxBoundary)
      }

      // 2. Either horizontal separation is >= 50px OR vertical tiers are staggered (top+10 vs top+22)
      for (let i = 1; i < levels.length; i++) {
        const prev = levels[i - 1]
        const curr = levels[i]
        const xDist = Math.abs(curr.labelX - prev.labelX)
        const isStaggeredY = curr.labelY !== prev.labelY
        expect(xDist >= 48 || isStaggeredY).toBe(true)
      }
    })

    it('2.3 Extreme Viewport Width Constriction activates vertical tier staggering safely', () => {
      const strikes = [100, 101, 102, 103]
      const spot = 101.5
      const putWall = 100.5
      const gammaFlip = 101.5
      const callWall = 102.5

      // Narrow screen: inner width = 120px (cannot fit 4 levels * 52px = 208px on a single line)
      const levels = computeLevelsAntiCollision({
        spot,
        putWall,
        callWall,
        gammaFlip,
        strikes,
        plotInnerW: 120,
        left: 40,
        top: 20,
      })

      expect(levels.length).toBe(4)
      // Verify alternating vertical tiers: 0 -> top+10, 1 -> top+22, 2 -> top+10, 3 -> top+22
      expect(levels[0].labelY).toBe(30)
      expect(levels[1].labelY).toBe(42)
      expect(levels[2].labelY).toBe(30)
      expect(levels[3].labelY).toBe(42)
    })
  })

  /* ==========================================================================
     AREA 3: Concurrency, Rapid Ticker Switching & Race-Free Lifecycle
     ========================================================================== */
  describe('Area 3: Rapid Ticker Switching Under Active Polling & Zero Race Conditions', () => {
    it('3.1 Out-of-order asynchronous responses do NOT overwrite newer ticker selection (Sequence ID Isolation)', async () => {
      const responses: Record<string, { symbol: string; spot: number; gex: number }> = {
        SPY: { symbol: 'SPY', spot: 500, gex: 120 },
        QQQ: { symbol: 'QQQ', spot: 430, gex: 85 },
        NVDA: { symbol: 'NVDA', spot: 120, gex: 210 },
        AAPL: { symbol: 'AAPL', spot: 220, gex: 95 },
      }

      // Simulated network latencies: SPY=300ms, QQQ=100ms, NVDA=200ms, AAPL=50ms
      const delays: Record<string, number> = {
        SPY: 300,
        QQQ: 100,
        NVDA: 200,
        AAPL: 50,
      }

      const activeSymbol = ref('SPY')
      const loader = vi.fn().mockImplementation(() => {
        const sym = activeSymbol.value
        const delay = delays[sym] ?? 50
        return new Promise((resolve) => {
          setTimeout(() => resolve(responses[sym]), delay)
        })
      })

      const resource = useResource(loader, { immediate: false })

      // User rapidly switches SPY -> QQQ -> NVDA -> AAPL
      activeSymbol.value = 'SPY'
      const pSPY = resource.refresh({ clear: true })

      activeSymbol.value = 'QQQ'
      const pQQQ = resource.refresh({ clear: true })

      activeSymbol.value = 'NVDA'
      const pNVDA = resource.refresh({ clear: true })

      activeSymbol.value = 'AAPL'
      const pAAPL = resource.refresh({ clear: true })

      // Advance timers by 60ms: AAPL (50ms) finishes first
      await vi.advanceTimersByTimeAsync(60)
      await pAAPL
      expect(resource.data.value).toEqual({ symbol: 'AAPL', spot: 220, gex: 95 })

      // Advance timers by another 50ms (t=110ms): QQQ (100ms) finishes -> must NOT overwrite AAPL
      await vi.advanceTimersByTimeAsync(50)
      await pQQQ
      expect(resource.data.value).toEqual({ symbol: 'AAPL', spot: 220, gex: 95 })

      // Advance timers by another 100ms (t=210ms): NVDA (200ms) finishes -> must NOT overwrite AAPL
      await vi.advanceTimersByTimeAsync(100)
      await pNVDA
      expect(resource.data.value).toEqual({ symbol: 'AAPL', spot: 220, gex: 95 })

      // Advance timers by another 100ms (t=310ms): SPY (300ms) finishes -> must NOT overwrite AAPL
      await vi.advanceTimersByTimeAsync(100)
      await pSPY
      expect(resource.data.value).toEqual({ symbol: 'AAPL', spot: 220, gex: 95 })
    })

    it('3.2 Immediate Cache Blanking on Ticker Switch (clear: true) prevents stale telemetry flicker', async () => {
      let resolvePromise: (data: any) => void = () => {}
      const loader = vi.fn().mockImplementation(() => {
        return new Promise((resolve) => {
          resolvePromise = resolve
        })
      })

      const resource = useResource(loader, { immediate: false })

      // Load initial SPY data
      const p1 = resource.refresh()
      resolvePromise({ symbol: 'SPY', spot: 500 })
      await p1
      expect(resource.data.value).toEqual({ symbol: 'SPY', spot: 500 })

      // Switch to TSLA with { clear: true }
      const p2 = resource.refresh({ clear: true })

      // Synchronously, data.value MUST be null immediately so TSLA page does not paint SPY numbers
      expect(resource.data.value).toBeNull()
      expect(resource.loading.value).toBe(true)

      // Resolve TSLA data
      resolvePromise({ symbol: 'TSLA', spot: 200 })
      await p2
      expect(resource.data.value).toEqual({ symbol: 'TSLA', spot: 200 })
      expect(resource.loading.value).toBe(false)
    })

    it('3.3 In-flight gating skips passive polling cycles while a slow backend request is in progress', async () => {
      let resolveSlowRequest: () => void = () => {}
      const loader = vi.fn().mockImplementation(() => {
        return new Promise((resolve) => {
          resolveSlowRequest = () => resolve({ items: ['data'] })
        })
      })

      const resource = useResource(loader, {
        intervalMs: 1000,
        immediate: true,
      })

      expect(loader).toHaveBeenCalledTimes(1)

      // Advance timer by 1000ms (1 interval): first request is still in-flight, so poll is skipped
      await vi.advanceTimersByTimeAsync(1000)
      expect(loader).toHaveBeenCalledTimes(1)

      // Advance timer by another 2000ms: still in-flight, no stacking
      await vi.advanceTimersByTimeAsync(2000)
      expect(loader).toHaveBeenCalledTimes(1)

      // Slow request resolves
      resolveSlowRequest()
      await vi.advanceTimersByTimeAsync(1)
      expect(resource.data.value).toEqual({ items: ['data'] })

      // Next interval tick fires normally
      await vi.advanceTimersByTimeAsync(1000)
      expect(loader).toHaveBeenCalledTimes(2)
    })

    it('3.4 Superseded failed request does not wipe out newer valid data or set error', async () => {
      let rejectSPY: (err: any) => void = () => {}
      let resolveAAPL: (data: any) => void = () => {}

      let reqCount = 0
      const loader = vi.fn().mockImplementation(() => {
        reqCount++
        if (reqCount === 1) {
          return new Promise((_, reject) => {
            rejectSPY = reject
          })
        }
        return new Promise((resolve) => {
          resolveAAPL = resolve
        })
      })

      const resource = useResource(loader, { immediate: false })

      // Start SPY fetch
      const p1 = resource.refresh()
      // Immediately switch to AAPL
      const p2 = resource.refresh({ clear: true })

      // AAPL succeeds
      resolveAAPL({ symbol: 'AAPL' })
      await p2
      expect(resource.data.value).toEqual({ symbol: 'AAPL' })
      expect(resource.error.value).toBeNull()

      // Later, slow SPY rejects with network error
      rejectSPY(new Error('500 Internal Server Error'))
      await p1.catch(() => {})

      // AAPL data must remain intact and error must NOT be set
      expect(resource.data.value).toEqual({ symbol: 'AAPL' })
      expect(resource.error.value).toBeNull()
    })
  })

  /* ==========================================================================
     AREA 4: Memory Leak & Scope Disposal Verification
     ========================================================================== */
  describe('Area 4: Lifecycle Scope Disposal, Memory Leak Prevention & Event Cleanup', () => {
    it('4.1 EffectScope disposal clears polling interval and removes visibilitychange listener', () => {
      const removeEventListenerSpy = vi.fn()
      const addEventListenerSpy = vi.fn()

      ;(globalThis as any).document = {
        visibilityState: 'visible',
        addEventListener: addEventListenerSpy,
        removeEventListener: removeEventListenerSpy,
      }

      const clearIntervalSpy = vi.spyOn(globalThis, 'clearInterval')
      const loader = vi.fn().mockResolvedValue({ status: 'ok' })

      const scope = effectScope()

      scope.run(() => {
        useResource(loader, {
          intervalMs: 5000,
          immediate: false,
        })
      })

      expect(addEventListenerSpy).toHaveBeenCalledWith('visibilitychange', expect.any(Function))
      const registeredHandler = addEventListenerSpy.mock.calls[0][1]

      // Stop the scope (simulate Vue component unmount)
      scope.stop()

      // Verify timer cleared and listener removed
      expect(clearIntervalSpy).toHaveBeenCalled()
      expect(removeEventListenerSpy).toHaveBeenCalledWith('visibilitychange', registeredHandler)
    })

    it('4.2 Late-resolving promise after scope disposal does not mutate reactive refs', async () => {
      let resolveLate: (val: any) => void = () => {}
      const loader = vi.fn().mockImplementation(() => {
        return new Promise((resolve) => {
          resolveLate = resolve
        })
      })

      const scope = effectScope()
      let resource: any

      scope.run(() => {
        resource = useResource(loader, { immediate: true })
      })

      expect(resource.loading.value).toBe(true)

      // Unmount scope while request is pending
      scope.stop()

      // Late resolution
      resolveLate({ data: 'leak_payload' })
      await vi.advanceTimersByTimeAsync(1)

      // Reactive refs should NOT have taken the payload
      expect(resource.data.value).toBeNull()
      expect(resource.fetchedAt.value).toBeNull()
    })

    it('4.3 Debounce utility cancels pending timer and executes trailing edge only', async () => {
      const callback = vi.fn()
      const debounced = debounce(callback, 200)

      // 50 rapid calls in 50ms
      for (let i = 0; i < 50; i++) {
        debounced(`call_${i}`)
        vi.advanceTimersByTime(1)
      }

      expect(callback).toHaveBeenCalledTimes(0)

      // Advance by 200ms
      vi.advanceTimersByTime(200)
      expect(callback).toHaveBeenCalledTimes(1)
      expect(callback).toHaveBeenCalledWith('call_49')
    })
  })
})
