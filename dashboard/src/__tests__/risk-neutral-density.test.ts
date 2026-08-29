import { describe, expect, it } from 'vitest'
import { buildSmile, riskNeutralDensity } from '@/riskNeutralDensity'
import type { IvStrikeRow, OptionsIntelligence, StackedSignals } from '@/api'
import type { Smile, SmilePoint } from '@/regimeContracts'

/** Minimal-but-honest OptionsIntelligence fixture — see gamma-regime.test.ts
 *  for the same pattern; duplicated here so this file has no cross-file
 *  dependency on another test's fixture shape. */
function basePayload(overrides: Partial<OptionsIntelligence> = {}): OptionsIntelligence {
  return {
    schema_version: 'test',
    symbol: 'TEST',
    mode_requested: 'live',
    mode_resolved: 'live',
    asof_utc: '2026-08-27T00:00:00Z',
    observed_at: '2026-08-27T00:00:00Z',
    freshness: { age_seconds: 1 },
    filters: {},
    chain_context: {
      selection: 'nearest',
      selected_expiry: '2026-09-19',
      selected_dte: 23,
      snapshot_dte: 23,
      selection_asof: '2026-08-27T00:00:00Z',
      available_expiries: [],
    },
    provider: {
      chain: 'test',
      flow: 'test',
      open_interest: 'test',
      activity_basis: 'trade_tape',
      signed_flow_available: true,
    },
    summary: {
      spot: 100,
      call_premium: 0,
      put_premium: 0,
      call_put_ratio: null,
      activity_imbalance: null,
      signed_net_premium: null,
      unresolved_premium: 0,
      total_gex_m: 0,
      regime: 'neutral',
      gamma_flip: null,
      call_wall: null,
      put_wall: null,
      zero_gamma: null,
      pin_strike: null,
    },
    quality: {
      chain_contracts_raw: 0,
      chain_contracts_included: 0,
      chain_rejected: {},
      flow_prints_raw: 0,
      flow_prints_included: 0,
      flow_rejected: {},
      gamma_source: {},
      anomaly_sample_size: 0,
    },
    price_series: [],
    flow_series: [],
    flow_tape: [],
    gex_by_strike: [],
    gex_history: [],
    anomalies: { count: 0, method: 'test' },
    probability: { available: false, method: 'test' },
    warnings: [],
    caveats: [],
    ...overrides,
  }
}

function ivRow(strike: number, callIv: number | null, putIv: number | null): IvStrikeRow {
  return {
    strike,
    call_iv: callIv,
    put_iv: putIv,
    skew: callIv != null && putIv != null ? callIv - putIv : null,
    distance_pct: (strike - 100) / 100,
  }
}

/** Wraps a set of iv_surface rows in an otherwise-empty StackedSignals, so
 *  buildSmile tests only have to spell out the one lens they exercise. */
function stackedSignals(ivSurface: IvStrikeRow[]): StackedSignals {
  return {
    theta_by_strike: [],
    theta_summary: {
      net_theta_flow: 0,
      call_theta_flow: 0,
      put_theta_flow: 0,
      abs_theta_flow: 0,
      decay_side: null,
      source: 'test',
    },
    vanna_summary: {
      net_vanna_flow: 0,
      call_vanna_flow: 0,
      put_vanna_flow: 0,
      regime: null,
      source: 'test',
    },
    iv_surface: ivSurface,
    iv_summary: {
      available: ivSurface.length > 0,
      atm_iv: 0.25,
      peak_call_iv_strike: null,
      peak_put_iv_strike: null,
      call_iv_wall: null,
      put_iv_wall: null,
      method: 'test',
    },
    volume_profile: [],
    volume_profile_summary: { available: false },
    confluence: [],
    quality: {
      theta_vanna_contracts_measured: 0,
      theta_vanna_contracts_skipped: 0,
      iv_strikes_measured: ivSurface.length,
      volume_profile_available: false,
    },
  }
}

