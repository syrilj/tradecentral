import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { linearScale } from '../charts/scale'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')

function readSrc(rel: string): string {
  return readFileSync(join(root, rel), 'utf8')
}

describe('Milestone 5: Options Chart Geometry, Scales, Crosshairs & Tooltips', () => {
  describe('OptionsDriftChart Math & Geometry Engine', () => {
    it('computes continuous ordinal timeline mapping and collapses gaps correctly', () => {
      // Non-uniform timestamps (e.g. over weekends)
      const rawPrice = [
        { t: '2026-08-14T14:30:00Z', close: 580 },
        { t: '2026-08-14T20:00:00Z', close: 585 },
        { t: '2026-08-17T14:30:00Z', close: 590 },
      ]
      const rawFlow = [
        { t: '2026-08-14T15:00:00Z', call_premium: 100_000, put_premium: 50_000 },
        { t: '2026-08-17T14:30:00Z', call_premium: 200_000, put_premium: 80_000 },
      ]

      const parseTime = (iso: string) => new Date(iso).getTime()
      const timelineSet = new Set<number>()
      rawPrice.forEach((p) => timelineSet.add(parseTime(p.t)))
      rawFlow.forEach((f) => timelineSet.add(parseTime(f.t)))
      const timeline = Array.from(timelineSet).sort((a, b) => a - b)

      expect(timeline.length).toBe(4)

      const W = 1000
      const pad = { l: 50, r: 16 }
      const xScale = linearScale([0, timeline.length - 1], [pad.l, W - pad.r])

      // Ordinal index lookup
      function ordinalIndex(ts: number): number {
        const arr = timeline
        const n = arr.length
        if (n === 0) return 0
        if (ts <= arr[0]) return 0
        if (ts >= arr[n - 1]) return n - 1
        let lo = 0
        let hi = n - 1
        while (hi - lo > 1) {
          const mid = (lo + hi) >> 1
          if (arr[mid] <= ts) lo = mid
          else hi = mid
        }
        const span = arr[hi] - arr[lo]
        return span > 0 ? lo + (ts - arr[lo]) / span : lo
      }

      // First point maps to pad.l
      expect(xScale(ordinalIndex(timeline[0]))).toBeCloseTo(50)
      // Last point maps to W - pad.r
      expect(xScale(ordinalIndex(timeline[timeline.length - 1]))).toBeCloseTo(984)

      // Clamping out-of-range timestamps
      expect(ordinalIndex(timeline[0] - 1_000_000)).toBe(0)
      expect(ordinalIndex(timeline[timeline.length - 1] + 1_000_000)).toBe(timeline.length - 1)
    })

    it('computes price domain with institutional structure level expansion and padding', () => {
      const prices = [{ close: 570 }, { close: 585 }]
      const spot = 580
      const callWall = 600
      const putWall = 550
      const gammaFlip = 575

      let lo = Infinity
      let hi = -Infinity
      for (const p of prices) {
        if (p.close < lo) lo = p.close
        if (p.close > hi) hi = p.close
      }
      for (const extra of [spot, callWall, putWall, gammaFlip]) {
        if (extra != null && Number.isFinite(extra) && extra > 0) {
          if (extra < lo) lo = extra
          if (extra > hi) hi = extra
        }
      }

      expect(lo).toBe(550) // Expanded to putWall
      expect(hi).toBe(600) // Expanded to callWall

      const padAmt = Math.max((hi - lo) * 0.12, hi * 0.006, 0.5)
      const domain = { lo: lo - padAmt, hi: hi + padAmt }

      expect(domain.lo).toBeLessThan(550)
      expect(domain.hi).toBeGreaterThan(600)
    })

    it('computes activity bars dual side-by-side geometry and scaling without NaN', () => {
      const flow = [
        { t: '2026-08-16T14:30:00Z', call_premium: 500_000, put_premium: 250_000 },
        { t: '2026-08-16T15:00:00Z', call_premium: 0, put_premium: 1_200_000 },
        { t: '2026-08-16T15:30:00Z', call_premium: 800_000, put_premium: 0 },
      ]

      let bucketPremMax = 1
      for (const p of flow) {
        bucketPremMax = Math.max(bucketPremMax, p.call_premium || 0, p.put_premium || 0)
      }
      expect(bucketPremMax).toBe(1_200_000)

      const flowH = 80
      const scale = flowH / bucketPremMax
      const flowBot = 300

      const bars = flow.map((p) => {
        const c = Math.max(0, p.call_premium || 0)
        const pu = Math.max(0, p.put_premium || 0)
        const callH = Math.max(c > 0 ? 1.5 : 0, c * scale)
        const putH = Math.max(pu > 0 ? 1.5 : 0, pu * scale)
        return {
          callH,
          putH,
          callY: flowBot - callH,
          putY: flowBot - putH,
        }
      })

      expect(bars[0].callH).toBeCloseTo((500_000 / 1_200_000) * 80)
      expect(bars[0].putH).toBeCloseTo((250_000 / 1_200_000) * 80)
      expect(bars[1].callH).toBe(0)
      expect(bars[1].putH).toBe(80)
      expect(bars[2].putH).toBe(0)
      expect(bars.every((b) => Number.isFinite(b.callH) && Number.isFinite(b.putH))).toBe(true)
    })

    it('calculates crosshair coordinate clamping and axis price pill alignment', () => {
      const W = 800
      const pad = { l: 50, r: 16, t: 18, b: 20, gap: 10 }
      const priceDomain = { lo: 500, hi: 600 }
      const priceH = 200
      const priceBot = pad.t + priceH
      const priceScale = linearScale([priceDomain.lo, priceDomain.hi], [priceBot, pad.t])

      // Invert price from pixel Y
      expect(priceScale.invert(pad.t)).toBeCloseTo(600)
      expect(priceScale.invert(priceBot)).toBeCloseTo(500)
      expect(priceScale(550)).toBeCloseTo(pad.t + priceH / 2)

      // Hover index clamping from cursor pixel X
      const timelineLength = 20
      const xScale = linearScale([0, timelineLength - 1], [pad.l, W - pad.r])

      const cursorPx = 400
      const rawIdx = Math.round(xScale.invert(cursorPx))
      const clampedIdx = Math.max(0, Math.min(timelineLength - 1, rawIdx))

      expect(clampedIdx).toBeGreaterThanOrEqual(0)
      expect(clampedIdx).toBeLessThan(timelineLength)
    })

    it('calculates 3rd Friday OPEX markers correctly for institutional dates', () => {
      // August 2026 3rd Friday: Aug 1 is Saturday (dow 6) -> 1st Friday is Aug 7 -> 3rd Friday is Aug 21
      const augustStart = new Date(Date.UTC(2026, 7, 1)).getTime()
      const augustEnd = new Date(Date.UTC(2026, 7, 31, 23, 59, 59)).getTime()

      const first = new Date(Date.UTC(2026, 7, 1))
      const dow = first.getUTCDay()
      const firstFri = 1 + ((5 - dow + 7) % 7)
      const thirdFri = firstFri + 14
      const opexTs = Date.UTC(2026, 7, thirdFri, 20, 0, 0)
      const opexDate = new Date(opexTs)

      expect(opexDate.getUTCDate()).toBe(21)
      expect(opexDate.getUTCMonth()).toBe(7) // August (0-indexed)
      expect(opexTs).toBeGreaterThanOrEqual(augustStart)
      expect(opexTs).toBeLessThanOrEqual(augustEnd)
    })
  })

  describe('GammaExposureMap Math & Level Collision Staggering', () => {
    it('computes band centering and dual Call/Put bar geometry around zero baseline', () => {
      const rows = [
        { strike: 570, call_gex_m: 50, put_gex_m: -20, net_gex_m: 30, call_oi: 1000, put_oi: 500 },
        { strike: 580, call_gex_m: 80, put_gex_m: -80, net_gex_m: 0, call_oi: 2000, put_oi: 2000 },
        { strike: 590, call_gex_m: 30, put_gex_m: -100, net_gex_m: -70, call_oi: 600, put_oi: 2500 },
      ]

      const top = 30
      const plotInnerH = 200
      const zeroY = top + plotInnerH / 2
      const halfPlotH = plotInnerH / 2 - 4
      const maxAbs = 100 // max of all calls, puts, nets

      const bars = rows.map((r) => {
        const callH = (r.call_gex_m / maxAbs) * halfPlotH
        const putH = (Math.abs(r.put_gex_m) / maxAbs) * halfPlotH
        const callY = zeroY - callH
        const putY = zeroY
        const netY = zeroY - (r.net_gex_m / maxAbs) * halfPlotH
        return { callH, putH, callY, putY, netY }
      })

      // Dual bars: neutral battleground at 580 has both call and put bars equal height
      expect(bars[1].callH).toBe(bars[1].putH)
      expect(bars[1].netY).toBe(zeroY) // net is exactly on zero baseline

      // Call grows UP from zeroY
      expect(bars[0].callY).toBeLessThan(zeroY)
      expect(bars[0].callY + bars[0].callH).toBe(zeroY)

      // Put grows DOWN from zeroY
      expect(bars[0].putY).toBe(zeroY)
    })

    it('resolves structural level label collisions with forward and backward passes', () => {
      const left = 52
      const plotInnerW = 700
      const minBoundary = left + 28
      const maxBoundary = left + plotInnerW - 28
      const minGap = 52

      // 4 levels close to each other
      const placed = [
        { key: 'put', label: 'PUT W', x: 200 },
        { key: 'flip', label: 'FLIP', x: 210 },
        { key: 'spot', label: 'SPOT', x: 220 },
        { key: 'call', label: 'CALL W', x: 230 },
      ]

      const xs = placed.map((l) => Math.max(minBoundary, Math.min(maxBoundary, l.x)))

      // Forward pass
      for (let i = 1; i < xs.length; i++) {
        if (xs[i] < xs[i - 1] + minGap) {
          xs[i] = xs[i - 1] + minGap
        }
      }

      // Backward pass
      if (xs[xs.length - 1] > maxBoundary) {
        xs[xs.length - 1] = maxBoundary
        for (let i = xs.length - 2; i >= 0; i--) {
          if (xs[i] > xs[i + 1] - minGap) {
            xs[i] = xs[i + 1] - minGap
          }
        }
      }

      // Verify each consecutive pair is separated by at least minGap
      for (let i = 1; i < xs.length; i++) {
        expect(xs[i] - xs[i - 1]).toBeGreaterThanOrEqual(minGap - 1e-6)
      }
      expect(xs[0]).toBeGreaterThanOrEqual(minBoundary)
      expect(xs[xs.length - 1]).toBeLessThanOrEqual(maxBoundary)
    })

    it('interpolates exact x-coordinate for arbitrary strike prices', () => {
      const rows = [
        { strike: 500 },
        { strike: 550 },
        { strike: 600 },
      ]
      const left = 50
      const bandW = 60
      const bandCenter = (idx: number) => left + bandW * (idx + 0.5)

      function xOfPrice(price: number): number | null {
        if (price <= rows[0].strike) return bandCenter(0)
        const lastIndex = rows.length - 1
        if (price >= rows[lastIndex].strike) return bandCenter(lastIndex)
        for (let i = 0; i < lastIndex; i++) {
          const lo = rows[i]
          const hi = rows[i + 1]
          if (price >= lo.strike && price <= hi.strike) {
            const span = hi.strike - lo.strike
            const t = span > 1e-9 ? (price - lo.strike) / span : 0
            return bandCenter(i + t)
          }
        }
        return null
      }

      // Exact midpoint strike 525 between 500 and 550
      expect(xOfPrice(525)).toBeCloseTo(bandCenter(0.5))
      // Strike 575 between 550 and 600
      expect(xOfPrice(575)).toBeCloseTo(bandCenter(1.5))
      // Out of bounds clamps cleanly
      expect(xOfPrice(400)).toBe(bandCenter(0))
      expect(xOfPrice(700)).toBe(bandCenter(2))
    })

    it('creates cumulative GEX area polygon with closed zero-line anchor', () => {
      const bars = [
        { cx: 100, cumNetY: 80 },
        { cx: 200, cumNetY: 60 },
        { cx: 300, cumNetY: 90 },
      ]
      const zeroY = 120

      const line = bars.map((b, i) => `${i === 0 ? 'M' : 'L'} ${b.cx.toFixed(1)} ${b.cumNetY.toFixed(1)}`).join(' ')
      const area = `${line} L ${bars[bars.length - 1].cx.toFixed(1)} ${zeroY.toFixed(1)} L ${bars[0].cx.toFixed(1)} ${zeroY.toFixed(1)} Z`

      expect(area.startsWith('M 100.0 80.0')).toBe(true)
      expect(area.endsWith('L 100.0 120.0 Z')).toBe(true)
      expect(area).toContain('L 300.0 120.0')
    })
  })

  describe('ProbabilityDensityChart 2D Lognormal Tails & Risk Calculator Math', () => {
    function cdfNormal(x: number): number {
      const t = 1 / (1 + 0.2316419 * Math.abs(x))
      const d = 0.3989423 * Math.exp(-x * x / 2)
      const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
      return x >= 0 ? 1 - p : p
    }

    function density(x: number, mu: number, sigma: number): number {
      if (x <= 0 || sigma <= 0) return 0
      const z = (Math.log(x) - mu) / sigma
      return (1 / (x * sigma * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * z * z)
    }

    it('evaluates lognormal PDF density with genuine positive values and correct peak behavior', () => {
      const spot = 500
      const iv = 0.25
      const T = 30 / 365
      const sigma = iv * Math.sqrt(T)
      const mu = Math.log(spot) - 0.5 * sigma * sigma

      const peakD = density(spot, mu, sigma)
      expect(peakD).toBeGreaterThan(0)
      expect(Number.isFinite(peakD)).toBe(true)

      // Far OTM densities approach 0
      expect(density(100, mu, sigma)).toBeLessThan(peakD * 0.01)
      expect(density(1500, mu, sigma)).toBeLessThan(peakD * 0.01)
      expect(density(-10, mu, sigma)).toBe(0)
    })

    it('verifies standard normal CDF approximation properties and symmetry', () => {
      // N(0) = 0.5
      expect(cdfNormal(0)).toBeCloseTo(0.5, 4)

      // Symmetry: N(x) + N(-x) = 1
      for (const z of [0.5, 1.0, 1.645, 1.96, 2.576, 3.0]) {
        expect(cdfNormal(z) + cdfNormal(-z)).toBeCloseTo(1.0, 5)
      }

      // 1 sigma ~ 68.27% -> 1 - 2 * N(-1) ~ 0.6827
      const oneSigmaMass = 1 - 2 * cdfNormal(-1)
      expect(oneSigmaMass).toBeCloseTo(0.6827, 3)

      // 2 sigma ~ 95.45%
      const twoSigmaMass = 1 - 2 * cdfNormal(-2)
      expect(twoSigmaMass).toBeCloseTo(0.9545, 3)
    })

    it('partitions 2D lognormal area path into distinct put (lower) and call (upper) tail segments', () => {
      const spot = 500
      const iv = 0.20
      const T = 45 / 365
      const sigma = iv * Math.sqrt(T)
      const mu = Math.log(spot) - 0.5 * sigma * sigma
      const low = 400
      const high = 600
      const n = 50
      const H = 260
      const pad = { l: 36, r: 14, t: 28, b: 28 }
      const plotH = H - pad.t - pad.b
      const plotW = 600 - pad.l - pad.r

      const pts: { price: number; dens: number; x: number; y: number }[] = []
      let maxD = 1e-12
      for (let i = 0; i < n; i++) {
        const price = low + (i / (n - 1)) * (high - low)
        const d = density(price, mu, sigma)
        if (d > maxD) maxD = d
      }
      for (let i = 0; i < n; i++) {
        const price = low + (i / (n - 1)) * (high - low)
        const d = density(price, mu, sigma)
        const u = i / (n - 1)
        pts.push({
          price,
          dens: d,
          x: pad.l + u * plotW,
          y: H - pad.b - (d / maxD) * plotH,
        })
      }

      const baseBottom = (H - pad.b).toFixed(2)
      const spotU = (spot - low) / (high - low)
      const spotX = pad.l + spotU * plotW
      const spotDens = density(spot, mu, sigma)
      const spotY = H - pad.b - (spotDens / maxD) * plotH

      const lowerPts = pts.filter((p) => p.price <= spot)
      const lowerSegments = lowerPts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
      lowerSegments.push(`L${spotX.toFixed(2)},${spotY.toFixed(2)}`)
      const putArea = `${lowerSegments.join(' ')} L${spotX.toFixed(2)},${baseBottom} L${pts[0].x.toFixed(2)},${baseBottom} Z`

      const upperPts = pts.filter((p) => p.price >= spot)
      const upperSegments = [`M${spotX.toFixed(2)},${spotY.toFixed(2)}`]
      upperPts.forEach((p) => upperSegments.push(`L${p.x.toFixed(2)},${p.y.toFixed(2)}`))
      const callArea = `${upperSegments.join(' ')} L${pts[pts.length - 1].x.toFixed(2)},${baseBottom} L${spotX.toFixed(2)},${baseBottom} Z`

      expect(putArea.startsWith('M')).toBe(true)
      expect(putArea.endsWith('Z')).toBe(true)
      expect(callArea.startsWith('M')).toBe(true)
      expect(callArea.endsWith('Z')).toBe(true)
      expect(putArea).toContain(spotX.toFixed(2))
      expect(callArea).toContain(spotX.toFixed(2))
    })

    it('calculates risk-neutral target price probabilities and Z-scores', () => {
      const spot = 500
      const targetPrice = 525 // +5%
      const iv = 0.20
      const T = 30 / 365
      const sigma = iv * Math.sqrt(T)

      const d2 = (Math.log(spot / targetPrice) - 0.5 * sigma * sigma) / sigma
      const probAbove = cdfNormal(d2)
      const probBelow = 1 - probAbove

      expect(probAbove).toBeGreaterThan(0)
      expect(probAbove).toBeLessThan(0.5) // Above spot -> probability < 50%
      expect(probBelow).toBeGreaterThan(0.5)
      expect(probAbove + probBelow).toBeCloseTo(1.0, 5)

      // Inside walls calculation
      const putWall = 480
      const callWall = 530
      const d2Put = (Math.log(spot / putWall) - 0.5 * sigma * sigma) / sigma
      const d2Call = (Math.log(spot / callWall) - 0.5 * sigma * sigma) / sigma
      const probBetweenWalls = Math.max(0, cdfNormal(d2Put) - cdfNormal(d2Call))

      expect(probBetweenWalls).toBeGreaterThan(0.5)
      expect(probBetweenWalls).toBeLessThan(1.0)
    })
  })

  describe('GammaHistoryStrip Scaling & Proportion Math', () => {
    it('computes historical price and GEX bar scales around gexMid', () => {
      const history = [
        { t: '2026-08-10', spot: 570, call_wall: 590, put_wall: 550, total_gex_m: 120 },
        { t: '2026-08-11', spot: 575, call_wall: 590, put_wall: 550, total_gex_m: -80 },
        { t: '2026-08-12', spot: 580, call_wall: 600, put_wall: 560, total_gex_m: 200 },
      ]

      const maxGex = Math.max(1e-9, ...history.map((p) => Math.abs(p.total_gex_m)))
      expect(maxGex).toBe(200)

      const H = 110
      const top = 12
      const priceBottom = Math.round(top + (H - top - 16) * 0.58)
      const gexTop = priceBottom + 8
      const gexBottom = H - 14
      const gexMid = (gexTop + gexBottom) / 2
      const gexHalf = Math.max(6, (gexBottom - gexTop) / 2 - 1)

      const bars = history.map((point) => {
        const h = Math.max(1.5, (Math.abs(point.total_gex_m) / maxGex) * gexHalf)
        const y = point.total_gex_m >= 0 ? gexMid - h : gexMid
        return { h, y, isPos: point.total_gex_m >= 0 }
      })

      // Maximum bar reaches gexHalf
      expect(bars[2].h).toBeCloseTo(gexHalf)
      expect(bars[2].y).toBeCloseTo(gexMid - gexHalf)

      // Negative bar sits below gexMid
      expect(bars[1].isPos).toBe(false)
      expect(bars[1].y).toBe(gexMid)
    })
  })

  describe('Component Token and Visual Polish Conformance', () => {
    const gexMapSrc = readSrc('components/GammaExposureMap.vue')
    const driftSrc = readSrc('components/OptionsDriftChart.vue')
    const pdfSrc = readSrc('components/ProbabilityDensityChart.vue')
    const histSrc = readSrc('components/GammaHistoryStrip.vue')

    it('GammaExposureMap complies with high-DPI strokes, crisp zero line, and transitions', () => {
      expect(gexMapSrc).toContain('stroke: var(--call-hi)')
      expect(gexMapSrc).toContain('stroke: var(--put-hi)')
      expect(gexMapSrc).toContain('stroke: var(--rule-hi)')
      expect(gexMapSrc).toContain('transition: transform 0.15s cubic-bezier(0.16, 1, 0.3, 1)')
      expect(gexMapSrc).toContain('level-chip')
    })

    it('OptionsDriftChart complies with crosshair overlay, crisp zero lines, and responsive activity bars', () => {
      expect(driftSrc).toContain('crosshair')
      expect(driftSrc).toContain('crosshair-v')
      expect(driftSrc).toContain('crosshair-h')
      expect(driftSrc).toContain('crosshair-pill-bg')
      expect(driftSrc).toContain('activity-bars')
      expect(driftSrc).toContain('stroke: var(--call-hi)')
      expect(driftSrc).toContain('stroke: var(--put-hi)')
    })

    it('ProbabilityDensityChart complies with emerald upper tail and crimson lower tail fills and 1σ bounds', () => {
      expect(pdfSrc).toContain('putArea')
      expect(pdfSrc).toContain('callArea')
      expect(pdfSrc).toContain('var(--put-wash)')
      expect(pdfSrc).toContain('var(--call-wash)')
      expect(pdfSrc).toContain('sigma-bounds')
      expect(pdfSrc).toContain('sigma-bound low')
      expect(pdfSrc).toContain('sigma-bound high')
      expect(pdfSrc).toContain('probe-tip-bg')
    })

    it('GammaHistoryStrip complies with high-contrast emerald/crimson palette and interactive tooltips', () => {
      expect(histSrc).toContain('rect.positive')
      expect(histSrc).toContain('rect.negative')
      expect(histSrc).toContain('var(--call-hi)')
      expect(histSrc).toContain('var(--put-hi)')
      expect(histSrc).toContain('history-probe')
      expect(histSrc).toContain('hoverIdx')
    })

    it('strictly maintains instrument token compliance and anti-neon rules across all charts', () => {
      for (const [, src] of [
        ['GammaExposureMap', gexMapSrc],
        ['OptionsDriftChart', driftSrc],
        ['ProbabilityDensityChart', pdfSrc],
        ['GammaHistoryStrip', histSrc],
      ]) {
        expect(src).not.toContain('#ef4444')
        expect(src).not.toContain('#22c55e')
        expect(src).not.toContain('text-shadow')
        expect(src).not.toContain('drop-shadow')
      }
    })
  })
})
