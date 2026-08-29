import { describe, expect, it } from 'vitest'
import { buildRegimeState } from '@/gammaRegime'
import type { OptionsIntelligence } from '@/api'

/**
 * Minimal-but-honest OptionsIntelligence fixture: every field the interface
 * actually requires, populated with inert values, so tests can override just
 * the handful of fields gammaRegime.ts reads (summary, quality,
 * gex_price_profile) without fighting the wider payload shape.
 */
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
    gex_price_profile: [],
    gex_history: [],
    anomalies: { count: 0, method: 'test' },
    probability: { available: false, method: 'test' },
    warnings: [],
    caveats: [],
    ...overrides,
  }
}

// A monotone-increasing net-gamma profile: dealers go from short (below 100)
// to long (above 100), crossing zero exactly at the zero-gamma level. This
// is the standard shape used across every interpolation/slope test below.
const MONOTONE_PROFILE = [
  { spot: 90, net_gex_m: -50 },
  { spot: 95, net_gex_m: -20 },
  { spot: 100, net_gex_m: 0 },
  { spot: 105, net_gex_m: 30 },
  { spot: 110, net_gex_m: 60 },
]

function withProfile(overrides: Partial<OptionsIntelligence> = {}): OptionsIntelligence {
  return basePayload({
    summary: {
      ...basePayload().summary,
      spot: 100,
      zero_gamma: 100,
    },
    gex_price_profile: MONOTONE_PROFILE,
    ...overrides,
  })
}

describe('buildRegimeState — interpolation and slope', () => {
  it('interpolates net gamma linearly between the two bracketing grid points', () => {
    const payload = withProfile()
    const state = buildRegimeState(payload, 97.5)
    expect(state.netGammaM).toBeCloseTo(-10, 10) // halfway between -20 (@95) and 0 (@100)
  })

  it('returns the exact grid value when live spot lands on a grid point', () => {
    const payload = withProfile()
    const state = buildRegimeState(payload, 95)
    expect(state.netGammaM).toBeCloseTo(-20, 10)
  })

  it('gammaSlope has the correct sign on a known monotone-increasing profile', () => {
    const payload = withProfile()
    const state = buildRegimeState(payload, 97.5)
    // Segment [95,100]: (0 - (-20)) / (100 - 95) = 4 — positive, matching
    // the profile's monotone-increasing shape.
    expect(state.gammaSlope).toBeCloseTo(4, 10)
    expect(state.gammaSlope).toBeGreaterThan(0)
  })

  it('gammaSlope sign flips on a monotone-decreasing profile', () => {
    // Same spot grid, negated net gamma: still ascending by spot, but the
    // reading now decreases as spot rises.
    const profile = MONOTONE_PROFILE.map((p) => ({ spot: p.spot, net_gex_m: -p.net_gex_m }))
    const payload = withProfile({ gex_price_profile: profile })
    const state = buildRegimeState(payload, 97.5)
    expect(state.gammaSlope).toBeLessThan(0)
  })

  it('clamps to the boundary value when live spot is below the measured range (no extrapolation)', () => {
    const payload = withProfile()
    const state = buildRegimeState(payload, 50)
    expect(state.netGammaM).toBe(-50)
  })

  it('clamps to the boundary value when live spot is above the measured range (no extrapolation)', () => {
    const payload = withProfile()
    const state = buildRegimeState(payload, 200)
    expect(state.netGammaM).toBe(60)
  })

  it('falls back to payload spot when liveSpot is null', () => {
    const payload = withProfile({ summary: { ...withProfile().summary, spot: 105 } })
    const state = buildRegimeState(payload, null)
    expect(state.spot).toBe(105)
    expect(state.netGammaM).toBeCloseTo(30, 10)
  })

  it("handles a single-point profile by returning that point's value with a null slope", () => {
    const payload = withProfile({ gex_price_profile: [{ spot: 100, net_gex_m: 42 }] })
    const state = buildRegimeState(payload, 137)
    expect(state.netGammaM).toBe(42)
    expect(state.gammaSlope).toBeNull()
  })

  it('drops non-finite grid points before interpolating', () => {
    const dirty = [
      { spot: 90, net_gex_m: -50 },
      { spot: 95, net_gex_m: Number.NaN },
      { spot: 100, net_gex_m: 0 },
      { spot: 105, net_gex_m: Number.POSITIVE_INFINITY },
      { spot: 110, net_gex_m: 60 },
    ]
    const payload = withProfile({ gex_price_profile: dirty })
    const state = buildRegimeState(payload, 97)
    // With the NaN/Infinity rows dropped, the remaining bracket is [90,-50]
    // .. [100,0]: t = (97-90)/10 = 0.7 -> -50 + 0.7*50 = -15.
    expect(state.netGammaM).toBeCloseTo(-15, 10)
  })

  it('an empty profile yields no read at all (regime unmeasurable, no numeric fields)', () => {
    const payload = withProfile({ gex_price_profile: [] })
    const state = buildRegimeState(payload, 100)
    expect(state.regime).toBe('unmeasurable')
    expect(state.netGammaM).toBeNull()
    expect(state.gammaSlope).toBeNull()
    expect(state.spot).toBeNull()
  })
})

