import { describe, it, expect } from 'vitest'
import { linearScale, niceTicks, niceDomain, timeScale, dateTicks } from '../scale'
import { linePath, smoothPath, areaPath, stepPath, candlePath, bandPath, sparkline } from '../path'
import {
  pctChange,
  cumulative,
  drawdown,
  maxDrawdown,
  rollingMean,
  rollingStd,
  ema,
  annVol,
  annReturn,
  sharpe,
  correlation,
  quantile,
  zscore,
  normalizeTo,
} from '../stats'

describe('scale', () => {
  it('linearScale maps domain endpoints to range endpoints and invert round-trips', () => {
    const s = linearScale([0, 100], [0, 500])
    expect(s(0)).toBeCloseTo(0)
    expect(s(100)).toBeCloseTo(500)
    expect(s(50)).toBeCloseTo(250)
    expect(s.invert(0)).toBeCloseTo(0)
    expect(s.invert(500)).toBeCloseTo(100)
    expect(s.invert(s(37))).toBeCloseTo(37)
  })

  it('linearScale handles reversed domains (e.g. a y-axis)', () => {
    const s = linearScale([10, -10], [0, 100])
    expect(s(10)).toBeCloseTo(0)
    expect(s(-10)).toBeCloseTo(100)
    expect(s.invert(s(3))).toBeCloseTo(3)
  })

  it('degenerate domain [5,5] never produces NaN or Infinity', () => {
    const s = linearScale([5, 5], [0, 100])
    expect(Number.isFinite(s(5))).toBe(true)
    expect(Number.isFinite(s(999))).toBe(true)
    expect(Number.isFinite(s.invert(50))).toBe(true)

    const ticks = niceTicks(5, 5)
    expect(ticks.every((t) => Number.isFinite(t))).toBe(true)

    const dom = niceDomain(5, 5)
    expect(dom.every((t) => Number.isFinite(t))).toBe(true)
    expect(dom[0]).toBeLessThan(dom[1])
  })

  it('niceTicks returns 1-2-5 spaced values inside the requested range', () => {
    const ticks = niceTicks(0, 100, 5)
    expect(ticks.length).toBeGreaterThan(0)
    for (const t of ticks) {
      expect(t).toBeGreaterThanOrEqual(0)
      expect(t).toBeLessThanOrEqual(100)
    }
    const step = ticks[1] - ticks[0]
    const exponent = Math.floor(Math.log10(step))
    const normalized = Math.round((step / Math.pow(10, exponent)) * 1e6) / 1e6
    expect([1, 2, 5, 10]).toContain(normalized)
  })

  it('niceTicks stays inside an irregular range too', () => {
    const ticks = niceTicks(3.7, 91.2, 6)
    for (const t of ticks) {
      expect(t).toBeGreaterThanOrEqual(3.7)
      expect(t).toBeLessThanOrEqual(91.2)
    }
  })

  it('timeScale is ordinal on bar index, not wall-clock time', () => {
    // huge date gap between index 1 and 2 must NOT skew the mapping
    const dates = ['2024-01-01', '2024-01-02', '2024-06-01']
    const s = timeScale(dates, [0, 200])
    expect(s(0)).toBeCloseTo(0)
    expect(s(2)).toBeCloseTo(200)
    expect(s(1)).toBeCloseTo(100)
  })

  it('timeScale and dateTicks never throw on empty input', () => {
    expect(dateTicks([])).toEqual([])
    const s = timeScale([], [0, 100])
    expect(Number.isFinite(s(0))).toBe(true)
  })

  it('dateTicks picks adaptive granularity and stays within the series bounds', () => {
    const days = Array.from({ length: 10 }, (_, i) => `2024-01-${String(i + 1).padStart(2, '0')}`)
    const ticks = dateTicks(days, 4)
    expect(ticks.length).toBeGreaterThan(0)
    for (const t of ticks) {
      expect(t.i).toBeGreaterThanOrEqual(0)
      expect(t.i).toBeLessThan(days.length)
      expect(t.label.length).toBeGreaterThan(0)
    }

    const years = ['2018-01-01', '2020-06-15', '2023-11-30']
    const yearTicks = dateTicks(years, 3)
    expect(yearTicks.some((t) => t.label === '2018')).toBe(true)
  })
})