function trapezoid(xs: number[], ys: number[]): number {
  let sum = 0
  for (let i = 0; i < xs.length - 1; i++) {
    sum += ((ys[i] + ys[i + 1]) / 2) * (xs[i + 1] - xs[i])
  }
  return sum
}

/** Closed-form Black-Scholes risk-neutral (lognormal) density of S_T, the
 *  exact target Breeden-Litzenberger recovers when the smile genuinely is
 *  flat/constant-vol GBM. This is the independent ground truth the flat-
 *  smile test checks the implementation against. */
function lognormalDensity(K: number, S0: number, sigma: number, T: number, r: number): number {
  const variance = sigma * sigma * T
  const mu = Math.log(S0) + (r - 0.5 * sigma * sigma) * T
  const z = Math.log(K) - mu
  return Math.exp(-(z * z) / (2 * variance)) / (K * Math.sqrt(2 * Math.PI * variance))
}

function flatSmilePoints(
  spot: number,
  iv: number,
  logMoneynessRange: number,
  n: number,
): SmilePoint[] {
  const points: SmilePoint[] = []
  for (let i = 0; i < n; i++) {
    const logMoneyness = -logMoneynessRange + (2 * logMoneynessRange * i) / (n - 1)
    points.push({ logMoneyness, strike: spot * Math.exp(logMoneyness), iv })
  }
  return points
}

describe('riskNeutralDensity — Breeden-Litzenberger correctness (flat smile)', () => {
  const spot = 100
  const sigma = 0.25
  const T = 0.5
  const smile: Smile = {
    points: flatSmilePoints(spot, sigma, 0.7, 15),
    spot,
    tYears: T,
    riskFreeRate: 0,
    expiry: '2027-02-27',
    observedStrikes: 15,
    windowHalfWidth: 0.4,
    strikesDropped: 0,
  }

  it('recovers the closed-form lognormal density to within 2% in the central region', () => {
    const result = riskNeutralDensity(smile)
    expect(result.unavailableReason).toBeNull()
    expect(result.grid).not.toBeNull()
    const { strikes, density } = result.grid!

    // Central region: strikes within ~15% of spot, comfortably inside the
    // observed smile range and away from the grid's own tail truncation.
    const centralIndices = strikes.map((k, i) => ({ k, i })).filter(({ k }) => k >= 85 && k <= 115)
    expect(centralIndices.length).toBeGreaterThan(20) // sanity: grid resolution actually covers this band

    for (const { k, i } of centralIndices) {
      const expected = lognormalDensity(k, spot, sigma, T, 0)
      const actual = density[i]
      const relError = Math.abs(actual - expected) / expected
      expect(relError, `strike ${k}: expected ${expected}, got ${actual}`).toBeLessThan(0.02)
    }
  })

  it('integrates to 1 over the full grid', () => {
    const result = riskNeutralDensity(smile)
    const { strikes, density } = result.grid!
    const mass = trapezoid(strikes, density)
    expect(mass).toBeCloseTo(1, 6)
  })

  it('clips negligible or no negative mass on a smooth, noise-free flat smile', () => {
    const result = riskNeutralDensity(smile)
    // A perfectly flat, arbitrage-free input smile should reprice into an
    // essentially non-negative second difference everywhere; only floating-
    // point noise, if anything, should get clipped.
    expect(result.clippedMass).toBeLessThan(0.005)
  })
})