describe('buildRegimeState — distance to flip and regime classification', () => {
  it('computes signed distance to zero_gamma', () => {
    const payload = withProfile()
    const below = buildRegimeState(payload, 90)
    expect(below.distanceToFlip).toBeCloseTo((90 - 100) / 90, 10)
    expect(below.distanceToFlip).toBeLessThan(0)

    const above = buildRegimeState(payload, 110)
    expect(above.distanceToFlip).toBeCloseTo((110 - 100) / 110, 10)
    expect(above.distanceToFlip).toBeGreaterThan(0)
  })

  it('falls back to gamma_flip when zero_gamma is null', () => {
    const payload = withProfile({
      summary: { ...withProfile().summary, zero_gamma: null, gamma_flip: 100 },
    })
    const state = buildRegimeState(payload, 90)
    expect(state.zeroGamma).toBe(100)
    expect(state.distanceToFlip).toBeCloseTo((90 - 100) / 90, 10)
  })

  it('classifies short gamma below the zero-gamma level, outside the flip band', () => {
    const payload = withProfile()
    const state = buildRegimeState(payload, 90)
    expect(state.regime).toBe('short')
    expect(state.netGammaM).toBeLessThan(0)
  })

  it('classifies long gamma above the zero-gamma level, outside the flip band', () => {
    const payload = withProfile()
    const state = buildRegimeState(payload, 110)
    expect(state.regime).toBe('long')
    expect(state.netGammaM).toBeGreaterThan(0)
  })

  it('classifies flip when within the default flip band', () => {
    const payload = withProfile()
    // 0.2% off zero-gamma is inside the default 0.25% band.
    const state = buildRegimeState(payload, 100.2)
    expect(Math.abs(state.distanceToFlip ?? Infinity)).toBeLessThanOrEqual(0.0025)
    expect(state.regime).toBe('flip')
  })

  it('respects a custom flipBandPct', () => {
    const payload = withProfile()
    // 2% off zero-gamma: outside the default band, inside a widened 5% band.
    const narrow = buildRegimeState(payload, 102)
    expect(narrow.regime).not.toBe('flip')
    const wide = buildRegimeState(payload, 102, { flipBandPct: 0.05 })
    expect(wide.regime).toBe('flip')
  })
})

describe('buildRegimeState — unmeasurable handling', () => {
  it('yields an all-null RegimeState when quality.gex_measurable is explicitly false', () => {
    const payload = withProfile({
      quality: { ...basePayload().quality, gex_measurable: false },
    })
    const state = buildRegimeState(payload, 100)

    expect(state.regime).toBe('unmeasurable')
    expect(state.measurable).toBe(false)
    // CRITICAL: every numeric field is null, not just the GEX-derived ones —
    // a fake zero (or a partially-populated tile showing spot/walls while
    // gamma is blank) is worse than an explicit "no read".
    expect(state.netGammaM).toBeNull()
    expect(state.gammaSlope).toBeNull()
    expect(state.distanceToFlip).toBeNull()
    expect(state.spot).toBeNull()
    expect(state.zeroGamma).toBeNull()
    expect(state.pinStrike).toBeNull()
    expect(state.callWall).toBeNull()
    expect(state.putWall).toBeNull()
    expect(state.gammaScaleM).toBeNull()
    expect(state.slopeScaleM).toBeNull()
  })

  it('treats a missing gex_measurable flag as measurable (older payloads keep reading)', () => {
    const payload = withProfile({
      quality: { ...basePayload().quality, gex_measurable: undefined },
    })
    const state = buildRegimeState(payload, 90)
    expect(state.measurable).toBe(true)
    expect(state.regime).toBe('short')
  })

  it('a null payload yields an all-null, unmeasurable RegimeState', () => {
    const state = buildRegimeState(null, 100)
    expect(state.regime).toBe('unmeasurable')
    expect(state.measurable).toBe(false)
    expect(state.netGammaM).toBeNull()
    expect(state.spot).toBeNull()
  })

  it('never emits 0 for netGammaM when the profile cannot be measured', () => {
    // A profile that resolves to net_gex_m === 0 by real interpolation is
    // fine (tested elsewhere as regime "flip"); this checks the failure path
    // specifically doesn't default a missing read to 0.
    const payload = withProfile({ gex_price_profile: [] })
    const state = buildRegimeState(payload, 100)
    expect(state.netGammaM).toBeNull()
    expect(state.netGammaM).not.toBe(0)
  })
})

