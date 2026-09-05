import { describe, expect, it } from 'vitest'
import { bsThetaDay, greekCurves, type GreekKind } from '../landing-viz'

/**
 * The landing-page model lab plots these curves inside a fixed viewBox whose
 * x axis is the strike range mapped onto [0, 100]. A regression here is
 * invisible in unit-free maths but renders the lab as an empty plot, so the
 * axis contract is pinned explicitly.
 */
const KINDS: GreekKind[] = ['value', 'delta', 'gamma', 'vega', 'theta']

const S = 100
const T = 30 / 365
const SIGMA = 0.3
const R = 0.05
const Q = 0
const K_LOW = 60
const K_HIGH = 140
const N = 121

describe('greekCurves', () => {
  it.each(KINDS)('maps the %s curve onto the full [0, 100] strike axis', (kind) => {
    const { call, put } = greekCurves(kind, S, T, SIGMA, R, Q, K_LOW, K_HIGH, N)

    for (const series of [call, put]) {
      expect(series).toHaveLength(N)
      expect(series[0]!.x).toBeCloseTo(0)
      expect(series[series.length - 1]!.x).toBeCloseTo(100)
      for (const p of series) {
        expect(p.x).toBeGreaterThanOrEqual(0)
        expect(p.x).toBeLessThanOrEqual(100)
        expect(Number.isFinite(p.y)).toBe(true)
        expect(Math.abs(p.y)).toBeLessThanOrEqual(1 + 1e-9)
      }
    }
  })

  it('spaces strikes evenly and keeps x monotonically increasing', () => {
    const { call, strikes } = greekCurves('value', S, T, SIGMA, R, Q, K_LOW, K_HIGH, N)

    expect(strikes[0]).toBeCloseTo(K_LOW)
    expect(strikes[strikes.length - 1]).toBeCloseTo(K_HIGH)
    for (let i = 1; i < call.length; i++) {
      expect(call[i]!.x).toBeGreaterThan(call[i - 1]!.x)
    }
    // Midpoint strike lands at the midpoint of the axis.
    expect(call[(N - 1) / 2]!.x).toBeCloseTo(50)
  })

  it('normalises call and put against one shared scale so at least one curve peaks at ±1', () => {
    const { call, put } = greekCurves('value', S, T, SIGMA, R, Q, K_LOW, K_HIGH, N)
    const peak = Math.max(...[...call, ...put].map((p) => Math.abs(p.y)))
    expect(peak).toBeCloseTo(1)
  })

  it.each(KINDS)(
    'uses the FULL band for %s: a point at +1 and a point at the bottom edge',
    (kind) => {
      // A symmetric maxAbs scale left non-negative Greeks (value/gamma/vega)
      // floating in the top half and theta in the bottom half, rendering half
      // the plot as dead space. Domain normalisation pins both band edges.
      const { call, put } = greekCurves(kind, S, T, SIGMA, R, Q, K_LOW, K_HIGH, N)
      const ys = [...call, ...put].map((p) => p.y)
      expect(Math.max(...ys)).toBeCloseTo(1)
      // All kinds touch -1 exactly except value, whose domain floor is 0 (for
      // the payoff boundary) while the cheapest option still costs ~$0.27.
      if (kind === 'value') expect(Math.min(...ys)).toBeLessThanOrEqual(-0.9)
      else expect(Math.min(...ys)).toBeCloseTo(-1)
    },
  )

  it('reports its domain, and the value domain reaches 0 for the payoff boundary', () => {
    const { domain } = greekCurves('value', S, T, SIGMA, R, Q, K_LOW, K_HIGH, N)
    expect(domain.lo).toBe(0)
    // Domain top is the deep-ITM call value at K=60 (~$40.2): the ATM $3.63
    // value sits mid-band instead of hugging the frame edge.
    expect(domain.hi).toBeGreaterThan(30)
  })
})

describe('bsThetaDay', () => {
  const AT_ATM = { S: 100, K: 100, T: 30 / 365, sigma: 0.3, r: 0.05, q: 0 }

  it('keeps both ATM legs negative and the call the deeper decay at r>0, q=0', () => {
    const call = bsThetaDay(AT_ATM, 'call')
    const put = bsThetaDay(AT_ATM, 'put')
    expect(call).toBeLessThan(0)
    expect(put).toBeLessThan(0)
    // ATM: call −0.064/d, put −0.050/d — the put is shallower.
    expect(call).toBeCloseTo(-0.064, 3)
    expect(put).toBeCloseTo(-0.05, 3)
  })

  it('satisfies the carry identity theta_put − theta_call = rK·e^{−rT}/365 at q=0', () => {
    // Hull: the legs differ only by the strike-carry term. A sign slip on
    // either rK term (which once handed deep-ITM calls positive theta)
    // breaks this identity immediately.
    const deepItmCall = bsThetaDay({ ...AT_ATM, K: 60 }, 'call')
    expect(deepItmCall).toBeLessThan(0)
    for (const K of [60, 80, 100, 120, 140]) {
      const call = bsThetaDay({ ...AT_ATM, K }, 'call')
      const put = bsThetaDay({ ...AT_ATM, K }, 'put')
      expect(put - call).toBeCloseTo((0.05 * K * Math.exp(-0.05 * AT_ATM.T)) / 365, 6)
    }
  })
})