describe('riskNeutralDensity — skewed smile produces asymmetric tails', () => {
  it('negative (put) skew puts more mass in the left tail than the right', () => {
    const spot = 100
    const T = 0.5
    // Linear vol skew in log-moneyness: IV rises for downside (puts), falls
    // for upside (calls) — the standard equity/index "smirk" shape that is
    // known to fatten the downside of the risk-neutral distribution.
    const points: SmilePoint[] = []
    const n = 15
    const range = 0.8
    for (let i = 0; i < n; i++) {
      const m = -range + (2 * range * i) / (n - 1)
      const iv = 0.22 - 0.3 * m
      points.push({ logMoneyness: m, strike: spot * Math.exp(m), iv })
    }
    const smile: Smile = {
      points,
      spot,
      tYears: T,
      riskFreeRate: 0,
      expiry: 'x',
      observedStrikes: n,
      windowHalfWidth: 0.4,
      strikesDropped: 0,
    }

    const result = riskNeutralDensity(smile)
    expect(result.grid).not.toBeNull()
    const { strikes, density } = result.grid!

    // Compare genuine tails (>=20% away from spot on each side), not a
    // simple below/above-spot split. A lognormal's median already sits
    // below spot even with a perfectly FLAT smile (Jensen's inequality on
    // the log transform), so a median split conflates that baseline
    // location effect with skew and is not a clean test of skew itself.
    // Deep out-of-the-money mass is where added put-side IV actually shows
    // up: it widens the left wing specifically, which is what "fatter
    // downside tail" means.
    const cut = 0.2
    const lo = spot * (1 - cut)
    const hi = spot * (1 + cut)
    const leftIdx = strikes.map((_, i) => i).filter((i) => strikes[i] < lo)
    const rightIdx = strikes.map((_, i) => i).filter((i) => strikes[i] > hi)
    const leftTailMass = trapezoid(
      leftIdx.map((i) => strikes[i]),
      leftIdx.map((i) => density[i]),
    )
    const rightTailMass = trapezoid(
      rightIdx.map((i) => strikes[i]),
      rightIdx.map((i) => density[i]),
    )
    expect(leftTailMass).toBeGreaterThan(rightTailMass)
  })
})

describe('riskNeutralDensity — failure paths never throw, always explain', () => {
  it('returns unavailableReason for a null smile', () => {
    const result = riskNeutralDensity(null)
    expect(result.grid).toBeNull()
    expect(result.clippedMass).toBe(0)
    expect(result.unavailableReason).toBe('no smile available')
  })

  it('returns unavailableReason for a smile with fewer than 4 strikes', () => {
    const sparse: Smile = {
      points: [
        { logMoneyness: -0.1, strike: 90, iv: 0.3 },
        { logMoneyness: 0, strike: 100, iv: 0.25 },
        { logMoneyness: 0.1, strike: 110, iv: 0.22 },
      ],
      spot: 100,
      tYears: 0.5,
      riskFreeRate: 0,
      expiry: 'x',
      observedStrikes: 3,
      windowHalfWidth: 0.4,
      strikesDropped: 0,
    }
    const result = riskNeutralDensity(sparse)
    expect(result.grid).toBeNull()
    expect(result.unavailableReason).not.toBeNull()
  })

  it('returns unavailableReason for a non-positive time to expiry', () => {
    const smile: Smile = {
      points: flatSmilePoints(100, 0.25, 0.5, 6),
      spot: 100,
      tYears: 0,
      riskFreeRate: 0,
      expiry: 'x',
      observedStrikes: 6,
      windowHalfWidth: 0.4,
      strikesDropped: 0,
    }
    const result = riskNeutralDensity(smile)
    expect(result.grid).toBeNull()
    expect(result.unavailableReason).not.toBeNull()
  })

  it('never throws on a garbage smile (NaN spot)', () => {
    const smile: Smile = {
      points: flatSmilePoints(100, 0.25, 0.5, 6),
      spot: Number.NaN,
      tYears: 0.5,
      riskFreeRate: 0,
      expiry: 'x',
      observedStrikes: 6,
      windowHalfWidth: 0.4,
      strikesDropped: 0,
    }
    expect(() => riskNeutralDensity(smile)).not.toThrow()
    const result = riskNeutralDensity(smile)
    expect(result.grid).toBeNull()
    expect(result.unavailableReason).not.toBeNull()
  })
})