describe('path', () => {
  it('every path function returns "" on empty input', () => {
    expect(linePath([])).toBe('')
    expect(smoothPath([])).toBe('')
    expect(areaPath([], 0)).toBe('')
    expect(stepPath([])).toBe('')
    expect(bandPath([], [])).toBe('')

    const c = candlePath([], 3)
    expect(c.up).toBe('')
    expect(c.down).toBe('')
    expect(c.wicks).toBe('')

    const sp = sparkline([], 100, 40)
    expect(sp.d).toBe('')
    expect(sp.area).toBe('')
  })

  it('linePath emits an M-then-L path with rounded coordinates', () => {
    const d = linePath([
      { x: 0, y: 0 },
      { x: 1.005, y: 2.3333 },
      { x: 5, y: 5 },
    ])
    expect(d.startsWith('M')).toBe(true)
    expect(d).toContain('L')
    expect(d).not.toContain('NaN')
  })

  it('smoothPath falls back for tiny inputs and never emits NaN for real curves', () => {
    expect(smoothPath([])).toBe('')
    expect(smoothPath([{ x: 1, y: 1 }])).toBe('M1,1')
    expect(smoothPath([{ x: 0, y: 0 }, { x: 10, y: 10 }])).toBe(linePath([{ x: 0, y: 0 }, { x: 10, y: 10 }]))

    const d = smoothPath([
      { x: 0, y: 0 },
      { x: 10, y: 5 },
      { x: 20, y: 0 },
      { x: 30, y: 8 },
    ])
    expect(d.startsWith('M')).toBe(true)
    expect(d).toContain('C')
    expect(d).not.toContain('NaN')
  })

  it('smoothPath with tension 0 degenerates to straight segments between points', () => {
    const pts = [
      { x: 0, y: 0 },
      { x: 10, y: 5 },
      { x: 20, y: 0 },
    ]
    const d = smoothPath(pts, 0)
    // control points collapse onto the endpoints, so the curve visits
    // each source point exactly (still emitted as C commands)
    expect(d).not.toContain('NaN')
    expect(d.startsWith('M0,0')).toBe(true)
  })

  it('areaPath closes the shape back to the baseline', () => {
    const d = areaPath(
      [
        { x: 0, y: 10 },
        { x: 10, y: 0 },
      ],
      20,
    )
    expect(d.startsWith('M')).toBe(true)
    expect(d.endsWith('Z')).toBe(true)
    expect(d).not.toContain('NaN')
  })

  it('stepPath inserts a horizontal-then-vertical segment between points', () => {
    const d = stepPath([
      { x: 0, y: 0 },
      { x: 10, y: 5 },
    ])
    expect(d).toBe('M0,0L10,0L10,5')
  })

  it('candlePath buckets bodies into up/down and always emits wicks', () => {
    const bars = [
      { x: 0, o: 10, h: 12, l: 9, c: 11 }, // bullish: c >= o
      { x: 10, o: 11, h: 12, l: 8, c: 9 }, // bearish: c < o
    ]
    const { up, down, wicks } = candlePath(bars, 2)
    expect(up).toContain('M')
    expect(up).toContain('Z')
    expect(down).toContain('M')
    expect(wicks).not.toContain('NaN')
    expect((wicks.match(/M/g) ?? []).length).toBe(2)
  })

  it('bandPath closes a ribbon between an upper and lower series', () => {
    const upper = [
      { x: 0, y: 0 },
      { x: 10, y: 0 },
    ]
    const lower = [
      { x: 0, y: 5 },
      { x: 10, y: 5 },
    ]
    const d = bandPath(upper, lower)
    expect(d.startsWith('M')).toBe(true)
    expect(d.endsWith('Z')).toBe(true)
    expect(d).not.toContain('NaN')
  })

  it('sparkline output d starts with "M" and contains no NaN', () => {
    const sp = sparkline([1, 5, 3, 8, 2, 9, 4], 100, 30, 2)
    expect(sp.d.startsWith('M')).toBe(true)
    expect(sp.d).not.toContain('NaN')
    expect(sp.area).not.toContain('NaN')
    expect(Number.isFinite(sp.last.x)).toBe(true)
    expect(Number.isFinite(sp.min.y)).toBe(true)
    expect(Number.isFinite(sp.max.y)).toBe(true)
  })

  it('sparkline handles a flat series (degenerate value domain) without NaN', () => {
    const sp = sparkline([5, 5, 5, 5], 100, 30)
    expect(sp.d).not.toContain('NaN')
    expect(Number.isFinite(sp.last.y)).toBe(true)
  })
})

