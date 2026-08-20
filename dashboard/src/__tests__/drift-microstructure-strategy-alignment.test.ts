import { describe, expect, it } from 'vitest'

/**
 * Logic mirror of DriftView strategy activation and primary selection.
 * Directly verifies the mathematical invariants required to eliminate contradictions.
 */
function evaluateDriftStrategies(params: {
  spot: number | null
  callWall: number | null
  putWall: number | null
  gammaFlip: number | null
  netGex: number | null
  netCharmFlow: number | null
  /** Gross charm magnitude (sum of per-strike |flow|). Defaults to |net|. */
  absCharmFlow?: number | null
  pressureImbalance: number
  expectedMove?: number
}) {
  const spotVal = params.spot
  const cw = params.callWall
  const pw = params.putWall
  const flip = params.gammaFlip
  const gex = params.netGex ?? 0
  const charm = params.netCharmFlow ?? 0
  // Scale-free: net charm flow is shares/day and scales with open interest, so
  // an absolute cutoff fires on every liquid symbol and never on an illiquid one.
  const grossCharm = params.absCharmFlow ?? Math.abs(charm)
  const charmRatio = grossCharm > 0 ? charm / grossCharm : 0
  const CHARM_ONE_SIDED = 0.2
  const imb = params.pressureImbalance

  // Structural breakdown takes precedence (mirrors microstructureAssessment ordering)
  const structuralBreakdown =
    (pw != null && spotVal != null && spotVal <= pw) ||
    (flip != null && spotVal != null && spotVal < flip && gex < 0)

  const s1Active =
    gex >= 0 &&
    spotVal != null &&
    pw != null &&
    cw != null &&
    spotVal >= pw &&
    spotVal <= cw &&
    Math.abs(imb) <= 0.25

  const s2Active =
    !structuralBreakdown &&
    ((cw != null && spotVal != null && spotVal >= cw) ||
      (imb > 0.25 && (cw == null || (spotVal != null && spotVal < cw))) ||
      (charmRatio <= -CHARM_ONE_SIDED && gex >= 0))

  const s3Active = structuralBreakdown || imb < -0.25

  const strategies = [
    { id: 'strat-1', title: 'Strategy 1: Mean-Reversion Channeling', isActive: s1Active, directionType: 'range' },
    { id: 'strat-2', title: 'Strategy 2: Breakout Expansion & Charm Inflow', isActive: s2Active, directionType: 'buying' },
    { id: 'strat-3', title: 'Strategy 3: Breakdown Expansion Below Key Support', isActive: s3Active, directionType: 'selling' },
  ]

  let primary = strategies[0]
  if (strategies[2].isActive) primary = strategies[2]
  else if (strategies[0].isActive) primary = strategies[0]
  else if (strategies[1].isActive) primary = strategies[1]

  return {
    structuralBreakdown,
    s1Active,
    s2Active,
    s3Active,
    primaryStrategy: primary,
  }
}

