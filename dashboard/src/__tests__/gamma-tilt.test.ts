/**
 * Behavioural tests for gammaTilt.ts.
 *
 * riskNeutralDensity.ts is being built by another worker in parallel and may
 * not exist yet, so it is mocked here per the dispatch instructions. The
 * mock is not a canned stub — it computes a real lognormal risk-neutral
 * density from the smile's average IV (a standard Black-Scholes terminal
 * distribution), so that when gammaTilt.ts rescales the smile's IVs by
 * volScale before calling it, the returned density's width genuinely
 * changes. That lets the width/shift assertions below exercise the real
 * mechanism (IV rescale -> reprice -> Esscher tilt -> renormalize) rather
 * than asserting against a fixed shape.
 */
import { describe, expect, it, vi } from 'vitest'
import type {
  RegimeState,
  RiskNeutralResult,
  Smile,
  SmilePoint,
  TiltParams,
} from '@/regimeContracts'
import type { CharmSummary } from '@/api'

function buildLognormalGrid(smile: Smile, gridPoints: number, widthSigma: number) {
  const avgIv = smile.points.reduce((sum, p) => sum + p.iv, 0) / smile.points.length
  const sigma = Math.max(avgIv, 1e-6)
  const T = Math.max(smile.tYears, 1e-6)
  const spot = smile.spot
  const sd = sigma * Math.sqrt(T)
  const lo = -widthSigma * sd
  const hi = widthSigma * sd
  const strikes: number[] = []
  const density: number[] = []
  const mu = -0.5 * sigma * sigma * T // risk-neutral drift term (r=0 for test simplicity)
  for (let i = 0; i < gridPoints; i++) {
    const frac = i / (gridPoints - 1)
    const logM = lo + frac * (hi - lo)
    const k = spot * Math.exp(logM)
    const d = (Math.log(k / spot) - mu) / sd
    const pdf = Math.exp(-0.5 * d * d) / (k * sigma * Math.sqrt(2 * Math.PI * T))
    strikes.push(k)
    density.push(pdf)
  }
  // Renormalize by trapezoidal integration so the mock's own output
  // integrates to 1 despite grid discretization — mirrors what a real
  // Breeden-Litzenberger implementation is expected to guarantee.
  let mass = 0
  for (let i = 1; i < strikes.length; i++) {
    mass += ((strikes[i] - strikes[i - 1]) * (density[i] + density[i - 1])) / 2
  }
  return { strikes, density: density.map((v) => v / mass) }
}

vi.mock('@/riskNeutralDensity', () => ({
  riskNeutralDensity: vi.fn(
    (
      smile: Smile | null,
      opts?: { gridPoints?: number; widthSigma?: number },
    ): RiskNeutralResult => {
      if (!smile || smile.points.length === 0) {
        return { grid: null, clippedMass: 0, unavailableReason: 'no smile' }
      }
      // A fine grid matters here: the pin-pull test resolves a sub-percent
      // shift in the argmax between two pinPull strengths, which a coarse
      // grid would quantize away entirely (verified empirically — 241
      // points collapses both cases to the same grid index).
      const { strikes, density } = buildLognormalGrid(
        smile,
        opts?.gridPoints ?? 2001,
        opts?.widthSigma ?? 5,
      )
      return {
        grid: { strikes, density, spot: smile.spot, tYears: smile.tYears, kind: 'risk-neutral' },
        clippedMass: 0,
        unavailableReason: null,
      }
    },
  ),
}))

// Import after the mock so gammaTilt.ts picks up the mocked module.
import {
  applyTilt,
  deriveTilt,
  GAMMA_NORMALIZATION_M,
  SLOPE_NORMALIZATION_M,
  regimeProbabilities,
} from '@/gammaTilt'

const SPOT = 100