describe('stats', () => {
  it('cumulative(pctChange(prices)) reconstructs the price ratio within 1e-9', () => {
    const prices = [100, 105, 98, 120, 130.5, 99]
    const cum = cumulative(pctChange(prices))
    const ratio = cum[cum.length - 1]
    const expected = prices[prices.length - 1] / prices[0]
    expect(Math.abs(ratio - expected)).toBeLessThan(1e-9)
  })

  it('pctChange starts with 0', () => {
    expect(pctChange([50, 55, 44])[0]).toBe(0)
    expect(pctChange([])).toEqual([])
  })

  it('maxDrawdown on a known hand-computed series', () => {
    expect(maxDrawdown([1, 1.5, 0.75, 1.2])).toBeCloseTo(-0.5, 9)
  })

  it('drawdown is zero at/after a new peak and negative below the running peak', () => {
    const dd = drawdown([1, 1.5, 0.75, 1.2])
    expect(dd[0]).toBeCloseTo(0)
    expect(dd[1]).toBeCloseTo(0)
    expect(dd[2]).toBeCloseTo(-0.5)
    expect(dd[3]).toBeCloseTo(-0.2)
  })

  it('rollingMean / rollingStd return null before the window fills', () => {
    const v = [1, 2, 3, 4, 5]
    const mean = rollingMean(v, 3)
    expect(mean[0]).toBeNull()
    expect(mean[1]).toBeNull()
    expect(mean[2]).toBeCloseTo(2)
    expect(mean[4]).toBeCloseTo(4)

    const std = rollingStd(v, 3)
    expect(std[0]).toBeNull()
    expect(std[1]).toBeNull()
    expect(std[2]).not.toBeNull()
    expect(rollingMean(v, 99).every((x) => x === null)).toBe(true)
  })

  it('ema seeds with the first value and holds steady on a constant series', () => {
    const out = ema([10, 10, 10, 10], 3)
    expect(out[0]).toBe(10)
    for (const x of out) expect(x).toBeCloseTo(10)
  })

  it('correlation of a series with itself is 1, with its negation is -1', () => {
    const a = [1, 2, 3, 4, 5, 3, 2]
    const negA = a.map((x) => -x)
    expect(correlation(a, a)).toBeCloseTo(1, 9)
    expect(correlation(a, negA)).toBeCloseTo(-1, 9)
  })

  it('correlation returns NaN for a constant series or insufficient data', () => {
    expect(Number.isNaN(correlation([1, 1, 1], [1, 2, 3]))).toBe(true)
    expect(Number.isNaN(correlation([1], [1]))).toBe(true)
    expect(Number.isNaN(correlation([], []))).toBe(true)
  })

  it('sharpe returns NaN on a constant-return series', () => {
    const constant = [0.01, 0.01, 0.01, 0.01, 0.01]
    expect(Number.isNaN(sharpe(constant))).toBe(true)
  })

  it('sharpe is a finite number for a noisy, non-constant return series', () => {
    const returns = [0.02, -0.01, 0.03, 0.01, -0.005, 0.025, 0.015]
    expect(Number.isFinite(sharpe(returns))).toBe(true)
  })

  it('annVol / annReturn never throw and flag insufficient data with NaN', () => {
    const returns = [0.01, -0.02, 0.015, 0.005, -0.01]
    expect(Number.isFinite(annVol(returns, 252))).toBe(true)
    expect(Number.isFinite(annReturn(returns, 252))).toBe(true)
    expect(Number.isNaN(annVol([0.01], 252))).toBe(true)
    expect(Number.isNaN(annVol([], 252))).toBe(true)
    expect(Number.isNaN(annReturn([], 252))).toBe(true)
  })

  it('annReturn floors at -1 when cumulative growth is wiped out', () => {
    expect(annReturn([-1, 0.5], 252)).toBe(-1)
  })

  it('quantile matches known percentiles under linear interpolation', () => {
    const v = [1, 2, 3, 4, 5]
    expect(quantile(v, 0)).toBe(1)
    expect(quantile(v, 1)).toBe(5)
    expect(quantile(v, 0.5)).toBeCloseTo(3)
    expect(Number.isNaN(quantile([], 0.5))).toBe(true)
  })

  it('zscore centers data at mean 0 and never throws on a constant series', () => {
    const z = zscore([2, 4, 4, 4, 5, 5, 7, 9])
    const mean = z.reduce((a, b) => a + b, 0) / z.length
    expect(mean).toBeCloseTo(0, 9)
    expect(zscore([5, 5, 5]).every((x) => x === 0)).toBe(true)
    expect(zscore([])).toEqual([])
  })

  it('normalizeTo rebases a series to the given base', () => {
    const norm = normalizeTo([50, 100, 25], 1)
    expect(norm[0]).toBeCloseTo(1)
    expect(norm[1]).toBeCloseTo(2)
    expect(norm[2]).toBeCloseTo(0.5)
    expect(normalizeTo([])).toEqual([])
  })

  it('every scalar-aggregate stats function returns NaN (never throws) on empty input', () => {
    expect(Number.isNaN(maxDrawdown([]))).toBe(true)
    expect(Number.isNaN(sharpe([]))).toBe(true)
    expect(Number.isNaN(correlation([], []))).toBe(true)
    expect(Number.isNaN(quantile([], 0.5))).toBe(true)
    expect(cumulative([])).toEqual([])
    expect(drawdown([])).toEqual([])
  })
})