describe('Drift Strategy and Microstructure Alignment', () => {
  it('CBRS scenario: spot < flip in negative GEX resolves to Strategy 3 (SHORT BIAS) despite positive gauge imbalance', () => {
    // Exact parameters from CBRS prompt
    const res = evaluateDriftStrategies({
      spot: 210.40,
      putWall: 200.0,
      callWall: 220.0,
      gammaFlip: 227.0, // spot (210.40) < flip (227.0)
      netGex: -7.0,     // negative GEX
      netCharmFlow: -26682,
      pressureImbalance: 0.86, // buying pressure gauge
    })

    expect(res.structuralBreakdown).toBe(true)
    expect(res.s2Active).toBe(false) // s2 LONG must be suppressed
    expect(res.s3Active).toBe(true)  // s3 SHORT is triggered
    expect(res.primaryStrategy.id).toBe('strat-3')
    expect(res.primaryStrategy.directionType).toBe('selling')
  })

  it('spot below Put Wall triggers Strategy 3 (SHORT) regardless of gauge', () => {
    const res = evaluateDriftStrategies({
      spot: 195.0,
      putWall: 200.0,
      callWall: 220.0,
      gammaFlip: 210.0,
      netGex: 5.0,
      netCharmFlow: -5000,
      pressureImbalance: 0.5,
    })

    expect(res.structuralBreakdown).toBe(true)
    expect(res.s2Active).toBe(false)
    expect(res.s3Active).toBe(true)
    expect(res.primaryStrategy.id).toBe('strat-3')
  })

  it('spot above Call Wall triggers Strategy 2 (LONG / Breakout)', () => {
    const res = evaluateDriftStrategies({
      spot: 225.0,
      putWall: 200.0,
      callWall: 220.0,
      gammaFlip: 210.0,
      netGex: 5.0,
      netCharmFlow: 1000,
      pressureImbalance: 0.4,
    })

    expect(res.structuralBreakdown).toBe(false)
    expect(res.s2Active).toBe(true)
    expect(res.primaryStrategy.id).toBe('strat-2')
    expect(res.primaryStrategy.directionType).toBe('buying')
  })

  it('spot bounded between walls with positive GEX and balanced pressure triggers Strategy 1 (Range)', () => {
    const res = evaluateDriftStrategies({
      spot: 210.0,
      putWall: 200.0,
      callWall: 220.0,
      gammaFlip: 205.0,
      netGex: 12.0,
      netCharmFlow: 500,
      pressureImbalance: 0.05,
    })

    expect(res.structuralBreakdown).toBe(false)
    expect(res.s1Active).toBe(true)
    expect(res.s2Active).toBe(false)
    expect(res.s3Active).toBe(false)
    expect(res.primaryStrategy.id).toBe('strat-1')
    expect(res.primaryStrategy.directionType).toBe('range')
  })

  // --- scale-free charm threshold regressions -------------------------------
  // Net charm flow is shares/day and scales with the chain's open interest. The
  // old absolute cutoffs (charm < -2000 for strategies, ±1500 for the
  // microstructure read) therefore fired on essentially every liquid symbol and
  // never on an illiquid one. Both directions are pinned below.

  it('does NOT call a mega-cap one-sided when net charm is a small share of gross', () => {
    // -3M shares/day looks enormous in absolute terms and trips the old
    // `charm < -2000` rule instantly — but it is only 5% of this chain's gross
    // charm flow, i.e. an essentially two-sided book.
    const res = evaluateDriftStrategies({
      spot: 210.0,
      putWall: 200.0,
      callWall: 220.0,
      gammaFlip: 205.0,
      netGex: 12.0,
      netCharmFlow: -3_000_000,
      absCharmFlow: 60_000_000,
      pressureImbalance: 0.05,
    })

    expect(res.s2Active).toBe(false)
    // Balanced book inside the walls in positive gamma is the range regime.
    expect(res.s1Active).toBe(true)
    expect(res.primaryStrategy.id).toBe('strat-1')
  })

  it('DOES call an illiquid name one-sided when net charm dominates its gross', () => {
    // -800 shares/day never reached the old -2000 cutoff, so a genuinely
    // one-sided small-cap book (80% of gross pointing one way) was ignored.
    const res = evaluateDriftStrategies({
      spot: 210.0,
      putWall: 200.0,
      callWall: 220.0,
      gammaFlip: 205.0,
      netGex: 12.0,
      netCharmFlow: -800,
      absCharmFlow: 1_000,
      pressureImbalance: 0.05,
    })

    // s2's charm branch is what this pins. (Primary selection still prefers the
    // range strategy here, since spot is inside the walls in positive gamma —
    // that ordering is asserted separately above.)
    expect(res.s2Active).toBe(true)
  })

  it('treats a chain with no measurable charm as neutral, not as a signal', () => {
    // Every contract skipped -> gross 0. Must not divide by zero or fabricate
    // a direction from a 0/0 ratio.
    const res = evaluateDriftStrategies({
      spot: 210.0,
      putWall: 200.0,
      callWall: 220.0,
      gammaFlip: 205.0,
      netGex: 12.0,
      netCharmFlow: 0,
      absCharmFlow: 0,
      pressureImbalance: 0.05,
    })

    expect(res.s2Active).toBe(false)
    expect(res.s3Active).toBe(false)
    expect(res.s1Active).toBe(true)
  })
})