function makeSmile(overrides: Partial<Smile> = {}): Smile {
  const strikes = [70, 80, 90, 95, 100, 105, 110, 120, 130]
  const points: SmilePoint[] = strikes.map((strike) => ({
    strike,
    logMoneyness: Math.log(strike / SPOT),
    iv: 0.22, // flat smile keeps the mock's average-IV shortcut exact
  }))
  return {
    points,
    spot: SPOT,
    tYears: 30 / 365,
    riskFreeRate: 0,
    expiry: '2026-09-25',
    observedStrikes: strikes.length,
    windowHalfWidth: 0.4,
    strikesDropped: 0,
    ...overrides,
  }
}

function makeState(overrides: Partial<RegimeState> = {}): RegimeState {
  return {
    netGammaM: 0,
    gammaSlope: 0,
    distanceToFlip: 0.01,
    regime: 'short',
    flipBandPct: 0.002,
    spot: SPOT,
    zeroGamma: SPOT,
    pinStrike: null,
    callWall: 115,
    putWall: 85,
    measurable: true,
    // null by default so existing tests exercise the GAMMA_NORMALIZATION_M /
    // SLOPE_NORMALIZATION_M fallback path; the scale-invariance tests below
    // set these explicitly to exercise the profile-derived path instead.
    gammaScaleM: null,
    slopeScaleM: null,
    ...overrides,
  }
}

function makeCharm(overrides: Partial<CharmSummary> = {}): CharmSummary {
  return {
    net_charm_flow: 0,
    call_charm_flow: 0,
    put_charm_flow: 0,
    abs_charm_flow: 0,
    contracts_measured: 100,
    contracts_skipped: 0,
    pressure: 'balanced',
    source: 'test',
    ...overrides,
  }
}

function trapezoid(xs: number[], ys: number[]): number {
  let sum = 0
  for (let i = 1; i < xs.length; i++) {
    sum += ((xs[i] - xs[i - 1]) * (ys[i] + ys[i - 1])) / 2
  }
  return sum
}