describe('buildSmile', () => {
  /*
   * Reproduces the live SPY defect. The nearest SPY expiry is frequently 1DTE,
   * where sigma*sqrt(T) is ~1.1%, yet the chain quotes strikes from 500 to 900
   * around a 771 spot. Those far wings are tens of sigmas out, priced in
   * pennies, and their implied vols are bid-ask noise that oscillated
   * 0.93 -> 0.61 -> 0.85 -> 0.57 across ADJACENT strikes in the real payload.
   * Interpolating through that put non-convexity into the repriced call curve
   * and drove ~28% of the density mass negative before clipping.
   */
  it('restricts a wide chain to a window scaled by the horizon', () => {
    const spot = 771
    const noisyWing = [0.93, 0.61, 0.74, 0.85, 0.78, 0.69, 0.57]
    const rows: IvStrikeRow[] = []
    noisyWing.forEach((iv, i) => rows.push(ivRow(500 + i * 5, null, iv)))
    for (let k = 750; k <= 795; k += 5) rows.push(ivRow(k, 0.216, 0.216))
    for (let i = 0; i < 5; i++) rows.push(ivRow(860 + i * 10, 0.7 + i * 0.1, null))

    const payload = basePayload({
      summary: { ...basePayload().summary, spot },
      probability: { available: true, method: 'test', horizon_days: 1, atm_iv: 0.216 },
      stacked_signals: stackedSignals(rows),
    })

    const smile = buildSmile(payload)!
    expect(smile.strikesDropped).toBeGreaterThan(0)
    // 8 * 0.216 * sqrt(1/365) ~= 9%, so nothing 35% out may survive.
    expect(smile.windowHalfWidth).toBeLessThan(0.15)
    const kept = smile.points.map((p) => p.strike)
    expect(Math.min(...kept)).toBeGreaterThan(600)
    expect(Math.max(...kept)).toBeLessThan(900)
    expect(smile.observedStrikes).toBe(smile.points.length)
  })

  it('widens rather than starving the interpolator on a sparse chain', () => {
    // Only 4 usable strikes, all far out. Obeying the horizon window literally
    // would leave PCHIP with too few nodes, which fails harder than a wide
    // window does — so the window yields.
    const spot = 100
    const rows = [
      ivRow(60, null, 0.5),
      ivRow(70, null, 0.45),
      ivRow(130, 0.4, null),
      ivRow(140, 0.42, null),
    ]
    const payload = basePayload({
      summary: { ...basePayload().summary, spot },
      probability: { available: true, method: 'test', horizon_days: 1, atm_iv: 0.2 },
      stacked_signals: stackedSignals(rows),
    })

    const smile = buildSmile(payload)
    expect(smile).not.toBeNull()
    expect(smile!.points.length).toBeGreaterThanOrEqual(4)
  })

  /*
   * Regression guard: buildSmile once hardcoded riskFreeRate to 0 on the belief
   * that no rate reached the payload. It does — the server ships
   * `asdict(OptionsFilters)` as `filters`, carrying the exact rate the chain was
   * priced with. Pricing the smile at 0 while the payload's own Greeks used
   * 0.045 put the Black-Scholes forward S*exp(rT) ~0.37% low over a 30-day
   * horizon, biasing modalTarget down in one direction every time.
   */
  it('prices the smile with the risk-free rate the payload was built with', () => {
    const payload = basePayload({
      summary: { ...basePayload().summary, spot: 100 },
      probability: { available: true, method: 'test', horizon_days: 30 },
      filters: { risk_free_rate: 0.0425 },
      stacked_signals: stackedSignals([
        ivRow(90, 0.3, 0.28),
        ivRow(95, 0.27, 0.26),
        ivRow(100, 0.25, 0.25),
        ivRow(105, 0.23, 0.24),
        ivRow(110, 0.22, 0.23),
      ]),
    })

    expect(buildSmile(payload)!.riskFreeRate).toBeCloseTo(0.0425, 10)
  })

  it('falls back to the server default when the payload rate is absent or out of bounds', () => {
    const smile = (filters: Record<string, number | string | null> | undefined) =>
      buildSmile(
        basePayload({
          summary: { ...basePayload().summary, spot: 100 },
          probability: { available: true, method: 'test', horizon_days: 30 },
          filters,
          stacked_signals: stackedSignals([
            ivRow(90, 0.3, 0.28),
            ivRow(95, 0.27, 0.26),
            ivRow(100, 0.25, 0.25),
            ivRow(105, 0.23, 0.24),
            ivRow(110, 0.22, 0.23),
          ]),
        }),
      )!.riskFreeRate

    expect(smile(undefined)).toBeCloseTo(0.045, 10)
    expect(smile({})).toBeCloseTo(0.045, 10)
    // Outside the server's own -0.05..0.25 guard rails: malformed, not a market
    // condition, so it must never reach pricing.
    expect(smile({ risk_free_rate: 9 })).toBeCloseTo(0.045, 10)
    expect(smile({ risk_free_rate: -1 })).toBeCloseTo(0.045, 10)
    expect(smile({ risk_free_rate: 'oops' })).toBeCloseTo(0.045, 10)
  })

  it('builds a sorted smile from iv_surface, preferring the OTM side per strike', () => {
    const payload = basePayload({
      summary: { ...basePayload().summary, spot: 100 },
      probability: { available: true, method: 'test', horizon_days: 45 },
      stacked_signals: stackedSignals([
        ivRow(80, 0.5, 0.35), // below spot -> should prefer put_iv (0.35)
        ivRow(90, 0.3, 0.28), // below spot -> prefer put_iv (0.28)
        ivRow(100, 0.24, 0.25), // at spot: strike <= spot -> prefer put_iv (0.25)
        ivRow(110, 0.2, 0.4), // above spot -> prefer call_iv (0.2)
        ivRow(120, 0.18, 0.6), // above spot -> prefer call_iv (0.18)
      ]),
    })

    const smile = buildSmile(payload)
    expect(smile).not.toBeNull()
    expect(smile!.observedStrikes).toBe(5)
    expect(smile!.tYears).toBeCloseTo(45 / 365, 10)
    // sorted ascending by log-moneyness (== ascending strike here)
    for (let i = 1; i < smile!.points.length; i++) {
      expect(smile!.points[i].logMoneyness).toBeGreaterThan(smile!.points[i - 1].logMoneyness)
    }
    const byStrike = new Map(smile!.points.map((p) => [p.strike, p.iv]))
    expect(byStrike.get(80)).toBeCloseTo(0.35, 10)
    expect(byStrike.get(90)).toBeCloseTo(0.28, 10)
    expect(byStrike.get(100)).toBeCloseTo(0.25, 10)
    expect(byStrike.get(110)).toBeCloseTo(0.2, 10)
    expect(byStrike.get(120)).toBeCloseTo(0.18, 10)
  })

  it('returns null (sparse chain) when fewer than 4 strikes carry a usable IV', () => {
    const payload = basePayload({
      summary: { ...basePayload().summary, spot: 100 },
      stacked_signals: stackedSignals([
        ivRow(90, 0.3, 0.28),
        ivRow(100, 0.24, 0.25),
        ivRow(110, 0.2, 0.4),
      ]),
    })
    expect(buildSmile(payload)).toBeNull()
  })

  it('returns null when there is no payload', () => {
    expect(buildSmile(null)).toBeNull()
  })

  it('returns null when spot is missing or non-positive', () => {
    const payload = basePayload({ summary: { ...basePayload().summary, spot: 0 } })
    expect(buildSmile(payload)).toBeNull()
  })

  it('falls back to a 30-day horizon when probability.horizon_days is absent', () => {
    const payload = basePayload({
      summary: { ...basePayload().summary, spot: 100 },
      stacked_signals: stackedSignals([
        ivRow(90, 0.3, 0.28),
        ivRow(95, 0.27, 0.26),
        ivRow(100, 0.24, 0.25),
        ivRow(110, 0.2, 0.4),
      ]),
    })
    const smile = buildSmile(payload)
    expect(smile).not.toBeNull()
    expect(smile!.tYears).toBeCloseTo(30 / 365, 10)
  })
})