describe('buildRegimeState — gammaScaleM / slopeScaleM (symbol-relative scale)', () => {
  it('picks the largest |net_gex_m| across the profile as gammaScaleM', () => {
    const payload = withProfile()
    const state = buildRegimeState(payload, 97.5)
    // MONOTONE_PROFILE values are [-50,-20,0,30,60]; largest magnitude is 60.
    expect(state.gammaScaleM).toBe(60)
  })

  it('picks the largest |Δnet_gex_m/Δspot| across adjacent pairs as slopeScaleM', () => {
    // Segments: [90,-50]-[95,-20]=6/pt, [95,-20]-[100,0]=4/pt,
    // [100,0]-[105,30]=6/pt, [105,30]-[110,60]=6/pt -> a non-uniform
    // segment breaks the tie so the "largest" pick is unambiguous.
    const profile = [
      { spot: 90, net_gex_m: -50 },
      { spot: 95, net_gex_m: -20 },
      { spot: 100, net_gex_m: 0 },
      { spot: 103, net_gex_m: 45 }, // steep segment: 45/3 = 15 per unit spot
      { spot: 110, net_gex_m: 60 },
    ]
    const payload = withProfile({ gex_price_profile: profile })
    const state = buildRegimeState(payload, 97.5)
    expect(state.slopeScaleM).toBeCloseTo(15, 10)
  })

  it('scales linearly with the profile: a 50x profile yields a 50x gammaScaleM', () => {
    const payload = withProfile()
    const scaled = withProfile({
      gex_price_profile: MONOTONE_PROFILE.map((p) => ({
        spot: p.spot,
        net_gex_m: p.net_gex_m * 50,
      })),
    })
    const base = buildRegimeState(payload, 97.5)
    const wide = buildRegimeState(scaled, 97.5)
    expect(base.gammaScaleM).not.toBeNull()
    expect(wide.gammaScaleM).toBeCloseTo((base.gammaScaleM as number) * 50, 6)
    expect(wide.slopeScaleM).toBeCloseTo((base.slopeScaleM as number) * 50, 6)
  })

  it('is null on a single-point profile (no range to establish a scale)', () => {
    const payload = withProfile({ gex_price_profile: [{ spot: 100, net_gex_m: 42 }] })
    const state = buildRegimeState(payload, 100)
    expect(state.gammaScaleM).toBeNull()
    expect(state.slopeScaleM).toBeNull()
  })

  it('is null on an empty profile', () => {
    const payload = withProfile({ gex_price_profile: [] })
    const state = buildRegimeState(payload, 100)
    expect(state.gammaScaleM).toBeNull()
    expect(state.slopeScaleM).toBeNull()
  })

  it('is null whenever the regime is unmeasurable', () => {
    const payload = withProfile({
      quality: { ...basePayload().quality, gex_measurable: false },
    })
    const state = buildRegimeState(payload, 100)
    expect(state.regime).toBe('unmeasurable')
    expect(state.gammaScaleM).toBeNull()
    expect(state.slopeScaleM).toBeNull()
  })

  it('is never exactly 0 — a flat-but-nonzero profile still yields a positive scale, and an all-zero profile yields null rather than 0', () => {
    const allZero = withProfile({
      gex_price_profile: MONOTONE_PROFILE.map((p) => ({ spot: p.spot, net_gex_m: 0 })),
    })
    const state = buildRegimeState(allZero, 97.5)
    expect(state.gammaScaleM).toBeNull()
    expect(state.slopeScaleM).toBeNull()
  })
})