describe('deriveTilt', () => {
  it('returns identity tilt when regime is unmeasurable, even with strong inputs', () => {
    const state = makeState({ regime: 'unmeasurable', netGammaM: -800, gammaSlope: 400 })
    const charm = makeCharm({ net_charm_flow: 500, abs_charm_flow: 500 })
    const tilt = deriveTilt(state, charm, 0.1)
    expect(tilt.volScale).toBe(1)
    expect(tilt.theta).toBe(0)
    expect(tilt.pinPull).toBe(0)
    expect(tilt.constants).toEqual({ lambda: 0.35, kappa: 0.25 })
  })

  it('produces volScale > 1 for short gamma and < 1 for long gamma, both clamped to [0.6, 1.8]', () => {
    const shortTilt = deriveTilt(
      makeState({ regime: 'short', netGammaM: -GAMMA_NORMALIZATION_M }),
      null,
      0.5,
    )
    const longTilt = deriveTilt(
      makeState({ regime: 'long', netGammaM: GAMMA_NORMALIZATION_M }),
      null,
      0.5,
    )
    expect(shortTilt.volScale).toBeGreaterThan(1)
    expect(longTilt.volScale).toBeLessThan(1)
    for (const t of [shortTilt, longTilt]) {
      expect(t.volScale).toBeGreaterThanOrEqual(0.6)
      expect(t.volScale).toBeLessThanOrEqual(1.8)
    }
  })

  it('scales pinPull by charm and weights it by (1 - sessionFractionRemaining)', () => {
    const state = makeState({ pinStrike: 100 })
    const charm = makeCharm({ net_charm_flow: 300, abs_charm_flow: 300 })
    const nearClose = deriveTilt(state, charm, 0.1) // 0.9 weight
    const nearOpen = deriveTilt(state, charm, 0.9) // 0.1 weight
    expect(nearClose.pinPull).toBeGreaterThan(nearOpen.pinPull)
    expect(nearClose.pinPull).toBeGreaterThan(0)
    expect(nearClose.pinPull).toBeLessThanOrEqual(1)
  })

  it('pinPull is zero when charm is null, regardless of session fraction', () => {
    const state = makeState({ pinStrike: 100 })
    expect(deriveTilt(state, null, 0.1).pinPull).toBe(0)
    expect(deriveTilt(state, undefined, 0.99).pinPull).toBe(0)
  })

  it('extreme inputs stay inside the documented clamps and never produce NaN', () => {
    for (const regime of ['short', 'long', 'flip'] as const) {
      const state = makeState({
        regime,
        netGammaM: 1e9,
        gammaSlope: -1e9,
        pinStrike: 100,
      })
      const charm = makeCharm({ net_charm_flow: 1e9, abs_charm_flow: 1e9 })
      const tilt = deriveTilt(state, charm, 0.1)
      expect(Number.isFinite(tilt.volScale)).toBe(true)
      expect(Number.isFinite(tilt.theta)).toBe(true)
      expect(Number.isFinite(tilt.pinPull)).toBe(true)
      expect(tilt.volScale).toBeGreaterThanOrEqual(0.6)
      expect(tilt.volScale).toBeLessThanOrEqual(1.8)
      expect(tilt.theta).toBeGreaterThanOrEqual(-3)
      expect(tilt.theta).toBeLessThanOrEqual(3)
      expect(tilt.pinPull).toBeGreaterThanOrEqual(0)
      expect(tilt.pinPull).toBeLessThanOrEqual(1)

      // Also probe negative-extreme netGammaM / positive-extreme slope, and
      // a charm reading with net larger in magnitude than abs (malformed
      // upstream data) to make sure normalization never divides into NaN.
      const flipped = deriveTilt(
        makeState({ regime, netGammaM: -1e9, gammaSlope: 1e9, pinStrike: 100 }),
        makeCharm({ net_charm_flow: -1e9, abs_charm_flow: 0 }),
        0.9,
      )
      expect(Number.isFinite(flipped.volScale)).toBe(true)
      expect(Number.isFinite(flipped.theta)).toBe(true)
      expect(Number.isFinite(flipped.pinPull)).toBe(true)
    }
  })
})

