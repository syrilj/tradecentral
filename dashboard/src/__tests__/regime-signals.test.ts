/**
 * Unit tests for dashboard/src/regimeSignals.ts — the client-side signal
 * primitives the /regime fast tick feeds: level-crossing detection, trigger
 * distances, and the lognormal probability fallback.
 */
import { describe, expect, it } from 'vitest'
import { approxProbabilities, levelCrossings, normalCdf, triggerDistance } from '@/regimeSignals'

describe('levelCrossings', () => {
  const levels = [
    { key: 'put' as const, label: 'PUT WALL', price: 638 },
    { key: 'flip' as const, label: 'GAMMA FLIP', price: 640.5 },
    { key: 'call' as const, label: 'CALL WALL', price: 644 },
  ]

  it('detects an upward crossing with dir "up"', () => {
    const out = levelCrossings(640, 641, levels)
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({ key: 'flip', label: 'GAMMA FLIP', price: 640.5, dir: 'up' })
  })

  it('detects a downward crossing with dir "down"', () => {
    const out = levelCrossings(645, 643, levels)
    expect(out).toHaveLength(1)
    expect(out[0]).toMatchObject({ key: 'call', dir: 'down' })
  })

  it('reports multiple crossed levels nearest-to-origin first, not by price', () => {
    // Falling from 645 to a spot just below the flip: the call wall was met
    // first, so it must be the first event even though the flip is lower.
    const out = levelCrossings(645, 640.2, levels)
    expect(out.map((c) => c.label)).toEqual(['CALL WALL', 'GAMMA FLIP'])
  })

  it('crosses nothing when spot does not move', () => {
    expect(levelCrossings(640.5, 640.5, levels)).toEqual([])
  })

  it('fires only when spot passes THROUGH a level, not when it merely lands on it', () => {
    // Strict interior comparison: dwelling exactly on the flip has not yet
    // produced a break (and re-touch noise would double-fire otherwise);
    // the event registers once the next tick moves past it.
    expect(levelCrossings(639, 640.5, levels)).toHaveLength(0)
    expect(levelCrossings(639, 640.6, levels)).toHaveLength(1)
    expect(levelCrossings(639, 640.4, levels)).toHaveLength(0)
  })

  it('crosses nothing for non-finite endpoints', () => {
    expect(levelCrossings(NaN, 641, levels)).toEqual([])
    expect(levelCrossings(640, Infinity, levels)).toEqual([])
  })
})

describe('triggerDistance', () => {
  it('signs the distance by side of spot and gives the EM multiple', () => {
    const above = triggerDistance(640, 644, 4)
    expect(above.pct).toBeCloseTo(0.625)
    expect(above.emMultiple).toBeCloseTo(1)

    const below = triggerDistance(640, 636, 4)
    expect(below.pct).toBeCloseTo(-0.625)
    expect(below.emMultiple).toBeCloseTo(1)
  })

  it('returns null EM multiple when no expected move is available', () => {
    expect(triggerDistance(640, 644, null).emMultiple).toBeNull()
    expect(triggerDistance(640, 644, 0).emMultiple).toBeNull()
  })
})

describe('normalCdf', () => {
  it('matches known normal CDF values', () => {
    expect(normalCdf(0)).toBeCloseTo(0.5)
    expect(normalCdf(1)).toBeCloseTo(0.841344746, 5)
    expect(normalCdf(-1)).toBeCloseTo(0.158655254, 5)
    expect(normalCdf(2)).toBeCloseTo(0.977249868, 5)
  })

  it('is symmetric around zero', () => {
    expect(normalCdf(0.7) + normalCdf(-0.7)).toBeCloseTo(1)
  })
})

describe('approxProbabilities — the fallback that keeps the deck live', () => {
  const base = { spot: 640, iv: 0.16, tYears: 1 / 252, callWall: 644, putWall: 636 }

  it('returns null on non-positive or non-finite inputs', () => {
    expect(approxProbabilities({ ...base, spot: 0 })).toBeNull()
    expect(approxProbabilities({ ...base, iv: -0.1 })).toBeNull()
    expect(approxProbabilities({ ...base, tYears: 0 })).toBeNull()
    expect(approxProbabilities({ ...base, spot: NaN })).toBeNull()
  })

  it('puts slightly more mass above the call wall than below the put wall when the walls are equidistant in dollars', () => {
    const out = approxProbabilities(base)!
    expect(out).not.toBeNull()
    // The log transform places an equal-dollar lower wall marginally farther
    // from spot than the upper one (|ln(636/640)| > |ln(644/640)|), so the
    // upside break is marginally the likelier of the two.
    expect(out.probAboveCallWall!).toBeGreaterThan(out.probBelowPutWall!)
    expect(out.probBelowPutWall!).toBeGreaterThan(0)
    expect(out.probAboveCallWall!).toBeLessThan(0.5)
  })

  it('splits the between-walls mass so the three probabilities stay coherent', () => {
    const out = approxProbabilities(base)!
    expect(out.probBetweenWalls!).toBeCloseTo(1 - out.probAboveCallWall! - out.probBelowPutWall!, 6)
    expect(out.probBetweenWalls!).toBeGreaterThanOrEqual(0)
  })

  it('narrows the 68% band as the horizon shrinks (0DTE < 1 week < 1 year)', () => {
    const d0 = approxProbabilities({ ...base, tYears: 1 / 252 })!.band68!
    const d5 = approxProbabilities({ ...base, tYears: 5 / 252 })!.band68!
    const d365 = approxProbabilities({ ...base, tYears: 1 })!.band68!
    expect(d0.high - d0.low).toBeLessThan(d5.high - d5.low)
    expect(d5.high - d5.low).toBeLessThan(d365.high - d365.low)
    expect(d0.low).toBeGreaterThan(0)
  })

  it('matches the closed-form lognormal band and expected move at a clean horizon', () => {
    // iv·sqrt(T) = 0.16 over a full year → band = spot·e^±0.16 and
    // EM = (band.high − band.low)/2 = spot·sinh(0.16).
    const out = approxProbabilities({ ...base, tYears: 1 })!
    expect(out.band68!.low).toBeCloseTo(640 * Math.exp(-0.16), 4)
    expect(out.band68!.high).toBeCloseTo(640 * Math.exp(0.16), 4)
    expect(out.expectedMove!).toBeCloseTo(640 * Math.sinh(0.16), 4)
  })

  it('monotonically raises P(above call wall) as the call wall approaches spot', () => {
    const far = approxProbabilities({ ...base, callWall: 650 })!.probAboveCallWall!
    const near = approxProbabilities({ ...base, callWall: 641 })!.probAboveCallWall!
    expect(near).toBeGreaterThan(far)
    expect(near).toBeLessThan(0.5)
  })

  it('returns null wall probabilities when the walls are unmeasurable, not fake zeros', () => {
    const out = approxProbabilities({ ...base, callWall: null, putWall: null })!
    expect(out.probAboveCallWall).toBeNull()
    expect(out.probBelowPutWall).toBeNull()
    expect(out.probBetweenWalls).toBeNull()
    // The distribution-level outputs remain usable.
    expect(out.band68!.high).toBeGreaterThan(base.spot)
    expect(out.expectedMove!).toBeGreaterThan(0)
  })
})
