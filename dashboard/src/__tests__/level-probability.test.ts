/**
 * Unit tests for dashboard/src/levelProbability.ts — first-passage (touch)
 * probability for a price level.
 *
 * The tests that matter here are the ones pinning the maths to a result that
 * can be derived independently, not to whatever the implementation happens to
 * return: the driftless reflection identity, monotonicity in every input, and
 * the touch >= terminal ordering that makes the pair meaningful.
 */
import { describe, expect, it } from 'vitest'
import {
  levelProbability,
  levelProbabilityByHorizon,
  medianTimeToTouch,
  sessionYears,
  tradingDayYears,
} from '@/levelProbability'
import { normalCdf } from '@/regimeSignals'

describe('levelProbability', () => {
  it('matches the reflection identity 2*N(-|b|/(sigma*sqrt(T))) when drift is zero', () => {
    // Zero drift needs r = sigma^2/2 so that mu = r - sigma^2/2 = 0.
    const sigma = 0.2
    const tYears = 30 / 252
    const spot = 100
    const level = 104
    const p = levelProbability({ spot, level, sigma, tYears, rate: (sigma * sigma) / 2 })
    const b = Math.log(level / spot)
    const expected = 2 * normalCdf(-Math.abs(b) / (sigma * Math.sqrt(tYears)))
    expect(p).not.toBeNull()
    expect(p!.touch).toBeCloseTo(expected, 10)
  })

  it('gives the same driftless touch probability above and below by log distance', () => {
    const sigma = 0.3
    const tYears = 5 / 252
    const rate = (sigma * sigma) / 2
    const up = levelProbability({ spot: 100, level: 105, sigma, tYears, rate })
    const down = levelProbability({ spot: 105, level: 100, sigma, tYears, rate })
    expect(up!.touch).toBeCloseTo(down!.touch, 12)
  })

  it('reports touch strictly above terminal for a barrier away from spot', () => {
    // The whole point of the module: price can tag a level and settle back
    // inside it, and terminal probability scores that as a miss.
    const p = levelProbability({ spot: 600, level: 612, sigma: 0.18, tYears: 1 / 252 })!
    expect(p.touch).toBeGreaterThan(p.terminal)
    expect(p.rejection).toBeCloseTo(p.touch - p.terminal, 12)
  })

  it('is monotonically increasing in time and in volatility', () => {
    const base = { spot: 100, level: 103, sigma: 0.25 }
    const short = levelProbability({ ...base, tYears: 1 / 252 })!
    const long = levelProbability({ ...base, tYears: 20 / 252 })!
    expect(long.touch).toBeGreaterThan(short.touch)

    const calm = levelProbability({ ...base, tYears: 5 / 252, sigma: 0.12 })!
    const wild = levelProbability({ ...base, tYears: 5 / 252, sigma: 0.6 })!
    expect(wild.touch).toBeGreaterThan(calm.touch)
  })

  it('is monotonically decreasing in distance', () => {
    const near = levelProbability({ spot: 100, level: 101, sigma: 0.2, tYears: 5 / 252 })!
    const far = levelProbability({ spot: 100, level: 110, sigma: 0.2, tYears: 5 / 252 })!
    expect(near.touch).toBeGreaterThan(far.touch)
  })

  it('labels direction by which side of spot the level sits on', () => {
    expect(levelProbability({ spot: 100, level: 105, sigma: 0.2, tYears: 0.02 })!.direction).toBe(
      'up',
    )
    expect(levelProbability({ spot: 100, level: 95, sigma: 0.2, tYears: 0.02 })!.direction).toBe(
      'down',
    )
  })

  it('treats a level at spot as already touched rather than dividing by zero', () => {
    const p = levelProbability({ spot: 100, level: 100, sigma: 0.2, tYears: 0.02 })!
    expect(p.touch).toBe(1)
    expect(Number.isFinite(p.terminal)).toBe(true)
  })

  it('stays inside [0, 1] for an extremely near barrier under high vol', () => {
    const p = levelProbability({ spot: 100, level: 100.0001, sigma: 3, tYears: 1 })!
    expect(p.touch).toBeLessThanOrEqual(1)
    expect(p.touch).toBeGreaterThanOrEqual(0)
    expect(p.terminal).toBeLessThanOrEqual(p.touch)
  })

  it('does not overflow to NaN for a far barrier under a tiny sigma', () => {
    // 2*mu*b/sigma^2 blows up here; the exp() clamp is what keeps this finite.
    const p = levelProbability({ spot: 100, level: 400, sigma: 0.001, tYears: 1 })!
    expect(Number.isFinite(p.touch)).toBe(true)
    expect(p.touch).toBeLessThan(0.01)
  })

  it('withholds rather than guessing when an input makes the question meaningless', () => {
    expect(levelProbability({ spot: 0, level: 100, sigma: 0.2, tYears: 0.1 })).toBeNull()
    expect(levelProbability({ spot: 100, level: 0, sigma: 0.2, tYears: 0.1 })).toBeNull()
    expect(levelProbability({ spot: 100, level: 105, sigma: 0, tYears: 0.1 })).toBeNull()
    expect(levelProbability({ spot: 100, level: 105, sigma: 0.2, tYears: 0 })).toBeNull()
    expect(levelProbability({ spot: 100, level: 105, sigma: NaN, tYears: 0.1 })).toBeNull()
  })
})

describe('horizon helpers', () => {
  it('converts a remaining-session fraction onto the 252-day trading clock', () => {
    expect(sessionYears(1)).toBeCloseTo(1 / 252, 12)
    expect(sessionYears(0.5)).toBeCloseTo(0.5 / 252, 12)
  })

  it('returns zero for a closed or invalid session so probabilities withhold', () => {
    expect(sessionYears(0)).toBe(0)
    expect(sessionYears(-1)).toBe(0)
    expect(tradingDayYears(0)).toBe(0)
  })

  it('prices one level across several horizons without recomputing sigma', () => {
    const out = levelProbabilityByHorizon(100, 103, 0.25, [
      { key: 'd1', label: '1 day', tYears: tradingDayYears(1) },
      { key: 'd5', label: '5 days', tYears: tradingDayYears(5) },
    ])
    expect(out).toHaveLength(2)
    expect(out[1].prob!.touch).toBeGreaterThan(out[0].prob!.touch)
    expect(out[0].horizon.label).toBe('1 day')
  })
})

describe('medianTimeToTouch', () => {
  it('lands inside the horizon and halves the touch probability there', () => {
    const input = { spot: 100, level: 102, sigma: 0.25, tYears: 20 / 252 }
    const t = medianTimeToTouch(input)!
    expect(t).toBeGreaterThan(0)
    expect(t).toBeLessThan(input.tYears)
    const half = levelProbability({ ...input, tYears: t })!
    const full = levelProbability(input)!
    expect(half.touch).toBeCloseTo(full.touch / 2, 4)
  })

  it('withholds when the level is effectively unreachable inside the horizon', () => {
    expect(medianTimeToTouch({ spot: 100, level: 400, sigma: 0.1, tYears: 1 / 252 })).toBeNull()
  })
})