describe('deriveTilt: scale-free normalization (gammaScaleM / slopeScaleM)', () => {
  // This surface's primary universe is SPY/QQQ/IWM and the 11 sector ETFs.
  // Index-scale net gamma runs orders of magnitude above a single name's, so
  // normalizing against a fixed $M constant saturated tanh to ~1.0 for
  // essentially every index reading — volScale pinned at its bound with no
  // discrimination exactly where this tab is pointed most of the time. These
  // tests prove that defect is closed: the same *relative* gamma posture
  // must produce the same volScale/theta regardless of the symbol's absolute
  // gamma scale.

  it('produces identical volScale and theta for the same relative posture at single-name scale and index scale', () => {
    // Single name: profile max ~100 $M, current reading at 80% of that max.
    const singleName = deriveTilt(
      makeState({
        regime: 'short',
        netGammaM: -80,
        gammaScaleM: 100,
        gammaSlope: -60,
        slopeScaleM: 100,
      }),
      null,
      0.5,
    )
    // Index: profile max ~5000 $M (SPY/QQQ-scale), identical 80% relative posture.
    const index = deriveTilt(
      makeState({
        regime: 'short',
        netGammaM: -4000,
        gammaScaleM: 5000,
        gammaSlope: -3000,
        slopeScaleM: 5000,
      }),
      null,
      0.5,
    )
    expect(index.volScale).toBeCloseTo(singleName.volScale, 12)
    expect(index.theta).toBeCloseTo(singleName.theta, 12)
  })

  it('preserves discrimination between two index-scale readings that the old fixed-$M divisor would have both saturated to the same clamp', () => {
    // With the pre-fix fixed divisor (GAMMA_NORMALIZATION_M = 500), both
    // -1000 and -4500 satisfy |netGammaM/500| >> 1, so tanh saturates both
    // to ~-1 and volScale collapses to the same value near its clamp for
    // both — no discrimination between a mild and an extreme index GEX
    // print. Normalizing against the symbol's own gammaScaleM keeps them
    // distinguishable.
    const weakIndex = deriveTilt(
      makeState({ regime: 'short', netGammaM: -1000, gammaScaleM: 5000 }),
      null,
      0.5,
    )
    const strongIndex = deriveTilt(
      makeState({ regime: 'short', netGammaM: -4500, gammaScaleM: 5000 }),
      null,
      0.5,
    )
    expect(strongIndex.volScale).toBeGreaterThan(weakIndex.volScale)
    // Neither sits pinned at the hard clamp (1.8) — there's real headroom,
    // i.e. genuine discrimination rather than two points on a flat
    // saturated wall.
    expect(weakIndex.volScale).toBeLessThan(1.8)
    expect(strongIndex.volScale).toBeLessThan(1.8)
  })

  it('falls back to the fixed constants when gammaScaleM/slopeScaleM are null, zero, or negative', () => {
    const explicitFallback = deriveTilt(
      makeState({
        regime: 'short',
        netGammaM: -300,
        gammaSlope: -150,
        gammaScaleM: GAMMA_NORMALIZATION_M,
        slopeScaleM: SLOPE_NORMALIZATION_M,
      }),
      null,
      0.5,
    )
    for (const badScale of [null, 0, -50]) {
      const viaFallback = deriveTilt(
        makeState({
          regime: 'short',
          netGammaM: -300,
          gammaSlope: -150,
          gammaScaleM: badScale,
          slopeScaleM: badScale,
        }),
        null,
        0.5,
      )
      expect(viaFallback.volScale).toBeCloseTo(explicitFallback.volScale, 12)
      expect(viaFallback.theta).toBeCloseTo(explicitFallback.theta, 12)
    }
  })

  it('extreme index-scale inputs (netGammaM and its own profile scale both huge) stay inside clamps and never produce NaN', () => {
    const tilt = deriveTilt(
      makeState({
        regime: 'short',
        netGammaM: 1e9,
        gammaScaleM: 1e9,
        gammaSlope: -1e9,
        slopeScaleM: 1e9,
      }),
      null,
      0.1,
    )
    expect(Number.isFinite(tilt.volScale)).toBe(true)
    expect(Number.isFinite(tilt.theta)).toBe(true)
    expect(tilt.volScale).toBeGreaterThanOrEqual(0.6)
    expect(tilt.volScale).toBeLessThanOrEqual(1.8)
    expect(tilt.theta).toBeGreaterThanOrEqual(-3)
    expect(tilt.theta).toBeLessThanOrEqual(3)
  })
})

