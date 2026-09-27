import { describe, it, expect } from 'vitest'
import {
  REVEAL_PHASES,
  stripEntrance,
  iconFlight,
  segmentOpacity,
  shuffleOrder,
} from '../reveal-math'

describe('reveal-math', () => {
  it('strip entrance rises from hidden to fully visible by enterEnd', () => {
    expect(stripEntrance(0)).toEqual({ opacity: 0, offset: 24 })
    const settled = stripEntrance(REVEAL_PHASES.enterEnd)
    expect(settled.opacity).toBe(1)
    expect(settled.offset).toBe(0)
  })

  it('icon flight stays grounded before the enter band ends', () => {
    expect(iconFlight(0.1, 0, 5)).toEqual({ y: 0, x: 0 })
  })

  it('icon flight lands (y and x both 1) at or past flightEnd for every index', () => {
    for (let i = 0; i < 5; i++) {
      expect(iconFlight(REVEAL_PHASES.flightEnd, i, 5)).toEqual({ y: 1, x: 1 })
    }
  })

  it('later indices depart later than earlier ones', () => {
    const p = REVEAL_PHASES.enterEnd + 0.05
    const first = iconFlight(p, 0, 5).y
    const last = iconFlight(p, 4, 5).y
    expect(first).toBeGreaterThan(last)
  })

  it('segments stay hidden until the flight band ends', () => {
    expect(segmentOpacity(REVEAL_PHASES.flightEnd, 0, 5)).toBe(0)
  })

  it('segments fully reveal by the end of scroll', () => {
    for (let i = 0; i < 5; i++) {
      expect(segmentOpacity(1, i, 5)).toBe(1)
    }
  })

  it('the whole sentence is readable by settleEnd, leaving a hold band', () => {
    expect(REVEAL_PHASES.settleEnd).toBeLessThan(1)
    for (let i = 0; i < 5; i++) {
      expect(segmentOpacity(REVEAL_PHASES.settleEnd, i, 5)).toBe(1)
    }
  })

  it('front-loads the bands so no more than half the pin is spent on blank text', () => {
    expect(REVEAL_PHASES.enterEnd).toBeLessThan(REVEAL_PHASES.flightEnd)
    expect(REVEAL_PHASES.flightEnd).toBeLessThanOrEqual(0.5)
    // The first word lands before the midpoint of the scrub.
    const anyVisibleAtHalf = [0, 1, 2, 3, 4].some((i) => segmentOpacity(0.5, i, 5) > 0)
    expect(anyVisibleAtHalf).toBe(true)
  })

  it('shuffleOrder returns a permutation of 0..count-1', () => {
    const order = shuffleOrder(5, () => 0.5)
    expect([...order].sort((a, b) => a - b)).toEqual([0, 1, 2, 3, 4])
  })

  it('shuffleOrder is deterministic for a given rand function', () => {
    const seq = [0.1, 0.9, 0.2, 0.8, 0.3]
    let i = 0
    const rand = () => seq[i++ % seq.length]
    const a = shuffleOrder(5, rand)
    i = 0
    const b = shuffleOrder(5, rand)
    expect(a).toEqual(b)
  })
})