describe('applyTilt', () => {
  it('is a numerical no-op under the identity tilt', async () => {
    const { riskNeutralDensity } = await import('@/riskNeutralDensity')
    const smile = makeSmile()
    const state = makeState()
    const untilted = riskNeutralDensity(smile)
    const identity: TiltParams = {
      volScale: 1,
      theta: 0,
      pinPull: 0,
      constants: { lambda: 0.35, kappa: 0.25 },
    }
    const tilted = applyTilt(smile, identity, state)

    expect(tilted.grid).not.toBeNull()
    expect(untilted.grid).not.toBeNull()
    if (!tilted.grid || !untilted.grid) return

    expect(tilted.grid.strikes).toEqual(untilted.grid.strikes)
    for (let i = 0; i < tilted.grid.density.length; i++) {
      expect(tilted.grid.density[i]).toBeCloseTo(untilted.grid.density[i], 9)
    }
  })

  it('returns null grid with a reason when smile is null', () => {
    const result = applyTilt(
      null,
      { volScale: 1, theta: 0, pinPull: 0, constants: { lambda: 0.35, kappa: 0.25 } },
      makeState(),
    )
    expect(result.grid).toBeNull()
    expect(result.unavailableReason).toBeTruthy()
  })

  it('every tilted density integrates to 1 across a spread of tilts', () => {
    const smile = makeSmile()
    const state = makeState({ pinStrike: 100 })
    const tilts: TiltParams[] = [
      { volScale: 1, theta: 0, pinPull: 0, constants: { lambda: 0.35, kappa: 0.25 } },
      { volScale: 1.25, theta: 1.5, pinPull: 0.4, constants: { lambda: 0.35, kappa: 0.25 } },
      { volScale: 0.75, theta: -1.5, pinPull: 0.8, constants: { lambda: 0.35, kappa: 0.25 } },
      { volScale: 1.8, theta: 3, pinPull: 1, constants: { lambda: 0.35, kappa: 0.25 } },
      { volScale: 0.6, theta: -3, pinPull: 1, constants: { lambda: 0.35, kappa: 0.25 } },
    ]
    for (const tilt of tilts) {
      const result = applyTilt(smile, tilt, state)
      expect(result.grid).not.toBeNull()
      if (!result.grid) continue
      const mass = trapezoid(result.grid.strikes, result.grid.density)
      expect(mass).toBeCloseTo(1, 6)
      expect(result.grid.kind).toBe('tilted')
    }
  })
})

describe('regimeProbabilities: gamma-driven width', () => {
  it('short gamma widens band68 vs the untilted density; long gamma narrows it', async () => {
    const { riskNeutralDensity } = await import('@/riskNeutralDensity')
    const smile = makeSmile()
    // gammaSlope held at 0 so theta stays 0 and only volScale moves — isolates
    // the width effect from the drift effect.
    const shortState = makeState({
      regime: 'short',
      netGammaM: -GAMMA_NORMALIZATION_M,
      gammaSlope: 0,
    })
    const longState = makeState({ regime: 'long', netGammaM: GAMMA_NORMALIZATION_M, gammaSlope: 0 })

    const untilted = riskNeutralDensity(smile)
    expect(untilted.grid).not.toBeNull()
    if (!untilted.grid) return
    const baseline = regimeProbabilities(untilted.grid, makeState({ regime: 'flip' }))

    const shortTilt = deriveTilt(shortState, null, 0.5)
    const longTilt = deriveTilt(longState, null, 0.5)
    const shortResult = applyTilt(smile, shortTilt, shortState)
    const longResult = applyTilt(smile, longTilt, longState)
    expect(shortResult.grid).not.toBeNull()
    expect(longResult.grid).not.toBeNull()
    if (!shortResult.grid || !longResult.grid) return

    const shortProbs = regimeProbabilities(shortResult.grid, shortState)
    const longProbs = regimeProbabilities(longResult.grid, longState)

    expect(baseline.band68).not.toBeNull()
    expect(shortProbs.band68).not.toBeNull()
    expect(longProbs.band68).not.toBeNull()
    if (!baseline.band68 || !shortProbs.band68 || !longProbs.band68) return

    const baselineWidth = baseline.band68.high - baseline.band68.low
    const shortWidth = shortProbs.band68.high - shortProbs.band68.low
    const longWidth = longProbs.band68.high - longProbs.band68.low

    expect(shortWidth).toBeGreaterThan(baselineWidth)
    expect(longWidth).toBeLessThan(baselineWidth)
  })
})

describe('regimeProbabilities: theta-driven drift', () => {
  it('positive theta shifts modalTarget up, negative shifts it down, monotonically', () => {
    const smile = makeSmile()
    const state = makeState({ pinStrike: null })
    const thetas = [-2.5, -1, 0, 1, 2.5]
    const targets = thetas.map((theta) => {
      const tilt: TiltParams = {
        volScale: 1,
        theta,
        pinPull: 0,
        constants: { lambda: 0.35, kappa: 0.25 },
      }
      const result = applyTilt(smile, tilt, state)
      const probs = regimeProbabilities(result.grid, state)
      expect(probs.modalTarget).not.toBeNull()
      return probs.modalTarget as number
    })
    for (let i = 1; i < targets.length; i++) {
      expect(targets[i]).toBeGreaterThan(targets[i - 1])
    }
  })
})

describe('regimeProbabilities: pinPull-driven pinning', () => {
  it('pulls modalTarget toward pinStrike, more strongly at low sessionFractionRemaining', () => {
    const smile = makeSmile()
    const pinStrike = 112 // above spot, inside the grid but off the untilted mode
    const state = makeState({ regime: 'short', netGammaM: 0, gammaSlope: 0, pinStrike })
    const charm = makeCharm({ net_charm_flow: 400, abs_charm_flow: 400 })

    const tiltNearClose = deriveTilt(state, charm, 0.1)
    const tiltNearOpen = deriveTilt(state, charm, 0.9)

    const resultNearClose = applyTilt(smile, tiltNearClose, state)
    const resultNearOpen = applyTilt(smile, tiltNearOpen, state)

    const probsNearClose = regimeProbabilities(resultNearClose.grid, state)
    const probsNearOpen = regimeProbabilities(resultNearOpen.grid, state)

    expect(probsNearClose.modalTarget).not.toBeNull()
    expect(probsNearOpen.modalTarget).not.toBeNull()
    if (probsNearClose.modalTarget == null || probsNearOpen.modalTarget == null) return

    const distNearClose = Math.abs(probsNearClose.modalTarget - pinStrike)
    const distNearOpen = Math.abs(probsNearOpen.modalTarget - pinStrike)

    // Stronger pull (near close) must land closer to the pin than the
    // weaker pull (near open).
    expect(distNearClose).toBeLessThan(distNearOpen)
  })
})

describe('regimeProbabilities: unmeasurable regime', () => {
  it('returns all-null probabilities regardless of grid content', async () => {
    const { riskNeutralDensity } = await import('@/riskNeutralDensity')
    const smile = makeSmile()
    const untilted = riskNeutralDensity(smile)
    const probs = regimeProbabilities(untilted.grid, makeState({ regime: 'unmeasurable' }))
    expect(probs.probAboveCallWall).toBeNull()
    expect(probs.probBelowPutWall).toBeNull()
    expect(probs.probBetweenWalls).toBeNull()
    expect(probs.modalTarget).toBeNull()
    expect(probs.expectedMove).toBeNull()
    expect(probs.band68).toBeNull()
  })

  it('returns all-null probabilities when grid is null', () => {
    const probs = regimeProbabilities(null, makeState({ regime: 'short' }))
    expect(probs.band68).toBeNull()
    expect(probs.modalTarget).toBeNull()
  })
})

describe('regimeProbabilities: wall integrals', () => {
  it('probAboveCallWall + probBelowPutWall + probBetweenWalls sums to ~1', async () => {
    const { riskNeutralDensity } = await import('@/riskNeutralDensity')
    const smile = makeSmile()
    const untilted = riskNeutralDensity(smile)
    expect(untilted.grid).not.toBeNull()
    if (!untilted.grid) return
    const state = makeState({ callWall: 115, putWall: 85, regime: 'flip' })
    const probs = regimeProbabilities(untilted.grid, state)
    expect(probs.probAboveCallWall).not.toBeNull()
    expect(probs.probBelowPutWall).not.toBeNull()
    expect(probs.probBetweenWalls).not.toBeNull()
    if (
      probs.probAboveCallWall == null ||
      probs.probBelowPutWall == null ||
      probs.probBetweenWalls == null
    )
      return
    const total = probs.probAboveCallWall + probs.probBelowPutWall + probs.probBetweenWalls
    expect(total).toBeCloseTo(1, 6)
    expect(probs.probAboveCallWall).toBeGreaterThan(0)
    expect(probs.probBelowPutWall).toBeGreaterThan(0)
  })
})
